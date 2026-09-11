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

  ⚠ **Known gap.** The house standard is that anything deployed on opti carries a SOPS
  vault at `smart-home:opti-stacks/<stack>/secrets.sops.env`, rendered by
  `sops-render.sh`. This stack does not have one: its `.env` was written by hand during
  first deployment. It currently holds no live secret (alerting is off, so the ntfy
  fields are empty), so nothing is at risk today, but the moment a token goes in there
  it should move into SOPS first.

- **The mail watcher** reuses credentials that already exist in
  `/srv/prod/career/runner.env` on opti: the iCloud app password and the Claude Code
  OAuth token. It stores no credential of its own, and the local Thunderbird path needs
  none at all.

## If this is an active incident

Rotate in this order: the `basic_auth` hash (`CADDY_HASH_SHOPWATCH` in the caddy SOPS
vault), then the iCloud app password, then the Claude Code OAuth token. Take a database
backup first (`POST /api/backup`); price history is append-only and worth keeping.
