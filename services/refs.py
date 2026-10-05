import json


def parse_refs(value: str | None) -> list[str]:
    """Одно значение (старый формат) или JSON-список -> список строк."""
    if not value:
        return []
    if value.startswith("["):
        return list(json.loads(value))
    return [value]


def dump_refs(items: list[str]) -> str:
    """Одно значение хранится как есть (совместимо со старым форматом), несколько — JSON."""
    return items[0] if len(items) == 1 else json.dumps(items)
