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
        assignment_task = AssignmentTask(
            assignment_id=assignment.assignment_id,
            task_id=task.task_id,
            order_index=0,
            max_score=1,
        )
        db.session.add(assignment_task)
        db.session.flush()
        submission = Submission(
            assignment_id=assignment.assignment_id,
            student_id=student.student_id,
            status='ASSIGNED',
        )
        db.session.add(submission)
        db.session.commit()
        assignment_id = assignment.assignment_id
        submission_id = submission.submission_id
        assignment_task_id = assignment_task.assignment_task_id

    login_as(client, role_users['student_user_id'], 'student')

    legacy_page = client.get(f'/sandbox/task_detail/{assignment_id}', follow_redirects=False)
    assert legacy_page.status_code == 302
    assert legacy_page.headers['Location'].endswith(f'/submissions/{submission_id}')

    canonical_entry = client.get(f'/submissions/{submission_id}', follow_redirects=False)
    assert canonical_entry.status_code == 302
    assert canonical_entry.headers['Location'].startswith('/task-workspace/?')
    assert f'context_id={submission_id}' in canonical_entry.headers['Location']
    assert f'assignment_task_id={assignment_task_id}' in canonical_entry.headers['Location']

    workspace = client.get(canonical_entry.headers['Location'])
    assert workspace.status_code == 200
    assert b'V2 assignment regression' in workspace.data

    login_as(client, role_users['tutor_id'], 'tutor')
    teacher_entry = client.get(f'/submissions/{submission_id}', follow_redirects=False)
    assert teacher_entry.status_code == 302
    assert teacher_entry.headers['Location'].endswith(f'/submissions/{submission_id}/grade')

    teacher_workspace_entry = client.get(teacher_entry.headers['Location'], follow_redirects=False)
    assert teacher_workspace_entry.status_code == 302
    assert teacher_workspace_entry.headers['Location'].startswith('/task-workspace/?')
    assert 'review=1' in teacher_workspace_entry.headers['Location']
    teacher_review = client.get(teacher_workspace_entry.headers['Location'])
    assert teacher_review.status_code == 200
    assert b'V2 assignment regression' in teacher_review.data

    retired_api = client.post(
        f'/sandbox/api/task_detail/{assignment_id}/submit_assignment',
        json={'answers': {}},
    )
    assert retired_api.status_code in {404, 405}


def test_student_with_grading_permission_keeps_owner_submission_workspace(app, client, role_users, monkeypatch):
    """A student who also has grading permission must not enter the teacher/student redirect loop."""
    with app.app_context():
        student = db.session.get(Student, role_users['student_id'])
        task = Tasks(task_number=1, content_html='<p>Dual-role regression</p>', answer='42')
        db.session.add(task)
        db.session.flush()
        assignment = Assignment(
            title='Dual-role submission regression',
            assignment_type='homework',
            created_by_id=role_users['tutor_id'],
            is_active=True,
            deadline=datetime.now(timezone.utc) + timedelta(days=1),
        )
        db.session.add(assignment)
        db.session.flush()
        assignment_task = AssignmentTask(
            assignment_id=assignment.assignment_id,
            task_id=task.task_id,
            order_index=0,
            max_score=1,
        )
        db.session.add(assignment_task)
        db.session.flush()
        submission = Submission(
            assignment_id=assignment.assignment_id,
            student_id=student.student_id,
            status='ASSIGNED',
        )
        db.session.add(submission)
        db.session.commit()
        submission_id = submission.submission_id
        assignment_task_id = assignment_task.assignment_task_id

    login_as(client, role_users['student_user_id'], 'student')
    monkeypatch.setattr('app.assignments.routes.has_permission', lambda _user, _permission: True)

    entry = client.get(f'/submissions/{submission_id}', follow_redirects=False)

    assert entry.status_code == 302
    assert entry.headers['Location'].startswith('/task-workspace/?')
    assert f'context_id={submission_id}' in entry.headers['Location']
    assert f'assignment_task_id={assignment_task_id}' in entry.headers['Location']
    workspace = client.get(entry.headers['Location'])
    assert workspace.status_code == 200
    assert b'Dual-role submission regression' in workspace.data


def test_student_flag_does_not_redirect_privileged_reviewer_back_to_submission(app, client, role_users, monkeypatch):
    """A privileged dual-role reviewer may review another student's submission."""
    from app.models import User

    with app.app_context():
        task = Tasks(task_number=1, content_html='<p>Reviewer route regression</p>', answer='42')
        db.session.add(task)
        db.session.flush()
        assignment = Assignment(
            title='Reviewer route regression',
            assignment_type='homework',
            created_by_id=role_users['tutor_id'],
            is_active=True,
            deadline=datetime.now(timezone.utc) + timedelta(days=1),
        )
        db.session.add(assignment)
        db.session.flush()
        assignment_task = AssignmentTask(
            assignment_id=assignment.assignment_id,
            task_id=task.task_id,
            order_index=0,
            max_score=1,
        )
        db.session.add(assignment_task)
        db.session.flush()
        submission = Submission(
            assignment_id=assignment.assignment_id,
            student_id=role_users['student_id'],
            status='ASSIGNED',
        )
        db.session.add(submission)
        db.session.commit()
        submission_id = submission.submission_id

    original_is_student = User.is_student
    monkeypatch.setattr(
        User,
        'is_student',
        lambda user: True if user.id == role_users['tutor_id'] else original_is_student(user),
    )
    monkeypatch.setattr('app.assignments.routes._can_current_user_access_submission', lambda _submission: True)
    login_as(client, role_users['tutor_id'], 'tutor')

    entry = client.get(f'/submissions/{submission_id}', follow_redirects=False)
    assert entry.status_code == 302
    assert entry.headers['Location'].endswith(f'/submissions/{submission_id}/grade')

    review = client.get(f'/submissions/{submission_id}/grade?legacy=1', follow_redirects=False)
    assert review.status_code == 200
    assert b'Reviewer route regression' in review.data
