"""Adapter normalisation. An adapter must never invent a value it could not read."""

from __future__ import annotations

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
