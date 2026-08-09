import os
from pathlib import Path

import pytest


# Исторические файлы tests/v2 были исполняемыми QA-скриптами: они создавали
# приложение и меняли локальную БД прямо при импорте. Pytest не должен собирать
# их как тестовые модули. Они сохранены как справочные сценарии до миграции.
collect_ignore = [
    path.name
    for path in Path(__file__).parent.glob('test_*.py')
    if path.name not in {
        'test_role_lifecycle_recovery.py',
        'test_admin_functional_v2.py',
        'test_lesson_studio.py',
        'test_auth_invitations_roles_v2.py',
        'test_preparation_mode_v2.py',
        'test_theory_learning_cycle_v2.py',
        'test_schema_contract_v2.py',
    }
]

os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
os.environ.setdefault('SECRET_KEY', 'tests-v2-isolated-secret-key')
os.environ.setdefault('TRAINER_SHARED_SECRET', 'tests-v2-trainer-secret-key')
os.environ.setdefault('DISABLE_BACKGROUND_WORKERS', '1')


@pytest.fixture()
def app():
    from app import create_app, db

    test_app = create_app()
    test_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
    )
    with test_app.app_context():
        db.create_all()
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def login_as(client, user_id: int, role: str):
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True
        session['sandbox_role'] = role


@pytest.fixture()
def role_users(app):
    from app import db
    from app.models import Enrollment, Student, User

    with app.app_context():
        tutor = User(username='v2_tutor', email='v2_tutor@example.test', role='tutor', is_active=True)
        student_user = User(username='v2_student', email='v2_student@example.test', role='student', is_active=True)
        db.session.add_all([tutor, student_user])
        db.session.flush()
        student = Student(name='V2 Fixture Student', user_id=student_user.id, is_active=True)
        db.session.add(student)
        db.session.add(Enrollment(student_id=student_user.id, tutor_id=tutor.id, subject='Информатика', status='active'))
        db.session.commit()
        return {
            'tutor_id': tutor.id,
            'student_user_id': student_user.id,
            'student_id': student.student_id,
        }
