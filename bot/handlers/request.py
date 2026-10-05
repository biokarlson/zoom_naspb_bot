import logging
from datetime import date, datetime, timezone

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import config
from bot import keyboards as kb
from bot import notify, views
from bot.callbacks import Flow, Menu
from bot.states import RequestFSM
from db import repo
from db.models import Link, Meeting, Status
from services.availability import decide_link
from services.caldav_client import CalendarUnavailable, load_client
from services.recurrence import Rule, describe, matches
from services.zoom import ZoomClient

log = logging.getLogger(__name__)
router = Router()

WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]


def _start(data: dict) -> datetime:
    d = date.fromisoformat(data["date"])
    h, mi = map(int, data["time"].split(":"))
    return datetime(d.year, d.month, d.day, h, mi, tzinfo=config.TZ)


def _rule(data: dict, start: datetime) -> Rule | None:
    if data.get("recurring") and data.get("weeks"):
        return Rule(start.weekday(), tuple(data["weeks"]))
    return None


# ------------------------------------------------------------------ старт

async def _begin(target: Message, state: FSMContext, zoom: ZoomClient, user_id: int):
    if not await zoom.is_connected():
        await target.answer("Zoom пока не подключён, обратитесь к админу")
        return
    if await load_client() is None:
        await target.answer("Яндекс Календарь пока не подключён, обратитесь к админу")
        return
    async with repo.Session() as s:
        n = await repo.count_pending(s, user_id)
    if n >= config.MAX_PENDING_PER_USER:
        await target.answer(
            f"У вас уже {n} заявки на рассмотрении — это максимум. "
            "Дождитесь решения или отмените одну из них в «Управление».")
        return
    await state.clear()
    await state.set_state(RequestFSM.title)
    await target.answer("Название встречи? (/cancel — отмена)")


@router.callback_query(Menu.filter(F.a == "request"))
async def begin(cb: CallbackQuery, state: FSMContext, zoom: ZoomClient):
    await cb.answer()
    await _begin(cb.message, state, zoom, cb.from_user.id)


@router.message(Command("request"))
async def cmd_request(message: Message, state: FSMContext, zoom: ZoomClient):
    await _begin(message, state, zoom, message.from_user.id)


@router.message(RequestFSM.title, F.text)
async def got_title(message: Message, state: FSMContext):
    title = message.text.strip()
    if not title or len(title) > 200:
        await message.answer("Название должно быть от 1 до 200 символов. Попробуйте ещё раз.")
        return
    await state.update_data(title=title)
    await state.set_state(RequestFSM.committee)
    await message.answer("Комитет?")


@router.message(RequestFSM.committee, F.text)
async def got_committee(message: Message, state: FSMContext):
    committee = message.text.strip()
    if not committee or len(committee) > 200:
        await message.answer("Комитет: от 1 до 200 символов. Попробуйте ещё раз.")
        return
    await state.update_data(committee=committee)
    await state.set_state(RequestFSM.date)
    await message.answer("Дата встречи (ДД.ММ.ГГГГ), например 13.10.2026:")


@router.message(RequestFSM.date, F.text)
async def got_date(message: Message, state: FSMContext):
    try:
        d = datetime.strptime(message.text.strip(), "%d.%m.%Y").date()
    except ValueError:
        await message.answer("Не понял дату. Формат: ДД.ММ.ГГГГ, например 13.10.2026.")
        return
    if d < datetime.now(config.TZ).date():
        await message.answer("Эта дата уже прошла. Введите будущую дату.")
        return
    await state.update_data(date=d.isoformat())
    await state.set_state(RequestFSM.time)
    await message.answer("Время начала по Москве (ЧЧ:ММ), например 19:00:")


@router.message(RequestFSM.time, F.text)
async def got_time(message: Message, state: FSMContext):
    try:
        t = datetime.strptime(message.text.strip(), "%H:%M")
    except ValueError:
        await message.answer("Не понял время. Формат: ЧЧ:ММ, например 19:00.")
        return
    data = await state.get_data()
    d = date.fromisoformat(data["date"])
    start = datetime(d.year, d.month, d.day, t.hour, t.minute, tzinfo=config.TZ)
    if start <= datetime.now(timezone.utc):
        await message.answer("Это время уже прошло. Введите другое время (или /cancel и начните заново с другой даты).")
        return
    await state.update_data(time=t.strftime("%H:%M"))
    if "recurring" in data:             # повторный ввод даты/времени после отказа или конфликта
        if data["recurring"]:
            await _after_weeks(message, state, message.from_user.id)
        else:
            await _check_and_confirm(message, state, message.from_user.id)
        return
    await state.set_state(RequestFSM.duration)
    await message.answer("Продолжительность:", reply_markup=kb.durations())


@router.callback_query(RequestFSM.duration, Flow.filter(F.step == "dur"))
async def got_duration(cb: CallbackQuery, callback_data: Flow, state: FSMContext):
    await cb.answer()
    await state.update_data(dur=int(callback_data.v))
    await state.set_state(RequestFSM.repeat)
    await cb.message.answer("Повторять встречу?", reply_markup=kb.repeat_kb())


@router.callback_query(RequestFSM.repeat, Flow.filter(F.step == "rep"))
async def got_repeat(cb: CallbackQuery, callback_data: Flow, state: FSMContext):
    await cb.answer()
    if callback_data.v == "no":
        await state.update_data(recurring=False, weeks=[], weeks_done=False)
        await _check_and_confirm(cb.message, state, cb.from_user.id)
        return
    await state.update_data(recurring=True, weeks=[], weeks_done=False)
    await state.set_state(RequestFSM.weeks)
    await cb.message.answer(
        "Какие недели месяца? День недели возьму из даты первой встречи. "
        "Можно выбрать несколько.", reply_markup=kb.weeks_kb([]))


@router.callback_query(RequestFSM.weeks, Flow.filter(F.step == "wk"))
async def got_week(cb: CallbackQuery, callback_data: Flow, state: FSMContext):
    data = await state.get_data()
    weeks: list[int] = list(data.get("weeks", []))
    if callback_data.v == "done":
        if not weeks:
            await cb.answer("Выберите хотя бы одну неделю", show_alert=True)
            return
        await cb.answer()
        await state.update_data(weeks_done=True)
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass
        await _after_weeks(cb.message, state, cb.from_user.id)
        return
    w = int(callback_data.v)
    weeks = [x for x in weeks if x != w] if w in weeks else weeks + [w]
    await state.update_data(weeks=weeks)
    await cb.answer()
    try:
        await cb.message.edit_reply_markup(reply_markup=kb.weeks_kb(weeks))
    except TelegramBadRequest:
        pass


# ------------------------------------------------------------------ проверки

async def _after_weeks(msg: Message, state: FSMContext, user_id: int):
    data = await state.get_data()
    start = _start(data)
    rule = Rule(start.weekday(), tuple(data["weeks"]))
    if not matches(start.date(), rule):
        await state.set_state(RequestFSM.date)
        await msg.answer(
            f"Дата {start:%d.%m.%Y} ({WEEKDAYS[start.weekday()]}) не подходит под правило "
            f"«{describe(rule)}». Введите другую дату (ДД.ММ.ГГГГ).")
        return
    await _check_and_confirm(msg, state, user_id)


async def _check_and_confirm(msg: Message, state: FSMContext, user_id: int):
    data = await state.get_data()
    start = _start(data)
    dur_min = data["dur"] * 60
    rule = _rule(data, start)

    cal = await load_client()
    if cal is None:
        await state.clear()
        await msg.answer("Яндекс Календарь не подключён. Обратитесь к админу.")
        return
    try:
        async with repo.Session() as s:
            decision = await decide_link(s, cal, start, dur_min, rule)
    except CalendarUnavailable:
        log.exception("calendar check failed")
        await state.clear()
        await msg.answer("Не удалось проверить занятость: календарь недоступен. Попробуйте позже.")
        return

    await state.set_state(RequestFSM.confirm)
    if decision.kind is None:
        lines = ["⛔ В это время уже идут две встречи (по общей и по отдельной ссылке), "
                 "третью создать нельзя:"]
        for when, iv in decision.conflicts[:5]:
            kind = "встреча, созданная ботом" if iv.source == "bot" else "событие в календаре"
            lines.append(f"• {when:%d.%m.%Y %H:%M} — {kind}")
        if len(decision.conflicts) > 5:
            lines.append(f"…и ещё {len(decision.conflicts) - 5}")
        lines.append("\nВыберите другую дату или свяжитесь с админом.")
        await msg.answer("\n".join(lines), reply_markup=kb.conflict_kb())
        return

    overlap = decision.kind == Link.ALT
    await state.update_data(overlap=overlap)
    summary = [
        "📝 Проверьте заявку:",
        f"Название: {views.esc(data['title'])}",
        f"Комитет: {views.esc(data['committee'])}",
        f"Дата и время: {start:%d.%m.%Y %H:%M} МСК",
        f"Продолжительность: {views.dur_text(dur_min)}",
        f"Повтор: {describe(rule) if rule else 'нет'}",
    ]
    if overlap:
        what = "для всей серии" if rule else "для вашей встречи"
        summary.append(
            f"\n⚠️ Время пересекается с другой встречей, поэтому {what} будет создана "
            "отдельная ссылка — она не совпадёт с общей.")
    await msg.answer("\n".join(summary),
                     reply_markup=kb.overlap_kb() if overlap else kb.confirm_kb())


# ------------------------------------------------------------------ конфликт / подтверждение

@router.callback_query(RequestFSM.confirm, Flow.filter(F.step == "conflict"))
async def on_conflict(cb: CallbackQuery, callback_data: Flow, state: FSMContext, bot: Bot):
    await cb.answer()
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    if callback_data.v == "date":
        await state.set_state(RequestFSM.date)
        await cb.message.answer("Введите другую дату (ДД.ММ.ГГГГ):")
        return
    data = await state.get_data()
    text = (f"✉️ {views.user_link(cb.from_user)} не смог записаться на {data.get('date')} "
            f"{data.get('time')} (время занято) и просит связаться.\n"
            f"Заявка: {views.esc(data.get('title', ''))}")
    await notify.notify_admins(bot, text)
    await state.clear()
    await cb.message.answer("Сообщение отправлено админу, он свяжется с вами.")


@router.callback_query(RequestFSM.confirm, Flow.filter(F.step == "confirm"))
async def on_confirm(cb: CallbackQuery, callback_data: Flow, state: FSMContext, bot: Bot):
    await cb.answer()
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    if callback_data.v == "cancel":
        await state.clear()
        await cb.message.answer("Заявка отменена.", reply_markup=kb.main_menu())
        return

    data = await state.get_data()
    uid = cb.from_user.id
    start = _start(data)
    rule = _rule(data, start)
    name = cb.from_user.full_name + (f" (@{cb.from_user.username})" if cb.from_user.username else "")

    async with repo.Session() as s:
        if await repo.count_pending(s, uid) >= config.MAX_PENDING_PER_USER:
            await state.clear()
            await cb.message.answer("Лимит заявок на рассмотрении исчерпан.")
            return
        m = Meeting(
            author_tg_id=uid, author_name=name, title=data["title"], committee=data["committee"],
            start_at=start, duration_min=data["dur"] * 60,
            is_recurring=rule is not None,
            weekday=rule.weekday if rule else None,
            weeks_of_month=list(rule.weeks) if rule else None,
            status=Status.PENDING, admin_msgs=[],
            overlap_flag=bool(data.get("overlap", False)),
        )
        s.add(m)
        await s.commit()

    refs = await notify.send_admin_cards(bot, m)
    async with repo.Session() as s:
        await repo.set_admin_msgs(s, m.id, refs)
    await state.clear()
    if refs:
        await cb.message.answer("Заявка отправлена админу. Результат придёт сюда.",
                                reply_markup=kb.main_menu())
    else:
        await cb.message.answer(
            "Заявка сохранена, но доставить её админу не удалось. Свяжитесь с админом напрямую.",
            reply_markup=kb.main_menu())
