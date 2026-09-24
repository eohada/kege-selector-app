"""
Integration tests for Teacher Dashboard V2, Todo checklist API, and route compatibility.
"""

import json
import pytest
from core.db_models import db, User


def login_client(client, user_id: int, role: str = 'tutor'):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True
        sess['sandbox_role'] = role


def get_or_create_teacher():
    user = User.query.filter_by(username='test_dash_teacher').first()
    if not user:
        user = User(
            username='test_dash_teacher',
            email='test_dash_teacher@example.com',
            role='tutor',
        )
        user.set_password('Password123!')
        db.session.add(user)
        db.session.commit()
    return user


def test_teacher_dashboard_render(app):
    """Verifies that /dashboard renders the rich teacher dashboard for a tutor"""
    with app.app_context():
        teacher = get_or_create_teacher()
        teacher_id = teacher.id

    client = app.test_client()
    login_client(client, teacher_id, 'tutor')

    response = client.get('/dashboard')
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    # Core blocks from the screenshot
    assert 'Фокус на сегодня' in html
    assert 'Быстрые действия' in html
    assert 'Не забыть!' in html
    assert 'Средний результат учеников' in html
    assert 'Динамика учеников' in html
    assert 'Карта тем' in html
    assert 'Последняя активность' in html
    assert 'активных учеников' in html
    assert 'Назначить пробник' in html
    assert 'Банк' in html or 'Банк задач' in html


def test_teacher_dashboard_todo_api(app):
    """Verifies adding, toggling, and deleting items in the To-Do checklist"""
    from app.main.teacher_dashboard_service import save_teacher_todos

    with app.app_context():
        teacher = get_or_create_teacher()
        teacher_id = teacher.id
        save_teacher_todos(teacher_id, [])

    client = app.test_client()
    login_client(client, teacher_id, 'tutor')

    # 1. Add todo
    todo_text = 'Проверить ДЗ №15 по динамике'
    add_res = client.post(
        '/api/teacher-dashboard/todo',
        data=json.dumps({'action': 'add', 'text': todo_text}),
        content_type='application/json'
    )
    assert add_res.status_code == 200
    data = add_res.get_json()
    assert data.get('success') is True
    todos = data.get('todos', [])
    added_item = next((t for t in todos if t['text'] == todo_text), None)
    assert added_item is not None
    assert added_item['done'] is False

    # 2. Toggle todo
    toggle_res = client.post(
        '/api/teacher-dashboard/todo',
        data=json.dumps({'action': 'toggle', 'id': added_item['id']}),
        content_type='application/json'
    )
    assert toggle_res.status_code == 200
    toggle_data = toggle_res.get_json()
    assert toggle_data.get('success') is True
    toggled_item = next((t for t in toggle_data.get('todos', []) if t['id'] == added_item['id']), None)
    assert toggled_item is not None
    assert toggled_item['done'] is True

    # 3. Delete todo
    del_res = client.post(
        '/api/teacher-dashboard/todo',
        data=json.dumps({'action': 'delete', 'id': added_item['id']}),
        content_type='application/json'
    )
    assert del_res.status_code == 200
    del_data = del_res.get_json()
    assert del_data.get('success') is True
    remaining = [t for t in del_data.get('todos', []) if t['id'] == added_item['id']]
    assert len(remaining) == 0


def test_teacher_dashboard_quick_student(app):
    """Verifies creating a student directly from the quick student modal"""
    from core.db_models import Student, TeacherStudent

    with app.app_context():
        teacher = get_or_create_teacher()
        teacher_id = teacher.id

    client = app.test_client()
    login_client(client, teacher_id, 'tutor')

    student_name = f'Тестовый Ученик {teacher_id}'
    res = client.post(
        '/api/teacher-dashboard/quick-student',
        data=json.dumps({
            'name': student_name,
            'target_score': 90,
            'telegram': '@test_student_tg',
            'category': 'ЕГЭ Информатика'
        }),
        content_type='application/json'
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data.get('success') is True
    assert data.get('student_id') is not None

    with app.app_context():
        st = Student.query.get(data['student_id'])
        assert st is not None
        assert st.name == student_name
        assert st.mentor_id == teacher_id
        # Verify TeacherStudent link
        ts = TeacherStudent.query.filter_by(teacher_id=teacher_id, student_id=st.user_id).first()
        assert ts is not None


def test_students_catalog_route_preserved(app):
    """Verifies that /students still renders the student catalog"""
    with app.app_context():
        teacher = get_or_create_teacher()
        teacher_id = teacher.id

    client = app.test_client()
    login_client(client, teacher_id, 'tutor')

    response = client.get('/students')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    # Should render students catalog
    assert 'Ученики' in html or 'Все ученики' in html
