"""Offer extraction, matching and the arithmetic that turns an offer into a lead.

No test here calls the API. The model's job is to read English; these tests cover
everything either side of that, which is where the mistakes that cost money live.
"""

from __future__ import annotations

import pytest

from app import mailwatch, offers, store
from app.db import connect

# ------------------------------------------------------------------------- the gate


@pytest.mark.parametrize("text", [
    "Spend $2000 or more on TVs & get $500 OFF!",
    "Sign Up, Activate & Get 20% off^ a huge range",
    "Use code SAVENOW at checkout",
    "Half price gift ideas",
    "Get $30 Off* When you Spend $300",
    "Clearance now on",
])
def test_gate_lets_real_offers_through(text):
    assert offers.worth_extracting(text, "")


@pytest.mark.parametrize("text", [
    "Introducing the new Samsung Galaxy range",
    "Your order has shipped",
    "5 ways to get the most from your soundbar",
    "New arrivals this week",
])
def test_gate_keeps_brand_noise_out(text):
    """The control. Without this the gate is just 'always true' and saves nothing."""
    assert not offers.worth_extracting(text, "")


# ------------------------------------------------------------------- the arithmetic


def test_percent_off_projection():
    offer = {"kind": "percent_off", "amount": 20}
    assert offers.projected_price(offer, 1699, 1699) == 1359.2


def test_dollar_off_respects_a_spend_threshold():
    offer = {"kind": "dollar_off", "amount": 500, "spend_threshold": 2000}
    assert offers.projected_price(offer, 2400, 2400) == 1900
    assert offers.projected_price(offer, 1500, 1500) is None, "below the threshold, no offer"


def test_nonsense_amounts_are_refused_rather_than_computed():
    assert offers.projected_price({"kind": "percent_off", "amount": 120}, 1000, 1000) is None
    assert offers.projected_price({"kind": "dollar_off", "amount": 5000}, 1000, 1000) is None
    assert offers.projected_price({"kind": "percent_off", "amount": None}, 1000, 1000) is None
    assert offers.projected_price({"kind": "finance", "amount": 10}, 1000, 1000) is None


# --------------------------------------------------------------------- the matching


def armed_board(db):
    """Q930H with a confirmed $869 delivered price, so projections have a basis."""
    from app import provenance
    with connect(db) as conn:
        product = store.product_by_model(conn, "HW-Q930H/XY")
        listing = store.find_listing(
            conn, product["id"], store.ensure_retailer(conn, "Crowdshop")["id"])
        provenance.set_field(conn, listing["id"], "freight", 0.0, state=provenance.MANUAL)
        conn.commit()
    return db


def test_an_offer_only_discounts_the_retailer_that_sent_it(seeded):
    """The bug Rodney caught on sight: a Good Guys code applied to Crowdshop's price.

    An offer belongs to the shop that sent it. Projecting it from whichever listing
    happens to be cheapest invents a price you cannot buy at any counter.
    """
    armed_board(seeded)   # Crowdshop confirmed at $869; The Good Guys at $1,699
    with connect(seeded) as conn:
        offer = {"kind": "percent_off", "amount": 20, "categories": ["audio"],
                 "retailer_name": "The Good Guys", "summary": "20% off audio"}
        matches = offers.match_products(conn, offer)
        assert len(matches) == 1
        m = matches[0]
        assert "The Good Guys" in m["rationale"]
        assert "Crowdshop" not in m["rationale"]
        # 1699 is The Good Guys' own price, not the board's best of 869.
        assert m["basis_delivered"] == 1699.0
        assert m["projected_delivered"] == 1359.2


def test_the_control_the_same_offer_from_crowdshop_uses_crowdshops_price(seeded):
    armed_board(seeded)
    with connect(seeded) as conn:
        m = offers.match_products(conn, {
            "kind": "percent_off", "amount": 20, "categories": ["audio"],
            "retailer_name": "Crowdshop", "summary": "20% off audio"})[0]
        assert m["basis_delivered"] == 869.0
        assert m["projected_delivered"] == 695.2


def test_an_offer_from_a_shop_not_on_the_board_matches_nothing(seeded):
    armed_board(seeded)
    with connect(seeded) as conn:
        assert offers.match_products(conn, {
            "kind": "percent_off", "amount": 20, "categories": ["audio"],
            "retailer_name": "Betta", "summary": "20% off audio"}) == []


def test_an_offer_with_no_retailer_matches_nothing(seeded):
    armed_board(seeded)
    with connect(seeded) as conn:
        assert offers.match_products(conn, {
            "kind": "percent_off", "amount": 20, "categories": ["audio"]}) == []


def test_a_projection_from_an_unconfirmed_price_never_claims_to_cross_the_trigger(seeded):
    """Harvey Norman's freight is unknown, so a discount on it is doubly provisional."""
    with connect(seeded) as conn:
        m = offers.match_products(conn, {
            "kind": "percent_off", "amount": 60, "categories": ["audio"],
            "retailer_name": "Harvey Norman", "summary": "60% off"})[0]
        assert m["projected_delivered"] == 678.0
        assert m["crosses_trigger"] is False
        assert "before freight, which is still unknown" in m["rationale"]


def test_an_offer_that_actually_crosses_the_trigger(conn):
    """The case worth being told about: over target, and the offer brings it under."""
    from app import provenance

    pid = store.create_product(conn, {
        "name": "LG C4 65", "model": "OLED65C4PSA", "category": "tv",
        "trigger_price": 2200, "excellent_price": 2000})
    retailer = store.ensure_retailer(conn, "Bing Lee")
    listing = store.create_listing(conn, {"product_id": pid, "retailer_id": retailer["id"]})
    provenance.set_field(conn, listing, "advertised_price", 2450.0, state=provenance.MANUAL)
    provenance.set_field(conn, listing, "freight", 0.0, state=provenance.MANUAL)
    conn.commit()

    m = offers.match_products(conn, {
        "kind": "dollar_off", "amount": 500, "spend_threshold": 2000,
        "categories": ["tv"], "retailer_name": "Bing Lee",
        "summary": "$500 off TVs over $2000"})[0]
    assert m["basis_delivered"] == 2450.0
    assert m["projected_delivered"] == 1950.0
    assert m["crosses_trigger"] is True
    assert "under your $2,200 trigger" in m["rationale"]


def test_an_offer_on_an_unrelated_category_matches_nothing(seeded):
    armed_board(seeded)
    with connect(seeded) as conn:
        assert offers.match_products(conn, {
            "kind": "percent_off", "amount": 20, "categories": ["phone"],
            "retailer_name": "Crowdshop", "summary": "20% off phones"}) == []


def test_storewide_reaches_the_sending_retailers_listing(seeded):
    armed_board(seeded)
    with connect(seeded) as conn:
        matches = offers.match_products(conn, {
            "kind": "dollar_off", "amount": 50, "categories": ["storewide"],
            "retailer_name": "Crowdshop", "summary": "$50 off storewide"})
        assert [m["product_name"] for m in matches] == ["Samsung Q-Series 9.1.4ch Soundbar"]
        assert matches[0]["projected_delivered"] == 819.0


def test_a_bought_product_is_not_matched(seeded):
    armed_board(seeded)
    with connect(seeded) as conn:
        product = store.product_by_model(conn, "HW-Q930H/XY")
        store.record_purchase(conn, product["id"], {"price_paid": 869})
        conn.commit()
        assert offers.match_products(conn, {
            "kind": "percent_off", "amount": 20, "categories": ["audio"],
            "retailer_name": "Crowdshop"}) == []


# -------------------------------------------------------------------- persistence


SAMPLE = {
    "message_id": "<abc123@email.thegoodguys.com.au>",
    "retailer_name": "The Good Guys",
    "subject": "20% off a huge range",
    "received_at": "2026-09-10T09:00:00Z",
    "kind": "percent_off", "amount": 20, "spend_threshold": None,
    "applies_to": "a huge range instore and online",
    "categories": ["storewide"], "excludes": "Apple, Dyson, gift cards",
    "code": None, "expires": "2026-09-13", "requires_signup": True,
    "confidence": "medium", "summary": "20% off a wide range, needs StoreCash signup",
    "extracted_by": "test",
}


def test_recording_an_offer_stores_it_with_its_matches(seeded):
    armed_board(seeded)
    with connect(seeded) as conn:
        recorded = offers.record_offer(conn, dict(SAMPLE))
        assert recorded["retailer_name"] == "The Good Guys"
        assert recorded["categories"] == ["storewide"]
        assert recorded["requires_signup"] == 1
        assert len(recorded["matches"]) == 1
        # Projected from The Good Guys' own $1,699, because they sent the offer.
        assert recorded["matches"][0]["basis_delivered"] == 1699.0
        assert recorded["matches"][0]["projected_delivered"] == 1359.2


def test_the_same_email_is_never_recorded_twice(seeded):
    with connect(seeded) as conn:
        assert offers.record_offer(conn, dict(SAMPLE)) is not None
        assert offers.record_offer(conn, dict(SAMPLE)) is None, "Message-ID is the dedupe key"


def test_an_expired_offer_drops_out_of_the_live_list(seeded):
    with connect(seeded) as conn:
        offers.record_offer(conn, dict(SAMPLE, expires="2020-01-01",
                                       message_id="<old@x>"))
        offers.record_offer(conn, dict(SAMPLE, expires="2099-01-01",
                                       message_id="<new@x>"))
        conn.commit()
        live = offers.list_offers(conn, only_live=True)
        assert [o["message_id"] for o in live] == ["<new@x>"]
        assert len(offers.list_offers(conn, only_live=False)) == 2


def test_an_offer_with_no_expiry_counts_as_live(seeded):
    with connect(seeded) as conn:
        offers.record_offer(conn, dict(SAMPLE, expires=None))
        conn.commit()
        assert len(offers.list_offers(conn, only_live=True)) == 1


# ------------------------------------------------------------- an offer is not a price


def test_recording_an_offer_never_touches_a_listing(seeded):
    """The standing rule. An offer is a lead; the board's prices stay as they were."""
    armed_board(seeded)
    with connect(seeded) as conn:
        before = [dict(r) for r in conn.execute(
            "SELECT id, advertised_price, freight, coupon_discount FROM listings ORDER BY id")]
        offers.record_offer(conn, dict(SAMPLE))
        conn.commit()
        after = [dict(r) for r in conn.execute(
            "SELECT id, advertised_price, freight, coupon_discount FROM listings ORDER BY id")]
    assert before == after


# ----------------------------------------------------------------- the mail reader


def test_only_known_retailers_are_read():
    assert mailwatch.retailer_for("JB Hi-Fi <deals@email.jbhifi.com.au>") == "JB Hi-Fi"
    assert mailwatch.retailer_for("TGG <x@email.thegoodguys.com.au>") == "The Good Guys"
    assert mailwatch.retailer_for("Mum <mum@example.com>") is None, "personal mail is never opened"
    assert mailwatch.retailer_for("") is None


def test_order_mail_is_skipped_even_though_the_domain_matches():
    """Order confirmations carry no offers and do carry personal details."""
    assert mailwatch.retailer_for("JB <noreply@order.jbhifi.com.au>") is None


def test_html_bodies_are_flattened_to_readable_text():
    import email.message
    msg = email.message.EmailMessage()
    msg.set_content("<p>Get <b>20% off</b></p><script>evil()</script>", subtype="html")
    text = mailwatch.body_text(msg)
    assert "20% off" in text
    assert "evil()" not in text and "<b>" not in text
