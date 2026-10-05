from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

import config
from db import repo
from db.models import Meeting
from services.caldav_client import BusyInterval, CalDavClient
from services.recurrence import Rule, expand


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


async def _bot_busy(s: AsyncSession, window: tuple[datetime, datetime],
                    exclude_id: int | None, now: datetime) -> list[BusyInterval]:
    out: list[BusyInterval] = []
    for m in await repo.busy_meetings(s, exclude_id):
        for a, b in occurrences(m.start_at, m.duration_min, rule_of(m), now):
            if _overlaps(a, b, *window):
                out.append(BusyInterval(a, b, "bot", m.title))
    return out


async def find_conflicts(
    s: AsyncSession, cal: CalDavClient, start: datetime, duration_min: int,
    rule: Rule | None = None, exclude_id: int | None = None,
    now: datetime | None = None,
) -> list[tuple[datetime, BusyInterval]]:
    now = now or datetime.now(timezone.utc)
    cand = occurrences(start, duration_min, rule, now)
    window = (min(a for a, _ in cand), max(b for _, b in cand))

    busy = await _bot_busy(s, window, exclude_id, now)
    busy += await cal.fetch_busy(*window)

    conflicts = []
    for a, b in cand:
        for iv in busy:
            if _overlaps(a, b, iv.start, iv.end):
                conflicts.append((a.astimezone(config.TZ), iv))
    return conflicts
