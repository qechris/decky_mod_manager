"""Per-game mod handlers.

To support a new game, subclass ``BaseHandler`` (or ``GenericHandler`` if plain
file mirroring is enough), set ``games`` to its Steam appids and Nexus
domains, and add the class to ``HANDLERS``. Unlisted games use
``GenericHandler``.
"""

from __future__ import annotations

from handlers.base import BaseHandler, EnableResult
from handlers.generic import GenericHandler
from handlers.kingdom_come import KCD2_APPID, KCD_APPID, KingdomComeHandler
from handlers.witcher3 import WITCHER3_APPID, Witcher3Handler

HANDLERS: list[type[BaseHandler]] = [Witcher3Handler, KingdomComeHandler]


def get_handler(appid: str) -> BaseHandler:
    for cls in HANDLERS:
        if str(appid) in cls.games:
            return cls()
    return GenericHandler()


def known_nexus_domain(appid: str) -> str | None:
    return get_handler(appid).games.get(str(appid))


__all__ = [
    "BaseHandler",
    "EnableResult",
    "GenericHandler",
    "HANDLERS",
    "KCD_APPID",
    "KCD2_APPID",
    "KingdomComeHandler",
    "Witcher3Handler",
    "WITCHER3_APPID",
    "get_handler",
    "known_nexus_domain",
]
