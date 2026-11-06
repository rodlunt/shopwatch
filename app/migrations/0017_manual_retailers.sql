-- 0017: a retailer can be marked "manual": checked by a person, not by a scraper.
--
-- Why: Shopify's bot protection has answered the honest direct fetch with HTTP 429
-- ("local_rate_limited") on small_devices and zaitronics since 3 Nov 2026 (measured on opti
-- 2026-11-06: direct 429 even with a browser User-Agent string, a headless browser 200,
-- same IP; the Cloudflare header on the response is only Shopify's CDN). Rather than wiring
-- in a headless browser for a few pages a day, they are checked by hand and the dashboard
-- says when a check is due.
--
-- This is a separate flag, not "adapter = NULL", because the container's startup seed
-- (store.ensure_retailer) backfills an adapter onto any retailer that has none, so a
-- nulled adapter would quietly come back at the next restart.
--
-- A manual retailer is skipped by the watcher and by the adapter-health check, and is
-- watched by a staleness alarm instead (pi_health.health): going manual must never mean
-- going unwatched.
ALTER TABLE retailers ADD COLUMN manual_since TEXT;
ALTER TABLE retailers ADD COLUMN manual_reason TEXT;

UPDATE retailers
   SET manual_since = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),
       manual_reason = 'Shopify bot protection refuses the automatic fetch (HTTP 429 local_rate_limited) since 3 Nov 2026'
 WHERE adapter IN ('small_devices', 'zaitronics') AND manual_since IS NULL;
