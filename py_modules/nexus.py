"""Nexus Mods client.

Three things this talks to:

1. ``https://search.nexusmods.com/mods`` — undocumented but stable JSON search
   used by Nexus's own site for autocomplete. No auth required.
2. ``https://api.nexusmods.com/v1/...`` — official v1 REST API for mod info,
   file lists, and download links. Requires the user's personal API key
   (Authorization: ``apikey: <key>`` header).
3. ``https://www.nexusmods.com/games`` — a static JSON listing of all games
   with their numeric ID and ``domain_name``. Cached on first use.

Free Nexus accounts can only obtain download links via the v1 API by passing
a one-time ``key``/``expires`` pair issued in an NXM link clicked in the
browser. Premium accounts can request a link directly. We support both:
``download_link()`` takes optional NXM credentials.
"""

from __future__ import annotations

import asyncio
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

USER_AGENT = "decky-mod-manager/0.1 (+https://github.com/local)"
V1_BASE = "https://api.nexusmods.com/v1"
V2_GRAPHQL_URL = "https://api.nexusmods.com/v2/graphql"
GAMES_INDEX_URL = f"{V1_BASE}/games.json"

# Nexus retired the undocumented ``search.nexusmods.com/mods`` endpoint
# (Cloudflare authoritatively returns NXDOMAIN). The replacement is the v2
# GraphQL API at ``api.nexusmods.com/v2/graphql``; the ``mods`` query takes
# a ``nameStemmed`` filter that gives stemmed/fuzzy matching against the
# mod name. Verified live against the deck.
_SEARCH_GQL = """
query SearchMods($q: String!, $domain: String!, $count: Int!) {
  mods(
    filter: {
      gameDomainName: { value: $domain, op: EQUALS }
      nameStemmed: { value: $q, op: MATCHES }
    }
    sort: { downloads: { direction: DESC } }
    count: $count
  ) {
    nodes {
      modId
      name
      uploader { name }
      downloads
      endorsements
      pictureUrl
      adultContent
    }
  }
}
"""


def _build_ssl_context() -> ssl.SSLContext:
    """Build an SSLContext that can actually verify Nexus's certificate.

    Decky's bundled Python (PyInstaller-frozen loader) doesn't pick up the
    system CA bundle through ``ssl.create_default_context()`` — the default
    context comes up with an empty CA store, so every HTTPS request fails
    with ``CERTIFICATE_VERIFY_FAILED``. We hit this in production on the
    Deck: Nexus search silently rendered "No results." because the frontend
    swallowed the exception.

    Lookup order:
    1. ``SSL_CERT_FILE`` env var (user override)
    2. Common Linux distro paths — SteamOS uses
       ``/etc/ssl/certs/ca-certificates.crt`` (symlink into
       ``/etc/ca-certificates/extracted/tls-ca-bundle.pem``)
    3. ``certifi`` if installed
    4. Default context (will fail in Decky's sandbox, but at least the
       error message will be informative)
    """
    ctx = ssl.create_default_context()
    cafile = os.environ.get("SSL_CERT_FILE")
    if not cafile or not os.path.exists(cafile):
        for candidate in (
            "/etc/ssl/certs/ca-certificates.crt",  # SteamOS, Debian, Ubuntu, Arch
            "/etc/pki/tls/certs/ca-bundle.crt",     # RHEL, Fedora, CentOS
            "/etc/ssl/cert.pem",                    # macOS, Alpine, *BSD
            "/etc/ca-certificates/extracted/tls-ca-bundle.pem",  # SteamOS direct
        ):
            if os.path.exists(candidate):
                cafile = candidate
                break
        else:
            cafile = None
    if cafile:
        ctx.load_verify_locations(cafile=cafile)
        return ctx
    try:
        import certifi  # type: ignore
        ctx.load_verify_locations(cafile=certifi.where())
    except ImportError:
        pass
    return ctx


_SSL_CONTEXT = _build_ssl_context()


# Appid → Nexus domain. Seeded with the ones we explicitly support; extended
# at runtime by matching the game's name against the Nexus games index.
APPID_TO_NEXUS_DOMAIN: dict[str, str] = {
    "292030": "witcher3",       # The Witcher 3
    "489830": "skyrimspecialedition",
    "377160": "fallout4",
    "1086940": "baldursgate3",
    "1091500": "cyberpunk2077",
    "22380": "newvegas",        # Fallout: New Vegas
    "72850": "skyrim",
    "611670": "kingdomcomedeliverance",
    "1245620": "eldenring",
    "1817070": "marvelsspiderman",
    "1888160": "starfield",
}


class NexusError(RuntimeError):
    pass


@dataclass
class NexusSearchHit:
    mod_id: int
    name: str
    author: str
    downloads: int
    endorsements: int
    image: str | None

    def to_dict(self) -> dict:
        return {
            "mod_id": self.mod_id,
            "name": self.name,
            "author": self.author,
            "downloads": self.downloads,
            "endorsements": self.endorsements,
            "image": self.image,
        }


@dataclass
class NexusModFile:
    file_id: int
    name: str
    version: str
    size_kb: int
    category: str
    is_primary: bool

    def to_dict(self) -> dict:
        return {
            "file_id": self.file_id,
            "name": self.name,
            "version": self.version,
            "size_kb": self.size_kb,
            "category": self.category,
            "is_primary": self.is_primary,
        }


# ----------------------------------------------------------------- transport


def _request(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(req, context=_SSL_CONTEXT, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        raise NexusError(f"HTTP {e.code} for {url}: {body}") from e
    except urllib.error.URLError as e:
        raise NexusError(f"network error for {url}: {e.reason}") from e


def _request_json(url: str, *, headers: dict[str, str] | None = None) -> Any:
    raw = _request(url, headers=headers)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise NexusError(f"bad JSON from {url}") from e


# --------------------------------------------------------------- games index


class _GamesIndex:
    """Caches the Nexus games list so we can map names → domain."""

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = cache_dir / "nexus_games.json"
        self._index: dict[str, dict] | None = None  # domain_name -> entry

    def _load_cached(self) -> dict[str, dict] | None:
        if not self.cache_file.exists():
            return None
        if time.time() - self.cache_file.stat().st_mtime > 7 * 86400:
            return None
        try:
            return {g["domain_name"]: g for g in json.loads(self.cache_file.read_text())}
        except (json.JSONDecodeError, OSError, KeyError):
            return None

    def _fetch(self, api_key: str) -> dict[str, dict]:
        data = _request_json(GAMES_INDEX_URL, headers={"apikey": api_key})
        if not isinstance(data, list):
            raise NexusError("unexpected games index payload")
        try:
            self.cache_file.write_text(json.dumps(data))
        except OSError:
            pass
        return {g["domain_name"]: g for g in data}

    def get(self, api_key: str) -> dict[str, dict]:
        if self._index is None:
            self._index = self._load_cached() or self._fetch(api_key)
        return self._index

    def domain_for_name(self, api_key: str, name: str) -> str | None:
        idx = self.get(api_key)
        norm = _normalize_name(name)
        for entry in idx.values():
            if _normalize_name(entry.get("name", "")) == norm:
                return entry["domain_name"]
        # Looser contains-match as a fallback
        for entry in idx.values():
            if norm and norm in _normalize_name(entry.get("name", "")):
                return entry["domain_name"]
        return None


def _normalize_name(s: str) -> str:
    return "".join(c for c in s.lower() if c.isalnum())


# ------------------------------------------------------------- public client


class NexusClient:
    def __init__(self, cache_dir: Path):
        self._games = _GamesIndex(cache_dir)

    # ---- domain resolution ---------------------------------------------

    def resolve_domain(self, appid: str, game_name: str, api_key: str | None) -> str | None:
        if str(appid) in APPID_TO_NEXUS_DOMAIN:
            return APPID_TO_NEXUS_DOMAIN[str(appid)]
        if api_key:
            try:
                return self._games.domain_for_name(api_key, game_name)
            except NexusError:
                return None
        return None

    # ---- search (no API key required) ----------------------------------

    async def search(self, domain: str, query: str, *, api_key: str | None = None) -> list[NexusSearchHit]:
        # GraphQL v2 — see _SEARCH_GQL comment for why we left the legacy
        # search.nexusmods.com endpoint behind. ``api_key`` not required:
        # the mods query is publicly readable.
        body = json.dumps({
            "query": _SEARCH_GQL,
            "variables": {"q": query, "domain": domain, "count": 20},
        }).encode("utf-8")

        def _post() -> dict:
            req = urllib.request.Request(
                V2_GRAPHQL_URL,
                data=body,
                headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
            )
            try:
                with urllib.request.urlopen(req, context=_SSL_CONTEXT, timeout=20) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="replace")[:300]
                raise NexusError(f"HTTP {e.code} from Nexus GraphQL: {err_body}") from e
            except urllib.error.URLError as e:
                raise NexusError(f"network error reaching Nexus GraphQL: {e.reason}") from e

        data = await asyncio.to_thread(_post)
        if data.get("errors"):
            raise NexusError(f"GraphQL error: {data['errors'][0].get('message', data['errors'])}")
        nodes = (((data.get("data") or {}).get("mods") or {}).get("nodes")) or []
        out: list[NexusSearchHit] = []
        for r in nodes:
            try:
                out.append(NexusSearchHit(
                    mod_id=int(r["modId"]),
                    name=str(r.get("name") or ""),
                    author=str(((r.get("uploader") or {}).get("name")) or ""),
                    downloads=int(r.get("downloads") or 0),
                    endorsements=int(r.get("endorsements") or 0),
                    image=r.get("pictureUrl"),
                ))
            except (KeyError, TypeError, ValueError):
                continue
        return out

    async def trending(self, domain: str, api_key: str) -> list[dict]:
        url = f"{V1_BASE}/games/{domain}/mods/trending.json"
        data = await asyncio.to_thread(_request_json, url, headers={"apikey": api_key})
        return data if isinstance(data, list) else []

    async def latest_added(self, domain: str, api_key: str) -> list[dict]:
        url = f"{V1_BASE}/games/{domain}/mods/latest_added.json"
        data = await asyncio.to_thread(_request_json, url, headers={"apikey": api_key})
        return data if isinstance(data, list) else []

    # ---- mod / file info (API key required) ----------------------------

    async def mod_info(self, domain: str, mod_id: int, api_key: str) -> dict:
        url = f"{V1_BASE}/games/{domain}/mods/{mod_id}.json"
        return await asyncio.to_thread(_request_json, url, headers={"apikey": api_key})

    async def mod_files(self, domain: str, mod_id: int, api_key: str) -> list[NexusModFile]:
        url = f"{V1_BASE}/games/{domain}/mods/{mod_id}/files.json"
        data = await asyncio.to_thread(_request_json, url, headers={"apikey": api_key})
        files = data.get("files") if isinstance(data, dict) else []
        out: list[NexusModFile] = []
        for f in files or []:
            try:
                out.append(NexusModFile(
                    file_id=int(f["file_id"]),
                    name=str(f.get("name") or ""),
                    version=str(f.get("version") or ""),
                    size_kb=int(f.get("size_kb") or f.get("size") or 0),
                    category=str(f.get("category_name") or ""),
                    is_primary=bool(f.get("is_primary")),
                ))
            except (KeyError, TypeError, ValueError):
                continue
        return out

    async def download_link(
        self,
        domain: str,
        mod_id: int,
        file_id: int,
        api_key: str,
        *,
        nxm_key: str | None = None,
        nxm_expires: int | None = None,
    ) -> str:
        """Return a direct CDN URL for a mod file.

        Premium users get a link with no extra params. Free users must supply
        the ``key`` / ``expires`` pair from a clicked NXM://... link.
        """
        params: dict[str, str] = {}
        if nxm_key:
            params["key"] = nxm_key
        if nxm_expires:
            params["expires"] = str(nxm_expires)
        qs = ("?" + urllib.parse.urlencode(params)) if params else ""
        url = f"{V1_BASE}/games/{domain}/mods/{mod_id}/files/{file_id}/download_link.json{qs}"
        data = await asyncio.to_thread(_request_json, url, headers={"apikey": api_key})
        if not isinstance(data, list) or not data:
            raise NexusError("no download link returned")
        link = data[0].get("URI")
        if not link:
            raise NexusError("download link missing URI")
        return link

    # ---- raw file download ---------------------------------------------

    async def download_to(self, url: str, dest: Path) -> Path:
        def _do() -> Path:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            dest.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(req, context=_SSL_CONTEXT, timeout=120) as resp, dest.open("wb") as fh:
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    fh.write(chunk)
            return dest
        return await asyncio.to_thread(_do)

    # ---- internals -----------------------------------------------------

    async def _domain_to_numeric_id(self, domain: str, api_key: str | None) -> int | None:
        if not api_key:
            return None
        def _do() -> int | None:
            idx = self._games.get(api_key)
            entry = idx.get(domain)
            if entry and "id" in entry:
                try:
                    return int(entry["id"])
                except (TypeError, ValueError):
                    return None
            return None
        return await asyncio.to_thread(_do)
