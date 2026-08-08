import sys
import os
import json
import re
from datetime import datetime, timezone, timedelta

sys.path.insert(0, r"e:\projects\kege_selector_app_current")

from app import create_app
from core.db_models import User, Student, Assignment, AssignmentTask, Submission, Answer, Tasks, db

app = create_app()
app.config['WTF_CSRF_ENABLED'] = False
app.config['TESTING'] = True

client = app.test_client()

print("=== STARTING QA ASSIGNMENT DETAILS & MANAGEMENT TEST SUITE ===")

with app.app_context():
    teacher = User.query.filter_by(username='Teacher_1').first()
    assert teacher is not None, "Teacher_1 user not found in DB!"

    created_assignment_ids = []

    try:
        # Create a test assignment in DB
        a = Assignment(
            title="Тестовая работа QA Details",
            assignment_type="exam",
            status="active",
            created_by_id=teacher.id,
            time_limit_minutes=120,
            max_attempts_default=2,
            hard_deadline=True,
            allow_separate_submission=False,
            deadline=datetime.now(timezone.utc) + timedelta(days=3)
        )
        db.session.add(a)
        db.session.commit()
        assignment_id = a.assignment_id
        created_assignment_ids.append(assignment_id)

        # Attach 1 task to this assignment
        t1 = Tasks.query.filter_by(is_active=True).first()
        if not t1:
            t1 = Tasks(task_number=14, topic="Динамика", answer="4096", max_score=1, is_active=True)
            db.session.add(t1)
            db.session.commit()

        at1 = AssignmentTask(
            assignment_id=assignment_id,
            task_id=t1.task_id,
            order_index=1,
            max_score=1,
            answer_override="4096"
        )
        db.session.add(at1)
        db.session.commit()

        # -----------------------------------------------------------------
        # TEST 1: GET /sandbox/assignment/<id>/details
        # -----------------------------------------------------------------
        res_get = client.get(f'/sandbox/assignment/{assignment_id}/details')
        assert res_get.status_code == 200, f"Expected 200, got {res_get.status_code}"
        html = res_get.get_data(as_text=True)
        assert 'assignment-details-data' in html, "JSON container missing from details HTML!"
        assert 'QA Details' in html, "Assignment title fragment missing from HTML!"
        print("[OK QA 1] GET /sandbox/assignment/<id>/details rendered 200 OK with JSON container!")

        # -----------------------------------------------------------------
        # TEST 2: POST /sandbox/api/assignment/<id>/update
        # -----------------------------------------------------------------
        res_update = client.post(f'/sandbox/api/assignment/{assignment_id}/update', json={
            'title': 'Тестовая работа QA Details (Обновлена)',
            'assignment_type': 'homework',
            'time_limit_minutes': 90,
            'max_attempts_default': 3,
            'hard_deadline': False,
            'allow_separate_submission': True,
            'deadline': '2026-07-30T23:59',
            'tasks': [
                {
                    'assignment_task_id': at1.assignment_task_id,
                    'max_score': 2,
                    'answer_override': '8192'
                }
            ]
        })
        assert res_update.status_code == 200
        update_data = res_update.get_json()
        assert update_data['success'] is True

        # Refresh DB session & verify updates
        db.session.expire_all()
        updated_a = db.session.get(Assignment, assignment_id)
        assert updated_a.title == 'Тестовая работа QA Details (Обновлена)'
        assert updated_a.time_limit_minutes == 90
        assert updated_a.max_attempts_default == 3
        assert updated_a.hard_deadline is False
        assert updated_a.allow_separate_submission is True

        updated_at1 = db.session.get(AssignmentTask, at1.assignment_task_id)
        assert updated_at1.max_score == 2
        assert updated_at1.answer_override == '8192'
        print("[OK QA 2] POST /sandbox/api/assignment/<id>/update successfully updated title, deadline, score & answer_override!")

        # -----------------------------------------------------------------
        # TEST 3: POST /sandbox/api/assignment/<id>/add_random_task
        # -----------------------------------------------------------------
        res_add_task = client.post(f'/sandbox/api/assignment/{assignment_id}/add_random_task')
        assert res_add_task.status_code == 200
        add_data = res_add_task.get_json()
        assert add_data['success'] is True
        added_at_id = add_data['assignment_task_id']
        print(f"[OK QA 3] POST /sandbox/api/assignment/<id>/add_random_task added assignment_task_id {added_at_id}!")

        # -----------------------------------------------------------------
        # TEST 4: POST /sandbox/api/assignment/<id>/remove_task/<at_id>
        # -----------------------------------------------------------------
        res_remove = client.post(f'/sandbox/api/assignment/{assignment_id}/remove_task/{added_at_id}')
        assert res_remove.status_code == 200
        remove_data = res_remove.get_json()
        assert remove_data['success'] is True
        db.session.expire_all()
        assert db.session.get(AssignmentTask, added_at_id) is None
        print("[OK QA 4] POST /sandbox/api/assignment/<id>/remove_task/<at_id> successfully deleted task!")

        # -----------------------------------------------------------------
        # TEST 5: POST /sandbox/api/assignment/<id>/duplicate
        # -----------------------------------------------------------------
        res_dup = client.post(f'/sandbox/api/assignment/{assignment_id}/duplicate')
        assert res_dup.status_code == 200
        dup_data = res_dup.get_json()
        assert dup_data['success'] is True
        new_a_id = dup_data['new_assignment_id']
        created_assignment_ids.append(new_a_id)
        dup_a = db.session.get(Assignment, new_a_id)
        assert dup_a is not None
        assert dup_a.status == 'draft'
        assert 'Копия' in dup_a.title
        print(f"[OK QA 5] POST /sandbox/api/assignment/<id>/duplicate created draft copy with ID {new_a_id}!")

        # -----------------------------------------------------------------
        # TEST 6: POST /sandbox/api/assignment/<id>/archive
        # -----------------------------------------------------------------
        res_arch = client.post(f'/sandbox/api/assignment/{assignment_id}/archive')
        assert res_arch.status_code == 200
        arch_data = res_arch.get_json()
        assert arch_data['success'] is True
        db.session.expire_all()
        arch_a = db.session.get(Assignment, assignment_id)
        assert arch_a.status == 'archived'
        print("[OK QA 6] POST /sandbox/api/assignment/<id>/archive marked assignment as archived!")

        # -----------------------------------------------------------------
        # TEST 7: ZERO confirm() and alert() CALLS IN TEMPLATE
        # -----------------------------------------------------------------
        filepath = os.path.join(r"e:\projects\kege_selector_app_current", "templates", "sandbox", "assignment_details.html")
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        script_blocks = re.findall(r'<script[^>]*>(.*?)</script>', content, re.DOTALL)
        for idx, block in enumerate(script_blocks, start=1):
            for l_num, line in enumerate(block.split('\n'), start=1):
                assert 'confirm(' not in line, f"confirm() found in assignment_details.html block {idx} line {l_num}: {line.strip()}"
                assert 'alert(' not in line, f"alert() found in assignment_details.html block {idx} line {l_num}: {line.strip()}"

        print("[OK QA 7] Strictly 0 calls to confirm( and alert( in assignment_details.html template!")

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

print("\nALL QA ASSIGNMENT DETAILS & MANAGEMENT TESTS PASSED 100%!")
