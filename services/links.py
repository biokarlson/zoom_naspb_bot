"""Единая ссылка встречи: заданная админом (с учётом отдельной комнаты) или из Zoom.
Заданные ссылки кэшируются в памяти (бот работает одним процессом), чтобы карточки и
списки могли показывать ссылку синхронно."""
from __future__ import annotations

from db import repo
from services import templating

_cache = {"join": "", "short": "", "calendar": ""}

CALENDAR_KEY = "calendar_url"   # ссылка на календарь для пользователей


async def load_custom() -> tuple[str, str]:
    async with repo.Session() as s:
        join = await repo.get_setting(s, templating.CUSTOM_JOIN_KEY)
        short = await repo.get_setting(s, templating.CUSTOM_SHORT_KEY)
    return join, short


async def refresh_cache() -> None:
    _cache["join"], _cache["short"] = await load_custom()
    async with repo.Session() as s:
        _cache["calendar"] = await repo.get_setting(s, CALENDAR_KEY)


def calendar_url() -> str:
    """Ссылка на календарь для кнопки «📅 Календарь» (пусто — кнопки нет)."""
    return _cache["calendar"]


def display_link(m) -> str:
    """Ссылка для показа в боте: такая же, как в сообщении автору."""
    return templating.effective_link(
        getattr(m, "link_kind", None), m.zoom_join_url or "", _cache["join"], _cache["short"])
