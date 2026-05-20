"""Witcher 3 Script Merger detection / install / launch.

Script Merger is a third-party Windows .NET app (Nexus mod 484 in the
``witcher3`` domain). It diffs ``.ws`` files from multiple mods and produces
a "mod0000_MergedFiles" mod that resolves conflicts.

We support three actions:

* ``status``  — return where (if anywhere) Script Merger is installed and
                whether Proton can be located to launch it.
* ``install`` — download the latest Script Merger archive from Nexus into
                ``data_dir/tools/script-merger`` and extract it.
* ``launch``  — run ``WitcherScriptMerger.exe`` under Proton, with the
                game install path set as the working dir.

Launching requires Wine/Proton. We look for the user's Proton install via
Steam's ``compatibilitytools.d`` and the bundled Proton versions under
``steamapps/common``. If none are found we return enough info for the UI to
explain what's missing.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path

from nexus import NexusClient, NexusError

SCRIPT_MERGER_NEXUS_MOD_ID = 484  # https://www.nexusmods.com/witcher3/mods/484
DATA_DIR = Path.home() / ".local" / "share" / "decky-mod-manager"
TOOL_DIR = DATA_DIR / "tools" / "script-merger"
SCRIPT_MERGER_EXE = "WitcherScriptMerger.exe"


def _find_existing_merger(game_install: Path) -> Path | None:
    """Look in the canonical spots a user might've installed Script Merger."""
    candidates = [
        TOOL_DIR,
        game_install.parent / "Script Merger",
        game_install / "Script Merger",
        Path.home() / "Apps" / "Script Merger",
    ]
    for base in candidates:
        exe = base / SCRIPT_MERGER_EXE
        if exe.exists():
            return exe
    return None


def _find_proton() -> Path | None:
    """Locate any Proton install on this system. Returns the ``proton`` script."""
    steam = Path.home() / ".steam" / "steam"
    if not steam.exists():
        steam = Path.home() / ".local" / "share" / "Steam"
    search_roots = [
        steam / "compatibilitytools.d",
        steam / "steamapps" / "common",
    ]
    candidates: list[Path] = []
    for root in search_roots:
        if not root.is_dir():
            continue
        for child in root.iterdir():
            if not child.is_dir():
                continue
            proton = child / "proton"
            if proton.exists() and os.access(proton, os.X_OK):
                candidates.append(proton)
    if not candidates:
        return None
    # Prefer GE-Proton if present; otherwise the lexicographically newest.
    candidates.sort(key=lambda p: ("GE-Proton" not in p.parent.name, p.parent.name), reverse=True)
    return candidates[0]


async def script_merger_action(
    action: str,
    game_install: Path,
    *,
    api_key: str | None = None,
) -> dict:
    if action == "status":
        return _status(game_install)
    if action == "install":
        if not api_key:
            raise NexusError("Set your Nexus API key in Settings to install Script Merger.")
        return await _install(api_key)
    if action == "launch":
        return await _launch(game_install)
    raise ValueError(f"unknown script_merger action: {action}")


def _status(game_install: Path) -> dict:
    exe = _find_existing_merger(game_install)
    proton = _find_proton()
    return {
        "installed": exe is not None,
        "exe_path": str(exe) if exe else None,
        "proton_path": str(proton) if proton else None,
        "data_dir": str(TOOL_DIR),
    }


async def _install(api_key: str) -> dict:
    nx = NexusClient(DATA_DIR / "cache")
    files = await nx.mod_files("witcher3", SCRIPT_MERGER_NEXUS_MOD_ID, api_key)
    primary = next((f for f in files if f.is_primary), None) or (files[0] if files else None)
    if primary is None:
        raise NexusError("Script Merger has no downloadable files on Nexus.")
    link = await nx.download_link("witcher3", SCRIPT_MERGER_NEXUS_MOD_ID, primary.file_id, api_key)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    archive = DATA_DIR / "cache" / f"script-merger-{primary.file_id}{Path(primary.name).suffix or '.zip'}"
    await nx.download_to(link, archive)

    # Extract into the canonical tool dir.
    if TOOL_DIR.exists():
        shutil.rmtree(TOOL_DIR)
    TOOL_DIR.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(_extract_into, archive, TOOL_DIR)

    # The archive often has a single top-level dir; flatten it.
    entries = [p for p in TOOL_DIR.iterdir() if not p.name.startswith(".")]
    if len(entries) == 1 and entries[0].is_dir():
        inner = entries[0]
        for child in list(inner.iterdir()):
            shutil.move(str(child), str(TOOL_DIR / child.name))
        inner.rmdir()

    exe = TOOL_DIR / SCRIPT_MERGER_EXE
    if not exe.exists():
        # Sometimes nested another level
        for p in TOOL_DIR.rglob(SCRIPT_MERGER_EXE):
            exe = p
            break
    return {
        "installed": exe.exists(),
        "exe_path": str(exe) if exe.exists() else None,
    }


def _extract_into(archive: Path, dest: Path) -> None:
    import tarfile
    import zipfile

    name = archive.name.lower()
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest)
    elif name.endswith((".tar.gz", ".tgz", ".tar")):
        with tarfile.open(archive) as tf:
            tf.extractall(dest)
    elif name.endswith(".7z"):
        try:
            import py7zr  # type: ignore
        except ImportError as e:
            raise NexusError("7z extraction needs the 'py7zr' package") from e
        with py7zr.SevenZipFile(archive) as sz:
            sz.extractall(dest)
    else:
        raise NexusError(f"don't know how to extract {archive.name}")


async def _launch(game_install: Path) -> dict:
    exe = _find_existing_merger(game_install)
    if exe is None:
        raise NexusError("Script Merger is not installed. Install it first.")
    proton = _find_proton()
    if proton is None:
        raise NexusError(
            "No Proton install found. Install any Proton version via Steam "
            "(or GE-Proton via ProtonUp-Qt) and try again."
        )
    prefix = TOOL_DIR / "compatdata"
    prefix.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "STEAM_COMPAT_DATA_PATH": str(prefix),
        "STEAM_COMPAT_CLIENT_INSTALL_PATH": str(Path.home() / ".steam" / "steam"),
        "WINEDLLOVERRIDES": "",
    }
    # Fire-and-forget — don't block the event loop on the GUI app.
    subprocess.Popen(
        [str(proton), "run", str(exe)],
        cwd=str(exe.parent),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {"launched": True, "exe_path": str(exe), "proton_path": str(proton)}
