---
title: The Witcher 3
layout: default
parent: Games
nav_order: 1
---

# The Witcher 3: Wild Hunt

App ID `292030`. Handler: `witcher3`.

## Where the plugin puts things

| What | Where |
|---|---|
| Mod folders | `<install>/Mods/<modname>/content/...` |
| DLC mods | `<install>/DLC/<dlcname>/content/...` |
| `mods.settings` (load order / enable list) | `<Proton prefix>/drive_c/users/steamuser/Documents/The Witcher 3/mods.settings` |
| Optional `bin/config/r4game/user_config_matrix/pc/input.xml` | Same path under `<install>/` |

The full Proton-prefix path on a typical Deck:
```
~/.steam/steam/steamapps/compatdata/292030/pfx/drive_c/users/steamuser/Documents/The Witcher 3/mods.settings
```

The **Tools → Diagnostics** panel shows the exact path our handler
resolved — useful for confirming we're writing where the game reads.

## Layout normalization

When you install a W3 mod, the plugin normalizes whatever shape the
archive ships in to the canonical `Mods/modX/content/...` layout. The
4 common archive shapes:

| Archive | Becomes |
|---|---|
| `Mods/modFoo/content/...` (already wrapped) | unchanged |
| `modFoo/content/...` (single mod folder) | wrapped in `Mods/` |
| `Foo/content/...` (no `mod` prefix) | renamed to `Mods/modFoo/` |
| Bare `content/scripts/...` | wrapped as `Mods/mod<uuid>/content/scripts/...` |

The `mod` prefix on the folder name matters — REDengine silently
ignores any folder under `Mods/` that doesn't start with `mod`.

## Native script merger

`.ws` files (Witcher Script — text-format scripts) frequently conflict
when multiple mods edit the same vanilla file. The merger:

1. Reads each enabled mod's `.ws` files
2. Diffs against the vanilla copy from `content/content0/scripts/`
3. Runs `diff3 -m` to produce a 3-way merge per file
4. **Auto-resolves conflicts** by picking the higher-priority mod's
   side (per `mods.settings` `Priority`)
5. Writes merged output to `<install>/Mods/mod0000_DeckyMerged/`

The `mod0000_` prefix makes it sort first alphabetically — REDengine
loads mods in order, so our merged version takes precedence over the
individual mods' raw `.ws` files.

Run it from **Tools → Merge scripts**. The result row shows merged
file count + any conflicts that were auto-resolved (with the list of
which files conflicted).

## Native settings merger

For `bin/config/r4game/user_config_matrix/pc/input.xml` and
`userConfigDef.xml` — also `diff3`-based, but writes directly to the
install path (not a separate mod folder, because the engine reads
these from fixed paths).

Uses a **baseline** snapshot pattern: the first time you run the
merger, vanilla gets snapshotted to
`~/.local/share/decky-mod-manager/baselines/292030/<path>`. Future
merges always 3-way-merge against that snapshot, so re-running doesn't
balloon the file with duplicate entries.

## Proton-side Script Merger (optional)

The original Windows
[Script Merger](https://www.nexusmods.com/witcher3/mods/484) runs fine
under Proton. The Tools tab has buttons to download + launch it. Use this
if you want the manual GUI conflict-resolution UI.

If both Proton merger and native merger are run, they produce different
output dirs (`mod0000_MergedFiles` vs `mod0000_DeckyMerged`) — keep one
or the other, not both.

## Common pitfalls

- **First mod after a clean install**: `mods.settings` doesn't exist
  until W3 has launched once. The plugin will create it, but the game
  needs the Proton prefix to exist — launch W3 from Steam at least once
  before installing mods.
- **Mods installed by older plugin versions**: pre-0.1 had a layout
  bug that produced `Mods/modFoo/content/content/...` (doubled
  `content/`). Uninstall + reinstall through the plugin to fix.
- **Mods that ship a `mod.json` or `modinfo.xml`**: not used by W3.
  Some mod packs include these for other tools; we ignore them.

## See also

- [sinitar's Modding Guide](https://www.sinitargaming.com/tw3.html) — authoritative reference
- [Script Merger on Nexus](https://www.nexusmods.com/witcher3/mods/484)
- [`apocalyptech/w3scriptmerge`](https://github.com/apocalyptech/w3scriptmerge) — the BSD-3 project that inspired our native merger
