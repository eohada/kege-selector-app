import sys
import os

sys.path.insert(0, os.path.abspath('.'))
sys.stdout.reconfigure(encoding='utf-8')

import io
import unittest
from app import create_app, db
from app.models import User, LibraryMaterial


class TestLibraryHubV2(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()

    def test_1_library_get_as_teacher(self):
        """Тест 1: GET /library от имени преподавателя возвращает 200 OK."""
        with self.app.app_context():
            teacher = User.query.filter_by(role='tutor').first()
            if not teacher:
                teacher = User.query.first()
            teacher_id = teacher.id

        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(teacher_id)
            sess['_fresh'] = True
            sess['sandbox_role'] = 'tutor'

        response = self.client.get('/library')
        self.assertEqual(response.status_code, 200)
        self.assertTrue('Библиотека' in response.get_data(as_text=True) or 'Единая база знаний' in response.get_data(as_text=True))

    def test_2_upload_material_api(self):
        """Тест 2: POST /api/teacher/materials/upload с тестовым файлом создает запись в БД и сохраняет файл."""
        with self.app.app_context():
            teacher = User.query.filter_by(role='tutor').first()
            if not teacher:
                teacher = User.query.first()
            teacher_id = teacher.id

        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(teacher_id)
            sess['_fresh'] = True
            sess['sandbox_role'] = 'tutor'

        test_file_content = b"Sample educational material content for test"
        data = {
            'file': (io.BytesIO(test_file_content), 'test_cheat_sheet.pdf'),
            'title': 'Тестовая шпаргалка по №24',
            'description': 'Описание тестового файла',
            'category': 'materials',
            'tags': 'егэ, теория, питон',
            'is_visible_to_students': 'true'
        }

        response = self.client.post('/api/teacher/materials/upload', data=data, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 201)
        res_json = response.get_json()
        self.assertEqual(res_json['status'], 'success')
        material_data = res_json['material']
        self.assertEqual(material_data['title'], 'Тестовая шпаргалка по №24')
        self.assertEqual(material_data['file_extension'], 'pdf')
        self.assertTrue(material_data['is_visible_to_students'])

        with self.app.app_context():
            mat_db = LibraryMaterial.query.get(material_data['id'])
            self.assertIsNotNone(mat_db)
            self.assertEqual(mat_db.original_filename, 'test_cheat_sheet.pdf')
            upload_folder = os.path.join(self.app.root_path, 'static', 'uploads', 'library')
            file_path = os.path.join(upload_folder, mat_db.filename)
            self.assertTrue(os.path.exists(file_path))

    def test_3_download_material(self):
        """Тест 3: GET /materials/download/<id> отдаёт файл."""
        self.test_2_upload_material_api()

        with self.app.app_context():
            mat = LibraryMaterial.query.filter_by(original_filename='test_cheat_sheet.pdf').first()
            self.assertIsNotNone(mat)
            mat_id = mat.id
            teacher_id = mat.teacher_id

        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(teacher_id)
            sess['_fresh'] = True
            sess['sandbox_role'] = 'tutor'

        response = self.client.get(f'/materials/download/{mat_id}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"Sample educational material content for test")

    def test_4_delete_material_api(self):
        """Тест 4: DELETE /api/teacher/materials/<id> успешно удаляет файл и запись в БД."""
        self.test_2_upload_material_api()

        with self.app.app_context():
            mat = LibraryMaterial.query.filter_by(original_filename='test_cheat_sheet.pdf').first()
            self.assertIsNotNone(mat)
            mat_id = mat.id
            filename = mat.filename
            teacher_id = mat.teacher_id

        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(teacher_id)
            sess['_fresh'] = True
            sess['sandbox_role'] = 'tutor'

        response = self.client.delete(f'/api/teacher/materials/{mat_id}')
        self.assertEqual(response.status_code, 200)
        res_json = response.get_json()
        self.assertEqual(res_json['status'], 'success')

        with self.app.app_context():
            mat_db = LibraryMaterial.query.get(mat_id)
            self.assertIsNone(mat_db)
            upload_folder = os.path.join(self.app.root_path, 'static', 'uploads', 'library')
            file_path = os.path.join(upload_folder, filename)
            self.assertFalse(os.path.exists(file_path))

    def test_5_student_access_redirect(self):
        """Тест 5: Доступ студента к /library возвращает 302 редирект на /dashboard."""
        with self.app.app_context():
            student = User.query.filter_by(role='student').first()
            if not student:
                student = User.query.first()
            student_id = student.id

        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(student_id)
            sess['_fresh'] = True
            sess['sandbox_role'] = 'student'

        response = self.client.get('/library')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/dashboard', response.headers['Location'])


if __name__ == '__main__':
    unittest.main()
