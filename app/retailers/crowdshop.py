"""Crowdshop adapter.

Crowdshop shows a price guide (a range) rather than a single figure on some listings,
and its checkout has returned "No shipping options were found" for some postcodes. A
displayed $0 delivery is NOT evidence of free shipping and is deliberately not recorded
as freight = 0; freight stays unresolved until a human confirms it at checkout.
"""

from __future__ import annotations

import re

from .base import Observation, RetailerAdapter, observation_from_json_ld, parse_price, register

#: A price guide written as a range, e.g. "$869 - $889" or "$869 to $889".
#:
#: BOTH sides must carry a currency symbol. Without that this matched any "N to M"
#: anywhere in the page text and took the first hit, so "Dispatch 3 to 5 business days"
#: yielded a range of 3 to 5 and parse() promoted $3 as the advertised price. That is
#: the adapter inventing a figure, and because the historical low never rises again it
#: would have been permanent.
#:
#: The separator is an alternation, not a character class. `[-–to]{1,2}` meant "one or
#: two of the characters -, en dash, t, o in any order", so "$100 tt $200" and
#: "$100 oo $200" both matched.
#:
#: The en dash is DELIBERATE and must not be "cleaned up": it matches a dash in the
#: retailer's own HTML, not one we write, and the house ban governs output rather than
#: input we parse. Removing it would stop en-dash ranges parsing and nothing else,
#: since hyphen and "to" are separately handled. An earlier version of this comment
#: claimed removing it broke all range parsing, which was wrong.
RANGE_RE = re.compile(
    r"\$\s*(\d[\d,]*(?:\.\d{2})?)\s*(?:-|–|to)\s*\$\s*(\d[\d,]*(?:\.\d{2})?)"
)


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
