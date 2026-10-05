import logging
from datetime import datetime
from types import SimpleNamespace

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from bot import keyboards as kb
from bot.callbacks import Adm
from bot.filters import AdminFilter
from bot.states import AdminFSM
from db import repo
from services import crypto, templating
from services.caldav_client import CalDavClient, CalendarUnavailable
from services.zoom import ZoomClient
from web.oauth import authorize_url, new_state

log = logging.getLogger(__name__)
router = Router()
router.message.filter(AdminFilter())
router.callback_query.filter(AdminFilter())


# ------------------------------------------------------------------ Zoom

@router.callback_query(Adm.filter(F.a == "zoom"))
async def zoom_connect(cb: CallbackQuery, zoom: ZoomClient):
    await cb.answer()
    connected = await zoom.is_connected()
    b = InlineKeyboardBuilder()
    b.button(text="Авторизовать Zoom", url=authorize_url(new_state(cb.from_user.id)))
    prefix = "Zoom уже подключён, можно переподключить. " if connected else ""
    await cb.message.answer(
        prefix + "Нажмите кнопку и разрешите доступ. Ссылка действует 10 минут.",
        reply_markup=b.as_markup())


# ------------------------------------------------------------------ Яндекс Календарь

@router.callback_query(Adm.filter(F.a == "caldav"))
async def cal_start(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.clear()
    await state.set_state(AdminFSM.caldav_login)
    await cb.message.answer(
        "Введите логин Яндекса (почта). Нужен пароль приложения для календаря "
        "(Яндекс ID → Безопасность → Пароли приложений → «Календарь»), не основной пароль. "
        "/cancel — отмена.")


@router.message(AdminFSM.caldav_login, F.text)
async def cal_login(message: Message, state: FSMContext):
    await state.update_data(login=message.text.strip())
    await state.set_state(AdminFSM.caldav_password)
    await message.answer("Теперь пароль приложения. Сообщение с паролем я удалю.")


async def _save_calendar(message: Message, state: FSMContext, idx: int) -> None:
    data = await state.get_data()
    name, url = data["cals"][idx]
    async with repo.Session() as s:
        await repo.set_setting(s, "caldav_login", data["login"])
        await repo.set_setting(s, "caldav_password", data["pwd_enc"])
        await repo.set_setting(s, "caldav_calendar_url", url)
    await state.clear()
    await message.answer(f"Календарь подключён ✅: {name}")


@router.message(AdminFSM.caldav_password, F.text)
async def cal_password(message: Message, state: FSMContext):
    pwd = message.text.strip()
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
    data = await state.get_data()
    try:
        cals = await CalDavClient(data["login"], pwd).list_calendars()
    except CalendarUnavailable as e:
        await state.clear()
        await message.answer(f"Не удалось подключиться: {e}\nПроверьте логин и пароль приложения и начните заново.")
        return
    if not cals:
        await state.clear()
        await message.answer("В аккаунте не найдено календарей.")
        return
    await state.update_data(pwd_enc=crypto.encrypt(pwd), cals=[list(c) for c in cals])
    if len(cals) == 1:
        await _save_calendar(message, state, 0)
        return
    b = InlineKeyboardBuilder()
    for i, (name, _) in enumerate(cals):
        b.button(text=name[:40], callback_data=Adm(a="cal_pick", v=str(i)))
    b.adjust(1)
    await state.set_state(AdminFSM.caldav_pick)
    await message.answer("Выберите календарь для встреч:", reply_markup=b.as_markup())


@router.callback_query(AdminFSM.caldav_pick, Adm.filter(F.a == "cal_pick"))
async def cal_pick(cb: CallbackQuery, callback_data: Adm, state: FSMContext):
    await cb.answer()
    await _save_calendar(cb.message, state, int(callback_data.v))


# ------------------------------------------------------------------ шаблон

def _sample_meeting() -> SimpleNamespace:
    return SimpleNamespace(
        title="Название встречи", committee="Комитет",
        start_at=datetime(2026, 11, 10, 19, 0, tzinfo=config.TZ), duration_min=120,
        is_recurring=True, weekday=1, weeks_of_month=[2, 4],
        zoom_join_url="https://zoom.us/j/123456789", zoom_meeting_id="123456789",
        zoom_passcode="abc123", author_name="Иван Иванов")


async def _current(key: str, default: str = "") -> str:
    async with repo.Session() as s:
        return await repo.get_setting(s, key) or default


@router.callback_query(Adm.filter(F.a == "template"))
async def tpl_show(cb: CallbackQuery):
    await cb.answer()
    tpl = await _current("template", templating.DEFAULT_TEMPLATE)
    variables = ", ".join("{" + v + "}" for v in sorted(templating.ALLOWED))
    b = InlineKeyboardBuilder()
    b.button(text="Изменить", callback_data=Adm(a="tpl_edit"))
    b.button(text="Сбросить на стандартный", callback_data=Adm(a="tpl_reset"))
    b.adjust(2)
    await cb.message.answer(
        f"Текущий шаблон:\n\n{tpl}\n\nПеременные: {variables}",
        reply_markup=b.as_markup(), parse_mode=None)


@router.callback_query(Adm.filter(F.a == "tpl_edit"))
async def tpl_edit(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(AdminFSM.template)
    await cb.message.answer("Пришлите новый текст шаблона одним сообщением. /cancel — отмена.")


@router.message(AdminFSM.template, F.text)
async def tpl_save(message: Message, state: FSMContext):
    text = message.text
    error = templating.validate_template(text)
    if error:
        await message.answer(f"❌ {error}\nИсправьте и пришлите снова или /cancel.", parse_mode=None)
        return
    async with repo.Session() as s:
        await repo.set_setting(s, "template", text)
    await state.clear()
    extra = await _current("extra_text")
    preview = templating.render(text, _sample_meeting(), extra)
    await message.answer("Шаблон сохранён ✅ Пример:\n\n" + preview, parse_mode=None)


@router.callback_query(Adm.filter(F.a == "tpl_reset"))
async def tpl_reset(cb: CallbackQuery):
    await cb.answer()
    async with repo.Session() as s:
        await repo.set_setting(s, "template", "")
    await cb.message.answer("Возвращён стандартный шаблон.")


# ------------------------------------------------------------------ {extra_text}

@router.callback_query(Adm.filter(F.a == "extra"))
async def extra_show(cb: CallbackQuery):
    await cb.answer()
    extra = await _current("extra_text")
    b = InlineKeyboardBuilder()
    b.button(text="Изменить", callback_data=Adm(a="extra_edit"))
    b.button(text="Очистить", callback_data=Adm(a="extra_clear"))
    b.adjust(2)
    await cb.message.answer(
        "Дополнительный текст ({extra_text}):\n\n" + (extra or "(пусто)"),
        reply_markup=b.as_markup(), parse_mode=None)


@router.callback_query(Adm.filter(F.a == "extra_edit"))
async def extra_edit(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(AdminFSM.extra)
    await cb.message.answer("Пришлите новый дополнительный текст. /cancel — отмена.")


@router.message(AdminFSM.extra, F.text)
async def extra_save(message: Message, state: FSMContext):
    async with repo.Session() as s:
        await repo.set_setting(s, "extra_text", message.text)
    await state.clear()
    await message.answer("Дополнительный текст сохранён ✅")


@router.callback_query(Adm.filter(F.a == "extra_clear"))
async def extra_clear(cb: CallbackQuery):
    await cb.answer()
    async with repo.Session() as s:
        await repo.set_setting(s, "extra_text", "")
    await cb.message.answer("Дополнительный текст очищен.")
