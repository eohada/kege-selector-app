from datetime import timedelta
from io import BytesIO


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
    assert 'Работа • выбрать и отправить'.encode('utf-8') in page.data
    assert 'Выбрать из банка'.encode('utf-8') in page.data
    assert 'Создать своё'.encode('utf-8') in page.data
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


def test_author_task_is_saved_in_personal_bank_with_files_and_manual_review(app, client, role_users):
    """Авторская задача из единого конструктора сохраняется, назначается и ждёт ручной проверки."""
    from app import db
    from app.models import Course
    from core.db_models import Assignment, AssignmentTask, Tasks, utc_now

    with app.app_context():
        course = Course(title='ЕГЭ информатика — авторские задачи', slug='v2-author-bank', is_active=True)
        db.session.add(course)
        db.session.commit()
        course_id = course.id

    _login_as(client, role_users['tutor_id'], 'tutor')
    created = client.post('/task-generator/bank/create', data={
        'course_id': str(course_id),
        'task_number': '6',
        'content': 'Определите результат работы алгоритма.',
        'starter_code': "print('Привет, BooStudy!')",
        'max_score': '3',
        'manual_grading': 'true',
        'files': (BytesIO(b'example input'), 'input.txt'),
    }, content_type='multipart/form-data')
    assert created.status_code == 201, created.get_json()
    created_task = created.get_json()['task']
    assert created_task['requires_manual_grading'] is True

    personal_bank = client.get(f'/task-generator/bank/picker/list?exam_course_id={course_id}&only_my=true')
    assert personal_bank.status_code == 200, personal_bank.get_json()
    assert [item['task_id'] for item in personal_bank.get_json()['items']] == [created_task['task_id']]

    with app.app_context():
        task = db.session.get(Tasks, created_task['task_id'])
        assert task.created_by_id == role_users['tutor_id']
        assert task.starter_code == "print('Привет, BooStudy!')"
        assert task.attached_files

    draft = client.post('/assignments/api/create/draft', json={
        'title': 'Авторская задача',
        'assignment_type': 'homework',
        'deadline': (utc_now() + timedelta(days=2)).isoformat(),
        'course_id': course_id,
        'tasks': [{
            'task_id': created_task['task_id'], 'max_score': 3,
            'requires_manual_grading': True,
        }],
    })
    assert draft.status_code == 200, draft.get_json()
    draft_id = draft.get_json()['assignment_id']

    published = client.post('/assignments/distribute', json={
        'draft_id': draft_id,
        'title': 'Авторская задача',
        'type': 'homework',
        'recipientIds': [role_users['student_id']],
        'deadline': (utc_now() + timedelta(days=2)).isoformat(),
        'tasks': [{
            'task_id': created_task['task_id'], 'max_score': 3,
            'requires_manual_grading': True,
        }],
    })
    assert published.status_code == 201, published.get_json()

    with app.app_context():
        assignment = db.session.get(Assignment, published.get_json()['assignment_id'])
        assignment_task = AssignmentTask.query.filter_by(assignment_id=assignment.assignment_id).one()
        assert assignment_task.requires_manual_grading is True
        assert assignment_task.max_score == 3


def test_teacher_can_open_student_file_and_canvas_from_assignment_review(app, client, role_users):
    """Вложения и заметки ученика остаются доступны преподавателю в одном контуре проверки."""
    from app import db
    from core.db_models import Assignment, AssignmentTask, Submission, Tasks, utc_now

    with app.app_context():
        task = Tasks(task_number=9, content_html='<p>Задача с файлом и рисунком</p>', answer=None)
        db.session.add(task)
        db.session.flush()
        assignment = Assignment(
            title='Вложения и рисунок', assignment_type='homework', deadline=utc_now() + timedelta(days=2),
            created_by_id=role_users['tutor_id'], is_active=True,
        )
        db.session.add(assignment)
        db.session.flush()
        assignment_task = AssignmentTask(
            assignment_id=assignment.assignment_id, task_id=task.task_id, order_index=0,
            max_score=1, requires_manual_grading=True,
        )
        db.session.add(assignment_task)
        db.session.flush()
        submission = Submission(assignment_id=assignment.assignment_id, student_id=role_users['student_id'], status='ASSIGNED')
        db.session.add(submission)
        db.session.commit()
        submission_id = submission.submission_id
        assignment_task_id = assignment_task.assignment_task_id
        task_id = task.task_id

    _login_as(client, role_users['student_user_id'], 'student')
    assert client.post(f'/submissions/{submission_id}/start').status_code == 200
    uploaded = client.post(
        f'/submissions/{submission_id}/upload-answer-file',
        data={'assignment_task_id': str(assignment_task_id), 'file': (BytesIO(b'my work'), 'solution.txt')},
        content_type='multipart/form-data',
    )
    assert uploaded.status_code == 200, uploaded.get_json()
    attachment_url = uploaded.get_json()['url']
    saved_canvas = client.post('/api/canvas/save', json={
        'task_id': task_id,
        'context_type': 'submission_task',
        'context_id': submission_id,
        'strokes': [{'color': '#4f46e5', 'width': 3, 'points': [{'x': 10, 'y': 10}, {'x': 20, 'y': 20}]}],
    })
    assert saved_canvas.status_code == 200, saved_canvas.get_json()

    _login_as(client, role_users['tutor_id'], 'tutor')
    assert client.get(attachment_url).status_code == 200
    canvas = client.get(
        f'/api/canvas/view/{role_users["student_user_id"]}',
        query_string={'task_id': task_id, 'context_type': 'submission', 'context_id': submission_id},
    )
    assert canvas.status_code == 200, canvas.get_json()
    assert canvas.get_json()['exists'] is True
    review = client.get(f'/submissions/{submission_id}/grade')
    assert review.status_code == 200
    assert attachment_url.encode() in review.data
    assert 'Заметки ученика'.encode('utf-8') in review.data


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
