"""Harvey Norman adapter.

Harvey Norman fronts its product pages with bot protection and personalises both
delivery cost and store stock behind a postcode/store selection. Price is usually
readable from JSON-LD when the fetch gets through; freight and pickup are not
determinable from the public page and stay manual.
"""

from __future__ import annotations

from .base import Observation, RetailerAdapter, observation_from_json_ld, parse_price, register


@register
class HarveyNormanAdapter(RetailerAdapter):
    slug = "harvey_norman"
    name = "Harvey Norman"
    homepage = "https://www.harveynorman.com.au"
    never_scrapable = ("freight", "pickup_status", "pickup_location")

    def parse(self, html: str, expected_model: str | None = None) -> Observation:
        obs = observation_from_json_ld(html, expected_model)
        if obs.advertised_price is None:
            obs.advertised_price = _meta_price(html)
            if obs.advertised_price is not None and "advertised_price" in obs.unresolved:
                obs.unresolved.remove("advertised_price")
        obs.notes = "Freight and pickup require a postcode/store selection; maintain manually."
        return obs


def _meta_price(html: str) -> float | None:
    from .base import BeautifulSoup

    if BeautifulSoup is None:
        return None
    soup = BeautifulSoup(html, "html.parser")
    for attrs in ({"property": "product:price:amount"}, {"itemprop": "price"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            return parse_price(tag["content"])
    return None
