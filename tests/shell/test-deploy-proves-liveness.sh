#!/bin/bash
# Control for: every deploy path proves the container is alive before exiting 0.
#
# The bug this guards: the health check ran only after a rebuild, so "already at
# this SHA" and "no image inputs changed" both exited 0 having checked nothing.
# Re-running the workflow against a crash-looping container printed "nothing to
# do", went green, and left production down.
#
# Run: bash tests/shell/test-deploy-proves-liveness.sh
set -euo pipefail
here=$(cd "$(dirname "$0")/../.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# A source repo with two commits whose diff touches NOTHING in the rebuild trigger,
# so the deploy takes the no-rebuild path: the one that used to check nothing.
src="$work/src"
mkdir -p "$src"
git -C "$src" init -q
git -C "$src" config user.email t@local; git -C "$src" config user.name t
mkdir -p "$src/deploy"
cp "$here/deploy/docker-compose.opti.yml" "$src/deploy/"
echo "one" > "$src/README.md"
git -C "$src" add -A && git -C "$src" commit -qm one
OLD_SHA=$(git -C "$src" rev-parse HEAD)
echo "two" > "$src/README.md"
git -C "$src" add -A && git -C "$src" commit -qm two
NEW_SHA=$(git -C "$src" rev-parse HEAD)

# A stack whose repo sits on the older commit.
stack="$work/stack"
mkdir -p "$stack"
git clone -q "$src" "$stack/repo"
git -C "$stack/repo" checkout -q "$OLD_SHA"

# Stub docker. Reports whatever health status the fixture file says.
bin="$work/bin"; mkdir -p "$bin"
cat > "$bin/docker" <<'STUB'
#!/bin/sh
# only `docker inspect -f '{{.State.Health.Status}}' <name>` is exercised here
cat "$FAKE_HEALTH"
STUB
chmod +x "$bin/docker"

run_deploy() {
  PATH="$bin:$PATH" \
  SHOPWATCH_STACK="$stack" SHOPWATCH_CONTAINER=fake SHOPWATCH_PROBE_SLEEP=0 \
  FAKE_HEALTH="$work/health" \
    sh "$here/deploy/shopwatch-deploy" "$src" "$NEW_SHA"
}

# --- the control: an unhealthy container must FAIL the no-rebuild deploy --------
echo unhealthy > "$work/health"
if run_deploy >"$work/out" 2>&1; then
  echo "FAIL: deploy reported success against an unhealthy container"
  sed 's/^/    /' "$work/out"; exit 1
fi
grep -q "not healthy" "$work/out" || { echo "FAIL: wrong failure reason"; cat "$work/out"; exit 1; }
grep -q "no image inputs changed" "$work/out" || { echo "FAIL: did not take the no-rebuild path"; cat "$work/out"; exit 1; }

# --- and a healthy one must still pass, or the check is just broken -------------
git -C "$stack/repo" checkout -q "$OLD_SHA"
echo healthy > "$work/health"
run_deploy >"$work/out2" 2>&1 || { echo "FAIL: healthy container rejected"; cat "$work/out2"; exit 1; }
grep -q "healthy at" "$work/out2" || { echo "FAIL: no liveness line on success"; cat "$work/out2"; exit 1; }

# --- the already-at-this-SHA path must check too --------------------------------
echo unhealthy > "$work/health"
if run_deploy >"$work/out3" 2>&1; then
  echo "FAIL: 'already at this SHA' reported success against an unhealthy container"
  sed 's/^/    /' "$work/out3"; exit 1
fi
grep -q "already at" "$work/out3" || { echo "FAIL: did not take the already-at path"; cat "$work/out3"; exit 1; }

echo "PASS: all three paths prove liveness before exiting 0"
