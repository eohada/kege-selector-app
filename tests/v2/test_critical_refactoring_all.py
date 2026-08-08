import sys
import os

sys.path.insert(0, os.path.abspath('.'))
sys.stdout.reconfigure(encoding='utf-8')

import unittest
from app import create_app, db
from app.models import User, Student


class TestCriticalRefactoringV2(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()

    def test_1_analytics_no_hardcode(self):
        """Тест 1: GET /analytics от преподавателя возвращает 200 OK без статического хардкода."""
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
        html = response.get_data(as_text=True)
        self.assertIn('Аналитика группы и потоков', html)

    def test_2_students_route_restored(self):
        """Тест 2: GET /students и GET /teacher/students возвращают 200 OK (V2 Student Roster)."""
        with self.app.app_context():
            teacher = User.query.filter_by(role='tutor').first()
            if not teacher:
                teacher = User.query.first()
            teacher_id = teacher.id

        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(teacher_id)
            sess['_fresh'] = True
            sess['sandbox_role'] = 'tutor'

        response1 = self.client.get('/students')
        self.assertEqual(response1.status_code, 200)

        response2 = self.client.get('/teacher/students')
        self.assertEqual(response2.status_code, 200)

    def test_3_schedule_v2_migrated(self):
        """Тест 3: GET /schedule возвращает 200 OK и рендерит V2-шаблон (layout_teacher)."""
        with self.app.app_context():
            teacher = User.query.filter_by(role='tutor').first()
            if not teacher:
                teacher = User.query.first()
            teacher_id = teacher.id

        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(teacher_id)
            sess['_fresh'] = True
            sess['sandbox_role'] = 'tutor'

        response = self.client.get('/schedule')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('schedule-page', html)

    def test_4_dev_switcher_api_and_impersonation(self):
        """Тест 4: API /api/dev/users и /sandbox/impersonate/<id> корректно отдают пользователей и переключают сессию."""
        with self.app.app_context():
            teacher = User.query.filter_by(role='tutor').first()
            if not teacher:
                teacher = User.query.first()
            teacher_id = teacher.id

            student = User.query.filter_by(role='student').first()
            if not student:
                student = User(email='test_imp_student@boostudy.ru', role='student', full_name='Имперсонируемый Студент')
                db.session.add(student)
                db.session.commit()
            student_id = student.id

        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(teacher_id)
            sess['_fresh'] = True
            sess['sandbox_role'] = 'tutor'

        # GET /api/dev/users
        res_api1 = self.client.get('/api/dev/users')
        self.assertEqual(res_api1.status_code, 200)
        data1 = res_api1.get_json()
        self.assertEqual(data1['status'], 'success')
        self.assertTrue(len(data1['users']) > 0)

        # GET /sandbox/api/impersonate/users
        res_api2 = self.client.get('/sandbox/api/impersonate/users')
        self.assertEqual(res_api2.status_code, 200)

        # GET /sandbox/impersonate/<student_id>
        res_imp = self.client.get(f'/sandbox/impersonate/{student_id}')
        self.assertEqual(res_imp.status_code, 302)

        with self.client.session_transaction() as sess:
            self.assertEqual(sess['_user_id'], str(student_id))
            self.assertEqual(sess['sandbox_role'], 'student')

        # GET /sandbox/impersonate/revert
        res_rev = self.client.get('/sandbox/impersonate/revert')
        self.assertEqual(res_rev.status_code, 302)

        with self.client.session_transaction() as sess:
            self.assertEqual(sess['_user_id'], str(teacher_id))


if __name__ == '__main__':
    unittest.main()
