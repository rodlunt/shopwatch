# Next session brief: 28/10/2026 (Pi watch: 429 root cause, stock parsing, specs)

Supersedes the 27 Oct brief below. The 27 Oct "429 from opti" follow-up and the "Rasberry" typo are done; the rest of that brief still stands as history.

## What shipped (PRs #133 to #135, all merged with regular merges, CI green, deployed; VERIFIED via `gh pr view` and the container)

- **#134** (7d74e4b) the 429s were the TLS handshake, not load or pace. The image's OpenSSL 3.5 offers a post-quantum key share by default; Shopify's edge scores that as a bot. Same URL, user agent and headers, six requests 8 s apart: opti host (OpenSSL 3.0) 6/6 ok, curl HTTP/1.1 and HTTP/2 6/6 ok, container default 6/6 refused, container X25519 only 6/6 ok. New `app/http_client.py` offers X25519 only (one fallback to the default if a server rejects it; `SHOPWATCH_TLS_CURVE` overrides, empty disables), used by the Pi page fetch and the robots.txt fetch. Live check after deploy: run 18 (Pi 4 1GB) all four retailers ok. README corrected.
- **#133** (b8ed2d8) `availability.normalise`: "In stock - no backorders accepted" no longer reads as backorder; "Low Stock" (Little Bird's own status) reads as limited.
- **#135** (dc478ae) a 429 on robots.txt now fails closed and is not cached (it used to count as "no file, allow everything").
- **Data, not code:** products 16 to 20 renamed with an `(xG)` suffix (A+ 0.5G, B+ 1G, 4 1GB 1G, 4 2GB 2G, 5 1GB 1G), the "Rasberry" typo fixed, and each given a specs block (SoC, CPU, RAM, wifi, Bluetooth, Ethernet, USB, video, release year). Specs are from memory, not a retailer page: the Pi 5 1GB row is the one to check. The identity parsers (RAM, generation, B+) return the same values for the new names.

## Open follow-ups

- Read the 07:00 AEST scheduled run (and the 17:20 one): expect no `HTTP 429` and no "model mismatch". Runs 13 to 18 in `/api/price-watch/runs` are my manual checks (`manual-*` triggers, alerts off), not scheduled ones.
- `app/retailers/base.py` (Core Electronics, PB Tech) still uses plain `requests.get`. They were not being refused; move it onto `http_client.get` only if that changes.
- Restock alerts, not built: Little Bird has a "Notify Me" button on out-of-stock pages and a webhooks help page (VERIFIED from its help pages); PB Tech's wish list only emails sale price drops (LIKELY, NZ site); Core Electronics may have a notify button (LIKELY, unconfirmed); Pakronics and Pi Australia nothing found. Idea: ingest the restock emails as a second signal.
- Little Bird's Pi 4 2GB product page (AF-4292) says "no longer available" (schema Discontinued); check whether that listing is still worth watching.
- Pi 3 B+ winding down, price history thin: see the 27 Oct notes below, unchanged.
- Gotchas met this session: run `uvx ruff check .` before opening a PR (CI lint failed #133 on a 109-character line); `httpx` is not installed locally, so a few `test_pi_watch` and TestClient tests fail here and pass in CI.

---

# Next session brief: 27/10/2026 (Pi price watch for Bark Marker)

Written from the CRM and Pi watch session; the CRM side is in `smart-home/nextsession.md` (27 Oct). The sections below the rule are older and stand as history.

## What shipped (PRs #128 to #131, all merged, VERIFIED via `gh pr list`)

- **#128** scheduled Raspberry Pi price and stock watch for Bark Marker; **#129** honour a short Retry-After once and slow the request pace; **#130** retry Shopify `local_rate_limited` up to three times and commit per listing; **#131** Pi 3 Model B+ (product 20) with five listings (Core, Little Bird, Pi Australia, Pakronics, PB Tech), a Little Bird adapter and a B vs B+ guard.
- **Five boards watched, twice daily:** Pi 3 A+, Pi 3 B+, Pi 4 1GB, Pi 4 2GB, Pi 5 1GB. App on `127.0.0.1:8477` on opti.
- **Trigger prices set 27 Oct:** A+ $41, B+ $59, 4 1GB $58, 4 2GB $95, 5 1GB $75 (about 10% under normal in-stock price; the 4 2GB figure is a guess). Alerts only fire for in-stock listings.
- **Consumer:** the CRM Units tab reads `GET /api/crm/pi-watch` (stale after 26 h) and edits triggers through `PATCH /api/crm/pi-watch/{id}/trigger`. That panel was verified by tests only, not on the live page (the endpoint needs Caddy's key).
- Egress: `smart-home` allowlisted Little Bird (b68ebbc).

## Open follow-ups

- Confirm the four Shopify listings that returned 429 from opti (Pakronics, Pi Australia, Zaitronics, Small Devices) now read, and Little Bird as the fifth Shopify site. Not checked after #130.
- Pi 3 B+ looks to be winding down (LIKELY: Pololu lists it discontinued, SparkFun dropped its kit Oct 2025, PB Tech and Pakronics out of stock); no official end of life notice found.
- 12 month price history was thin (PriceSpy, CamelCamelCamel and Wayback blocked or sparse): prices flat or rising, official rises 1 Dec 2025, 2 Feb 2026, 1 Apr 2026 and 1 Oct 2026 (the last from one secondary source). The watch's own history is the anchor now.
- Cosmetic: the Pi 3 A+ is named "Rasberry" in its product record.

---

# Next session brief: 27/09/2026 (second close of the day)
Branch: main (this baton lands via chore/session-end-2026-09-27b)

## What shipped this session

Three PRs, all merged with regular merges, CI green, each deploy verified by the checkout
on opti rather than by the run. VERIFIED.

- **#121** (3708b2d): time-bomb test fix (`test_adding_a_listing_with_a_promo_end_date`
  hard-coded 2026-09-21 as a future date) plus the morning baton.
- **#122** (22d5c32): mailwatch reads image-only offers. `code` joined `WEAK_FIELDS` so a
  code-less percent-off renders; `render_tiles()` captures two 900x3200 screens by
  injecting a negative top margin, stops at a blank tile, sends all tiles to the model in
  one call; Chrome gets `--timeout=45000` so dead tracking pixels no longer run the render
  into the 120 s subprocess timeout.
- **#123** (1e99115): `--disable-dev-shm-usage` (Chrome's GPU process crashed in Docker's
  64 MB `/dev/shm` on image-heavy mail, exit 0, no file: 3/5 renders as shipped, 5/5 with
  the flag) plus one retry for a screenshot-less run. Found because the first live run of
  #122 died that way.

**After-fix control on the deployed code (1e99115), against the saved HTML of the real
Good Guys "Just For You" email:** two tiles in 4 s, vision in 11 s, `code=JFY2026`,
expiry 2026-09-27, full exclusions block read. The JB Hi-Fi email that timed out on 26 Sep
renders both tiles in 3 s. VERIFIED, results also posted as a comment on #123.

Also this session, no code: the soundbar was bought (order 5QG5W48WG, $679.20, purchase
row 4, product 1 PURCHASED) and the Good Guys price-match question answered. Details in
the previous baton in git history and in memory.

## Files touched

`app/render.py`, `app/offers.py`, `app/mailwatch.py`, `tests/test_render.py`,
`tests/test_offers.py`, `tests/test_api.py`, `README.md`, this file. Eight files.

## Verification

- pytest exit 0 locally after every change; CI `test`, `lint`, `audit` green on every PR
  head and on main. ruff clean.
- Deploy tree on opti at 1e99115, `healthz` ok. VERIFIED.
- 0 open issues, 0 open PRs.

## Open follow-ups

- **egress-watch digests on every render.** Each render loads the retailer image hosts
  (AWS, Cloudflare) and egress-watch batches them into an ntfy digest; today's test
  renders fired several. The daily mailwatch run will do the same on any email that
  renders. Allowlisting those destinations in `opti-stacks/egress-watch/allowlist.conf`
  (narrow CIDR + 443) is Rodney's call, not done. LIKELY the first thing that annoys.
- **Offer 20 on the board still has `code=None`.** The offer expired 27 Sep, so it was
  not re-recorded. Nothing to do unless a re-extract of past mail is wanted, and past
  mail renders as "offer ended" anyway (README, "Reading the artwork").
- **`record_purchase` does not lower `lowest_known_price`.** Product 1's low stayed at
  $705 after a $679.20 purchase; the view shows `moved_since_purchase` instead. May be
  deliberate. GUESSING; decide whether a paid price should count as a low.
- **Appliance Central seller note is stale** (says "SAVENOW $60" against a $1050
  headline; listing carries $765 with a $40 coupon). Cosmetic, batch it.
- **A render that produces the screenshot but Chrome still exits non-zero** is not
  handled specially; the existing "no screenshot" and timeout paths cover what was seen.
  GUESSING there is no such case; nothing observed.
- `~/.claude/instructions/repo-setup.md` is 273 hand-written lines, well over the
  55-line threshold; flagged three closes running, still unread.

## Suggested starting point

Watch the next two daily mailwatch runs (10:00 Brisbane) in `journalctl -u
shopwatch-mailwatch.service`: expect "rendered N" lines on any real offer without a code,
no "RENDER FAILED" lines, and a code on any recorded percent-off. If egress-watch digests
are the only noise, allowlist the image hosts and move on.
