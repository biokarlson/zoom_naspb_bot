import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dateutil.relativedelta import relativedelta

import config
from bot.callbacks import Menu
from bot.states import CheckFSM
from db import repo
from services import daycheck, dateparse
from services.caldav_client import CalendarUnavailable, load_client

log = logging.getLogger(__name__)
router = Router()

PROMPT = ("Дата для проверки: например, 13.10.2026, 13.10, сегодня, завтра или послезавтра. "
          "/cancel — отмена.")


def _after_kb():
    b = InlineKeyboardBuilder()
    b.button(text="🔍 Другая дата", callback_data=Menu(a="check"))
    b.button(text="📝 Подать заявку", callback_data=Menu(a="request"))
    b.adjust(2)
    return b.as_markup()


async def _ask(target: Message, state: FSMContext):
    await state.clear()
    if await load_client() is None:
        await target.answer("Яндекс Календарь пока не подключён, обратитесь к админу")
        return
    await state.set_state(CheckFSM.date)
    await target.answer(PROMPT)


@router.callback_query(Menu.filter(F.a == "check"))
async def check_button(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await _ask(cb.message, state)


@router.message(Command("check"))
async def check_command(message: Message, state: FSMContext):
    await _ask(message, state)


@router.message(CheckFSM.date, F.text)
async def check_date(message: Message, state: FSMContext):
    today = datetime.now(config.TZ).date()
    day = dateparse.parse_date(message.text, today)
    if day is None:
        await message.answer("Не понял дату. Примеры: 13.10.2026, 13.10, сегодня, завтра.")
        return
    if day < today:
        await message.answer("Эта дата уже прошла. Введите сегодняшнюю или будущую дату.")
        return
    limit = today + relativedelta(months=config.HORIZON_MONTHS)
    if day > limit:
        await message.answer(
            f"Проверка работает на ближайшие {config.HORIZON_MONTHS} мес. (до {limit:%d.%m.%Y}).")
        return
    cal = await load_client()
    if cal is None:
        await state.clear()
        await message.answer("Яндекс Календарь пока не подключён, обратитесь к админу")
        return
    try:
        async with repo.Session() as s:
            segs = await daycheck.day_report(s, cal, day)
    except CalendarUnavailable:
        log.exception("day check failed")
        await state.clear()
        await message.answer("Не удалось проверить: календарь недоступен. Попробуйте позже.")
        return
    await state.clear()
    await message.answer(daycheck.format_report(day, segs), reply_markup=_after_kb())
