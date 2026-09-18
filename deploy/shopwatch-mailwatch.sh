#!/bin/bash
# Read retailer marketing email for offers and post them to the shopwatch board.
# Credentials come from the job-search runner env: the iCloud app password and the
# Claude Code OAuth token are both already there and already proven by /check-seek.
set -euo pipefail
set -a; . /srv/prod/career/runner.env; set +a

REPO=/srv/prod/shopwatch/repo
PY=/srv/prod/shopwatch/mailwatch-venv/bin/python

# Wait for the board to actually answer before reading any mail. A deploy recreates
# the container and changes its IP, and a run that starts mid-restart fails after
# having already spent model calls. Resolve late, and prove it responds.
IP=""
for _ in $(seq 1 30); do
  CANDIDATE=$(docker inspect shopwatch --format "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}" 2>/dev/null || true)
  if [ -n "$CANDIDATE" ] && curl -sf -m 5 "http://$CANDIDATE:8477/healthz" >/dev/null 2>&1; then
    IP="$CANDIDATE"; break
  fi
  sleep 4
done
[ -n "$IP" ] || { echo "shopwatch did not answer within 2 minutes; not reading mail" >&2; exit 1; }

# Where a render fault is announced. Without this the notifier is compiled in and
# silent, which is the failure it exists to prevent. server-alerts already exists
# and is already subscribed; a new topic nobody subscribed to is an alert you
# cannot hear. Runs as root, which is what makes /root/.ntfy_pub_token readable.
export SHOPWATCH_FAULT_NTFY_URL=https://ntfy.lunt.au/server-alerts

export PYTHONPATH="$REPO" SHOPWATCH_URL="http://$IP:8477" SHOPWATCH_DB=/tmp/shopwatch-mailwatch.db
cd "$REPO"
# Only the last fortnight: offers are short-dated and a backfill is a separate job.
exec "$PY" -m app.mailwatch --imap --cli --render --cleanup --since "$(date -d "21 days ago" +%Y-%m-%d)"
