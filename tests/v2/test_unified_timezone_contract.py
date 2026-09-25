import pytest
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from app.utils.timezone import (
    UTC,
    LEGACY_TIMEZONE_NAME,
    is_valid_timezone,
    canonical_timezone_name,
    get_timezone,
    parse_local_to_utc,
    to_utc_instant,
    format_utc_iso_z,
    to_viewer_tz,
    format_viewer_dt,
    get_schedule_week_bounds,
)
from tests.v2.conftest import login_as


def test_timezone_normalization_and_validation():
    # Canonical IANA zones
    assert is_valid_timezone('Europe/Moscow') is True
    assert is_valid_timezone('Asia/Tomsk') is True
    assert is_valid_timezone('Asia/Kathmandu') is True
    assert is_valid_timezone('Australia/Adelaide') is True
    assert is_valid_timezone('America/St_Johns') is True
    assert is_valid_timezone('UTC') is True

    # Invalid names
    assert is_valid_timezone('Fake/Timezone') is False
    assert is_valid_timezone('') is False
    assert is_valid_timezone(None) is False

    # Aliases and normalization
    assert canonical_timezone_name('moscow') == 'Europe/Moscow'
    assert canonical_timezone_name('tomsk') == 'Asia/Tomsk'
    assert canonical_timezone_name('Europe/Moscow') == 'Europe/Moscow'
    assert canonical_timezone_name('invalid_string') == 'Europe/Moscow'
    assert canonical_timezone_name(None) == 'Europe/Moscow'


def test_parse_local_to_utc_matrix():
    # Moscow (UTC+3) 18:00 -> 15:00 UTC
    msk = parse_local_to_utc('2026-10-15', '18:00', 'Europe/Moscow')
    assert msk == datetime(2026, 10, 15, 15, 0, tzinfo=UTC)

    # Kaliningrad (UTC+2) 18:00 -> 16:00 UTC
    kln = parse_local_to_utc('2026-10-15', '18:00', 'Europe/Kaliningrad')
    assert kln == datetime(2026, 10, 15, 16, 0, tzinfo=UTC)

    # Yekaterinburg (UTC+5) 18:00 -> 13:00 UTC
    ykt = parse_local_to_utc('2026-10-15', '18:00', 'Asia/Yekaterinburg')
    assert ykt == datetime(2026, 10, 15, 13, 0, tzinfo=UTC)

    # Tomsk (UTC+7) 18:00 -> 11:00 UTC
    tsk = parse_local_to_utc('2026-10-15', '18:00', 'Asia/Tomsk')
    assert tsk == datetime(2026, 10, 15, 11, 0, tzinfo=UTC)

    # Vladivostok (UTC+10) 18:00 -> 08:00 UTC
    vld = parse_local_to_utc('2026-10-15', '18:00', 'Asia/Vladivostok')
    assert vld == datetime(2026, 10, 15, 8, 0, tzinfo=UTC)

    # Kathmandu (UTC+5:45) 18:00 -> 12:15 UTC
    ktm = parse_local_to_utc('2026-10-15', '18:00', 'Asia/Kathmandu')
    assert ktm == datetime(2026, 10, 15, 12, 15, tzinfo=UTC)

    # Adelaide DST (Australia/Adelaide is UTC+10:30 in October / southern hemisphere summer)
    adl = parse_local_to_utc('2026-10-15', '18:00', 'Australia/Adelaide')
    assert adl == datetime(2026, 10, 15, 7, 30, tzinfo=UTC)

    # St. John's (America/St_Johns is UTC-2:30 during daylight saving in October)
    stj = parse_local_to_utc('2026-10-15', '18:00', 'America/St_Johns')
    assert stj == datetime(2026, 10, 15, 20, 30, tzinfo=UTC)


def test_utc_instant_round_trip():
    # Teacher in Moscow creates lesson for 18:00
    utc_instant = parse_local_to_utc('2026-10-15', '18:00', 'Europe/Moscow')
    iso_z = format_utc_iso_z(utc_instant)
    assert iso_z == '2026-10-15T15:00:00Z'

    # Viewer 1: Moscow
    assert format_viewer_dt(iso_z, 'Europe/Moscow', '%H:%M') == '18:00'
    assert format_viewer_dt(iso_z, 'Europe/Moscow', '%Y-%m-%d') == '2026-10-15'

    # Viewer 2: Kaliningrad (UTC+2) -> 17:00
    assert format_viewer_dt(iso_z, 'Europe/Kaliningrad', '%H:%M') == '17:00'

    # Viewer 3: Yekaterinburg (UTC+5) -> 20:00
    assert format_viewer_dt(iso_z, 'Asia/Yekaterinburg', '%H:%M') == '20:00'

    # Viewer 4: Tomsk (UTC+7) -> 22:00
    assert format_viewer_dt(iso_z, 'Asia/Tomsk', '%H:%M') == '22:00'

    # Viewer 5: Vladivostok (UTC+10) -> 01:00 next day
    assert format_viewer_dt(iso_z, 'Asia/Vladivostok', '%H:%M') == '01:00'
    assert format_viewer_dt(iso_z, 'Asia/Vladivostok', '%Y-%m-%d') == '2026-10-16'

    # Viewer 6: Kathmandu (UTC+5:45) -> 20:45
    assert format_viewer_dt(iso_z, 'Asia/Kathmandu', '%H:%M') == '20:45'


def test_schedule_week_bounds_in_viewer_timezone():
    # Instant: 2026-10-18 22:00:00 UTC (Sunday night in UTC)
    # In Moscow (UTC+3): 2026-10-19 01:00:00 (Monday morning!)
    instant = datetime(2026, 10, 18, 22, 0, tzinfo=UTC)

    # In UTC, 2026-10-18 is Sunday, belonging to week starting Monday 2026-10-12
    bounds_utc = get_schedule_week_bounds(instant, 0, viewer_tz='UTC')
    assert bounds_utc['week_start'].strftime('%Y-%m-%d') == '2026-10-12'

    # In Moscow, 2026-10-19 is Monday, belonging to week starting Monday 2026-10-19
    bounds_msk = get_schedule_week_bounds(instant, 0, viewer_tz='Europe/Moscow')
    assert bounds_msk['week_start'].strftime('%Y-%m-%d') == '2026-10-19'


def test_create_lesson_api_accepts_start_time_utc(app, client, role_users):
    from app import db
    from app.models import Lesson

    login_as(client, role_users['tutor_id'], 'tutor')

    payload = {
        'student_id': role_users['student_id'],
        'start_time_utc': '2026-10-25T15:00:00Z',
        'lesson_date': '2026-10-25',
        'time': '18:00',
        'duration': 60,
        'topic': 'UTC ISO Test Lesson',
        'status': 'planned',
        'timezone': 'Europe/Moscow',
    }

    res = client.post('/api/schedule/create_lesson', json=payload)
    assert res.status_code == 200
    data = res.get_json()
    assert data['status'] == 'success'
    lesson_id = data['lesson_id']

    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        assert lesson is not None
        utc_dt = to_utc_instant(lesson.lesson_date)
        assert utc_dt == datetime(2026, 10, 25, 15, 0, tzinfo=UTC)
        msk_dt = to_viewer_tz(utc_dt, 'Europe/Moscow')
        assert msk_dt.strftime('%H:%M') == '18:00'


def test_create_lesson_api_local_conversion_fallback(app, client, role_users):
    from app import db
    from app.models import Lesson

    login_as(client, role_users['tutor_id'], 'tutor')

    payload = {
        'student_id': role_users['student_id'],
        'lesson_date': '2026-10-26',
        'time': '18:00',
        'duration': 60,
        'topic': 'Local Conversion Test Lesson',
        'status': 'planned',
        'timezone': 'Europe/Moscow',
    }

    res = client.post('/api/schedule/create_lesson', json=payload)
    assert res.status_code == 200
    lesson_id = res.get_json()['lesson_id']

    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        utc_dt = to_utc_instant(lesson.lesson_date)
        assert utc_dt == datetime(2026, 10, 26, 15, 0, tzinfo=UTC)
        msk_dt = to_viewer_tz(utc_dt, 'Europe/Moscow')
        assert msk_dt.strftime('%H:%M') == '18:00'


def test_profile_timezone_update_and_validation(app, client, role_users):
    from app import db
    from app.models import User, UserProfile

    with app.app_context():
        # Ensure student has profile
        st_user = db.session.get(User, role_users['student_user_id'])
        if not st_user.profile:
            st_user.profile = UserProfile(user_id=st_user.id)
            db.session.commit()

    login_as(client, role_users['student_user_id'], 'student')

    # 1. Valid IANA timezone
    res = client.post('/api/profile/edit', json={
        'timezone': 'Asia/Vladivostok',
        'first_name': 'Тест',
        'last_name': 'Учеников',
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['timezone'] == 'Asia/Vladivostok'

    with app.app_context():
        user = db.session.get(User, role_users['student_user_id'])
        assert user.profile.timezone == 'Asia/Vladivostok'

    # 2. Invalid timezone should be rejected
    res_bad = client.post('/api/profile/edit', json={
        'timezone': 'Invalid/Timezone_Name_123',
    })
    assert res_bad.status_code == 400
    assert 'Некорректный часовой пояс' in res_bad.get_json()['error']


def test_assignment_deadline_utc_and_blocks(app, client, role_users):
    from app import db
    from app.models import Assignment
    from app.assignments.routes import _submission_deadline_passed

    with app.app_context():
        # Assignment with deadline in past
        past_dl = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        a_past = Assignment(
            title='Past Assignment',
            assignment_type='homework',
            deadline=past_dl,
            hard_deadline=True,
            created_by_id=role_users['tutor_id'],
        )
        # Assignment with deadline in future
        future_dl = datetime(2026, 12, 31, 12, 0, tzinfo=UTC)
        a_future = Assignment(
            title='Future Assignment',
            assignment_type='homework',
            deadline=future_dl,
            hard_deadline=True,
            created_by_id=role_users['tutor_id'],
        )
        db.session.add_all([a_past, a_future])
        db.session.commit()

        ref_now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        assert _submission_deadline_passed(a_past, now=ref_now) is True
        assert _submission_deadline_passed(a_future, now=ref_now) is False
