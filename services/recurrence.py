from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from dateutil.relativedelta import relativedelta

import config

LAST = -1
_BYDAY = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
_WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
_GENDER = ["m", "m", "f", "m", "f", "f", "n"]
_ORD = {
    1: ("1-й", "1-я", "1-е"), 2: ("2-й", "2-я", "2-е"),
    3: ("3-й", "3-я", "3-е"), 4: ("4-й", "4-я", "4-е"),
    LAST: ("последний", "последняя", "последнее"),
}
_EACH = {"m": "каждый", "f": "каждая", "n": "каждое"}
_GIDX = {"m": 0, "f": 1, "n": 2}


@dataclass(frozen=True)
class Rule:
    weekday: int
    weeks: tuple[int, ...]

    def __post_init__(self):
        if not self.weeks or any(w not in _ORD for w in self.weeks):
            raise ValueError("некорректные недели месяца")
        object.__setattr__(self, "weeks", tuple(sorted(set(self.weeks), key=lambda w: (w == LAST, w))))


def weeks_of_date(d: date) -> set[int]:
    result = set()
    n = (d.day - 1) // 7 + 1
    if n <= 4:
        result.add(n)
    if d.day + 7 > calendar.monthrange(d.year, d.month)[1]:
        result.add(LAST)
    return result


def matches(d: date, rule: Rule) -> bool:
    return d.weekday() == rule.weekday and bool(weeks_of_date(d) & set(rule.weeks))


def build_rrule(rule: Rule) -> str:
    days = ",".join(f"{w}{_BYDAY[rule.weekday]}" for w in rule.weeks)
    return f"RRULE:FREQ=MONTHLY;BYDAY={days}"


def describe(rule: Rule) -> str:
    g = _GENDER[rule.weekday]
    parts = [_ORD[w][_GIDX[g]] for w in rule.weeks]
    ords = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " и " + parts[-1]
    return f"{_EACH[g]} {ords} {_WEEKDAYS[rule.weekday]} месяца"


def expand(first_start: datetime, rule: Rule, now: datetime,
           horizon_months: int = config.HORIZON_MONTHS) -> list[datetime]:
    start_local = first_start.astimezone(config.TZ)
    t = start_local.timetz().replace(tzinfo=None)
    first_day = start_local.date()
    limit = (max(now.astimezone(config.TZ), start_local) + relativedelta(months=horizon_months)).date()

    days: set[date] = set()
    cur = first_day.replace(day=1)
    while cur <= limit:
        for day in range(1, calendar.monthrange(cur.year, cur.month)[1] + 1):
            d = cur.replace(day=day)
            if first_day <= d <= limit and matches(d, rule):
                days.add(d)
        cur += relativedelta(months=1)
    return [datetime.combine(d, t, tzinfo=config.TZ) for d in sorted(days)]


def split_rules(rule: Rule) -> list[Rule]:
    """Правило с несколькими неделями -> по одному правилу на неделю."""
    return [Rule(rule.weekday, (w,)) for w in rule.weeks]


def first_occurrence_on_or_after(d: date, rule: Rule) -> date:
    for i in range(400):
        cand = d + timedelta(days=i)
        if matches(cand, rule):
            return cand
    raise ValueError("не найдено занятие по правилу")


def has_overlapping_weeks(rule: Rule) -> bool:
    """4-я и последняя неделя в некоторых месяцах — один и тот же день недели."""
    return 4 in rule.weeks and LAST in rule.weeks


OVERLAP_WEEKS_NOTE = ("В месяцах, где 4-я и последняя неделя совпадают, в Яндекс Календаре будут "
                      "два одинаковых события (в Zoom и в расписании бота дубля нет).")


def calendar_plan(first_start: datetime, rule: Rule | None) -> list[tuple[datetime, str | None]]:
    """Какие события создать в календаре: [(начало первого занятия, RRULE или None)].
    Яндекс корректно разворачивает только одну неделю в BYDAY, поэтому серия с несколькими
    неделями создаётся отдельными событиями — по одному на каждую выбранную неделю.
    Известное ограничение: для пары «4-я + последняя» в месяцах, где они совпадают,
    в календаре два одинаковых события (BYMONTHDAY и BYDAY=5xx Яндекс разворачивает неверно)."""
    if rule is None:
        return [(first_start, None)]
    t = first_start.astimezone(config.TZ)
    tm = t.timetz().replace(tzinfo=None)
    plan = []
    for sub in split_rules(rule):
        d = first_occurrence_on_or_after(t.date(), sub)
        plan.append((datetime.combine(d, tm, tzinfo=config.TZ), build_rrule(sub)))
    return plan
