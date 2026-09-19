"""Auto-deriving historical_low_price/excellent_price/trigger_price from
lowest_known_price (issue #101).

A confirmed lowest_known_price should not leave a product un-actionable just because
nobody typed a target in by hand. store.maybe_derive_price_targets fills any of the
three that is still NULL, and never touches one that already has a value - the same
"a manual edit beats an automated write" discipline provenance.py already enforces for
listings, just as a plain boolean per field (migrations/0014) rather than the full
state machine, since a product only ever has one auto-writer for these three fields.

historical_low_price is not just a display default the way the other two are:
pricing.classify() reads it directly and checks it first, so deriving it can change a
listing's live classification, not only what the edit dialog shows.
"""

from __future__ import annotations

from app import pricing, store


def test_derives_all_three_targets_from_lowest_known_price(conn):
    product_id = store.create_product(conn, {"name": "Soundbar", "model": "SB-1"})
    store.update_product(conn, product_id, {"lowest_known_price": 1000.0})
    conn.commit()

    product = store.get_product(conn, product_id)
    assert product["historical_low_price"] == 1000.0
    assert product["excellent_price"] == 1000.0
    assert product["trigger_price"] == 1100.0
    assert product["historical_low_price_auto"] == 1
    assert product["excellent_price_auto"] == 1
    assert product["trigger_price_auto"] == 1


def test_does_nothing_without_a_lowest_known_price(conn):
    product_id = store.create_product(conn, {"name": "Soundbar", "model": "SB-2"})
    conn.commit()

    product = store.get_product(conn, product_id)
    assert product["historical_low_price"] is None
    assert product["trigger_price"] is None
    assert product["excellent_price"] is None
    assert product["historical_low_price_auto"] == 0
    assert product["trigger_price_auto"] == 0
    assert product["excellent_price_auto"] == 0


def test_never_overrides_a_value_the_user_set_by_hand(conn):
    product_id = store.create_product(conn, {
        "name": "Soundbar", "model": "SB-3",
        "historical_low_price": 900.0, "trigger_price": 1500.0, "excellent_price": 1200.0,
    })
    store.update_product(conn, product_id, {"lowest_known_price": 1000.0})
    conn.commit()

    product = store.get_product(conn, product_id)
    assert product["historical_low_price"] == 900.0
    assert product["trigger_price"] == 1500.0
    assert product["excellent_price"] == 1200.0
    assert product["historical_low_price_auto"] == 0
    assert product["trigger_price_auto"] == 0
    assert product["excellent_price_auto"] == 0


def test_fills_only_the_targets_left_unset(conn):
    product_id = store.create_product(conn, {"name": "Soundbar", "model": "SB-4",
                                               "excellent_price": 950.0})
    store.update_product(conn, product_id, {"lowest_known_price": 1000.0})
    conn.commit()

    product = store.get_product(conn, product_id)
    assert product["excellent_price"] == 950.0
    assert product["excellent_price_auto"] == 0
    assert product["historical_low_price"] == 1000.0
    assert product["historical_low_price_auto"] == 1
    assert product["trigger_price"] == 1100.0
    assert product["trigger_price_auto"] == 1


def test_creating_with_a_known_low_and_no_targets_derives_immediately(conn):
    product_id = store.create_product(conn, {
        "name": "Soundbar", "model": "SB-5", "lowest_known_price": 800.0,
    })
    conn.commit()

    product = store.get_product(conn, product_id)
    assert product["historical_low_price"] == 800.0
    assert product["excellent_price"] == 800.0
    assert product["trigger_price"] == 880.0


def test_hand_typed_change_locks_the_field(conn):
    product_id = store.create_product(conn, {"name": "Soundbar", "model": "SB-6",
                                               "lowest_known_price": 1000.0})
    conn.commit()
    product = store.get_product(conn, product_id)
    assert product["trigger_price_auto"] == 1
    assert product["historical_low_price_auto"] == 1

    # A real edit: a different number than the auto-filled one, on both fields.
    store.update_product(conn, product_id, {"trigger_price": 1300.0, "historical_low_price": 850.0})
    conn.commit()
    product = store.get_product(conn, product_id)
    assert product["trigger_price"] == 1300.0
    assert product["trigger_price_auto"] == 0
    assert product["historical_low_price"] == 850.0
    assert product["historical_low_price_auto"] == 0

    # A lower low afterwards must not overwrite either now-locked field.
    store.update_product(conn, product_id, {"lowest_known_price": 700.0})
    conn.commit()
    product = store.get_product(conn, product_id)
    assert product["trigger_price"] == 1300.0
    assert product["trigger_price_auto"] == 0
    assert product["historical_low_price"] == 850.0
    assert product["historical_low_price_auto"] == 0


def test_resubmitting_the_same_value_does_not_lock_an_auto_field(conn):
    """The edit dialog's Save always resends every field on the form (app.js ep-save),
    whether or not the user touched it. Only an actual change should count as a
    hand-typed edit, or opening Edit for something unrelated and saving would silently
    lock every auto-derived target the first time round."""
    product_id = store.create_product(conn, {"name": "Soundbar", "model": "SB-7",
                                               "lowest_known_price": 1000.0})
    conn.commit()
    product = store.get_product(conn, product_id)
    assert product["trigger_price_auto"] == 1
    assert product["excellent_price_auto"] == 1
    assert product["historical_low_price_auto"] == 1

    # Resave with the exact same numbers still in the form, plus an unrelated change.
    store.update_product(conn, product_id, {
        "notes": "just editing notes",
        "trigger_price": product["trigger_price"],
        "excellent_price": product["excellent_price"],
        "historical_low_price": product["historical_low_price"],
    })
    conn.commit()

    product = store.get_product(conn, product_id)
    assert product["trigger_price_auto"] == 1
    assert product["excellent_price_auto"] == 1
    assert product["historical_low_price_auto"] == 1


def test_clearing_a_target_unlocks_it_and_refills_immediately(conn):
    product_id = store.create_product(conn, {
        "name": "Soundbar", "model": "SB-8",
        "lowest_known_price": 1000.0, "trigger_price": 1300.0, "historical_low_price": 850.0,
    })
    conn.commit()
    product = store.get_product(conn, product_id)
    assert product["trigger_price_auto"] == 0  # typed in at creation, not derived
    assert product["historical_low_price_auto"] == 0

    store.update_product(conn, product_id, {"trigger_price": None, "historical_low_price": None})
    conn.commit()

    product = store.get_product(conn, product_id)
    assert product["trigger_price"] == 1100.0
    assert product["trigger_price_auto"] == 1
    assert product["historical_low_price"] == 1000.0
    assert product["historical_low_price_auto"] == 1


def test_maybe_lower_known_low_triggers_derivation(conn):
    """The auto-tracking write path (store.record_observation -> maybe_lower_known_low)
    must derive targets too, not just the PATCH-driven edit-dialog path."""
    product_id = store.create_product(conn, {"name": "Soundbar", "model": "SB-9"})
    retailer = store.ensure_retailer(conn, "Test Retailer")
    listing_id = store.create_listing(conn, {
        "product_id": product_id, "retailer_id": retailer["id"],
        "advertised_price": 900.0, "freight": 0,
    })
    conn.commit()

    store.record_observation(conn, listing_id, source="test")
    conn.commit()

    product = store.get_product(conn, product_id)
    assert product["lowest_known_price"] == 900.0
    assert product["historical_low_price"] == 900.0
    assert product["excellent_price"] == 900.0
    assert product["trigger_price"] == 990.0
    assert product["historical_low_price_auto"] == 1
    assert product["excellent_price_auto"] == 1
    assert product["trigger_price_auto"] == 1


def test_derived_historical_low_changes_live_classification(conn):
    """historical_low_price is not just a display default: pricing.classify() reads it
    directly, so a product that already has a lowest_known_price but no
    historical_low_price can have a listing's rating change the moment this runs."""
    product_id = store.create_product(conn, {
        "name": "Soundbar", "model": "SB-10", "lowest_known_price": 900.0,
        "excellent_price": 950.0,
    })
    conn.commit()
    product = dict(store.get_product(conn, product_id))

    # Before historical_low_price exists, a price matching the known low rates on
    # excellent_price alone.
    del product["historical_low_price"]  # simulate the pre-derivation state
    assert pricing.classify(900.0, {**product, "historical_low_price": None}) == pricing.EXCELLENT

    # maybe_derive_price_targets already ran during create_product above (lowest_known_price
    # was present and historical_low_price was unset), so it should already be filled.
    product = dict(store.get_product(conn, product_id))
    assert product["historical_low_price"] == 900.0
    assert pricing.classify(900.0, product) == pricing.HISTORICAL_LOW
