# shopwatch: what you need to know that the repo does not tell you

This file used to be a session diary and was rewritten six times in one day, because a
diary restates conclusions and conclusions rot. SHAs, test counts, PR numbers and issue
lists were wrong within hours every single time.

So it holds two things now: **traps that will cost you if you do not know them**, and
**decisions with the reasoning that produced them**. Neither goes stale on a merge.

Anything countable is a command, not a number.

## Check the current state

```bash
cd ~/Projects/shopwatch
git fetch -q origin && git status -sb | head -1
gh issue list --state open && gh pr list --state open
.venv/bin/pytest tests/ -q | tail -1 && .venv/bin/python -m ruff check .
ssh root@100.115.75.8 'git -C /srv/prod/shopwatch/repo rev-parse --short HEAD; \
  docker inspect -f "{{.State.Health.Status}}" shopwatch'
```

`main` and opti should match, and the container should read `healthy`.

## Traps

**`git push opti` is rejected.** Merge to `main` is the only path to production. The bare
repo that used to accept push-to-deploy keeps a `pre-receive` hook that refuses and says
so. Any note telling you otherwise predates 11 Sep 2026.

**The deploy installs its own host scripts, and did not always.** `deploy/shopwatch-deploy`
and `deploy/pre-receive` execute from an install path. Before the workflow installed them
from the verified checkout, editing either in the repo merged green, deployed green and
changed nothing. If you add another host script, add it to `--install-from` or it will do
the same.

**Static assets are cached immutable for 30 days by Caddy.** The cache-buster is a content
hash of `app/static`. It used to be a hand-maintained constant that was never bumped, so
every CSS and JS change in the project's history was invisible to a returning browser. Do
not replace it with a version string.

**Appliance Central is browser-only in both directions.** Their adapter fetches but parses
nothing, and they have no mailing list at all. They hold the best confirmed price, so this
is the retailer that matters and the one nothing can automate.

**`listing_verification` is the confidence layer.** Per aspect: `VERIFIED`, `IMPORTED`,
`FLAGGED`, plus a note. Read it before trusting a number. `IMPORTED` means read once in a
browser and never cross-checked.

## Decisions, and why

**No timer on the price watch. The reason is egress monitoring, not scraping.** Two of the
four watchable listings return a price, so a schedule would not be a no-op. But opti's
`egress-watch` alerts on a container opening an outbound connection it has not made
before, and a scheduled run pushes to `security-events` every pass. Retailers are
Cloudflare-fronted with rotating anycast IPs so `/32` allowlist entries go stale, and
`allowlist.conf` refuses wide CIDRs by design because a Cloudflare `/13` would blind it to
any container beaconing to any Cloudflare-fronted host. The README's cron and systemd
recipes are kept for the day that changes, and carry the warning.

**Crowdshop is ruled out on its business model, not its price.** $869 is the cheapest
number anyone advertises and it is not a price: they are a group-buy and freight is only
costed after the purchase closes, so there is nothing to quote. Rodney's call: it would
need to be a lot cheaper before the risk is worth it.

**Ruled out is a state, distinct from deactivated.** Deactivated means "not a real
listing" and hides it. Ruled out means "real, and I will not buy it": still listed, still
plotted, still price-watched, never the answer, never alerted on. The reason survives
being put back in the running.

## The buying decision

Samsung HW-Q930H/XY. Trigger $900 delivered, excellent $850.

As at 12 Sep 2026 the cheapest usable price was **$990 at Appliance Central**, $90 over
the trigger, with every retailer priced and the one cheaper listing ruled out. Read it
live rather than trusting that figure:

```bash
ssh root@100.115.75.8 'docker exec shopwatch python3 -c "
import sqlite3
c = sqlite3.connect(\"/data/shopwatch.db\"); c.row_factory = sqlite3.Row
for r in c.execute(\"\"\"select rt.name, l.advertised_price, l.freight, l.ruled_out
                      from listings l join retailers rt on rt.id=l.retailer_id
                      where l.product_id=1 order by l.advertised_price\"\"\"):
    print(dict(r))"'
```

It moves when a retailer moves, not when anyone writes software.

## What two reviews taught, worth applying to the next one

**Fixes weakened each other.** Excluding merchant stock numbers from the model comparison
removed the warning that would have caught a different bug writing the wrong product's
price. That bug was not new; it became **silent**. When a change removes a check, ask what
was leaning on it.

**"Grep returned zero" was not proof.** An em-dash purge reported clean on a search that
could not see the escaped form, and the two it missed were the widest emitters in the
codebase. A text search proves something about the text you searched for, not about the
property you care about.

**Not every new test is a control.** Several written alongside these fixes pass against
the unfixed code by design; they are regression guards. The PRs say which is which, and a
test that has not been watched failing is not evidence.
