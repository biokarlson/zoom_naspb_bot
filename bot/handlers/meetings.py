import logging
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

import config
from bot import keyboards as kb
from bot import notify, views
from bot.callbacks import Card, Pg
from db import repo
from db.models import Meeting, Status
from services.cancellation import cancel_meeting, is_running_or_started
from services.zoom import ZoomClient

log = logging.getLogger(__name__)
router = Router()


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _load(cb: CallbackQuery, meeting_id: int, *, admin_only: bool = False,
                author_only: bool = False) -> Meeting | None:
    """Загрузка встречи с проверкой прав. При отказе сам отвечает и возвращает None."""
    uid = cb.from_user.id
    async with repo.Session() as s:
        m = await repo.get_meeting(s, meeting_id)
    if m is None:
        await cb.answer("Встреча не найдена", show_alert=True)
        return None
    is_admin = config.is_admin(uid)
    if admin_only and not is_admin:
        await cb.answer("Нет доступа", show_alert=True)
        return None
    if author_only and m.author_tg_id != uid:
        await cb.answer("Нет доступа", show_alert=True)
        return None
    if not (is_admin or m.author_tg_id == uid):
        await cb.answer("Нет доступа", show_alert=True)
        return None
    return m


# ------------------------------------------------------------------ списки и карточки

@router.callback_query(Pg.filter())
async def on_page(cb: CallbackQuery, callback_data: Pg):
    if callback_data.scope == "all" and not config.is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    await cb.answer()
    text, markup = await views.build_list(callback_data.scope, callback_data.n, cb.from_user.id)
    await views.edit_or_send(cb, text, markup)


@router.callback_query(Card.filter(F.a == "open"))
async def open_card(cb: CallbackQuery, callback_data: Card):
    m = await _load(cb, callback_data.id)
    if not m:
        return
    await cb.answer()
    admin = config.is_admin(cb.from_user.id)
    await views.edit_or_send(cb, views.card_text(m, _now(), admin=admin), kb.card_kb(m, admin=admin))


# ------------------------------------------------------------------ действия автора

@router.callback_query(Card.filter(F.a == "withdraw"))
async def withdraw(cb: CallbackQuery, callback_data: Card, bot: Bot):
    if not await _load(cb, callback_data.id, author_only=True):
        return
    async with repo.Session() as s:
        ok = await repo.transition(s, callback_data.id, [Status.PENDING], Status.WITHDRAWN)
        m = await repo.get_meeting(s, callback_data.id)
    if not ok:
        await cb.answer("Заявка уже обработана", show_alert=True)
        return
    await cb.answer("Заявка отменена")
    await notify.refresh_admin_messages(bot, m, "↩️ Отменена автором")
    await views.edit_or_send(cb, "Заявка отменена, лимит освобождён.")


@router.callback_query(Card.filter(F.a == "request_cancel"))
async def request_cancel(cb: CallbackQuery, callback_data: Card, bot: Bot):
    m = await _load(cb, callback_data.id, author_only=True)
    if not m:
        return
    if is_running_or_started(m, _now()):
        await cb.answer("Занятие уже началось — отменить нельзя", show_alert=True)
        return
    async with repo.Session() as s:
        ok = await repo.transition(s, callback_data.id, [Status.APPROVED], Status.CANCEL_REQUESTED)
        m = await repo.get_meeting(s, callback_data.id)
    if not ok:
        await cb.answer("Состояние встречи изменилось", show_alert=True)
        return
    await cb.answer("Запрос отправлен")
    sent = await notify.send_cancel_request(bot, m)
    note = "Запрос на отмену отправлен админу." if sent else \
        "Запрос сохранён, но доставить его админу не удалось. Свяжитесь с админом напрямую."
    await views.edit_or_send(cb, note)


# ------------------------------------------------------------------ действия админа

@router.callback_query(Card.filter(F.a == "cancel"))
async def ask_cancel(cb: CallbackQuery, callback_data: Card):
    m = await _load(cb, callback_data.id, admin_only=True)
    if not m:
        return
    await cb.answer()
    await views.edit_or_send(
        cb, f"Точно отменить встречу «{views.esc(m.title)}»?", kb.confirm_cancel_kb(m.id))


@router.callback_query(Card.filter(F.a == "cancel_no"))
async def cancel_no(cb: CallbackQuery, callback_data: Card):
    m = await _load(cb, callback_data.id, admin_only=True)
    if not m:
        return
    await cb.answer()
    await views.edit_or_send(cb, views.card_text(m, _now(), admin=True), kb.card_kb(m, admin=True))


async def _do_cancel(cb: CallbackQuery, meeting_id: int, bot: Bot, zoom: ZoomClient,
                     *, author_text: str, admin_suffix: str) -> None:
    await views.safe_answer(cb, "Отменяю…")
    res = await cancel_meeting(zoom, meeting_id)
    if res.ok:
        m = res.meeting
        await views.edit_or_send(
            cb, views.card_text(m, _now(), admin=True, suffix=admin_suffix))
        await notify.notify_author(bot, m.author_tg_id, author_text.format(title=views.esc(m.title)))
    elif res.already_processed:
        await cb.message.answer("Встреча уже отменена или недоступна для отмены")
    else:
        await cb.message.answer(f"⚠️ {views.esc(res.text)}")


@router.callback_query(Card.filter(F.a == "cancel_yes"))
async def cancel_yes(cb: CallbackQuery, callback_data: Card, bot: Bot, zoom: ZoomClient):
    if not await _load(cb, callback_data.id, admin_only=True):
        return
    await _do_cancel(cb, callback_data.id, bot, zoom,
                     author_text="Встреча «{title}» отменена администратором.",
                     admin_suffix="🚫 Отменена")


@router.callback_query(Card.filter(F.a == "cr_ok"))
async def cr_ok(cb: CallbackQuery, callback_data: Card, bot: Bot, zoom: ZoomClient):
    if not await _load(cb, callback_data.id, admin_only=True):
        return
    await _do_cancel(cb, callback_data.id, bot, zoom,
                     author_text="Отмена одобрена: встреча «{title}» отменена.",
                     admin_suffix="🚫 Отмена одобрена")


@router.callback_query(Card.filter(F.a == "cr_no"))
async def cr_no(cb: CallbackQuery, callback_data: Card, bot: Bot):
    if not await _load(cb, callback_data.id, admin_only=True):
        return
    async with repo.Session() as s:
        ok = await repo.transition(s, callback_data.id, [Status.CANCEL_REQUESTED], Status.APPROVED)
        m = await repo.get_meeting(s, callback_data.id)
    if not ok:
        await cb.answer("Запрос уже обработан", show_alert=True)
        return
    await cb.answer("Отклонено")
    await views.edit_or_send(
        cb, views.card_text(m, _now(), admin=True, suffix="Отмена отклонена, встреча остаётся в силе"))
    await notify.notify_author(
        bot, m.author_tg_id,
        f"Отмена отклонена, встреча «{views.esc(m.title)}» остаётся в силе.")
