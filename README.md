# Mod Manager

A [Decky Loader](https://decky.xyz) plugin for installing and managing game
mods on Steam Deck — directly from Game Mode, controller-only, no desktop
detour.

> ⚠️ **Status: early.** Working for the maintainer's own use on a Deck
> (SteamOS 3.x, Decky Loader 3.2+). Hasn't been through the Decky plugin
> store review. Expect rough edges and please [open issues](https://github.com/qa-chrisb/decky_mod_manager/issues).

## Highlights

- 🎮 **Browse Nexus from the QAM.** Search, download, and install mods
  without leaving Game Mode. Bring your own [Nexus API key](https://www.nexusmods.com/users/myaccount?tab=api).
- 🔌 **First-class handlers for Witcher 3 and Kingdom Come: Deliverance**
  (both KCD1 and KCD2). Layout normalization, `mods.settings` / `mod_order.txt`
  management, and game-specific tools.
- 🪄 **Native Linux script merger for Witcher 3.** Resolves `.ws` and
  `input.xml` conflicts via GNU `diff3` with auto-resolution by mod
  priority. No Windows Script Merger / Proton round-trip required.
- 🛟 **Symlink-based enable/disable.** Toggling a mod is instant and
  reversible. Vanilla files are backed up before being overwritten.
- 🧰 **Generic file-mirror handler** for any game we don't have a custom
  handler for — install whatever, toggle whenever.

## Documentation

| Audience | Where to look |
|---|---|
| **End users** — install + usage + per-game guides | [Docs site](https://qa-chrisb.github.io/decky_mod_manager/) (Jekyll, also under [`docs/`](docs/)) |
| **Contributors** — dev setup, testing, PRs | [CONTRIBUTING.md](CONTRIBUTING.md) |
| **Reporting a vulnerability** | [SECURITY.md](SECURITY.md) |
| **Community norms** | [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) |

## Quick install (end users)

1. Install [Decky Loader](https://decky.xyz) on your Steam Deck if you haven't.
2. Download the latest plugin archive from [Releases](https://github.com/qa-chrisb/decky_mod_manager/releases) (when available).
3. Open Decky → ⚙ Settings → Plugins → Install from URL/Zip.
4. Open the QAM → puzzle-piece (Decky) → **Mod Manager**.

For now, until releases ship: clone this repo, run `pnpm install && pnpm run build`,
and copy the resulting directory into `~/homebrew/plugins/Mod Manager/`. See
the [docs site](https://qa-chrisb.github.io/decky_mod_manager/install.html)
for the full step-by-step.

## Supported games

| Game | App ID | Handler | Notes |
|---|---|---|---|
| The Witcher 3: Wild Hunt | 292030 | `witcher3` | Native script + settings merger, optional Proton GUI Script Merger fallback |
| Kingdom Come: Deliverance | 379430 | `kingdom_come` | `mod_order.txt` whitelist/order management |
| Kingdom Come: Deliverance II | 1771300 | `kingdom_come` | Same layout as KCD1 |
| Everything else | – | `generic` | File-mirror via symlinks; toggle on/off |

Want first-class support for another game? [Open a feature request](https://github.com/qa-chrisb/decky_mod_manager/issues/new?template=feature.yml).

## On-disk layout

```
~/.local/share/decky-mod-manager/
├── state.json                       # installed mods, enabled state, file lists
├── settings.json                    # Nexus API key (file-mode 0600 recommended)
├── library/<game_id>/<mod_id>/      # extracted mod payloads
├── backups/<game_id>/<mod_id>/      # vanilla files displaced by a mod
└── baselines/<game_id>/<rel>        # snapshot before settings-merger writes
```

Mods are applied to the game by symlinking each file from `library/` into
the game install. Toggling is just unlinking and re-linking.

## License

[BSD 3-Clause](LICENSE) — short, permissive, and matches the BSD-3 of
[`apocalyptech/w3scriptmerge`](https://github.com/apocalyptech/w3scriptmerge),
which inspired the native script merger.

## Credits & prior art

- [Decky Loader](https://decky.xyz) team — the runtime that makes this plugin possible.
- [`apocalyptech/w3scriptmerge`](https://github.com/apocalyptech/w3scriptmerge)
  for the `diff3`-based script merging approach.
- [sinitar's Witcher 3 Modding Guide](https://www.sinitargaming.com/tw3.html)
  and [Nexus Modding Guide for KCD](https://wiki.nexusmods.com/index.php/Modding_guide_for_KCD)
  for documenting the conventions our handlers implement.
- Every Nexus mod author whose work this plugin makes a tiny bit easier to install.
