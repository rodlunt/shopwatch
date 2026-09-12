#!/bin/bash
# Control for: every path the Dockerfile COPYs into the image must trigger a rebuild
# when it changes, not just Dockerfile/requirements.txt/app/ themselves.
#
# The bug this guards: the Dockerfile gained `COPY tools ./tools` (PR #66, for
# tools/llm-helper.py) without the rebuild-trigger regex gaining `tools/` to match. A
# real fix confined to that directory (PR #67, codex's --skip-git-repo-check) diffed
# clean against every pattern in the old regex, the deploy printed "no image inputs
# changed", and the running container kept serving the stale file while the Deploy
# workflow, the git log and the deploy's own message all said the new commit was live.
#
# Run: bash tests/shell/test-deploy-rebuild-trigger.sh
set -euo pipefail
here=$(cd "$(dirname "$0")/../.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# A source repo whose second commit touches ONLY tools/ - nothing under app/, no
# Dockerfile, no requirements.txt, no compose file. Exactly PR #67's shape.
src="$work/src"
mkdir -p "$src/deploy" "$src/tools"
git -C "$src" init -q
git -C "$src" config user.email t@local; git -C "$src" config user.name t
cp "$here/deploy/docker-compose.opti.yml" "$src/deploy/"
echo "one" > "$src/tools/llm-helper.py"
git -C "$src" add -A && git -C "$src" commit -qm one
OLD_SHA=$(git -C "$src" rev-parse HEAD)
echo "two - with --skip-git-repo-check" > "$src/tools/llm-helper.py"
git -C "$src" add -A && git -C "$src" commit -qm two
NEW_SHA=$(git -C "$src" rev-parse HEAD)

stack="$work/stack"
mkdir -p "$stack"
git clone -q "$src" "$stack/repo"
git -C "$stack/repo" checkout -q "$OLD_SHA"

# Stub docker: always healthy, and records whether `compose up --build` was invoked -
# that invocation is the only observable proof a rebuild actually happened.
bin="$work/bin"; mkdir -p "$bin"
cat > "$bin/docker" <<STUB
#!/bin/sh
if [ "\$1" = "inspect" ]; then
  echo healthy
  exit 0
fi
echo "\$@" >> "$work/docker-calls"
exit 0
STUB
chmod +x "$bin/docker"

PATH="$bin:$PATH" \
SHOPWATCH_STACK="$stack" SHOPWATCH_CONTAINER=fake SHOPWATCH_PROBE_SLEEP=0 \
  sh "$here/deploy/shopwatch-deploy" "$src" "$NEW_SHA" >"$work/out" 2>&1 \
  || { echo "FAIL: deploy exited non-zero"; cat "$work/out"; exit 1; }

grep -q "image inputs changed, rebuilding" "$work/out" \
  || { echo "FAIL: a tools/-only change did not trigger a rebuild"; cat "$work/out"; exit 1; }
[ -f "$work/docker-calls" ] && grep -q "compose up" "$work/docker-calls" \
  || { echo "FAIL: docker compose up --build was never actually invoked"; exit 1; }

echo "PASS: a tools/-only change correctly triggers an image rebuild"
