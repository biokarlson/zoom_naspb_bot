from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from db import repo
from db.models import Meeting, Status
from services.availability import occurrences, rule_of
from services.caldav_client import load_client
from services.zoom import ZoomClient

log = logging.getLogger(__name__)
_in_progress: set[int] = set()


@dataclass
class CancelResult:
    ok: bool
    text: str
    already_processed: bool = False
    meeting: Meeting | None = None


def is_running_or_started(m: Meeting, now: datetime) -> bool:
    """Одиночная: уже началась. Серия: какое-то занятие идёт прямо сейчас."""
    occ = occurrences(m.start_at, m.duration_min, rule_of(m), now)
    if rule_of(m) is None:
        return now >= occ[0][0]
    return any(a <= now < b for a, b in occ)


async def cancel_meeting(zoom: ZoomClient, meeting_id: int) -> CancelResult:
    """Zoom -> календарь -> БД. Повторный вызов безопасен: 404 в Zoom/календаре = уже удалено."""
    if meeting_id in _in_progress:
        return CancelResult(False, "Отмена уже выполняется", already_processed=True)
    _in_progress.add(meeting_id)
    try:
        async with repo.Session() as s:
            m = await repo.get_meeting(s, meeting_id)
        if m is None or m.status not in (Status.APPROVED, Status.CANCEL_REQUESTED):
            return CancelResult(False, "Встреча уже отменена или недоступна для отмены",
                                already_processed=True)

        now = datetime.now(timezone.utc)
        if is_running_or_started(m, now):
            return CancelResult(False, "Встречу нельзя отменить: занятие уже идёт или началось")

        done: list[str] = []
        failed: list[str] = []

        if m.zoom_meeting_id:
            try:
                await zoom.delete_meeting(m.zoom_meeting_id)
                done.append("удалена встреча Zoom")
            except Exception as e:
                log.exception("Zoom delete failed")
                failed.append(f"не удалена встреча Zoom: {e}")
        else:
            done.append("встречи Zoom не было")

        if m.caldav_href:
            cal = await load_client()
            if cal is None:
                failed.append("не удалено событие календаря: календарь не подключён")
            else:
                try:
                    await cal.delete_event(m.caldav_href)
                    done.append("удалено событие календаря")
                except Exception as e:
                    log.exception("CalDAV delete failed")
                    failed.append(f"не удалено событие календаря: {e}")

        if failed:
            return CancelResult(
                False,
                "Отмена не завершена, статус не изменён.\nСделано: " + "; ".join(done) +
                "\nОсталось: " + "; ".join(failed) + "\nМожно повторить отмену.")

        async with repo.Session() as s:
            ok = await repo.transition(
                s, meeting_id, (Status.APPROVED, Status.CANCEL_REQUESTED), Status.CANCELLED)
            m = await repo.get_meeting(s, meeting_id)
        if not ok:
            return CancelResult(False, "Встреча уже отменена", already_processed=True)
        return CancelResult(True, "Встреча отменена", meeting=m)
    finally:
        _in_progress.discard(meeting_id)
