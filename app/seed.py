"""Seed data: category profiles, retailers, and the Samsung HW-Q930H/XY research board.

Seeding is idempotent and additive. It never updates or deletes an existing product, so
running it against a live database cannot clobber research you have already done.
"""

from __future__ import annotations

import argparse
import sqlite3

from . import provenance, store
from .db import migrate, session, utcnow

# --------------------------------------------------------------------- category profiles

CATEGORY_PROFILES: dict[str, list[tuple[str, str, str]]] = {
    "tv": [
        ("screen_size_in", "Screen size (in)", "number"),
        ("panel_technology", "Panel technology", "text"),
        ("native_refresh_hz", "Native refresh (Hz)", "number"),
        ("four_k_120", "4K 120 support", "bool"),
        ("hdmi_21_ports", "HDMI 2.1 ports", "number"),
        ("vrr", "VRR", "bool"),
        ("allm", "ALLM", "bool"),
        ("earc", "eARC", "bool"),
        ("dolby_vision", "Dolby Vision", "bool"),
        ("hdr10_plus", "HDR10+", "bool"),
        ("operating_system", "Operating system", "text"),
        ("ethernet_speed", "Ethernet speed", "text"),
        ("wifi", "Wi-Fi", "text"),
        ("stand_weight_kg", "Stand weight (kg)", "number"),
        ("moonlight_suitability", "Moonlight suitability", "text"),
        ("gaming_notes", "Gaming notes", "text"),
    ],
    "soundbar": [
        ("channels", "Channel configuration", "text"),
        ("dolby_atmos", "Dolby Atmos", "bool"),
        ("dts_x", "DTS:X", "bool"),
        ("hdmi_inputs", "HDMI inputs", "number"),
        ("earc", "eARC", "bool"),
        ("wireless_rears", "Wireless rear speakers", "bool"),
        ("rear_quantity", "Rear speaker quantity", "number"),
        ("system_notes", "Total system notes", "text"),
    ],
    "power_tool": [
        ("tool_type", "Tool type", "text"),
        ("battery_platform", "Battery platform", "text"),
        ("voltage", "Voltage", "text"),
        ("battery_included", "Battery included", "bool"),
        ("battery_capacity_ah", "Battery capacity (Ah)", "number"),
        ("charger_included", "Charger included", "bool"),
        ("kit_contents", "Kit contents", "text"),
        ("warranty", "Warranty", "text"),
    ],
    "appliance": [
        ("energy_star", "Energy rating", "text"),
        ("capacity", "Capacity", "text"),
        ("install_type", "Installation type", "text"),
        ("plumbing_required", "Plumbing required", "bool"),
    ],
}

RETAILERS = [
    ("Crowdshop", "crowdshop", "https://crowdshop.com.au"),
    ("Harvey Norman", "harvey_norman", "https://www.harveynorman.com.au"),
    ("JB Hi-Fi", "jb_hifi", "https://www.jbhifi.com.au"),
    ("The Good Guys", "the_good_guys", "https://www.thegoodguys.com.au"),
    ("Appliance Central", "appliance_central", "https://www.appliancecentral.com.au"),
    ("Appliances Online", None, "https://www.appliancesonline.com.au"),
    ("Bing Lee", None, "https://www.binglee.com.au"),
    ("Betta", None, "https://www.betta.com.au"),
]


def seed_categories(conn: sqlite3.Connection) -> int:
    added = 0
    for category, fields in CATEGORY_PROFILES.items():
        for sort, (key, label, kind) in enumerate(fields):
            cur = conn.execute(
                "INSERT OR IGNORE INTO category_specifications"
                " (category, field_key, label, kind, sort) VALUES (?, ?, ?, ?, ?)",
                (category, key, label, kind, sort),
            )
            added += cur.rowcount
    return added


def seed_retailers(conn: sqlite3.Connection) -> int:
    added = 0
    for name, adapter, homepage in RETAILERS:
        before = conn.execute("SELECT COUNT(*) c FROM retailers").fetchone()["c"]
        store.ensure_retailer(conn, name, adapter=adapter, homepage=homepage)
        after = conn.execute("SELECT COUNT(*) c FROM retailers").fetchone()["c"]
        added += after - before
    return added


# ------------------------------------------------------------------------ Q930H research

Q930H_CONTENTS = "Soundbar, subwoofer, 2x rear speakers, remote, wall bracket"

# Each entry: retailer, values, provenance state, verification overrides, notes.
Q930H_LISTINGS = [
    {
        "retailer": "Crowdshop",
        "url": None,
        "values": {
            "model_on_page": "HW-Q930H/XY",
            "advertised_price": 869.0,
            "price_guide": "869-889 (page quotes a range)",
            "condition": "NEW",
            "stock_status": "In Stock (page states)",
            "warranty": "1 year manufacturer (stated on page)",
            "included_components": Q930H_CONTENTS,
            "seller_notes": (
                "Postcode 4506 returned 'No shipping options were found' at checkout, so "
                "freight and fulfilment are unresolved. A displayed $0 delivery is NOT "
                "confirmation of free shipping."
            ),
        },
        "verification": {
            "model": provenance.VERIFIED,
            "freight": (provenance.FLAGGED, "Checkout returned no shipping options for 4506"),
            "contents": provenance.VERIFIED,
        },
    },
    {
        "retailer": "Appliance Central",
        "url": None,
        "values": {
            "model_on_page": "HW-Q930H/XY",
            "advertised_price": 1059.0,
            "condition": "NEW",
            "stock_status": "In stock (warehouse dispatch)",
            "seller_notes": (
                "Approximately $1059 after coupon at last observation. Valid benchmark but "
                "above target."
            ),
        },
        "verification": {"model": provenance.VERIFIED},
    },
    {
        "retailer": "Harvey Norman",
        "url": None,
        "values": {
            "model_on_page": "HW-Q930H/XY",
            "advertised_price": 1695.0,
            "condition": "NEW",
            "seller_notes": "Last observed headline price. Freight/pickup not determined.",
        },
        "verification": {"model": provenance.VERIFIED},
    },
    {
        "retailer": "JB Hi-Fi",
        "url": None,
        "values": {
            "model_on_page": "HW-Q930H/XY",
            "advertised_price": 1699.0,
            "condition": "NEW",
            "seller_notes": (
                "Last observed headline price from the live product page. Older ~$999 search "
                "snippets are stale and must not be imported as current."
            ),
        },
        "verification": {"model": provenance.VERIFIED},
    },
    {
        "retailer": "The Good Guys",
        "url": None,
        "values": {
            "model_on_page": "HW-Q930H/XY",
            "advertised_price": 1699.0,
            "condition": "NEW",
            "seller_notes": (
                "Last observed headline price from the live product page. Older ~$999 search "
                "snippets are stale and must not be imported as current."
            ),
        },
        "verification": {"model": provenance.VERIFIED},
    },
]


def seed_q930h(conn: sqlite3.Connection) -> int | None:
    """Create the Q930H board. Returns the product id, or None if it already exists."""
    if store.product_by_model(conn, "HW-Q930H/XY"):
        return None

    product_id = store.create_product(
        conn,
        {
            "name": "Samsung Q-Series 9.1.4ch Soundbar",
            "model": "HW-Q930H/XY",
            "brand": "Samsung",
            "category": "soundbar",
            "generation": "H series",
            "verdict": "MAYBE",
            "trigger_price": 900.0,
            "excellent_price": 850.0,
            "historical_low_price": 800.0,
            "lowest_known_notes": (
                "No confirmed delivered low recorded yet. Historical-low territory is set at "
                "$800 delivered from prior market observation, not from a verified purchase."
            ),
            "fit_notes": (
                "Preferred over the Q990H: the Q990 system is too large / excessive for the "
                "available room layout."
            ),
            "notes": (
                "Targets are DELIVERED prices, not headline. Trigger $900, excellent $850 or "
                "less, historical-low territory around $800."
            ),
            "specs": {
                "channels": "9.1.4",
                "dolby_atmos": True,
                "dts_x": True,
                "wireless_rears": True,
                "rear_quantity": 2,
                "system_notes": "Soundbar + subwoofer + 2 rear speakers.",
            },
            "components": {
                "subwoofer": {"note": "dimensions and weight not yet confirmed"},
                "rear_speakers": {"quantity": 2, "note": "dimensions and weight not yet confirmed"},
            },
        },
    )

    for entry in Q930H_LISTINGS:
        retailer = store.ensure_retailer(conn, entry["retailer"])
        listing_id = store.create_listing(
            conn,
            {
                "product_id": product_id,
                "retailer_id": retailer["id"],
                "url": entry["url"],
                "condition": "NEW",
            },
        )
        provenance.apply_values(
            conn,
            listing_id,
            entry["values"],
            state=provenance.IMPORTED,
            source="seed",
            note="Seeded from prior research notes",
        )
        conn.execute(
            "UPDATE listings SET last_checked_at = ? WHERE id = ?", (utcnow(), listing_id)
        )
        provenance.sync_verification_from_provenance(conn, listing_id)
        for aspect, value in entry.get("verification", {}).items():
            status, note = value if isinstance(value, tuple) else (value, None)
            provenance.set_verification(conn, listing_id, aspect, status, note)
        store.record_observation(conn, listing_id, source="seed", note="initial research figure")

    conn.execute(
        "INSERT INTO alert_rules (product_id, name, conditions, max_delivered,"
        " require_complete, require_resolved, min_change) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (product_id, "New stock at or under trigger", "NEW", 900.0, 1, 1, 20.0),
    )
    conn.execute(
        "INSERT INTO alert_rules (product_id, name, conditions, max_delivered,"
        " require_complete, require_resolved, min_change) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            product_id,
            "Secondary stock, complete system only",
            "FACTORY_SECOND,CARTON_DAMAGED,EX_DISPLAY,REFURBISHED,USED",
            800.0,
            1,
            1,
            20.0,
        ),
    )
    return product_id


def seed_all() -> dict[str, object]:
    migrate()
    with session() as conn:
        result = {
            "category_fields_added": seed_categories(conn),
            "retailers_added": seed_retailers(conn),
            "q930h_product_id": seed_q930h(conn),
        }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.seed")
    parser.parse_args(argv)
    result = seed_all()
    if result["q930h_product_id"] is None:
        print("HW-Q930H/XY already present, left untouched.")
    else:
        print(f"seeded HW-Q930H/XY as product {result['q930h_product_id']}")
    print(
        f"category fields added: {result['category_fields_added']}, "
        f"retailers added: {result['retailers_added']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
