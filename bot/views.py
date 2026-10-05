import html
import math
from datetime import datetime, timedelta, timezone

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, User
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from bot.callbacks import Card, Menu, Pg
from db import repo
from db.models import Meeting, Status
from services.availability import rule_of
from services.recurrence import describe, expand


def esc(x) -> str:
    return html.escape(str(x))


def dt_text(dt: datetime) -> str:
    return dt.astimezone(config.TZ).strftime("%d.%m.%Y %H:%M")


def dur_text(minutes: int) -> str:
    if minutes % 60:
        return f"{minutes} мин"
    h = minutes // 60
    return f"{h} {'час' if h == 1 else 'часа' if 2 <= h <= 4 else 'часов'}"


def user_link(u: User) -> str:
    return f'<a href="tg://user?id={u.id}">{esc(u.full_name)}</a>'


def author_link(m: Meeting) -> str:
    return f'<a href="tg://user?id={m.author_tg_id}">{esc(m.author_name or m.author_tg_id)}</a>'


def next_occurrence(m: Meeting, now: datetime) -> datetime | None:
    """Ближайшее (или идущее сейчас) занятие; None — встреча в прошлом."""
    d = timedelta(minutes=m.duration_min)
    rule = rule_of(m)
    if rule is None:
        return m.start_at if m.start_at + d > now else None
    for s in expand(m.start_at, rule, now):
        if s + d > now:
            return s
    return None


def card_text(m: Meeting, now: datetime, *, admin: bool, head: str = "", suffix: str = "") -> str:
    nxt = next_occurrence(m, now) or m.start_at
    rule = rule_of(m)
    lines = [head] if head else []
    lines += [f"<b>{esc(m.title)}</b>", f"Комитет: {esc(m.committee)}"]
    if admin:
        lines.append(f"Автор: {author_link(m)}")
    if rule:
        lines.append(f"Ближайшее занятие: {dt_text(nxt)} МСК")
        lines.append(f"Повтор: {describe(rule)}")
    else:
        lines.append(f"Дата и время: {dt_text(nxt)} МСК")
    lines.append(f"Продолжительность: {dur_text(m.duration_min)}")
    if m.zoom_join_url and m.status in Status.BUSY:
        lines.append(f"Zoom: {esc(m.zoom_join_url)}")
    lines.append(f"Статус: {Status.LABELS[m.status]}")
    if suffix:
        lines.append("\n" + suffix)
    return "\n".join(lines)


def _row_user(i: int, m: Meeting, nxt: datetime) -> str:
    rule = rule_of(m)
    lines = [f"{i}. <b>{esc(m.title)}</b>", f"   Комитет: {esc(m.committee)}",
             f"   {dt_text(nxt)} МСК · {Status.LABELS[m.status]}"]
    if rule:
        lines.append(f"   🔁 {describe(rule)}")
    if m.zoom_join_url and m.status in Status.BUSY:
        lines.append(f"   Zoom: {esc(m.zoom_join_url)}")
    return "\n".join(lines)


def _row_admin(i: int, m: Meeting, nxt: datetime) -> str:
    mark = "🔁 " if m.is_recurring else ""
    return f"{i}. {mark}<b>{esc(m.title)}</b> — {dt_text(nxt)} · {Status.LABELS[m.status]}"


async def build_list(scope: str, page: int, viewer_id: int) -> tuple[str, InlineKeyboardMarkup]:
    now = datetime.now(timezone.utc)
    async with repo.Session() as s:
        ms = await (repo.active_meetings(s) if scope == "all"
                    else repo.user_visible_meetings(s, viewer_id))
    items = [(m, nxt) for m in ms if (nxt := next_occurrence(m, now)) is not None]
    if scope == "all":
        items.sort(key=lambda t: (t[0].status != Status.PENDING, t[1]))
    else:
        items.sort(key=lambda t: t[1])

    title = "Все встречи" if scope == "all" else "Мои встречи"
    b = InlineKeyboardBuilder()
    if not items:
        b.row(InlineKeyboardButton(text="« В меню", callback_data=Menu(a="home").pack()))
        return f"<b>{title}</b>\n\nПока пусто.", b.as_markup()

    total = max(1, math.ceil(len(items) / config.PAGE_SIZE))
    page = min(max(page, 0), total - 1)
    start = page * config.PAGE_SIZE
    chunk = items[start:start + config.PAGE_SIZE]

    row_fn = _row_admin if scope == "all" else _row_user
    text = f"<b>{title}</b> (стр. {page + 1}/{total})\n\n" + "\n".join(
        row_fn(start + i + 1, m, nxt) for i, (m, nxt) in enumerate(chunk))
    for i, (m, _) in enumerate(chunk):
        b.row(InlineKeyboardButton(
            text=f"{start + i + 1}. {m.title[:40]}", callback_data=Card(a="open", id=m.id).pack()))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="« Назад", callback_data=Pg(scope=scope, n=page - 1).pack()))
    if page < total - 1:
        nav.append(InlineKeyboardButton(text="Вперёд »", callback_data=Pg(scope=scope, n=page + 1).pack()))
    if nav:
        b.row(*nav)
    b.row(InlineKeyboardButton(text="« В меню", callback_data=Menu(a="home").pack()))
    return text, b.as_markup()


async def edit_or_send(cb: CallbackQuery, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    try:
        await cb.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=markup)


async def safe_answer(cb: CallbackQuery, text: str | None = None, alert: bool = False) -> None:
    """cb.answer, не падающий, если запрос устарел (долгие операции Zoom/CalDAV)."""
    try:
        await cb.answer(text, show_alert=alert)
    except TelegramBadRequest:
        pass
