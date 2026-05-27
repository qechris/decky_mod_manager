# Security Policy

## Reporting a vulnerability

**Don't open a public issue for security bugs.** Email the maintainer
privately or use GitHub's [private vulnerability reporting](https://github.com/qa-chrisb/decky_mod_manager/security/advisories/new)
form.

Please include:
- Decky Loader version
- Mod Manager version (from `plugin.json` `"version"`)
- A reproduction (steps + the affected mod / archive / setting, if any)
- The impact you're claiming (RCE? File overwrite outside game dir? API
  key leak?)

We'll acknowledge within 7 days and aim to ship a fix within 30 days for
anything actually exploitable.

## Threat model (what we worry about)

This is a Decky plugin running with **the user's privileges** (Linux user
`deck` on SteamOS). It does not run as root and does not request elevation.
The plugin can:
- Read/write under `~/.local/share/decky-mod-manager/` (its own data dir)
- Read/write under `<game install path>/` (e.g. `~/.steam/steam/steamapps/common/The Witcher 3/`)
- Read/write under the game's Proton prefix `Documents/` (for `mods.settings`)
- Make outbound HTTPS to `api.nexusmods.com` and `staticdelivery.nexusmods.com`

In-scope concerns we take seriously:
- **Path traversal via archive extraction.** Malicious mod archives that
  try to write outside the target directory (Zip Slip / TarSlip). We use
  Python's `zipfile`/`tarfile` (which mitigate this in 3.12+) and shell
  out to `7z`/`unrar` (which extract within `-o<dest>`).
- **API key handling.** The Nexus API key is stored under the data dir
  in `settings.json`. Sent as a header to `api.nexusmods.com` only.
- **SSL cert verification.** Never disabled; we explicitly construct an
  `SSLContext` against the system CA bundle.
- **Symlink target validation.** We symlink archive contents into the
  game install. A malicious archive could include relative paths that
  escape the install. We rely on archive-extraction tools to refuse
  these, but symlink-creation is a defense-in-depth gap we'd like to
  close.

Out of scope:
- The user's Nexus credentials beyond the API key (the plugin never sees
  the password)
- Anything that requires the attacker to already have shell access to
  the Deck
- Mods themselves being malicious (the user voluntarily installs them;
  we just put the files in place)

## Supported versions

Whichever versions are tagged in [Releases](https://github.com/qa-chrisb/decky_mod_manager/releases),
plus the current `main`. There's no LTS branch.
