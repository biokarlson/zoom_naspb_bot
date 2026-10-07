import os
from zoneinfo import ZoneInfo

# --- Константы (не секреты) ---
VERSION = "1.3"

def _parse_ids(raw: str) -> list[int]:
    ids: list[int] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError:
            raise RuntimeError(f"ADMIN_IDS: «{part}» не похоже на Telegram ID (ожидаются числа через запятую)")
    return ids


# Telegram ID админов: переменная окружения ADMIN_IDS (через запятую), например 123456789,987654321.
# Она не перезаписывается при деплое. Запасной список ниже используется, только если переменная не задана.
_FALLBACK_ADMIN_IDS = [123456789]
ADMIN_IDS: list[int] = _parse_ids(os.getenv("ADMIN_IDS", "")) or _FALLBACK_ADMIN_IDS
ADMIN_IDS_FROM_ENV = bool(_parse_ids(os.getenv("ADMIN_IDS", "")))
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
