from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

import config
from db import repo
from db.models import Link, Meeting
from services.caldav_client import BusyInterval, CalDavClient
from services.recurrence import Rule, expand
from services.refs import parse_refs


def rule_of(m: Meeting) -> Rule | None:
    if m.is_recurring and m.weekday is not None and m.weeks_of_month:
        return Rule(m.weekday, tuple(m.weeks_of_month))
    return None


def occurrences(start: datetime, duration_min: int, rule: Rule | None,
                now: datetime) -> list[tuple[datetime, datetime]]:
    starts = expand(start, rule, now) if rule else [start]
    d = timedelta(minutes=duration_min)
    return [(s.astimezone(timezone.utc), (s + d).astimezone(timezone.utc)) for s in starts]


def _overlaps(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end


async def gather_busy(
    s: AsyncSession, cal: CalDavClient, window: tuple[datetime, datetime],
    exclude_id: int | None, now: datetime,
) -> list[BusyInterval]:
    """Занятое время: встречи бота (с типом ссылки) + события календаря.
    События, созданные самим ботом, в календаре пропускаем: они уже учтены по БД.
    Остальные события календаря считаем занятыми общей ссылкой (календарь только для Zoom)."""
    out: list[BusyInterval] = []
    bot_uids: set[str] = set()
    for m in await repo.busy_meetings(s, exclude_id):
        bot_uids.update(parse_refs(m.caldav_uid))
        kind = m.link_kind or Link.MAIN
        for a, b in occurrences(m.start_at, m.duration_min, rule_of(m), now):
            if _overlaps(a, b, *window):
                out.append(BusyInterval(a, b, "bot", m.title, kind=kind))
    for iv in await cal.fetch_busy(*window):
        if iv.uid and iv.uid in bot_uids:
            continue
        out.append(iv)
    return out


def _window(cand: list[tuple[datetime, datetime]]) -> tuple[datetime, datetime]:
    return min(a for a, _ in cand), max(b for _, b in cand)


async def find_conflicts(
    s: AsyncSession, cal: CalDavClient, start: datetime, duration_min: int,
    rule: Rule | None = None, exclude_id: int | None = None,
    now: datetime | None = None,
) -> list[tuple[datetime, BusyInterval]]:
    now = now or datetime.now(timezone.utc)
    cand = occurrences(start, duration_min, rule, now)
    busy = await gather_busy(s, cal, _window(cand), exclude_id, now)
    return [(a.astimezone(config.TZ), iv)
            for a, b in cand for iv in busy if _overlaps(a, b, iv.start, iv.end)]


@dataclass
class LinkDecision:
    kind: str | None   # Link.MAIN | Link.ALT | None (слот занят и общей, и отдельной ссылкой)
    conflicts: list[tuple[datetime, BusyInterval]]


async def decide_link(
    s: AsyncSession, cal: CalDavClient, start: datetime, duration_min: int,
    rule: Rule | None = None, exclude_id: int | None = None,
    now: datetime | None = None,
) -> LinkDecision:
    """Общая ссылка, если ни одно занятие не пересекается с встречей на общей ссылке;
    иначе отдельная, если ни одно занятие не пересекается с встречей на отдельной;
    иначе None. Для серии условие проверяется по всем занятиям (ссылка одна на всю серию)."""
    now = now or datetime.now(timezone.utc)
    cand = occurrences(start, duration_min, rule, now)
    busy = await gather_busy(s, cal, _window(cand), exclude_id, now)

    main_blocked = alt_blocked = False
    conflicts: list[tuple[datetime, BusyInterval]] = []
    for a, b in cand:
        for iv in busy:
            if _overlaps(a, b, iv.start, iv.end):
                conflicts.append((a.astimezone(config.TZ), iv))
                if iv.kind == Link.ALT:
                    alt_blocked = True
                else:
                    main_blocked = True
    kind = Link.MAIN if not main_blocked else (Link.ALT if not alt_blocked else None)
    return LinkDecision(kind, conflicts)
