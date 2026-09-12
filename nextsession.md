# Next session brief: 12/09/2026

Branch: `fix/json-reply-parsing-trailing-data-remaining-sites`

## Commits this session (this thread, most recent first)

- `33a7e73` fix: apply the JSON trailing-data fix to the two other CLI-reply parsers (PR #75, open, not yet merged)
- `1a12ba3` Merge PR #74: llm-helper parse_reply trailing-data fix
- `bea43dd` Merge PR #72: app logo, dark-mode screenshots, drop shadow, click-to-expand
- `545905a` Merge PR #73: CONTRIBUTING.md
- `cc7b065` Merge PR #71: MIT to PolyForm Noncommercial license swap
- (+ this housekeeping commit, about to land)

Full 24h log runs to 95 commits; the above is this session's own thread (license, contributing guide, logo/dark-mode screenshots, and the JSON-parsing bug chain), not the whole day's history.

## Files touched (24h window)

82 files. Mainly: `LICENSE`, `README.md`, `CONTRIBUTING.md`, `docs/brand/*`, `docs/screenshots/*` (light/dark PNG pairs replacing the old single-theme JPGs), `app/offers.py`, `deploy/research-runner.py`, `tools/llm-helper.py`, and their test files.

## TODO tracking

No `TODO.md` in this repo. No project `CLAUDE.md` either, so no session lessons were appended anywhere project-local.

## Verification this session

- **VERIFIED**: full pytest suite passes (290 tests), `ruff check .` passes.
- **VERIFIED**: production confirmed live at commit `1a12ba3` via direct SSH/`docker exec` into the running container (both the git SHA label and the fixed `llm-helper.py` content).
- Build verification (Hugo/Vite) not applicable, not asked.

## Open issues

0 open (closed #60 "Now public", an announcement post, during this session-end).

## Open follow-ups

- **PR #75** (`fix/json-reply-parsing-trailing-data-remaining-sites`, this branch) is open, not merged. A fresh `/code-review` pass was launched specifically against it right before this session-end and had not reported back yet when this baton was written — check its result first, act on any findings, then merge.
- **Global instructions audit (read-only, not acted on)**: `~/.claude/instructions/repo-setup.md` is 273 hand-written lines, well over the 55-line trim-candidate threshold, and hasn't been read this session to judge whether that length is justified (GUESSING it's a trim candidate, not verified). `hardening.md` is 74 lines but its own stated design is "one rule per line, case detail lives in `hardening/cases.md`" (LIKELY not padded, matches documented intent) so not flagged as a real candidate despite being over threshold.

## Suggested starting point

Check whether the code-review fork launched against PR #75 has reported back; if findings exist, fix and re-verify before merging PR #75, same discipline as the PR #74 review cycle earlier this session (that one found the identical bug still live in two other files, now fixed here).
