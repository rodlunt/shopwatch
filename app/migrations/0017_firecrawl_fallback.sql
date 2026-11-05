-- 0017: per-adapter Firecrawl fallback state.
--
-- When a retailer refuses the honest direct fetch (401/403/429 or a bot interstitial) the Pi
-- adapters may fall back to the self-hosted Firecrawl instance, if SHOPWATCH_FIRECRAWL_URL is
-- set. The state is kept per adapter so that a retailer which blocks Firecrawl too is not
-- asked again:
--   untried  Firecrawl has not been needed yet (the default).
--   working  Firecrawl has fetched a page this adapter's direct fetch was refused on.
--   blocked  Firecrawl was refused as well. It is never tried again for this adapter until
--            someone resets it (python -m app.pi_health --reset-firecrawl <adapter>).
-- Firecrawl being DOWN is not "blocked": it changes nothing here and is reported as an
-- ordinary fetch error, so an outage cannot permanently switch the fallback off.
ALTER TABLE adapter_health ADD COLUMN firecrawl_state TEXT NOT NULL DEFAULT 'untried';
ALTER TABLE adapter_health ADD COLUMN firecrawl_blocked_at TEXT;
ALTER TABLE adapter_health ADD COLUMN firecrawl_note TEXT;
