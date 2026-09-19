"""Manual overrides, staleness, and the guarantee that a lock beats an automated write."""

from __future__ import annotations

import pytest

from app import provenance, store
from app.db import utcnow


@pytest.fixture()
def listing(conn):
    product_id = store.create_product(conn, {"name": "Test bar", "model": "TEST-1"})
    retailer = store.ensure_retailer(conn, "Test Retailer")
    return store.create_listing(
        conn, {"product_id": product_id, "retailer_id": retailer["id"]}
    )


def value(conn, listing_id, field):
    return conn.execute(f"SELECT {field} FROM listings WHERE id = ?", (listing_id,)).fetchone()[0]


def test_manual_edit_locks_the_field(conn, listing):
    provenance.set_field(conn, listing, "freight", 55, state=provenance.MANUAL, source="ui")
    prov = provenance.provenance_map(conn, listing)["freight"]
    assert prov["state"] == provenance.MANUAL
    assert prov["manual_locked"] == 1


def test_automated_write_cannot_overwrite_a_locked_field(conn, listing):
    provenance.set_field(conn, listing, "freight", 55, state=provenance.MANUAL, source="ui")
    wrote = provenance.set_field(
        conn, listing, "freight", 0, state=provenance.LIVE, source="scraper"
    )
    assert wrote is False
    assert value(conn, listing, "freight") == 55


def test_automated_write_lands_on_unlocked_fields_in_the_same_batch(conn, listing):
    provenance.set_field(conn, listing, "freight", 55, state=provenance.MANUAL, source="ui")
    result = provenance.apply_values(
        conn,
        listing,
        {"freight": 0, "advertised_price": 869},
        state=provenance.LIVE,
        source="scraper",
    )
    assert result["blocked"] == ["freight"]
    assert result["written"] == ["advertised_price"]
    assert value(conn, listing, "freight") == 55
    assert value(conn, listing, "advertised_price") == 869


def test_clear_override_hands_the_field_back_to_automation(conn, listing):
    provenance.set_field(conn, listing, "freight", 55, state=provenance.MANUAL, source="ui")
    provenance.clear_override(conn, listing, "freight")
    prov = provenance.provenance_map(conn, listing)["freight"]
    assert prov["manual_locked"] == 0
    assert prov["state"] == provenance.UNVERIFIED
    assert value(conn, listing, "freight") == 55, "clearing the lock must not clear the value"
    assert provenance.set_field(
        conn, listing, "freight", 12, state=provenance.LIVE, source="scraper"
    )
    assert value(conn, listing, "freight") == 12


def test_empty_string_clears_a_value_rather_than_storing_zero(conn, listing):
    provenance.set_field(conn, listing, "freight", 55, state=provenance.MANUAL)
    provenance.set_field(conn, listing, "freight", "", state=provenance.MANUAL)
    assert value(conn, listing, "freight") is None


def test_currency_formatting_is_accepted_from_the_ui(conn, listing):
    provenance.set_field(conn, listing, "advertised_price", "$1,059.00", state=provenance.MANUAL)
    assert value(conn, listing, "advertised_price") == 1059.0


def test_rubbish_in_a_numeric_field_is_rejected_not_coerced(conn, listing):
    with pytest.raises(provenance.FieldError):
        provenance.set_field(conn, listing, "advertised_price", "call us", state=provenance.MANUAL)


def test_untracked_field_is_rejected(conn, listing):
    with pytest.raises(provenance.FieldError):
        provenance.set_field(conn, listing, "id", 7, state=provenance.MANUAL)


def test_promo_end_date_is_accepted_and_locks_like_any_other_manual_field(conn, listing):
    provenance.set_field(
        conn, listing, "price_valid_until", "2026-09-21", state=provenance.MANUAL, source="ui"
    )
    prov = provenance.provenance_map(conn, listing)["price_valid_until"]
    assert prov["state"] == provenance.MANUAL
    assert prov["manual_locked"] == 1
    assert value(conn, listing, "price_valid_until") == "2026-09-21"


def test_promo_end_date_rejects_a_non_date(conn, listing):
    with pytest.raises(provenance.FieldError):
        provenance.set_field(
            conn, listing, "price_valid_until", "Monday 21/09", state=provenance.MANUAL
        )


def test_promo_end_date_empty_string_clears_it(conn, listing):
    provenance.set_field(conn, listing, "price_valid_until", "2026-09-21", state=provenance.MANUAL)
    provenance.set_field(conn, listing, "price_valid_until", "", state=provenance.MANUAL)
    assert value(conn, listing, "price_valid_until") is None


def test_stale_marking_skips_manual_fields(conn, listing):
    provenance.set_field(conn, listing, "advertised_price", 869, state=provenance.LIVE)
    provenance.set_field(conn, listing, "freight", 55, state=provenance.MANUAL)
    conn.execute(
        "UPDATE field_provenance SET updated_at = '2000-01-01T00:00:00Z' WHERE listing_id = ?",
        (listing,),
    )
    marked = provenance.mark_stale(conn, listing, stale_after_days=7)
    assert marked == ["advertised_price"]
    prov = provenance.provenance_map(conn, listing)
    assert prov["advertised_price"]["state"] == provenance.STALE
    assert prov["freight"]["state"] == provenance.MANUAL


def test_fresh_fields_are_not_marked_stale(conn, listing):
    provenance.set_field(conn, listing, "advertised_price", 869, state=provenance.LIVE)
    assert provenance.mark_stale(conn, listing, stale_after_days=7) == []


def test_verification_sync_reflects_provenance_but_not_human_verdicts(conn, listing):
    provenance.set_field(conn, listing, "advertised_price", 869, state=provenance.LIVE)
    provenance.set_verification(conn, listing, "model", provenance.VERIFIED, "checked the box")
    provenance.set_field(conn, listing, "model_on_page", "OTHER-1", state=provenance.LIVE)
    provenance.sync_verification_from_provenance(conn, listing)
    verification = provenance.verification_map(conn, listing)
    assert verification["price"]["status"] == provenance.LIVE
    assert verification["model"]["status"] == provenance.VERIFIED, "human verdict must survive"
    assert utcnow()
