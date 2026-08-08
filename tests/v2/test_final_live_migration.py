import sys
import os

sys.path.insert(0, os.path.abspath('.'))
sys.stdout.reconfigure(encoding='utf-8')

import unittest
from app import create_app, db
from app.models import User, Student


class TestFinalLiveMigrationV2(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()

    def test_1_assignments_live_route(self):
        """Тест 1: GET /assignments от преподавателя возвращает 200 OK."""
        with self.app.app_context():
            teacher = User.query.filter_by(role='tutor').first()
            if not teacher:
                teacher = User.query.first()
            teacher_id = teacher.id

        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(teacher_id)
            sess['_fresh'] = True
            sess['sandbox_role'] = 'tutor'

        response = self.client.get('/assignments')
        self.assertEqual(response.status_code, 200)

    def test_2_generator_live_route(self):
        """Тест 2: GET /generator и GET /task-generator возвращают 200 OK."""
        with self.app.app_context():
            teacher = User.query.filter_by(role='tutor').first()
            if not teacher:
                teacher = User.query.first()
            teacher_id = teacher.id

        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(teacher_id)
            sess['_fresh'] = True
            sess['sandbox_role'] = 'tutor'

        res1 = self.client.get('/generator')
        self.assertEqual(res1.status_code, 200)

        res2 = self.client.get('/task-generator')
        self.assertEqual(res2.status_code, 200)

    def test_3_students_v2_empty_state_and_roster(self):
        """Тест 3: GET /students от преподавателя выводит V2-реестр со стильным Empty State или динамическим списком."""
        with self.app.app_context():
            teacher = User.query.filter_by(role='tutor').first()
            if not teacher:
                teacher = User.query.first()
            teacher_id = teacher.id

        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(teacher_id)
            sess['_fresh'] = True
            sess['sandbox_role'] = 'tutor'

        response = self.client.get('/students')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('Ученики и поток', html)

    def test_4_sidebar_no_sandbox_prefixes(self):
        """Тест 4: Ссылки V2-сайдбара ведуть на боевые урлы без /sandbox/."""
        with open('templates/sandbox/layout_teacher.html', 'r', encoding='utf-8') as f:
            sidebar_html = f.read()

        self.assertIn('href="/assignments"', sidebar_html)
        self.assertIn('href="/task-generator"', sidebar_html)
        self.assertIn('href="/students"', sidebar_html)
        self.assertIn('href="/library"', sidebar_html)
        self.assertIn('href="/schedule"', sidebar_html)
        self.assertNotIn('href="/sandbox/assignments"', sidebar_html)
        self.assertNotIn('href="/sandbox/task_generator"', sidebar_html)


if __name__ == '__main__':
    unittest.main()
