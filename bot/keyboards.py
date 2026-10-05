from aiogram.types import (InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton,
                           ReplyKeyboardMarkup)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.callbacks import Adm, Card, Flow, Menu, Pg, Rev
from db.models import Meeting, Status


MENU_BUTTON_TEXT = "🏠 Главное меню"


def main_reply_kb() -> ReplyKeyboardMarkup:
    """Постоянная кнопка внизу экрана."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=MENU_BUTTON_TEXT)]],
        resize_keyboard=True, is_persistent=True)


def overlap_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Отправить заявку", callback_data=Flow(step="confirm", v="send"))
    b.button(text="Выбрать другую дату", callback_data=Flow(step="conflict", v="date"))
    b.button(text="Связаться с админом", callback_data=Flow(step="conflict", v="admin"))
    b.button(text="Отмена", callback_data=Flow(step="confirm", v="cancel"))
    b.adjust(1)
    return b.as_markup()


def main_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📝 Заявка", callback_data=Menu(a="request"))
    b.button(text="⚙️ Управление", callback_data=Menu(a="manage"))
    b.adjust(2)
    return b.as_markup()


def admin_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Подключить Zoom", callback_data=Adm(a="zoom"))
    b.button(text="Подключить календарь", callback_data=Adm(a="caldav"))
    b.button(text="Шаблон сообщения", callback_data=Adm(a="template"))
    b.button(text="Дополнительный текст", callback_data=Adm(a="extra"))
    b.button(text="📋 Все встречи", callback_data=Pg(scope="all", n=0))
    b.adjust(2, 2, 1)
    return b.as_markup()


def durations() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for h in (1, 2, 3, 4):
        b.button(text=f"{h} ч", callback_data=Flow(step="dur", v=str(h)))
    b.adjust(4)
    return b.as_markup()


def repeat_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Нет", callback_data=Flow(step="rep", v="no"))
    b.button(text="Да, ежемесячно", callback_data=Flow(step="rep", v="monthly"))
    b.adjust(2)
    return b.as_markup()


WEEK_LABELS = [("1", "1-я"), ("2", "2-я"), ("3", "3-я"), ("4", "4-я"), ("-1", "Последняя")]


def weeks_kb(selected: list[int]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for key, label in WEEK_LABELS:
        mark = "✅ " if int(key) in selected else ""
        b.button(text=mark + label, callback_data=Flow(step="wk", v=key))
    b.button(text="Готово", callback_data=Flow(step="wk", v="done"))
    b.adjust(3, 2, 1)
    return b.as_markup()


def confirm_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Отправить", callback_data=Flow(step="confirm", v="send"))
    b.button(text="Отмена", callback_data=Flow(step="confirm", v="cancel"))
    b.adjust(2)
    return b.as_markup()


def conflict_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Выбрать другую дату", callback_data=Flow(step="conflict", v="date"))
    b.button(text="Связаться с админом", callback_data=Flow(step="conflict", v="admin"))
    b.adjust(1)
    return b.as_markup()


def review_kb(meeting_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Одобрить", callback_data=Rev(a="approve", id=meeting_id))
    b.button(text="❌ Отклонить", callback_data=Rev(a="reject", id=meeting_id))
    b.button(text="🔍 Проверить занятость", callback_data=Rev(a="check", id=meeting_id))
    b.adjust(2, 1)
    return b.as_markup()


def cancel_request_kb(meeting_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Одобрить отмену", callback_data=Card(a="cr_ok", id=meeting_id))
    b.button(text="Отклонить", callback_data=Card(a="cr_no", id=meeting_id))
    b.adjust(2)
    return b.as_markup()


def confirm_cancel_kb(meeting_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Да", callback_data=Card(a="cancel_yes", id=meeting_id))
    b.button(text="Нет", callback_data=Card(a="cancel_no", id=meeting_id))
    b.adjust(2)
    return b.as_markup()


def card_kb(m: Meeting, *, admin: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if admin:
        if m.status == Status.PENDING:
            b.button(text="✅ Одобрить", callback_data=Rev(a="approve", id=m.id))
            b.button(text="❌ Отклонить", callback_data=Rev(a="reject", id=m.id))
            b.button(text="🔍 Проверить занятость", callback_data=Rev(a="check", id=m.id))
            b.adjust(2, 1)
        elif m.status == Status.APPROVED:
            b.button(text="Отменить встречу", callback_data=Card(a="cancel", id=m.id))
        elif m.status == Status.CANCEL_REQUESTED:
            b.button(text="Одобрить отмену", callback_data=Card(a="cr_ok", id=m.id))
            b.button(text="Отклонить", callback_data=Card(a="cr_no", id=m.id))
            b.adjust(2)
        b.row(InlineKeyboardButton(text="« К списку", callback_data=Pg(scope="all", n=0).pack()))
    else:
        if m.status == Status.PENDING:
            b.button(text="Отменить заявку", callback_data=Card(a="withdraw", id=m.id))
        elif m.status == Status.APPROVED:
            b.button(text="Запросить отмену", callback_data=Card(a="request_cancel", id=m.id))
        b.row(InlineKeyboardButton(text="« К списку", callback_data=Pg(scope="mine", n=0).pack()))
    return b.as_markup()
