from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo


def utcnow() -> datetime:
    return datetime.now(UTC)


def parse_local_datetime(value: str, timezone_name: str) -> datetime:
    local = datetime.strptime(value.strip(), "%d.%m.%Y %H:%M").replace(
        tzinfo=ZoneInfo(timezone_name)
    )
    return local.astimezone(UTC)


def format_datetime(value: datetime | None, timezone_name: str) -> str:
    if value is None:
        return "не указано"
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(ZoneInfo(timezone_name)).strftime("%d.%m.%Y %H:%M")
