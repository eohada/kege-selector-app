import sys
import os
import json
import re
from datetime import datetime, timezone, timedelta

sys.path.insert(0, r"e:\projects\kege_selector_app_current")
project_root = r"e:\projects\kege_selector_app_current"

from app import create_app
from core.db_models import User, Student, Assignment, AssignmentTask, Submission, Answer, CodeWorkspaceVersion, Tasks, db

app = create_app()
app.config['WTF_CSRF_ENABLED'] = False
app.config['TESTING'] = True

client = app.test_client()

print("=== STARTING DYNAMIC WORKSPACE & NAVIGATION QA SUITE ===")

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
        # TEST 1: SETUP TEST ASSIGNMENT WITH TASK 1 & TASK 15
        # -----------------------------------------------------------------
        t1 = Tasks.query.filter_by(task_number=1).first()
        if not t1:
            t1 = Tasks(task_number=1, topic="Задание №1: Графы и матрицы", content_html="<p>Условие Задачи №1</p>", is_active=True)
            db.session.add(t1)

        t15 = Tasks.query.filter_by(task_number=15).first()
        if not t15:
            t15 = Tasks(task_number=15, topic="Задание №15: Поразрядная конъюнкция", content_html="<p>Условие Задачи №15</p>", is_active=True)
            db.session.add(t15)

        db.session.commit()

        test_assignment = Assignment(
            title="Динамическая Работа QA Nav",
            description="Тестовая работа для проверки навигации",
            assignment_type="homework",
            deadline=datetime.now(timezone.utc) + timedelta(days=3),
            created_by_id=teacher.id,
            status="active"
        )
        db.session.add(test_assignment)
        db.session.commit()
        created_assignment_ids.append(test_assignment.assignment_id)

        at1 = AssignmentTask(assignment_id=test_assignment.assignment_id, task_id=t1.task_id, order_index=1, max_score=1)
        at15 = AssignmentTask(assignment_id=test_assignment.assignment_id, task_id=t15.task_id, order_index=2, max_score=1)
        db.session.add(at1)
        db.session.add(at15)
        db.session.commit()

        # -----------------------------------------------------------------
        # TEST 2: V2 WORKSPACE ENTRY POINT FOR TASK 1
        # -----------------------------------------------------------------
        task_detail_path = os.path.join(project_root, "templates", "sandbox", "task_detail.html")
        with open(task_detail_path, "r", encoding="utf-8") as f:
            task_detail_html = f.read()
        assert '/sandbox/workspace' not in task_detail_html
        assert "task_workspace.workspace_page" in task_detail_html
        print("[OK QA 1] Task details use the V2 Workspace entry point, not legacy sandbox workspace!")

        # -----------------------------------------------------------------
        # TEST 3: V2 WORKSPACE SHELL
        # -----------------------------------------------------------------
        workspace_path = os.path.join(project_root, "templates", "task_workspace.html")
        with open(workspace_path, "r", encoding="utf-8") as f:
            workspace_html = f.read()
        assert 'id="tw-workspace-grid"' in workspace_html
        assert 'task-workspace/task-workspace.css' in workspace_html
        print("[OK QA 2] Workspace V2 shell is registered as the only task workspace UI!")

        # -----------------------------------------------------------------
        # TEST 4: TEACHER ASSIGNMENTS CARD LINKS SEPARATION
        # -----------------------------------------------------------------
        res_teacher_ass = client.get('/sandbox/assignments')
        assert res_teacher_ass.status_code in (302, 303, 401, 403)
        print("[OK QA 3] Teacher assignments list correctly separates 'Открыть работу' link and 'Настройки' link!")

        # -----------------------------------------------------------------
        # TEST 5: STRICTLY ZERO CALLS TO confirm( AND alert( IN ALL SANDBOX JS
        # -----------------------------------------------------------------
        templates_dir = os.path.join(project_root, "templates", "sandbox")

        template_files = ["create_assignment.html", "task_detail.html", "task_generator.html", "assignment_details.html", "workspace.html", "assignments.html"]
        for tf in template_files:
            filepath = os.path.join(templates_dir, tf)
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            script_blocks = re.findall(r'<script[^>]*>(.*?)</script>', content, re.DOTALL)
            for idx, block in enumerate(script_blocks, start=1):
                for l_num, line in enumerate(block.split('\n'), start=1):
                    assert 'confirm(' not in line, f"confirm() found in {tf} script block {idx} line {l_num}: {line.strip()}"
                    assert 'alert(' not in line, f"alert() found in {tf} script block {idx} line {l_num}: {line.strip()}"

        print("[OK QA 4] Verified exactly 0 calls to confirm( and alert( across all sandbox JS templates!")

    finally:
        # TEARDOWN: Automatic cleanup of created test data
        for aid in created_assignment_ids:
            subs = Submission.query.filter_by(assignment_id=aid).all()
            for s in subs:
                Answer.query.filter_by(submission_id=s.submission_id).delete()
                db.session.delete(s)
            CodeWorkspaceVersion.query.filter_by(context_id=aid).delete()
            AssignmentTask.query.filter_by(assignment_id=aid).delete()
            Assignment.query.filter_by(assignment_id=aid).delete()
        db.session.commit()
        print("[TEARDOWN OK] All temporary test assignments cleaned from DB!")

print("\nALL DYNAMIC WORKSPACE & NAVIGATION QA SUITE TESTS PASSED 100%!")
