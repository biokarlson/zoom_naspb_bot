from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

import config


class AdminFilter(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        return event.from_user is not None and config.is_admin(event.from_user.id)
