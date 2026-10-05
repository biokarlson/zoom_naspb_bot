from __future__ import annotations

from typing import Protocol

import config
from db.models import Meeting
from services.zoom import ZoomClient, ZoomMeetingInfo


class SeriesStrategy(Protocol):
    async def create(self, zoom: ZoomClient, m: Meeting) -> ZoomMeetingInfo: ...


class Type3PmiSeries:
    """Одна постоянная ссылка (type 3 + PMI). Расписание хранят бот и календарь."""

    async def create(self, zoom: ZoomClient, m: Meeting) -> ZoomMeetingInfo:
        return await zoom.create_meeting(m.title, type=3)


# Чтобы заменить способ создания серий, подставьте другую реализацию здесь.
series_strategy: SeriesStrategy = Type3PmiSeries()


async def create_zoom_for(zoom: ZoomClient, m: Meeting) -> ZoomMeetingInfo:
    if m.is_recurring:
        return await series_strategy.create(zoom, m)
    # Разовая встреча — отдельная комната со своим ID и ссылкой (не личная PMI)
    return await zoom.create_meeting(
        m.title, type=2,
        start_local=m.start_at.astimezone(config.TZ),
        duration_min=m.duration_min,
        use_pmi=False,
    )
