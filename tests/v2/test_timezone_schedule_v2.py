from datetime import datetime, timezone

from tests.v2.conftest import login_as


def test_lesson_time_uses_utc_storage_and_iana_display():
    from app.utils.lesson_time import lesson_storage_to_local, parse_local_lesson_datetime

    # 14:00 в Красноярске (UTC+7) = 10:00 в Москве.
    stored = parse_local_lesson_datetime('2026-08-20', '14:00', 'Asia/Krasnoyarsk')
    assert stored == datetime(2026, 8, 20, 7, 0, tzinfo=timezone.utc)
    assert lesson_storage_to_local(stored, 'Europe/Moscow').strftime('%H:%M') == '10:00'
    assert lesson_storage_to_local(stored, 'Asia/Yekaterinburg').strftime('%H:%M') == '12:00'
    assert lesson_storage_to_local(stored, 'Asia/Yakutsk').strftime('%H:%M') == '16:00'


def test_student_schedule_api_never_expands_scope_with_view_all(app, client, role_users):
    from app import db
    from app.models import Lesson, Student, User

    with app.app_context():
        other_user = User(
            username='other_schedule_student',
            email='other_schedule_student@example.test',
            role='student',
            is_active=True,
        )
        db.session.add(other_user)
        db.session.flush()
        other_student = Student(name='Чужой ученик', user_id=other_user.id, is_active=True)
        own_student = db.session.get(Student, role_users['student_id'])
        own_student.name = 'Свой ученик'
        db.session.add_all([
            other_student,
            Lesson(
                student_id=own_student.student_id,
                lesson_date=datetime(2026, 8, 20, 7, 0, tzinfo=timezone.utc),
                duration=60,
                status='planned',
                topic='Свой урок',
            ),
        ])
        db.session.flush()
        db.session.add(Lesson(
            student_id=other_student.student_id,
            lesson_date=datetime(2026, 8, 20, 8, 0, tzinfo=timezone.utc),
            duration=60,
            status='planned',
            topic='Чужой урок',
        ))
        db.session.commit()

    login_as(client, role_users['student_user_id'], 'student')
    response = client.get('/schedule/api/events?start=2026-08-20&end=2026-08-20&view=all')

    assert response.status_code == 200
    events = response.get_json()['events']
    assert [event['topic'] for event in events] == ['Свой урок']


def test_manual_timezone_persists_in_user_and_profile(app, client, role_users):
    from app import db
    from app.models import User, UserProfile

    with app.app_context():
        user = db.session.get(User, role_users['student_user_id'])
        db.session.add(UserProfile(user_id=user.id, timezone='Europe/Moscow'))
        db.session.commit()

    login_as(client, role_users['student_user_id'], 'student')
    response = client.post('/api/me/timezone', json={
        'timezone_mode': 'manual',
        'timezone_iana': 'Asia/Tomsk',
    })

    assert response.status_code == 200
    assert response.get_json()['effective'] == 'Asia/Tomsk'
    with app.app_context():
        user = db.session.get(User, role_users['student_user_id'])
        profile = UserProfile.query.filter_by(user_id=user.id).one()
        assert user.timezone_mode == 'manual'
        assert user.timezone_iana == 'Asia/Tomsk'
        assert profile.timezone == 'Asia/Tomsk'


def test_course_entrypoints_are_visible_to_student_and_tutor(client, role_users):
    login_as(client, role_users['student_user_id'], 'student')
    student_dashboard = client.get('/dashboard')
    assert student_dashboard.status_code == 200
    assert 'Программа обучения'.encode() in student_dashboard.data
    assert f'/student/{role_users["student_id"]}/courses'.encode() in student_dashboard.data

    login_as(client, role_users['tutor_id'], 'tutor')
    teacher_dashboard = client.get(f'/student/{role_users["student_id"]}/dashboard')
    assert teacher_dashboard.status_code == 200
    assert 'Программа обучения'.encode() in teacher_dashboard.data
    assert f'/student/{role_users["student_id"]}/courses'.encode() in teacher_dashboard.data
