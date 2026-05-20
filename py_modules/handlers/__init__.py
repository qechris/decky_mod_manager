"""Per-game mod handlers.

A handler encapsulates the rules for installing/enabling/disabling mods for a
specific game (or the generic file-mirror default). Selection is by Steam appid.
"""

from __future__ import annotations

from handlers.base import BaseHandler, EnableResult
from handlers.generic import GenericHandler
from handlers.witcher3 import WITCHER3_APPID, Witcher3Handler

_REGISTRY: dict[str, type[BaseHandler]] = {
    WITCHER3_APPID: Witcher3Handler,
}


def get_handler(appid: str) -> BaseHandler:
    cls = _REGISTRY.get(str(appid), GenericHandler)
    return cls()


__all__ = [
    "BaseHandler",
    "EnableResult",
    "GenericHandler",
    "Witcher3Handler",
    "WITCHER3_APPID",
    "get_handler",
]
