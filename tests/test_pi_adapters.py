"""The Pi retailer adapters, run against saved real pages, with controls.

Every fixture is a trimmed copy of a page captured on 2026-10-26. The controls matter as
much as the happy paths: a parser that "passes" on a page it could not read is the failure
this suite exists to catch, so each retailer has a broken version that must raise.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app import availability as av
from app import robots
from app.retailers import FetchError, get_adapter
from app.retailers.pi_base import ParseFailure

FIX = Path(__file__).parent / "fixtures" / "pi"


def page(name: str) -> str:
    return (FIX / name).read_text()


def parse(slug: str, name: str, model: str | None, product: str | None):
    return get_adapter(slug).parse(page(name), model, product)


# ------------------------------------------------------------------ normaliser


@pytest.mark.parametrize(
    "text, schema, state, limit",
    [
        ("In stock", None, av.IN_STOCK, None),
        ("In stock (limit 1 per customer)", None, av.LIMITED, 1),
        ("In stock, ships same business day if ordered before 2PM (limit 1 per customer)",
         None, av.LIMITED, 1),
        ("In stock (only 1 left)", None, av.LIMITED, 1),
        ("In stock (10 per customer)", None, av.LIMITED, 10),
        ("Expect dispatch 2 to 6 Nov", None, av.DISPATCH_LATER, None),
        ("Available with a lead time Expect dispatch between Nov 02 and Nov 06", None,
         av.DISPATCH_LATER, None),
        ("Out of stock", None, av.OUT_OF_STOCK, None),
        ("Out of stock (5-10 day lead time)", None, av.OUT_OF_STOCK, None),
        ("Sold out", None, av.OUT_OF_STOCK, None),
        ("Backorder", None, av.BACKORDER, None),
        (None, "https://schema.org/InStock", av.IN_STOCK, None),
        (None, "https://schema.org/OutOfStock", av.OUT_OF_STOCK, None),
        (None, "http://schema.org/BackOrder", av.BACKORDER, None),
        (None, None, av.UNKNOWN, None),
        ("Call us", None, av.UNKNOWN, None),
    ],
)
def test_normalise(text, schema, state, limit):
    got = av.normalise(text, schema)
    assert got.state == state
    assert got.unit_limit == limit


def test_visible_words_beat_the_schema_value():
    """A page can say InStock in markup while telling the customer it is sold out."""
    assert av.normalise("Sold out", "https://schema.org/InStock").state == av.OUT_OF_STOCK


# ----------------------------------------------------------- one test per retailer


def test_core_electronics_in_stock_with_a_limit():
    obs = parse("core_electronics", "core_electronics_pi4_2gb_limit.html",
                "SC0193", "Raspberry Pi 4 Model B 2GB")
    assert obs.advertised_price == 109.33
    assert obs.availability == av.LIMITED and obs.unit_limit == 1
    assert obs.availability_text == (
        "In stock, ships same business day if ordered before 2PM (limit 1 per customer)"
    )
    assert obs.stock_status == obs.availability_text
    assert obs.freight is None, "freight is quoted at the cart and must stay unresolved"


def test_core_electronics_plain_in_stock():
    obs = parse("core_electronics", "core_electronics_pi3a_in_stock.html",
                "Raspberry Pi 3 Model A+", "Rasberry Pi 3 A+")
    assert (obs.advertised_price, obs.availability, obs.unit_limit) == (46.34, av.IN_STOCK, None)


def test_core_electronics_lead_time_keeps_the_dates():
    obs = parse("core_electronics", "core_electronics_pi5_1gb_lead_time.html",
                "Raspberry Pi 5 Model B 1GB", "Raspberry Pi 5 1GB")
    assert obs.advertised_price == 83.42
    assert obs.availability == av.DISPATCH_LATER
    assert "Expect dispatch between Nov 02 and Nov 06" in obs.availability_text
    assert obs.unit_limit == 1


def test_pb_tech_in_stock_with_a_buy_limit():
    obs = parse("pb_tech", "pb_tech_pi4_1gb_in_stock.html", "SC0192", "Raspberry Pi 4 Model B 1GB")
    assert obs.advertised_price == 72.08
    assert obs.availability == av.LIMITED and obs.unit_limit == 10
    assert obs.availability_text == "In stock (limit 10 per customer)"


def test_pakronics_out_of_stock():
    obs = parse("pakronics", "pakronics_pi4_1gb_out_of_stock.html", "SC0192",
                "Raspberry Pi 4 Model B 1GB")
    assert (obs.advertised_price, obs.availability) == (61.6, av.OUT_OF_STOCK)
    assert obs.availability_text == "Out of stock"


def test_pi_australia_picks_the_variant_by_sku_code():
    one = parse("raspberry_pi_australia", "pi_australia_pi4_variants.html", "SC0192",
                "Raspberry Pi 4 Model B 1GB")
    two = parse("raspberry_pi_australia", "pi_australia_pi4_variants.html", "SC0193",
                "Raspberry Pi 4 Model B 2GB")
    assert (one.advertised_price, two.advertised_price) == (70.61, 109.0)
    assert one.availability == two.availability == av.OUT_OF_STOCK


def test_pi_australia_reads_backordered_when_the_schema_says_in_stock():
    obs = parse("raspberry_pi_australia", "pi_australia_pi4_variants.html", "Raspberry Pi 4",
                "Raspberry Pi 4 Model B 3GB")
    assert obs.advertised_price == 138.0
    assert obs.availability == av.BACKORDER, "the page says backordered; the schema is wrong"


def test_zaitronics_sold_out_with_a_lead_time():
    obs = parse("zaitronics", "zaitronics_pi4_2gb_lead_time.html", "SC0193",
                "Raspberry Pi 4 Model B 2GB")
    assert obs.advertised_price == 88.0
    assert obs.availability == av.OUT_OF_STOCK
    assert obs.availability_text == "Out of stock (5-10 day lead time)"


def test_small_devices_picks_the_variant_by_ram():
    two = parse("small_devices", "small_devices_pi4_variants.html", "SC0193",
                "Raspberry Pi 4 Model B 2GB")
    four = parse("small_devices", "small_devices_pi4_variants.html", None,
                 "Raspberry Pi 4 Model B 4GB")
    assert (two.advertised_price, four.advertised_price) == (74.5, 102.0)


# ------------------------------------------------------------------- the controls


def test_a_page_with_no_structured_data_is_a_failure_not_an_empty_reading():
    for slug, name, model, product in [
        ("core_electronics", "core_electronics_pi4_2gb_limit.html", "SC0193", "Pi 4 2GB"),
        ("pb_tech", "pb_tech_pi4_1gb_in_stock.html", "SC0192", "Pi 4 1GB"),
        ("pakronics", "pakronics_pi4_1gb_out_of_stock.html", "SC0192", "Pi 4 1GB"),
        ("zaitronics", "zaitronics_pi4_2gb_lead_time.html", "SC0193", "Pi 4 2GB"),
    ]:
        # Control: the intact page parses, so the failure below is the damage, not the setup.
        assert get_adapter(slug).parse(page(name), model, product).advertised_price
        broken = re.sub(r'<script type="application/ld\+json">.*?</script>', "", page(name),
                        flags=re.S)
        with pytest.raises(ParseFailure):
            get_adapter(slug).parse(broken, model, product)


def test_a_changed_stock_layout_fails_instead_of_guessing_availability():
    for slug, name, cls, model, product in [
        ("core_electronics", "core_electronics_pi4_2gb_limit.html", "single-product-ship-note",
         "SC0193", "Pi 4 2GB"),
        ("pb_tech", "pb_tech_pi4_1gb_in_stock.html", "p_stock_title_dd", "SC0192", "Pi 4 1GB"),
    ]:
        assert cls in page(name)
        with pytest.raises(ParseFailure):
            get_adapter(slug).parse(page(name).replace(cls, "renamed"), model, product)


def test_a_zero_price_is_a_failure():
    html = page("core_electronics_pi3a_in_stock.html").replace('"46.34"', '"0"')
    with pytest.raises(ParseFailure):
        get_adapter("core_electronics").parse(html, "Raspberry Pi 3 Model A+", None)


def test_the_wrong_ram_size_is_rejected():
    """A listing re-pointed at another variant's page must not take that page's price."""
    with pytest.raises(ParseFailure, match="mismatch|single out"):
        parse("core_electronics", "core_electronics_pi4_2gb_limit.html", "SC0193",
              "Raspberry Pi 4 Model B 4GB")


def test_the_wrong_generation_is_rejected():
    with pytest.raises(ParseFailure, match="mismatch"):
        parse("core_electronics", "core_electronics_pi5_1gb_lead_time.html", None,
              "Raspberry Pi 4 Model B 1GB")


def test_a_variant_that_is_not_on_the_page_is_not_replaced_by_another():
    with pytest.raises(ParseFailure, match="variant"):
        parse("small_devices", "small_devices_pi4_variants.html", None, "Pi 4 Model B 1GB")
    with pytest.raises(ParseFailure):
        parse("raspberry_pi_australia", "pi_australia_pi4_variants.html", "SC9999",
              "Raspberry Pi 4 Model B 16GB")


# ----------------------------------------------------------- fetching and robots


class Resp:
    def __init__(self, status=200, text=""):
        self.status_code, self.text = status, text


@pytest.fixture()
def net(monkeypatch):
    """A fake requests.get keyed by URL; records every call."""
    monkeypatch.setenv("SHOPWATCH_SCRAPING_ENABLED", "true")
    monkeypatch.setenv("SHOPWATCH_REQUEST_DELAY", "0")
    monkeypatch.setenv("SHOPWATCH_REQUEST_JITTER", "0")
    robots.clear_cache()
    calls: list[tuple[str, str]] = []
    routes: dict[str, Resp] = {}

    def fake_get(url, timeout=None, headers=None):
        calls.append((url, (headers or {}).get("User-Agent", "")))
        if url not in routes:
            raise ConnectionError("no route " + url)
        return routes[url]

    import app.retailers.pi_base as pi_base
    import app.robots as robots_mod

    monkeypatch.setattr(pi_base.requests, "get", fake_get)
    monkeypatch.setattr(robots_mod.requests, "get", fake_get)
    yield routes, calls
    robots.clear_cache()


URL = "https://zaitronics.com.au/products/raspberry-pi-4-2gb-model-b"
ROBOTS = "https://zaitronics.com.au/robots.txt"


def test_one_page_request_with_an_identifying_user_agent(net):
    routes, calls = net
    routes[ROBOTS] = Resp(200, "User-agent: *\nAllow: /\n")
    routes[URL] = Resp(200, page("zaitronics_pi4_2gb_lead_time.html"))
    obs = get_adapter("zaitronics").check(URL, "SC0193", "Raspberry Pi 4 Model B 2GB")
    assert obs.advertised_price == 88.0
    assert [c[0] for c in calls] == [ROBOTS, URL], "robots.txt once, then exactly one page"
    assert all("shopwatch" in agent and "Mozilla" not in agent for _, agent in calls)


def test_robots_disallow_stops_the_fetch_before_the_page_is_requested(net):
    routes, calls = net
    routes[ROBOTS] = Resp(200, "User-agent: *\nDisallow: /products/\n")
    routes[URL] = Resp(200, page("zaitronics_pi4_2gb_lead_time.html"))
    with pytest.raises(FetchError, match="robots.txt disallows"):
        get_adapter("zaitronics").check(URL, "SC0193", "Pi 4 2GB")
    assert URL not in [c[0] for c in calls]


def test_unreadable_robots_fails_closed_but_a_missing_one_allows(net):
    routes, calls = net
    routes[URL] = Resp(200, page("zaitronics_pi4_2gb_lead_time.html"))
    routes[ROBOTS] = Resp(503)
    with pytest.raises(FetchError, match="unreachable"):
        get_adapter("zaitronics").check(URL, "SC0193", "Pi 4 2GB")
    robots.clear_cache()
    routes[ROBOTS] = Resp(404)
    assert get_adapter("zaitronics").check(URL, "SC0193", "Pi 4 2GB").advertised_price == 88.0


def test_an_interstitial_and_an_http_error_are_failures(net):
    routes, _ = net
    routes[ROBOTS] = Resp(404)
    routes[URL] = Resp(200, "<html><title>Just a moment...</title></html>")
    with pytest.raises(FetchError, match="interstitial"):
        get_adapter("zaitronics").check(URL, "SC0193", "Pi 4 2GB")
    routes[URL] = Resp(429)
    with pytest.raises(FetchError, match="429"):
        get_adapter("zaitronics").check(URL, "SC0193", "Pi 4 2GB")


def test_every_adapter_is_registered_and_amazon_is_not():
    for slug in ("core_electronics", "pb_tech", "pakronics", "small_devices", "zaitronics",
                 "raspberry_pi_australia"):
        assert get_adapter(slug) is not None, slug
    assert get_adapter("amazon_au") is None, "Amazon AU is deliberately manual"
