# Next session brief: 11/09/2026 (session end)

**Repo:** shopwatch, branch `main` at `8d0eb15` (protected: PR required, three checks,
strict, admins enforced)

> Third brief today. The first two were wrong within hours, so treat this one as
> perishable too: every claim below was read from the live system at session end, but
> that was a point in time.

## Deploying: read this before you push anything

**Merge to `main` is the only path to production.** `git push opti` is rejected at push
time by a `pre-receive` hook. Deploys run from the `Deploy` workflow on opti's
`opti-shopwatch` self-hosted runner, gated on the CI conclusion, against the exact SHA
CI verified.

The workflow now **installs** `deploy/shopwatch-deploy` and `deploy/pre-receive` from the
verified checkout before using them. Until today nothing did: they had been copied across
by hand once, so editing either in the repo merged green, deployed green, and changed
nothing about what actually ran.

| | |
|---|---|
| Live | https://shop.home.lunt.au (LAN only, `basic_auth`) |
| Runner | `actions.runner.rodlunt-shopwatch.opti-shopwatch.service` |
| Host scripts | installed by the deploy; control at `tests/shell/test-install-from.sh` |
| Mail watcher | `shopwatch-mailwatch.timer`, daily 10:00 Brisbane |

## Verification at session end (VERIFIED unless noted)

- **Tests:** 186 passed, `ruff check .` clean
- **main == opti:** both `8d0eb15`, container healthy
- **Installed deploy script == repo copy:** both `921772f52b32`
- **Working tree:** clean. Branches: `main` only, locally and on origin
- **Dependabot:** 0 open alerts

## What this session did

Shipped 10 PRs (#11 to #22). The substantial ones:

- **#8 CI now gates the deploy.** The bare repo used to deploy on push with nothing
  checking CI. Both gate controls were run and watched: a red run left the container
  untouched, and a push to the retired path was refused.
- **#16 One zoomable price axis** carrying every contender, with territory bands.
- **#17 The asset cache-buster had never busted anything.** `?v=` was a constant set in
  the first commit, against Caddy's 30-day immutable cache, so every CSS and JS change in
  this project's history was invisible to a returning browser. Now a content hash.
- **#19 Ruled-out state:** still listed, still plotted, never the answer.
- **#21 Alerts now honour it.** `best_listing()` skipped ruled-out listings; the alert
  engine did not, so a rejected listing could still push "act on it" to your phone.
- **#22 The deploy installs its own host scripts** (above).

## Open follow-ups: 10 issues, all from the session-end code review

Filed 2026-09-11 with verification evidence and confidence labels on each.

| | |
|---|---|
| **#26** | deploy's no-rebuild paths exit 0 without checking the container is alive |
| **#29** | axis bands overlap when an intermediate price target is NULL |
| **#30** | a product with prices but no targets draws no axis at all |
| **#25** | a price tie marks two listings as best (matches on value, not id) |
| **#28** | un-ruling a listing destroys the record of why it was ruled out |
| **#23** | wheel zoom over the axis traps page scrolling |
| **#24** | `role="img"` hides every plotted price from assistive tech |
| **#27** | 120s health budget can be shorter than the first healthcheck probe |
| **#31** | en dash in cluster label, dead `_label` guard, lane fallback overlaps |
| **#32** | no test coverage for the ruled-out API endpoint |

**#26 is the one to do first.** It is the same class as the two fixed today: a path that
reports success without having checked anything.

## The buying decision

Samsung HW-Q930H/XY. Trigger $900 delivered, excellent $850.

| Retailer | Delivered |
|---|---|
| ~~Crowdshop~~ | ~~$869~~ **ruled out**, group-buy, freight never quotable |
| **Appliance Central** | **$990**, the cheapest usable price |
| Appliances Online | $1,169, free delivery confirmed to 4506 |
| Harvey Norman | $1,695, in stock at ~all stores, collect |
| Bing Lee / Betta | $1,695 |
| JB Hi-Fi / The Good Guys | $1,699, free C&C Morayfield |

**$990 is $90 over the trigger and did not move all day.** Every retailer has been priced.
The one cheaper listing is ruled out on its business model, not its price, and a ruled-out
listing is still price-watched, so a genuine collapse would still be recorded (it just
will not alert).

Check `listing_verification` before trusting a number: Appliance Central's $990 is
`VERIFIED` on price, freight and stock; the three added yesterday evening are `IMPORTED`,
meaning read once in a browser and never cross-checked.

## Suggested starting point

Nothing is broken. If you want to build, **#26** is the highest-value issue and the
smallest. If you want to buy, the answer is still "not yet" and nothing on the board can
change that without a retailer moving.
