# Next session brief: 12/09/2026 (session end)

**Repo:** shopwatch, `main` (protected: PR required, CI checks, strict). Deliberately no
SHA here.

> This file used to carry commit SHAs, test counts and PR numbers as facts. That
> stopped in an earlier session (11-12 Sep 2026) because every one of those goes stale
> the moment the next merge lands, and the file was rewritten six times in one day for
> exactly that reason - a code-review pass this session caught this brief reintroducing
> the same anti-pattern on its first draft. Everything countable below is a command to
> re-derive it live, not a number to trust.

## Deploying: read this before you push anything

Merge to `main` is the only path to production. `git push opti` is rejected at push
time. Deploys run from the `Deploy` workflow on opti's self-hosted runner, gated on CI,
against the exact SHA CI verified.

**The rebuild-trigger regex must list every path the Dockerfile `COPY`s.** It missed
`tools/` once: a real fix shipped, CI went green, and the container kept serving the old
file with nothing reporting it. Check `deploy/shopwatch-deploy`'s trigger regex against
the Dockerfile's `COPY` lines whenever a new top-level directory becomes something the
app depends on.

## Verify current state (run these, do not trust remembered numbers)

```bash
git log --oneline -10                               # what actually landed last
.venv/bin/python -m pytest -q                        # test count, current
.venv/bin/python -m ruff check .                     # lint
gh pr list --state open                              # what's still open
gh issue list --state open                            # what's still open
ssh root@100.115.75.8 "docker exec shopwatch cat /app/git_sha 2>/dev/null || \
  docker inspect shopwatch --format '{{index .Config.Labels \"org.opencontainers.image.revision\"}}'"
                                                      # what's actually deployed
```

## Decisions this session, with reasoning

- **License is PolyForm Noncommercial 1.0.0, not MIT.** Free for noncommercial use;
  commercial use needs a licence from Rodney. GitHub's own license badge will always
  show "Other" for this - confirmed permanent (`licensee`'s known-license list is
  OSI-style-only by design, PolyForm isn't in it and never will be), not a formatting
  problem with the LICENSE file. Don't spend time trying to make the badge accurate.
- **Three JSON-reply parsers (`app/offers.py`, `deploy/research-runner.py`,
  `tools/llm-helper.py`) each pull one JSON object out of a CLI's text reply, and
  deliberately do NOT share a helper module** - each runs in a different execution
  context (in-container, host-only, user's-own-machine) this codebase keeps
  independent by design. Expect near-identical code in all three. A fix to the parsing
  logic in one almost certainly needs the identical fix in the other two: this happened
  for real this session, a first fix landed in `llm-helper.py` alone, and a
  `/code-review` pass caught the same bug still live in the other two.
- **The parsing fix takes the LAST complete JSON object in a reply, not the first.**
  Deliberate, not an oversight: every real reply reproduced this session that stated a
  draft or reference case before the real answer put the real answer last. This does
  not guarantee correctness if a reply ever states the real answer first and a
  counter-example after it; that trade-off was accepted rather than engineering for a
  pattern nothing has actually produced.
- **Dark-mode screenshots need a real capture, not just trusting the CSS.** Switching
  `emulate({colorScheme})` on an already-open `<dialog>` produces a stale-paint
  screenshot even though `getComputedStyle` and `matchMedia` both report the change
  correctly - reload or navigate fresh in the new scheme BEFORE opening any dialog,
  never mid-session with one already open.

## Open follow-ups

```bash
gh pr view 75   # the JSON-parsing fix PR - confirm merged; if not, why not
```

If PR #75 is still open: a `/code-review` pass was running against it when this session
ended and its findings were already acted on in the branch itself (leading-JSON-object
silent-wrong-answer bug, a `found`/NaN type-confusion bug in the research runner, a
non-dict-candidate crash, a RecursionError left uncaught, and a fragile test) - read the
PR body for the full list before assuming it still needs work.

## Suggested starting point

Run the verification commands above first. If PR #75 is merged and CI/deploy match,
this session's work needs no further checking.
