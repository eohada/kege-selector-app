"""
Tests for Telegram Sprint #1:
- Role detection for 'teacher', 'mentor', 'admin'
- Data isolation for student assignments and teacher review queue
- Production token protection and dev token enforcement in run_bot
- Profile link code generation endpoint aliases
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from app.models import User, UserProfile, Assignment, Submission, Student


def test_role_detection_teacher_mentor_admin():
    from app.telegram.handlers import _is_teacher, _has_access_role

    assert _is_teacher('teacher') is True
    assert _is_teacher('mentor') is True
    assert _is_teacher('tutor') is True
    assert _is_teacher('admin') is True
    assert _is_teacher('creator') is True
    assert _is_teacher('student') is False
    assert _is_teacher('parent') is False

    assert _has_access_role('teacher') is True
    assert _has_access_role('mentor') is True
    assert _has_access_role('tutor') is True
    assert _has_access_role('admin') is True
    assert _has_access_role('creator') is True
    assert _has_access_role('student') is True
    assert _has_access_role('parent') is True
    assert _has_access_role('guest') is False


def test_api_telegram_generate_auth_code_delegation(client, app):
    with app.app_context():
        from app import db
        user = User(
            username='auth_code_user_test',
            email='auth_code@boostudy.test',
            role='student',
            is_active=True,
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True

    response = client.post('/api/telegram/generate_auth_code')
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    assert data['code'].startswith('BS-')
    assert data['expires_in_minutes'] == 15
    assert 'instructions' in data
    assert data['code'] in data['instructions']


def test_telegram_bot_username_resolution(monkeypatch):
    from app.api.routes import _telegram_bot_username

    monkeypatch.setenv('ENVIRONMENT', 'local')
    monkeypatch.setenv('TELEGRAM_DEV_BOT_USERNAME', '@DevTestBot')
    monkeypatch.setenv('TELEGRAM_BOT_USERNAME', '@ProdBot')
    assert _telegram_bot_username() == 'DevTestBot'

    monkeypatch.delenv('TELEGRAM_DEV_BOT_USERNAME', raising=False)
    assert _telegram_bot_username() == 'ProdBot'


def test_run_bot_rejects_empty_dev_token(monkeypatch):
    import run_bot
    monkeypatch.delenv('TELEGRAM_DEV_BOT_TOKEN', raising=False)
    monkeypatch.delenv('TELEGRAM_BOT_TOKEN', raising=False)
    monkeypatch.delenv('MAIN_BOT_TOKEN', raising=False)

    with pytest.raises(SystemExit) as exc:
        run_bot.run()
    assert exc.value.code == 1


def test_run_bot_rejects_prod_token(monkeypatch):
    import run_bot
    monkeypatch.setenv('TELEGRAM_DEV_BOT_TOKEN', '8581074364:fake_production_secret')

    with pytest.raises(SystemExit) as exc:
        run_bot.run()
    assert exc.value.code == 1


def test_student_assignments_data_isolation(app):
    """Student A must never see Student B's assignments."""
    from app.telegram.application import build_student_assignments

    with app.app_context():
        from app import db
        student_user_a = User(username='student_a', email='a@boostudy.test', role='student', is_active=True)
        student_user_b = User(username='student_b', email='b@boostudy.test', role='student', is_active=True)
        db.session.add_all([student_user_a, student_user_b])
        db.session.flush()

        st_record_a = Student(user_id=student_user_a.id, name='Student A', is_active=True)
        st_record_b = Student(user_id=student_user_b.id, name='Student B', is_active=True)
        db.session.add_all([st_record_a, st_record_b])
        db.session.flush()

        due = datetime.now(timezone.utc) + timedelta(days=2)
        asg_a = Assignment(title='Math Homework A', assignment_type='homework', created_by_id=student_user_a.id, deadline=due, is_active=True)
        asg_b = Assignment(title='Physics Homework B', assignment_type='homework', created_by_id=student_user_b.id, deadline=due, is_active=True)
        db.session.add_all([asg_a, asg_b])
        db.session.flush()

        sub_a = Submission(assignment_id=asg_a.assignment_id, student_id=st_record_a.student_id, status='ASSIGNED')
        sub_b = Submission(assignment_id=asg_b.assignment_id, student_id=st_record_b.student_id, status='ASSIGNED')
        db.session.add_all([sub_a, sub_b])
        db.session.commit()

        items_a = build_student_assignments(student_user_a, status_filter='pending')
        items_b = build_student_assignments(student_user_b, status_filter='pending')

        titles_a = [item['title'] for item in items_a]
        titles_b = [item['title'] for item in items_b]

        assert 'Math Homework A' in titles_a
        assert 'Physics Homework B' not in titles_a

        assert 'Physics Homework B' in titles_b
        assert 'Math Homework A' not in titles_b


def test_teacher_review_queue_data_isolation(app):
    """Teacher A must only see submissions for students mentored by Teacher A."""
    from app.telegram.application import build_teacher_review_queue

    with app.app_context():
        from app import db
        teacher_a = User(username='teacher_a', email='t_a@boostudy.test', role='tutor', is_active=True)
        teacher_b = User(username='teacher_b', email='t_b@boostudy.test', role='tutor', is_active=True)
        db.session.add_all([teacher_a, teacher_b])
        db.session.flush()

        st_a = Student(name='Mentee A', mentor_id=teacher_a.id, is_active=True)
        st_b = Student(name='Mentee B', mentor_id=teacher_b.id, is_active=True)
        db.session.add_all([st_a, st_b])
        db.session.flush()

        due = datetime.now(timezone.utc) + timedelta(days=2)
        asg_1 = Assignment(title='Task 1', assignment_type='homework', created_by_id=teacher_a.id, deadline=due, is_active=True)
        asg_2 = Assignment(title='Task 2', assignment_type='homework', created_by_id=teacher_b.id, deadline=due, is_active=True)
        db.session.add_all([asg_1, asg_2])
        db.session.flush()

        sub_a = Submission(assignment_id=asg_1.assignment_id, student_id=st_a.student_id, status='SUBMITTED')
        sub_b = Submission(assignment_id=asg_2.assignment_id, student_id=st_b.student_id, status='SUBMITTED')
        db.session.add_all([sub_a, sub_b])
        db.session.commit()

        queue_a = build_teacher_review_queue(teacher_a)
        queue_b = build_teacher_review_queue(teacher_b)

        titles_a = [item.assignment_title for item in queue_a]
        titles_b = [item.assignment_title for item in queue_b]

        assert 'Task 1' in titles_a
        assert 'Task 2' not in titles_a

        assert 'Task 2' in titles_b
        assert 'Task 1' not in titles_b
