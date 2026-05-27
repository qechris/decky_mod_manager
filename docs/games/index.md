---
title: Games
layout: default
nav_order: 6
has_children: true
---

# Per-game guides

Each supported game has its own page covering install layout,
game-specific conventions, and pitfalls.

| Game | Handler | Page |
|---|---|---|
| The Witcher 3: Wild Hunt | `witcher3` | [W3 guide]({% link games/witcher3.md %}) |
| Kingdom Come: Deliverance (1 + 2) | `kingdom_come` | [KCD guide]({% link games/kingdom_come.md %}) |

For games without a custom handler, the **generic** handler mirrors
files into the game install via symlinks. Enable/disable works, but
there's no game-specific layout normalization, load-order management,
or merger. Open a [feature request](https://github.com/qa-chrisb/decky_mod_manager/issues/new?template=feature.yml)
if you'd like first-class support for a specific game.
