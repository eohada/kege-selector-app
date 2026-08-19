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


def test_v2_assignment_builder_uses_live_contracts_and_publishes_draft(app, client, role_users):
    """The public constructor renders the V2 canvas and never calls sandbox-only APIs."""
    from app import db
    from core.db_models import Assignment, Tasks, utc_now

    with app.app_context():
        task = Tasks.query.order_by(Tasks.task_id.asc()).first()
        if task is None:
            task = Tasks(task_number=1, content_html='V2 builder fixture task', answer='42')
            db.session.add(task)
            db.session.commit()
        task_id = task.task_id

    _login_as(client, role_users['tutor_id'], 'tutor')
    page = client.get('/assignments/create')
    assert page.status_code == 200
    assert 'Конструктор • Новая работа'.encode('utf-8') in page.data
    assert 'Откуда берём задания?'.encode('utf-8') not in page.data
    assert b'/sandbox/api/create_assignment' not in page.data

    tasks_response = client.get(f'/assignments/api/create/tasks?ids={task_id}')
    assert tasks_response.status_code == 200
    assert tasks_response.get_json()['tasks'][0]['task_id'] == task_id

    draft_response = client.post('/assignments/api/create/draft', json={
        'title': 'V2 draft',
        'assignment_type': 'homework',
        'deadline': (utc_now() + timedelta(days=2)).isoformat(),
        'tasks': [{'task_id': task_id, 'max_score': 2}],
    })
    assert draft_response.status_code == 200, draft_response.get_json()
    draft_id = draft_response.get_json()['assignment_id']

    draft_page = client.get(f'/assignments/create?assignment_id={draft_id}')
    assert draft_page.status_code == 200
    assert f'Черновик ID #{draft_id}'.encode('utf-8') in draft_page.data

    published = client.post('/assignments/distribute', json={
        'draft_id': draft_id,
        'title': 'V2 published work',
        'type': 'homework',
        'recipientIds': [role_users['student_id']],
        'tasks': [{'task_id': task_id, 'max_score': 2}],
        'deadline': (utc_now() + timedelta(days=2)).isoformat(),
    })
    assert published.status_code == 201, published.get_json()
    with app.app_context():
        assert db.session.get(Assignment, draft_id) is None
        assert db.session.get(Assignment, published.get_json()['assignment_id']).is_active is True


def test_assignment_detail_renders_canonical_v2_screen(app, client, role_users):
    """Teacher assignment details must not fall back to the legacy detail template."""
    from app import db
    from core.db_models import Assignment, AssignmentTask, Submission, Tasks, utc_now

    with app.app_context():
        task = Tasks.query.order_by(Tasks.task_id.asc()).first()
        if task is None:
            task = Tasks(task_number=1, content_html='V2 detail fixture', answer='42')
            db.session.add(task)
            db.session.commit()
        assignment = Assignment(
            title='V2 detail work',
            assignment_type='homework',
            deadline=utc_now() + timedelta(days=2),
            created_by_id=role_users['tutor_id'],
            is_active=True,
        )
        db.session.add(assignment)
        db.session.flush()
        db.session.add(AssignmentTask(assignment_id=assignment.assignment_id, task_id=task.task_id, order_index=0, max_score=1))
        db.session.add(Submission(assignment_id=assignment.assignment_id, student_id=role_users['student_id'], status='ASSIGNED'))
        db.session.commit()
        assignment_id = assignment.assignment_id

    _login_as(client, role_users['tutor_id'], 'tutor')
    response = client.get(f'/assignments/{assignment_id}')
    assert response.status_code == 200
    assert 'Назад к списку'.encode('utf-8') in response.data
    assert 'Очередь проверки'.encode('utf-8') in response.data
    assert b'/assignments/' + str(assignment_id).encode() + b'/queue' not in response.data
