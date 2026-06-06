from __future__ import annotations

from datetime import datetime, timezone

from core.db_models import MOSCOW_TZ, TOMSK_TZ

UTC = timezone.utc


def _tz_from_name(name: str | None):
    if (name or '').strip().lower() == 'tomsk':
        return TOMSK_TZ
    return MOSCOW_TZ


def parse_local_lesson_datetime(date_str: str, time_str: str, timezone_name: str) -> datetime:
    """
    Parse a local wall-clock lesson datetime and return a naive Moscow value for storage.

    We keep Lessons.lesson_date as naive Moscow wall time to match the rest of the legacy
    codebase, but centralize conversions here so the same value is interpreted consistently.
    """
    input_tz = _tz_from_name(timezone_name)
    local_dt = datetime.strptime(f'{date_str} {time_str}', '%Y-%m-%d %H:%M').replace(tzinfo=input_tz)
    return local_dt.astimezone(MOSCOW_TZ).replace(tzinfo=None)


def lesson_storage_to_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=MOSCOW_TZ).astimezone(UTC)
    return dt.astimezone(UTC)


def lesson_storage_to_local(dt: datetime | None, timezone_name: str) -> datetime | None:
    if dt is None:
        return None
    tz = _tz_from_name(timezone_name)
    return lesson_storage_to_utc(dt).astimezone(tz)


def lesson_storage_to_moscow(dt: datetime | None) -> datetime | None:
    return lesson_storage_to_local(dt, 'moscow')


def lesson_display_time(dt: datetime | None, timezone_name: str, fmt: str = '%d.%m.%Y %H:%M') -> str:
    local = lesson_storage_to_local(dt, timezone_name)
    return local.strftime(fmt) if local else '—'
