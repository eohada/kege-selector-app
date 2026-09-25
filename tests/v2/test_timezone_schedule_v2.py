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


def test_schedule_timezone_clean_extraction_and_test_layer(app, client, role_users):
    from app import db
    from app.models import Lesson, Student
    from app.schedule.routes import _extract_clean_lesson_datetime, _is_lesson_test

    # 1. Clean datetime extraction across timezones
    # 2026-09-25 15:30 in Europe/Moscow (UTC+3) -> 12:30 UTC
    clean_msk = _extract_clean_lesson_datetime('2026-09-25', '15:30', 'Europe/Moscow')
    assert clean_msk.tzinfo is not None
    assert clean_msk.astimezone(timezone.utc).hour == 12
    assert clean_msk.astimezone(timezone.utc).minute == 30

    # 2026-09-25 15:30 in Asia/Tomsk (UTC+7) -> 08:30 UTC
    clean_tomsk = _extract_clean_lesson_datetime('2026-09-25', '15:30', 'Asia/Tomsk')
    assert clean_tomsk.astimezone(timezone.utc).hour == 8
    assert clean_tomsk.astimezone(timezone.utc).minute == 30

    # 2. Heuristic detection of test lessons
    l_test_topic = Lesson(topic='тест времени', lesson_type='individual')
    assert _is_lesson_test(l_test_topic) is True

    l_test_type = Lesson(topic='Информатика №24', lesson_type='test')
    assert _is_lesson_test(l_test_type) is True

    l_test_note = Lesson(topic='Обычный урок', notes='__TEST__ debug info', lesson_type='individual')
    assert _is_lesson_test(l_test_note) is True

    l_regular = Lesson(topic='Разбор задания 27', lesson_type='individual', notes='Домашнее задание')
    assert _is_lesson_test(l_regular) is False

    # 3. Create lesson API with timezone & is_test flag
    login_as(client, role_users['tutor_id'], 'tutor')

    res_create = client.post('/api/schedule/create_lesson', json={
        'student_id': role_users['student_id'],
        'lesson_date': '2026-09-25',
        'time': '16:00',
        'duration': 60,
        'topic': 'Тестовый урок 1',
        'is_test': True,
        'timezone': 'Europe/Moscow'
    })
    assert res_create.status_code == 200
    res_data = res_create.get_json()
    assert res_data['status'] == 'success'
    lesson_id = res_data['lesson_id']

    with app.app_context():
        created_lesson = db.session.get(Lesson, lesson_id)
        assert created_lesson is not None
        assert _is_lesson_test(created_lesson) is True
        assert created_lesson.lesson_type == 'test'
        # In UTC: 16:00 MSK (UTC+3) -> 13:00 UTC
        utc_dt = created_lesson.lesson_date.astimezone(timezone.utc) if created_lesson.lesson_date.tzinfo else created_lesson.lesson_date.replace(tzinfo=timezone.utc)
        assert utc_dt.hour == 13

    # 4. Toggle test lesson API
    res_toggle = client.post(f'/api/schedule/lesson/{lesson_id}/toggle_test')
    assert res_toggle.status_code == 200
    data = res_toggle.get_json()
    assert data['is_test'] is False
    assert data['lesson_type'] == 'individual'

    with app.app_context():
        updated_lesson = db.session.get(Lesson, lesson_id)
        assert _is_lesson_test(updated_lesson) is False


def test_schedule_update_and_bulk_delete(app, client, role_users):
    from app import db
    from app.models import Lesson
    from app.schedule.routes import _is_lesson_test

    login_as(client, role_users['tutor_id'], 'tutor')

    # 1. Create two test lessons and one regular lesson
    res1 = client.post('/api/schedule/create_lesson', json={
        'student_id': role_users['student_id'],
        'lesson_date': '2026-09-26',
        'time': '10:00',
        'duration': 60,
        'topic': 'Тест для удаления 1',
        'is_test': True,
        'timezone': 'Europe/Moscow'
    })
    assert res1.status_code == 200
    id1 = res1.get_json()['lesson_id']

    res2 = client.post('/api/schedule/create_lesson', json={
        'student_id': role_users['student_id'],
        'lesson_date': '2026-09-26',
        'time': '11:00',
        'duration': 60,
        'topic': 'Тест для удаления 2',
        'is_test': True,
        'timezone': 'Europe/Moscow'
    })
    assert res2.status_code == 200
    id2 = res2.get_json()['lesson_id']

    res3 = client.post('/api/schedule/create_lesson', json={
        'student_id': role_users['student_id'],
        'lesson_date': '2026-09-26',
        'time': '12:00',
        'duration': 60,
        'topic': 'Обычный урок математики',
        'is_test': False,
        'timezone': 'Europe/Moscow'
    })
    assert res3.status_code == 200
    id3 = res3.get_json()['lesson_id']

    # 2. Smooth update test: update topic and duration on id3
    res_update = client.post(f'/api/schedule/update_lesson/{id3}', json={
        'student_id': role_users['student_id'],
        'topic': 'Обновлённый урок математики',
        'duration': 90,
        'status': 'completed',
        'notes': 'Разобрали стереометрию'
    })
    assert res_update.status_code == 200
    upd_data = res_update.get_json()
    assert upd_data['status'] == 'success'
    assert 'lesson' in upd_data
    assert upd_data['lesson']['topic'] == 'Обновлённый урок математики'
    assert upd_data['lesson']['duration_minutes'] == 90
    assert upd_data['lesson']['status'] == 'completed'

    with app.app_context():
        l3 = db.session.get(Lesson, id3)
        assert l3.topic == 'Обновлённый урок математики'
        assert l3.duration == 90
        assert l3.status == 'completed'

    # 3. Bulk delete by IDs: delete id1
    res_bulk_ids = client.post('/api/schedule/bulk_delete_lessons', json={
        'lesson_ids': [id1]
    })
    assert res_bulk_ids.status_code == 200
    b_data = res_bulk_ids.get_json()
    assert b_data['status'] == 'success'
    assert b_data['deleted_count'] == 1
    assert id1 in b_data['deleted_ids']

    with app.app_context():
        assert db.session.get(Lesson, id1) is None
        assert db.session.get(Lesson, id2) is not None

    # 4. Bulk delete all tests: delete_all_test=True should delete id2
    res_bulk_test = client.post('/api/schedule/bulk_delete_lessons', json={
        'delete_all_test': True
    })
    assert res_bulk_test.status_code == 200
    bt_data = res_bulk_test.get_json()
    assert bt_data['status'] == 'success'
    assert id2 in bt_data['deleted_ids']

    with app.app_context():
        assert db.session.get(Lesson, id2) is None
        # regular lesson id3 remains untouched
        assert db.session.get(Lesson, id3) is not None

    # 5. Single delete test: delete id3
    res_single_del = client.post(f'/api/schedule/delete_lesson/{id3}')
    assert res_single_del.status_code == 200
    with app.app_context():
        assert db.session.get(Lesson, id3) is None


def test_schedule_delete_with_complex_dependencies(app, client, role_users):
    """Проверка чистого каскадного удаления уроков с зависимостями (LessonTask, Whiteboard, Outcome, etc.)."""
    from app import db
    from app.models import (
        Lesson, Tasks, LessonTask, LessonTaskTeacherComment, LessonTaskAttempt,
        LessonWhiteboard, LessonOutcome, PendingAssignmentNotification,
        LessonMessage, LessonTeacherHomeworkNote, LearningError, moscow_now
    )

    login_as(client, role_users['tutor_id'], 'tutor')

    # Создаем урок
    res = client.post('/api/schedule/create_lesson', json={
        'student_id': role_users['student_id'],
        'lesson_date': '2026-09-28',
        'time': '15:00',
        'duration': 60,
        'topic': 'Урок со сложными зависимостями',
        'is_test': False,
        'timezone': 'Europe/Moscow'
    })
    assert res.status_code == 200
    lid = res.get_json()['lesson_id']

    # Навешиваем все типы зависимостей
    with app.app_context():
        task = Tasks(task_number=1, content_html='<p>Задание 1</p>')
        db.session.add(task)
        db.session.commit()

        lt = LessonTask(lesson_id=lid, task_id=task.task_id)
        db.session.add(lt)
        db.session.commit()

        comm = LessonTaskTeacherComment(lesson_task_id=lt.lesson_task_id, body='Отличная попытка')
        att = LessonTaskAttempt(lesson_task_id=lt.lesson_task_id, student_submission='42')
        wb = LessonWhiteboard(lesson_id=lid, miro_board_id='miro-board-test-123')
        outc = LessonOutcome(lesson_id=lid, mastery='high')
        pan = PendingAssignmentNotification(lesson_id=lid, student_id=role_users['student_id'], assignment_type='homework')
        msg = LessonMessage(lesson_id=lid, author_user_id=role_users['tutor_id'], body='Урок начнётся вовремя')
        note = LessonTeacherHomeworkNote(lesson_id=lid, teacher_user_id=role_users['tutor_id'], homework_text='Задать ДЗ', remind_at=moscow_now())
        err = LearningError(student_id=role_users['student_id'], lesson_id=lid, error_type='арифметика')

        db.session.add_all([comm, att, wb, outc, pan, msg, note, err])
        db.session.commit()
        err_id = err.error_id

        # Проверяем, что зависимости созданы
        assert db.session.get(LessonWhiteboard, wb.id) is not None
        assert db.session.get(LessonOutcome, outc.outcome_id) is not None

    # Массовое удаление через bulk_delete_lessons
    res_del = client.post('/api/schedule/bulk_delete_lessons', json={
        'lesson_ids': [lid]
    })
    assert res_del.status_code == 200
    del_data = res_del.get_json()
    assert del_data['status'] == 'success'
    assert lid in del_data['deleted_ids']

    # Проверяем полное очищение в базе данных
    with app.app_context():
        assert db.session.get(Lesson, lid) is None
        assert LessonWhiteboard.query.filter_by(lesson_id=lid).first() is None
        assert LessonOutcome.query.filter_by(lesson_id=lid).first() is None
        assert LessonTask.query.filter_by(lesson_id=lid).first() is None
        assert LessonTaskTeacherComment.query.filter_by(body='Отличная попытка').first() is None
        assert LessonTaskAttempt.query.filter_by(student_submission='42').first() is None
        assert PendingAssignmentNotification.query.filter_by(lesson_id=lid).first() is None
        assert LessonMessage.query.filter_by(lesson_id=lid).first() is None
        assert LessonTeacherHomeworkNote.query.filter_by(lesson_id=lid).first() is None
        # LearningError не удаляется, но его lesson_id сбрасывается в None
        remaining_err = db.session.get(LearningError, err_id)
        assert remaining_err is not None
        assert remaining_err.lesson_id is None


def test_create_schedule_lesson_with_null_lesson_date_and_various_date_formats(app, client, role_users):
    """Проверка создания урока, когда в БД есть уроки с lesson_date=None, и поддержка форматов даты."""
    from app import db
    from app.models import Lesson

    # Создаём урок без даты (lesson_date=None)
    with app.app_context():
        null_date_lesson = Lesson(
            student_id=role_users['student_id'],
            lesson_date=None,
            topic='Урок-черновик без даты',
            duration=60,
            status='planned'
        )
        db.session.add(null_date_lesson)
        db.session.commit()

    login_as(client, role_users['tutor_id'], 'tutor')

    # Создание урока в формате YYYY-MM-DD не должно падать на NoneType + timedelta
    res1 = client.post('/api/schedule/create_lesson', json={
        'student_id': role_users['student_id'],
        'lesson_date': '2026-09-28',
        'time': '15:00',
        'duration': 60,
        'topic': 'Урок после фикса None lesson_date',
        'timezone': 'Europe/Moscow'
    })
    assert res1.status_code == 200, res1.get_data(as_text=True)
    data1 = res1.get_json()
    assert data1['status'] == 'success'
    created_id = data1['lesson_id']

    # Создание урока в формате DD.MM.YYYY также должно корректно парситься
    res2 = client.post('/api/schedule/create_lesson', json={
        'student_id': role_users['student_id'],
        'lesson_date': '28.09.2026',
        'time': '17:00',
        'duration': 60,
        'topic': 'Урок с датой в формате DD.MM.YYYY',
        'timezone': 'Europe/Moscow'
    })
    assert res2.status_code == 200, res2.get_data(as_text=True)
    data2 = res2.get_json()
    assert data2['status'] == 'success'

    # Проверка, что реальное пересечение по времени по-прежнему отлавливается
    res_overlap = client.post('/api/schedule/create_lesson', json={
        'student_id': role_users['student_id'],
        'lesson_date': '2026-09-28',
        'time': '15:30',
        'duration': 60,
        'topic': 'Пересекающийся урок',
        'timezone': 'Europe/Moscow'
    })
    assert res_overlap.status_code == 409
    assert 'пересекающийся урок' in res_overlap.get_json()['message']



