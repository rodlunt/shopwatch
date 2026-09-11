"""The Good Guys adapter.

Same shape as JB Hi-Fi (same parent group): JSON-LD price where the fetch succeeds,
postcode-gated freight and store-gated pickup that stay manual.
"""

from __future__ import annotations

from .base import Observation, RetailerAdapter, observation_from_json_ld, register


@register
class TheGoodGuysAdapter(RetailerAdapter):
    slug = "the_good_guys"
    name = "The Good Guys"
    homepage = "https://www.thegoodguys.com.au"
    never_scrapable = ("freight", "pickup_status", "pickup_location")

    def parse(self, html: str, expected_model: str | None = None) -> Observation:
        obs = observation_from_json_ld(html, expected_model)
        obs.condition = obs.condition or "NEW"
        obs.notes = "Freight quoted at checkout by postcode; pickup needs a store. Manual fields."
        return obs
