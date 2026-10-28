"""One HTTP GET for the scrapers, with a classical TLS handshake.

Why this exists: from the Shopwatch container, Shopify storefronts (Pakronics, Pi Australia,
Zaitronics, Small Devices) answered "429 local_rate_limited" to most requests while the same
URL, user agent and headers got 200 from the opti host (measured 2026-10-28, six requests
each, 8 s apart: container default 6/6 refused, host 6/6 ok). Same egress IP and DNS. The
difference is the TLS stack: the image's OpenSSL 3.5 offers a hybrid post-quantum key share
by default, which makes an unusual ClientHello. Offering X25519 alone made the container
6/6 ok. So the edge is bot-scoring the handshake, not counting our requests.

X25519 is universally supported, so this is safe as a default. If a site rejects it the
handshake fails and we retry once with the library default, so a strict server cannot be
locked out by this change. SHOPWATCH_TLS_CURVE overrides the curve; set it empty to turn
the restriction off.
"""
from __future__ import annotations

import os
import ssl

try:  # pragma: no cover
    import requests
    from requests.adapters import HTTPAdapter
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]
    HTTPAdapter = object  # type: ignore[assignment,misc]

DEFAULT_CURVE = "X25519"


def _curve() -> str:
    return os.environ.get("SHOPWATCH_TLS_CURVE", DEFAULT_CURVE).strip()


class _CurveAdapter(HTTPAdapter):  # type: ignore[misc,valid-type]
    def __init__(self, curve: str, **kwargs) -> None:
        self._curve = curve
        super().__init__(**kwargs)

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.set_ecdh_curve(self._curve)
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)


def get(url: str, timeout: float | None = None, headers: dict | None = None):
    """requests.get with the restricted key exchange, falling back to the default once."""
    if requests is None:  # pragma: no cover
        raise RuntimeError("requests is not installed")
    curve = _curve()
    if not curve:
        return requests.get(url, timeout=timeout, headers=headers)
    try:
        with requests.Session() as session:
            session.mount("https://", _CurveAdapter(curve))
            return session.get(url, timeout=timeout, headers=headers)
    except requests.exceptions.SSLError:
        # The server did not accept the restricted handshake. Say nothing is wrong with
        # the page; just let the library negotiate normally.
        return requests.get(url, timeout=timeout, headers=headers)
