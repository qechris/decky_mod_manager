"""Nexus Mods client for the v3 API (https://api.nexusmods.com/openapi.yaml).

Two gaps in v3 are filled from older APIs:

* v3 search has no text query, so name search uses the v2 GraphQL ``mods``
  query. Browsing (trending, popular, new, updated) uses v3.
* v3 resolves a Steam appid to a numeric game id but not a domain name, so
  the id is mapped to a domain through the v1 games index.

Free accounts can only download with the ``key``/``expires`` pair from an
``nxm://`` link made by the website. Premium accounts download directly.
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
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

USER_AGENT = "decky-mod-manager/0.2.0"
V3_BASE = "https://api.nexusmods.com/v3"
V2_GRAPHQL_URL = "https://api.nexusmods.com/v2/graphql"
GAMES_INDEX_URL = "https://api.nexusmods.com/v1/games.json"
# Sort -> time range. Nexus defaults trending/popular to 7 days, which is
# empty for smaller games.
BROWSE_SORTS = {"trending": "28", "popular": "all", "new": "all", "updated": "all"}
_HIDDEN_FILE_CATEGORIES = {"old_version", "removed", "archived"}

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
    nodes { modId name summary uploader { name } downloads endorsements thumbnailUrl updatedAt }
  }
}
"""


def _build_ssl_context() -> ssl.SSLContext:
    """Decky's PyInstaller-frozen Python starts with an empty CA store, so
    every HTTPS request fails unless we point it at the system bundle."""
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


class NexusError(RuntimeError):
    pass


class NexusKeyRequired(NexusError):
    pass


@dataclass
class NexusMod:
    mod_id: int
    name: str
    summary: str
    author: str
    downloads: int
    endorsements: int
    image: str | None
    updated_at: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class NexusFile:
    file_id: int
    name: str
    version: str
    category: str
    is_primary: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class NxmLink:
    domain: str
    mod_id: int
    file_id: int
    key: str | None
    expires: int | None


def parse_nxm(url: str) -> NxmLink:
    """Parse ``nxm://<domain>/mods/<mod>/files/<file>?key=..&expires=..``."""
    parts = urllib.parse.urlsplit(url.strip())
    segs = [s for s in parts.path.split("/") if s]
    if parts.scheme != "nxm" or len(segs) != 4 or segs[0] != "mods" or segs[2] != "files":
        raise NexusError("That is not a Nexus mod download link (nxm://...).")
    q = dict(urllib.parse.parse_qsl(parts.query))
    try:
        return NxmLink(
            domain=parts.netloc.lower(),
            mod_id=int(segs[1]),
            file_id=int(segs[3]),
            key=q.get("key"),
            expires=int(q["expires"]) if "expires" in q else None,
        )
    except ValueError as e:
        raise NexusError("That nxm:// link is malformed.") from e


def _percent_encode_path(url: str) -> str:
    """Nexus CDN links can contain raw spaces, which urllib rejects."""
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(parts._replace(path=urllib.parse.quote(parts.path, safe="/%")))


def _request_json(
    url: str,
    *,
    api_key: str | None = None,
    body: Any = None,
    method: str | None = None,
) -> Any:
    headers = {"User-Agent": USER_AGENT, "Application-Name": "Decky Mod Manager"}
    if api_key:
        headers["apikey"] = api_key
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, context=_SSL_CONTEXT, timeout=20) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise _http_error(e) from e
    except urllib.error.URLError as e:
        raise NexusError(f"Can't reach Nexus: {e.reason}") from e
    except json.JSONDecodeError as e:
        raise NexusError("Nexus sent a reply we couldn't read.") from e


def _http_error(e: urllib.error.HTTPError) -> NexusError:
    detail = ""
    try:
        detail = json.loads(e.read()).get("detail") or ""
    except (ValueError, AttributeError):
        pass
    if e.code == 401:
        return NexusError("Nexus rejected the API key. Check it in Settings.")
    if e.code == 403 and "key" in detail.lower():
        return NexusKeyRequired(detail)
    if e.code in (400, 410):
        return NexusKeyRequired(detail or "The download link has expired. Get a new one.")
    if e.code == 404:
        return NexusError("Not found on Nexus.")
    if e.code == 429:
        return NexusError("Nexus rate limit hit. Try again in a minute.")
    return NexusError(f"Nexus error {e.code}: {detail}".rstrip(": "))


def _data(payload: Any) -> dict:
    return payload.get("data") or {} if isinstance(payload, dict) else {}


class NexusClient:
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._domains_file = cache_dir / "nexus_domains.json"

    # ---- game domain ---------------------------------------------------

    def resolve_domain(self, appid: str, api_key: str | None) -> str | None:
        cached = self._read_json(self._domains_file, {})
        if appid in cached:
            return cached[appid]
        if not api_key:
            return None
        detected = _data(_request_json(
            f"{V3_BASE}/vortex/detected-games",
            api_key=api_key,
            body={"steam": [appid], "gog": [], "epic": []},
        )).get("games") or []
        domain = None
        if detected:
            game_id = str(detected[0]["game_id"])
            domain = next(
                (g["domain_name"] for g in self._games_index(api_key) if str(g.get("id")) == game_id),
                None,
            )
        cached[appid] = domain
        self._write_json(self._domains_file, cached)
        return domain

    def _games_index(self, api_key: str) -> list[dict]:
        path = self.cache_dir / "nexus_games.json"
        if path.exists() and time.time() - path.stat().st_mtime < 7 * 86400:
            games = self._read_json(path, None)
            if isinstance(games, list):
                return games
        games = _request_json(GAMES_INDEX_URL, api_key=api_key)
        if not isinstance(games, list):
            raise NexusError("Nexus sent an unexpected games list.")
        self._write_json(path, games)
        return games

    # ---- finding mods --------------------------------------------------

    async def browse(self, domain: str, sort: str, api_key: str | None) -> list[NexusMod]:
        if sort not in BROWSE_SORTS:
            raise ValueError(f"unknown sort: {sort}")
        payload = await asyncio.to_thread(
            _request_json,
            f"{V3_BASE}/mods/search",
            api_key=api_key,
            body={
                "filters": {"games": [domain], "include_adult": False, "time_range": BROWSE_SORTS[sort]},
                "sort": {"field": sort},
                "pagination": {"page_size": 100},
            },
        )
        return [
            NexusMod(
                mod_id=int(m["game_scoped_id"]),
                name=m.get("name") or "",
                summary=m.get("summary") or "",
                author=(m.get("author") or {}).get("name") or "",
                downloads=int(m.get("downloads") or 0),
                endorsements=int(m.get("endorsements") or 0),
                image=m.get("thumbnail_url"),
                updated_at=m.get("updated_at") or "",
            )
            for m in _data(payload).get("mods") or []
        ]

    async def search(self, domain: str, query: str) -> list[NexusMod]:
        payload = await asyncio.to_thread(
            _request_json,
            V2_GRAPHQL_URL,
            body={"query": _SEARCH_GQL, "variables": {"q": query, "domain": domain, "count": 100}},
        )
        if payload.get("errors"):
            raise NexusError(f"Nexus search failed: {payload['errors'][0].get('message')}")
        return [
            NexusMod(
                mod_id=int(m["modId"]),
                name=m.get("name") or "",
                summary=m.get("summary") or "",
                author=(m.get("uploader") or {}).get("name") or "",
                downloads=int(m.get("downloads") or 0),
                endorsements=int(m.get("endorsements") or 0),
                image=m.get("thumbnailUrl"),
                updated_at=m.get("updatedAt") or "",
            )
            for m in ((payload.get("data") or {}).get("mods") or {}).get("nodes") or []
        ]

    # ---- files ---------------------------------------------------------

    async def mod_files(self, domain: str, mod_id: int, api_key: str) -> list[NexusFile]:
        """The newest version of each file on the mod page, main files first."""
        mod = _data(await asyncio.to_thread(
            _request_json, f"{V3_BASE}/games/{domain}/mods/{mod_id}", api_key=api_key,
        ))
        files = _data(await asyncio.to_thread(
            _request_json, f"{V3_BASE}/mods/{mod['id']}/files", api_key=api_key,
        )).get("mod_files") or []
        active = [f for f in files if f.get("is_active")]
        version_lists = await asyncio.gather(*(
            asyncio.to_thread(_request_json, f"{V3_BASE}/mod-files/{f['id']}/versions", api_key=api_key)
            for f in active
        ))
        out: list[NexusFile] = []
        for payload in version_lists:
            versions = [
                v for v in _data(payload).get("versions") or []
                if v.get("category") not in _HIDDEN_FILE_CATEGORIES
            ]
            if not versions:
                continue
            latest = max(versions, key=lambda v: float(v.get("position") or 0))
            out.append(NexusFile(
                file_id=int(latest["game_scoped_id"]),
                name=latest.get("name") or "",
                version=latest.get("version") or "",
                category=latest.get("category") or "",
                is_primary=bool(latest.get("is_primary")),
            ))
        order = {"main": 0, "update": 1, "optional": 2}
        out.sort(key=lambda f: (not f.is_primary, order.get(f.category, 3), f.name.lower()))
        return out

    async def download_link(
        self,
        domain: str,
        file_id: int,
        api_key: str,
        *,
        key: str | None = None,
        expires: int | None = None,
    ) -> str:
        qs = f"?{urllib.parse.urlencode({'key': key, 'expires': expires})}" if key and expires else ""
        payload = await asyncio.to_thread(
            _request_json,
            f"{V3_BASE}/games/{domain}/mod-file-versions/{file_id}/download-link{qs}",
            api_key=api_key,
        )
        links = _data(payload).get("links") or []
        if not links:
            raise NexusError("Nexus returned no download link.")
        return links[0]["url"]

    async def download_to(self, url: str, dest: Path, on_progress: Callable[[float], None] | None = None) -> Path:
        def _do() -> Path:
            req = urllib.request.Request(_percent_encode_path(url), headers={"User-Agent": USER_AGENT})
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                with urllib.request.urlopen(req, context=_SSL_CONTEXT, timeout=120) as resp, dest.open("wb") as fh:
                    total = int(resp.headers.get("Content-Length") or 0)
                    done = 0
                    while chunk := resp.read(256 * 1024):
                        fh.write(chunk)
                        done += len(chunk)
                        if total and on_progress:
                            on_progress(done / total)
            except (urllib.error.URLError, OSError) as e:
                dest.unlink(missing_ok=True)
                raise NexusError(f"Download failed: {e}") from e
            return dest
        return await asyncio.to_thread(_do)

    # ---- cache helpers -------------------------------------------------

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            return default

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        try:
            path.write_text(json.dumps(value))
        except OSError:
            pass
