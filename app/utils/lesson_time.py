from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.utils.timezone import (
    UTC,
    LEGACY_TIMEZONE as LEGACY_STORAGE_TZ,
    canonical_timezone_name as timezone_name,
    format_viewer_dt as lesson_display_time,
    get_timezone as timezone_from_name,
    parse_local_to_utc as parse_local_lesson_datetime,
    to_utc_instant as lesson_storage_to_utc,
    to_viewer_tz as lesson_storage_to_local,
)


def lesson_storage_to_moscow(dt: datetime | None) -> datetime | None:
    """Нормализовать и отобразить момент урока в московском поясе."""
    return lesson_storage_to_local(dt, 'Europe/Moscow')
