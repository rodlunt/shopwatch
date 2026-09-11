# Next session brief: 11/09/2026

**Repo:** shopwatch, branch `main` (protected: CI checks required, admins enforced)

## What this session built

A self-hosted shopping comparison and price-watch board, from nothing to deployed.

**Commits:** 43 on shopwatch, 4 on smart-home (both pushed). Highlights:

- `feat: shopping comparison and price-watch board` - the application
- `feat: product lifecycle, purchase records and price protection`
- `feat(ui): lead with the answer, disclose the detail on demand` - full UI rebuild
- `feat: read retailer marketing email for offers worth acting on`
- `feat: render the email and read the offer off the artwork`
- `chore: GitHub repo furniture to the house private-repo standard`

## Where it lives

| | |
|---|---|
| Live | https://shop.home.lunt.au (LAN only, `basic_auth`, own `CADDY_HASH_SHOPWATCH`) |
| Code | github.com/rodlunt/shopwatch (**private**, created this session) |
| Deploy | push to the `opti` remote; `post-receive` rebuilds the container |
| Stack | `/srv/prod/shopwatch` on opti, Dockge-managed, no published host port |
| Mail watcher | `shopwatch-mailwatch.timer`, daily 10:00 Brisbane |

## Verification (VERIFIED unless noted)

- **Tests:** 172 passed, `ruff check .` clean
- **CI:** three jobs (test, lint, audit) green on main
- **pip-audit:** clean across `requirements.txt` and `requirements-dev.txt`
- **Container:** healthy; gate returns 401 unauthenticated, 200 with the password
- **Mail watcher:** runs clean end to end; read-then-clear proven live (INBOX 15 to 14)
- **Build verification:** skipped, no Hugo or Vite in this project (not a failure)

## Open follow-ups

- **#4** Move the opti `.env` into a SOPS vault. Holds no live secret today, so nothing
  is at risk, but it should move before a token goes in.
- **#5** CI does not gate the deploy. opti deploys from its own bare repo, so a broken
  push to `opti` will still deploy. Two options written up in the issue.
- **Dependabot:** 1 alert (`pytest < 9.0.3`) still showing; the fix is on main and this
  is rescan lag, same pattern as the 21 that cleared earlier. LIKELY clears on next scan.
- **ntfy alerting is off** by choice. Turning it on cuts across the house
  "ntfy is for faults only" policy, so it is a decision, not a default.
- **Appliance Central** hold the best confirmed price ($990) and send no email. Worth
  subscribing to their list so the watcher can see their offers.

## The buying decision, as it stands

Samsung HW-Q930H/XY. Only confirmed delivered price is **$990 at Appliance Central**
($1,050 less the SAVENOW code, free shipping to 4506 confirmed), which is $90 over the
$900 trigger. Crowdshop's $869 would beat it but their checkout still will not quote a
delivery, so it is not a price yet. Harvey Norman and JB Hi-Fi freight remain unknown.

The Samsung S85H TV is recorded as bought (7 Sep, $1,448, Samsung Australia direct).
**Check that one:** the order shows a `-$100.00` trade-up line that does not reconcile
with the stated total, so if you actually paid $1,348 the record needs correcting.

## Suggested starting point

Check whether the 10:00 mail-watch run found anything, then decide on issue #5: a deploy
that no test can block is the largest remaining hole in this stack.
