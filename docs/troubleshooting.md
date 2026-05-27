---
title: Troubleshooting
layout: default
nav_order: 4
---

# Troubleshooting

First step for almost any issue: grab the backend log.

```bash
ssh deck@steamdeck.local
journalctl -u plugin_loader --no-pager --since "5 minutes ago" | grep -i mod_manager
```

That shows what the Python side actually said when things went wrong.

## "No Steam games found"

- The **Filter** field has text in it — tap the clear-X.
- Steam library is at a non-standard path. The plugin looks at
  `~/.steam/steam/` and `~/.local/share/Steam/`. If you've moved Steam,
  symlink one of those to your install.

## Mod installs but doesn't show in-game

### Witcher 3

The plugin writes `mods.settings` to the Proton prefix's Documents dir
(`compatdata/292030/pfx/drive_c/users/steamuser/Documents/The Witcher 3/`).
If you've never launched W3 from Steam, that prefix doesn't exist yet —
launch W3 once, then re-toggle the mod.

To verify, open **Tools → Diagnostics** in the W3 view. It should say
*"Using Proton prefix Documents (the game reads this)."*

### Kingdom Come: Deliverance

If `Mods/mod_order.txt` exists in the game install, it acts as a
whitelist — only mods listed in it load. The plugin appends to it on
enable, but if you've hand-edited it, your line may have been removed
or commented out. Open it and check:

```bash
nano '/home/deck/.steam/steam/steamapps/common/KingdomComeDeliverance/Mods/mod_order.txt'
```

## Nexus search returns no results / "Search failed: ..."

- API key not set. **Decky home → Mod Manager → Settings → New API key**.
- Key invalid. Regenerate at
  [nexusmods.com → My Account → API Access](https://www.nexusmods.com/users/myaccount?tab=api).
- The "Search failed" red box always prints the actual backend error —
  read it before guessing.

## Native script merger reports "merged 0 files"

Expected if no enabled mod conflicts with another — the merger only
acts when 2+ mods touch the same `.ws` file. If you're sure two mods
conflict and it still says 0, confirm both are toggled on in the
**Mods** tab.

## Plugin shows up but UI is blank

Usually a Decky-side hiccup, not the plugin. Try:

1. Decky settings → Plugins → **... → Reload** on Mod Manager.
2. If that doesn't work: `sudo systemctl restart plugin_loader` from SSH.
3. Last resort: Steam → Power → Restart.

## Getting more help

- [Open a bug](https://github.com/qa-chrisb/decky_mod_manager/issues/new?template=bug.yml)
  with the backend log excerpt.
- For questions, [start a discussion](https://github.com/qa-chrisb/decky_mod_manager/discussions).
