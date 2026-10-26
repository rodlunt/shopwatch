"""Event alerts for the Pi watch: back in stock, price drop, new lowest.

The target alert ("at or below trigger price") is stateless and lives in alerts.py. These
three are about change, so they need a before and an after:

* BACK_IN_STOCK: a listing goes from out of stock / backorder / dispatch later to in stock
  or limited.
* PRICE_DROP: a listing's delivered price falls by at least max($3, 5%) against the
  previous run (both thresholds are columns on the rule).
* NEW_LOWEST: the cheapest buyable delivered price across retailers is a new low.

"Before" is always the previous reading taken by an adapter at that listing, never a
hand-typed value, so the first automatic run records a baseline and says nothing. A change
becomes a row in alert_events the moment it is seen and stays 'pending' until a delivery
is confirmed, so a failed push is retried on the next run rather than lost, and the unique
dedupe key means the same change can never be queued twice. Anything that cannot be
delivered inside pi_event_expiry_hours is expired loudly, not dropped.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from . import alerts
from . import availability as av
from .config import Config, load_config
from .db import utcnow

log = logging.getLogger("shopwatch.pi_events")

BACK_IN_STOCK = "BACK_IN_STOCK"
PRICE_DROP = "PRICE_DROP"
NEW_LOWEST = "NEW_LOWEST"
TRIGGER = "TRIGGER"
EVENT_KINDS = (BACK_IN_STOCK, PRICE_DROP, NEW_LOWEST)

LABELS = {
    BACK_IN_STOCK: "BACK IN STOCK",
    PRICE_DROP: "PRICE DROP",
    NEW_LOWEST: "NEW LOWEST",
}

#: (name, kind, min_change) for every rule a Pi product should carry. max_delivered is
#: unused (0) for all of them: TRIGGER follows products.trigger_price, the rest are events.
RULE_SET = (
    ("At or below trigger price", TRIGGER, 1.0),
    ("Back in stock", BACK_IN_STOCK, 0.0),
    ("Price drop", PRICE_DROP, 0.0),
    ("New lowest in-stock price", NEW_LOWEST, 1.0),
)


def is_pi(category: str | None, config: Config | None = None) -> bool:
    config = config or load_config()
    return (category or "").strip().lower() == config.pi_category.strip().lower()


def ensure_rules(conn: sqlite3.Connection, config: Config | None = None) -> int:
    """Give every ACTIVE Pi product its alert rules. Idempotent; returns rows created.

    require_complete and require_resolved are 0: a bare board has no "included components"
    to record and no retailer confirms freight, so the stock defaults would suppress every
    Pi listing for ever.
    """
    config = config or load_config()
    created = 0
    for product in conn.execute(
        "SELECT id FROM products WHERE lower(category) = lower(?) AND status = 'ACTIVE'",
        (config.pi_category,),
    ).fetchall():
        for name, kind, min_change in RULE_SET:
            cur = conn.execute(
                "INSERT OR IGNORE INTO alert_rules (product_id, name, kind, conditions,"
                " max_delivered, require_complete, require_resolved, min_change)"
                " VALUES (?, ?, ?, 'NEW', 0, 0, 0, ?)",
                (product["id"], name, kind, min_change),
            )
            created += cur.rowcount
    return created


def _rule(conn: sqlite3.Connection, product_id: int, kind: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM alert_rules WHERE product_id = ? AND kind = ? AND enabled = 1",
        (product_id, kind),
    ).fetchone()


@dataclass
class EventAlert:
    """An event alert shaped like alerts.Alert, so one send() path serves both."""

    kind: str
    product_name: str
    retailer: str
    listing_id: int
    url: str | None
    old_price: float | None
    new_price: float
    availability_text: str | None
    unit_limit: int | None
    detail: str
    event_id: int | None = None

    def title(self) -> str:
        return f"{LABELS[self.kind]}: {self.product_name}"

    def body(self) -> str:
        lines = [f"{self.retailer} - ${self.new_price:.2f}"]
        if self.old_price is not None and self.kind in (PRICE_DROP, NEW_LOWEST):
            drop = self.old_price - self.new_price
            lines[0] += f" (was ${self.old_price:.2f}, down ${drop:.2f})"
        lines.append(self.detail)
        stock = self.availability_text or "availability unknown"
        if self.unit_limit and "limit" not in stock.lower():
            stock += f" (limit {self.unit_limit} per customer)"
        lines.append(f"Stock: {stock}")
        lines.append("Freight is quoted at the cart and is not included.")
        if self.url:
            lines.append(self.url)
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "product": self.product_name, "retailer": self.retailer,
            "old_price": self.old_price, "new_price": self.new_price,
            "availability_text": self.availability_text, "unit_limit": self.unit_limit,
            "detail": self.detail, "url": self.url, "listing_id": self.listing_id,
            "event_id": self.event_id, "at": utcnow(),
        }


def _queue(
    conn: sqlite3.Connection,
    config: Config,
    kind: str,
    product_id: int,
    listing_id: int | None,
    dedupe_key: str,
    payload: dict[str, Any],
) -> str:
    """Queue one event. Returns 'queued', 'duplicate' or 'suppressed'.

    A suppressed event (same kind, same listing, inside the cooldown) is still written, as
    'suppressed', so the suppression is on the record rather than silent.
    """
    if conn.execute("SELECT 1 FROM alert_events WHERE dedupe_key = ?", (dedupe_key,)).fetchone():
        return "duplicate"
    cutoff = (datetime.now(UTC) - timedelta(hours=config.pi_event_cooldown_hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    recent = conn.execute(
        "SELECT 1 FROM alert_events WHERE kind = ? AND product_id = ?"
        " AND IFNULL(listing_id, 0) = IFNULL(?, 0) AND status IN ('pending', 'sent')"
        " AND created_at > ?",
        (kind, product_id, listing_id, cutoff),
    ).fetchone()
    status = "suppressed" if recent else "pending"
    conn.execute(
        "INSERT INTO alert_events (kind, product_id, listing_id, dedupe_key, payload, status,"
        " created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (kind, product_id, listing_id, dedupe_key, json.dumps(payload), status, utcnow()),
    )
    if status == "suppressed":
        log.info("suppressed %s for listing %s: inside the %sh cooldown", kind, listing_id,
                 config.pi_event_cooldown_hours)
        return "suppressed"
    return "queued"


def previous_observation(
    conn: sqlite3.Connection, listing_id: int, source: str
) -> sqlite3.Row | None:
    """The last reading an adapter itself took at this listing, before the current one."""
    return conn.execute(
        "SELECT * FROM price_history WHERE listing_id = ? AND source = ?"
        " ORDER BY id DESC LIMIT 1",
        (listing_id, source),
    ).fetchone()


def detect_transitions(
    conn: sqlite3.Connection,
    config: Config,
    *,
    listing: sqlite3.Row,
    product_name: str,
    retailer_name: str,
    previous: sqlite3.Row | None,
    history_id: int | None,
    new_delivered: float | None,
    new_availability: str | None,
) -> list[str]:
    """Compare this reading with the previous adapter reading and queue what changed.

    `previous` must be fetched BEFORE the new history row is written. With no previous
    adapter reading there is nothing to compare with: a baseline is being established.
    """
    queued: list[str] = []
    if previous is None or history_id is None or new_delivered is None:
        return queued
    product_id = listing["product_id"]
    base = {
        "product": product_name, "retailer": retailer_name, "url": listing["url"],
        "availability_text": listing["stock_status"], "unit_limit": listing["unit_limit"],
    }

    rule = _rule(conn, product_id, PRICE_DROP)
    old = previous["delivered_price"]
    if rule and old is not None:
        need = max(rule["min_drop_abs"], old * rule["min_drop_pct"] / 100.0)
        if old - new_delivered >= need - 1e-9:
            result = _queue(
                conn, config, PRICE_DROP, product_id, listing["id"],
                f"{PRICE_DROP}:{listing['id']}:{history_id}",
                {**base, "old_price": old, "new_price": new_delivered,
                 "detail": f"Down ${old - new_delivered:.2f} since the previous check "
                           f"(alert at ${rule['min_drop_abs']:.0f} or "
                           f"{rule['min_drop_pct']:g}%, whichever is more)."},
            )
            queued.append(f"{PRICE_DROP}:{result}")

    rule = _rule(conn, product_id, BACK_IN_STOCK)
    was = av.normalise(previous["stock_status"]).state
    if rule and was in av.WAITING and new_availability in av.BUYABLE:
        result = _queue(
            conn, config, BACK_IN_STOCK, product_id, listing["id"],
            f"{BACK_IN_STOCK}:{listing['id']}:{history_id}",
            {**base, "old_price": old, "new_price": new_delivered,
             "detail": f"Was {was.replace('_', ' ')}, now {new_availability.replace('_', ' ')}."},
        )
        queued.append(f"{BACK_IN_STOCK}:{result}")
    return queued


def cheapest_buyable(conn: sqlite3.Connection, product_id: int) -> dict[str, Any] | None:
    """The cheapest in-stock delivered price across retailers, or None when nothing is."""
    from . import pricing, store

    product = store.get_product(conn, product_id)
    if product is None:
        return None
    best: dict[str, Any] | None = None
    for row in conn.execute(
        "SELECT l.*, r.name AS retailer_name FROM listings l"
        " JOIN retailers r ON r.id = l.retailer_id WHERE l.product_id = ? AND l.active = 1",
        (product_id,),
    ):
        if row["ruled_out"]:
            continue
        state = row["availability"] or av.normalise(row["stock_status"]).state
        if state not in av.BUYABLE:
            continue
        delivered = pricing.delivered_price(
            row["advertised_price"], row["freight"], row["cashback"], row["rebate"],
            row["coupon_discount"],
        )
        if not delivered.known:
            continue
        if best is None or delivered.value < best["price"]:
            best = {"price": delivered.value, "listing": row}
    return best


def evaluate_new_lowest(
    conn: sqlite3.Connection, config: Config, product_id: int, commit_baseline: bool = True
) -> dict[str, Any] | None:
    """Queue a NEW_LOWEST event if the best buyable price beats the record.

    The record is alert_rules.last_fired_price for the NEW_LOWEST rule. The first sight of
    a price sets it silently (a baseline, not news). It only ever falls: a dearer day does
    not raise the bar, or the next dip back to an old price would shout again. With
    commit_baseline False (the dry run) nothing is written.
    """
    rule = _rule(conn, product_id, NEW_LOWEST)
    if rule is None:
        return None
    best = cheapest_buyable(conn, product_id)
    if best is None:
        return None
    price, listing = best["price"], best["listing"]
    record = rule["last_fired_price"]
    if record is None:
        if commit_baseline:
            conn.execute("UPDATE alert_rules SET last_fired_price = ? WHERE id = ?",
                         (price, rule["id"]))
        return None
    if record - price < max(rule["min_change"], 0.005):
        return None
    product = conn.execute("SELECT name FROM products WHERE id = ?", (product_id,)).fetchone()
    payload = {
        "product": product["name"], "retailer": listing["retailer_name"],
        "url": listing["url"], "availability_text": listing["stock_status"],
        "unit_limit": listing["unit_limit"], "old_price": record, "new_price": price,
        "detail": "Cheapest in-stock price across retailers, a new low "
                  f"(previous low ${record:.2f}).",
    }
    if commit_baseline:
        _queue(conn, config, NEW_LOWEST, product_id, listing["id"],
               f"{NEW_LOWEST}:{product_id}:{price:.2f}", payload)
        conn.execute("UPDATE alert_rules SET last_fired_price = ?, last_fired_at = ?"
                     " WHERE id = ?", (price, utcnow(), rule["id"]))
    return payload


def _alert_from_row(row: sqlite3.Row) -> EventAlert:
    p = json.loads(row["payload"])
    return EventAlert(
        kind=row["kind"], product_name=p["product"], retailer=p["retailer"],
        listing_id=row["listing_id"] or 0, url=p.get("url"), old_price=p.get("old_price"),
        new_price=p["new_price"], availability_text=p.get("availability_text"),
        unit_limit=p.get("unit_limit"), detail=p.get("detail", ""), event_id=row["id"],
    )


def pending(conn: sqlite3.Connection) -> list[EventAlert]:
    return [
        _alert_from_row(r)
        for r in conn.execute(
            "SELECT * FROM alert_events WHERE status = 'pending' ORDER BY id"
        ).fetchall()
    ]


def deliver_pending(conn: sqlite3.Connection, config: Config | None = None) -> dict[str, Any]:
    """Send pending events. Confirmed delivery marks 'sent'; a failure leaves 'pending'.

    Rate limited to pi_max_alerts_per_run per run (the rest wait for the next run).
    Events still undelivered after pi_event_expiry_hours are marked 'expired' and reported
    as failures, so the run exits non-zero rather than quietly giving up.
    """
    config = config or load_config()
    out: dict[str, Any] = {"sent": 0, "failed": 0, "expired": 0, "deferred": 0,
                           "failures": [], "payload": []}
    cutoff = (datetime.now(UTC) - timedelta(hours=config.pi_event_expiry_hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    for row in conn.execute(
        "SELECT * FROM alert_events WHERE status = 'pending' AND created_at < ?", (cutoff,)
    ).fetchall():
        conn.execute("UPDATE alert_events SET status = 'expired' WHERE id = ?", (row["id"],))
        message = (
            f"{row['kind']} alert for listing {row['listing_id']} expired undelivered after "
            f"{config.pi_event_expiry_hours:g}h (last error: {row['last_error']})"
        )
        log.error(message)
        out["expired"] += 1
        out["failures"].append(message)

    rows = conn.execute(
        "SELECT * FROM alert_events WHERE status = 'pending' ORDER BY id"
    ).fetchall()
    for index, row in enumerate(rows):
        if index >= config.pi_max_alerts_per_run:
            out["deferred"] = len(rows) - index
            break
        alert = _alert_from_row(row)
        report = alerts.send(alert, config)
        if report.ok:
            conn.execute(
                "UPDATE alert_events SET status = 'sent', sent_at = ?, attempts = attempts + 1,"
                " last_error = NULL WHERE id = ?",
                (utcnow(), row["id"]),
            )
            out["sent"] += 1
            out["payload"].append(alert.to_dict())
        else:
            conn.execute(
                "UPDATE alert_events SET attempts = attempts + 1, last_error = ? WHERE id = ?",
                ("; ".join(report.failures)[:500], row["id"]),
            )
            out["failed"] += 1
            out["failures"].extend(report.failures)
    return out
