#!/usr/bin/env bash
# One-time Deck-side setup for the symlink-to-home deploy strategy.
#
# Background: Decky's plugin loader runs as root and re-chowns its plugins/
# entries to root on every load (see decky_loader/plugin/plugin.py:50-58 and
# the CHOWN_PLUGIN_PATH env gate). A directly-rsync'd plugin dir loses
# deck-ownership the moment Decky loads it, breaking sudoless deploys.
#
# The workaround this script implements:
#   DECK_PLUGIN_LINK (in ~/homebrew/plugins/, root-owned namespace)
#     ── symlink ──>
#   DECK_PLUGIN_DIR  (under /home/deck/, fully deck-owned)
#
# Decky's chown lands on the symlink itself (or fails silently); the actual
# files under DECK_PLUGIN_DIR stay deck-owned and rsync-writable forever.
#
# What this does (idempotent, in this order — order matters):
#   1. mkdir -p DECK_PLUGIN_DIR             (deck-owned, no sudo)
#   2. sudo: replace DECK_PLUGIN_LINK with a symlink → DECK_PLUGIN_DIR
#   3. Call deploy.sh --no-reload           (lands files into target dir)
#   4. sudo: restart plugin_loader.service  (Decky now scans → finds the
#      symlink → finds plugin.json → loads our plugin → re-injects QAM)
#
# If we restarted plugin_loader BEFORE step 3, Decky's scan would find an
# empty target dir, skip the plugin, and never retry — that was the original
# ordering bug.
#
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ -f scripts/.deploy-env ]]; then
  # shellcheck disable=SC1091
  source scripts/.deploy-env
fi
: "${DECK_HOST:?DECK_HOST not set in scripts/.deploy-env}"
: "${DECK_SSH_PORT:=22}"
: "${DECK_PLUGIN_DIR:=/home/deck/decky-plugins/mod_manager}"
: "${DECK_PLUGIN_LINK:=/home/deck/homebrew/plugins/mod_manager}"

echo "==> Setup target on $DECK_HOST:"
echo "    DECK_PLUGIN_DIR  (files live here, deck-owned) = $DECK_PLUGIN_DIR"
echo "    DECK_PLUGIN_LINK (symlink Decky reads)         = $DECK_PLUGIN_LINK"
echo "    Will also restart plugin_loader.service after deploying files."
echo
read -r -p "Continue? [y/N] " ans
[[ "$ans" =~ ^[Yy]$ ]] || { echo "aborted"; exit 1; }

# Step 1 + 2: create dir + symlink. One sudo prompt for ln/rm.
ssh -t -p "$DECK_SSH_PORT" "$DECK_HOST" "
  set -e
  src='$DECK_PLUGIN_DIR'
  link='$DECK_PLUGIN_LINK'

  mkdir -p \"\$src\"

  if [[ -L \"\$link\" && \"\$(readlink \"\$link\")\" == \"\$src\" ]]; then
    echo '--- symlink already correct ---'
  else
    echo \"--- replacing \$link with symlink -> \$src ---\"
    sudo rm -rf \"\$link\"
    sudo ln -s \"\$src\" \"\$link\"
  fi
  ls -ld \"\$link\"
"

# Step 3: land files into the now-existing deck-owned target. Reuses
# deploy.sh's whitelist + rsync rules. --no-reload because Decky may not
# even know about our plugin yet (no process to pkill); we restart the
# whole loader next.
echo
echo "==> Deploying initial payload"
./scripts/deploy.sh --no-reload

# Step 4: now that plugin.json exists in the symlink target, restart the
# loader so Decky scans and discovers the plugin. Same ssh -t to reuse the
# sudo session if the password is still cached.
echo
echo "==> Restarting plugin_loader so Decky picks up the plugin"
ssh -t -p "$DECK_SSH_PORT" "$DECK_HOST" "sudo systemctl restart plugin_loader"

echo
echo "==> Setup complete. Plugin should appear in QAM within a few seconds."
echo "    Subsequent iterations: just run ./scripts/deploy.sh (no sudo)."
