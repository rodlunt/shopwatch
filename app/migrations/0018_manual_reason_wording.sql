-- 0018: correct the reason stored for retailers marked manual.
--
-- 0017 and the API calls made at deploy named Cloudflare as the party refusing the fetch.
-- It is Shopify's own bot protection: the 429 body is the text "local_rate_limited" with
-- Shopify's x-dc and x-request-id headers, and "server: cloudflare" is only the CDN in front.
-- Only the exact old wording is rewritten; a reason a person typed is left alone.
UPDATE retailers
   SET manual_reason = 'Shopify bot protection refuses the automatic fetch (HTTP 429 local_rate_limited) since 3 Nov 2026'
 WHERE manual_reason = 'Cloudflare refuses the automatic fetch (HTTP 429) since 3 Nov 2026';
