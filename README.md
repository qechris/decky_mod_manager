# Mod Manager

A [Decky Loader](https://decky.xyz) plugin for installing and managing game
mods on Steam Deck, accessible directly from Game Mode.

## Features

- Auto-detects Steam games (Steam library folders + Proton compatdata)
- Drop-in mod library — point it at any `.zip`, `.7z`, or `.tar.*` archive
- One-tap enable / disable per mod (uses symlinks, so toggling is fast)
- Per-game vanilla backup of any overwritten files, restored on disable
- Uninstall removes the mod and restores all backups
- No game launching required — works entirely on the filesystem

## How it stores things

```
~/.local/share/decky-mod-manager/
├── state.json                # which mods exist, enabled state, file lists
├── library/<game_id>/<mod>/  # extracted mod payloads
└── backups/<game_id>/<mod>/  # vanilla files displaced by a mod
```

Mods are applied to the game by symlinking each file from
`library/<game_id>/<mod>/` into the game install directory, mirroring the
mod's internal directory tree.

## Installing a mod

1. Copy the mod archive somewhere on the Deck (e.g. `~/Downloads`).
2. Open the Quick Access menu → Mod Manager.
3. Pick the game, tap **Install Mod**, paste or browse to the archive path.
4. Toggle the mod on or off any time.

## Building

```bash
pnpm install
pnpm run build
```

Then symlink or copy this directory into `~/homebrew/plugins/`.
