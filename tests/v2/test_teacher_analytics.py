import sys
import os

sys.path.insert(0, os.path.abspath('.'))
sys.stdout.reconfigure(encoding='utf-8')

import unittest
from app import create_app, db
from app.models import User, SchoolGroup


class TestTeacherAnalyticsV2(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()

    def test_1_analytics_get_as_teacher(self):
        """Тест 1: GET /analytics от преподавателя возвращает 200 OK."""
        with self.app.app_context():
            teacher = User.query.filter_by(role='tutor').first()
            if not teacher:
                teacher = User.query.first()
            teacher_id = teacher.id

        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(teacher_id)
            sess['_fresh'] = True
            sess['sandbox_role'] = 'tutor'

        response = self.client.get('/analytics')
        self.assertEqual(response.status_code, 200)
        html_content = response.get_data(as_text=True)
        self.assertIn('Аналитика группы и потоков', html_content)
        self.assertIn('Средний балл КЕГЭ', html_content)

    def test_2_analytics_group_filter(self):
        """Тест 2: GET /analytics?group_id=1 с фильтром по группе возвращает 200 OK."""
        with self.app.app_context():
            teacher = User.query.filter_by(role='tutor').first()
            if not teacher:
                teacher = User.query.first()
            teacher_id = teacher.id

        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(teacher_id)
            sess['_fresh'] = True
            sess['sandbox_role'] = 'tutor'

        response = self.client.get('/analytics?group_id=1')
        self.assertEqual(response.status_code, 200)
        html_content = response.get_data(as_text=True)
        self.assertIn('Аналитика группы и потоков', html_content)

    def test_3_remind_student_hw_api(self):
        """Тест 3: POST /api/teacher/students/1/remind возвращает 200 OK и статус success."""
        with self.app.app_context():
            teacher = User.query.filter_by(role='tutor').first()
            if not teacher:
                teacher = User.query.first()
            teacher_id = teacher.id

        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(teacher_id)
            sess['_fresh'] = True
            sess['sandbox_role'] = 'tutor'

        response = self.client.post('/api/teacher/students/1/remind')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data['status'], 'success')
        self.assertIn('Напоминание о ДЗ успешно отправлено', data['message'])

    def test_4_student_access_redirect(self):
        """Тест 4: GET /analytics от имени студента возвращает 302 редирект на /dashboard."""
        with self.app.app_context():
            student = User.query.filter_by(role='student').first()
            if not student:
                student = User(email='test_student_analytics@boostudy.ru', role='student', full_name='Студент Тест')
                db.session.add(student)
                db.session.commit()
            student_id = student.id

        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(student_id)
            sess['_fresh'] = True
            sess['sandbox_role'] = 'student'

        response = self.client.get('/analytics')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith('/dashboard'))


if __name__ == '__main__':
    unittest.main()
