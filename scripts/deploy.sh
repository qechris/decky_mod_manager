#!/usr/bin/env bash
# Deploy the mod-manager plugin to a Steam Deck over SSH.
# Path B from the dev workflow: skip the Decky CLI, plain rsync + reload.
#
# Usage:
#   cp scripts/.deploy-env.example scripts/.deploy-env   # fill in your Deck
#   scripts/deploy.sh                                    # build + push + reload
#   scripts/deploy.sh --no-build                         # skip pnpm build (frontend unchanged)
#   scripts/deploy.sh --no-reload                        # land files without nudging Decky
#                                                        # (used by setup-deck.sh on fresh installs)
#
set -euo pipefail

# Parse flags (order-independent).
NO_BUILD=0
NO_RELOAD=0
for arg in "$@"; do
  case "$arg" in
    --no-build)  NO_BUILD=1 ;;
    --no-reload) NO_RELOAD=1 ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# --- config ---------------------------------------------------------------
# Loaded from scripts/.deploy-env (gitignored). Override via env if you like.
if [[ -f scripts/.deploy-env ]]; then
  # shellcheck disable=SC1091
  source scripts/.deploy-env
fi

: "${DECK_HOST:?DECK_HOST not set (e.g. deck@steamdeck.local, or deck@192.168.1.42)}"
: "${DECK_SSH_PORT:=22}"
DECK_PLUGIN_DIR="${DECK_PLUGIN_DIR:-/home/deck/decky-plugins/mod_manager}"
# This is the SYMLINK TARGET (deck-owned) — not Decky's canonical
# ~/homebrew/plugins/ path, which is just a symlink pointing here. See
# scripts/setup-deck.sh for the rationale.

SSH=(ssh -p "$DECK_SSH_PORT" "$DECK_HOST")

# --- build ----------------------------------------------------------------
if [[ $NO_BUILD -eq 0 ]]; then
  echo "==> pnpm build"
  pnpm run build
fi

# --- push -----------------------------------------------------------------
# Whitelist the runtime payload; exclude dev/source/meta.
#
# Target is a deck-owned dir, with a symlink to it from Decky's
# ~/homebrew/plugins/ namespace. setup-deck.sh creates both. We do NOT
# mkdir here on purpose: if it's missing, we want a loud rsync failure,
# not a silent wrong-place deploy.
echo "==> rsync to $DECK_HOST:$DECK_PLUGIN_DIR"

# --inplace: Decky chowns the plugin dir and plugin.json to root when it
# loads the plugin, so rsync can't create temp files there.
rsync -azP --delete --inplace \
  -e "ssh -p $DECK_SSH_PORT" \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --include='main.py' \
  --include='plugin.json' \
  --include='package.json' \
  --include='README.md' \
  --include='LICENSE' \
  --include='dist/***' \
  --include='py_modules/***' \
  --include='defaults/***' \
  --include='bin/***' \
  --exclude='*' \
  ./ "$DECK_HOST:$DECK_PLUGIN_DIR/"

# --- reload ---------------------------------------------------------------
reload_plugin() {
  # Killing the backend process leaves Decky 3.2 spinning on the dead socket,
  # so ask Decky to reload it through the Steam CEF debugger (port 8080).
  "${SSH[@]}" -f -o ExitOnForwardFailure=yes -L 8081:localhost:8080 sleep 10
  node scripts/reload.mjs 8081
}

if [[ $NO_RELOAD -eq 0 ]]; then
  reload_plugin
else
  echo "==> skipping reload (--no-reload)"
fi

echo "==> done"
