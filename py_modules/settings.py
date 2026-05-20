"""Simple JSON-backed settings persistence (Nexus API key, user prefs)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DEFAULTS: dict[str, Any] = {
    "nexus_api_key": "",
}


class Settings:
    def __init__(self, path: Path):
        self.path = path
        self._data: dict[str, Any] = dict(_DEFAULTS)
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            on_disk = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        if isinstance(on_disk, dict):
            self._data.update({k: on_disk[k] for k in on_disk if k in _DEFAULTS})

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._data, indent=2))
        tmp.replace(self.path)

    def get(self, key: str) -> Any:
        return self._data.get(key, _DEFAULTS.get(key))

    def set(self, key: str, value: Any) -> None:
        if key not in _DEFAULTS:
            raise KeyError(f"unknown setting: {key}")
        self._data[key] = value
        self._save()

    def as_dict_redacted(self) -> dict:
        """Returns settings safe to send to the frontend (api key truncated)."""
        out = dict(self._data)
        key = out.get("nexus_api_key") or ""
        if key:
            out["nexus_api_key"] = key[:4] + "•" * 8 + key[-4:]
            out["nexus_api_key_set"] = True
        else:
            out["nexus_api_key_set"] = False
        return out
