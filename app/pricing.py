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
