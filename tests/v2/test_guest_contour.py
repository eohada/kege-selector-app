"""Регрессионный контракт гостевой сессии.

Проверяет не внешний вид, а границы доступа и необратимость сдачи — именно те
места, где гостевой режим легко случайно превратить в обычную авторизацию.
"""

from io import BytesIO
from urllib.parse import urlparse

from app import db
from app.models import GuestDemoSnapshot, GuestResponse, GuestReview, GuestSession, GuestTask, GuestTemplate
from tests.v2.conftest import login_as


def _token(link):
    return urlparse(link).path.split("/")[-1]


def test_guest_code_join_incomplete_submit_and_lock(app, role_users):
    teacher = app.test_client()
    login_as(teacher, role_users["tutor_id"], "tutor")
    created = teacher.post(
        "/teacher/guest-sessions",
        json={"session_type": "TRIAL_EXAM", "template_key": "trial_python_start"},
    )
    assert created.status_code == 200
    payload = created.get_json()
    code = payload["code"]

    guest = app.test_client()
    assert guest.get(f"/guest/code/{code}").status_code == 302
    joined = guest.post(f"/guest/s/{code}/join", json={"display_name": "Тестовый гость"})
    assert joined.status_code == 200
    assert guest.get(joined.get_json()["link"]).status_code == 200

    with app.app_context():
        session_obj = GuestSession.query.filter_by(access_code=code).one()
        template = GuestTemplate.query.filter_by(template_key='trial_python_start').one()
        assert session_obj.template_id == template.id
        assert session_obj.settings['template_version'] == template.version
        first_task = GuestTask.query.filter_by(session_id=session_obj.id, position=1).one()
        second_task = GuestTask.query.filter_by(session_id=session_obj.id, position=2).one()

    saved = guest.post(
        f"/guest/s/{code}/api/responses/{first_task.id}",
        json={"answer_text": "int"},
    )
    assert saved.status_code == 200
    incomplete = guest.post(f"/guest/s/{code}/submit", json={})
    assert incomplete.status_code == 409
    assert incomplete.get_json()["incomplete"] is True
    assert second_task.position in incomplete.get_json()["missing"]

    submitted = guest.post(f"/guest/s/{code}/submit", json={"force": True})
    assert submitted.status_code == 200
    assert submitted.get_json()["status"] == "submitted"
    locked = guest.post(
        f"/guest/s/{code}/api/responses/{second_task.id}",
        json={"answer_text": "5"},
    )
    assert locked.status_code == 409
    repeat = guest.post(f"/guest/s/{code}/submit", json={})
    assert repeat.status_code == 200
    assert repeat.get_json()["status"] == "submitted"


def test_teacher_can_reopen_extend_and_rotate_guest_link(app, role_users):
    teacher = app.test_client()
    login_as(teacher, role_users["tutor_id"], "tutor")
    created = teacher.post(
        "/teacher/guest-sessions",
        json={"session_type": "INTRO_LESSON", "template_key": "intro_platform_tour"},
    )
    assert created.status_code == 200
    payload = created.get_json()
    session_id = payload["id"]
    old_token = _token(payload["link"])

    with app.app_context():
        session_obj = GuestSession.query.get(session_id)
        snapshot = GuestDemoSnapshot.query.filter_by(session_id=session_id).one()
        assert session_obj.template_id is not None
        assert snapshot.source_template_key == 'intro_platform_tour'
        assert len(snapshot.payload['sections']) >= 4
        assert len(session_obj.tasks) == 6

    closed = teacher.post(f"/teacher/guest-sessions/{session_id}/close")
    assert closed.status_code == 200
    reopened = teacher.post(f"/teacher/guest-sessions/{session_id}/reopen", json={"hours": 12})
    assert reopened.status_code == 200
    assert reopened.get_json()["status"] == "active"
    extended = teacher.post(f"/teacher/guest-sessions/{session_id}/extend", json={"hours": 48})
    assert extended.status_code == 200

    rotated = teacher.post(f"/teacher/guest-sessions/{session_id}/rotate-link")
    assert rotated.status_code == 200
    new_token = _token(rotated.get_json()["link"])
    assert new_token != old_token
    assert app.test_client().get(f"/guest/s/{old_token}").status_code == 404
    assert app.test_client().get(f"/guest/s/{new_token}").status_code == 200


def test_guest_state_multi_file_and_scoped_timeline(app, role_users, tmp_path):
    app.config['GUEST_UPLOAD_ROOT'] = str(tmp_path)
    teacher = app.test_client()
    login_as(teacher, role_users['tutor_id'], 'tutor')
    created = teacher.post('/teacher/guest-sessions', json={'session_type': 'TRIAL_EXAM', 'template_key': 'trial_algorithms'})
    assert created.status_code == 200
    payload = created.get_json()
    code = payload['code']
    guest = app.test_client()
    joined = guest.post(f'/guest/s/{code}/join', json={'display_name': 'State guest'})
    assert joined.status_code == 200
    with app.app_context():
        task_id = GuestTask.query.filter_by(session_id=payload['id'], position=1).one().id
    assert guest.post(f'/guest/s/{code}/api/responses/{task_id}', json={'answer_text': 'O(n)', 'comment': 'черновик', 'flagged': True}).status_code == 200
    uploaded = guest.post(f'/guest/s/{code}/api/responses/{task_id}/files', data={'file': [(BytesIO(b'a'), 'a.txt'), (BytesIO(b'bb'), 'b.txt')]}, content_type='multipart/form-data')
    assert uploaded.status_code == 200
    assert len(uploaded.get_json()['files']) == 2
    state = guest.get(f'/guest/s/{code}/api/state')
    assert state.status_code == 200
    response = next(item for item in state.get_json()['responses'] if item['task_id'] == task_id)
    assert response['answer_text'] == 'O(n)' and response['flagged'] is True and len(response['attachments']) == 2
    timeline = teacher.get(f"/teacher/guest-sessions/{payload['id']}/timeline?limit=20")
    assert timeline.status_code == 200
    assert any(item['event'] == 'response.saved' for item in timeline.get_json()['events'])
    assert teacher.get(f"/teacher/guest-sessions/{payload['id']}/timeline?limit=nope").status_code == 400


def test_trial_templates_have_full_variant_and_teacher_report(app, role_users):
    teacher = app.test_client()
    login_as(teacher, role_users['tutor_id'], 'tutor')
    created = teacher.post('/teacher/guest-sessions', json={'session_type': 'TRIAL_EXAM', 'template_key': 'trial_mixed'})
    assert created.status_code == 200
    payload = created.get_json()
    code = payload['code']
    guest = app.test_client()
    joined = guest.post(f'/guest/s/{code}/join', json={'display_name': 'Report guest'})
    assert joined.status_code == 200
    with app.app_context():
        session_obj = GuestSession.query.filter_by(access_code=code).one()
        assert len(session_obj.tasks) == 19
        first = session_obj.tasks[0]
        participant = session_obj.participants[0]
    assert guest.post(f'/guest/s/{code}/api/responses/{first.id}', json={'answer_text': first.expected_answer}).status_code == 200
    submitted = guest.post(f'/guest/s/{code}/submit', json={'force': True})
    assert submitted.status_code == 200
    with app.app_context():
        response = GuestResponse.query.filter_by(participant_id=participant.id, task_id=first.id).one()
        assert response.score == first.max_score
        response_ids = [item.id for item in GuestResponse.query.filter_by(participant_id=participant.id).all()]
    reviewed = teacher.post(
        f'/teacher/guest-sessions/{session_obj.id}/participants/{participant.id}/review',
        json={'responses': [{'id': response_ids[0], 'score': 0, 'error_reason': 'KNOWLEDGE_GAP', 'teacher_comment': 'Повторить тему'}], 'recommendation': 'Повторить базовые конструкции'},
    )
    assert reviewed.status_code == 200
    with app.app_context():
        response = GuestResponse.query.get(response_ids[0])
        review = GuestReview.query.filter_by(session_id=session_obj.id, participant_id=participant.id).one()
        assert response.teacher_score == 0 and response.error_reason == 'KNOWLEDGE_GAP'
        assert review.status == 'completed' and review.report['skills']
        assert review.report['loss_reasons']['KNOWLEDGE_GAP'] == 1


def test_session_content_settings_are_enforced_and_form_booleans_normalized(app, role_users, tmp_path):
    app.config['GUEST_UPLOAD_ROOT'] = str(tmp_path)
    teacher = app.test_client()
    login_as(teacher, role_users['tutor_id'], 'tutor')
    created = teacher.post('/teacher/guest-sessions', data={
        'session_type': 'TRIAL_EXAM',
        'template_key': 'trial_python_start',
        'allow_comments': 'false',
        'allow_drawings': 'false',
        'allow_photos': 'false',
    })
    assert created.status_code == 200
    payload = created.get_json()
    guest = app.test_client()
    assert guest.post(f"/guest/s/{payload['code']}/join", json={'display_name': 'Настройки'}).status_code == 200
    with app.app_context():
        session_obj = GuestSession.query.filter_by(access_code=payload['code']).one()
        task_id = session_obj.tasks[0].id
        assert session_obj.settings['allow_comments'] is False
        assert session_obj.settings['allow_drawings'] is False
        assert session_obj.settings['allow_photos'] is False
    assert guest.post(f"/guest/s/{payload['code']}/api/responses/{task_id}", json={'comment': 'запрещено'}).status_code == 403
    assert guest.post(f"/guest/s/{payload['code']}/api/responses/{task_id}/drawing", json={'dataUrl': 'data:image/png;base64,AA=='}).status_code == 403
    photo = guest.post(
        f"/guest/s/{payload['code']}/api/responses/{task_id}/files",
        data={'file': (BytesIO(b'png'), 'answer.png')},
        content_type='multipart/form-data',
    )
    assert photo.status_code == 403


def test_forced_submit_report_uses_all_tasks_and_cross_session_task_isolation(app, role_users):
    teacher = app.test_client()
    login_as(teacher, role_users['tutor_id'], 'tutor')
    first = teacher.post('/teacher/guest-sessions', json={'session_type': 'TRIAL_EXAM', 'template_key': 'trial_python_start'}).get_json()
    second = teacher.post('/teacher/guest-sessions', json={'session_type': 'TRIAL_EXAM', 'template_key': 'trial_algorithms'}).get_json()
    guest = app.test_client()
    assert guest.post(f"/guest/s/{first['code']}/join", json={'display_name': 'Изоляция'}).status_code == 200
    with app.app_context():
        first_session = GuestSession.query.filter_by(access_code=first['code']).one()
        second_session = GuestSession.query.filter_by(access_code=second['code']).one()
        own_task = first_session.tasks[0]
        foreign_task = second_session.tasks[0]
    assert guest.post(f"/guest/s/{first['code']}/api/responses/{foreign_task.id}", json={'answer_text': 'x'}).status_code == 404
    assert guest.post(f"/guest/s/{first['code']}/api/responses/{own_task.id}", json={'answer_text': own_task.expected_answer}).status_code == 200
    submitted = guest.post(f"/guest/s/{first['code']}/submit", json={'force': True})
    assert submitted.status_code == 200
    with app.app_context():
        persisted_session = GuestSession.query.filter_by(access_code=first['code']).one()
        participant = persisted_session.participants[0]
        review = GuestReview.query.filter_by(session_id=persisted_session.id, participant_id=participant.id).one()
        assert review.max_score == sum(task.max_score for task in persisted_session.tasks)
