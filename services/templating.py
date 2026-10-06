from __future__ import annotations

import string

import config
from db.models import Link, Meeting
from services.availability import rule_of
from services.recurrence import describe

ALLOWED = {
    "title", "committee", "date", "time", "duration", "join_url", "meeting_id",
    "passcode", "author", "recurrence", "join_short_url",
}

# Ключи настроек: заданные админом ссылки для {join_url} и {join_short_url}
CUSTOM_JOIN_KEY = "join_url_custom"
CUSTOM_SHORT_KEY = "join_short_url_custom"

DEFAULT_TEMPLATE = (
    "Ваша встреча одобрена ✅\n\n"
    "{title}\n"
    "Комитет: {committee}\n"
    "Дата: {date}, {time} (МСК), {duration}\n"
    "{recurrence}\n\n"
    "Подключиться к Zoom: {join_url}\n"
    "ID встречи: {meeting_id}\n"
    "Код доступа: {passcode}"
)

_SAMPLE = {k: "x" for k in ALLOWED}


def validate_template(template: str) -> str | None:
    """None — шаблон корректен, иначе текст ошибки."""
    try:
        for _, name, spec, conv in string.Formatter().parse(template):
            if name is None:
                continue
            if name == "extra_text":
                return ("Переменная {extra_text} больше не используется: дополнительный текст "
                        "отправляется отдельным сообщением после инструкции. Уберите её из шаблона.")
            if name not in ALLOWED:
                return f"Неизвестная переменная: {{{name}}}"
            if spec or conv:
                return f"Форматирование внутри {{{name}}} не поддерживается"
        template.format_map(_SAMPLE)
    except (ValueError, KeyError, IndexError) as e:
        return f"Ошибка синтаксиса: {e}"
    return None


def _duration_text(minutes: int) -> str:
    h = minutes // 60
    word = "час" if h == 1 else "часа" if 2 <= h <= 4 else "часов"
    return f"{h} {word}" if minutes % 60 == 0 else f"{minutes} мин"


def resolve_links(link_kind: str | None, api_url: str, custom_join_url: str = "",
                  custom_short_url: str = "") -> tuple[str, str]:
    """(join_url, join_short_url). Ссылка из Zoom API берётся, только если встреча в отдельной
    комнате либо админ не задал ни {join_url}, ни {join_short_url}. Если задана хотя бы одна —
    подставляются только заданные, незаданная остаётся пустой."""
    custom_join, custom_short = custom_join_url.strip(), custom_short_url.strip()
    if link_kind != Link.ALT and (custom_join or custom_short):
        return custom_join, custom_short
    return api_url, api_url


def effective_link(link_kind: str | None, api_url: str, custom_join_url: str = "",
                   custom_short_url: str = "") -> str:
    """Единая ссылка встречи для календаря, карточек и списков: {join_url}, а если он пуст — {join_short_url}."""
    join_url, short_url = resolve_links(link_kind, api_url, custom_join_url, custom_short_url)
    return join_url or short_url


def context_for(m: Meeting, custom_join_url: str = "", custom_short_url: str = "") -> dict[str, str]:
    start = m.start_at.astimezone(config.TZ)
    rule = rule_of(m)
    join_url, short_url = resolve_links(
        getattr(m, "link_kind", None), m.zoom_join_url or "", custom_join_url, custom_short_url)
    return {
        "title": m.title,
        "committee": m.committee,
        "date": start.strftime("%d.%m.%Y"),
        "time": start.strftime("%H:%M"),
        "duration": _duration_text(m.duration_min),
        "join_url": join_url,
        "join_short_url": short_url,
        "meeting_id": m.zoom_meeting_id or "",
        "passcode": m.zoom_passcode or "",
        "author": m.author_name,
        "recurrence": describe(rule) if rule else "",
    }


def render(template: str, m: Meeting, custom_join_url: str = "", custom_short_url: str = "") -> str:
    """Если сохранённый шаблон вдруг некорректен — используем шаблон по умолчанию."""
    if validate_template(template) is not None:
        template = DEFAULT_TEMPLATE
    return template.format_map(context_for(m, custom_join_url, custom_short_url)).strip()
