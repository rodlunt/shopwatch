"""Shared machinery for the Raspberry Pi retailer adapters.

What a Pi adapter promises, beyond the base contract:

* **Polite.** An honest user agent (config.pi_user_agent), robots.txt honoured (see
  app/robots.py, which fails closed), the politeness delay plus random jitter before every
  request, and exactly one page request per listing.
* **A reading or a failure, never a guess.** No price on the page raises ParseFailure
  (a FetchError), so the watcher counts it as an adapter failure and keeps the last good
  value. Availability that cannot be read comes back as `unknown` and leaves the stored
  availability alone.
* **Both the words and the enum.** `availability_text` is what the retailer said,
  `availability` is the normalised state, `unit_limit` the numeric purchase limit if any.
* **Freight is not invented.** Every one of these shops quotes freight at the cart by
  postcode, so freight stays unresolved (None) and the price is the GST-inclusive
  advertised price.
"""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass
from typing import Any

from .. import availability as av
from .. import robots
from .base import (
    BeautifulSoup,
    FetchError,
    Observation,
    RetailerAdapter,
    detect_block,
    json_ld_blocks,
    model_matches,
    parse_price,
    requests,
)


class ParseFailure(FetchError):
    """The page was fetched but did not contain a usable reading (layout changed, wrong
    product, no price). Subclasses FetchError so the watcher keeps the last good value."""


@dataclass
class Candidate:
    """One purchasable thing found on a page (a product, or one variant of a group)."""

    name: str | None
    sku: str | None
    price: float | None
    schema_availability: str | None


_RAM_RE = re.compile(r"(?<![\d.])(\d{1,2})\s*gb\b", re.IGNORECASE)
_GEN_RE = re.compile(r"\bpi\s*®?\s*(\d)\b", re.IGNORECASE)
_CODE_RE = re.compile(r"^[A-Z]{1,3}\d{3,}$")


def ram_of(*texts: str | None) -> str | None:
    """'2GB' from the first text that names a RAM size, else None."""
    for text in texts:
        match = _RAM_RE.search(text or "")
        if match:
            return f"{int(match.group(1))}GB"
    return None


def generation_of(text: str | None) -> str | None:
    match = _GEN_RE.search((text or "").replace("\xa0", " "))
    return match.group(1) if match else None


def candidates_from_json_ld(html: str) -> list[Candidate]:
    """Every Product (and every variant of a ProductGroup) with an offer, from JSON-LD."""
    found: list[Candidate] = []

    def read(block: dict[str, Any], inherit_name: str | None = None) -> None:
        offers = block.get("offers")
        offers = offers if isinstance(offers, list) else [offers]
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            found.append(
                Candidate(
                    name=block.get("name") or inherit_name,
                    sku=str(offer.get("sku") or block.get("sku") or block.get("mpn") or "") or None,
                    price=parse_price(offer.get("price") or offer.get("lowPrice")),
                    schema_availability=offer.get("availability"),
                )
            )

    for block in json_ld_blocks(html):
        types = block.get("@type")
        types = types if isinstance(types, list) else [types]
        lowered = {str(t).lower() for t in types if t}
        if "productgroup" in lowered:
            for variant in block.get("hasVariant") or []:
                if isinstance(variant, dict):
                    read(variant, block.get("name"))
        elif "product" in lowered:
            read(block)
    return found


def page_text(html: str) -> str:
    if BeautifulSoup is None:  # pragma: no cover
        return re.sub(r"<[^>]+>", " ", html)
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))


def choose(
    candidates: list[Candidate], expected_model: str | None, product_name: str | None
) -> Candidate:
    """Pick the one candidate that is this product, or raise.

    Order: a manufacturer code in the expected model (SC0192) found inside a candidate's
    SKU or name; else the RAM size from the product name or model. With neither to go on,
    only a page with exactly one candidate is accepted. Taking the cheapest or the first
    would write another variant's price onto this listing.
    """
    priced = [c for c in candidates if c.price is not None]
    if not priced:
        raise ParseFailure("no priced offer found on the page")

    code = expected_model.strip().upper() if expected_model else ""
    if _CODE_RE.match(code):
        hits = [c for c in priced if code in re.sub(r"[^A-Z0-9]", "", (c.sku or "").upper())
                or model_matches(code, c.sku)]
        if len(hits) == 1:
            return hits[0]

    ram = ram_of(product_name, expected_model)
    if ram:
        pattern = re.compile(rf"(?<![\d.]){ram[:-2]}\s*gb\b", re.IGNORECASE)
        hits = [c for c in priced if pattern.search(c.name or "") or pattern.search(c.sku or "")]
        if len(hits) == 1:
            return hits[0]
        raise ParseFailure(f"could not single out the {ram} variant among {len(priced)} offers")

    if len(priced) == 1:
        return priced[0]
    raise ParseFailure(f"{len(priced)} offers on the page and nothing to tell them apart")


def check_identity(page_name: str | None, expected_model: str | None, product_name: str | None):
    """Raise when the page is visibly a different RAM size or Pi generation."""
    if not page_name:
        return
    want_ram = ram_of(product_name, expected_model)
    have_ram = ram_of(page_name)
    if want_ram and have_ram and want_ram != have_ram:
        raise ParseFailure(f"model mismatch: page is {have_ram}, expected {want_ram}")
    want_gen = generation_of(product_name) or generation_of(expected_model)
    have_gen = generation_of(page_name)
    if want_gen and have_gen and want_gen != have_gen:
        raise ParseFailure(f"model mismatch: page is Pi {have_gen}, expected Pi {want_gen}")


def _retry_after(response) -> float | None:
    """Seconds from a Retry-After header given as a number, else None (dates are ignored)."""
    try:
        value = float(response.headers.get("Retry-After", ""))
    except (AttributeError, TypeError, ValueError):
        return None
    return value if value >= 0 else None


class PiAdapter(RetailerAdapter):
    """Base for the Pi retailers. Subclasses implement `read(html, ...)`."""

    never_scrapable = ("freight", "pickup_status")
    wants_product_name = True
    notes = "Freight is quoted at the cart by postcode; left unresolved."

    def fetch(self, url: str) -> str:
        if requests is None:  # pragma: no cover
            raise FetchError("requests is not installed")
        if not self.config.scraping_enabled:
            raise FetchError("scraping disabled by configuration")
        agent = self.config.pi_user_agent
        if self.config.robots_enforced:
            try:
                robots.check(url, agent, self.config.request_timeout)
            except robots.RobotsError as exc:
                raise FetchError(str(exc)) from exc
        # At most two attempts. The second happens only when the retailer says "slow down"
        # (429 or 503) AND tells us how long to wait, and that wait is short enough to sit
        # through. Shopify answered the first Pi runs with 429 and Retry-After: 60 on
        # roughly every other request, then 200 once left alone.
        for attempt in (1, 2):
            jitter = random.uniform(0, max(self.config.request_jitter, 0))
            time.sleep(max(self.config.request_delay, 0) + jitter)
            try:
                response = requests.get(
                    url,
                    timeout=self.config.request_timeout,
                    headers={"User-Agent": agent, "Accept-Language": "en-AU,en;q=0.9"},
                )
            except Exception as exc:
                raise FetchError(f"{type(exc).__name__}: {exc}") from exc
            if response.status_code in (429, 503) and attempt == 1:
                wait = _retry_after(response)
                if wait is not None and wait <= self.config.pi_retry_after_max:
                    time.sleep(wait)
                    continue
            break
        if response.status_code in (401, 403, 429):
            raise FetchError(f"HTTP {response.status_code}: retailer refused the request")
        if response.status_code != 200:
            raise FetchError(f"HTTP {response.status_code}")
        marker = detect_block(response.text)
        if marker:
            raise FetchError(f"bot-protection interstitial (matched {marker!r})")
        return response.text

    # Subclasses override this; the signature carries the product name for variants.
    def read(
        self, html: str, expected_model: str | None, product_name: str | None
    ) -> tuple[Candidate, str | None, str | None]:
        """Return (candidate, availability_text, page_name). Raise ParseFailure."""
        raise NotImplementedError

    def parse(
        self,
        html: str,
        expected_model: str | None = None,
        product_name: str | None = None,
    ) -> Observation:
        candidate, text, page_name = self.read(html, expected_model, product_name)
        check_identity(page_name or candidate.name, expected_model, product_name)
        if candidate.price is None or candidate.price <= 0:
            raise ParseFailure("no price on the page")
        state = av.normalise(text, candidate.schema_availability)
        if not text and state.state != av.UNKNOWN:
            text = (candidate.schema_availability or "").split("/")[-1]
        obs = Observation(
            advertised_price=candidate.price,
            condition="NEW",
            notes=self.notes,
            availability=state.state,
            availability_text=text,
            unit_limit=state.unit_limit or av.unit_limit_from(text),
        )
        if text and state.state != av.UNKNOWN:
            obs.stock_status = text
        else:
            # Words we cannot place stay out of the stored value, so the last good
            # availability (words and enum together) survives instead of being replaced
            # by something the alerts cannot interpret.
            obs.mark_unresolved("stock_status")
        if state.state == av.UNKNOWN:
            obs.mark_unresolved("availability")
        return obs

    def check(
        self,
        url: str,
        expected_model: str | None = None,
        product_name: str | None = None,
    ) -> Observation:
        obs = self.parse(self.fetch(url), expected_model, product_name)
        obs.mark_unresolved(*self.never_scrapable)
        return obs
