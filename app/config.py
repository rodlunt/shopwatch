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


def _str(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None else value


@dataclass
class Config:
    """Runtime settings.

    Every field uses `default_factory`, without exception. A plain default such as
    `port: int = _int("SHOPWATCH_PORT", 8477)` is evaluated once when the class is
    created, so it freezes whatever the environment held at import time and silently
    ignores every later change. That is not a test-only problem: it makes load_config()'s
    contract a lie. Keep the factories.
    """

    db_path: Path = field(
        default_factory=lambda: Path(os.environ.get("SHOPWATCH_DB", "data/shopwatch.db"))
    )
    currency: str = field(default_factory=lambda: _str("SHOPWATCH_CURRENCY", "AUD"))

    # How many days before a successfully-fetched field is considered STALE.
    stale_after_days: int = field(
        default_factory=lambda: _int("SHOPWATCH_STALE_AFTER_DAYS", 7)
    )

    # Ranking penalty applied to a listing whose freight is unresolved, so that an
    # unknown-freight listing cannot silently outrank a slightly dearer listing with a
    # confirmed delivered price. Ranking only: never written to the stored price.
    unresolved_freight_penalty: float = field(
        default_factory=lambda: _float("SHOPWATCH_UNRESOLVED_FREIGHT_PENALTY", 60.0)
    )

    # Scraping manners.
    request_timeout: float = field(
        default_factory=lambda: _float("SHOPWATCH_REQUEST_TIMEOUT", 20.0)
    )
    request_delay: float = field(
        default_factory=lambda: _float("SHOPWATCH_REQUEST_DELAY", 3.0)
    )
    user_agent: str = field(
        default_factory=lambda: _str(
            "SHOPWATCH_USER_AGENT",
            "Mozilla/5.0 (X11; Linux x86_64) shopwatch/0.1 (personal price watch)",
        )
    )
    scraping_enabled: bool = field(
        default_factory=lambda: _bool("SHOPWATCH_SCRAPING_ENABLED", True)
    )

    # Alerting.
    ntfy_url: str = field(default_factory=lambda: _str("SHOPWATCH_NTFY_URL", ""))
    ntfy_token: str = field(default_factory=lambda: _str("SHOPWATCH_NTFY_TOKEN", ""))
    ntfy_priority: str = field(default_factory=lambda: _str("SHOPWATCH_NTFY_PRIORITY", "high"))
    webhook_url: str = field(default_factory=lambda: _str("SHOPWATCH_WEBHOOK_URL", ""))
    alerts_enabled: bool = field(default_factory=lambda: _bool("SHOPWATCH_ALERTS_ENABLED", True))

    host: str = field(default_factory=lambda: _str("SHOPWATCH_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _int("SHOPWATCH_PORT", 8477))


def load_config() -> Config:
    """Build a Config from the current environment (re-read each call, so tests can patch)."""
    return Config()


#: Convenience handle for scripts. Call load_config() instead anywhere the environment
#: may have changed since import.
CONFIG = load_config()
