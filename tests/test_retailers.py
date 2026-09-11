"""Adapter normalisation. An adapter must never invent a value it could not read."""

from __future__ import annotations

import pytest

from app import retailers
from app.retailers import base, crowdshop

PRODUCT_PAGE = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"Samsung Q930H Soundbar",
 "mpn":"HW-Q930H/XY",
 "offers":{"@type":"Offer","price":"1699.00","priceCurrency":"AUD",
           "availability":"https://schema.org/InStock"}}
</script></head><body><p>Free delivery shown at $0</p></body></html>
"""

NO_PRICE_PAGE = """
<html><head><script type="application/ld+json">
{"@type":"Product","mpn":"HW-Q930H/XY","offers":{"@type":"Offer","availability":"OutOfStock"}}
</script></head><body>Call for price</body></html>
"""

WRONG_MODEL_PAGE = PRODUCT_PAGE.replace("HW-Q930H/XY", "HW-Q990H/XY")

RANGE_PAGE = """
<html><head><script type="application/ld+json">
{"@type":"Product","mpn":"HW-Q930H/XY"}
</script></head>
<body><div class="price-guide">Price guide: $869 - $889</div>
<div class="shipping">Delivery: $0</div></body></html>
"""


def test_json_ld_price_model_and_stock_are_normalised():
    obs = base.observation_from_json_ld(PRODUCT_PAGE, "HW-Q930H/XY")
    assert obs.advertised_price == 1699.0
    assert obs.model_on_page == "HW-Q930H/XY"
    assert obs.stock_status == "In Stock"
    assert obs.warnings == []


def test_a_page_without_a_price_reports_unresolved_not_zero():
    obs = base.observation_from_json_ld(NO_PRICE_PAGE, "HW-Q930H/XY")
    assert obs.advertised_price is None
    assert "advertised_price" in obs.unresolved
    assert "advertised_price" not in obs.to_values(), "unresolved fields must not be written"


def test_model_mismatch_is_warned_about_not_silently_accepted():
    obs = base.observation_from_json_ld(WRONG_MODEL_PAGE, "HW-Q930H/XY")
    assert obs.warnings and "model mismatch" in obs.warnings[0]


def test_model_matching_helper():
    assert base.model_matches("HW-Q930H/XY", "hw-q930h/xy")
    assert base.model_matches("HW-Q930H/XY", "Samsung HW-Q930H/XY Soundbar")
    assert not base.model_matches("HW-Q930H/XY", "HW-Q990H/XY")
    assert not base.model_matches("HW-Q930H/XY", None)


def test_price_parsing_rejects_text_and_handles_separators():
    assert base.parse_price("$1,699.00") == 1699.0
    assert base.parse_price("Now $869") == 869.0
    assert base.parse_price("Call for price") is None
    assert base.parse_price(None) is None


def test_crowdshop_keeps_the_range_and_never_records_zero_freight():
    obs = crowdshop.CrowdshopAdapter().parse(RANGE_PAGE, "HW-Q930H/XY")
    assert obs.price_guide == "869-889"
    assert obs.advertised_price == 869.0, "the low end is the headline figure"
    assert obs.freight is None, "a displayed $0 delivery is not confirmation of free shipping"
    assert "freight" not in obs.to_values()


def test_every_adapter_declares_what_it_cannot_read():
    registry = retailers.available_adapters()
    assert {"crowdshop", "harvey_norman", "jb_hifi", "the_good_guys", "appliance_central"} <= set(
        registry
    )
    for slug, cls in registry.items():
        assert isinstance(cls.never_scrapable, tuple), slug
        adapter = retailers.get_adapter(slug)
        assert adapter.name and adapter.homepage, slug


def test_unknown_adapter_slug_returns_none_rather_than_raising():
    assert retailers.get_adapter("not_a_retailer") is None
    assert retailers.get_adapter(None) is None


# A trimmed copy of what harveynorman.com.au actually returned on 2026-09-11: an
# Imperva/Incapsula challenge served with HTTP 200.
INCAPSULA_CHALLENGE = """
<!DOCTYPE html><html><head><noscript><title>Pardon Our Interruption</title></noscript>
<meta name="robots" content="noindex, nofollow"></head>
<body><h1>Pardon Our Interruption</h1>
<p>As you were browsing something about your browser made us think you were a bot.</p>
<script src="/_Incapsula_Resource?SWJIYLWA=719d34d31c8e3a6e6fffd425f7e032f3"></script>
</body></html>
"""

CLOUDFLARE_CHALLENGE = """
<html><head><title>Just a moment...</title></head>
<body><div id="cf-browser-verification">Checking your browser before accessing the site.</div>
</body></html>
"""


def test_a_challenge_page_is_detected_not_read_as_an_empty_product():
    assert base.detect_block(INCAPSULA_CHALLENGE) == "pardon our interruption"
    # Which Cloudflare marker matches first is an implementation detail; that one does is not.
    assert base.detect_block(CLOUDFLARE_CHALLENGE) is not None


def test_a_real_product_page_is_not_mistaken_for_a_challenge():
    """The control. Without this the detector could pass by flagging everything."""
    assert base.detect_block(PRODUCT_PAGE) is None
    assert base.detect_block(NO_PRICE_PAGE) is None
    assert base.detect_block(RANGE_PAGE) is None


def test_fetch_raises_on_a_challenge_page_served_with_http_200(monkeypatch):
    """A block must reach the watcher as an error, never as an unresolved price."""

    class FakeResponse:
        status_code = 200
        text = INCAPSULA_CHALLENGE

    monkeypatch.setattr(base, "requests", type("R", (), {"get": staticmethod(lambda *a, **k: FakeResponse())}))
    adapter = retailers.get_adapter("harvey_norman")
    adapter.config.request_delay = 0
    with pytest.raises(base.FetchError, match="bot-protection interstitial"):
        adapter.fetch("https://www.harveynorman.com.au/anything")


def test_fetch_returns_the_body_for_a_real_page(monkeypatch):
    """The other half of the control: the same path must succeed on a genuine page."""

    class FakeResponse:
        status_code = 200
        text = PRODUCT_PAGE

    monkeypatch.setattr(base, "requests", type("R", (), {"get": staticmethod(lambda *a, **k: FakeResponse())}))
    adapter = retailers.get_adapter("harvey_norman")
    adapter.config.request_delay = 0
    assert "HW-Q930H/XY" in adapter.fetch("https://www.harveynorman.com.au/anything")


# --------------------------- a merchant stock number is not a manufacturer model

def _ld(identifiers: str) -> str:
    """A minimal schema.org Product block. `identifiers` is raw JSON key/value text.

    Synthesised rather than captured, deliberately, because the point under test is
    which schema.org KEY carries the value, and a captured page pins only one shape.
    The captured-page fixture elsewhere in this file covers what a real page looks
    like; this one covers the key permutations that page cannot show all of.
    """
    return (
        '<html><script type="application/ld+json">'
        '{"@type": "Product", ' + identifiers + ','
        '"offers": {"@type": "Offer", "price": "1699.00",'
        ' "availability": "https://schema.org/InStock"}}'
        "</script></html>"
    )


def test_a_merchant_stock_number_is_not_compared_against_the_model():
    """JB Hi-Fi publishes sku 893039 on the right product page, and The Good Guys
    50098655. Comparing those tagged two correct listings as faults."""
    obs = base.observation_from_json_ld(_ld('"sku": "893039"'), expected_model="HW-Q930H/XY")
    assert obs.advertised_price == 1699.0, "control: the page was parsed at all"
    assert obs.model_on_page_key == "sku"
    assert not any("mismatch" in w for w in obs.warnings), obs.warnings


def test_an_alphanumeric_stock_number_is_also_not_compared():
    """The earlier fix skipped digits-only identifiers, so a retailer numbering its
    stock SAM-893039 still raised a permanent false mismatch. The key decides now."""
    obs = base.observation_from_json_ld(_ld('"sku": "SAM-893039"'), expected_model="HW-Q930H/XY")
    assert obs.advertised_price == 1699.0, "control: the page was parsed at all"
    assert not any("mismatch" in w for w in obs.warnings), obs.warnings


def test_a_manufacturer_part_number_is_still_compared():
    """The check must survive. Skipping every numeric identifier disabled it outright
    for the two retailers it was meant to help."""
    obs = base.observation_from_json_ld(_ld('"mpn": "HW-Q930F/XY"'), expected_model="HW-Q930H/XY")
    assert obs.advertised_price == 1699.0, "control: the page was parsed at all"
    assert any("mismatch" in w for w in obs.warnings), "a wrong mpn must flag"


def test_a_manufacturer_key_wins_when_the_page_publishes_both():
    obs = base.observation_from_json_ld(
        _ld('"sku": "893039", "mpn": "HW-Q930F/XY"'), expected_model="HW-Q930H/XY")
    assert obs.model_on_page_key == "mpn"
    assert any("mismatch" in w for w in obs.warnings)


def test_a_dropped_regional_suffix_is_the_same_product():
    obs = base.observation_from_json_ld(_ld('"mpn": "HW-Q930H"'), expected_model="HW-Q930H/XY")
    assert obs.advertised_price == 1699.0, "control: the page was parsed at all"
    assert not any("mismatch" in w for w in obs.warnings), obs.warnings


@pytest.mark.parametrize("found", ["HW-Q930", "XY", "930", "Q9"])
def test_a_substring_of_the_model_is_not_the_model(found):
    """model_matches accepted a substring either way, so HW-Q930 (a different
    soundbar) passed, and so did any two characters that happened to appear."""
    assert not base.model_matches("HW-Q930H/XY", found)


def test_the_same_model_punctuated_differently_still_matches():
    assert base.model_matches("HW-Q930H/XY", "HW Q930H XY")


# ------------------------------------- the price guide must not invent a figure

SHIPPING_PAGE = """
<html><body>
  <p>Dispatch 3 to 5 business days. Free returns within 30 days.</p>
  <div class="price">Price guide: $869 - $889</div>
</body></html>
"""


def test_a_shipping_sentence_is_not_a_price_range():
    """"Dispatch 3 to 5 business days" used to yield a range of 3 to 5, and parse()
    promoted $3 as the advertised price. The adapter must never invent a figure, and
    because the historical low never rises again that $3 would have been permanent.
    """
    low, high = crowdshop._price_range(SHIPPING_PAGE)
    assert (low, high) == (869.0, 889.0), "the real guide must win, not the first N to M"


def test_a_range_needs_currency_on_both_sides():
    assert crowdshop._price_range("<p>Dispatch 3 to 5 business days</p>") == (None, None)
    assert crowdshop._price_range("<p>Ships in 2-3 days</p>") == (None, None)


def test_the_separator_is_an_alternation_not_a_character_class():
    """`[-–to]{1,2}` matched "tt" and "oo", which widened the surface for the bug above."""
    assert crowdshop._price_range("<p>$100 tt $200</p>") == (None, None)
    assert crowdshop._price_range("<p>$100 oo $200</p>") == (None, None)


def test_every_separator_the_retailer_actually_uses_still_parses():
    """Control: the narrowing must not break the thing the regex exists for."""
    for text, want in (
        ("<p>$869 - $889</p>", (869.0, 889.0)),
        ("<p>$869 – $889</p>", (869.0, 889.0)),
        ("<p>$869 to $889</p>", (869.0, 889.0)),
        ("<p>$1,049.00-$1,199.00</p>", (1049.0, 1199.0)),
    ):
        assert crowdshop._price_range(text) == want, text


def test_the_model_inside_a_longer_page_title_still_matches():
    """One-directional containment: a page wrapping the model in a title is fine."""
    assert base.model_matches("HW-Q930H/XY", "Samsung HW-Q930H/XY Soundbar")


# ---------------------------- the page's own product, not a carousel entry

def _two_blocks(first: str, second: str) -> str:
    return (
        '<html>'
        '<script type="application/ld+json">{"@type": "Product", ' + first + '}</script>'
        '<script type="application/ld+json">{"@type": "Product", ' + second + '}</script>'
        '</html>'
    )


CAROUSEL = '"sku": "111111", "offers": {"@type": "Offer", "price": "249.00"}'
REAL = '"mpn": "HW-Q930H/XY", "offers": {"@type": "Offer", "price": "1699.00"}'
STUB = '"name": "Samsung"'


def test_a_leading_carousel_block_does_not_win():
    """Retailers emit recommendation Products before their own. The old loop took the
    first and broke, so a carousel entry's price was written to the listing, and with
    merchant numbers no longer compared it would land without raising a mismatch."""
    obs = base.observation_from_json_ld(_two_blocks(CAROUSEL, REAL),
                                        expected_model="HW-Q930H/XY")
    assert obs.advertised_price == 1699.0, "the page's own product must win"
    assert obs.model_on_page == "HW-Q930H/XY"
    assert not any("mismatch" in w for w in obs.warnings), obs.warnings


def test_a_leading_stub_block_does_not_swallow_the_price():
    """A Product block with no offers used to break the loop, leaving the price
    unresolved forever while the real block below was never examined."""
    obs = base.observation_from_json_ld(_two_blocks(STUB, REAL),
                                        expected_model="HW-Q930H/XY")
    assert obs.advertised_price == 1699.0
    assert "advertised_price" not in obs.unresolved


def test_with_no_expected_model_the_first_priced_block_wins():
    """Control: the selection must still work when there is nothing to match against."""
    obs = base.observation_from_json_ld(_two_blocks(CAROUSEL, REAL))
    assert obs.advertised_price == 249.0, "first priced block, in document order"


def test_a_single_product_page_is_unaffected():
    """Control: the ordinary case must not change."""
    obs = base.observation_from_json_ld(
        '<html><script type="application/ld+json">{"@type": "Product", ' + REAL + '}</script></html>',
        expected_model="HW-Q930H/XY")
    assert obs.advertised_price == 1699.0 and obs.model_on_page == "HW-Q930H/XY"
