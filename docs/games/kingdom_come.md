---
title: Kingdom Come Deliverance
layout: default
parent: Games
nav_order: 2
---

# Kingdom Come: Deliverance (1 and 2)

App IDs `379430` (KCD1) and `1771300` (KCD2). Handler: `kingdom_come`
(shared — both games use the same mod layout).

## Where the plugin puts things

| What | Where |
|---|---|
| Mod folders | `<install>/Mods/<modname>/...` |
| Mod contents | `<install>/Mods/<modname>/Data/*.pak` (+ `Localization/`, `mod.manifest`, `mod.cfg`) |
| Load order / enable list | `<install>/Mods/mod_order.txt` |

Note that unlike Witcher 3, the enable-list lives **inside the game
install** — not in the Proton prefix Documents. Simpler.

## Layout normalization

| Archive shape | Becomes |
|---|---|
| `Mods/MyMod/Data/...` (already wrapped) | unchanged |
| `MyMod/Data/...` (single mod folder) | wrapped in `Mods/` |
| Bare `Data/`, `Localization/`, `mod.manifest` | wrapped as `Mods/mod<uuid>/` |
| `Vortex-Wrapper-Dir/MyMod/...` | wrapper hoisted away first |

KCD has no required folder-name prefix — folders can be named anything,
and the plugin preserves what the mod author chose.

## mod_order.txt semantics (load-bearing)

This file does **two** things at once:

1. **Load order** — mods are loaded top-to-bottom
2. **Whitelist** — when the file exists, ONLY mods listed in it are loaded; mods in `Mods/` not listed are ignored

Without the file, every folder under `Mods/` loads alphabetically.

### How the plugin handles it

- **On enable**: if `mod_order.txt` already exists, append the new mod's
  folder name. If it doesn't exist, leave it alone — creating one
  would silently demote any of your other unlisted mods to "not loaded".
- **On disable**: remove the matching line(s), but preserve comments
  and other entries.
- Lines starting with `#` are treated as commented-out (the mod stays
  in the file but is disabled). The plugin won't re-enable a
  commented-out mod when you re-toggle it — it adds a new uncommented
  line instead, so both remain.

### Working with mod_order.txt directly

You can edit it by hand and the plugin will respect your edits. SSH into
the Deck:
```bash
nano '/home/deck/.steam/steam/steamapps/common/KingdomComeDeliverance/Mods/mod_order.txt'
```

Reorder, comment out (`#`), or delete lines. Save. The change takes
effect the next time the game launches — no plugin reload needed.

## Common mod types

- **Data-only mods** (most common): ship `Data/*.pak`. Drop in, enable, done.
- **Localization mods**: ship `Localization/english_xml.pak` etc.
- **Script mods**: a special kind of Data mod with patched `.lua` files.
- **DLC reskins**: ship under `Data/Levels/` or similar nested paths.

The plugin handles all of these via the same enable flow — symlinks
mirror whatever the archive contained.

## Common pitfalls

- **Mod doesn't load** despite being enabled in our UI: check `mod_order.txt`.
  If it exists and your mod isn't listed (whitelist mode), add it
  manually. The plugin appends on first enable, but if the file was
  created later by something else, existing-but-not-listed mods won't load.
- **KCD2 vs KCD1**: they're separate Steam installs with separate
  `Mods/` directories. Make sure you picked the right game in the picker.
- **Mods with installers** (e.g. some script mods ship a `.bat` installer
  for Windows): the plugin can't run those. Look at the `.bat` to see
  what files it would copy and place them manually, or use a generic
  unpacker.
