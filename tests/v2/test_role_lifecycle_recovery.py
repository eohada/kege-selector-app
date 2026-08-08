from datetime import timedelta

def login_as(client, user_id: int, role: str):
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True
        session['sandbox_role'] = role


def test_student_cannot_open_teacher_assignment_list(client, role_users):
    login_as(client, role_users['student_user_id'], 'student')

    response = client.get('/assignments')

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/submissions') or response.headers['Location'].endswith('/dashboard')


def test_enrollment_student_is_visible_in_tutor_roster(client, role_users):
    login_as(client, role_users['tutor_id'], 'tutor')

    response = client.get('/students')

    assert response.status_code == 200
    assert 'V2 Fixture Student' in response.get_data(as_text=True)


def test_legacy_student_pages_redirect_to_live_controllers(client, role_users):
    login_as(client, role_users['student_user_id'], 'student')

    expected = {
        '/sandbox/theory': '/theory',
        '/sandbox/trainer': '/trainer/v2',
        '/sandbox/schedule': '/schedule',
        '/sandbox/profile': '/profile',
    }
    for legacy_url, canonical_url in expected.items():
        response = client.get(legacy_url)
        assert response.status_code == 302
        assert response.headers['Location'].endswith(canonical_url)

    trainer_response = client.get('/trainer/v2')
    trainer_html = trainer_response.get_data(as_text=True)
    assert trainer_response.status_code == 200
    assert 'BooStudy Engine 7.0 OS' in trainer_html
    assert 'trainer-os-config' in trainer_html


def test_profile_metrics_are_derived_from_submissions(app, client, role_users):
    from app import db
    from core.db_models import Assignment, Submission, utc_now

    with app.app_context():
        db.session.query(Submission).delete(synchronize_session=False)
        db.session.commit()
        from core.db_models import Student
        stud_rec = Student.query.filter_by(user_id=role_users['student_user_id']).first()
        actual_student_id = stud_rec.student_id if stud_rec else role_users['student_id']
        assignment = Assignment(
            title='Fixture assignment',
            assignment_type='homework',
            deadline=utc_now() + timedelta(days=1),
            created_by_id=role_users['tutor_id'],
        )
        db.session.add(assignment)
        db.session.flush()
        db.session.add(Submission(
            assignment_id=assignment.assignment_id,
            student_id=actual_student_id,
            status='GRADED',
            total_score=7,
            max_score=10,
            percentage=70,
        ))
        db.session.commit()

    login_as(client, role_users['student_user_id'], 'student')
    response = client.get('/profile')
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '/' in html
    assert '70' in html
    assert 'Виктор Менторов' not in html
    assert 'Анна Сергеева' not in html


def test_tutor_student_assignment_lifecycle_end_to_end(app, client, role_users):
    from app import db
    from core.db_models import AssignmentTask, Submission, Tasks, utc_now

    with app.app_context():
        task = Tasks(task_number=1, content_html='<p>Release task</p>', answer='42')
        db.session.add(task)
        db.session.commit()
        task_id = task.task_id

    login_as(client, role_users['tutor_id'], 'tutor')
    distributed = client.post('/assignments/distribute', json={
        'title': 'Release lifecycle assignment',
        'type': 'homework',
        'deadline': (utc_now() + timedelta(days=1)).isoformat(),
        'tasks': [{'task_id': task_id, 'max_score': 1}],
        'recipientIds': [role_users['student_id']],
    })
    assert distributed.status_code == 201, distributed.get_json()
    assignment_id = distributed.get_json()['assignment_id']
    with app.app_context():
        submission = Submission.query.filter_by(assignment_id=assignment_id, student_id=role_users['student_id']).one()
        submission_id = submission.submission_id
        assignment_task_id = AssignmentTask.query.filter_by(assignment_id=assignment_id).one().assignment_task_id

    login_as(client, role_users['student_user_id'], 'student')
    assert client.get('/submissions').status_code == 200
    assert client.post(f'/submissions/{submission_id}/start').status_code == 200
    saved = client.put(f'/submissions/{submission_id}/autosave', json={
        'answers': [{'assignment_task_id': assignment_task_id, 'value': '42'}],
    })
    assert saved.status_code == 200
    submitted = client.post(f'/submissions/{submission_id}/submit', json={
        'task_times': {str(assignment_task_id): 15},
    })
    assert submitted.status_code == 200, submitted.get_json()

    login_as(client, role_users['tutor_id'], 'tutor')
    graded = client.post(f'/submissions/{submission_id}/grade', json={
        'scores': [{'assignment_task_id': assignment_task_id, 'score': 1, 'comment': 'Верно'}],
        'teacher_feedback': 'Отличная работа',
        'status': 'GRADED',
    })
    assert graded.status_code == 200, graded.get_json()

    login_as(client, role_users['student_user_id'], 'student')
    result = client.get(f'/submissions/{submission_id}')
    assert result.status_code == 200
    with app.app_context():
        final_submission = db.session.get(Submission, submission_id)
        assert final_submission.status == 'GRADED'
        assert final_submission.total_score == 1
        assert final_submission.percentage == 100
