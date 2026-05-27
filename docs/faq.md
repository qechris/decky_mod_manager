---
title: FAQ
layout: default
nav_order: 5
---

# FAQ

## Does this work without internet?

Yes for local-archive installs (Install from file). No for Browse Nexus,
which needs `api.nexusmods.com`.

## Can I use it with Vortex / r2modman / Stove?

Probably, but not at the same time on the same game. Each manager
expects to own the mod folders. If you've been using another manager,
clear its installs first.

## Will it brick my game?

It shouldn't. Every file we overwrite gets backed up to
`~/.local/share/decky-mod-manager/backups/<game_id>/<mod_id>/` before
the symlink replaces it. Disabling restores from there.

If you suspect a botched state, you can manually delete a mod's library
dir (`~/.local/share/decky-mod-manager/library/<game_id>/<mod_id>/`)
and the matching backup dir, then re-verify the game's files via
Steam → game → Properties → Installed Files → Verify integrity.

## Does it work with the Steam Cloud?

The plugin's own state (`state.json`, etc.) is NOT Cloud-synced. If you
factory-reset your Deck, you'll need to reinstall mods.

The games themselves still cloud-sync per Steam's normal rules. Mods
that change save files (rare) will be cloud-synced too.

## Will it work on a regular Linux PC?

Maybe. The plugin assumes SteamOS-like paths (`~/.steam/steam/`,
Proton compatdata structure, p7zip binaries) and that Decky Loader is
running. If your distro has those, it should work. The Witcher 3 handler
specifically expects a Proton prefix for `mods.settings`, which won't
exist if you run W3 natively under Wine outside Steam.

## Will it support [game]?

The **generic** handler already mirrors files into the game install
for any game — toggle on/off works. For first-class support
(layout normalization, load-order management, native merger), open a
[feature request](https://github.com/qa-chrisb/decky_mod_manager/issues/new?template=feature.yml)
explaining the game's mod conventions and we'll consider it.

## Why not just use Vortex via Bottles?

Vortex via Bottles works but requires:
- A Wine/Bottles install (~hundreds of MB)
- Switching to Desktop mode
- A separate UI

The point of this plugin is to keep mod management inside the QAM where
you already are. For complex desktop mod loadouts, Vortex is still the
right tool.

## Where's the Nexus password stored?

Nowhere. The plugin only ever sees your personal API key (a long random
string from Nexus's site), stored in plaintext in
`~/.local/share/decky-mod-manager/settings.json`. The plugin runs as
your user, so the file's protected by Linux file permissions.

## Is the source available?

Yes — [github.com/qa-chrisb/decky_mod_manager](https://github.com/qa-chrisb/decky_mod_manager).
[BSD 3-Clause license](https://github.com/qa-chrisb/decky_mod_manager/blob/main/LICENSE).
