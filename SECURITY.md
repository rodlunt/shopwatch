# Security

This is a private, single-user application. It runs on a home network behind
`basic_auth` and is not reachable from the internet.

## Reporting

Raise a GitHub issue on this repository, or email rodneylunt79@gmail.com if the issue
should not sit in an issue title. There is no bug bounty and no coordinated disclosure
process: this repo has one user, and that user is the person reading the report.

## What this application holds

Worth knowing before deciding how sensitive a given bug is:

- Purchase records, including what was paid, when, from whom, and order references.
- Retailer page URLs and research notes.
- Offers read out of personal email, including the sending address and subject.

It holds no payment details, no card numbers and no retailer account credentials.

## Where secrets live

- **Local development:** a gitignored `.env`. `.gitignore` has covered `.env*` since the
  first commit.
- **CI:** GitHub Actions secrets. The workflows in this repo currently need none.
- **Deployed on opti:** `/srv/prod/shopwatch/.env`, mode 0600, root-owned, never in git.
  **Rendered, never hand-written**, from the SOPS vault at
  `smart-home:opti-stacks/shopwatch/secrets.sops.env` via `sops-render.sh shopwatch`.
  The age private key lives only on opti. It carries the ntfy topic URL and publish
  token and nothing else; non-secret tuning sits in the compose file, in git, where it
  can be reviewed.

- **The mail watcher** reuses credentials that already exist in
  `/srv/prod/career/runner.env` on opti: the iCloud app password and the Claude Code
  OAuth token. It stores no credential of its own, and the local Thunderbird path needs
  none at all.

- **The product wizard's research runner** (`deploy/research-runner.py`, not yet wired
  into opti) reuses the same `/srv/prod/career/runner.env` Claude Code OAuth token as
  the mail watcher, for the same reason: nothing new to store or rotate. It runs as its
  own host-level script, never inside the `shopwatch` container - the container this
  API serves from never holds this credential and never gains new outbound egress.

## If this is an active incident

Rotate in this order: the `basic_auth` hash (`CADDY_HASH_SHOPWATCH` in the caddy SOPS
vault), then the iCloud app password, then the Claude Code OAuth token. Take a database
backup first (`POST /api/backup`); price history is append-only and worth keeping.
