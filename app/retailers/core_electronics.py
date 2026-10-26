"""Core Electronics (core-electronics.com.au, Magento).

The schema.org Offer gives the GST-inclusive price and a coarse availability. The words a
customer reads sit in `p.single-product-ship-note` ("In stock, ships same business day...",
"Available with a lead time / Expect dispatch between Nov 02 and Nov 06"), and a per
customer limit is written into the description ("limited to 1 per customer", "Max 1 per
customer"). Shipping is quoted from $7 at the cart; that is a floor, not a delivered price,
so freight stays unresolved.
"""

from __future__ import annotations

import re

from .base import BeautifulSoup, register
from .pi_base import ParseFailure, PiAdapter, candidates_from_json_ld, choose, page_text

_LIMIT = re.compile(r"(?:limited to|max(?:imum)?)\s+(\d+)\s+per customer", re.IGNORECASE)


@register
class CoreElectronicsAdapter(PiAdapter):
    slug = "core_electronics"
    name = "Core Electronics"
    homepage = "https://core-electronics.com.au"
    notes = "Freight quoted at the cart from $7 by postcode; left unresolved."

    def read(self, html, expected_model, product_name):
        candidate = choose(candidates_from_json_ld(html), expected_model, product_name)
        note = BeautifulSoup(html, "html.parser").select_one("p.single-product-ship-note")
        if note is None:
            raise ParseFailure("stock note (p.single-product-ship-note) not found; layout changed?")
        words = re.sub(r"\s+", " ", note.get_text(" ", strip=True))
        words = re.split(r"\s*Fastest delivery", words)[0].strip(" .,")
        if not words:
            raise ParseFailure("stock note is empty")
        match = _LIMIT.search(page_text(html))
        if match:
            words += f" (limit {match.group(1)} per customer)"
        return candidate, words, candidate.name
