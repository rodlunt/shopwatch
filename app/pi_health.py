"""Is the Pi watch actually watching?

A watch that stops quietly looks exactly like a watch with nothing to report, so this
module derives its verdict from the work (hardening rules 3 and 7): the newest successful
price observation for a Pi product, and a consecutive-failure count per adapter. Neither
can be set by the wrapper that runs the check.

    python -m app.pi_health        # exit 1 and say why when anything is wrong

The CLI is run by an hourly systemd timer whose OnFailure= pushes a high priority ntfy and
repeats hourly while the fault lasts. The same data backs GET /api/pi-watch and the
`pi_watch` block of /healthz and /api/meta.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from typing import Any

from . import availability as av
from . import retailers, store
from .config import Config, load_config
from .db import migrate, session, utcnow

PI_MIGRATION = "0016_pi_watch.sql"


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def record_run(
    conn: sqlite3.Connection, per_adapter: dict[str, dict[str, Any]], now: str | None = None
) -> None:
    """Fold one run into adapter_health.

    `per_adapter` maps adapter slug to {"ok": n, "failed": n, "error": last error text}.
    A run counts as a failed run for an adapter only when it had listings to check and not
    one of them produced a price: one dead product URL is a stale listing, shown in the
    API, while a whole adapter returning nothing is a broken adapter. Every individual
    failure still adds to total_failures.
    """
    now = now or utcnow()
    for slug, result in per_adapter.items():
        ok, failed = int(result.get("ok", 0)), int(result.get("failed", 0))
        if ok + failed == 0:
            continue
        conn.execute("INSERT OR IGNORE INTO adapter_health (adapter) VALUES (?)", (slug,))
        if ok:
            conn.execute(
                "UPDATE adapter_health SET last_run_at = ?, last_success_at = ?,"
                " consecutive_failures = 0, total_runs = total_runs + 1,"
                " total_failures = total_failures + ?, streak_alerted_at = NULL,"
                " last_error = ? WHERE adapter = ?",
                (now, now, failed, result.get("error") if failed else None, slug),
            )
        else:
            conn.execute(
                "UPDATE adapter_health SET last_run_at = ?, consecutive_failures ="
                " consecutive_failures + 1, total_runs = total_runs + 1,"
                " total_failures = total_failures + ?, last_error = ? WHERE adapter = ?",
                (now, failed, result.get("error"), slug),
            )


def _baseline(conn: sqlite3.Connection) -> datetime | None:
    """When the Pi watch came into existence, so "never succeeded" is not stale at once."""
    row = conn.execute(
        "SELECT applied_at FROM schema_migrations WHERE filename = ?", (PI_MIGRATION,)
    ).fetchone()
    return _parse(row["applied_at"]) if row else None


def last_success(conn: sqlite3.Connection, category: str) -> str | None:
    """Newest successful adapter observation for a product in the category.

    price_history rows are written only when an adapter returned a price, and hand-typed
    or imported rows carry another source, so this cannot be moved by anything except a
    real successful check.
    """
    row = conn.execute(
        "SELECT MAX(h.observed_at) AS t FROM price_history h"
        " JOIN products p ON p.id = h.product_id"
        " WHERE lower(p.category) = lower(?)"
        "   AND h.source IN (SELECT adapter FROM retailers WHERE adapter IS NOT NULL)",
        (category,),
    ).fetchone()
    return row["t"] if row else None


def manual_retailers(
    conn: sqlite3.Connection, config: Config | None = None, category: str | None = None
) -> list[dict[str, Any]]:
    """Retailers marked manual, with each active listing's age since its last check.

    Age runs from the listing's last check, or from when the retailer went manual if it
    has never been checked, so flipping a retailer to manual does not raise an alarm at
    once. `due` means the dashboard should ask for a check (manual_nudge_hours);
    `overdue` means the Pi-watch fault should fire (manual_stale_hours).
    """
    config = config or load_config()
    now = datetime.now(UTC)
    out: list[dict[str, Any]] = []
    for r in conn.execute(
        "SELECT id, name, adapter, homepage, manual_since, manual_reason FROM retailers"
        " WHERE manual_since IS NOT NULL ORDER BY name"
    ).fetchall():
        sql = (
            "SELECT l.id, l.product_id, l.url, l.advertised_price, l.stock_status,"
            " l.availability, l.last_checked_at, p.name AS product_name, p.model"
            " FROM listings l JOIN products p ON p.id = l.product_id"
            " WHERE l.retailer_id = ? AND l.active = 1 AND p.status = 'ACTIVE'"
        )
        args: list[Any] = [r["id"]]
        if category:
            sql += " AND lower(p.category) = lower(?)"
            args.append(category)
        listings = []
        for row in conn.execute(sql + " ORDER BY p.name", args):
            anchor = _parse(row["last_checked_at"]) or _parse(r["manual_since"])
            hours = round((now - anchor).total_seconds() / 3600, 1) if anchor else None
            listings.append(
                {
                    "listing_id": row["id"],
                    "product_id": row["product_id"],
                    "product_name": row["product_name"],
                    "model": row["model"],
                    "url": row["url"],
                    "price": row["advertised_price"],
                    "stock_status": row["stock_status"],
                    "availability": row["availability"],
                    "last_checked_at": row["last_checked_at"],
                    "age_hours": hours,
                    "due": hours is None or hours >= config.manual_nudge_hours,
                    "overdue": hours is None or hours >= config.manual_stale_hours,
                }
            )
        if listings:
            out.append(
                {
                    "retailer_id": r["id"],
                    "name": r["name"],
                    "adapter": r["adapter"],
                    "homepage": r["homepage"],
                    "manual_since": r["manual_since"],
                    "reason": r["manual_reason"],
                    "listings": listings,
                    "due": any(x["due"] for x in listings),
                    "overdue": any(x["overdue"] for x in listings),
                }
            )
    return out


def health(conn: sqlite3.Connection, config: Config | None = None) -> dict[str, Any]:
    config = config or load_config()
    now = datetime.now(UTC)
    last_ok = last_success(conn, config.pi_category)
    reasons: list[str] = []

    anchor = _parse(last_ok) or _baseline(conn)
    hours = round((now - anchor).total_seconds() / 3600, 1) if anchor else None
    if anchor is None:
        reasons.append("the Pi watch has no successful price check and no start time on record")
    elif hours is not None and hours > config.pi_stale_hours:
        since = last_ok or f"{PI_MIGRATION} was applied"
        reasons.append(
            f"no successful price check for any {config.pi_category} product in {hours:.0f} "
            f"hours (limit {config.pi_stale_hours:.0f}); last success: {since}"
        )

    adapters = []
    for row in conn.execute(
        "SELECT DISTINCT r.adapter FROM listings l JOIN retailers r ON r.id = l.retailer_id"
        " JOIN products p ON p.id = l.product_id"
        " WHERE l.active = 1 AND r.adapter IS NOT NULL AND r.manual_since IS NULL"
        "   AND lower(p.category) = lower(?)"
        " ORDER BY r.adapter",
        (config.pi_category,),
    ):
        slug = row["adapter"]
        h = conn.execute("SELECT * FROM adapter_health WHERE adapter = ?", (slug,)).fetchone()
        failures = h["consecutive_failures"] if h else 0
        broken = failures >= config.pi_streak_limit
        adapters.append(
            {
                "adapter": slug,
                "healthy": not broken,
                "consecutive_failed_runs": failures,
                "last_run_at": h["last_run_at"] if h else None,
                "last_success_at": h["last_success_at"] if h else None,
                "last_error": h["last_error"] if h else None,
                "total_runs": h["total_runs"] if h else 0,
                "total_failures": h["total_failures"] if h else 0,
            }
        )
        if broken:
            reasons.append(
                f"adapter {slug} has failed {failures} runs in a row "
                f"(roughly {failures / 2:g} days at two runs a day); "
                f"last error: {h['last_error']}"
            )

    manual = manual_retailers(conn, config, config.pi_category)
    for retailer in manual:
        late = [x for x in retailer["listings"] if x["overdue"]]
        if late:
            oldest = max(x["age_hours"] or 0 for x in late)
            reasons.append(
                f"manual retailer {retailer['name']}: {len(late)} listing(s) not checked for "
                f"up to {oldest:.0f} hours (limit {config.manual_stale_hours:.0f}); open the "
                "dashboard and record a check"
            )

    run = conn.execute(
        "SELECT started_at, finished_at, status, trigger FROM scrape_runs"
        " WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return {
        "status": "ok" if not reasons else "unhealthy",
        "reasons": reasons,
        "last_successful_check": last_ok,
        "hours_since_success": hours,
        "stale_after_hours": config.pi_stale_hours,
        "last_run": dict(run) if run else None,
        "adapters": adapters,
        "manual_retailers": manual,
        "checked_at": utcnow(),
    }


def heartbeat(conn: sqlite3.Connection, config: Config | None = None) -> dict[str, Any]:
    """The few fields worth putting on /healthz and /api/meta."""
    h = health(conn, config)
    return {
        "status": h["status"],
        "last_successful_check": h["last_successful_check"],
        "hours_since_success": h["hours_since_success"],
        "stale_after_hours": h["stale_after_hours"],
        "reasons": h["reasons"],
    }


def summary(conn: sqlite3.Connection, config: Config | None = None) -> dict[str, Any]:
    """GET /api/pi-watch: the cheapest buyable price per product, and how far to trust it."""
    config = config or load_config()
    products = []
    for product in store.list_products(conn):
        if (product.get("category") or "").lower() != config.pi_category.lower():
            continue
        if product.get("status") != "ACTIVE":
            continue
        rows = []
        for listing in product["listings"]:
            state = listing.get("availability") or av.normalise(listing.get("stock_status")).state
            error = conn.execute(
                "SELECT status, message FROM scrape_results WHERE listing_id = ?"
                " ORDER BY id DESC LIMIT 1",
                (listing["id"],),
            ).fetchone()
            rows.append(
                {
                    "listing_id": listing["id"],
                    "retailer": listing["retailer_name"],
                    "adapter": listing.get("retailer_adapter"),
                    "automatic": bool(listing.get("retailer_adapter"))
                    and not listing.get("retailer_manual_since"),
                    "price": listing["delivered_price"],
                    "freight_resolved": listing["delivered_resolved"],
                    "previous_price": listing.get("previous_price"),
                    "price_changed_at": listing.get("price_changed_at"),
                    "availability": state,
                    "availability_text": listing.get("stock_status"),
                    "unit_limit": listing.get("unit_limit"),
                    "last_checked_at": listing.get("last_checked_at"),
                    "last_result": error["status"] if error else None,
                    "last_error": error["message"]
                    if error and error["status"] in ("error", "unresolved")
                    else None,
                    "url": listing.get("url"),
                    "ruled_out": bool(listing.get("ruled_out")),
                }
            )
        buyable = [
            r for r in rows
            if r["availability"] in av.BUYABLE and r["price"] is not None and not r["ruled_out"]
        ]
        best = min(buyable, key=lambda r: r["price"]) if buyable else None
        checks = [r["last_checked_at"] for r in rows if r["last_checked_at"]]
        products.append(
            {
                "id": product["id"],
                "name": product["name"],
                "model": product["model"],
                "trigger_price": product.get("trigger_price"),
                "cheapest_in_stock": best,
                "in_stock_count": len(buyable),
                "retailer_count": len(rows),
                "last_successful_check": max(checks) if checks else None,
                "listings": rows,
            }
        )
    return {
        "category": config.pi_category,
        "generated_at": utcnow(),
        "health": health(conn, config),
        "supported_adapters": sorted(retailers.available_adapters()),
        "products": products,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.pi_health")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    migrate()
    with session() as conn:
        result = health(conn)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(f"pi-watch: {result['status']}; last success {result['last_successful_check']}")
        for adapter in result["adapters"]:
            print(
                f"  {adapter['adapter']}: {adapter['consecutive_failed_runs']} failed runs in a "
                f"row, last success {adapter['last_success_at']}"
            )
    for retailer in result["manual_retailers"]:
        oldest = max((x["age_hours"] or 0 for x in retailer["listings"]), default=0)
        print(f"  {retailer['name']} (manual): oldest check {oldest:.0f} hours ago")
    for reason in result["reasons"]:
        print(f"[PI-WATCH-FAULT] {reason}", file=sys.stderr)
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
