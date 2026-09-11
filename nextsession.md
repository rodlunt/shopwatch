# Next session brief: 11/09/2026 (session end)

**Repo:** shopwatch, `main` (protected: PR required, three checks, strict, admins
enforced). Deliberately no SHA here: this file has been invalidated by its own merge
once already.

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

- **Tests:** 199 passed, `ruff check .` clean
- **main == opti:** verified equal and the container healthy after every deploy
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

## Open follow-ups: none

All ten issues from the session-end code review were closed the same night across
five PRs (#36 to #40), one per file domain:

| | |
|---|---|
| #29, #30 | axis bands overlapped when a middle target was NULL; no axis drawn without targets |
| #25, #24 | best marker matched price not listing; axis was invisible to assistive tech |
| #23, #31 | wheel and touch both trapped page scrolling; en dash, dead guard, lane fallback |
| #28, #32 | un-ruling destroyed the reason; endpoint had no tests |
| #27 | healthcheck first probe landed past the deploy's own wait |

Two were the same shape as the bugs found earlier that day: something reporting success
while not doing its job. #23 had two causes where the issue named one, so fixing only
the wheel would have closed it looking resolved while touch users hit the identical wall.

**Not every new test is a control.** Several pass against the pre-fix code by design and
are regression guards; the PRs say which is which. #27 remains **LIKELY** rather than
VERIFIED: it was read off the configured intervals, not reproduced.

## Done after the session-end brief above was written

Four more PRs (#42 to #45), all from probing the two adapters the README had recorded as
"untested":

- **#42** a retailer stock number is not a model mismatch. JB Hi-Fi publishes `893039`
  and The Good Guys `50098655` on the right product pages, so both correct listings were
  about to be tagged as faults by anything that scraped them. Also fixed `model_matches`,
  which promised a punctuation-insensitive comparison while keeping `/`.
- **#43** the scraping table was measured before two adapters had ever run. Both work:
  each returns a price, stock and condition with no warnings. Appliance Central does not
  403, it fetches and parses nothing, which is a different problem.
- **#44** **no timer, and the reason is egress monitoring, not scraping.** Read that
  section before adding one. A scheduled run pushes to `security-events` every pass and
  the alerts cannot be suppressed without weakening a deliberately narrow allowlist.
- **#45** em and en dashes purged from prose and UI copy. One stays in `crowdshop.py`'s
  price-range regex, annotated: it matches a dash in the retailer's HTML, and deleting it
  silently stops range parsing.

**Two of four watchable listings return a price**, not three of five adapters. Crowdshop
has an adapter and no URL so the watcher cannot reach it; Appliances Online has the
opposite problem.

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

**Nothing, and that is the honest answer.** Zero open issues, zero open PRs, clean tree,
everything deployed and verified. The backlog was cleared the same night it was filed.

The one candidate is an **Appliances Online adapter**: they are the only retailer with a
URL and no adapter. I argued against building it and still would. They are $1,169, which
is $269 over the trigger, so they are not a contender. With no timer an adapter only runs
when invoked by hand, and at that point opening the page is just as quick. Their offers
already arrive through the mail watcher, which is the channel that would actually catch a
sale; the adapter would only add the price you would look up afterwards anyway.

If the soundbar still matters, the board is waiting on a retailer to move, not on
software. Better use of a session: a different project.
