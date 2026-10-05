import os
from zoneinfo import ZoneInfo

# --- Константы (не секреты) ---
ADMIN_IDS: list[int] = [293772874]          # впишите Telegram ID админов
TZ = ZoneInfo("Europe/Moscow")
HORIZON_MONTHS = 6                          # горизонт проверки занятости серий
MAX_PENDING_PER_USER = 2
REJECTED_VISIBLE_DAYS = 3
PAGE_SIZE = 10
CALDAV_URL = "https://caldav.yandex.ru"

# --- Секреты (только из окружения) ---
BOT_TOKEN = os.environ["BOT_TOKEN"]
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///zoombot.db")
SETTINGS_KEY = os.environ["SETTINGS_KEY"]   # Fernet-ключ
ZOOM_CLIENT_ID = os.environ["ZOOM_CLIENT_ID"]
ZOOM_CLIENT_SECRET = os.environ["ZOOM_CLIENT_SECRET"]
ZOOM_REDIRECT_URI = os.environ["ZOOM_REDIRECT_URI"]


def is_admin(tg_id: int) -> bool:
    return tg_id in ADMIN_IDS
