from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from db import repo
from db.models import Meeting, Status
from services.availability import rule_of
from services.caldav_client import CalendarUnavailable, load_client
from services.recurrence import calendar_plan
from services.refs import dump_refs
from services.series import create_zoom_for
from services.zoom import ZoomClient, ZoomError, ZoomNotConnected

log = logging.getLogger(__name__)
_in_progress: set[int] = set()   # защита от двойного нажатия внутри процесса


@dataclass
class ApprovalResult:
    ok: bool
    text: str                     # сообщение админу
    already_processed: bool = False
    meeting: Meeting | None = None


async def approve(zoom: ZoomClient, meeting_id: int) -> ApprovalResult:
    if meeting_id in _in_progress:
        return ApprovalResult(False, "Заявка уже обрабатывается", already_processed=True)
    _in_progress.add(meeting_id)
    try:
        async with repo.Session() as s:
            m = await repo.get_meeting(s, meeting_id)
        if m is None or m.status != Status.PENDING:
            return ApprovalResult(False, "Заявка уже обработана", already_processed=True)

        cal = await load_client()
        if cal is None:
            return ApprovalResult(False, "Яндекс Календарь не подключён. Одобрение невозможно.")

        # 1) Zoom
        try:
            info = await create_zoom_for(zoom, m)
        except ZoomNotConnected:
            return ApprovalResult(False, "Zoom не подключён. Одобрение невозможно.")
        except ZoomError as e:
            log.exception("Zoom create failed")
            return ApprovalResult(False, f"Не удалось создать встречу в Zoom: {e}\nСтатус заявки не изменён.")

        # 2) Календарь: одно событие на разовую встречу; для серии — по событию на каждую
        #    выбранную неделю месяца. Любой сбой откатывает уже созданное, включая Zoom.
        rule = rule_of(m)
        uids: list[str] = []
        hrefs: list[str] = []
        try:
            for ev_start, rrule in calendar_plan(m.start_at, rule):
                uid = f"{uuid.uuid4()}@zoombot"
                href = await cal.create_event(
                    uid=uid, title=m.title, committee=m.committee, start=ev_start,
                    duration_min=m.duration_min, join_url=info.join_url, rrule=rrule)
                uids.append(uid)
                hrefs.append(href)
        except CalendarUnavailable as e:
            log.exception("CalDAV create failed")
            notes = [await _rollback_calendar(cal, h) for h in hrefs]
            notes.append(await _rollback_zoom(zoom, info.meeting_id))
            return ApprovalResult(
                False, f"Не удалось создать событие в календаре: {e}\n" + "\n".join(notes)
                + "\nСтатус заявки не изменён.")

        # 3) Фиксация в БД одним атомарным UPDATE
        async with repo.Session() as s:
            done = await repo.finalize_approval(
                s, meeting_id, zoom_id=info.meeting_id, join_url=info.join_url,
                passcode=info.passcode, caldav_uid=dump_refs(uids), caldav_href=dump_refs(hrefs))
            if not done:  # статус изменился, пока мы создавали встречи — откат всего
                notes = [await _rollback_zoom(zoom, info.meeting_id)]
                notes += [await _rollback_calendar(cal, h) for h in hrefs]
                return ApprovalResult(False, "Заявка уже обработана\n" + "\n".join(notes),
                                      already_processed=True)
            m = await repo.get_meeting(s, meeting_id)
        return ApprovalResult(True, "Одобрено", meeting=m)
    finally:
        _in_progress.discard(meeting_id)


async def _rollback_zoom(zoom: ZoomClient, zoom_id: str) -> str:
    try:
        await zoom.delete_meeting(zoom_id)
        return "Встреча в Zoom откатана (удалена)."
    except Exception as e:
        log.exception("Zoom rollback failed")
        return f"⚠️ Встреча Zoom {zoom_id} осталась и требует ручного удаления ({e})."


async def _rollback_calendar(cal, href: str) -> str:
    try:
        await cal.delete_event(href)
        return "Событие в календаре откатано (удалено)."
    except Exception as e:
        log.exception("Calendar rollback failed")
        return f"⚠️ Событие календаря осталось и требует ручного удаления ({e})."
