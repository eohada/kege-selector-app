import os
import unittest
from app import create_app, db
from app.models import User
from app.theory.routes import _resolve_theory_uploaded_asset_by_name, _render_theory_content_html_core


class TestTheoryImageResolution(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            teacher = User.query.filter_by(role='tutor').first() or User.query.first()
            if not teacher:
                teacher = User(username='test_theory_tutor', email='test_theory_tutor@example.com', role='tutor')
                teacher.set_password('pass123')
                db.session.add(teacher)
                db.session.commit()
            self.teacher_id = teacher.id

    def test_resolve_theory_images_with_timestamp_prefix(self):
        with self.app.app_context():
            res_5 = _resolve_theory_uploaded_asset_by_name('1776307086_5.png')
            self.assertIsNotNone(res_5)
            self.assertTrue(res_5.endswith(os.path.join('data', 'theory', 'pictures', '18', '5.png')))

            res_step5 = _resolve_theory_uploaded_asset_by_name('1776309156_step-05.png')
            self.assertIsNotNone(res_step5)
            self.assertTrue(res_step5.endswith(os.path.join('data', 'theory', 'pictures', '22', 'step-05.png')))

            res_min = _resolve_theory_uploaded_asset_by_name('min-solving.png')
            self.assertIsNotNone(res_min)
            self.assertTrue(res_min.endswith(os.path.join('data', 'theory', 'pictures', '22', 'min-solving.png')))

            res_complete = _resolve_theory_uploaded_asset_by_name('complete-in-x-ms-solving.png')
            self.assertIsNotNone(res_complete)
            self.assertTrue(res_complete.endswith(os.path.join('data', 'theory', 'pictures', '22', 'complete-in-x-ms-solving.png')))

    def test_resolve_missing_image_returns_none(self):
        with self.app.app_context():
            res = _resolve_theory_uploaded_asset_by_name('completely_non_existent_image_12345.png')
            self.assertIsNone(res)

    def test_path_traversal_blocked(self):
        with self.app.app_context():
            res = _resolve_theory_uploaded_asset_by_name('../../etc/passwd')
            self.assertIsNone(res)

    def test_serve_theory_uploaded_file(self):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.teacher_id)
            sess['_fresh'] = True
            sess['sandbox_role'] = 'tutor'

        resp = self.client.get('/theory/uploads/pictures/18/5.png')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content_type, 'image/png')
        self.assertGreater(len(resp.data), 1000)

        # Path traversal attempt should 404
        bad_resp = self.client.get('/theory/uploads/pictures/../../etc/passwd')
        self.assertEqual(bad_resp.status_code, 404)

    def test_render_theory_content_with_placeholders(self):
        with self.app.test_request_context():
            md = (
                '# Разбор задания\n\n'
                '![Граф](1776307086_5.png)\n\n'
                '![Отсутствует](missing_diagram_foo_bar.png)\n'
            )
            html = _render_theory_content_html_core(md)
            self.assertIn('/theory/uploads/pictures/18/5.png', html)
            self.assertIn('theory-missing-image-placeholder', html)
            self.assertIn('Изображение «missing_diagram_foo_bar.png» временно недоступно', html)
