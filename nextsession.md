# Next session brief: 19/09/2026
Branch: main

## What shipped this session

18 PRs merged, all deployed and independently verified live (not just CI-green):
#95, #96, #102, #103, #104, #105, #106, #107, #108, #109, #110, #111, #112, #113,
#114, #115, #116, #117, #118, #119 (+ this housekeeping commit, about to land).

In rough chronological order:
- **#95/#96**: historical-low research (kind="historical_low" research jobs), and
  "add a listing by pasting a URL" (derives retailer from domain, scrapes or queues
  research).
- **#102**: optional promo/deal end-date on a listing.
- **#103**: historical-low research also surfaces other retailers it notices, tick-
  to-add (with an XSS fix for LLM-relayed URLs, validated at three layers).
- **#104**: clarified "Add retailer manually" vs "Add from a URL" button labels.
- **#105**: retailers get a stable hashed colour, shared between axis dot and
  listing row.
- **#106/#107**: trigger/excellent/historical_low_price auto-derive from
  lowest_known_price when unset (never overwrites a hand-set value), plus a one-
  time startup backfill for products that already existed before this shipped.
- **#108/#109/#110**: three rounds fixing price-axis label collisions - merging
  exact-duplicate-value marks, then lane-stacking near-miss collisions, then fixing
  the lane-stacking's own collision with the bands strip beneath it. Each was
  reproduced live via direct DOM measurement before being called fixed.
- **#111**: historical-low date/retailer/notes now shown on the product page, not
  just buried in Edit.
- **#112/#113**: retailer exclusion - a new Retailers nav page, cascades to
  deactivate that retailer's existing listings everywhere, blocks new adds, filters
  research candidates and pickers, and tells the historical-low LLM prompt directly
  to disregard excluded retailers (not just filtering its output after the fact).
- **#114**: groups can now be deleted; an empty group (last member left or deleted)
  removes itself automatically. Root-caused a real production incident from this: the
  "Smart Tags" group got auto-deleted, traced to a genuine CSS bug (zero gap between
  the new Delete-group button and the panel below when a group has no priced
  candidates), fixed and the group recreated by hand.
- **#115**: breadcrumbs on every page (a grouped product's crumb names and links its
  group).
- **#116/#117/#118**: three rounds of card-margin/max-width sweeps, all found by
  measuring live rather than eyeballing screenshots - a `.product` card has no
  padding of its own, every direct child must self-inset, and this bit multiple
  times until swept comprehensively.
- **#119**: historical-low notes render as real dot points (`reason_points` in the
  LLM prompt, `notes_html` Jinja filter + `notesElement` JS twin), with full
  backward compatibility for old single-paragraph notes. Also fixed the actual cause
  of a garbled truncation artifact seen live on a real product (a hard 500-char
  slice cutting mid-sentence).

Plus this session-end housekeeping commit: two README gaps filled in (the backfill
mechanism, group deletion/auto-cleanup weren't documented at all).

## Files touched (34)

`app/main.py`, `app/store.py`, `app/pricing.py`, `app/research.py`,
`app/provenance.py`, `app/ingest.py`, `app/url_intake.py`,
`deploy/research-runner.py`, `app/static/app.js`, `app/static/style.css`, five
templates (`base.html`, `_product.html`, `product.html`, `group.html`,
`retailers.html`), six new migrations (0010-0015), README.md, and eleven test files.

## Verification

**VERIFIED**: `521 passed in 14.94s` (pytest), `ruff check .` clean throughout every
PR. No Node/Hugo/Vite build step in this stack. Every UI-affecting change was
independently confirmed against the live `shop.home.lunt.au` deployment (direct DOM
measurement via javascript_tool, not just screenshots) after each deploy, not just
trusted from CI.

## Open follow-ups

- **0 open GitHub issues**, **0 open PRs**. Everything filed this session got built
  and merged in the same session.
- `~/.claude/instructions/repo-setup.md` is 273 hand-written lines, ~3.7x the next-
  largest instruction file - GUESSING it's worth a trim pass, but unverified this
  session (never read its content, just counted lines).
- A few PRs left explicit open design questions in their bodies that nobody has
  weighed in on yet, worth a look if any of this feels wrong in practice:
  - #105: retailer colour is hashed globally (same colour on every product a
    retailer appears on), not reset per-product like the group page's candidate
    colours.
  - #106: `kind` column on `research_jobs` vs a separate table for historical-low
    jobs (mirrors `llm_jobs`' existing pattern, reversible if wanted).
  - #113: excluding a retailer does NOT retroactively remove it from a group's
    already-drawn axis/candidate list on group pages specifically (only from
    product-level adds/research/pickers) - not verified either way this session.

## Suggested starting point next session

Nothing broken or pending: this was a long, self-contained UI/feature session for
shopwatch and everything shipped is live and confirmed. Natural next step is just
using the app normally (you'll notice anything still off faster than a sweep will)
or picking up one of the three design questions above if any of them are bugging
you in practice.
