"""Сверка серии с календарём: после создания событий читаем календарь обратно и сравниваем
развёрнутые сервером занятия с ожидаемыми (так ловим дубли и пропуски из-за особенностей
разворачивания правил повтора у Яндекса)."""
from __future__ import annotations

import asyncio
import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import config
from services.caldav_client import CalendarUnavailable
from services.recurrence import Rule, expand

log = logging.getLogger(__name__)

VERIFY_HORIZON_MONTHS = 12
ATTEMPTS = 3          # календарь может отдать события не сразу
DELAY_SEC = 2.0


@dataclass
class VerifyResult:
    error: str | None = None     # расхождение: серию нужно откатить
    warning: str | None = None   # не удалось прочитать календарь: не блокируем, но предупреждаем


def _fmt(dts: list[datetime], limit: int = 6) -> str:
    local = [d.astimezone(config.TZ).strftime("%d.%m.%Y") for d in dts]
    text = ", ".join(local[:limit])
    return text + (f" и ещё {len(local) - limit}" if len(local) > limit else "")


async def verify_series(cal, uids: list[str], first_start: datetime, rule: Rule,
                        now: datetime | None = None) -> VerifyResult:
    now = now or datetime.now(timezone.utc)
    expected = sorted(s.astimezone(timezone.utc)
                      for s in expand(first_start, rule, now, VERIFY_HORIZON_MONTHS))
    start, end = expected[0] - timedelta(days=1), expected[-1] + timedelta(days=1)

    mismatch: list[datetime] | None = None
    last_error: Exception | None = None
    for attempt in range(ATTEMPTS):
        if attempt:
            await asyncio.sleep(DELAY_SEC)
        try:
            got = sorted(await cal.fetch_instances(set(uids), start, end))
        except CalendarUnavailable as e:
            last_error = e
            continue
        if got == expected:
            return VerifyResult()
        mismatch = got

    if mismatch is None:
        log.warning("Не удалось сверить серию с календарём: %s", last_error)
        return VerifyResult(warning=(
            f"Не удалось сверить серию с календарём ({last_error}). Проверьте события вручную."))

    extra = list((Counter(mismatch) - Counter(expected)).elements())
    missing = list((Counter(expected) - Counter(mismatch)).elements())
    lines = [f"Яндекс Календарь развернул серию не так, как ожидалось "
             f"(сверка на {VERIFY_HORIZON_MONTHS} мес. вперёд). События откатаны."]
    if extra:
        lines.append(f"Лишние или повторные даты: {_fmt(extra)}")
    if missing:
        lines.append(f"Не хватает дат: {_fmt(missing)}")
    return VerifyResult(error="\n".join(lines))
