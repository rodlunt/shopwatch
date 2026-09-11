"""JB Hi-Fi adapter.

JB Hi-Fi serves its pages through an edge WAF that commonly answers a plain request
with a challenge. When a fetch does succeed the page still carries schema.org product
data. Delivery cost and click-and-collect availability are postcode/store specific and
are not read from the page.
"""

from __future__ import annotations

from .base import Observation, RetailerAdapter, observation_from_json_ld, register


@register
class JBHiFiAdapter(RetailerAdapter):
    slug = "jb_hifi"
    name = "JB Hi-Fi"
    homepage = "https://www.jbhifi.com.au"
    never_scrapable = ("freight", "pickup_status", "pickup_location")

    def parse(self, html: str, expected_model: str | None = None) -> Observation:
        obs = observation_from_json_ld(html, expected_model)
        obs.condition = obs.condition or "NEW"
        obs.notes = "Delivery cost and C&C stock are postcode/store specific; maintain manually."
        return obs
