# Next session brief: 11/09/2026 (evening)

**Repo:** shopwatch, branch `main` at `eea0f7f` (protected: PR required, three checks,
admins enforced, no force push)

> Replaces the morning brief, which had gone wrong in four places within a day. Every
> claim below was read from the live system on the evening of 11 Sep, not carried over.

## Deploying: read this before you push anything

**Merge to `main` is the only path to production.** `git push opti` no longer deploys and
will be **rejected** at push time by a `pre-receive` hook.

Until this evening opti deployed from its own bare repo via `post-receive`, so a push with
red tests rebuilt the container anyway. That is closed (#5). Deploys now run from the
`Deploy` workflow on opti's `opti-shopwatch` self-hosted runner, triggered by
`workflow_run` and guarded on the CI conclusion, against the exact SHA CI verified.

| | |
|---|---|
| Live | https://shop.home.lunt.au (LAN only, `basic_auth`) |
| Code | github.com/rodlunt/shopwatch (private) |
| Runner | `actions.runner.rodlunt-shopwatch.opti-shopwatch.service` |
| Deploy script | `/usr/local/bin/shopwatch-deploy` (root 0755, narrow sudoers rule) |
| Bare repo | retired, rejects pushes |
| Mail watcher | `shopwatch-mailwatch.timer`, daily 10:00 Brisbane |

Both gate controls were run and watched: a red CI run left the container untouched
(Deploy run `34586989348` skipped, clone unmoved), and a push to the retired path was
refused with a non-zero exit. Evidence is on issue #5.

## Verification (VERIFIED unless noted)

- **Tests:** 172 passed, `ruff check .` clean
- **CI + Deploy:** both success on `eea0f7f`; opti's clone is at `eea0f7f`, container healthy
- **Dependabot:** 0 open alerts (the `pytest` one cleared on rescan, as predicted)
- **Issues and PRs:** none open. Branches: `main` only
- **Board:** 2 products, 9 listings, 7 offers

## What changed since the morning brief

- **#5 closed.** CI now gates the deploy, with both controls run.
- **#4 closed.** ntfy alerting is **on**, token in the SOPS vault. The morning brief and
  the README both still said it was off; the README is fixed.
- **Appliances Online added to the mail watcher.** They were seeded as a retailer but
  missing from the sender allowlist and the IMAP search tokens, so their mail was never
  even retrieved. Rodney has subscribed; their first email arrived and was correctly
  classified as not an offer.
- **Three retailers priced for the first time:** Appliances Online $1,169 (free delivery
  confirmed to 4506), Bing Lee $1,695, Betta $1,695.

## Corrections to the morning brief

- **The TV record was already right.** It said to check a `-$100.00` trade-up line that
  did not reconcile. It reconciles: the $100 trade-up is inside the $1,399, the note on
  the purchase records the full working, and $1,271.82 x 1.1 = $1,399.00 exactly. Nothing
  to fix. Do not re-open this.
- **Do not try to subscribe to Appliance Central's mailing list.** There isn't one.
  Confirmed 11 Sep. Combined with their adapter getting a 403, they are browser-only in
  both directions, and they hold the best price.

## Open, and honestly stated

- **The price watcher has never run in production.** `scrape_runs` is empty and there is
  no timer, deliberately: too many adapters are blocked for a schedule to be anything but
  a no-op that looks like coverage. Most prices carry provenance `claude-in-chrome`,
  meaning a session read them by hand.
- **The deploy's health loop has been seen to pass, never to catch.** Proving it fails a
  job on a container that never comes up means deliberately shipping a broken image to
  production, which was judged not worth doing to prod.
- **Harvey Norman has no stock or pickup signal.** Their site is Incapsula-blocked.
  Rodney's call: look harder when a price shows up, not before.
- **JB Hi-Fi and The Good Guys freight stays unresolved on purpose.** Collection is
  acceptable to Rodney and both record free Click and Collect at Morayfield, but freight
  was not zeroed: that would claim delivery is free, which is not what is true. The $60
  unresolved-freight penalty is a ranking device only and never displayed.

## The buying decision, as it stands

Samsung HW-Q930H/XY. Trigger $900 delivered, excellent $850.

| Retailer | Advertised | Freight | Delivered |
|---|---|---|---|
| Crowdshop | $869 | **FLAGGED**, checkout quotes none for 4506 | not a price |
| **Appliance Central** | $1,050 less $60 code | $0 | **$990** |
| Appliances Online | $1,169 | $0 (confirmed 4506) | $1,169 |
| Harvey Norman / Bing Lee / Betta | $1,695 | unresolved | collectable |
| JB Hi-Fi | $1,699 | unresolved | free C&C Morayfield |
| The Good Guys | $1,699 | $28 | free C&C Morayfield |

**$990 is still $90 over the trigger and has not moved all day.** Three retailers sitting
on $1,695 is effectively RRP. Only two things can still change it: Crowdshop producing a
delivery quote, or Appliances Online's price match being pointed at something cheaper.

Check `listing_verification` before trusting any number. Appliance Central's $990 is
`VERIFIED` on price, freight and stock; the three added this evening are `IMPORTED`,
meaning read once in a browser and never cross-checked.

## Suggested starting point

Nothing in the repo needs attention. If the soundbar is still live, the highest-value
move is chasing a Crowdshop delivery quote, since it is the only advertised price under
the trigger.
