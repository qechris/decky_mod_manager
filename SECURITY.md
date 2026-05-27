# Security Policy

## Reporting a vulnerability

Don't open a public issue for security bugs. Use GitHub's
[private vulnerability reporting](https://github.com/qa-chrisb/decky_mod_manager/security/advisories/new)
form.

Please include:
- Decky Loader version
- Mod Manager version (from `plugin.json` `"version"`)
- A reproduction (steps + the affected mod / archive / setting)
- The impact you're claiming (RCE? File overwrite outside game dir? API key leak?)

I'll respond when I can — this is a one-person side project, not a
company with an on-call rotation.

## Threat model

This is a Decky plugin running with **the user's privileges** (Linux
user `deck` on SteamOS). It does not run as root and does not request
elevation. The plugin can:

- Read/write under `~/.local/share/decky-mod-manager/` (its own data dir)
- Read/write under `<game install path>/`
- Read/write under the game's Proton prefix `Documents/` (for `mods.settings`)
- Make outbound HTTPS to `api.nexusmods.com` and `staticdelivery.nexusmods.com`

In-scope concerns:

- **Path traversal via archive extraction** (Zip Slip / TarSlip).
  We use Python's `zipfile`/`tarfile` and shell out to `7z`/`unrar`
  with `-o<dest>`. Symlink-target validation on the resulting tree is
  a known defense-in-depth gap.
- **API key handling.** The Nexus API key is stored in
  `~/.local/share/decky-mod-manager/settings.json` and sent only as a
  header to `api.nexusmods.com`.
- **SSL cert verification.** Never disabled; we construct an
  `SSLContext` explicitly against the system CA bundle.

Out of scope:

- Mods themselves being malicious (the user voluntarily installs them;
  we just put the files in place).
- Anything requiring pre-existing shell access to the Deck.
