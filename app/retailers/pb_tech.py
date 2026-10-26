"""PB Tech Australia (pbtech.com/au).

JSON-LD carries the GST-inclusive price. The visible stock label is `a.p_stock_title_dd`
("In stock" and its siblings) and a purchase limit is printed as "Buy Limit 10 Units Per
Customer". robots.txt names several AI crawlers by agent and allows everything else outside
checkout and search, so a plainly identified personal watcher is permitted on product pages.
Freight is calculated at the cart by delivery area; left unresolved.
"""

from __future__ import annotations

import re

from .base import BeautifulSoup, register
from .pi_base import ParseFailure, PiAdapter, candidates_from_json_ld, choose, page_text

_LIMIT = re.compile(r"Buy Limit\s+(\d+)\s+Units? Per Customer", re.IGNORECASE)


@register
class PBTechAdapter(PiAdapter):
    slug = "pb_tech"
    name = "PB Tech"
    homepage = "https://www.pbtech.com/au/"
    notes = "Freight calculated at the cart by delivery area; left unresolved."

    def read(self, html, expected_model, product_name):
        candidate = choose(candidates_from_json_ld(html), expected_model, product_name)
        label = BeautifulSoup(html, "html.parser").select_one(".p_stock_title_dd")
        if label is None:
            raise ParseFailure("stock label (.p_stock_title_dd) not found; layout changed?")
        words = re.sub(r"\s+", " ", label.get_text(" ", strip=True))
        if not words:
            raise ParseFailure("stock label is empty")
        match = _LIMIT.search(page_text(html))
        if match:
            words += f" (limit {match.group(1)} per customer)"
        return candidate, words, candidate.name
