# Contributing

Thanks for considering a contribution. This project is a small Decky
plugin maintained by one person, so the workflow is deliberately simple.

## Quick start (dev loop)

Prereqs:
- macOS or Linux dev machine with `pnpm`, `python3`, `rsync`, `ssh`
- Steam Deck with [Decky Loader](https://decky.xyz) installed and SSH enabled
- (Optional) `fswatch` for auto-deploy on save: `brew install fswatch`

```bash
git clone https://github.com/qa-chrisb/decky_mod_manager.git
cd decky_mod_manager
pnpm install

# One-time Deck setup
cp scripts/.deploy-env.example scripts/.deploy-env
$EDITOR scripts/.deploy-env       # set DECK_HOST etc
./scripts/setup-deck.sh           # creates the symlink-to-home layout, deploys, restarts loader

# Tight dev loop (rebuilds + redeploys on every save)
./scripts/dev.sh

# Or do it manually
./scripts/deploy.sh               # one-shot: build + push + reload backend
./scripts/deploy.sh --no-build    # frontend hasn't changed
./scripts/deploy.sh --no-reload   # land files but don't bump the plugin
```

See [`scripts/deploy.sh`](scripts/deploy.sh) and [`scripts/setup-deck.sh`](scripts/setup-deck.sh)
for what they actually do — both are well-commented and worth reading
once before you trust them with your Deck.

### Why the symlink-to-home layout?

Decky's plugin loader runs as root and re-chowns its plugin directories on
load. Rsync'ing directly into `~/homebrew/plugins/` loses deck-ownership
after each Decky reload, breaking sudoless deploys. `setup-deck.sh` puts
the actual files under `/home/deck/decky-plugins/mod_manager/` (fully
deck-owned, rsync-writable forever) and symlinks them into
`~/homebrew/plugins/`. The chown lands on the symlink, leaving the real
files alone. See the script header for the order-of-ops gotcha.

## Tests

```bash
python3 -m unittest discover -s tests
```

We use the stdlib `unittest` because Decky's plugin Python is a
PyInstaller-frozen runtime with no third-party packages. Sticking to the
stdlib avoids "works on my machine, fails on the Deck."

Frontend type-check (no runtime tests — the UI is exercised by CDP in
manual smoke tests):
```bash
node_modules/.bin/tsc --noEmit
pnpm run build
```

### Writing tests

- Per-handler tests go in `tests/test_<game>.py`. See `tests/test_witcher3_layout.py`
  for the pattern: build a synthetic install in a `TemporaryDirectory`,
  exercise the handler, assert on the resulting layout/state.
- Tests must pass on **both** macOS dev hosts and the Deck. Avoid Linux-only
  shell tools without an `@unittest.skipUnless(shutil.which("...")` guard.
- New on-disk schemas need a backward-compat test (extra fields tolerated,
  missing fields defaulted). See `tests/test_state_load.py`.

## Pull requests

- Branch from `main`, name like `fix-w3-mods-settings-path` or `feat-kcd-support`.
- One commit per logical change is ideal but not required — we don't
  squash-merge, so each commit ends up in history. Write commit messages
  that explain *why*, not just *what*.
- Run tests and `tsc` before pushing. CI runs both on every PR.
- Open a PR against `main`. CI must be green before merge.

## Code style

- **Python**: stdlib only. `from __future__ import annotations` everywhere
  for forward-compat type hints. Type-hint public functions.
- **TypeScript**: strict mode, no `any` except for talking to untyped
  Decky-UI props (cast inline with a comment).
- **No comments restating *what* code does** — readers can see that.
  Save comments for *why* (subtle invariants, workarounds for specific
  bugs, behavior that would surprise a reader).
- **Match existing patterns.** If a handler does layout normalization a
  certain way, the new one should too. Consistency > clever.

## Adding a new game handler

1. Create `py_modules/handlers/<game>.py` subclassing `BaseHandler`
   (or `GenericHandler` if plain file mirroring is enough). Set
   `games = {"<steam appid>": "<nexus domain>"}` and override
   `post_install_payload`, `enable`, `disable` as needed. Look at
   `witcher3.py` and `kingdom_come.py` for templates.
2. Add the class to `HANDLERS` in `py_modules/handlers/__init__.py`.
3. Add `tests/test_<game>.py` covering the 4 common archive shapes
   (already-wrapped, single-mod-folder, bare contents, vortex-wrapper),
   plus any game-specific load-order or settings file management.
4. Update the supported-games table in `README.md`.
5. (Optional) Add a per-game page under `docs/games/<game>.md`.

## Bug reports

Use the [bug template](.github/ISSUE_TEMPLATE/bug.yml) — it asks for
the journalctl excerpt, which is the most useful single piece of info
in 9 out of 10 reports.
