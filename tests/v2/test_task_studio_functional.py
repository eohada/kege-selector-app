import sys
import os

sys.path.insert(0, os.path.abspath('.'))
sys.stdout.reconfigure(encoding='utf-8')

import unittest
from unittest.mock import patch
from app import create_app, db
from app.models import User, Tasks, TaskBookmark, TaskTemplate, TemplateTask, TaskSolution


class TestTaskStudioFunctionalV2(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()
            teacher = User.query.filter_by(role='tutor').first()
            if not teacher:
                teacher = User.query.filter_by(role='teacher').first()
            if not teacher:
                teacher = User.query.first()
            if not teacher:
                teacher = User(
                    username='synthetic_task_studio_teacher',
                    email='synthetic-task-studio@example.test',
                    role='tutor',
                    is_active=True,
                )
                teacher.set_password('synthetic-test-only')
                db.session.add(teacher)
                db.session.commit()
            self.teacher_id = teacher.id

            # Ensure we have at least one test task
            task = Tasks.query.filter_by(is_active=True).first()
            self.task_id = task.task_id if task else None

    def _login_as_teacher(self):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.teacher_id)
            sess['_fresh'] = True
            sess['sandbox_role'] = 'tutor'

    def test_1_structure_api(self):
        """GET /task-generator/bank/structure возвращает реальную древовидную структуру и статистику."""
        self._login_as_teacher()
        res = self.client.get('/task-generator/bank/structure')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertIn('stats', data)
        self.assertIn('total_tasks', data['stats'])
        self.assertIn('my_tasks', data['stats'])
        self.assertIn('bookmarked_tasks', data['stats'])
        self.assertIn('courses', data)
        self.assertIn('exam_tree', data)
        self.assertIn('python_tree', data)
        self.assertGreater(len(data['exam_tree']), 0)

    def test_2_toggle_bookmark_api(self):
        """POST /task-generator/bank/toggle-bookmark переключает закладку для преподавателя."""
        if not self.task_id:
            self.skipTest("No tasks available in database")

        self._login_as_teacher()

        # Clean existing bookmark if any
        with self.app.app_context():
            TaskBookmark.query.filter_by(user_id=self.teacher_id, task_id=self.task_id).delete()
            db.session.commit()

        # 1. Toggle ON
        res = self.client.post('/task-generator/bank/toggle-bookmark', json={'task_id': self.task_id})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertTrue(data['is_bookmarked'])

        with self.app.app_context():
            bm = TaskBookmark.query.filter_by(user_id=self.teacher_id, task_id=self.task_id).first()
            self.assertIsNotNone(bm)

        # 2. Toggle OFF
        res = self.client.post('/task-generator/bank/toggle-bookmark', json={'task_id': self.task_id})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertFalse(data['is_bookmarked'])

        with self.app.app_context():
            bm = TaskBookmark.query.filter_by(user_id=self.teacher_id, task_id=self.task_id).first()
            self.assertIsNone(bm)

    def test_3_save_set_api(self):
        """POST /task-generator/bank/save-set сохраняет подборку в TaskTemplate + TemplateTask."""
        if not self.task_id:
            self.skipTest("No tasks available in database")

        self._login_as_teacher()
        payload = {
            'title': 'Тестовая подборка Task Studio',
            'description': 'Проверка создания подборки из Task Studio',
            'task_ids': [self.task_id]
        }
        res = self.client.post('/task-generator/bank/save-set', json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertIn('template_id', data)
        tpl_id = data['template_id']

        with self.app.app_context():
            tpl = TaskTemplate.query.get(tpl_id)
            self.assertIsNotNone(tpl)
            self.assertEqual(tpl.name, 'Тестовая подборка Task Studio')
            tasks = TemplateTask.query.filter_by(template_id=tpl_id).all()
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0].task_id, self.task_id)

    def test_4_update_solution_api(self):
        """POST /task-generator/bank/<task_id>/update-solution обновляет разбор задачи."""
        if not self.task_id:
            self.skipTest("No tasks available in database")

        self._login_as_teacher()
        test_solution = "Эталонное решение: используем динамическое программирование O(N)."
        res = self.client.post(
            f'/task-generator/bank/{self.task_id}/update-solution',
            json={'solution': test_solution}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['solution'], test_solution)

        with self.app.app_context():
            sol = TaskSolution.query.filter_by(task_id=self.task_id).first()
            self.assertIsNotNone(sol)
            self.assertEqual(sol.solution_text, test_solution)

    def test_5_picker_list_sort_and_bookmark_filter(self):
        """GET /task-generator/bank/picker/list возвращает stats, sort и фильтрует по закладкам."""
        if not self.task_id:
            self.skipTest("No tasks available in database")

        self._login_as_teacher()

        # Add bookmark for test
        with self.app.app_context():
            TaskBookmark.query.filter_by(user_id=self.teacher_id, task_id=self.task_id).delete()
            db.session.add(TaskBookmark(user_id=self.teacher_id, task_id=self.task_id))
            db.session.commit()

        # Query with only_bookmarked
        res = self.client.get('/task-generator/bank/picker/list?only_bookmarked=true&sort=number_asc')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertIn('stats', data)
        self.assertIn('items', data)
        self.assertGreater(len(data['items']), 0)

        item = data['items'][0]
        self.assertIn('is_bookmarked', item)
        self.assertTrue(item['is_bookmarked'])
        self.assertIn('usage_count', item)
        self.assertIn('updated_at_formatted', item)

        # Clean up bookmark
        with self.app.app_context():
            TaskBookmark.query.filter_by(user_id=self.teacher_id, task_id=self.task_id).delete()
            db.session.commit()

class TestSyntheticDraftPickerSafety(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            teacher = User(username='synthetic-draft-picker-test', role='creator')
            db.session.add(teacher)
            db.session.commit()
            self.teacher_id = teacher.id

        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.teacher_id)
            sess['_fresh'] = True

    def test_synthetic_draft_tasks_only_show_in_verified_allowlist_mode(self):
        source_key = 'boostudy.synthetic.adaptive-v1/test/task-picker-allowlist'
        with self.app.app_context():
            task = Tasks(
                bank_category='synthetic_adaptive_draft',
                task_number=9999,
                source_key=source_key,
                content_html='<p>Synthetic draft picker security check</p>',
                answer='5',
                answer_spec={'type': 'short_answer'},
                created_by_id=self.teacher_id,
                is_active=True,
            )
            db.session.add(task)
            db.session.commit()
            task_id = task.task_id

        ordinary = self.client.get('/task-generator/bank/picker/list?per_page=100')
        self.assertEqual(ordinary.status_code, 200)
        self.assertNotIn(task_id, {item['task_id'] for item in ordinary.get_json()['items']})
        ordinary_all = self.client.get('/task-generator/bank/picker/list?per_page=100&bank_category=all')
        self.assertEqual(ordinary_all.status_code, 200)
        self.assertNotIn(task_id, {item['task_id'] for item in ordinary_all.get_json()['items']})

        with patch('app.ai_lab.database_safety.has_verified_safe_ai_lab_db', return_value=True), \
             patch('app.ai_lab.provider.is_local_ai_lab_enabled', return_value=True), \
             patch('app.ai_lab.platform_homework._allowlisted_user_ids', return_value=set()), \
             patch('app.ai_lab.platform_homework._allowlisted_actor_ids', return_value={self.teacher_id}), \
             patch('app.ai_lab.platform_homework._allowlisted_task_author_ids', return_value={self.teacher_id}):
            allowed = self.client.get('/task-generator/bank/picker/list?per_page=100')

        self.assertEqual(allowed.status_code, 200)
        items = {item['task_id']: item for item in allowed.get_json()['items']}
        self.assertIn(task_id, items)
        self.assertEqual(items[task_id]['bank_category'], 'synthetic_adaptive_draft')


if __name__ == '__main__':
    unittest.main()
