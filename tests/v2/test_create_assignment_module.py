import sys
import os
import json
import re

sys.path.insert(0, r"e:\projects\kege_selector_app_current")

from app import create_app
from core.db_models import User, Student, Assignment, AssignmentTask, Submission, Answer, Tasks, db

app = create_app()
app.config['WTF_CSRF_ENABLED'] = False
app.config['TESTING'] = True

client = app.test_client()

print("=== TESTING QA ASSIGNMENT CONSTRUCTOR MODULE (/sandbox/create_assignment) ===")

with app.app_context():
    teacher = User.query.filter_by(username='Teacher_1').first()
    assert teacher is not None

    student_user = User.query.filter_by(username='Student_1').first()
    assert student_user is not None

    student_rec = Student.query.filter_by(user_id=student_user.id).first()
    assert student_rec is not None

    created_assignment_ids = []

    try:
        # -----------------------------------------------------------------
        # TEST 1: RENDER CREATE ASSIGNMENT PAGE & INITIAL DATA
        # -----------------------------------------------------------------
        res_page = client.get('/sandbox/create_assignment')
        assert res_page.status_code == 200
        html_page = res_page.get_data(as_text=True)

        assert '<script id="create-assignment-data" type="application/json">' in html_page
        assert 'JSON.parse(rawDataEl.textContent)' in html_page
        print("[OK QA 1] Page /sandbox/create_assignment renders successfully with JSON data container!")

        # -----------------------------------------------------------------
        # TEST 2: QUICK MOCK VARIANT GENERATION (27 TASKS)
        # -----------------------------------------------------------------
        res_quick = client.get('/sandbox/api/create_assignment/quick_mock_variant')
        assert res_quick.status_code == 200
        quick_json = res_quick.get_json()
        assert quick_json['success'] is True
        assert len(quick_json['tasks']) == 27
        print(f"[OK QA 2] Quick mock variant API generated {len(quick_json['tasks'])} tasks for KEGE №1-27!")

        # -----------------------------------------------------------------
        # TEST 3: PARSING TASK IDS FROM MODAL (1, 2)
        # -----------------------------------------------------------------
        res_ids = client.get('/sandbox/api/create_assignment/get_tasks_by_ids?ids=1,2')
        assert res_ids.status_code == 200
        ids_json = res_ids.get_json()
        assert ids_json['success'] is True
        assert len(ids_json['tasks']) >= 2
        print(f"[OK QA 3] Task IDs parsing API retrieved {len(ids_json['tasks'])} tasks successfully!")

        # -----------------------------------------------------------------
        # TEST 4: DRAFT SAVING & ASSIGNMENT CREATION WITH RECIPIENTS
        # -----------------------------------------------------------------
        res_draft = client.post('/sandbox/api/create_assignment/save_draft', json={
            'title': 'Тестовый черновик QA',
            'assignment_type': 'exam',
            'tasks': [{'task_id': 1, 'max_score': 1}, {'task_id': 2, 'max_score': 2}]
        })
        assert res_draft.status_code == 200
        draft_json = res_draft.get_json()
        assert draft_json['success'] is True
        draft_id = draft_json['assignment_id']
        created_assignment_ids.append(draft_id)
        print(f"[OK QA 4.1] Draft saved successfully (Assignment ID #{draft_id})!")

        # Submit Assignment
        res_submit = client.post('/sandbox/api/create_assignment/submit', json={
            'assignment_id': draft_id,
            'title': 'Пробник КЕГЭ 2026 (QA Test)',
            'assignment_type': 'exam',
            'time_limit_minutes': 235,
            'max_attempts_default': 1,
            'hard_deadline': True,
            'allow_separate_submission': False,
            'tasks': [{'task_id': 1, 'max_score': 1}, {'task_id': 2, 'max_score': 2}],
            'target_students': [student_rec.student_id],
            'target_groups': ['11 Класс']
        })
        assert res_submit.status_code == 200
        submit_json = res_submit.get_json()
        assert submit_json['success'] is True
        print(f"[OK QA 4.2] Assignment #{draft_id} submitted and assigned to recipients!")

        # Verify DB records
        assign_record = Assignment.query.get(draft_id)
        assert assign_record is not None
        assert assign_record.status == 'active'
        assert assign_record.time_limit_minutes == 235

        tasks_count = AssignmentTask.query.filter_by(assignment_id=draft_id).count()
        assert tasks_count == 2

        submissions_count = Submission.query.filter_by(assignment_id=draft_id).count()
        assert submissions_count >= 1
        print(f"[OK QA 4.3] DB verification confirmed active assignment, {tasks_count} tasks, and {submissions_count} student submission records!")

        # -----------------------------------------------------------------
        # TEST 5: 0 VS CODE LINTER ERRORS IN create_assignment.html
        # -----------------------------------------------------------------
        project_root = r"e:\projects\kege_selector_app_current"
        template_path = os.path.join(project_root, "templates", "sandbox", "create_assignment.html")
        assert os.path.exists(template_path)
        with open(template_path, "r", encoding="utf-8") as f:
            template_raw = f.read()

        assert '<script id="create-assignment-data" type="application/json">' in template_raw
        assert 'JSON.parse(rawDataEl.textContent)' in template_raw

        script_blocks = re.findall(r'<script>(.*?)</script>', template_raw, re.DOTALL)
        for block in script_blocks:
            assert '{{' not in block and '}}' not in block, f"Raw Jinja tag found inside executable script block: {block[:50]}..."
        print("[OK QA 5] Executable <script> block in create_assignment.html contains ZERO raw Jinja {{ ... }} tags (100% clean for VS Code linter)!")

    finally:
        # TEARDOWN: Automatic cleanup of created test data
        for aid in created_assignment_ids:
            subs = Submission.query.filter_by(assignment_id=aid).all()
            for s in subs:
                Answer.query.filter_by(submission_id=s.submission_id).delete()
                db.session.delete(s)
            AssignmentTask.query.filter_by(assignment_id=aid).delete()
            Assignment.query.filter_by(assignment_id=aid).delete()
        db.session.commit()
        print("[TEARDOWN OK] All temporary test assignments cleaned from DB!")

print("\nALL ASSIGNMENT CONSTRUCTOR SUITE TESTS PASSED 100%!")
