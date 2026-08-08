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

print("=== TESTING QA STUDENT ASSIGNMENT LOGIC & 3D MODAL SUITE ===")

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
        # TEST 1 & 2: EXAM TIMED ASSIGNMENT, START STATUS, REMAINING_SECONDS & MAX_ATTEMPTS
        # -----------------------------------------------------------------
        exam_assignment = Assignment(
            title="Пробник КЕГЭ 2026 (Timed QA Exam)",
            assignment_type="exam",
            deadline=datetime.now(timezone.utc) + timedelta(days=7),
            time_limit_minutes=235,
            max_attempts_default=3,
            allow_separate_submission=False,
            created_by_id=teacher.id,
            status="active"
        )
        db.session.add(exam_assignment)
        db.session.commit()
        created_assignment_ids.append(exam_assignment.assignment_id)

        at1 = AssignmentTask(assignment_id=exam_assignment.assignment_id, task_id=1, order_index=1, max_score=1)
        db.session.add(at1)

        sub_exam = Submission(
            assignment_id=exam_assignment.assignment_id,
            student_id=student_rec.student_id,
            status="ASSIGNED"
        )
        db.session.add(sub_exam)
        db.session.commit()

        # Call start API
        res_start = client.post(f'/sandbox/api/assignment/{exam_assignment.assignment_id}/start')
        assert res_start.status_code == 200
        start_json = res_start.get_json()

        assert start_json['success'] is True
        assert start_json['status'] == "IN_PROGRESS"
        assert start_json['remaining_seconds'] > 0
        assert start_json['remaining_seconds'] <= 235 * 60

        # Verify DB submission status is IN_PROGRESS (not SUBMITTED)
        db.session.refresh(sub_exam)
        assert sub_exam.status == "IN_PROGRESS"
        assert sub_exam.started_at is not None
        print(f"[OK QA 1] Exam start API set status=IN_PROGRESS and remaining_seconds={start_json['remaining_seconds']} > 0!")

        # Verify task detail page rendering
        res_detail = client.get(f'/sandbox/task_detail/{exam_assignment.assignment_id}')
        assert res_detail.status_code == 200
        html_detail = res_detail.get_data(as_text=True)

        assert 'Попытки: 0/3' in html_detail
        assert 'submit-confirm-modal' in html_detail
        print("[OK QA 2] max_attempts_default=3 correctly saved and displayed as 'Попытки: 0/3' with 3D modal!")

        # -----------------------------------------------------------------
        # TEST 3: HOMEWORK SUBMISSION (HW -> COMPLETED & REVEAL ANSWERS)
        # -----------------------------------------------------------------
        hw_assignment = Assignment(
            title="Домашка по КЕГЭ (HW QA)",
            assignment_type="homework",
            deadline=datetime.now(timezone.utc) + timedelta(days=7),
            max_attempts_default=3,
            allow_separate_submission=True,
            created_by_id=teacher.id,
            status="active"
        )
        db.session.add(hw_assignment)
        db.session.commit()
        created_assignment_ids.append(hw_assignment.assignment_id)

        at2 = AssignmentTask(assignment_id=hw_assignment.assignment_id, task_id=1, order_index=1, max_score=1)
        db.session.add(at2)

        sub_hw = Submission(
            assignment_id=hw_assignment.assignment_id,
            student_id=student_rec.student_id,
            status="IN_PROGRESS"
        )
        db.session.add(sub_hw)
        db.session.commit()

        # Submit HW
        res_sub_hw = client.post(f'/sandbox/api/task_detail/{hw_assignment.assignment_id}/submit_assignment', json={})
        assert res_sub_hw.status_code == 200
        sub_hw_json = res_sub_hw.get_json()
        assert sub_hw_json['success'] is True
        assert sub_hw_json['status'] == "COMPLETED"

        db.session.refresh(sub_hw)
        assert sub_hw.status == "COMPLETED"
        print("[OK QA 3] Homework submission transitioned status to COMPLETED!")

        # Verify answers revealed on page render for completed homework
        res_hw_detail = client.get(f'/sandbox/task_detail/{hw_assignment.assignment_id}')
        assert res_hw_detail.status_code == 200
        hw_html = res_hw_detail.get_data(as_text=True)
        assert '"show_answers": true' in hw_html
        print("[OK QA 3.1] Completed Homework reveals answers to student!")

        # -----------------------------------------------------------------
        # TEST 4: EXAM SUBMISSION (EXAM -> UNDER_REVIEW & HIDE ANSWERS)
        # -----------------------------------------------------------------
        res_sub_exam = client.post(f'/sandbox/api/task_detail/{exam_assignment.assignment_id}/submit_assignment', json={})
        assert res_sub_exam.status_code == 200
        exam_sub_json = res_sub_exam.get_json()
        assert exam_sub_json['success'] is True
        assert exam_sub_json['status'] == "UNDER_REVIEW"

        db.session.refresh(sub_exam)
        assert sub_exam.status == "UNDER_REVIEW"
        print("[OK QA 4] Exam submission transitioned status to UNDER_REVIEW (Сдано на проверку)!")

        # -----------------------------------------------------------------
        # TEST 5: ZERO CALLS TO confirm( AND alert( IN TEMPLATE JS
        # -----------------------------------------------------------------
        project_root = r"e:\projects\kege_selector_app_current"
        templates_dir = os.path.join(project_root, "templates", "sandbox")

        template_files = ["create_assignment.html", "task_detail.html", "task_generator.html"]
        for tf in template_files:
            filepath = os.path.join(templates_dir, tf)
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            script_blocks = re.findall(r'<script[^>]*>(.*?)</script>', content, re.DOTALL)
            for idx, block in enumerate(script_blocks, start=1):
                for l_num, line in enumerate(block.split('\n'), start=1):
                    assert 'confirm(' not in line, f"confirm() found in {tf} script block {idx} line {l_num}: {line.strip()}"
                    assert 'alert(' not in line, f"alert() found in {tf} script block {idx} line {l_num}: {line.strip()}"

        print("[OK QA 5] Verified exactly 0 calls to confirm( and alert( across all sandbox JS templates!")

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

print("\nALL QA STUDENT ASSIGNMENT & 3D MODAL SUITE TESTS PASSED 100%!")
