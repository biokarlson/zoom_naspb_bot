from __future__ import annotations

from typing import Protocol

import config
from db.models import Meeting
from services.zoom import ZoomClient, ZoomMeetingInfo


class SeriesStrategy(Protocol):
    async def create(self, zoom: ZoomClient, m: Meeting, *, use_pmi: bool) -> ZoomMeetingInfo: ...


class Type3Series:
    """Одна постоянная ссылка на всю серию (type 3, без фиксированного времени).
    use_pmi=True — общая ссылка (PMI), False — отдельная комната на всю серию.
    Расписание хранят бот и календарь."""

    async def create(self, zoom: ZoomClient, m: Meeting, *, use_pmi: bool) -> ZoomMeetingInfo:
        return await zoom.create_meeting(m.title, type=3, use_pmi=use_pmi)


# Чтобы заменить способ создания серий, подставьте другую реализацию здесь.
series_strategy: SeriesStrategy = Type3Series()


async def create_zoom_for(zoom: ZoomClient, m: Meeting, *, use_pmi: bool = True) -> ZoomMeetingInfo:
    if m.is_recurring:
        return await series_strategy.create(zoom, m, use_pmi=use_pmi)
    return await zoom.create_meeting(
        m.title, type=2,
        start_local=m.start_at.astimezone(config.TZ),
        duration_min=m.duration_min,
        use_pmi=use_pmi,
    )
