"""Appliance Central adapter.

A smaller storefront that usually publishes clean JSON-LD. Its headline price frequently
excludes a coupon that only applies in the cart, so the scraped price is the pre-coupon
price: record the coupon separately rather than folding it into the advertised figure.
"""

from __future__ import annotations

from .base import Observation, RetailerAdapter, observation_from_json_ld, register


@register
class ApplianceCentralAdapter(RetailerAdapter):
    slug = "appliance_central"
    name = "Appliance Central"
    homepage = "https://www.appliancecentral.com.au"
    never_scrapable = ("freight",)

    def parse(self, html: str, expected_model: str | None = None) -> Observation:
        obs = observation_from_json_ld(html, expected_model)
        obs.notes = (
            "Scraped price is pre-coupon. Enter cart coupons in the coupon field, "
            "not by editing the advertised price."
        )
        return obs
