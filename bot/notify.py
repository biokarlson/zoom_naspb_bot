import logging
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

import config
from bot import keyboards as kb
from bot import views
from db import repo
from db.models import Link, Meeting
from services import templating

log = logging.getLogger(__name__)

ALT_NOTE = ("⚠️ Время вашей встречи пересекалось с другой встречей, поэтому для неё создана "
            "отдельная комната. Эта ссылка отличается от общей — используйте именно её.")


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def send_admin_cards(bot: Bot, m: Meeting) -> list[dict]:
    text = views.card_text(m, _now(), admin=True, head="📝 Новая заявка")
    refs = []
    for admin_id in config.ADMIN_IDS:
        try:
            msg = await bot.send_message(admin_id, text, reply_markup=kb.review_kb(m.id))
            refs.append({"chat_id": admin_id, "message_id": msg.message_id})
        except (TelegramForbiddenError, TelegramBadRequest):
            log.warning("Не удалось отправить заявку админу %s", admin_id)
    return refs


async def send_cancel_request(bot: Bot, m: Meeting) -> int:
    text = views.card_text(m, _now(), admin=True, head="🛑 Запрос на отмену встречи")
    sent = 0
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, reply_markup=kb.cancel_request_kb(m.id))
            sent += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            log.warning("Не удалось отправить запрос отмены админу %s", admin_id)
    return sent


async def refresh_admin_messages(bot: Bot, m: Meeting, suffix: str) -> None:
    """Убирает кнопки и дописывает итог в сообщения админов о заявке."""
    text = views.card_text(m, _now(), admin=True, head="📝 Заявка", suffix=suffix)
    for ref in m.admin_msgs or []:
        try:
            await bot.edit_message_text(
                text, chat_id=ref["chat_id"], message_id=ref["message_id"], reply_markup=None)
        except TelegramBadRequest:
            pass


async def notify_author(bot: Bot, tg_id: int, text: str, *, plain: bool = False) -> bool:
    try:
        if plain:
            await bot.send_message(tg_id, text, parse_mode=None)
        else:
            await bot.send_message(tg_id, text)
        return True
    except (TelegramForbiddenError, TelegramBadRequest):
        log.warning("Не удалось уведомить пользователя %s", tg_id)
        return False


async def notify_admins(bot: Bot, text: str) -> None:
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except (TelegramForbiddenError, TelegramBadRequest):
            pass


async def render_instruction(m: Meeting) -> str:
    async with repo.Session() as s:
        tpl = await repo.get_setting(s, "template") or templating.DEFAULT_TEMPLATE
        custom_join = await repo.get_setting(s, templating.CUSTOM_JOIN_KEY)
        custom_short = await repo.get_setting(s, templating.CUSTOM_SHORT_KEY)
    text = templating.render(tpl, m, custom_join, custom_short)
    if m.link_kind == Link.ALT:
        text = ALT_NOTE + "\n\n" + text
    return text


async def send_instruction(bot: Bot, m: Meeting) -> bool:
    """Инструкция автору + (если задан) дополнительный текст отдельным сообщением.
    Возвращает успех отправки инструкции."""
    text = await render_instruction(m)
    ok = await notify_author(bot, m.author_tg_id, text, plain=True)
    if not ok:
        return False
    async with repo.Session() as s:
        extra = (await repo.get_setting(s, "extra_text")).strip()
    if extra:
        await notify_author(bot, m.author_tg_id, extra, plain=True)
    return True
