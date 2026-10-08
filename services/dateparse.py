"""Разбор даты из ввода пользователя: несколько вариантов записи и слова сегодня/завтра/послезавтра.
Свободный текст («13 октября») не разбирается."""
from __future__ import annotations

import re
from datetime import date, time, timedelta

_WORDS = {"сегодня": 0, "завтра": 1, "послезавтра": 2}
_TIME_RE = re.compile(r"^(\d{1,2})(?:[:.\-](\d{2}))?$")      # 19:00, 19.00, 19-00, 9:30, 19
_TIME4_RE = re.compile(r"^(\d{2})(\d{2})$")                     # 1900
_RE = re.compile(r"^(\d{1,2})[./\-](\d{1,2})(?:[./\-](\d{2}|\d{4}))?$")


def parse_date(text: str, today: date) -> date | None:
    t = text.strip().lower()
    if t in _WORDS:
        return today + timedelta(days=_WORDS[t])
    m = _RE.match(t)
    if not m:
        return None
    d, mo, y = int(m[1]), int(m[2]), m[3]
    try:
        if y is None:                       # без года — ближайшая будущая дата
            cand = date(today.year, mo, d)
            return cand if cand >= today else date(today.year + 1, mo, d)
        return date(int(y) + (2000 if len(y) == 2 else 0), mo, d)
    except ValueError:
        return None


def parse_time(text: str) -> time | None:
    """19:00, 19.00, 19-00, 1900, 19 (только часы), 9:30. Без разбора слов и 12-часового формата."""
    t = text.strip()
    m = _TIME_RE.match(t) or _TIME4_RE.match(t)
    if not m:
        return None
    h = int(m[1])
    mi = int(m[2]) if m[2] is not None else 0
    if h > 23 or mi > 59:
        return None
    return time(h, mi)
