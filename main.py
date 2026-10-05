import asyncio
import logging
import os

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from aiohttp import web

import config
from bot.handlers import admin_settings, meetings, request, review, start
from db import repo
from services.zoom import ZoomClient
from web.oauth import create_app


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    await repo.init_db()
    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    try:  # меню команд (кнопка слева от поля ввода)
        await bot.set_my_commands([
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="request", description="Подать заявку"),
            BotCommand(command="my", description="Мои встречи"),
            BotCommand(command="cancel", description="Отменить действие"),
        ])
    except Exception:
        logging.getLogger(__name__).exception("Не удалось задать меню команд")
    # admin_settings первым: его фильтры пропускают только админов
    for r in (start.router, admin_settings.router, request.router, review.router, meetings.router):
        dp.include_router(r)

    async with aiohttp.ClientSession() as http:
        zoom = ZoomClient(http)
        dp["zoom"] = zoom

        runner = web.AppRunner(create_app(bot, zoom))
        await runner.setup()
        port = int(os.getenv("PORT", "8080"))
        await web.TCPSite(runner, "0.0.0.0", port).start()

        try:
            await dp.start_polling(bot)
        finally:
            await runner.cleanup()
            await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
