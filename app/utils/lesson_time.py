from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.db_models import MOSCOW_TZ

UTC = timezone.utc
LEGACY_STORAGE_TZ = MOSCOW_TZ

_ALIASES = {
    'moscow': 'Europe/Moscow',
    'europe/moscow': 'Europe/Moscow',
    'tomsk': 'Asia/Tomsk',
    'asia/tomsk': 'Asia/Tomsk',
    'utc': 'UTC',
}


def timezone_name(name: str | None, fallback: str = 'Europe/Moscow') -> str:
    """Вернуть валидное каноничное имя IANA без привязки к списку городов."""
    raw = (name or '').strip()
    candidate = _ALIASES.get(raw.lower(), raw or fallback)
    try:
        return ZoneInfo(candidate).key
    except (ZoneInfoNotFoundError, ValueError):
        return fallback


def timezone_from_name(name: str | None, fallback: str = 'Europe/Moscow') -> ZoneInfo:
    return ZoneInfo(timezone_name(name, fallback))


def lesson_storage_to_utc(dt: datetime | None) -> datetime | None:
    """Нормализовать момент урока в UTC.

    Новые записи хранятся aware UTC. Старые naive значения интерпретируются как
    московское wall time для обратной совместимости уже созданных уроков.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=LEGACY_STORAGE_TZ).astimezone(UTC)
    return dt.astimezone(UTC)


def parse_local_lesson_datetime(date_str: str, time_str: str, timezone_name_value: str | None) -> datetime:
    """Преобразовать введённые человеком локальные дату/время в UTC для БД."""
    tz = timezone_from_name(timezone_name_value)
    wall_time = datetime.strptime(f'{date_str} {time_str}', '%Y-%m-%d %H:%M')
    return wall_time.replace(tzinfo=tz).astimezone(UTC)


def lesson_storage_to_local(dt: datetime | None, timezone_name_value: str | None) -> datetime | None:
    instant = lesson_storage_to_utc(dt)
    return instant.astimezone(timezone_from_name(timezone_name_value)) if instant else None


def lesson_storage_to_moscow(dt: datetime | None) -> datetime | None:
    return lesson_storage_to_local(dt, 'Europe/Moscow')


def lesson_display_time(dt: datetime | None, timezone_name_value: str | None, fmt: str = '%d.%m.%Y %H:%M') -> str:
    local = lesson_storage_to_local(dt, timezone_name_value)
    return local.strftime(fmt) if local else '—'
