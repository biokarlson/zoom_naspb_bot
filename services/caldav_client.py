from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import caldav

import config


class CalendarUnavailable(Exception):
    pass


@dataclass(frozen=True)
class BusyInterval:
    start: datetime
    end: datetime
    source: str
    title: str = ""


def _to_utc(v) -> datetime:
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=config.TZ)
        return v.astimezone(timezone.utc)
    return datetime.combine(v, datetime.min.time(), tzinfo=config.TZ).astimezone(timezone.utc)


def _parse_vevent(comp) -> BusyInterval | None:
    if str(comp.get("TRANSP", "OPAQUE")).upper() == "TRANSPARENT":
        return None
    if str(comp.get("STATUS", "")).upper() == "CANCELLED":
        return None
    ds = comp.decoded("DTSTART")
    start = _to_utc(ds)
    if "DTEND" in comp:
        end = _to_utc(comp.decoded("DTEND"))
    elif "DURATION" in comp:
        end = start + comp.decoded("DURATION")
    elif isinstance(ds, date) and not isinstance(ds, datetime):
        end = start + timedelta(days=1)
    else:
        end = start + timedelta(minutes=1)
    if end <= start:
        end = start + timedelta(minutes=1)
    return BusyInterval(start, end, "calendar", str(comp.get("SUMMARY", "")))


class CalDavClient:
    def __init__(self, username: str, password: str, calendar_url: str | None = None):
        self._username, self._password, self._calendar_url = username, password, calendar_url

    def _calendar(self):
        client = caldav.DAVClient(
            url=config.CALDAV_URL, username=self._username, password=self._password)
        principal = client.principal()
        if self._calendar_url:
            return client, client.calendar(url=self._calendar_url)
        cals = principal.calendars()
        if not cals:
            raise CalendarUnavailable("В аккаунте нет календарей")
        return client, cals[0]

    def _fetch_busy_sync(self, start: datetime, end: datetime) -> list[BusyInterval]:
        _, cal = self._calendar()
        events = cal.search(start=start, end=end, event=True, expand=True)
        result: list[BusyInterval] = []
        for ev in events:
            for comp in ev.icalendar_instance.walk("VEVENT"):
                iv = _parse_vevent(comp)
                if iv and iv.start < end and start < iv.end:
                    result.append(iv)
        return result

    async def fetch_busy(self, start: datetime, end: datetime) -> list[BusyInterval]:
        try:
            return await asyncio.to_thread(self._fetch_busy_sync, start, end)
        except CalendarUnavailable:
            raise
        except Exception as e:
            raise CalendarUnavailable(str(e)) from e


# ---------------------------------------------------------------- запись событий

def _esc(t: str) -> str:
    return (t.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
             .replace("\r\n", "\\n").replace("\n", "\\n"))


def _fold(line: str) -> str:
    """Складывание строк iCalendar по 75 байт (с учётом UTF-8)."""
    if len(line.encode()) <= 75:
        return line
    parts, cur, limit = [], b"", 75
    for ch in line:
        b = ch.encode()
        if len(cur) + len(b) > limit:
            parts.append(cur)
            cur, limit = b, 74
        else:
            cur += b
    parts.append(cur)
    return "\r\n ".join(p.decode() for p in parts)


def build_ics(uid: str, title: str, committee: str, start_local: datetime,
              duration_min: int, join_url: str, rrule: str | None = None) -> str:
    """ICS одного события. Время с TZID=Europe/Moscow (UTC+3 без перехода на летнее),
    иначе у серий день недели в BYDAY мог бы 'уплыть' при пересчёте в UTC."""
    end_local = start_local + timedelta(minutes=duration_min)
    fmt = "%Y%m%dT%H%M%S"
    desc = f"Комитет: {committee}\nZoom: {join_url}"
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//zoombot//RU", "CALSCALE:GREGORIAN",
        "BEGIN:VTIMEZONE", "TZID:Europe/Moscow",
        "BEGIN:STANDARD", "DTSTART:19700101T000000",
        "TZOFFSETFROM:+0300", "TZOFFSETTO:+0300", "TZNAME:MSK", "END:STANDARD",
        "END:VTIMEZONE",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{datetime.now(timezone.utc).strftime(fmt)}Z",
        f"DTSTART;TZID=Europe/Moscow:{start_local.strftime(fmt)}",
        f"DTEND;TZID=Europe/Moscow:{end_local.strftime(fmt)}",
        f"SUMMARY:{_esc(title)}",
        f"DESCRIPTION:{_esc(desc)}",
        f"URL:{join_url}",
        "TRANSP:OPAQUE",
    ]
    if rrule:
        lines.append(rrule)  # уже вида "RRULE:FREQ=MONTHLY;BYDAY=2TU,4TU"
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(_fold(l) for l in lines) + "\r\n"


def _create_sync(self: "CalDavClient", ics: str) -> str:
    _, cal = self._calendar()
    ev = cal.save_event(ics)
    return str(ev.url)


def _delete_sync(self: "CalDavClient", href: str) -> None:
    client, _ = self._calendar()
    try:
        caldav.Event(client=client, url=href).delete()
    except caldav.error.NotFoundError:
        return  # уже удалено — считаем успехом


async def _create_event(self: "CalDavClient", *, uid: str, title: str, committee: str,
                        start: datetime, duration_min: int, join_url: str,
                        rrule: str | None = None) -> str:
    """Создаёт событие, возвращает URL (href) для последующего удаления."""
    ics = build_ics(uid, title, committee, start.astimezone(config.TZ),
                    duration_min, join_url, rrule)
    try:
        return await asyncio.to_thread(_create_sync, self, ics)
    except Exception as e:
        raise CalendarUnavailable(str(e)) from e


async def _delete_event(self: "CalDavClient", href: str) -> None:
    try:
        await asyncio.to_thread(_delete_sync, self, href)
    except Exception as e:
        raise CalendarUnavailable(str(e)) from e


CalDavClient.create_event = _create_event
CalDavClient.delete_event = _delete_event


async def load_client() -> "CalDavClient | None":
    """Клиент из сохранённых настроек; None, если календарь не подключён."""
    from db import repo
    from services import crypto
    async with repo.Session() as s:
        login = await repo.get_setting(s, "caldav_login")
        pwd = await repo.get_setting(s, "caldav_password")
        cal_url = await repo.get_setting(s, "caldav_calendar_url")
    if not login or not pwd:
        return None
    return CalDavClient(login, crypto.decrypt(pwd), cal_url or None)


def _list_sync(self: "CalDavClient") -> list[tuple[str, str]]:
    client = caldav.DAVClient(
        url=config.CALDAV_URL, username=self._username, password=self._password)
    cals = client.principal().calendars()
    return [(str(getattr(c, "name", None) or "Календарь"), str(c.url)) for c in cals]


async def _list_calendars(self: "CalDavClient") -> list[tuple[str, str]]:
    """Проверяет логин/пароль и возвращает [(название, url)]."""
    try:
        return await asyncio.to_thread(_list_sync, self)
    except Exception as e:
        raise CalendarUnavailable(str(e)) from e


CalDavClient.list_calendars = _list_calendars
