"""Little Bird Electronics (littlebirdelectronics.com.au).

Not Shopify: a custom storefront, but the product page carries a schema.org Product with
one Offer per variant (GST-inclusive price, schema.org availability, the SKU as
"RP-<manufacturer code>"). robots.txt allows /products for any agent, so a plainly
identified personal watcher is permitted on product pages. Freight is shown in the markup
as a flat rate but is quoted at the cart by destination, so it is left unresolved like
every other Pi retailer. The page prints no stock count, so a limit is never invented.
"""

from __future__ import annotations

from .base import register
from .pi_base import PiAdapter, candidates_from_json_ld, choose

_SCHEMA_WORDS = {
    "instock": "In stock",
    "outofstock": "Out of stock",
    "soldout": "Out of stock",
    "backorder": "Backorder",
    "preorder": "Pre-order",
    "limitedavailability": "Limited stock",
}


@register
class LittleBirdAdapter(PiAdapter):
    slug = "little_bird"
    name = "Little Bird Electronics"
    homepage = "https://littlebirdelectronics.com.au"
    notes = "Freight is quoted at checkout; left unresolved."

    def read(self, html, expected_model, product_name):
        candidate = choose(candidates_from_json_ld(html), expected_model, product_name)
        key = (candidate.schema_availability or "").split("/")[-1].lower()
        return candidate, _SCHEMA_WORDS.get(key), candidate.name
