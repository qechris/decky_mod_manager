---
title: Home
layout: default
nav_order: 1
---

# Mod Manager for Steam Deck

A [Decky Loader](https://decky.xyz) plugin for installing and managing
game mods on Steam Deck — directly from Game Mode, controller-only.

[Install]({% link install.md %}){: .btn .btn-primary }
[Browse usage]({% link usage.md %}){: .btn }
[Source on GitHub](https://github.com/qa-chrisb/decky_mod_manager){: .btn }

---

## At a glance

- 🎮 **Browse Nexus from the QAM** — search, download, install. No desktop mode.
- 🔌 **First-class support for Witcher 3 and Kingdom Come: Deliverance** (1 and 2).
- 🪄 **Native Linux script merger for Witcher 3** — diff3-based, auto-resolves conflicts by mod priority. No Windows Script Merger needed.
- 🛟 **Symlink-based on/off** — toggling is instant, vanilla files backed up before overwrite.
- 🧰 **Generic file-mirror handler** for everything else — install whatever, toggle whenever.

## What's here

| Page | What's covered |
|---|---|
| [Install]({% link install.md %}) | Getting the plugin onto your Deck |
| [Usage]({% link usage.md %}) | Browsing, installing, enabling, merging |
| [Troubleshooting]({% link troubleshooting.md %}) | "My mod isn't loading" and other common knots |
| [FAQ]({% link faq.md %}) | Quick answers |
| [The Witcher 3]({% link games/witcher3.md %}) | W3-specific workflow + script/settings merger |
| [Kingdom Come: Deliverance]({% link games/kingdom_come.md %}) | KCD/KCD2 workflow + mod_order.txt |

## Status

Early but working. Used by the maintainer on a Steam Deck OLED running
SteamOS 3.x with Decky Loader 3.2+. The Decky plugin store hasn't
reviewed it yet — install from GitHub for now.

If something doesn't work, please [file an issue](https://github.com/qa-chrisb/decky_mod_manager/issues/new?template=bug.yml).
