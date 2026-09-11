## What and why

<!-- What changed, and the reason. Write it for someone reading the history in six
     months, not for someone who watched you do it. -->

Closes #

## Verification

<!-- Name the artefact that proves this works: a test file, a command and its output,
     a screenshot, a live URL. "It works on my machine" is not verification.

     Where this touches a check, gate, guard or watcher, say how you saw it FAIL
     against the broken version. A control that has only ever passed proves nothing. -->

## Checklist

- [ ] `.venv/bin/python -m pytest` passes
- [ ] `.venv/bin/python -m ruff check .` passes
- [ ] Commits follow conventional commits
- [ ] Australian English, no em dashes or en dashes
- [ ] No secrets, `.env` files or personal data added
- [ ] If a value cannot be determined, it is stored as unresolved rather than guessed
