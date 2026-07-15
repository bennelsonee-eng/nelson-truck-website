#!/usr/bin/env bash
# Install server-side git hooks for the titan-truck-website deploy.
# Run this ON the titan-prod box:
#   bash /home/titan/titan-truck-website/app/scripts/deploy/install-hooks.sh
#
# Idempotent: backs up any existing hook once (.bak), copies the canonical hook
# from app/scripts/deploy/ into .git/hooks/, makes it executable, and retires the
# legacy post-checkout backend-restart (it never fired on `git pull`).
set -euo pipefail

REPO="/home/titan/titan-truck-website"
SRC="$REPO/app/scripts/deploy"
DST="$REPO/.git/hooks"

for hook in post-merge; do
  if [ -f "$DST/$hook" ] && [ ! -f "$DST/$hook.bak" ]; then
    cp "$DST/$hook" "$DST/$hook.bak"
    echo "backed up existing $hook -> $hook.bak"
  fi
  install -m 0755 "$SRC/$hook" "$DST/$hook"
  echo "installed $DST/$hook"
done

# Retire the legacy post-checkout restart: post-merge now owns backend restart,
# and post-checkout never fired on `git pull`. Disable to avoid double restarts
# on manual checkouts; keep a .disabled copy for reference.
if [ -f "$DST/post-checkout.d/restart-backend.sh" ]; then
  mv "$DST/post-checkout.d/restart-backend.sh" "$DST/post-checkout.d/restart-backend.sh.disabled"
  echo "retired legacy post-checkout.d/restart-backend.sh -> .disabled"
fi

echo "done. active deploy hook: $DST/post-merge"
