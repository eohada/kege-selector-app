"""Canonical V2 regression for student assignment entry points.

This replaced an executable QA script that queried a developer database at
import time and exercised retired `/sandbox/api/task_detail/*` endpoints.
"""

from datetime import datetime, timedelta, timezone

from app.models import Assignment, AssignmentTask, Student, Submission, Tasks, db

from .conftest import login_as


def test_student_assignment_uses_v2_submission_surface(app, client, role_users):
    with app.app_context():
        tutor_id = role_users['tutor_id']
        student = db.session.get(Student, role_users['student_id'])
        task = Tasks(task_number=1, content_html='<p>V2 task</p>', answer='42')
        db.session.add(task)
        db.session.flush()

        assignment = Assignment(
            title='V2 assignment regression',
            assignment_type='homework',
            created_by_id=tutor_id,
            is_active=True,
            deadline=datetime.now(timezone.utc) + timedelta(days=1),
        )
        db.session.add(assignment)
        db.session.flush()
        db.session.add(AssignmentTask(
            assignment_id=assignment.assignment_id,
            task_id=task.task_id,
            order_index=0,
            max_score=1,
        ))
        submission = Submission(
            assignment_id=assignment.assignment_id,
            student_id=student.student_id,
            status='ASSIGNED',
        )
        db.session.add(submission)
        db.session.commit()
        assignment_id = assignment.assignment_id
        submission_id = submission.submission_id

    login_as(client, role_users['student_user_id'], 'student')

    legacy_page = client.get(f'/sandbox/task_detail/{assignment_id}', follow_redirects=False)
    assert legacy_page.status_code == 302
    assert legacy_page.headers['Location'].endswith(f'/submissions/{submission_id}')

    canonical_page = client.get(f'/submissions/{submission_id}')
    assert canonical_page.status_code == 200
    assert b'V2 assignment regression' in canonical_page.data

    retired_api = client.post(
        f'/sandbox/api/task_detail/{assignment_id}/submit_assignment',
        json={'answers': {}},
    )
    assert retired_api.status_code in {404, 405}
