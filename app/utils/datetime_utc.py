"""UTC helpers, user-facing timezone name, and JSON-safe ISO-8601 (Z)."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from core.db_models import MOSCOW_TZ


def coerce_to_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=MOSCOW_TZ).astimezone(timezone.utc)
    return dt.astimezone(timezone.utc)


def as_utc_iso_z(dt: datetime | None) -> str | None:
    u = coerce_to_utc(dt)
    if u is None:
        return None
    return u.strftime('%Y-%m-%dT%H:%M:%S') + 'Z'


def effective_timezone_name(user) -> str:
    """IANA zone for UI (meta tag, Intl); manual > profile.timezone > Moscow."""
    mode = (getattr(user, 'timezone_mode', None) or 'auto').lower()
    if mode == 'manual':
        iana = (getattr(user, 'timezone_iana', None) or '').strip()
        if iana:
            try:
                ZoneInfo(iana)
                return iana
            except Exception:
                pass
    prof = getattr(user, 'profile', None)
    if prof and getattr(prof, 'timezone', None):
        try:
            ZoneInfo(str(prof.timezone))
            return str(prof.timezone)
        except Exception:
            pass
    return 'Europe/Moscow'


def deadline_from_form_to_utc(dt: datetime) -> datetime:
    """Parse chain often ends with Moscow wall clock; store as aware UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MOSCOW_TZ)
    return dt.astimezone(timezone.utc)
