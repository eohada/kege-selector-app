"""UTC helpers, user-facing timezone name, and JSON-safe ISO-8601 (Z).

Delegates to canonical app.utils.timezone implementation while maintaining
full backward compatibility for existing callers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.utils.timezone import (
    UTC,
    LEGACY_TIMEZONE as MOSCOW_TZ,
    canonical_timezone_name,
    format_utc_iso_z as as_utc_iso_z,
    get_timezone,
    to_utc_instant,
    utc_now,
)


def coerce_to_utc(dt: datetime | None) -> datetime | None:
    """Normalize datetime to aware UTC datetime."""
    return to_utc_instant(dt, assume_utc_if_naive=True)


def effective_timezone_name(user) -> str:
    """IANA zone for UI (meta tag, Intl); profile timezone is source of truth."""
    if not user:
        return 'Europe/Moscow'

    # 1. Direct user.timezone_iana (manual or synced)
    iana = (getattr(user, 'timezone_iana', None) or '').strip()
    if iana:
        try:
            return ZoneInfo(canonical_timezone_name(iana)).key
        except Exception:
            pass

    # 2. Profile timezone
    prof = getattr(user, 'profile', None)
    if prof and getattr(prof, 'timezone', None):
        prof_tz = str(prof.timezone).strip()
        if prof_tz:
            try:
                return ZoneInfo(canonical_timezone_name(prof_tz)).key
            except Exception:
                pass

    return 'Europe/Moscow'


def deadline_from_form_to_utc(dt: datetime) -> datetime:
    """Parse chain often ends with Moscow wall clock; store as aware UTC."""
    return to_utc_instant(dt, assume_utc_if_naive=False, legacy_fallback_tz='Europe/Moscow') or utc_now()
