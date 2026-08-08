import sys
import os

sys.path.insert(0, os.path.abspath('.'))
sys.stdout.reconfigure(encoding='utf-8')

import unittest
from app import create_app, db
from app.models import User, TaskTemplate


class TestTemplateCreationDirectV2(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()

    def test_1_create_template_api(self):
        """Тест 1: POST /api/templates/create успешно создает шаблон."""
        with self.app.app_context():
            teacher = User.query.filter_by(role='tutor').first()
            if not teacher:
                teacher = User.query.first()
            teacher_id = teacher.id

        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(teacher_id)
            sess['_fresh'] = True
            sess['sandbox_role'] = 'tutor'

        payload = {
            'name': 'Прямой шаблон из Единого Хаба',
            'description': 'Тестирование прямого ввода шаблона',
            'template_type': 'homework',
            'category': 'Информатика КЕГЭ'
        }

        response = self.client.post('/api/templates/create', json=payload)
        self.assertEqual(response.status_code, 201)
        data = response.get_json()
        self.assertEqual(data['status'], 'success')
        self.assertIn('template_id', data)

        template_id = data['template_id']
        with self.app.app_context():
            tpl = TaskTemplate.query.get(template_id)
            self.assertIsNotNone(tpl)
            self.assertEqual(tpl.name, 'Прямой шаблон из Единого Хаба')

    def test_2_library_templates_tab_get(self):
        """Тест 2: GET /library?tab=templates от имени преподавателя возвращает 200 OK."""
        with self.app.app_context():
            teacher = User.query.filter_by(role='tutor').first()
            if not teacher:
                teacher = User.query.first()
            teacher_id = teacher.id

        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(teacher_id)
            sess['_fresh'] = True
            sess['sandbox_role'] = 'tutor'

        response = self.client.get('/library?tab=templates')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Создать шаблон', response.get_data(as_text=True))

    def test_3_task_generator_back_link(self):
        """Тест 3: GET /sandbox/task_generator содержит ссылку Назад на /library?tab=templates."""
        with self.app.app_context():
            teacher = User.query.filter_by(role='tutor').first()
            if not teacher:
                teacher = User.query.first()
            teacher_id = teacher.id

        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(teacher_id)
            sess['_fresh'] = True
            sess['sandbox_role'] = 'tutor'

        response = self.client.get('/sandbox/task_generator')
        self.assertEqual(response.status_code, 200)
        html_content = response.get_data(as_text=True)
        self.assertIn('/library?tab=templates', html_content)


if __name__ == '__main__':
    unittest.main()
