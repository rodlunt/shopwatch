"""The price-watch subsystem.

Runnable four ways, all the same code path:

    python -m app.price_watch              # CLI / cron / systemd timer
    POST /api/price-watch/run              # UI button or external automation

For every active listing with an adapter and a URL it fetches the page, normalises it,
writes the fields that are not manually locked, and appends a history observation.

Non-negotiables, each of which has its own test:
  * a fetch failure never destroys the last good value;
  * a manually locked field is never overwritten;
  * one retailer failing does not abort the run;
  * an unresolved value is stored as unresolved, never as zero.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from typing import Any

from . import alerts, pi_events, pi_health, pricing, provenance, retailers, store
from .config import Config, load_config
from .db import migrate, session, utcnow

log = logging.getLogger("shopwatch.price_watch")

#: check_listing status -> summary counter key
STATUS_COUNTER = {"ok": "ok", "unresolved": "unresolved", "skipped": "skipped",
                  "error": "errors"}


def _open_run(conn: sqlite3.Connection, trigger: str) -> int:
    cur = conn.execute(
        "INSERT INTO scrape_runs (started_at, trigger, status) VALUES (?, ?, 'running')",
        (utcnow(), trigger),
    )
    return int(cur.lastrowid)


def _record(
    conn: sqlite3.Connection,
    run_id: int,
    listing_id: int | None,
    status: str,
    message: str,
    payload: Any = None,
) -> None:
    conn.execute(
        "INSERT INTO scrape_results (run_id, listing_id, status, message, payload)"
        " VALUES (?, ?, ?, ?, ?)",
        (run_id, listing_id, status, message, json.dumps(payload) if payload else None),
    )


def check_listing(
    conn: sqlite3.Connection,
    listing: sqlite3.Row,
    product: sqlite3.Row,
    run_id: int,
    config: Config,
) -> str:
    """Check one listing. Returns 'ok', 'unresolved', 'skipped' or 'error'."""
    adapter = retailers.get_adapter(listing["retailer_adapter"])
    if adapter is None:
        _record(conn, run_id, listing["id"], "skipped", "no adapter for this retailer")
        return "skipped"
    if not listing["url"]:
        _record(conn, run_id, listing["id"], "skipped", "listing has no URL")
        return "skipped"

    # Read before anything is written: the previous adapter reading is what a price drop
    # or a back-in-stock is measured against.
    previous = pi_events.previous_observation(conn, listing["id"], adapter.slug)
    before = pricing.delivered_price(
        listing["advertised_price"], listing["freight"], listing["cashback"],
        listing["rebate"], listing["coupon_discount"],
    )

    try:
        if getattr(adapter, "wants_product_name", False):
            observation = adapter.check(listing["url"], product["model"], product["name"])
        else:
            observation = adapter.check(listing["url"], product["model"])
    except retailers.FetchError as exc:
        # Deliberately leaves every stored value alone. The previous reading is still the
        # best information available; an error is not evidence that the price changed.
        _record(conn, run_id, listing["id"], "error", str(exc))
        log.warning("%s: %s", adapter.name, exc)
        return "error"
    except Exception as exc:  # an adapter bug must not abort the whole run
        _record(
            conn, run_id, listing["id"], "error",
            f"adapter crashed: {type(exc).__name__}: {exc}",
        )
        log.exception("adapter %s crashed", adapter.slug)
        return "error"

    values = observation.to_values()
    applied = provenance.apply_values(
        conn, listing["id"], values, state=provenance.LIVE, source=adapter.slug
    )
    conn.execute(
        "UPDATE listings SET last_checked_at = ?, updated_at = ? WHERE id = ?",
        (utcnow(), utcnow(), listing["id"]),
    )
    provenance.sync_verification_from_provenance(conn, listing["id"])

    for warning in observation.warnings:
        _record(conn, run_id, listing["id"], "warning", warning)

    # The note has to be the warning that caused the flag, not warnings[0]. Any adapter
    # appending its own warning first would otherwise file unrelated text under the
    # "model mismatch" fault tag, and the operator reads a reason that has nothing to
    # do with why the listing is flagged.
    mismatch = next((w for w in observation.warnings if "model mismatch" in w), None)
    if mismatch:
        provenance.set_verification(conn, listing["id"], "model", provenance.FLAGGED, mismatch)
    elif observation.model_on_page_key in retailers.MANUFACTURER_KEYS:
        # This run actually compared a manufacturer identifier and it matched, so a
        # flag left by an earlier run is now known to be wrong. Clear it.
        #
        # sync_verification_from_provenance deliberately never touches a FLAGGED
        # aspect, so without this a listing flagged by the old shape-based comparison
        # stays red forever, which is the outcome that fix existed to prevent. The same
        # applied to any one-off bad reading.
        #
        # Only cleared when the check genuinely ran: a page publishing just a merchant
        # stock number gives no evidence either way, and silence is not a clean bill of
        # health (hardening rule 12).
        current = provenance.verification_map(conn, listing["id"])
        if current["model"]["status"] == provenance.FLAGGED:
            provenance.set_verification(
                conn, listing["id"], "model", provenance.LIVE,
                f"cleared: {observation.model_on_page!r} matched on this run",
            )

    _write_availability(conn, listing, observation, applied)
    _track_price_change(conn, listing, before)

    history_id = store.record_observation(conn, listing["id"], source=adapter.slug)
    fresh = conn.execute("SELECT * FROM listings WHERE id = ?", (listing["id"],)).fetchone()
    if pi_events.is_pi(product["category"], config) and observation.availability is not None:
        after = pricing.delivered_price(
            fresh["advertised_price"], fresh["freight"], fresh["cashback"], fresh["rebate"],
            fresh["coupon_discount"],
        )
        pi_events.detect_transitions(
            conn, config, listing=fresh, product_name=product["name"],
            retailer_name=listing["retailer_name"], previous=previous,
            history_id=history_id, new_delivered=after.value,
            new_availability=fresh["availability"],
        )

    payload = {
        "updated": applied["written"],
        "preserved_manual": applied["blocked"],
        "unresolved": observation.unresolved,
        "warnings": observation.warnings,
    }
    status = "ok" if observation.advertised_price is not None else "unresolved"
    message = observation.notes or ""
    if status == "ok" and "advertised_price" in applied["blocked"] and pi_events.is_pi(
        product["category"], config
    ):
        # The page was read but the price could not be stored. For the Pi watch that is a
        # failure, not a success: a green run that changes nothing is the thing to avoid.
        status = "unresolved"
        message = "advertised_price is manually locked, so the watch could not update it"
    _record(conn, run_id, listing["id"], status, message, payload)
    return status


def _write_availability(
    conn: sqlite3.Connection, listing: sqlite3.Row, observation: retailers.Observation,
    applied: dict[str, list[str]],
) -> None:
    """Store the normalised availability and unit limit alongside stock_status.

    They follow stock_status: if a human has locked that field, the normalised value is
    left alone too, or the two would disagree. An availability the adapter could not read
    (unknown) never overwrites the last known one.
    """
    if observation.availability is None or "stock_status" not in applied["written"]:
        return
    if observation.availability == "unknown":
        return
    conn.execute(
        "UPDATE listings SET availability = ?, unit_limit = ? WHERE id = ?",
        (observation.availability, observation.unit_limit, listing["id"]),
    )


def _track_price_change(conn: sqlite3.Connection, listing: sqlite3.Row, before) -> None:
    """Remember the price before the latest change and when it moved."""
    row = conn.execute("SELECT * FROM listings WHERE id = ?", (listing["id"],)).fetchone()
    after = pricing.delivered_price(
        row["advertised_price"], row["freight"], row["cashback"], row["rebate"],
        row["coupon_discount"],
    )
    if before.value is None or after.value is None:
        return
    if abs(after.value - before.value) >= 0.005:
        conn.execute(
            "UPDATE listings SET previous_price = ?, price_changed_at = ? WHERE id = ?",
            (before.value, utcnow(), listing["id"]),
        )


def _last_message(conn: sqlite3.Connection, run_id: int, listing_id: int) -> str:
    row = conn.execute(
        "SELECT message FROM scrape_results WHERE run_id = ? AND listing_id = ?"
        " AND status IN ('error', 'unresolved') ORDER BY id DESC LIMIT 1",
        (run_id, listing_id),
    ).fetchone()
    return (row["message"] if row else "") or "no message"


def run(
    product_id: int | None = None,
    trigger: str = "cli",
    send_alerts: bool = True,
    config: Config | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    """Execute one watch pass. Returns a summary suitable for the API and the CLI."""
    config = config or load_config()
    summary: dict[str, Any] = {
        "run_id": None, "checked": 0, "ok": 0, "unresolved": 0, "skipped": 0,
        "errors": 0, "stale_marked": 0, "alerts": [], "delivery_failures": [],
        "events": {}, "adapters": {}, "category": category,
    }

    with session() as conn:
        run_id = _open_run(conn, trigger)
        summary["run_id"] = run_id

        # Only products still being hunted are checked, plus purchased ones inside an
        # open price-protection window. Polling a retailer about something already bought
        # and not under protection is a request nobody reads the answer to.
        where = (
            "WHERE l.active = 1 AND ("
            "  p.status = 'ACTIVE'"
            "  OR (p.status = 'PURCHASED' AND EXISTS ("
            "       SELECT 1 FROM purchases pu WHERE pu.product_id = p.id"
            "         AND pu.price_protection_until IS NOT NULL"
            "         AND substr(pu.price_protection_until, 1, 10) >= ?))"
            ")"
        )
        params: list = [utcnow()[:10]]
        if product_id:
            where += " AND l.product_id = ?"
            params.append(product_id)
        if category:
            # Only this category is touched: the other products are not polled at all.
            where += " AND lower(p.category) = lower(?)"
            params.append(category)
        listings = conn.execute(
            "SELECT l.*, r.adapter AS retailer_adapter, r.name AS retailer_name"
            " FROM listings l"
            " JOIN retailers r ON r.id = l.retailer_id"
            " JOIN products p ON p.id = l.product_id " + where,
            params,
        ).fetchall()

        if category and pi_events.is_pi(category, config):
            pi_events.ensure_rules(conn, config)

        per_adapter: dict[str, dict[str, Any]] = {}
        for listing in listings:
            product = store.get_product(conn, listing["product_id"])
            if product is None:
                continue
            status = check_listing(conn, listing, product, run_id, config)
            # Commit per listing. A run with retries can take many minutes, and holding
            # one write transaction open that long would make every other write (a UI
            # edit, mailwatch posting an offer) wait out SQLite's busy timeout and fail.
            conn.commit()
            summary["checked"] += 1
            summary[STATUS_COUNTER[status]] += 1
            if status != "skipped":
                slot = per_adapter.setdefault(
                    listing["retailer_adapter"], {"ok": 0, "failed": 0, "error": None}
                )
                if status == "ok":
                    slot["ok"] += 1
                else:
                    slot["failed"] += 1
                    slot["error"] = _last_message(conn, run_id, listing["id"])[:300]
        pi_health.record_run(conn, per_adapter)
        summary["adapters"] = per_adapter

        for product_row in {listing["product_id"] for listing in listings}:
            row = store.get_product(conn, product_row)
            if row is not None and pi_events.is_pi(row["category"], config):
                pi_events.evaluate_new_lowest(conn, config, product_row)

        for listing in listings:
            summary["stale_marked"] += len(
                provenance.mark_stale(conn, listing["id"], config.stale_after_days)
            )

        attempted = summary["checked"] - summary["skipped"]
        if attempted and summary["errors"] == attempted:
            status = "failed"
        elif summary["errors"]:
            status = "partial"
        else:
            status = "ok"

        conn.execute(
            "UPDATE scrape_runs SET finished_at = ?, status = ?, checked = ?, updated = ?,"
            " errors = ? WHERE id = ?",
            (utcnow(), status, summary["checked"], summary["ok"], summary["errors"], run_id),
        )
        summary["status"] = status

        if send_alerts:
            if product_id:
                view = store.product_view(conn, product_id)
                raised = alerts.evaluate_product(conn, view) if view else []
            else:
                raised = alerts.evaluate_all(conn)
            dispatched = alerts.dispatch(conn, raised, config)
            summary["alerts"] = dispatched["payload"]
            summary["delivery_failures"] = list(dispatched["delivery_failures"])
            events = pi_events.deliver_pending(conn, config)
            summary["events"] = {k: events[k] for k in ("sent", "failed", "expired", "deferred")}
            summary["alerts"] = summary["alerts"] + events["payload"]
            summary["delivery_failures"].extend(events["failures"])

    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.price_watch")
    parser.add_argument("--product", type=int, help="limit the run to one product id")
    parser.add_argument(
        "--category", help="limit the run to one category (the Pi timer passes Barkmarker)"
    )
    parser.add_argument("--no-alerts", action="store_true", help="check prices, send nothing")
    parser.add_argument("--trigger", default="cli", help="label recorded against the run")
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    migrate()
    summary = run(
        product_id=args.product, trigger=args.trigger, send_alerts=not args.no_alerts,
        category=args.category,
    )

    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(
            f"run {summary['run_id']}: {summary['status']} - checked {summary['checked']}, "
            f"ok {summary['ok']}, unresolved {summary['unresolved']}, "
            f"skipped {summary['skipped']}, errors {summary['errors']}, "
            f"alerts {len(summary['alerts'])}"
        )

    # Fail loudly for cron: a run where everything errored, or where an alert could not be
    # delivered, must not exit 0 and look healthy.
    if summary["status"] == "failed" or summary["delivery_failures"]:
        for failure in summary["delivery_failures"]:
            print(f"[ALERT-FAILURE] {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
