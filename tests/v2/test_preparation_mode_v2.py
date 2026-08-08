"""
Тестовый модуль V2 для проверки Режима Подготовки (Launch Mode).
Проверяет:
1. Переключение режима только Администратором/Создателем (обычный учитель/ученик/родитель получает 403).
2. Поведение при Mode OFF: полный обычный доступ у всех ролей.
3. Поведение при Mode ON:
   - Преподаватель/Создатель сохраняют 100% полный доступ без редиректов.
   - Регистрация учеников и родителей по токен-ссылкам работает штатно, базы данных и связи создаются.
   - Вход ученика и родителя работает.
   - Запросы к веб-страницам (/dashboard, /lessons/...) от ученика/родителя редиректятся на /preparation.
   - Запросы к API от ученика/родителя получают 403 JSON с флагом preparation_mode.
4. Отключение режима (Mode OFF):
   - Зарегистрированные во время режима подготовки ученики и родители БЕЗ ДОПОЛНИТЕЛЬНЫХ ШАГОВ получают обычный доступ.
"""

import pytest
import secrets
import hashlib
from datetime import timedelta
from app.models import db, User, Student, InviteLink, FamilyTie, TeacherStudent, SystemSetting
from core.db_models import moscow_now

def create_user(client, username, email, role, password="Password123!"):
    user = User(username=username, email=email, role=role, is_active=True)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user

def login_user_id(client, user_id: int, role: str):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True
        sess['sandbox_role'] = role
        sess['role'] = role

def logout(client):
    with client.session_transaction() as sess:
        sess.clear()


def test_preparation_mode_toggle_permissions(client, app):
    """Обычный teacher/student/parent не могут переключать режим подготовки. Только admin/creator."""
    with app.app_context():
        creator = create_user(client, "prep_creator_1", "prep_creator_1@test.com", "creator")
        teacher = create_user(client, "prep_teacher_1", "prep_teacher_1@test.com", "tutor")
        student_u = create_user(client, "prep_student_perm", "prep_student_perm@test.com", "student")

        # 1. Студент пытается переключить -> 403
        login_user_id(client, student_u.id, student_u.role)
        res = client.post('/admin/preparation/toggle', headers={'X-Requested-With': 'XMLHttpRequest'})
        assert res.status_code == 403

        # 2. Учитель пытается переключить -> 403
        login_user_id(client, teacher.id, teacher.role)
        res = client.post('/admin/preparation/toggle', headers={'X-Requested-With': 'XMLHttpRequest'})
        assert res.status_code == 403

        # 3. Создатель переключает -> 200 OK
        login_user_id(client, creator.id, creator.role)
        res = client.post('/admin/preparation/toggle', headers={'X-Requested-With': 'XMLHttpRequest'})
        assert res.status_code == 200
        assert SystemSetting.get_value('preparation_mode_enabled', 'false') == 'true'

        # Сбрасываем обратно
        client.post('/admin/preparation/toggle', headers={'X-Requested-With': 'XMLHttpRequest'})
        assert SystemSetting.get_value('preparation_mode_enabled', 'false') == 'false'


def test_preparation_mode_full_flow(client, app):
    """Полный жизненный цикл Launch Mode: ON -> Регистрации -> Заглушка -> OFF -> Восстановление доступа."""
    with app.app_context():
        # Сбрасываем флаг режима подготовки
        SystemSetting.set_value('preparation_mode_enabled', 'false')

        # Создаем Персонажей
        creator = create_user(client, "prep_main_creator", "prep_main_creator@test.com", "creator")
        teacher = create_user(client, "prep_main_teacher", "prep_main_teacher@test.com", "tutor")
        creator_id = creator.id
        teacher_id = teacher.id

        # --- ШАГ 1: Включаем Launch Mode ---
        login_user_id(client, creator_id, 'creator')
        res = client.post('/admin/preparation/toggle', headers={'X-Requested-With': 'XMLHttpRequest'})
        assert res.status_code == 200
        assert SystemSetting.get_value('preparation_mode_enabled', 'false') == 'true'

        # --- ШАГ 2: Преподаватель видит платформу штатно ---
        teacher_client = app.test_client()
        login_user_id(teacher_client, teacher_id, 'tutor')
        res_dash = teacher_client.get('/dashboard')
        assert res_dash.status_code == 200
        assert b'/preparation' not in res_dash.data

        # --- ШАГ 3: Генерация Инвайтов для Ученика и Родителя ---
        raw_st_token = secrets.token_urlsafe(32)
        st_invite = InviteLink(
            token_hash=hashlib.sha256(raw_st_token.encode('utf-8')).hexdigest(),
            email='',
            role='student',
            teacher_id=teacher_id,
            created_by_user_id=teacher_id,
            expires_at=moscow_now() + timedelta(days=7)
        )
        db.session.add(st_invite)
        db.session.commit()

        # --- ШАГ 4: Ученик регистрируется как гость во время режима подготовки ---
        guest_client_1 = app.test_client()
        guest_client_1.get('/logout')
        reg_st_res = guest_client_1.post(f'/register/student/{raw_st_token}', data={
            'username': 'launch_st1',
            'full_name': 'Launch Student 1',
            'email': 'launch_st1@test.com',
            'password': 'Password123!',
            'confirm_password': 'Password123!'
        }, follow_redirects=True)
        assert reg_st_res.status_code == 200

        new_st_user = User.query.filter_by(email='launch_st1@test.com').first()
        assert new_st_user is not None
        assert new_st_user.role == 'student'
        st_obj = Student.query.filter_by(user_id=new_st_user.id).first()
        assert st_obj is not None
        st_user_id = new_st_user.id

        # --- ШАГ 5: Ученик пытается зайти на /dashboard -> редирект на /preparation ---
        dash_res = guest_client_1.get('/dashboard')
        assert dash_res.status_code == 302
        assert '/preparation' in dash_res.headers['Location']

        prep_page_res = guest_client_1.get('/preparation')
        assert prep_page_res.status_code == 200
        assert 'Почти всё готово!' in prep_page_res.get_data(as_text=True)

        # Запрос к API от ученика -> 403 JSON с флагом preparation_mode
        api_res = guest_client_1.get('/api/v2/student/dashboard/summary', headers={'X-Requested-With': 'XMLHttpRequest'})
        assert api_res.status_code == 403
        data = api_res.get_json()
        assert data['preparation_mode'] is True

        # --- ШАГ 6: Ссылка и регистрация Родителя во время режима подготовки ---
        raw_pr_token = secrets.token_urlsafe(32)
        pr_invite = InviteLink(
            token_hash=hashlib.sha256(raw_pr_token.encode('utf-8')).hexdigest(),
            email='',
            role='parent',
            student_id=st_obj.student_id,
            teacher_id=teacher_id,
            created_by_user_id=teacher_id,
            expires_at=moscow_now() + timedelta(days=7)
        )
        db.session.add(pr_invite)
        db.session.commit()

        guest_client_2 = app.test_client()
        guest_client_2.get('/logout')
        reg_pr_res = guest_client_2.post(f'/register/parent/{raw_pr_token}', data={
            'username': 'launch_pr1',
            'full_name': 'Launch Parent 1',
            'email': 'launch_pr1@test.com',
            'password': 'Password123!',
            'confirm_password': 'Password123!'
        }, follow_redirects=True)
        assert reg_pr_res.status_code == 200

        new_pr_user = User.query.filter_by(email='launch_pr1@test.com').first()
        assert new_pr_user is not None
        assert new_pr_user.role == 'parent'
        pr_user_id = new_pr_user.id

        # Проверяем семейную связь FamilyTie
        tie = FamilyTie.query.filter_by(parent_id=pr_user_id, student_id=st_user_id).first()
        assert tie is not None

        # Родитель заходит и видит заглушку /preparation
        pr_dash_res = guest_client_2.get('/dashboard')
        assert pr_dash_res.status_code == 302
        assert '/preparation' in pr_dash_res.headers['Location']

        # --- ШАГ 7: Создатель ВЫКЛЮЧАЕТ режим подготовки (Mode OFF) ---
        cr_client = app.test_client()
        login_user_id(cr_client, creator_id, 'creator')
        res_off = cr_client.post('/admin/preparation/toggle', headers={'X-Requested-With': 'XMLHttpRequest'})
        assert res_off.status_code == 200
        assert SystemSetting.get_value('preparation_mode_enabled', 'false') == 'false'

        # --- ШАГ 8: Ученик и Родитель СРАЗУ получают доступ к обычному кабинету ---
        st_after_off = guest_client_1.get('/dashboard')
        assert st_after_off.status_code == 200
        assert b'/preparation' not in st_after_off.data

        pr_after_off = guest_client_2.get('/dashboard')
        assert pr_after_off.status_code == 200
        assert b'/preparation' not in pr_after_off.data
