from datetime import timedelta


def _login_as(client, user_id: int, role: str) -> None:
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True
        session['sandbox_role'] = role


def test_assignment_lifecycle_uses_only_canonical_v2_endpoints(app, client, role_users):
    """Teacher assignment → student work → manual grading is persisted end to end."""
    from app import db
    from core.db_models import AssignmentTask, Submission, Tasks, utc_now

    with app.app_context():
        task = Tasks.query.order_by(Tasks.task_id.asc()).first()
        if task is None:
            task = Tasks(task_number=1, content_html='Release fixture task', answer='42')
            db.session.add(task)
            db.session.commit()
        task_id = task.task_id

    _login_as(client, role_users['tutor_id'], 'tutor')
    distributed = client.post('/assignments/distribute', json={
        'title': 'Release assignment lifecycle',
        'type': 'homework',
        'recipientIds': [role_users['student_id']],
        'tasks': [{'task_id': task_id, 'max_score': 1}],
        'deadline': (utc_now() + timedelta(days=2)).isoformat(),
    })
    assert distributed.status_code == 201, distributed.get_json()
    assignment_id = distributed.get_json()['assignment_id']

    with app.app_context():
        submission = Submission.query.filter_by(
            assignment_id=assignment_id,
            student_id=role_users['student_id'],
        ).one()
        assignment_task_id = AssignmentTask.query.filter_by(assignment_id=assignment_id).one().assignment_task_id
        submission_id = submission.submission_id

    _login_as(client, role_users['student_user_id'], 'student')
    assert client.get('/submissions').status_code == 200
    assert client.post(f'/submissions/{submission_id}/start').status_code == 200
    assert client.put(f'/submissions/{submission_id}/autosave', json={
        'answers': [{'assignment_task_id': assignment_task_id, 'value': '42'}],
    }).status_code == 200
    submitted = client.post(f'/submissions/{submission_id}/submit', json={
        'task_times': {str(assignment_task_id): 15},
    })
    assert submitted.status_code == 200, submitted.get_json()
    assert submitted.get_json()['status'] in {'SUBMITTED', 'NEEDS_MANUAL_REVIEW'}

    _login_as(client, role_users['tutor_id'], 'tutor')
    grade_page = client.get(f'/submissions/{submission_id}/grade')
    assert grade_page.status_code == 200
    graded = client.post(f'/submissions/{submission_id}/grade', json={
        'scores': [{'assignment_task_id': assignment_task_id, 'score': 1, 'comment': 'Верно'}],
        'status': 'GRADED',
    })
    assert graded.status_code == 200, graded.get_json()

    with app.app_context():
        final_submission = db.session.get(Submission, submission_id)
        assert final_submission.status == 'GRADED'
        assert final_submission.total_score == 1
