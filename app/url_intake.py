"""Turn a bare retailer URL into a retailer identity - the "paste a listing URL" path
(issue #94: someone has a product page open, has no interest in typing a retailer name
or picking one from a list, and just wants to hand over the address).

Deliberately does not import anything from deploy/research-runner.py, even though that
module already has near-identical domain-to-display-name logic for its own "discover
retailers" feature. That script runs host-side, outside this container, on its own
venv; importing across that boundary would tie this container's behaviour to a file
that is not even guaranteed to be present at runtime. A dozen lines of duplicated regex
here is cheaper than that coupling.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from . import retailers


def bare_domain(url: str) -> str | None:
    """Lowercased host with any leading www. stripped, or None for an unusable url.

    Deliberately strict about scheme: something that merely contains a dot is not
    evidence it is a URL at all, and a scheme this app cannot fetch later (ftp:,
    mailto:, javascript:) must not be accepted just because urlparse tolerates it.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    netloc = parsed.netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


def adapter_for_domain(domain: str) -> type[retailers.RetailerAdapter] | None:
    """The registered adapter whose declared homepage matches this domain, or None.

    Matching on the adapter's own `homepage` class attribute rather than a separate
    domain table: that attribute is already the single source of truth other code
    trusts (the wizard's retailer list, price_watch), so a retailer added here lines
    up with the same adapter price_watch would pick up on its next scheduled pass.
    """
    for cls in retailers.available_adapters().values():
        home = bare_domain(cls.homepage) if cls.homepage else None
        if home and home == domain:
            return cls
    return None


#: TLD suffixes stripped before turning a domain into a readable name. Not exhaustive -
#: an unrecognised TLD is left in place, which is a worse-looking name than a wrong one.
_TLD_RE = re.compile(r"\.(com\.au|net\.au|org\.au|com|net|org|io|co)$")


def display_name_for_domain(domain: str) -> str:
    """A readable starting-point retailer name derived purely from the domain, e.g.
    "centrecom.com.au" -> "Centrecom". Approximate by construction: a domain rarely
    spells a brand's actual styling ("jbhifi.com.au" vs "JB Hi-Fi"). That is an
    acceptable trade-off here, not a defect to fix, because store.ensure_retailer
    matches on name case-insensitively and the wizard already lets a mis-cased or
    mis-spaced retailer be renamed later - this only has to be a reasonable label to
    show while the listing itself lands, not the final word on how the retailer is
    styled everywhere.
    """
    base = _TLD_RE.sub("", domain)
    parts = re.split(r"[.\-_]+", base)
    return " ".join(p.capitalize() for p in parts if p) or domain
