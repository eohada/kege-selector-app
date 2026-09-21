import pytest
from datetime import datetime, timezone
from tests.v2.test_role_lifecycle_recovery import login_as


def _lifecycle_fixture(app, role_users, *, status='planned', initial_balance=5):
    from app import db
    from app.models import Lesson, Student

    with app.app_context():
        student = Student.query.get(role_users['student_id'])
        student.lessons_balance = initial_balance

        lesson = Lesson(
            student_id=student.student_id,
            lesson_date=datetime.now(timezone.utc),
            duration=60,
            status=status,
            topic='Тестовый урок жизненного цикла',
        )
        db.session.add(lesson)
        db.session.commit()
        return lesson.lesson_id, student.student_id


def test_lesson_lifecycle_waiting_room_and_start(app, client, role_users):
    lesson_id, student_id = _lifecycle_fixture(app, role_users, status='planned', initial_balance=3)

    # 1. Студент заходит на запланированный урок -> попадает в комнату ожидания
    login_as(client, role_users['student_user_id'], 'student')
    resp = client.get(f'/lesson/{lesson_id}/room')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'Комната ожидания урока' in html
    assert 'Ожидаем сигнал преподавателя' in html
    assert 'Запланирован' in html
    assert 'lesson-studio-os' not in html

    # 2. Студент опрашивает статус урока -> status=planned, is_live=False
    status_resp = client.get(f'/lesson/{lesson_id}/status')
    assert status_resp.status_code == 200
    status_data = status_resp.get_json()
    assert status_data['success'] is True
    assert status_data['status'] == 'planned'
    assert status_data['is_live'] is False

    # 3. Студент не может самовольно начать урок
    start_attempt = client.post(f'/lesson/{lesson_id}/start', json={})
    assert start_attempt.status_code == 403

    # 4. Преподаватель открывает комнату -> видит кнопку "Начать урок"
    login_as(client, role_users['tutor_id'], 'tutor')
    tutor_room = client.get(f'/lesson/{lesson_id}/room')
    assert tutor_room.status_code == 200
    tutor_html = tutor_room.get_data(as_text=True)
    assert 'os-start-lesson' in tutor_html
    assert 'Начать урок' in tutor_html

    # 5. Преподаватель начинает урок через API
    start_resp = client.post(f'/lesson/{lesson_id}/start', json={})
    assert start_resp.status_code == 200
    start_data = start_resp.get_json()
    assert start_data['success'] is True
    assert start_data['status'] == 'in_progress'

    # 6. Студент опрашивает статус -> is_live=True
    login_as(client, role_users['student_user_id'], 'student')
    status_resp_after = client.get(f'/lesson/{lesson_id}/status')
    assert status_resp_after.status_code == 200
    assert status_resp_after.get_json()['status'] == 'in_progress'
    assert status_resp_after.get_json()['is_live'] is True

    # 7. Студент теперь заходит в живую комнату
    live_room = client.get(f'/lesson/{lesson_id}/room')
    assert live_room.status_code == 200
    live_html = live_room.get_data(as_text=True)
    assert 'Комната ожидания урока' not in live_html
    assert 'lesson-studio-os' in live_html


def test_lesson_completion_deducts_balance_idempotently(app, client, role_users):
    from app.models import Lesson, Student

    lesson_id, student_id = _lifecycle_fixture(app, role_users, status='in_progress', initial_balance=5)

    # Завершаем урок со стороны преподавателя
    login_as(client, role_users['tutor_id'], 'tutor')
    finish_resp = client.post(
        f'/lesson/{lesson_id}/studio/finish',
        json={
            'outcome': {
                'completed': ['Тема пройдена успешно'],
                'repeat': [],
                'homework': 'Сделать номера 1-5'
            }
        }
    )
    assert finish_resp.status_code == 200
    assert finish_resp.get_json()['success'] is True

    with app.app_context():
        lesson = Lesson.query.get(lesson_id)
        student = Student.query.get(student_id)
        assert lesson.status == 'completed'
        assert lesson.balance_deducted is True
        # Было 5, длительность 60 мин (1 юнит) -> стало 4
        assert student.lessons_balance == 4

    # Повторный вызов finish не должен повторно списывать баланс
    finish_again = client.post(
        f'/lesson/{lesson_id}/studio/finish',
        json={
            'outcome': {
                'completed': ['Повторное сохранение итогов'],
            }
        }
    )
    assert finish_again.status_code == 200

    with app.app_context():
        student = Student.query.get(student_id)
        assert student.lessons_balance == 4


def test_lesson_complete_route_deducts_balance(app, client, role_users):
    from app.models import Lesson, Student

    lesson_id, student_id = _lifecycle_fixture(app, role_users, status='in_progress', initial_balance=10)

    login_as(client, role_users['tutor_id'], 'tutor')
    complete_resp = client.post(
        f'/lesson/{lesson_id}/complete',
        data={
            'topic': 'Завершённый урок',
            'notes': 'Итоги',
            'homework': 'ДЗ',
        }
    )
    assert complete_resp.status_code in (200, 302)

    with app.app_context():
        lesson = Lesson.query.get(lesson_id)
        student = Student.query.get(student_id)
        assert lesson.status == 'completed'
        assert lesson.balance_deducted is True
        assert student.lessons_balance == 9
