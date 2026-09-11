"""Retailer adapters. Importing this package registers every adapter."""

from . import (  # noqa: F401  (import for side effect: registration)
    appliance_central,
    crowdshop,
    harvey_norman,
    jb_hifi,
    the_good_guys,
)
from .base import (  # noqa: F401
    FetchError,
    Observation,
    RetailerAdapter,
    available_adapters,
    get_adapter,
    model_matches,
    parse_price,
    register,
)

__all__ = [
    "FetchError",
    "Observation",
    "RetailerAdapter",
    "available_adapters",
    "get_adapter",
    "model_matches",
    "parse_price",
    "register",
]
