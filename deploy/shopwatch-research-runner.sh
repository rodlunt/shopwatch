#!/bin/bash
# Claim and process at most one queued research job, then exit. Fired every 2 minutes
# by shopwatch-research-runner.timer, mirroring shopwatch-mailwatch.sh's own shape.
# Credentials come from the job-search runner env: the Claude Code OAuth token is
# already there and already proven by /check-seek and by mailwatch's own reuse of it.
set -euo pipefail
set -a; . /srv/prod/career/runner.env; set +a

REPO=/srv/prod/shopwatch/repo
PY=/srv/prod/shopwatch/research-venv/bin/python

# Wait for the board to actually answer before claiming a job. A deploy recreates the
# container and changes its IP; a run that starts mid-restart must not silently miss a
# job or, worse, claim one against a container about to disappear.
IP=""
for _ in $(seq 1 30); do
  CANDIDATE=$(docker inspect shopwatch --format "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}" 2>/dev/null || true)
  if [ -n "$CANDIDATE" ] && curl -sf -m 5 "http://$CANDIDATE:8477/healthz" >/dev/null 2>&1; then
    IP="$CANDIDATE"; break
  fi
  sleep 4
done
[ -n "$IP" ] || { echo "shopwatch did not answer within 2 minutes; not claiming a job" >&2; exit 1; }

export SHOPWATCH_URL="http://$IP:8477"
cd "$REPO"
exec "$PY" deploy/research-runner.py --once
