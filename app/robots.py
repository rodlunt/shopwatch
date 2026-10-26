"""robots.txt, honoured as a rule rather than a courtesy.

Before a page is fetched for the Pi watch, the host's robots.txt is read (once per host
per process, cached for a day) and the URL must be allowed for our own user agent.

Fails closed, because this runs unattended:
  * robots.txt answers 200: its rules apply.
  * 404 or another 4xx (RFC 9309 "unavailable"): no rules exist, the URL is allowed.
  * 5xx or a network error ("unreachable"): treated as disallowed, and the check raises.
    A watcher that cannot read the rules does not get to assume they say yes.
"""

from __future__ import annotations

import time
from urllib import robotparser
from urllib.parse import urlsplit

try:  # pragma: no cover
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

CACHE_SECONDS = 24 * 3600
_cache: dict[str, tuple[float, robotparser.RobotFileParser | None]] = {}


class RobotsError(RuntimeError):
    """robots.txt forbids the URL, or could not be read."""


def _load(origin: str, user_agent: str, timeout: float) -> robotparser.RobotFileParser | None:
    """None means "no robots.txt, everything allowed"."""
    if requests is None:  # pragma: no cover
        raise RobotsError("requests is not installed")
    try:
        response = requests.get(
            origin + "/robots.txt", timeout=timeout, headers={"User-Agent": user_agent}
        )
    except Exception as exc:
        raise RobotsError(f"robots.txt unreachable ({type(exc).__name__}: {exc})") from exc
    if response.status_code >= 500:
        raise RobotsError(f"robots.txt unreachable (HTTP {response.status_code})")
    if response.status_code != 200:
        return None
    parser = robotparser.RobotFileParser()
    parser.parse(response.text.splitlines())
    return parser


def check(url: str, user_agent: str, timeout: float = 15.0) -> None:
    """Raise RobotsError unless `url` may be fetched by `user_agent`."""
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    now = time.monotonic()
    cached = _cache.get(origin)
    if cached is None or now - cached[0] > CACHE_SECONDS:
        cached = (now, _load(origin, user_agent, timeout))
        _cache[origin] = cached
    parser = cached[1]
    if parser is not None and not parser.can_fetch(user_agent, url):
        raise RobotsError(f"robots.txt disallows {parts.path or '/'} for this user agent")


def clear_cache() -> None:
    _cache.clear()
