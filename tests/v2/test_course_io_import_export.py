from __future__ import annotations

import io
import json
import pytest

from app.courses.course_io import import_course_from_data, export_course_to_dict
from core.db_models import LearningTrajectory, TrajectoryModule, Lesson, ExamSkill


def login_as(client, user_id: int, role: str):
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True
        session['sandbox_role'] = role


def test_import_course_from_data_and_export(client, app, role_users):
    login_as(client, role_users['tutor_id'], 'tutor')

    curriculum_sample = {
        'title': 'ЕГЭ Информатика: Полный курс (Тест)',
        'subject': 'Информатика',
        'is_template': True,
        'target_score': '80-100',
        'goal': 'Подготовка к ЕГЭ',
        'result': 'Результат 80+',
        'skills': [
            {
                'topic_code': 'TEST_SKILL_01',
                'name': 'Тестовый навык графов',
                'section': 'Информационные модели',
                'exam_task_number': 1
            }
        ],
        'modules': [
            {
                'order': 10,
                'name': 'Модуль 1. Основы',
                'result': 'Освоение базы',
                'description': 'Введение и синтаксис',
                'is_control_exam': False,
                'lessons': [
                    {
                        'order': 10,
                        'title': 'Урок 1. Старт',
                        'lesson_format': 'Теория + Практика',
                        'duration_minutes': 60,
                        'topic_codes': ['TEST_SKILL_01'],
                        'studio_scenario': '1. Вводная часть\n2. Практика',
                        'theory_content': '### Конспект теории',
                        'homework_content': 'Решить задачи 1-5'
                    }
                ]
            }
        ]
    }

    with app.app_context():
        trajectory, stats = import_course_from_data(curriculum_sample, user_id=role_users['tutor_id'])
        assert trajectory.course_id is not None
        assert stats['modules'] == 1
        assert stats['lessons'] == 1
        assert stats['skills'] == 1
        assert trajectory.target_score == 80

        # Check export
        exported = export_course_to_dict(trajectory)
        assert exported['title'] == 'ЕГЭ Информатика: Полный курс (Тест)'
        assert len(exported['modules']) == 1
        assert exported['modules'][0]['name'] == 'Модуль 1. Основы'
        assert len(exported['modules'][0]['lessons']) == 1
        assert exported['modules'][0]['lessons'][0]['title'] == 'Урок 1. Старт'
        assert exported['modules'][0]['lessons'][0]['topic_codes'] == ['TEST_SKILL_01']
        assert exported['modules'][0]['lessons'][0]['studio_scenario'] == '1. Вводная часть\n2. Практика'


def test_course_import_http_routes(client, app, role_users):
    login_as(client, role_users['tutor_id'], 'tutor')

    sample_course = {
        'title': 'Курс через API Импорт',
        'subject': 'Информатика',
        'is_template': True,
        'target_score': 100,
        'modules': [
            {
                'name': 'Модуль API',
                'lessons': [
                    {'title': 'Урок API 1', 'duration_minutes': 60}
                ]
            }
        ]
    }

    # 1. AJAX JSON POST
    resp = client.post('/courses/import', json=sample_course, headers={'X-Requested-With': 'XMLHttpRequest'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    assert 'course_id' in data
    imported_id = data['course_id']

    # 2. View imported course page
    view_resp = client.get(f'/courses/{imported_id}')
    assert view_resp.status_code == 200
    assert 'Курс через API Импорт'.encode('utf-8') in view_resp.data

    # 3. Export JSON route
    export_resp = client.get(f'/courses/{imported_id}/export/json')
    assert export_resp.status_code == 200
    assert export_resp.headers.get('Content-Type') == 'application/json'
    export_data = json.loads(export_resp.data.decode('utf-8'))
    assert export_data['title'] == 'Курс через API Импорт'


def test_import_course_with_invalid_or_missing_exam_course_id(client, app, role_users):
    """
    Проверяет, что импорт курса с несуществующим exam_course_id (например, 99999)
    или отсутствующим курсом не вызывает ForeignKeyViolation, а безопасно разрешает
    или обнуляет exam_course_id.
    """
    login_as(client, role_users['tutor_id'], 'tutor')

    course_with_foreign_id = {
        'title': 'ЕГЭ Информатика: Полный курс подготовки (72 урока)',
        'subject': 'Информатика',
        'is_template': True,
        'student_id': None,
        'exam_course_id': 999999,  # Несуществующий внешний ID
        'target_score': 80,
        'modules': [
            {
                'name': 'Раздел 1',
                'lessons': [
                    {'title': 'Урок 1', 'duration_minutes': 60}
                ]
            }
        ]
    }

    with app.app_context():
        trajectory, stats = import_course_from_data(course_with_foreign_id, user_id=role_users['tutor_id'])
        assert trajectory.course_id is not None
        assert trajectory.title == 'ЕГЭ Информатика: Полный курс подготовки (72 урока)'
        # exam_course_id должен либо указывать на валидный существующий курс, либо быть None, но не 999999
        from core.db_models import Course
        if trajectory.exam_course_id:
            assert Course.query.get(trajectory.exam_course_id) is not None
        assert trajectory.student_id is None
        assert stats['modules'] == 1
        assert stats['lessons'] == 1

