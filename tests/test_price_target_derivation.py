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

store.run_price_target_backfill is the follow-up fix: maybe_derive_price_targets only
ever runs from create_product/update_product/maybe_lower_known_low, so a product that
already had a lowest_known_price before #106 shipped sat un-derived until some
unrelated future write happened to touch it. The backfill tests below simulate that
pre-#106 state by writing lowest_known_price directly via SQL, bypassing every path
that would otherwise have triggered derivation already.
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


def test_backfill_derives_targets_for_a_product_with_no_lowest_known_price(conn):
    product_id = store.create_product(conn, {"name": "Soundbar", "model": "BF-1"})
    conn.commit()

    updated = store.run_price_target_backfill(conn)
    conn.commit()

    assert updated == 0
    product = store.get_product(conn, product_id)
    assert product["historical_low_price"] is None
    assert product["excellent_price"] is None
    assert product["trigger_price"] is None


def test_backfill_derives_targets_for_a_pre_existing_product(conn):
    """The actual bug: a product created (or already sitting) with a lowest_known_price
    but no targets, from before #106 shipped or from any write path that predates it.
    Simulated here by writing lowest_known_price directly, bypassing every path that
    would otherwise have triggered maybe_derive_price_targets already."""
    product_id = store.create_product(conn, {"name": "Soundbar", "model": "BF-2"})
    conn.execute(
        "UPDATE products SET lowest_known_price = ? WHERE id = ?", (500.0, product_id)
    )
    conn.commit()
    product = store.get_product(conn, product_id)
    assert product["historical_low_price"] is None  # confirms the bug's starting state

    updated = store.run_price_target_backfill(conn)
    conn.commit()

    assert updated == 1
    product = store.get_product(conn, product_id)
    assert product["historical_low_price"] == 500.0
    assert product["excellent_price"] == 500.0
    assert product["trigger_price"] == 550.0
    assert product["historical_low_price_auto"] == 1
    assert product["excellent_price_auto"] == 1
    assert product["trigger_price_auto"] == 1


def test_backfill_never_touches_a_hand_set_field(conn):
    """One target hand-set, the other two left null, lowest_known_price set behind
    every write path's back - the backfill must fill only the two still-null fields."""
    product_id = store.create_product(conn, {"name": "Soundbar", "model": "BF-3"})
    conn.execute(
        "UPDATE products SET lowest_known_price = ?, trigger_price = ? WHERE id = ?",
        (500.0, 999.0, product_id),
    )
    conn.commit()

    updated = store.run_price_target_backfill(conn)
    conn.commit()

    assert updated == 1
    product = store.get_product(conn, product_id)
    assert product["trigger_price"] == 999.0
    assert product["trigger_price_auto"] == 0
    assert product["historical_low_price"] == 500.0
    assert product["historical_low_price_auto"] == 1
    assert product["excellent_price"] == 500.0
    assert product["excellent_price_auto"] == 1


def test_backfill_is_a_noop_for_an_already_backfilled_product(conn):
    """A product a normal write path already fixed (e.g. the incidental no-op Edit-Save
    from the bug report) should be left exactly as is - not re-derived, not re-counted."""
    product_id = store.create_product(conn, {
        "name": "Soundbar", "model": "BF-4", "lowest_known_price": 500.0,
    })
    conn.commit()
    product = store.get_product(conn, product_id)
    assert product["historical_low_price"] == 500.0  # create_product already derived it

    updated = store.run_price_target_backfill(conn)
    conn.commit()

    assert updated == 0
    product = store.get_product(conn, product_id)
    assert product["historical_low_price"] == 500.0
    assert product["excellent_price"] == 500.0
    assert product["trigger_price"] == 550.0


def test_backfill_sweeps_a_mixed_board_once_each(conn):
    """Several products in various states in one sweep, matching the real board shape."""
    no_low = store.create_product(conn, {"name": "A", "model": "BF-5"})
    needs_backfill = store.create_product(conn, {"name": "B", "model": "BF-6"})
    conn.execute(
        "UPDATE products SET lowest_known_price = ? WHERE id = ?", (400.0, needs_backfill)
    )
    partially_hand_set = store.create_product(conn, {"name": "C", "model": "BF-7"})
    conn.execute(
        "UPDATE products SET lowest_known_price = ?, excellent_price = ? WHERE id = ?",
        (300.0, 250.0, partially_hand_set),
    )
    already_derived = store.create_product(conn, {
        "name": "D", "model": "BF-8", "lowest_known_price": 600.0,
    })
    conn.commit()

    updated = store.run_price_target_backfill(conn)
    conn.commit()

    assert updated == 2  # needs_backfill and partially_hand_set; the other two are no-ops

    assert store.get_product(conn, no_low)["historical_low_price"] is None

    b = store.get_product(conn, needs_backfill)
    assert b["historical_low_price"] == 400.0
    assert b["excellent_price"] == 400.0
    assert b["trigger_price"] == 440.0

    c = store.get_product(conn, partially_hand_set)
    assert c["excellent_price"] == 250.0
    assert c["excellent_price_auto"] == 0
    assert c["historical_low_price"] == 300.0
    assert c["historical_low_price_auto"] == 1
    assert c["trigger_price"] == 330.0
    assert c["trigger_price_auto"] == 1

    d = store.get_product(conn, already_derived)
    assert d["historical_low_price"] == 600.0
    assert d["excellent_price"] == 600.0
    assert d["trigger_price"] == 660.0


def test_backfill_does_not_reapply_on_a_second_run(conn):
    """The marker row must stop a second sweep from re-scanning - simulated here by
    hand-setting a target after the first run and confirming a second run leaves it
    alone rather than treating it as still-eligible."""
    product_id = store.create_product(conn, {"name": "Soundbar", "model": "BF-9"})
    conn.execute(
        "UPDATE products SET lowest_known_price = ? WHERE id = ?", (700.0, product_id)
    )
    conn.commit()

    first = store.run_price_target_backfill(conn)
    conn.commit()
    assert first == 1

    # Simulate a product created after the sweep ran, with a target still null - if the
    # marker didn't stop a second sweep, this would get swept up too.
    later_product_id = store.create_product(conn, {"name": "Soundbar", "model": "BF-10"})
    conn.execute(
        "UPDATE products SET lowest_known_price = ? WHERE id = ?", (800.0, later_product_id)
    )
    conn.commit()

    second = store.run_price_target_backfill(conn)
    conn.commit()

    assert second == 0
    later = store.get_product(conn, later_product_id)
    assert later["historical_low_price"] is None  # still untouched - not this sweep's job


def test_backfill_startup_sequence_is_idempotent(db):
    """The real lifespan sequence: migrate() then run_price_target_backfill(), across two
    separate startups against the same on-disk database - the second boot must not
    re-derive or re-count anything the first boot already applied."""
    from app.db import connect, migrate

    migrate(db)
    conn = connect(db)
    product_id = store.create_product(conn, {"name": "Soundbar", "model": "BF-11"})
    conn.execute(
        "UPDATE products SET lowest_known_price = ? WHERE id = ?", (900.0, product_id)
    )
    conn.commit()
    conn.close()

    # First "boot".
    migrate(db)
    conn = connect(db)
    first = store.run_price_target_backfill(conn)
    conn.commit()
    conn.close()
    assert first == 1

    # Second "boot" against the same file, nothing new touched by hand in between.
    migrate(db)
    conn = connect(db)
    second = store.run_price_target_backfill(conn)
    product = store.get_product(conn, product_id)
    conn.commit()
    conn.close()

    assert second == 0
    assert product["historical_low_price"] == 900.0
    assert product["trigger_price"] == 990.0


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
