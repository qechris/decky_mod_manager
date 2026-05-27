---
title: FAQ
layout: default
nav_order: 5
---

# FAQ

## Does this work without internet?

Yes for local-archive installs. No for Browse Nexus (needs
`api.nexusmods.com`).

## Will it brick my game?

Every file the plugin overwrites is backed up to
`~/.local/share/decky-mod-manager/backups/<game_id>/<mod_id>/` before
the symlink replaces it. Disabling restores from there.

If you suspect a botched state, delete the mod's library + backup dirs
and use Steam → game → Properties → Installed Files → Verify integrity
to restore the game files.

## Where's the Nexus password stored?

Nowhere. The plugin only ever sees your personal API key — a long
random string from Nexus's site — stored in
`~/.local/share/decky-mod-manager/settings.json`. The plugin runs as
your user, so the file is protected by normal Linux file permissions.

## Will it support [game]?

The **generic** handler already mirrors files into the game install
for any game — toggle on/off works for anything. For first-class
support (layout normalization, load-order management, native merger),
open a [feature request](https://github.com/qa-chrisb/decky_mod_manager/issues/new?template=feature.yml)
with the game's mod conventions.
