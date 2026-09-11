"""Query and assembly layer: everything the API and templates read goes through here."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping
from typing import Any

from . import pricing, provenance
from .config import load_config
from .db import utcnow

PRODUCT_FIELDS = [
    "name", "model", "brand", "category", "generation", "verdict", "status", "notes",
    "trigger_price", "excellent_price", "historical_low_price",
    "lowest_known_price", "lowest_known_date", "lowest_known_retailer", "lowest_known_notes",
    "width_mm", "height_mm", "depth_mm", "weight_kg",
    "packaged_width_mm", "packaged_height_mm", "packaged_depth_mm", "packaged_weight_kg",
    "mounting_notes", "vesa", "fit_notes", "archived",
]

LISTING_FIELDS = provenance.TRACKED_FIELDS + ["product_id", "retailer_id", "active"]

VERDICTS = ["BUY", "MAYBE", "IGNORE"]

#: Where a product sits in the process, as distinct from the verdict on it.
#: ACTIVE    - being researched or hunted, alerts armed
#: PURCHASED - bought; alerts off unless a price-protection window is open
#: PARKED    - set aside without deleting anything
STATUSES = ["ACTIVE", "PURCHASED", "PARKED"]


def normalise_model(model: str | None) -> str:
    """Model-matching key: case and separator insensitive.

    HW-Q930H/XY, hw q930h/xy and HWQ930H/XY are the same product. Region suffixes are
    kept, because HW-Q930H/XY and HW-Q930H/XU are genuinely different stock.
    """
    if not model:
        return ""
    return re.sub(r"[^A-Z0-9/]", "", model.upper())


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


# --------------------------------------------------------------------------- retailers


def ensure_retailer(conn: sqlite3.Connection, name: str, **extra: Any) -> sqlite3.Row:
    """Find a retailer by name (case insensitive) or create it."""
    name = name.strip()
    row = conn.execute(
        "SELECT * FROM retailers WHERE lower(name) = lower(?) OR slug = ?",
        (name, slugify(name)),
    ).fetchone()
    if row:
        # Backfill an adapter/homepage onto a retailer first created by a bare import.
        updates = {
            k: v for k, v in (("adapter", extra.get("adapter")),
                              ("homepage", extra.get("homepage")))
            if v and not row[k]
        }
        if updates:
            assignments = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(
                f"UPDATE retailers SET {assignments} WHERE id = ?",
                [*updates.values(), row["id"]],
            )
            row = conn.execute("SELECT * FROM retailers WHERE id = ?", (row["id"],)).fetchone()
        return row
    conn.execute(
        "INSERT INTO retailers (name, slug, adapter, homepage, notes) VALUES (?, ?, ?, ?, ?)",
        (name, slugify(name), extra.get("adapter"), extra.get("homepage"), extra.get("notes")),
    )
    return conn.execute("SELECT * FROM retailers WHERE slug = ?", (slugify(name),)).fetchone()


def list_retailers(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT * FROM retailers ORDER BY name")]


# --------------------------------------------------------------------------- products


def product_by_model(conn: sqlite3.Connection, model: str) -> sqlite3.Row | None:
    """Exact-model match, tolerant of punctuation and case only."""
    target = normalise_model(model)
    for row in conn.execute("SELECT * FROM products"):
        if normalise_model(row["model"]) == target:
            return row
    return None


def get_product(conn: sqlite3.Connection, product_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()


def create_product(conn: sqlite3.Connection, data: Mapping[str, Any]) -> int:
    payload = {k: v for k, v in data.items() if k in PRODUCT_FIELDS}
    payload.setdefault("category", "general")
    payload.setdefault("verdict", "MAYBE")
    if not payload.get("name") or not payload.get("model"):
        raise ValueError("name and model are required")
    payload["specs_json"] = json.dumps(data.get("specs") or {})
    payload["components_json"] = json.dumps(data.get("components") or {})
    payload["created_at"] = payload["updated_at"] = utcnow()
    cols = ", ".join(payload)
    marks = ", ".join("?" for _ in payload)
    cur = conn.execute(f"INSERT INTO products ({cols}) VALUES ({marks})", list(payload.values()))
    return int(cur.lastrowid)


def update_product(conn: sqlite3.Connection, product_id: int, data: Mapping[str, Any]) -> None:
    payload = {k: v for k, v in data.items() if k in PRODUCT_FIELDS}
    if "specs" in data:
        payload["specs_json"] = json.dumps(data["specs"] or {})
    if "components" in data:
        payload["components_json"] = json.dumps(data["components"] or {})
    if not payload:
        return
    payload["updated_at"] = utcnow()
    assignments = ", ".join(f"{k} = ?" for k in payload)
    conn.execute(
        f"UPDATE products SET {assignments} WHERE id = ?", [*payload.values(), product_id]
    )


# --------------------------------------------------------------------------- listings


def create_listing(conn: sqlite3.Connection, data: Mapping[str, Any]) -> int:
    payload = {k: v for k, v in data.items() if k in LISTING_FIELDS}
    if not payload.get("product_id") or not payload.get("retailer_id"):
        raise ValueError("product_id and retailer_id are required")
    payload.setdefault("condition", "NEW")
    payload["created_at"] = payload["updated_at"] = utcnow()
    cols = ", ".join(payload)
    marks = ", ".join("?" for _ in payload)
    cur = conn.execute(f"INSERT INTO listings ({cols}) VALUES ({marks})", list(payload.values()))
    return int(cur.lastrowid)


def find_listing(
    conn: sqlite3.Connection, product_id: int, retailer_id: int, url: str | None = None
) -> sqlite3.Row | None:
    if url:
        row = conn.execute(
            "SELECT * FROM listings WHERE product_id = ? AND retailer_id = ? AND url = ?",
            (product_id, retailer_id, url),
        ).fetchone()
        if row:
            return row
    return conn.execute(
        "SELECT * FROM listings WHERE product_id = ? AND retailer_id = ? ORDER BY id LIMIT 1",
        (product_id, retailer_id),
    ).fetchone()


def enrich_listing(
    conn: sqlite3.Connection, row: sqlite3.Row, product: Mapping[str, Any], penalty: float
) -> dict[str, Any]:
    """Attach delivered price, classification, provenance and verification to a listing row."""
    listing = dict(row)
    delivered = pricing.delivered_price(
        listing["advertised_price"],
        listing["freight"],
        listing["cashback"],
        listing["rebate"],
        listing["coupon_discount"],
    )
    listing["delivered"] = delivered
    listing["delivered_price"] = delivered.value
    listing["delivered_resolved"] = delivered.resolved
    listing["classification"] = pricing.classify(delivered, product)
    listing["classification_label"] = pricing.CLASS_LABELS[listing["classification"]]
    listing["diff_from_low"] = pricing.difference_from_low(
        delivered, product.get("lowest_known_price")
    )
    listing["provenance"] = provenance.provenance_map(conn, listing["id"])
    listing["verification"] = provenance.verification_map(conn, listing["id"])
    listing["manual_fields"] = sorted(
        f for f, p in listing["provenance"].items() if p["manual_locked"]
    )
    listing["rank"] = pricing.rank_key(delivered, penalty)
    return listing


SORT_KEYS = {
    "delivered": lambda r: r["rank"],
    "headline": lambda r: (r["advertised_price"] is None, r["advertised_price"] or 0.0),
    "retailer": lambda r: (r["retailer_name"] or "").lower(),
    "stock": lambda r: (r["stock_status"] or "zzz").lower(),
    "condition": lambda r: (
        pricing.CONDITIONS.index(r["condition"]) if r["condition"] in pricing.CONDITIONS else 99
    ),
    "verification": lambda r: -sum(
        1 for v in r["verification"].values() if v["status"] in {"VERIFIED", "LIVE", "MANUAL"}
    ),
    "diff": lambda r: (r["diff_from_low"] is None, r["diff_from_low"] or 0.0),
}


def listings_for_product(
    conn: sqlite3.Connection,
    product: Mapping[str, Any],
    sort: str = "delivered",
    include_inactive: bool = False,
) -> list[dict[str, Any]]:
    penalty = load_config().unresolved_freight_penalty
    where = "WHERE l.product_id = ?" + ("" if include_inactive else " AND l.active = 1")
    rows = conn.execute(
        "SELECT l.*, r.name AS retailer_name, r.slug AS retailer_slug,"
        " r.adapter AS retailer_adapter"
        " FROM listings l JOIN retailers r ON r.id = l.retailer_id "
        + where,
        (product["id"],),
    ).fetchall()
    enriched = [enrich_listing(conn, r, product, penalty) for r in rows]
    key = SORT_KEYS.get(sort, SORT_KEYS["delivered"])
    enriched.sort(key=key)
    return enriched


def product_view(
    conn: sqlite3.Connection, product_id: int, sort: str = "delivered"
) -> dict[str, Any] | None:
    """The full comparison view for one product: summary plus the retailer matrix."""
    row = get_product(conn, product_id)
    if row is None:
        return None
    product = dict(row)
    product["specs"] = json.loads(product.pop("specs_json") or "{}")
    product["components"] = json.loads(product.pop("components_json") or "{}")
    listings = listings_for_product(conn, product, sort=sort)

    best = pricing.best_listing(listings, load_config().unresolved_freight_penalty)
    product["best_listing"] = best
    product["best_delivered"] = best["delivered_price"] if best else None
    product["best_retailer"] = best["retailer_name"] if best else None
    product["best_classification"] = best["classification"] if best else pricing.UNRESOLVED
    product["best_resolved"] = bool(best and best["delivered_resolved"])
    product["diff_from_low"] = (
        pricing.difference_from_low(best["delivered_price"], product["lowest_known_price"])
        if best
        else None
    )
    product["listings"] = listings
    product["category_fields"] = category_fields(conn, product["category"])

    product["scale"] = pricing.threshold_scale(product, product["best_delivered"], listings)

    purchase = latest_purchase(conn, product_id)
    product["purchase"] = purchase
    if purchase:
        # Did it get cheaper after you bought it? The whole reason to keep watching.
        product["moved_since_purchase"] = (
            round(product["best_delivered"] - purchase["price_paid"], 2)
            if product["best_delivered"] is not None
            else None
        )
        product["protection_open"] = protection_open(purchase)
    else:
        product["moved_since_purchase"] = None
        product["protection_open"] = False

    # Live offers that could touch this product. Imported lazily to keep the module
    # graph acyclic: offers reads the product view, the product view lists offers.
    from . import offers as _offers
    product["offers"] = _offers.offers_for_product(conn, product_id)

    product["tone"], product["verdict_line"] = pricing.verdict_line(product)
    # Contenders are what you choose between; the rest are folded away by default.
    product["contenders"] = [
        listing for listing in listings
        if listing["classification"] != pricing.ABOVE_TARGET
    ][:4]
    if not product["contenders"]:
        product["contenders"] = listings[:2]
    contender_ids = {listing["id"] for listing in product["contenders"]}
    product["also_ran"] = [listing for listing in listings if listing["id"] not in contender_ids]
    return product


# -------------------------------------------------------------------------- purchases


def protection_open(purchase: Mapping[str, Any] | None) -> bool:
    """Is a price-protection window still running? Dates are plain YYYY-MM-DD."""
    if not purchase or not purchase.get("price_protection_until"):
        return False
    return str(purchase["price_protection_until"])[:10] >= utcnow()[:10]


def latest_purchase(conn: sqlite3.Connection, product_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM purchases WHERE product_id = ? ORDER BY purchased_at DESC, id DESC LIMIT 1",
        (product_id,),
    ).fetchone()
    return dict(row) if row else None


def record_purchase(
    conn: sqlite3.Connection, product_id: int, data: Mapping[str, Any]
) -> dict[str, Any]:
    """Record a purchase and move the product to PURCHASED.

    The listing is optional: plenty of things get bought in a shop, over the phone, or
    from somewhere that was never on the board. `price_paid` is the delivered figure and
    is the only required number, because it is the only one that settles the question.
    """
    price_paid = data.get("price_paid")
    if price_paid in (None, ""):
        raise ValueError("price_paid (delivered) is required")
    try:
        price_paid = float(price_paid)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"price_paid must be a number, got {price_paid!r}") from exc

    listing_id = data.get("listing_id")
    retailer_id, retailer_name = None, data.get("retailer_name")
    if listing_id:
        row = conn.execute(
            "SELECT l.retailer_id, r.name FROM listings l JOIN retailers r ON r.id = l.retailer_id"
            " WHERE l.id = ?",
            (listing_id,),
        ).fetchone()
        if row:
            retailer_id, retailer_name = row["retailer_id"], row["name"]
    elif retailer_name:
        retailer_id = ensure_retailer(conn, retailer_name)["id"]

    cur = conn.execute(
        "INSERT INTO purchases (product_id, listing_id, retailer_id, retailer_name,"
        " purchased_at, price_paid, advertised_paid, freight_paid, condition,"
        " order_reference, warranty_months, price_protection_until, notes, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            product_id, listing_id, retailer_id, retailer_name,
            data.get("purchased_at") or utcnow()[:10], price_paid,
            data.get("advertised_paid"), data.get("freight_paid"),
            (data.get("condition") or "NEW").upper(), data.get("order_reference"),
            data.get("warranty_months"), data.get("price_protection_until"),
            data.get("notes"), utcnow(),
        ),
    )
    conn.execute(
        "UPDATE products SET status = 'PURCHASED', updated_at = ? WHERE id = ?",
        (utcnow(), product_id),
    )
    # The purchase is itself an observation, and the best one: it is a price someone
    # actually paid rather than one a page advertised.
    conn.execute(
        "INSERT INTO price_history (product_id, listing_id, retailer_id, observed_at,"
        " advertised_price, delivered_price, freight, freight_resolved, condition, source, note)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, 'purchase', ?)",
        (
            product_id, listing_id, retailer_id, data.get("purchased_at") or utcnow(),
            data.get("advertised_paid"), price_paid, data.get("freight_paid"),
            (data.get("condition") or "NEW").upper(),
            data.get("notes") or "purchase recorded",
        ),
    )
    return dict(conn.execute("SELECT * FROM purchases WHERE id = ?", (cur.lastrowid,)).fetchone())


def undo_purchase(conn: sqlite3.Connection, product_id: int) -> bool:
    """Delete the most recent purchase and return the product to ACTIVE.

    The price_history row is deliberately left behind: it records a price that really was
    paid, and history is append-only even when the bookkeeping was wrong.
    """
    purchase = latest_purchase(conn, product_id)
    if not purchase:
        return False
    conn.execute("DELETE FROM purchases WHERE id = ?", (purchase["id"],))
    conn.execute(
        "UPDATE products SET status = 'ACTIVE', updated_at = ? WHERE id = ?",
        (utcnow(), product_id),
    )
    return True


STATUS_ORDER = {"ACTIVE": 0, "PURCHASED": 1, "PARKED": 2}


def list_products(
    conn: sqlite3.Connection,
    include_archived: bool = False,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Products with their matrices assembled. ACTIVE first, so the hunt stays on top."""
    clauses = [] if include_archived else ["archived = 0"]
    params: list[Any] = []
    if status and status.upper() != "ALL":
        clauses.append("status = ?")
        params.append(status.upper())
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    ids = [r["id"] for r in conn.execute(f"SELECT id FROM products{where} ORDER BY name", params)]
    products = [p for p in (product_view(conn, pid) for pid in ids) if p]
    products.sort(key=lambda p: (STATUS_ORDER.get(p["status"], 9), p["name"].lower()))
    return products


# --------------------------------------------------------------------------- history


def record_observation(
    conn: sqlite3.Connection,
    listing_id: int,
    source: str,
    note: str | None = None,
) -> int | None:
    """Append a price-history row from a listing's current state.

    Skipped when there is no price to record: a row of nulls is noise, not history.
    """
    row = conn.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()
    if row is None or row["advertised_price"] is None:
        return None
    delivered = pricing.delivered_price(
        row["advertised_price"], row["freight"], row["cashback"], row["rebate"],
        row["coupon_discount"],
    )
    cur = conn.execute(
        "INSERT INTO price_history (product_id, listing_id, retailer_id, observed_at,"
        " advertised_price, delivered_price, freight, freight_resolved, cashback,"
        " stock_status, condition, source, note)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            row["product_id"], listing_id, row["retailer_id"], utcnow(),
            row["advertised_price"], delivered.value, row["freight"], int(delivered.resolved),
            row["cashback"], row["stock_status"], row["condition"], source, note,
        ),
    )
    maybe_lower_known_low(conn, row["product_id"], delivered, listing_id)
    return int(cur.lastrowid)


def maybe_lower_known_low(
    conn: sqlite3.Connection, product_id: int, delivered: pricing.Delivered, listing_id: int
) -> bool:
    """Lower the product's recorded historical low when a confirmed price beats it.

    Only confirmed-freight prices qualify. The low is never raised automatically: the
    whole point of a historical low is that it survives the market moving.
    """
    if not delivered.resolved or delivered.value is None:
        return False
    product = get_product(conn, product_id)
    if product is None:
        return False
    current = product["lowest_known_price"]
    if current is not None and delivered.value >= current:
        return False
    retailer = conn.execute(
        "SELECT r.name FROM listings l JOIN retailers r ON r.id = l.retailer_id WHERE l.id = ?",
        (listing_id,),
    ).fetchone()
    conn.execute(
        "UPDATE products SET lowest_known_price = ?, lowest_known_date = ?,"
        " lowest_known_retailer = ?, updated_at = ? WHERE id = ?",
        (
            delivered.value,
            utcnow()[:10],
            retailer["name"] if retailer else None,
            utcnow(),
            product_id,
        ),
    )
    return True


def price_history(
    conn: sqlite3.Connection, product_id: int, limit: int = 500
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT h.*, r.name AS retailer_name FROM price_history h"
        " LEFT JOIN retailers r ON r.id = h.retailer_id"
        " WHERE h.product_id = ? ORDER BY h.observed_at DESC, h.id DESC LIMIT ?",
        (product_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- categories


def category_fields(conn: sqlite3.Connection, category: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM category_specifications WHERE category = ? ORDER BY sort, label",
        (category,),
    ).fetchall()
    return [dict(r) for r in rows]


def categories(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT category FROM category_specifications ORDER BY category"
    ).fetchall()
    known = [r["category"] for r in rows]
    used = [
        r["category"]
        for r in conn.execute("SELECT DISTINCT category FROM products ORDER BY category")
    ]
    return sorted(set(known) | set(used))
