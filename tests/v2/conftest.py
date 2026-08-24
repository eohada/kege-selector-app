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
        'test_dynamic_workspace_and_navigation.py',
        'test_lesson_room_interactive.py',
        'test_full_assignment_lifecycle.py',
        'test_deploy_bluegreen_contract.py',
        'test_release_readiness_v2.py',
        'test_student_assignment_logic.py',
        'test_timezone_schedule_v2.py',
        'test_course_adaptive_program_v2.py',
    }
]

os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
os.environ.setdefault('SECRET_KEY', 'tests-v2-isolated-secret-key')
os.environ.setdefault('TRAINER_SHARED_SECRET', 'tests-v2-trainer-secret-key')
os.environ.setdefault('DISABLE_BACKGROUND_WORKERS', '1')


@pytest.fixture()
def app(request):
    from app import create_app, db

    test_app = create_app({
        'TESTING': True,
        'WTF_CSRF_ENABLED': False,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
    })
    # Не держим app_context вокруг всего теста: Flask-Login кэширует current_user
    # в g, и при переключении tutor -> student в одном клиенте получалась роль
    # предыдущего запроса. Контекст нужен только для создания и очистки БД.
    with test_app.app_context():
        db.create_all()
    # Три исторических release-readiness теста используют db.session напрямую
    # вне запроса. Даём контекст только этому модулю; остальные тесты обязаны
    # работать без общего контекста, чтобы проверять реальное переключение ролей.
    legacy_context = None
    if request.node.fspath.basename == 'test_release_readiness_v2.py':
        legacy_context = test_app.app_context()
        legacy_context.push()
    try:
        yield test_app
    finally:
        # Realtime-модули держат состояние комнат на уровне процесса. При
        # полном прогоне V2 один процесс обслуживает несколько Flask app,
        # поэтому очищаем его так же, как очищаем изолированную БД.
        from app.lessons import lesson_socket
        from app.task_workspace import socket as workspace_socket

        with test_app.app_context():
            lesson_socket._lesson_presence.clear()
            with workspace_socket._workspace_autosave_lock:
                for timer in workspace_socket._workspace_autosave_timers.values():
                    timer.cancel()
                workspace_socket._workspace_autosave_timers.clear()
            workspace_socket._workspace_rooms.clear()
            workspace_socket._workspace_state.clear()
            workspace_socket._workspace_cursor_emit_at.clear()
            db.session.remove()
            db.drop_all()
        if legacy_context is not None:
            legacy_context.pop()


@pytest.fixture()
def client(app):
    return app.test_client()


def login_as(client, user_id: int, role: str):
    # Remove a previous app's signed session before installing the requested
    # identity. This matters when several create_app() instances run in one
    # pytest process and share the Flask test client's cookie jar.
    client.delete_cookie('session')
    client.delete_cookie('remember_token')
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user_id)
        session['_fresh'] = True
        session['sandbox_role'] = role


@pytest.fixture()
def role_users(app):
    from app import db
    from app.models import Enrollment, Student, User

    with app.app_context():
        tutor = User(username='v2_tutor', email='v2_tutor@example.test', role='tutor', is_active=True)
        creator = User(username='v2_creator', email='v2_creator@example.test', role='creator', is_active=True)
        student_user = User(username='v2_student', email='v2_student@example.test', role='student', is_active=True)
        db.session.add_all([tutor, creator, student_user])
        db.session.flush()
        student = Student(name='V2 Fixture Student', user_id=student_user.id, is_active=True)
        db.session.add(student)
        db.session.add(Enrollment(student_id=student_user.id, tutor_id=tutor.id, subject='Информатика', status='active'))
        db.session.commit()
        return {
            'tutor_id': tutor.id,
            'creator_id': creator.id,
            'student_user_id': student_user.id,
            'student_id': student.student_id,
        }
