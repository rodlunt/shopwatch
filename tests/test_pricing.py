"""Delivered-price arithmetic, classification and ranking."""

from __future__ import annotations

from app import pricing

TARGETS = {"trigger_price": 900, "excellent_price": 850, "historical_low_price": 800}


def test_delivered_adds_freight_and_subtracts_every_discount():
    result = pricing.delivered_price(1000, freight=50, cashback=100, rebate=25, coupon_discount=15)
    assert result.value == 910.0
    assert result.resolved is True


def test_zero_freight_is_confirmed_free_shipping():
    result = pricing.delivered_price(869, freight=0)
    assert result.value == 869.0
    assert result.resolved is True


def test_null_freight_is_unresolved_not_free():
    result = pricing.delivered_price(869, freight=None)
    assert result.value == 869.0, "the provisional figure still shows"
    assert result.resolved is False, "but it must not claim to be a delivered price"


def test_no_advertised_price_means_no_delivered_price():
    assert pricing.delivered_price(None, freight=0).value is None


def test_price_strings_and_cashback_larger_than_price():
    assert pricing.delivered_price("1,059.00", freight="0").value == 1059.0
    assert pricing.delivered_price(100, freight=0, cashback=250).value == 0.0


def test_classification_thresholds_are_inclusive_and_ordered():
    assert pricing.classify(pricing.delivered_price(800, 0), TARGETS) == pricing.HISTORICAL_LOW
    assert pricing.classify(pricing.delivered_price(799, 0), TARGETS) == pricing.HISTORICAL_LOW
    assert pricing.classify(pricing.delivered_price(850, 0), TARGETS) == pricing.EXCELLENT
    assert pricing.classify(pricing.delivered_price(899, 0), TARGETS) == pricing.TRIGGER_MET
    assert pricing.classify(pricing.delivered_price(900, 0), TARGETS) == pricing.TRIGGER_MET
    assert pricing.classify(pricing.delivered_price(901, 0), TARGETS) == pricing.ABOVE_TARGET


def test_unresolved_freight_cannot_claim_a_good_deal():
    """An 869 headline with unknown freight is not an EXCELLENT buy, it is unresolved."""
    assert pricing.classify(pricing.delivered_price(869, None), TARGETS) == pricing.UNRESOLVED
    # Above target stays above target: freight can only make it worse.
    assert pricing.classify(pricing.delivered_price(1699, None), TARGETS) == pricing.ABOVE_TARGET


def test_unresolved_listing_does_not_outrank_slightly_dearer_confirmed_one():
    unresolved = pricing.delivered_price(869, None)
    confirmed = pricing.delivered_price(880, 0)
    assert pricing.rank_key(unresolved, 60) > pricing.rank_key(confirmed, 60)


def test_unresolved_listing_still_wins_when_it_is_far_cheaper():
    unresolved = pricing.delivered_price(700, None)
    confirmed = pricing.delivered_price(880, 0)
    assert pricing.rank_key(unresolved, 60) < pricing.rank_key(confirmed, 60)


def test_unpriced_listings_sort_last():
    assert pricing.rank_key(pricing.delivered_price(None), 60) > pricing.rank_key(
        pricing.delivered_price(9999, 0), 60
    )


def test_difference_from_historical_low():
    assert pricing.difference_from_low(pricing.delivered_price(869, 0), 800) == 69.0
    assert pricing.difference_from_low(pricing.delivered_price(869, 0), None) is None
