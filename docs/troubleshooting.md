---
title: Troubleshooting
layout: default
nav_order: 4
---

# Troubleshooting

First step for almost any issue: **grab the backend log**.

```bash
ssh deck@steamdeck.local
journalctl -u plugin_loader --no-pager --since "5 minutes ago" | grep -i mod_manager
```

That'll show what the Python side actually said when things went wrong.

## "No Steam games found"

- You're filtering: the **Filter** field has text in it. Tap the clear-X.
- Steam library at a non-standard path: the plugin only looks at
  `~/.steam/steam/` and `~/.local/share/Steam/`. If you've moved Steam,
  symlink one of those to your install.
- The plugin's not loading at all — check the backend log. The
  `mod-manager: loaded` line should appear during plugin boot.

## "Mod installs but doesn't show in-game"

Most common causes:

### Witcher 3
- `mods.settings` is being written to the wrong place. Open
  **Tools → Diagnostics**. It should say *"Using Proton prefix Documents
  (the game reads this)."* If it falls back to "install Mods/", the
  Proton prefix for W3 (`compatdata/292030/pfx/`) doesn't exist. Launch
  W3 once via Steam to create it, then re-toggle the mod.
- Mod folder name doesn't start with `mod`. Our handler auto-renames
  on install — if you're hitting this for an existing install, uninstall
  and reinstall through the plugin.
- The mod was installed by an older plugin version with the
  doubled-`content/` bug. Uninstall and reinstall through the plugin.

### Kingdom Come: Deliverance
- `mod_order.txt` exists in `<install>/Mods/` and acts as a whitelist.
  Our handler appends new mods to it when present, but if you manually
  edited it after enabling, the line might've been removed. Check it.
- KCD2 expects mods in the same layout but at the KCD2 install path
  (different appid). Make sure you picked the right game in the picker.

### Anything else (generic handler)
- The mod expected a specific install path the archive didn't include.
  Check the mod's Nexus instructions — sometimes you need to manually
  place files outside the install dir.

## "7z archives require the 'py7zr' package"

You're on an older plugin version. Update to 0.1+ which falls back to
the system `7z` binary (always present on SteamOS).

## "URL can't contain control characters" on install

Old plugin version. Update — we URL-encode CDN paths now.

## Nexus search returns no results / "Search failed: ..."

- API key not set. **Decky home → Mod Manager → Settings → New API key**.
- Key invalid / expired. Regenerate at
  [nexusmods.com → My Account → API Access](https://www.nexusmods.com/users/myaccount?tab=api).
- Internet outage. Try `curl https://api.nexusmods.com/v2/graphql` from
  the Deck.
- The "Search failed" red box shows the actual error — read it. If it
  says certificate verify failed, you're on an old version (we added an
  explicit CA bundle in a recent commit).

## "Native script merger merged 0 files"

Expected when no enabled mod conflicts with another (the merger only
merges when 2+ mods touch the same `.ws` file). If you're sure two
mods conflict and it still says 0:

- Confirm both mods are **enabled** (toggle on the Mods tab).
- Look at `~/.local/share/decky-mod-manager/state.json` — both should
  have `"enabled": true`.
- Make sure the mod folders in `<install>/Mods/` aren't named with
  the doubled-`content/` bug (`Mods/modFoo/content/content/scripts/`
  — wrong; should be `Mods/modFoo/content/scripts/`). Reinstall through
  the plugin to fix.

## Plugin won't load after an update

Check the backend log. If it shows:
- `ImportError`: a Python import broke. Could be a name shadowing with
  Decky's bundled modules (we hit this with `settings.py` once —
  renamed to `mm_settings.py`).
- `TypeError: Mod.__init__() got unknown keyword argument`: your
  `state.json` has fields from an old schema. We tolerate this from
  0.1+, but if you're upgrading across that boundary, you can also
  just `rm ~/.local/share/decky-mod-manager/state.json` and reinstall
  your mods.

## Plugin shows up but UI doesn't render

Usually a Decky-side bug. Try:
1. Decky → Plugins → ... → **Reload** on Mod Manager.
2. If that doesn't work: `sudo systemctl restart plugin_loader` from SSH.
3. Last resort: Steam → Power → Restart.

## Getting more help

- [Open a bug](https://github.com/qa-chrisb/decky_mod_manager/issues/new?template=bug.yml)
  with the backend log excerpt.
- For questions, [start a discussion](https://github.com/qa-chrisb/decky_mod_manager/discussions).
