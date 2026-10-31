import os
import pytest
from app import create_app
from app.models import db, User, Lesson, Student, TeacherStudent
from app.main.routes import _is_dev_impersonation_allowed
from app.lessons.routes import _whiteboard_access
from app.utils.local_dev_profile_pool import ensure_local_dev_profile_pool


def test_production_lockdown(monkeypatch):
    """Тест 1: В production dev-gate безусловно отключен, имперсонация дает 403."""
    monkeypatch.setenv('DATABASE_URL', 'postgresql://prod_mock:mock@127.0.0.1:5432/prod_db')
    monkeypatch.setenv('ENVIRONMENT', 'production')
    monkeypatch.setenv('FLASK_ENV', 'production')
    monkeypatch.setenv('APP_URL', 'https://boostudy.ru')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', '123456789:ABCdefGHIjklMNOpqrsTUVwxyz')
    monkeypatch.setattr('app.telegram.config.validate_public_telegram_config', lambda: None)
    
    app = create_app()
    with app.test_request_context():
        # В production dev-gate строго False
        assert _is_dev_impersonation_allowed() is False


def test_dev_disabled_by_env_flag(monkeypatch):
    """Тест 2: При явном флаге BOOSTUDY_DEV_IMPERSONATION=0 имперсонация выключена."""
    monkeypatch.setenv('ENVIRONMENT', 'local')
    monkeypatch.setenv('BOOSTUDY_DEV_IMPERSONATION', '0')
    
    app = create_app()
    with app.app_context():
        db.create_all()
        assert _is_dev_impersonation_allowed() is False
        
    with app.test_client() as client:
        res = client.get('/sandbox/api/impersonate/users')
        assert res.status_code == 403
        
        res = client.get('/sandbox/impersonate/demo_teacher_2')
        assert res.status_code == 403


def test_dev_allowed_lifecycle(monkeypatch):
    """Тест 3: Полный жизненный цикл dev-имперсонации в доверенном dev-контуре."""
    monkeypatch.setenv('ENVIRONMENT', 'local')
    monkeypatch.setenv('BOOSTUDY_DEV_IMPERSONATION', '1')
    
    app = create_app()
    with app.app_context():
        db.create_all()
        ensure_local_dev_profile_pool()
        
    with app.test_client() as client:
        # 1. Запрос 15 аккаунтов со страницы /login (без предварительной авторизации)
        res = client.get('/sandbox/api/impersonate/users')
        assert res.status_code == 200
        data = res.get_json()
        users = data.get('users', [])
        assert len(users) == 15
        usernames = [u['username'] for u in users]
        assert 'demo_teacher_2' in usernames
        assert 'demo_student_1' in usernames
        assert 'creator' in usernames
        
        # 2. Попытка имперсонации произвольного аккаунта вне пула -> отказ
        res_non = client.get('/sandbox/impersonate/non_existent_target')
        assert res_non.status_code in (403, 404)
        
        # 3. Вход под преподавателем в один клик
        res_t = client.get('/sandbox/impersonate/demo_teacher_2', follow_redirects=True)
        assert res_t.status_code == 200
        with client.session_transaction() as sess:
            assert sess.get('sandbox_role') == 'teacher'
            assert sess.get('is_impersonating') is True
            
        # 4. Переключение под учеником
        res_s = client.get('/sandbox/impersonate/demo_student_1', follow_redirects=True)
        assert res_s.status_code == 200
        with client.session_transaction() as sess:
            assert sess.get('sandbox_role') == 'student'
            assert sess.get('is_impersonating') is True
            
        # 5. Возврат к исходному состоянию
        res_rev = client.get('/sandbox/impersonate/revert', follow_redirects=True)
        assert res_rev.status_code == 200
        with client.session_transaction() as sess:
            assert sess.get('is_impersonating') is None


def test_lesson_genuine_rbac(monkeypatch):
    """Тест 4: Проверка штатной RBAC-модели на уроке без обходов авторизации."""
    monkeypatch.setenv('ENVIRONMENT', 'local')
    monkeypatch.setenv('BOOSTUDY_DEV_IMPERSONATION', '1')
    
    app = create_app()
    with app.app_context():
        db.create_all()
        ensure_local_dev_profile_pool()
        
        t_user = User.query.filter_by(username='demo_teacher_2').first()
        s1_user = User.query.filter_by(username='demo_student_1').first()
        s2_user = User.query.filter_by(username='demo_student_2').first()
        
        # Преподаватель имеет доступ через TeacherStudent
        with app.test_request_context():
            from flask_login import login_user
            login_user(t_user)
            _, role = _whiteboard_access(89)
            assert role == 'teacher'
            
        # Ученик 1 имеет доступ как владелец урока
        with app.test_request_context():
            from flask_login import login_user
            login_user(s1_user)
            _, role = _whiteboard_access(89)
            assert role == 'student'
            
        # Ученик 2 получает отказ 403 на чужой урок
        with app.test_request_context():
            from flask_login import login_user
            login_user(s2_user)
            with pytest.raises(Exception):
                _whiteboard_access(89)
