"""The four Shopify retailers: Pakronics, Pi Australia, Zaitronics and Small Devices.

All four publish schema.org JSON-LD with the GST-inclusive price and a schema.org
availability per variant. Pi Australia and Small Devices put several RAM sizes on one
page (a ProductGroup), so the variant is chosen by the SKU code or the RAM size (see
pi_base.choose) and never by position or price. Shopify exposes no stock count, so a
limit is never invented. Two retailer-specific words matter and are read from the page:
Zaitronics prints a lead time on sold-out items, and Pi Australia prints
"<n>GB is backordered" while the schema still says InStock.
"""

from __future__ import annotations

import re

from .base import register
from .pi_base import PiAdapter, candidates_from_json_ld, choose, page_text, ram_of

_SCHEMA_WORDS = {
    "instock": "In stock",
    "outofstock": "Out of stock",
    "soldout": "Out of stock",
    "backorder": "Backorder",
    "preorder": "Pre-order",
    "limitedavailability": "Limited stock",
}
_LEAD = re.compile(r"(\d+\s*-\s*\d+\s*day lead time)", re.IGNORECASE)


class ShopifyPiAdapter(PiAdapter):
    notes = "Shipping is calculated at checkout; freight left unresolved."

    def read(self, html, expected_model, product_name):
        candidate = choose(candidates_from_json_ld(html), expected_model, product_name)
        key = (candidate.schema_availability or "").split("/")[-1].lower()
        words = _SCHEMA_WORDS.get(key)
        text = page_text(html)
        ram = ram_of(product_name, expected_model)
        if ram and re.search(rf"\b{ram}\b[^.]{{0,40}}is backordered", text, re.IGNORECASE):
            words = "Backorder"
        if words == "Out of stock":
            lead = _LEAD.search(text)
            if lead:
                words = f"Out of stock ({lead.group(1)})"
        return candidate, words, candidate.name


@register
class PakronicsAdapter(ShopifyPiAdapter):
    slug = "pakronics"
    name = "Pakronics"
    homepage = "https://www.pakronics.com.au"


@register
class RaspberryPiAustraliaAdapter(ShopifyPiAdapter):
    slug = "raspberry_pi_australia"
    name = "Raspberry Pi Australia"
    homepage = "https://piaustralia.com.au"


@register
class ZaitronicsAdapter(ShopifyPiAdapter):
    slug = "zaitronics"
    name = "Zaitronics"
    homepage = "https://zaitronics.com.au"


@register
class SmallDevicesAdapter(ShopifyPiAdapter):
    slug = "small_devices"
    name = "Small Devices"
    homepage = "https://smalldevices.com.au"
