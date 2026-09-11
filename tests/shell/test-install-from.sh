#!/bin/bash
# Control for shopwatch-deploy --install-from.
#
# The bug this guards: the host scripts are versioned in the repo but execute from
# an install path, so editing the repo copy changed nothing in production and the
# deploy still went green. This proves the install actually replaces the target.
#
# Run: bash tests/shell/test-install-from.sh
set -euo pipefail
here=$(cd "$(dirname "$0")/../.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

mkdir -p "$work/src/deploy" "$work/installed"
cp "$here/deploy/shopwatch-deploy" "$work/src/deploy/shopwatch-deploy"
cp "$here/deploy/pre-receive" "$work/src/deploy/pre-receive"

# Seed the install path with deliberately STALE content, which is the real-world
# state this fixes: something copied across by hand at some point in the past.
echo '#!/bin/sh
echo "STALE VERSION"' > "$work/installed/bin"
echo '#!/bin/sh
echo "STALE HOOK"' > "$work/installed/hook"
chmod +x "$work/installed/bin" "$work/installed/hook"

before_bin=$(sha256sum "$work/installed/bin" | cut -d' ' -f1)
grep -q "STALE VERSION" "$work/installed/bin" || { echo "FAIL: fixture not stale"; exit 1; }

SHOPWATCH_BIN="$work/installed/bin" SHOPWATCH_HOOK="$work/installed/hook" \
  sh "$here/deploy/shopwatch-deploy" --install-from "$work/src" >/dev/null

after_bin=$(sha256sum "$work/installed/bin" | cut -d' ' -f1)
src_bin=$(sha256sum "$work/src/deploy/shopwatch-deploy" | cut -d' ' -f1)
src_hook=$(sha256sum "$work/src/deploy/pre-receive" | cut -d' ' -f1)
after_hook=$(sha256sum "$work/installed/hook" | cut -d' ' -f1)

[ "$before_bin" != "$after_bin" ] || { echo "FAIL: install did not change the target"; exit 1; }
[ "$after_bin" = "$src_bin" ]     || { echo "FAIL: installed binary != source"; exit 1; }
[ "$after_hook" = "$src_hook" ]   || { echo "FAIL: installed hook != source"; exit 1; }
grep -q "STALE" "$work/installed/bin" && { echo "FAIL: stale content survived"; exit 1; }
[ -x "$work/installed/bin" ]      || { echo "FAIL: installed binary not executable"; exit 1; }

# Fails closed on a source that has no scripts, rather than silently doing nothing.
mkdir -p "$work/empty/deploy"
if SHOPWATCH_BIN="$work/installed/bin" SHOPWATCH_HOOK="$work/installed/hook" \
     sh "$here/deploy/shopwatch-deploy" --install-from "$work/empty" 2>/dev/null; then
  echo "FAIL: accepted a source with no scripts"; exit 1
fi

echo "PASS: install replaces stale targets, verifies hashes, and fails closed"
