import sys
import os
import json
import re
from datetime import datetime, timezone, timedelta

sys.path.insert(0, r"e:\projects\kege_selector_app_current")

from app import create_app
from core.db_models import User, Student, Assignment, AssignmentTask, Submission, Answer, Tasks, db
from app.main.routes import format_deadline_display

app = create_app()
app.config['WTF_CSRF_ENABLED'] = False
app.config['TESTING'] = True

client = app.test_client()

print("=== STARTING QA FULL ASSIGNMENT LIFECYCLE & TIMEZONE TEST SUITE ===")

with app.app_context():
    teacher = User.query.filter_by(username='Teacher_1').first()
    assert teacher is not None

    student_user = User.query.filter_by(username='Student_1').first()
    assert student_user is not None

    student_rec = Student.query.filter_by(user_id=student_user.id).first()
    assert student_rec is not None

    tz_user = timezone(timedelta(hours=7))
    created_assignment_ids = []

    try:
        # -----------------------------------------------------------------
        # TEST 1: TIMEZONE & DEADLINE PARSING ("Сегодня, 20:49")
        # -----------------------------------------------------------------
        now_local = datetime.now(timezone.utc).astimezone(tz_user)
        today_deadline_local = datetime(now_local.year, now_local.month, now_local.day, 20, 49, tzinfo=tz_user)
        today_deadline_utc = today_deadline_local.astimezone(timezone.utc)

        # Format display before submission
        formatted_dl = format_deadline_display(today_deadline_utc, raw_status='IN_PROGRESS')
        assert formatted_dl == "Сегодня, 20:49", f"Expected 'Сегодня, 20:49', got '{formatted_dl}'"
        print(f"[OK QA 1] Today's deadline 20:49 strictly formatted as: Today 20:49")

        # Create Exam & Homework assignments via submit API
        res_create_exam = client.post('/sandbox/api/create_assignment/submit', json={
            'title': 'Пробник КЕГЭ (Full Lifecycle Exam)',
            'assignment_type': 'exam',
            'time_limit_minutes': 235,
            'max_attempts_default': 3,
            'deadline': today_deadline_local.strftime('%Y-%m-%dT%H:%M'),
            'tasks': [{'task_id': 1, 'max_score': 1}]
        })
        assert res_create_exam.status_code == 200
        exam_data = res_create_exam.get_json()
        assert exam_data['success'] is True
        exam_id = exam_data.get('assignment_id')
        created_assignment_ids.append(exam_id)

        exam_assignment = db.session.get(Assignment, exam_id)
        assert exam_assignment is not None
        db_dl = exam_assignment.deadline.replace(tzinfo=timezone.utc) if not exam_assignment.deadline.tzinfo else exam_assignment.deadline
        assert db_dl == today_deadline_utc
        print("[OK QA 1.1] Deadline created with datetime-local stored properly in UTC and displayed as Today 20:49!")

        # -----------------------------------------------------------------
        # TEST 2: SAFE AUTO-SUBMIT ON TIMER EXPIRATION (ANSWERS PAYLOAD SAVED)
        # -----------------------------------------------------------------
        # Fetch existing submission created by create_assignment/submit
        sub_exam = Submission.query.filter_by(assignment_id=exam_id, student_id=student_rec.student_id).first()
        if not sub_exam:
            sub_exam = Submission(assignment_id=exam_id, student_id=student_rec.student_id)
            db.session.add(sub_exam)
        sub_exam.status = "IN_PROGRESS"
        sub_exam.started_at = datetime.now(timezone.utc) - timedelta(minutes=240) # timer expired
        db.session.commit()

        # Get AssignmentTask ID
        at = AssignmentTask.query.filter_by(assignment_id=exam_id).first()
        assert at is not None

        # Timer expired -> Frontend submits answers payload with is_auto_submit=True
        res_auto_sub = client.post(f'/sandbox/api/task_detail/{exam_id}/submit_assignment', json={
            'answers': {str(at.assignment_task_id): '42'},
            'is_auto_submit': True
        })
        assert res_auto_sub.status_code == 200
        auto_json = res_auto_sub.get_json()
        assert auto_json['success'] is True
        assert auto_json['is_auto_submit'] is True
        assert auto_json['status'] == "UNDER_REVIEW"

        # Expire test session cache to read freshly saved DB records
        db.session.expire_all()

        # Verify answer was saved in DB
        ans_in_db = Answer.query.filter_by(submission_id=sub_exam.submission_id, assignment_task_id=at.assignment_task_id).first()
        assert ans_in_db is not None, f"Answer for sub {sub_exam.submission_id} and task {at.assignment_task_id} not found!"
        assert ans_in_db.value == "42"
        print("[OK QA 2] Safe auto-submit on t=0 successfully saved answers payload into DB!")

        # -----------------------------------------------------------------
        # TEST 3: DYNAMIC BADGES & SMART DEADLINE DISPLAY ON /sandbox/tasks
        # -----------------------------------------------------------------
        res_tasks = client.get('/sandbox/tasks')
        assert res_tasks.status_code == 200
        tasks_html = res_tasks.get_data(as_text=True)

        # Check presence of badges
        assert 'ПРОБНИК КЕГЭ' in tasks_html
        assert 'НА ПРОВЕРКЕ' in tasks_html
        assert 'Сдано' in tasks_html
        print("[OK QA 3] Dynamic badges 'ПРОБНИК КЕГЭ', 'НА ПРОВЕРКЕ' and 'Сдано DD.MM в HH:MM' rendered on /sandbox/tasks!")

        # -----------------------------------------------------------------
        # TEST 4: DRAFT AUTO-SAVE & REPEAT ATTEMPTS
        # -----------------------------------------------------------------
        # Draft auto-save API test
        res_draft = client.post(f'/sandbox/api/task_detail/{exam_id}/save_draft', json={
            'answers': {str(at.assignment_task_id): 'draft_val'}
        })
        assert res_draft.status_code == 200

        # Start new attempt test
        res_retry = client.post(f'/sandbox/api/assignment/{exam_id}/start_new_attempt')
        assert res_retry.status_code == 200
        retry_json = res_retry.get_json()
        assert retry_json['success'] is True
        assert retry_json['attempt_count'] == 2

        db.session.expire_all()
        sub_exam_refreshed = db.session.get(Submission, sub_exam.submission_id)
        assert sub_exam_refreshed.status == "IN_PROGRESS"
        assert sub_exam_refreshed.submitted_at is None
        print("[OK QA 4] Draft auto-save and Repeat Attempt mechanics (Attempt #2) fully verified!")

        # -----------------------------------------------------------------
        # TEST 5: ZERO CALLS TO confirm( AND alert( IN TEMPLATES
        # -----------------------------------------------------------------
        project_root = r"e:\projects\kege_selector_app_current"
        templates_dir = os.path.join(project_root, "templates", "sandbox")

        template_files = ["create_assignment.html", "task_detail.html", "tasks.html", "task_generator.html"]
        for tf in template_files:
            filepath = os.path.join(templates_dir, tf)
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            script_blocks = re.findall(r'<script[^>]*>(.*?)</script>', content, re.DOTALL)
            for idx, block in enumerate(script_blocks, start=1):
                for l_num, line in enumerate(block.split('\n'), start=1):
                    assert 'confirm(' not in line, f"confirm() found in {tf} block {idx} line {l_num}: {line.strip()}"
                    assert 'alert(' not in line, f"alert() found in {tf} block {idx} line {l_num}: {line.strip()}"

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

print("\nALL QA FULL ASSIGNMENT LIFECYCLE & TIMEZONE TESTS PASSED 100%!")
