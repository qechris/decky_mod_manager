---
title: Usage
layout: default
nav_order: 3
---

# Usage

## Opening Mod Manager

QAM (right shoulder button or the `...` button) → Decky puzzle-piece
icon → **Mod Manager**.

## Picking a game

You'll see the **Games** tab listing every Steam-installed game we
detected. Proton runtimes and SteamLinuxRuntime variants are filtered
out automatically. Games with installed mods show a count like
"1/2 mods enabled" under the name.

Tap a game to open its detail page. The **←** pill takes you back.

## Game detail page

Three tabs:
- **Mods** — installed mods, turn on/off, remove
- **Get mods** — browse or search Nexus and install directly
- **Tools** — game-specific tools (only appears for games that have them, e.g. W3)

## Installing a mod

### From Nexus

1. **Get mods** tab → pick **Trending**, **Popular**, **New** or
   **Updated**, or type a search and tap **Search**.
2. Tap a result → its files are listed, the recommended one first.
3. Pick a file → tap **Install**.
4. The mod downloads, extracts, and appears in the **Mods** tab, off.
5. Turn it on.

Free Nexus accounts: Nexus only lets premium accounts download straight
from the API. If you're on a free account, the install window asks for
an `nxm://` link. On the mod's Nexus page, press **Mod manager download**,
copy the `nxm://` link, and paste it in.

### From a local archive

1. Drop a `.zip`/`.7z`/`.rar`/`.tar.*` archive somewhere on your Deck
   (e.g. `~/Downloads`).
2. **Mods** tab → **Install from file** → pick the archive.
3. Turn it on.

## Enabling / disabling

Toggle the switch on a mod's row. Internally:
- **Enable**: every file in the mod's library payload gets symlinked
  into the game install. Any vanilla file it would overwrite is moved
  to a per-mod backup first.
- **Disable**: symlinks removed, vanilla files restored from backup.

Both operations are instant and reversible. Save a file mid-game, toggle
a mod, no issue.

## Uninstalling

Mod row → trash button. If the mod was on, it's turned off first.
Library payload and backup dir are deleted. Downloaded archives are
deleted right after install.

If two mods ship the same file, the one turned on last wins. Turning it
off brings back the other mod's file; turning both off brings back the
game's own file.

## Per-game tools

### Witcher 3

The **Tools** tab in a W3 detail page surfaces:
- Proton-side Script Merger (download + launch via Proton)
- Native Linux script merger (`diff3`-based, no Proton round-trip)
- Native settings merger (`input.xml` + `userConfigDef.xml`)
- "Remove merged outputs" — wipes the merged mod + restores baselines
- Diagnostics — shows where `mods.settings` is being written

See the [Witcher 3 guide]({% link games/witcher3.md %}).

### Kingdom Come: Deliverance (1 and 2)

No special tools yet — the handler just manages `mod_order.txt`. See
the [KCD guide]({% link games/kingdom_come.md %}).

## Where your stuff lives

```
~/.local/share/decky-mod-manager/
├── state.json                       # which mods exist, enabled, files installed
├── settings.json                    # your Nexus API key
├── library/<game_id>/<mod_id>/      # extracted mod payloads (sources)
├── backups/<game_id>/<mod_id>/      # vanilla files displaced when you enabled
├── baselines/<game_id>/<rel>/       # baseline snapshots used by settings merger
├── cache/                           # Nexus game list cache
└── tools/                           # third-party tools (Script Merger etc.)
```

The library is independent of the game install. If Steam reinstalls
the game, your mods are still here — just re-enable them.
