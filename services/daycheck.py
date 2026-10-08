"""Проверка занятости на день без заявки: какие промежутки заняты и можно ли подать заявку."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

import config
from db.models import Link

SECOND = "✅"   # занято одной встречей: возможна вторая (отдельная ссылка)
FULL = "⛔️"    # заняты и общая, и отдельная ссылка: подать заявку нельзя
_WD = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

LEGEND = (
    "Обозначения:\n"
    "✅ — время занято одной встречей: заявку подать можно, у вашей встречи будет отдельная ссылка\n"
    "⛔️ — идут две встречи одновременно: заявку подать нельзя\n"
    "Остальное время свободно. Встреча должна целиком попадать в свободное время или в ✅."
)


@dataclass
class Segment:
    start: datetime
    end: datetime
    label: str


def compute_segments(busy, wstart: datetime, wend: datetime) -> list[Segment]:
    """Склеенные промежутки, где общая ссылка занята: ✅, если отдельная свободна, иначе ⛔️.
    Время, когда занята только отдельная ссылка (общая свободна), считается свободным."""
    pts = {wstart, wend}
    for iv in busy:
        pts.add(min(max(iv.start, wstart), wend))
        pts.add(min(max(iv.end, wstart), wend))
    pts = sorted(pts)
    segs: list[Segment] = []
    for a, b in zip(pts, pts[1:]):
        main = alt = False
        for iv in busy:
            if iv.start < b and a < iv.end:
                if iv.kind == Link.ALT:
                    alt = True
                else:
                    main = True
        if not main:
            continue
        label = FULL if alt else SECOND
        if segs and segs[-1].label == label and segs[-1].end == a:
            segs[-1].end = b
        else:
            segs.append(Segment(a, b, label))
    return segs


async def day_report(s, cal, day: date, now: datetime | None = None) -> list[Segment]:
    from services.availability import gather_busy
    now = now or datetime.now(timezone.utc)
    start = datetime.combine(day, time.min, tzinfo=config.TZ)
    wstart, wend = start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)
    busy = await gather_busy(s, cal, (wstart, wend), None, now)
    return compute_segments(busy, wstart, wend)


def format_report(day: date, segs: list[Segment]) -> str:
    head = f"🔍 {day:%d.%m.%Y} ({_WD[day.weekday()]})"
    if not segs:
        return f"{head}: день свободен."
    day_start = datetime.combine(day, time.min, tzinfo=config.TZ).astimezone(timezone.utc)
    day_end = day_start + timedelta(days=1)
    lines = [f"{head}: занятое время (МСК)\n"]
    for sg in segs:
        if sg.start <= day_start and sg.end >= day_end:
            span = "весь день"
        else:
            a = sg.start.astimezone(config.TZ).strftime("%H:%M")
            b = "24:00" if sg.end >= day_end else sg.end.astimezone(config.TZ).strftime("%H:%M")
            span = f"{a}–{b}"
        lines.append(f"{sg.label} {span}")
    return "\n".join(lines) + "\n\n" + LEGEND
