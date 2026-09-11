"""Crowdshop adapter.

Crowdshop shows a price guide (a range) rather than a single figure on some listings,
and its checkout has returned "No shipping options were found" for some postcodes. A
displayed $0 delivery is NOT evidence of free shipping and is deliberately not recorded
as freight = 0; freight stays unresolved until a human confirms it at checkout.
"""

from __future__ import annotations

import re

from .base import Observation, RetailerAdapter, observation_from_json_ld, parse_price, register

#: The en dash in this character class is DELIBERATE and must not be "cleaned up".
#: It is matching a dash that appears in the retailer's own HTML ("$100-$200" written
#: with an en dash), not one we write. The house ban on en and em dashes governs output,
#: not input we have to parse. Deleting it stops Crowdshop price ranges parsing.
RANGE_RE = re.compile(r"\$?\s*(\d[\d,]*(?:\.\d{2})?)\s*[-–to]{1,2}\s*\$?\s*(\d[\d,]*(?:\.\d{2})?)")


@register
class CrowdshopAdapter(RetailerAdapter):
    slug = "crowdshop"
    name = "Crowdshop"
    homepage = "https://crowdshop.com.au"
    never_scrapable = ("freight", "pickup_status")

    def parse(self, html: str, expected_model: str | None = None) -> Observation:
        obs = observation_from_json_ld(html, expected_model)
        low, high = _price_range(html)
        if low is not None and high is not None:
            obs.price_guide = f"{low:.0f}-{high:.0f}"
            if obs.advertised_price is None:
                obs.advertised_price = low
                if "advertised_price" in obs.unresolved:
                    obs.unresolved.remove("advertised_price")
        obs.notes = (
            "Price guide may be a range. Displayed $0 delivery is not confirmation of free "
            "shipping; freight left unresolved until checkout confirms it."
        )
        return obs


def _price_range(html: str) -> tuple[float | None, float | None]:
    from .base import BeautifulSoup

    if BeautifulSoup is None:
        return None, None
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    match = RANGE_RE.search(text)
    if not match:
        return None, None
    return parse_price(match.group(1)), parse_price(match.group(2))
