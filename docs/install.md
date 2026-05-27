---
title: Install
layout: default
nav_order: 2
---

# Install

## Prerequisites

- A Steam Deck (or any SteamOS-like system) running [Decky Loader](https://decky.xyz)
  3.2 or newer. Other distros (Bazzite, HoloISO, ChimeraOS) should work
  if Decky runs.
- An internet connection for the Nexus browser. Local-archive installs
  work offline.
- *(Optional)* A free [Nexus Mods](https://www.nexusmods.com) account if
  you want Browse-Nexus to work. You'll generate a personal API key.

## Option 1 — Install from release (recommended once releases ship)

1. On the Deck, open **Settings → Decky → Plugins → Install from URL**.
2. Paste the latest `.tar.gz` URL from
   [GitHub Releases](https://github.com/qa-chrisb/decky_mod_manager/releases).
3. Decky downloads + installs. The plugin appears in the QAM under the
   Decky puzzle-piece icon as "Mod Manager".

> No release tagged yet — use Option 2 for now.

## Option 2 — Install from source

Requires `git`, `pnpm`, Node 20+, and `rsync` on your dev machine.
Steam Deck side just needs SSH enabled (see [Enabling SSH](#enabling-ssh-on-the-deck)).

```bash
# On your dev machine:
git clone https://github.com/qa-chrisb/decky_mod_manager.git
cd decky_mod_manager
pnpm install
pnpm run build

# Configure your Deck's address:
cp scripts/.deploy-env.example scripts/.deploy-env
$EDITOR scripts/.deploy-env       # set DECK_HOST etc

# One-time Deck setup (creates the symlink-to-home layout + first deploy):
./scripts/setup-deck.sh
```

The plugin appears in the QAM right after `setup-deck.sh` finishes.

To redeploy after edits: `./scripts/deploy.sh`. For an automatic dev
loop (rebuild + redeploy on every save), `./scripts/dev.sh` (requires
`fswatch`).

## Option 3 — Manual zip install (no dev machine)

If you can't run a dev box but want to install from source:

1. Download the repo zip from GitHub.
2. On Deck in Desktop mode, extract to a folder.
3. Run `pnpm install && pnpm run build` inside that folder (install Node first via Discover or pacman).
4. Copy the whole folder to `~/homebrew/plugins/Mod Manager/`.
5. Restart Decky from settings or `sudo systemctl restart plugin_loader`.

This isn't well-supported — Option 2 from a real dev machine is much smoother.

## Setting up your Nexus API key

1. Sign in at [nexusmods.com](https://www.nexusmods.com).
2. **My account → API Access → Generate a personal API key**.
3. Copy it.
4. On the Deck, QAM → Decky → Mod Manager → Back-arrow to Decky home → **Settings → New API key → paste → Save key**.
5. The key is stored in `~/.local/share/decky-mod-manager/settings.json`
   on the Deck. It's never sent anywhere except `api.nexusmods.com`.

> Free Nexus accounts can search and view metadata, but downloading
> through the API requires a one-time NXM:// link click from the mod's
> Nexus page in a browser. Premium accounts can download directly.

## Enabling SSH on the Deck

In Desktop mode:
```bash
passwd                                  # set a deck-user password
sudo systemctl enable --now sshd        # turn SSH on
hostname -I                             # find the Deck's IP (or use steamdeck.local)
```

From your dev machine: `ssh deck@steamdeck.local` should now work. If
mDNS doesn't resolve, use the IP from `hostname -I` instead.

## Updating

- From release: same as install — Decky shows an update notification.
- From source: `git pull && ./scripts/deploy.sh`.

## Uninstalling

QAM → Decky → ⚙ Plugins → **... → Uninstall** on Mod Manager. To wipe
state too: `rm -rf ~/.local/share/decky-mod-manager/`.
