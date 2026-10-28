"""Normalised stock availability.

Retailers describe stock in free text ("In stock (limit 1 per customer)", "Expect dispatch
between Nov 02 and Nov 06", "Sold out"). Alerting needs a small closed set, so this maps
the words onto an enum and pulls out a unit limit, while the raw text is always kept
alongside it. Anything not recognised is UNKNOWN, never a guess at in stock.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

IN_STOCK = "in_stock"
LIMITED = "limited"
DISPATCH_LATER = "dispatch_later"
BACKORDER = "backorder"
OUT_OF_STOCK = "out_of_stock"
UNKNOWN = "unknown"

ALL = (IN_STOCK, LIMITED, DISPATCH_LATER, BACKORDER, OUT_OF_STOCK, UNKNOWN)
#: Can be bought now.
BUYABLE = (IN_STOCK, LIMITED)
#: Cannot be bought now, but is expected to be: the "before" side of a back-in-stock.
WAITING = (OUT_OF_STOCK, BACKORDER, DISPATCH_LATER)


@dataclass(frozen=True)
class Availability:
    state: str
    unit_limit: int | None = None


_OUT = re.compile(r"out of stock|sold out|unavailable|discontinued|no stock|not available")
_IN = re.compile(r"\bin stock\b|\bavailable now\b|ships (?:today|same)|in-stock")
_BACK = re.compile(r"back-?\s?order|pre-?order")
# "In stock - no backorders accepted" names the word to say it does not apply.
_NO_BACK = re.compile(r"\b(?:no|without|not)\s+(?:\w+\s+)?(?:back-?\s?order|pre-?order)s?\b(?:\s+accepted)?")
_LOW = re.compile(r"low stock|few left|limited stock|limited availability|only a few")
_LATER = re.compile(r"expect(?:ed)? dispatch|lead time|dispatch (?:between|in|from|on)|ships in")
_LIMIT = re.compile(
    r"(?:limit(?:ed)?(?: to)?|max(?:imum)?)\s*(\d+)(?:\s*(?:units?|per customer|each))?"
    r"|(\d+)\s*(?:units?\s*)?per customer"
    r"|only\s+(\d+)\s+left"
)


def unit_limit_from(text: str | None) -> int | None:
    """The numeric purchase limit stated in the text, or None."""
    if not text:
        return None
    match = _LIMIT.search(text.lower())
    if not match:
        return None
    value = next((g for g in match.groups() if g), None)
    return int(value) if value else None


def normalise(text: str | None, schema: str | None = None) -> Availability:
    """Map retailer words (and an optional schema.org availability) onto the enum.

    Out-of-stock wording wins over everything: "Out of stock (5-10 day lead time)" is not
    something you can buy, whatever the lead time says. The schema.org value is only a
    fallback when the visible words say nothing, because the visible words are what a
    customer is actually told.
    """
    lowered = (text or "").lower()
    limit = unit_limit_from(lowered)
    if _OUT.search(lowered):
        return Availability(OUT_OF_STOCK)
    if _BACK.search(_NO_BACK.sub(" ", lowered)):
        return Availability(BACKORDER)
    if _LATER.search(lowered) and not _IN.search(lowered):
        return Availability(DISPATCH_LATER)
    if _IN.search(lowered):
        return Availability(LIMITED, limit) if limit else Availability(IN_STOCK)
    if _LOW.search(lowered):
        return Availability(LIMITED, limit)

    key = (schema or "").split("/")[-1].lower().replace("_", "")
    if key == "instock":
        return Availability(LIMITED, limit) if limit else Availability(IN_STOCK)
    if key in {"outofstock", "soldout", "discontinued"}:
        return Availability(OUT_OF_STOCK)
    if key in {"backorder", "preorder"}:
        return Availability(BACKORDER)
    if key == "limitedavailability":
        return Availability(LIMITED, limit)
    return Availability(UNKNOWN)
