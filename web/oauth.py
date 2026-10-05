from __future__ import annotations

import secrets
import time
from urllib.parse import urlencode

from aiohttp import web

import config
from services.zoom import ZoomClient

STATE_TTL = 600
_states: dict[str, tuple[int, float]] = {}


def new_state(admin_tg_id: int) -> str:
    now = time.time()
    for k in [k for k, (_, exp) in _states.items() if exp < now]:
        del _states[k]
    token = secrets.token_urlsafe(24)
    _states[token] = (admin_tg_id, now + STATE_TTL)
    return token


def authorize_url(state: str) -> str:
    return "https://zoom.us/oauth/authorize?" + urlencode({
        "response_type": "code",
        "client_id": config.ZOOM_CLIENT_ID,
        "redirect_uri": config.ZOOM_REDIRECT_URI,
        "state": state,
    })


def _page(text: str, status: int = 200) -> web.Response:
    html = f"<html><body style='font-family:sans-serif;text-align:center;margin-top:20vh'>{text}</body></html>"
    return web.Response(text=html, content_type="text/html", status=status)


async def zoom_callback(request: web.Request) -> web.Response:
    bot, zoom = request.app["bot"], request.app["zoom"]
    state = request.query.get("state", "")
    code = request.query.get("code")
    entry = _states.pop(state, None)

    if not entry or entry[1] < time.time():
        return _page("Ссылка устарела. Запустите подключение в боте заново.", 400)
    admin_id = entry[0]
    if request.query.get("error") or not code:
        await bot.send_message(admin_id, "Подключение Zoom отменено или не удалось.")
        return _page("Подключение не выполнено. Вернитесь в бота.", 400)

    try:
        await zoom.exchange_code(code)
    except Exception as e:
        await bot.send_message(admin_id, f"Не удалось подключить Zoom: {e}")
        return _page("Ошибка подключения. Подробности в боте.", 500)

    await bot.send_message(admin_id, "Zoom подключён ✅")
    return _page("Zoom подключён. Можно закрыть страницу и вернуться в Telegram.")


def create_app(bot, zoom: ZoomClient) -> web.Application:
    app = web.Application()
    app["bot"], app["zoom"] = bot, zoom
    app.router.add_get("/zoom/callback", zoom_callback)
    return app
