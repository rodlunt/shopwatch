"""Runtime configuration. Everything comes from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class Config:
    db_path: Path = field(
        default_factory=lambda: Path(os.environ.get("SHOPWATCH_DB", "data/shopwatch.db"))
    )
    currency: str = os.environ.get("SHOPWATCH_CURRENCY", "AUD")

    # How many days before a successfully-fetched field is considered STALE.
    stale_after_days: int = _int("SHOPWATCH_STALE_AFTER_DAYS", 7)

    # Ranking penalty applied to a listing whose freight is unresolved, so that an
    # unknown-freight listing cannot silently outrank a slightly dearer listing with a
    # confirmed delivered price. Ranking only: never written to the stored price.
    unresolved_freight_penalty: float = _float("SHOPWATCH_UNRESOLVED_FREIGHT_PENALTY", 60.0)

    # Scraping manners.
    request_timeout: float = _float("SHOPWATCH_REQUEST_TIMEOUT", 20.0)
    request_delay: float = _float("SHOPWATCH_REQUEST_DELAY", 3.0)
    user_agent: str = os.environ.get(
        "SHOPWATCH_USER_AGENT",
        "Mozilla/5.0 (X11; Linux x86_64) shopwatch/0.1 (personal price watch)",
    )
    scraping_enabled: bool = _bool("SHOPWATCH_SCRAPING_ENABLED", True)

    # Alerting.
    ntfy_url: str = os.environ.get("SHOPWATCH_NTFY_URL", "")
    ntfy_token: str = os.environ.get("SHOPWATCH_NTFY_TOKEN", "")
    ntfy_priority: str = os.environ.get("SHOPWATCH_NTFY_PRIORITY", "high")
    webhook_url: str = os.environ.get("SHOPWATCH_WEBHOOK_URL", "")
    alerts_enabled: bool = _bool("SHOPWATCH_ALERTS_ENABLED", True)

    host: str = os.environ.get("SHOPWATCH_HOST", "0.0.0.0")
    port: int = _int("SHOPWATCH_PORT", 8477)


def load_config() -> Config:
    """Build a Config from the current environment (re-read each call, so tests can patch)."""
    return Config()


CONFIG = load_config()
