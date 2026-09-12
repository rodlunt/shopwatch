# Contributing

Shopwatch is a personal homelab project, built and maintained by one person for one
household. It's public because there's no reason to hide it, not because it's looking
for a team.

## Issues

Bug reports and feature requests are welcome, use the templates. A bug report with a
failing test or an exact repro gets looked at faster than a description of a feeling.
A feature request that names the buying decision it would help with gets a better
answer than one that names a feature.

## Pull requests

Small, focused fixes (a genuine bug, a broken doc link, a typo) are easy to review and
usually get merged. Anything bigger - a new feature, a new retailer adapter, a
refactor - open an issue first and say what you want to do before spending time on it.
Scope and direction for this project are the maintainer's call, and that's decided
faster in an issue than in review comments on a finished PR.

If you do send a PR: match the existing conventions (conventional commits, Australian
English, the checklist in the PR template), and run the tests and linter locally first.

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
```

## License terms for contributions

Shopwatch is licensed under [PolyForm Noncommercial 1.0.0](LICENSE), not a
traditional open-source license - noncommercial use is free, commercial use needs a
separate arrangement with the maintainer. By submitting a contribution, you agree it's
offered under those same terms unless you and the maintainer agree otherwise in
writing. If that's not workable for you, it's better to know before opening a PR than
after.
