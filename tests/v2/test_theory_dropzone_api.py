import sys
import os

sys.path.insert(0, os.path.abspath('.'))
sys.stdout.reconfigure(encoding='utf-8')

import io
import unittest
from app import create_app, db
from app.models import User, LibraryMaterial


class TestTheoryDropzoneApiV2(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()

    def test_1_create_theory_with_file(self):
        """Тест 1: POST /api/teacher/materials/upload создает запись теории С ПРИКРЕПЛЕННЫМ ФАЙЛОМ."""
        with self.app.app_context():
            teacher = User.query.filter_by(role='tutor').first()
            if not teacher:
                teacher = User.query.first()
            teacher_id = teacher.id

        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(teacher_id)
            sess['_fresh'] = True
            sess['sandbox_role'] = 'tutor'

        pdf_content = b"%PDF-1.4 Mock theory PDF document content"
        data = {
            'file': (io.BytesIO(pdf_content), 'Теория_Динамика_№27.pdf'),
            'title': 'Разбор алгоритмов динамики №27',
            'description': 'Подробный конспект с примерами кода',
            'category': 'theory',
            'tags': 'динамика, алгоритмы, егэ',
            'is_visible_to_students': 'true'
        }

        response = self.client.post('/api/teacher/materials/upload', data=data, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 201)
        res_json = response.get_json()
        self.assertEqual(res_json['status'], 'success')
        mat_data = res_json['material']
        self.assertEqual(mat_data['category'], 'theory')
        self.assertEqual(mat_data['file_extension'], 'pdf')

        with self.app.app_context():
            mat_db = LibraryMaterial.query.get(mat_data['id'])
            self.assertIsNotNone(mat_db)
            self.assertEqual(mat_db.title, 'Разбор алгоритмов динамики №27')
            upload_folder = os.path.join(self.app.root_path, 'static', 'uploads', 'library')
            file_path = os.path.join(upload_folder, mat_db.filename)
            self.assertTrue(os.path.exists(file_path))

    def test_2_create_theory_text_only(self):
        """Тест 2: POST /api/teacher/materials/upload создает текстовую теорию БЕЗ ФАЙЛА."""
        with self.app.app_context():
            teacher = User.query.filter_by(role='tutor').first()
            if not teacher:
                teacher = User.query.first()
            teacher_id = teacher.id

        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(teacher_id)
            sess['_fresh'] = True
            sess['sandbox_role'] = 'tutor'

        data = {
            'title': 'Чистая текстовая шпаргалка',
            'description': 'Краткий текстовый конспект формул',
            'category': 'theory',
            'tags': 'формулы, шпора'
        }

        response = self.client.post('/api/teacher/materials/upload', data=data, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 201)
        res_json = response.get_json()
        self.assertEqual(res_json['status'], 'success')
        mat_data = res_json['material']
        self.assertEqual(mat_data['category'], 'theory')

        with self.app.app_context():
            mat_db = LibraryMaterial.query.get(mat_data['id'])
            self.assertIsNotNone(mat_db)
            self.assertEqual(mat_db.title, 'Чистая текстовая шпаргалка')


if __name__ == '__main__':
    unittest.main()
