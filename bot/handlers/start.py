from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import config
from bot import keyboards as kb
from bot import views
from bot.callbacks import Menu
from services.caldav_client import load_client
from services.zoom import ZoomClient

router = Router()
MENU_TEXT = "Выберите действие:"


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(MENU_TEXT, reply_markup=kb.main_menu())


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=kb.main_menu())


@router.callback_query(Menu.filter(F.a == "home"))
async def home(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer()
    await views.edit_or_send(cb, MENU_TEXT, kb.main_menu())


@router.callback_query(Menu.filter(F.a == "manage"))
async def manage(cb: CallbackQuery, state: FSMContext, zoom: ZoomClient):
    await state.clear()
    await cb.answer()
    if config.is_admin(cb.from_user.id):
        zoom_ok = await zoom.is_connected()
        cal_ok = await load_client() is not None
        text = (
            "<b>Управление</b>\n\n"
            f"Zoom: {'✅ подключён' if zoom_ok else '❌ не подключён'}\n"
            f"Яндекс Календарь: {'✅ подключён' if cal_ok else '❌ не подключён'}"
        )
        await views.edit_or_send(cb, text, kb.admin_menu())
    else:
        text, markup = await views.build_list("mine", 0, cb.from_user.id)
        await views.edit_or_send(cb, text, markup)
