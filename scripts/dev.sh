#!/usr/bin/env bash
# Fully automatic dev loop: edit → save → deployed to Deck.
#
# Runs `rollup -c -w` so dist/ stays fresh, plus an fswatch loop that
# rsyncs to the Deck whenever any tracked file changes.
#
# Prereqs: brew install fswatch
#
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

command -v fswatch >/dev/null || { echo "fswatch not installed (brew install fswatch)"; exit 1; }

# Initial build + deploy so the Deck starts in sync.
./scripts/deploy.sh

# Background: keep dist/index.js rebuilding on every src/ save.
pnpm run watch &
WATCH_PID=$!
trap 'kill $WATCH_PID 2>/dev/null || true' EXIT

# Foreground: watch the runtime payload and deploy on any change.
# -o = one event per batch; -l 0.3 = coalesce bursts (avoid double-deploys
# while rollup is mid-write).
fswatch -o -l 0.3 \
  dist/index.js \
  main.py \
  plugin.json \
  py_modules \
  | while read -r _; do
      echo "==> change detected, deploying"
      ./scripts/deploy.sh --no-build || echo "deploy failed; continuing"
    done
