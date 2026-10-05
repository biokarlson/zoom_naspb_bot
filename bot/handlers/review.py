import logging
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery

import config
from bot import notify, views
from bot.callbacks import Rev
from db import repo
from db.models import Link, Meeting, Status
from services import approval
from services.availability import decide_link, rule_of
from services.caldav_client import CalendarUnavailable, load_client
from services.zoom import ZoomClient

log = logging.getLogger(__name__)
router = Router()


async def _finish(bot: Bot, cb: CallbackQuery, m: Meeting, suffix: str) -> None:
    """Итог в сообщениях админов; если нажато в карточке списка — обновляем и её."""
    await notify.refresh_admin_messages(bot, m, suffix)
    refs = {(r["chat_id"], r["message_id"]) for r in (m.admin_msgs or [])}
    msg = cb.message
    if (msg.chat.id, msg.message_id) not in refs:
        try:
            await msg.edit_text(
                views.card_text(m, datetime.now(timezone.utc), admin=True, suffix=suffix),
                reply_markup=None)
        except TelegramBadRequest:
            pass


async def _strip_buttons(cb: CallbackQuery) -> None:
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass


@router.callback_query(Rev.filter(F.a == "approve"))
async def on_approve(cb: CallbackQuery, callback_data: Rev, bot: Bot, zoom: ZoomClient):
    if not config.is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    await views.safe_answer(cb, "Создаю встречу…")
    res = await approval.approve(zoom, callback_data.id)

    if res.already_processed:
        await cb.message.answer("Заявка уже обработана")
        await _strip_buttons(cb)
        return
    if not res.ok:
        await cb.message.answer(f"⚠️ {views.esc(res.text)}")
        return

    m = res.meeting
    suffix = "✅ Одобрено" + (" · отдельная ссылка (пересечение)" if m.link_kind == Link.ALT else "")
    await _finish(bot, cb, m, suffix)
    if not await notify.send_instruction(bot, m):
        await cb.message.answer("⚠️ Встреча создана, но сообщение автору доставить не удалось.")


@router.callback_query(Rev.filter(F.a == "reject"))
async def on_reject(cb: CallbackQuery, callback_data: Rev, bot: Bot):
    if not config.is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    async with repo.Session() as s:
        ok = await repo.transition(s, callback_data.id, [Status.PENDING], Status.REJECTED)
        m = await repo.get_meeting(s, callback_data.id)
    if not ok:
        await cb.answer("Заявка уже обработана", show_alert=True)
        await _strip_buttons(cb)
        return
    await cb.answer("Отклонено")
    await _finish(bot, cb, m, "❌ Отклонено")
    await notify.notify_author(bot, m.author_tg_id, f"Заявка «{views.esc(m.title)}» отклонена.")


@router.callback_query(Rev.filter(F.a == "check"))
async def on_check(cb: CallbackQuery, callback_data: Rev):
    if not config.is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    async with repo.Session() as s:
        m = await repo.get_meeting(s, callback_data.id)
    if m is None or m.status != Status.PENDING:
        await cb.answer("Заявка уже обработана", show_alert=True)
        await _strip_buttons(cb)
        return
    await views.safe_answer(cb, "Проверяю…")
    cal = await load_client()
    if cal is None:
        await cb.message.answer("Яндекс Календарь не подключён.")
        return
    try:
        async with repo.Session() as s:
            decision = await decide_link(
                s, cal, m.start_at, m.duration_min, rule_of(m), exclude_id=m.id)
    except CalendarUnavailable as e:
        await cb.message.answer(f"Не удалось проверить: календарь недоступен ({views.esc(e)})")
        return
    title = views.esc(m.title)
    if not decision.conflicts:
        await cb.message.answer(f"🔍 «{title}»: время свободно ✅ Будет общая ссылка.")
        return
    if decision.kind == Link.MAIN:
        head = f"🔍 «{title}»: есть пересечение, но общая ссылка свободна ✅ Будет общая ссылка."
    elif decision.kind == Link.ALT:
        head = f"🔍 «{title}»: пересечение ⚠️ Будет создана отдельная ссылка."
    else:
        head = f"🔍 «{title}»: ⛔ заняты и общая, и отдельная ссылка. Одобрить нельзя."
    lines = [head]
    for when, iv in decision.conflicts[:10]:
        kind = "встреча бота" if iv.source == "bot" else "календарь"
        link = " (отдельная ссылка)" if iv.kind == Link.ALT else ""
        lines.append(f"• {when:%d.%m.%Y %H:%M} — {kind}: {views.esc(iv.title)}{link}")
    if len(decision.conflicts) > 10:
        lines.append(f"…и ещё {len(decision.conflicts) - 10}")
    await cb.message.answer("\n".join(lines))
