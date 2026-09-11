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

- **Tests:** 220 passed, `ruff check .` clean
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

## Two more rounds after the session-end brief above

**Adapter probe (#42 to #45).** The README recorded two adapters as "untested". Both
work. That turned up three things: retailer stock numbers were being read as model
mismatches, the scraping table was measured before those adapters had ever run, and the
real reason for having no timer is egress monitoring rather than broken scraping.

**xhigh review (#47 to #52), 15 findings, all fixed.** Six were in work from the same day.

| | |
|---|---|
| #47 | Crowdshop's price guide read "Dispatch 3 to 5 business days" as a range and promoted **$3** as the advertised price, written as LIVE provenance. The historical low never rises, so it would have been permanent. Dormant only because that listing has no URL. |
| #48 | model identity now decided by the schema.org key (`mpn`/`model` against `sku`), not the string's shape, which was wrong in both directions. `model_matches` also accepted `"XY"` and `"930"` as the model. |
| #49 | the dash purge missed the two widest emitters; `tagFor` re-rendered a ruled-out listing as "excellent" after an inline edit |
| #50 | a `FLAGGED` model aspect could never be cleared by any run, only by hand |
| #51 | the first schema.org `Product` block won, so a carousel entry's price could be written to the listing |
| #52 | README miscounted which run failures are `errors` against `unresolved`, and still handed over cron and systemd recipes contradicting the no-timer decision |

### Two things to carry into the next review

**Fixes weakened each other.** #48 stopped comparing merchant stock numbers, which
removed the mismatch warning that would have caught #51's wrong-block price. #51 was only
silent because #48 had landed. When a change removes a check, look for what was relying
on it.

**"Grep returned zero" was not proof.** The dash purge reported clean on a search that
could not see the escaped form, and the two it missed were the widest emitters in the
codebase. A text search proves something about the text you searched for, not about the
property you actually care about.

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
