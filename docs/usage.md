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

Tap a game to open its detail page.

## Game detail page

Three tabs:
- **Mods** — installed mods, toggle on/off, uninstall
- **Nexus** — search Nexus and install directly
- **Tools** — game-specific tools (only appears for games with custom handlers, e.g. W3 + KCD)

## Installing a mod

### From Nexus

1. **Nexus** tab → type your search → tap **Search** (or press Enter on the OSK).
2. Tap a result → file picker modal opens.
3. Pick a file variant (MAIN, OPTIONAL, etc.) → tap **Install**.
4. The mod downloads, extracts, and appears in the **Mods** tab —
   disabled by default.
5. Toggle it on.

### From a local archive

1. Drop a `.zip`/`.7z`/`.rar`/`.tar.*` archive somewhere on your Deck
   (e.g. `~/Downloads`).
2. **Mods** tab → **Install from file** → paste the absolute path → **Install**.
3. Toggle on.

## Enabling / disabling

Toggle the switch on a mod's row. Internally:
- **Enable**: every file in the mod's library payload gets symlinked
  into the game install. Any vanilla file it would overwrite is moved
  to a per-mod backup first.
- **Disable**: symlinks removed, vanilla files restored from backup.

Both operations are instant and reversible. Save a file mid-game, toggle
a mod, no issue.

## Uninstalling

Mod row → **Uninstall**. If the mod was enabled, it's disabled first.
Library payload and backup dir are deleted. Free Nexus downloads remain
cached at `~/.local/share/decky-mod-manager/cache/` — clear by hand if
you're tight on space.

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
├── cache/                           # downloaded Nexus archives
└── tools/                           # third-party tools (Script Merger etc.)
```

The library is independent of the game install. If Steam reinstalls
the game, your mods are still here — just re-enable them.
