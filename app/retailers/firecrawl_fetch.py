"""Fetch one page through the self-hosted Firecrawl instance, as a fallback.

Used only by the Pi adapters, only after the honest direct fetch was refused, and only
when SHOPWATCH_FIRECRAWL_URL is set. Firecrawl drives a headless browser, so it looks like
an ordinary visitor; that is the point of it and also why it is a fallback and not the
default. robots.txt is still checked by the caller before either path runs.

Firecrawl answers HTTP 200 with {"success": true, "data": {"rawHtml", "metadata":
{"statusCode": <the target's status>}}} even when the target refused it (observed on opti,
2026-11-06, against a 429, a 403 and a 404). So three outcomes have to be told apart:

  Blocked      the target refused Firecrawl too (401/403/429, or a bot interstitial). The
               caller records this and stops using Firecrawl for that retailer.
  Unavailable  Firecrawl itself failed (down, timeout, not JSON, empty page). This says
               nothing about the retailer, so it must never be recorded as a block.
  FetchError   the target answered with some other non-200 (a 404 product page); an
               ordinary fetch failure.
"""

from __future__ import annotations

from .base import FetchError, detect_block, requests

#: Target statuses that mean "this retailer does not want to be fetched this way".
REFUSAL_CODES = (401, 403, 429)


class Blocked(FetchError):
    """The retailer refused Firecrawl as well."""


class Unavailable(FetchError):
    """Firecrawl itself could not do the job."""


def fetch(url: str, base_url: str, timeout: float) -> str:
    if requests is None:  # pragma: no cover
        raise Unavailable("requests is not installed")
    endpoint = base_url.rstrip("/") + "/v1/scrape"
    try:
        response = requests.post(
            endpoint, json={"url": url, "formats": ["rawHtml"]}, timeout=timeout
        )
    except Exception as exc:  # connection refused, timeout, DNS: Firecrawl is not answering
        raise Unavailable(f"{type(exc).__name__}: {exc}") from exc
    try:
        body = response.json()
    except ValueError as exc:
        raise Unavailable(f"Firecrawl answered HTTP {response.status_code} with no JSON") from exc
    if not isinstance(body, dict) or not body.get("success"):
        error = body.get("error") if isinstance(body, dict) else None
        raise Unavailable(f"Firecrawl error: {str(error or response.status_code)[:200]}")
    data = body.get("data") or {}
    target = (data.get("metadata") or {}).get("statusCode")
    if target in REFUSAL_CODES:
        raise Blocked(f"the retailer answered Firecrawl with HTTP {target}")
    if target not in (None, 200):
        raise FetchError(f"HTTP {target} (via Firecrawl)")
    html = data.get("rawHtml") or ""
    if not html.strip():
        raise Unavailable("Firecrawl returned an empty page")
    marker = detect_block(html)
    if marker:
        raise Blocked(f"bot-protection interstitial via Firecrawl (matched {marker!r})")
    return html
