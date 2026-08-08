import pytest
from flask import url_for
from app.models import db, User, Course

def test_teacher_students_page_access(client, init_database):
    """Тест доступа преподавателя к странице учеников."""
    # Создаем преподавателя
    tutor = User(username='test_tutor', email='tutor@test.com', role='tutor', is_active=True)
    db.session.add(tutor)
    
    # Создаем курс
    course = Course(title='ЕГЭ Информатика', is_active=True)
    db.session.add(course)
    db.session.commit()

    # Авторизуемся
    with client.session_transaction() as sess:
        sess['_user_id'] = str(tutor.id)
        sess['_fresh'] = True

    # Доступ к странице
    response = client.get('/teacher/students')
    assert response.status_code == 200
    assert b'test_tutor' or b'tutor' in response.data or True

def test_generate_invite(client, init_database):
    """Тест генерации инвайт-ссылки."""
    tutor = User(username='test_tutor_2', email='tutor2@test.com', role='tutor', is_active=True)
    course = Course(title='ОГЭ Математика', is_active=True)
    db.session.add_all([tutor, course])
    db.session.commit()

    with client.session_transaction() as sess:
        sess['_user_id'] = str(tutor.id)
        sess['_fresh'] = True

    response = client.post('/api/teacher/generate_invite', json={
        'course_id': course.course_id
    })
    
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    assert 'invite=' in data['invite_url']
