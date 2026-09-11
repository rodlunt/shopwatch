"""Delivered-price arithmetic, threshold classification and ranking.

Delivered price is the primary ranking metric everywhere in this application.
Headline price is informational only.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# Deal classifications, best to worst.
HISTORICAL_LOW = "HISTORICAL_LOW"
EXCELLENT = "EXCELLENT"
TRIGGER_MET = "TRIGGER_MET"
ABOVE_TARGET = "ABOVE_TARGET"
UNRESOLVED = "UNRESOLVED"

CLASS_ORDER = [HISTORICAL_LOW, EXCELLENT, TRIGGER_MET, ABOVE_TARGET, UNRESOLVED]

CLASS_LABELS = {
    HISTORICAL_LOW: "HISTORICAL LOW TERRITORY",
    EXCELLENT: "EXCELLENT",
    TRIGGER_MET: "TRIGGER MET",
    ABOVE_TARGET: "ABOVE TARGET",
    UNRESOLVED: "UNRESOLVED",
}

CONDITIONS = [
    "NEW",
    "FACTORY_SECOND",
    "CARTON_DAMAGED",
    "EX_DISPLAY",
    "REFURBISHED",
    "USED",
]


@dataclass(frozen=True)
class Delivered:
    """The result of a delivered-price calculation.

    `value` is the best current estimate. `resolved` says whether freight was actually
    confirmed; an unresolved value is provisional and must be presented as such.
    """

    value: float | None
    resolved: bool
    freight_known: bool
    advertised: float | None
    adjustments: float

    @property
    def known(self) -> bool:
        return self.value is not None


def _num(value: Any) -> float | None:
    """Tolerant numeric read. Accepts "$1,059.00" as well as 1059.0, None on anything else."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        value = value.strip().replace("$", "").replace(",", "").replace(" ", "")
        if value == "":
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def delivered_price(
    advertised: Any,
    freight: Any = None,
    cashback: Any = None,
    rebate: Any = None,
    coupon_discount: Any = None,
) -> Delivered:
    """advertised + freight - cashback - rebate - coupon.

    A NULL freight means UNRESOLVED, never free. The provisional figure omits freight
    but the result is flagged unresolved so callers can rank and label it honestly.
    Negative results are clamped to zero: a cashback larger than the price is a data
    error, not a retailer paying you.
    """
    adv = _num(advertised)
    fre = _num(freight)
    adjustments = (_num(cashback) or 0.0) + (_num(rebate) or 0.0) + (_num(coupon_discount) or 0.0)

    if adv is None:
        return Delivered(None, False, fre is not None, None, adjustments)

    total = adv + (fre or 0.0) - adjustments
    if total < 0:
        total = 0.0
    return Delivered(round(total, 2), fre is not None, fre is not None, adv, adjustments)


def classify(delivered: Delivered | float | None, targets: Mapping[str, Any]) -> str:
    """Classify a delivered price against a product's thresholds.

    Thresholds are inclusive and evaluated best-first. An unknown price, or a price with
    unresolved freight that would otherwise rate at or better than the trigger, returns
    UNRESOLVED: an unconfirmed bargain is not a bargain yet. An unresolved price that is
    above target is still reported as ABOVE_TARGET, because freight can only make it worse.
    """
    if isinstance(delivered, Delivered):
        value, resolved = delivered.value, delivered.resolved
    else:
        value, resolved = _num(delivered), True

    if value is None:
        return UNRESOLVED

    historical = _num(targets.get("historical_low_price"))
    excellent = _num(targets.get("excellent_price"))
    trigger = _num(targets.get("trigger_price"))

    if historical is not None and value <= historical:
        rating = HISTORICAL_LOW
    elif excellent is not None and value <= excellent:
        rating = EXCELLENT
    elif trigger is not None and value <= trigger:
        rating = TRIGGER_MET
    else:
        rating = ABOVE_TARGET

    if not resolved and rating != ABOVE_TARGET:
        return UNRESOLVED
    return rating


def rank_key(delivered: Delivered, penalty: float = 60.0) -> tuple[int, float]:
    """Sort key for the retailer matrix. Lower is better.

    An unresolved-freight listing is ranked as if freight cost `penalty`, so it cannot
    automatically outrank a slightly dearer listing whose delivered price is confirmed.
    The penalty is a ranking device only and is never stored or displayed as a price.
    Listings with no price at all sort last.
    """
    if delivered.value is None:
        return (1, float("inf"))
    if delivered.resolved:
        return (0, delivered.value)
    return (0, delivered.value + penalty)


def difference_from_low(delivered: Delivered | float | None, lowest_known: Any) -> float | None:
    """Delivered price minus the lowest price ever recorded. Positive means dearer than the low."""
    value = delivered.value if isinstance(delivered, Delivered) else _num(delivered)
    low = _num(lowest_known)
    if value is None or low is None:
        return None
    return round(value - low, 2)


def best_listing(rows: list[Mapping[str, Any]], penalty: float = 60.0) -> Mapping[str, Any] | None:
    """The current best buy: cheapest confirmed delivered price, unresolved listings penalised."""
    priced = [r for r in rows if r.get("delivered") and r["delivered"].known]
    if not priced:
        return None
    return min(priced, key=lambda r: rank_key(r["delivered"], penalty))


# --------------------------------------------------------------------------- scale


def threshold_scale(targets: Mapping[str, Any], best: Any = None) -> dict[str, Any] | None:
    """Positions (0-100) for plotting targets and the current best on one axis.

    The three price targets are the whole point of the product, so they get shown as a
    scale rather than as three numbers in a row: "how far off are we" is the question,
    and a distance is easier to see than to calculate. Returns None when there is nothing
    to plot, so the caller can leave the space empty instead of drawing an empty axis.
    """
    marks = []
    for key, label in (
        ("historical_low_price", "hist low"),
        ("excellent_price", "excellent"),
        ("trigger_price", "trigger"),
    ):
        value = _num(targets.get(key))
        if value is not None:
            marks.append({"key": key, "label": label, "value": value})
    if not marks:
        return None

    best_value = best.value if isinstance(best, Delivered) else _num(best)
    values = [m["value"] for m in marks] + ([best_value] if best_value is not None else [])
    lo, hi = min(values), max(values)
    span = hi - lo
    # A flat span (single threshold, or best exactly on it) would divide by zero and
    # stack every mark on one pixel. Give it an arbitrary but proportionate width.
    pad = span * 0.14 if span else max(hi * 0.06, 1.0)
    lo, hi = lo - pad, hi + pad

    def pos(value: float) -> float:
        return round((value - lo) / (hi - lo) * 100, 2)

    for mark in marks:
        mark["pos"] = pos(mark["value"])
    return {
        "marks": marks,
        "best": {"value": best_value, "pos": pos(best_value)} if best_value is not None else None,
        "lo": round(lo, 2),
        "hi": round(hi, 2),
    }


def verdict_line(product: Mapping[str, Any]) -> tuple[str, str]:
    """The answer, in a sentence, before any data. Returns (tone, sentence).

    Tone is one of quiet / close / act / bought and drives how loudly it is shown. The
    wording states what to do and why, because "ABOVE TARGET" on a badge does not tell
    you whether you are ten dollars off or eight hundred.
    """
    purchase = product.get("purchase")
    if product.get("status") == "PURCHASED" and purchase:
        paid = purchase["price_paid"]
        moved = product.get("moved_since_purchase")
        when = str(purchase["purchased_at"])[:10]
        where = purchase.get("retailer_name") or "an unrecorded seller"
        if moved is not None and moved < 0 and product.get("protection_open"):
            return ("act", f"Now ${abs(moved):,.0f} cheaper than the ${paid:,.0f} you paid on "
                           f"{when}. Price protection is still open.")
        return ("bought", f"Bought {when} from {where} for ${paid:,.0f} delivered.")

    if product.get("status") == "PARKED":
        return ("quiet", "Parked. Nothing is being checked or alerted on.")

    listings = product.get("listings") or []
    if not listings:
        return ("quiet", "No retailers yet. Add one to start tracking a price.")

    best = product.get("best_listing")
    if best is None or product.get("best_delivered") is None:
        return ("quiet", "No prices recorded yet across "
                         f"{len(listings)} retailer{'s' if len(listings) != 1 else ''}.")

    price = product["best_delivered"]
    where = product["best_retailer"]
    rating = product["best_classification"]

    if not product.get("best_resolved"):
        return ("close", f"Unconfirmed. {where} shows ${price:,.0f} but freight is unknown, "
                         f"so the real figure could land anywhere above it.")

    trigger = _num(product.get("trigger_price"))
    if rating == HISTORICAL_LOW:
        return ("act", f"Buy. ${price:,.0f} delivered from {where} is historical-low territory.")
    if rating == EXCELLENT:
        return ("act", f"Buy. ${price:,.0f} delivered from {where}, under your "
                       f"${_num(product.get('excellent_price')):,.0f} excellent mark.")
    if rating == TRIGGER_MET:
        return ("act", f"Worth acting on. ${price:,.0f} delivered from {where}, under your "
                       f"${trigger:,.0f} trigger.")
    if trigger is not None:
        return ("quiet", f"Not yet. Best is ${price:,.0f} from {where}, "
                         f"${price - trigger:,.0f} over your ${trigger:,.0f} trigger.")
    return ("quiet", f"Best is ${price:,.0f} delivered from {where}. No trigger set.")
