"""BooStudy Canonical Timezone & Instant Module.

Unified contract:
1. Every temporal instant (lesson date/time, deadline, submission, Celery ETA)
   is represented in Python as a timezone-aware datetime in UTC (UTC instant).
2. Serialization to JSON/API is ISO-8601 with trailing 'Z' (YYYY-MM-DDTHH:mm:ssZ).
3. Database storage: TIMESTAMP WITH TIME ZONE (or UTC instant in SQLite).
4. Profile stores full IANA timezone name (e.g. Europe/Moscow, Asia/Kathmandu).
5. User input: local date + local time + profile IANA timezone -> converted to UTC instant once.
6. Display: converted to viewer's IANA timezone at render time.
7. Schedule grid/week calculations: calculated relative to viewer's IANA timezone.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

UTC = timezone.utc
LEGACY_TIMEZONE_NAME = 'Europe/Moscow'
LEGACY_TIMEZONE = ZoneInfo(LEGACY_TIMEZONE_NAME)

_TIMEZONE_ALIASES: dict[str, str] = {
    'moscow': 'Europe/Moscow',
    'europe/moscow': 'Europe/Moscow',
    'msk': 'Europe/Moscow',
    'tomsk': 'Asia/Tomsk',
    'asia/tomsk': 'Asia/Tomsk',
    'yekaterinburg': 'Asia/Yekaterinburg',
    'ekaterinburg': 'Asia/Yekaterinburg',
    'yekt': 'Asia/Yekaterinburg',
    'novosibirsk': 'Asia/Novosibirsk',
    'krasnoyarsk': 'Asia/Krasnoyarsk',
    'kaliningrad': 'Europe/Kaliningrad',
    'vladivostok': 'Asia/Vladivostok',
    'utc': 'UTC',
    'gmt': 'UTC',
    'z': 'UTC',
}


def utc_now() -> datetime:
    """Return current timestamp as timezone-aware UTC datetime."""
    return datetime.now(UTC)


def is_valid_timezone(name: str | None) -> bool:
    """Check if string is a valid IANA timezone identifier."""
    if not name or not isinstance(name, str):
        return False
    candidate = name.strip()
    candidate = _TIMEZONE_ALIASES.get(candidate.lower(), candidate)
    try:
        ZoneInfo(candidate)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def canonical_timezone_name(name: str | None, fallback: str = LEGACY_TIMEZONE_NAME) -> str:
    """Normalize and validate IANA timezone name.

    Returns canonical IANA key (e.g. 'Europe/Moscow') or fallback if invalid.
    """
    raw = (name or '').strip()
    if not raw:
        return fallback
    candidate = _TIMEZONE_ALIASES.get(raw.lower(), raw)
    try:
        return ZoneInfo(candidate).key
    except (ZoneInfoNotFoundError, ValueError):
        return fallback


def get_timezone(name: str | None, fallback: str = LEGACY_TIMEZONE_NAME) -> ZoneInfo:
    """Return ZoneInfo object for given timezone name with safe fallback."""
    return ZoneInfo(canonical_timezone_name(name, fallback))


def parse_local_to_utc(date_str: str, time_str: str, tz_name: str | None) -> datetime:
    """Convert user-entered local date and time in given IANA timezone to aware UTC instant.

    Supports date in YYYY-MM-DD or DD.MM.YYYY format.
    Supports time in HH:MM or HH:MM:SS format.
    Handles ambiguous and non-existent times during DST transitions safely.
    """
    tz = get_timezone(tz_name)
    d = (date_str or '').strip()
    t = (time_str or '12:00').strip()
    if len(t) > 5 and ':' in t[:5]:
        t = t[:5]
    elif not t:
        t = '12:00'

    wall_time: datetime
    if '.' in d:
        try:
            wall_time = datetime.strptime(f'{d} {t}', '%d.%m.%Y %H:%M')
        except ValueError:
            wall_time = datetime.strptime(f'{d} {t}', '%Y-%m-%d %H:%M')
    else:
        try:
            wall_time = datetime.strptime(f'{d} {t}', '%Y-%m-%d %H:%M')
        except ValueError:
            wall_time = datetime.strptime(f'{d} {t}', '%d.%m.%Y %H:%M')

    # Attach tzinfo with fold=0 (handles DST gap / fold safely)
    aware_local = wall_time.replace(tzinfo=tz, fold=0)
    return aware_local.astimezone(UTC)


def to_utc_instant(
    dt_or_str: datetime | str | None,
    *,
    assume_utc_if_naive: bool = True,
    legacy_fallback_tz: str | None = None
) -> datetime | None:
    """Normalize any datetime object or ISO string to timezone-aware UTC datetime.

    - If aware: converts directly to UTC.
    - If naive datetime and assume_utc_if_naive=True: attaches UTC.
    - If naive datetime and assume_utc_if_naive=False: interprets as legacy_fallback_tz (default Europe/Moscow).
    - If string: parses ISO-8601 (handling 'Z', offset, or naive).
    """
    if dt_or_str is None:
        return None

    if isinstance(dt_or_str, str):
        val = dt_or_str.strip()
        if not val:
            return None
        # Handle trailing Z
        if val.endswith('Z') or val.endswith('z'):
            val = val[:-1] + '+00:00'
        # Normalize space to T
        if ' ' in val and 'T' not in val:
            val = val.replace(' ', 'T', 1)
        try:
            parsed = datetime.fromisoformat(val)
        except ValueError:
            # Fallback for simple date or Russian format
            if '.' in val:
                try:
                    parsed = datetime.strptime(val[:16], '%d.%m.%Y %H:%M')
                except ValueError:
                    parsed = datetime.strptime(val[:10], '%d.%m.%Y')
            else:
                try:
                    parsed = datetime.strptime(val[:16], '%Y-%m-%d %H:%M')
                except ValueError:
                    parsed = datetime.strptime(val[:10], '%Y-%m-%d')

        if parsed.tzinfo is not None:
            return parsed.astimezone(UTC)
        dt_or_str = parsed

    if isinstance(dt_or_str, datetime):
        if dt_or_str.tzinfo is not None:
            return dt_or_str.astimezone(UTC)
        if assume_utc_if_naive:
            return dt_or_str.replace(tzinfo=UTC)
        fallback_zone = get_timezone(legacy_fallback_tz or LEGACY_TIMEZONE_NAME)
        return dt_or_str.replace(tzinfo=fallback_zone).astimezone(UTC)

    return None


def format_utc_iso_z(dt: datetime | None) -> str | None:
    """Format aware UTC instant as strict ISO-8601 string ending with 'Z'."""
    u = to_utc_instant(dt, assume_utc_if_naive=True)
    if u is None:
        return None
    return u.strftime('%Y-%m-%dT%H:%M:%SZ')


def to_viewer_tz(dt: datetime | str | None, viewer_tz: str | None = None) -> datetime | None:
    """Convert UTC instant to the viewer's IANA timezone."""
    instant = to_utc_instant(dt, assume_utc_if_naive=True)
    if instant is None:
        return None
    target_zone = get_timezone(viewer_tz)
    return instant.astimezone(target_zone)


def format_viewer_dt(
    dt: datetime | str | None,
    viewer_tz: str | None = None,
    fmt: str = '%d.%m.%Y %H:%M'
) -> str:
    """Convert UTC instant to viewer's timezone and format as string."""
    local = to_viewer_tz(dt, viewer_tz)
    if local is None:
        return '—'
    return local.strftime(fmt)


def get_schedule_week_bounds(
    ref_date_or_now: date | datetime | None,
    week_offset: int,
    viewer_tz: str | None = None
) -> dict[str, Any]:
    """Calculate Monday..Sunday week boundaries relative to viewer's IANA timezone.

    Prevents date shifts caused by server running in a different timezone (e.g. UTC vs MSK).
    """
    tz = get_timezone(viewer_tz)
    if ref_date_or_now is None:
        viewer_now = datetime.now(tz)
        today_date = viewer_now.date()
    elif isinstance(ref_date_or_now, datetime):
        if ref_date_or_now.tzinfo is None:
            ref_date_or_now = ref_date_or_now.replace(tzinfo=UTC)
        today_date = ref_date_or_now.astimezone(tz).date()
    else:
        today_date = ref_date_or_now

    # Monday of the target week
    diff_to_monday = today_date.weekday()
    target_monday = today_date - timedelta(days=diff_to_monday) + timedelta(weeks=week_offset)
    target_sunday = target_monday + timedelta(days=6)

    day_names = ['ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ', 'СБ', 'ВС']
    weekdays: list[dict[str, Any]] = []
    for i in range(7):
        cur_day = target_monday + timedelta(days=i)
        weekdays.append({
            'name': day_names[i],
            'date': cur_day.day,
            'iso': cur_day.isoformat(),
            'is_today': (cur_day == today_date),
            'weekday_index': i,
        })

    # UTC intervals for SQL querying covering the whole week in viewer's timezone
    week_start_local = datetime.combine(target_monday, time.min, tzinfo=tz)
    week_end_local = datetime.combine(target_sunday, time.max, tzinfo=tz)
    week_start_utc = week_start_local.astimezone(UTC)
    week_end_utc = week_end_local.astimezone(UTC)

    return {
        'today': today_date,
        'week_start': target_monday,
        'week_end': target_sunday,
        'week_start_local': week_start_local,
        'week_end_local': week_end_local,
        'week_start_utc': week_start_utc,
        'week_end_utc': week_end_utc,
        'weekdays': weekdays,
        'viewer_tz': tz.key,
    }


def get_grouped_timezones_for_ui() -> list[dict[str, Any]]:
    """Return full grouped IANA timezone choices with Russian labels and UTC offsets."""
    now_utc = utc_now()

    def _offset_label(tz_key: str) -> str:
        try:
            offset = ZoneInfo(tz_key).utcoffset(now_utc)
            if offset is None:
                return 'UTC'
            total_minutes = int(offset.total_seconds() // 60)
            sign = '+' if total_minutes >= 0 else '-'
            abs_min = abs(total_minutes)
            h, m = divmod(abs_min, 60)
            if m:
                return f"UTC{sign}{h}:{m:02d}"
            return f"UTC{sign}{h}"
        except Exception:
            return 'UTC'

    groups = [
        {
            'group': 'Россия',
            'zones': [
                ('Europe/Kaliningrad', 'Калининград (МСК-1)'),
                ('Europe/Moscow', 'Москва, Санкт-Петербург (МСК)'),
                ('Europe/Kirov', 'Киров (МСК)'),
                ('Europe/Volgograd', 'Волгоград (МСК)'),
                ('Europe/Astrakhan', 'Астрахань, Ульяновск (МСК+1)'),
                ('Europe/Samara', 'Самара, Саратов, Ижевск (МСК+1)'),
                ('Europe/Ulyanovsk', 'Ульяновск (МСК+1)'),
                ('Asia/Yekaterinburg', 'Екатеринбург, Пермь, Тюмень, Уфа, Челябинск (МСК+2)'),
                ('Asia/Omsk', 'Омск (МСК+3)'),
                ('Asia/Barnaul', 'Барнаул, Алтай (МСК+4)'),
                ('Asia/Novosibirsk', 'Новосибирск (МСК+4)'),
                ('Asia/Tomsk', 'Томск (МСК+4)'),
                ('Asia/Novokuznetsk', 'Новокузнецк, Кемерово (МСК+4)'),
                ('Asia/Krasnoyarsk', 'Красноярск (МСК+4)'),
                ('Asia/Irkutsk', 'Иркутск, Улан-Удэ (МСК+5)'),
                ('Asia/Chita', 'Чита (МСК+6)'),
                ('Asia/Yakutsk', 'Якутск (МСК+6)'),
                ('Asia/Khandyga', 'Хандыга (МСК+6)'),
                ('Asia/Vladivostok', 'Владивосток, Хабаровск (МСК+7)'),
                ('Asia/Ust-Nera', 'Усть-Нера (МСК+7)'),
                ('Asia/Magadan', 'Магадан (МСК+8)'),
                ('Asia/Sakhalin', 'Южно-Сахалинск (МСК+8)'),
                ('Asia/Srednekolymsk', 'Среднеколымск (МСК+8)'),
                ('Asia/Kamchatka', 'Петропавловск-Камчатский (МСК+9)'),
                ('Asia/Anadyr', 'Анадырь, Чукотка (МСК+9)'),
            ]
        },
        {
            'group': 'СНГ и соседние страны',
            'zones': [
                ('Europe/Minsk', 'Минск (Беларусь)'),
                ('Asia/Almaty', 'Алматы, Астана (Казахстан)'),
                ('Asia/Qyzylorda', 'Кызылорда, Актобе (Казахстан)'),
                ('Asia/Tashkent', 'Ташкент, Самарканд (Узбекистан)'),
                ('Asia/Bishkek', 'Бишкек (Кыргызстан)'),
                ('Asia/Dushanbe', 'Душанбе (Таджикистан)'),
                ('Asia/Ashgabat', 'Ашхабад (Туркменистан)'),
                ('Asia/Tbilisi', 'Тбилиси (Грузия)'),
                ('Asia/Yerevan', 'Ереван (Армения)'),
                ('Asia/Baku', 'Баку (Азербайджан)'),
                ('Europe/Chisinau', 'Кишинёв (Молдова)'),
            ]
        },
        {
            'group': 'Европа',
            'zones': [
                ('Europe/London', 'Лондон, Дублин (GMT/BST)'),
                ('Europe/Berlin', 'Берлин, Франкфурт (CET/CEST)'),
                ('Europe/Paris', 'Париж, Брюссель, Амстердам (CET/CEST)'),
                ('Europe/Rome', 'Рим, Милан (CET/CEST)'),
                ('Europe/Madrid', 'Мадрид, Барселона (CET/CEST)'),
                ('Europe/Warsaw', 'Варшава, Краков (CET/CEST)'),
                ('Europe/Prague', 'Прага, Братислава (CET/CEST)'),
                ('Europe/Vienna', 'Вена, Цюрих (CET/CEST)'),
                ('Europe/Belgrade', 'Белград, Загреб, Сараево (CET/CEST)'),
                ('Europe/Athens', 'Афины, Салоники (EET/EEST)'),
                ('Europe/Bucharest', 'Бухарест, София (EET/EEST)'),
                ('Europe/Helsinki', 'Хельсинки, Таллин, Рига, Вильнюс (EET/EEST)'),
                ('Europe/Kyiv', 'Киев (EET/EEST)'),
                ('Europe/Istanbul', 'Стамбул, Анкара (TRT, UTC+3)'),
                ('Europe/Lisbon', 'Лиссабон (WET/WEST)'),
            ]
        },
        {
            'group': 'Азия и Ближний Восток',
            'zones': [
                ('Asia/Dubai', 'Дубай, Абу-Даби (GST, UTC+4)'),
                ('Asia/Riyadh', 'Эр-Рияд, Джидда (AST, UTC+3)'),
                ('Asia/Jerusalem', 'Иерусалим, Тель-Авив (IDT)'),
                ('Asia/Tehran', 'Тегеран (IRST)'),
                ('Asia/Karachi', 'Карачи, Исламабад (PKT, UTC+5)'),
                ('Asia/Kolkata', 'Дели, Мумбаи (IST, UTC+5:30)'),
                ('Asia/Kathmandu', 'Катманду (NPT, UTC+5:45)'),
                ('Asia/Dhaka', 'Дакка (BST, UTC+6)'),
                ('Asia/Bangkok', 'Бангкок, Ханой, Джакарта (ICT, UTC+7)'),
                ('Asia/Singapore', 'Сингапур, Куала-Лумпур (SGT, UTC+8)'),
                ('Asia/Hong_Kong', 'Гонконг (HKT, UTC+8)'),
                ('Asia/Shanghai', 'Пекин, Шанхай (CST, UTC+8)'),
                ('Asia/Seoul', 'Сеул (KST, UTC+9)'),
                ('Asia/Tokyo', 'Токио (JST, UTC+9)'),
            ]
        },
        {
            'group': 'Америка',
            'zones': [
                ('America/New_York', 'Нью-Йорк, Вашингтон, Майами (Eastern)'),
                ('America/Chicago', 'Чикаго, Хьюстон, Даллас (Central)'),
                ('America/Denver', 'Денвер, Солт-Лейк-Сити (Mountain)'),
                ('America/Phoenix', 'Феникс, Аризона (MST, без DST)'),
                ('America/Los_Angeles', 'Лос-Анджелес, Сан-Франциско, Сиэтл (Pacific)'),
                ('America/Anchorage', 'Анкоридж, Аляска (AKST/AKDT)'),
                ('Pacific/Honolulu', 'Гонолулу, Гавайи (HST, UTC-10)'),
                ('America/Toronto', 'Торонто, Монреаль (Канада)'),
                ('America/Vancouver', 'Ванкувер (Канада)'),
                ('America/St_Johns', 'Сент-Джонс, Ньюфаундленд (NST/NDT, UTC-3:30 / UTC-2:30)'),
                ('America/Mexico_City', 'Мехико (Мексика)'),
                ('America/Bogota', 'Богота, Лима (UTC-5)'),
                ('America/Sao_Paulo', 'Сан-Паулу, Рио-де-Жанейро (BRT, UTC-3)'),
                ('America/Buenos_Aires', 'Буэнос-Айрес (ART, UTC-3)'),
                ('America/Santiago', 'Сантьяго (Чили)'),
            ]
        },
        {
            'group': 'Австралия и Океания',
            'zones': [
                ('Australia/Perth', 'Перт (AWST, UTC+8)'),
                ('Australia/Darwin', 'Дарвин (ACST, UTC+9:30)'),
                ('Australia/Adelaide', 'Аделаида (ACST/ACDT, UTC+9:30 / UTC+10:30)'),
                ('Australia/Brisbane', 'Брисбен (AEST, UTC+10)'),
                ('Australia/Sydney', 'Сидней, Мельбурн, Канберра (AEST/AEDT, UTC+10 / UTC+11)'),
                ('Pacific/Auckland', 'Окленд, Веллингтон (NZST/NZDT, UTC+12 / UTC+13)'),
                ('Pacific/Fiji', 'Фиджи (FJT, UTC+12)'),
            ]
        },
        {
            'group': 'Африка и UTC',
            'zones': [
                ('UTC', 'UTC (Всемирное координированное время)'),
                ('Africa/Cairo', 'Каир (EET/EEST, UTC+2 / UTC+3)'),
                ('Africa/Johannesburg', 'Йоханнесбург, Кейптаун (SAST, UTC+2)'),
                ('Africa/Nairobi', 'Найроби, Аддис-Абеба (EAT, UTC+3)'),
                ('Africa/Lagos', 'Лагос (WAT, UTC+1)'),
                ('Africa/Casablanca', 'Касабланка (WET/WEST)'),
            ]
        }
    ]

    result: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for g in groups:
        g_zones = []
        for tz_key, label in g['zones']:
            if tz_key not in seen_keys and is_valid_timezone(tz_key):
                seen_keys.add(tz_key)
                offset = _offset_label(tz_key)
                g_zones.append({
                    'key': tz_key,
                    'label': label,
                    'offset': offset,
                    'full_label': f"{label} ({offset})"
                })
        if g_zones:
            result.append({'group': g['group'], 'zones': g_zones})

    return result
