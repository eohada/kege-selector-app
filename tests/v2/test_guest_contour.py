"""Регрессионный контракт гостевой сессии.

Проверяет не внешний вид, а границы доступа и необратимость сдачи — именно те
места, где гостевой режим легко случайно превратить в обычную авторизацию.
"""

from datetime import timedelta
from io import BytesIO
from urllib.parse import urlparse

from app import db
from app.models import GuestDemoSnapshot, GuestResponse, GuestReview, GuestSession, GuestTask, GuestTemplate, utc_now
from tests.v2.conftest import login_as


def _token(link):
    return urlparse(link).path.split("/")[-1]


def test_guest_code_join_incomplete_submit_and_lock(app, role_users):
    teacher = app.test_client()
    login_as(teacher, role_users["tutor_id"], "tutor")
    created = teacher.post(
        "/teacher/guest-sessions",
        json={"session_type": "TRIAL_EXAM", "template_key": "trial_ege_full_1"},
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
        template = GuestTemplate.query.filter_by(template_key='trial_ege_full_1').one()
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
    assert f"/guest/code/{payload['code']}" in payload['link']

    with app.app_context():
        session_obj = GuestSession.query.get(session_id)
        snapshot = GuestDemoSnapshot.query.filter_by(session_id=session_id).one()
        assert session_obj.template_id is not None
        assert snapshot.source_template_key == 'intro_platform_tour'
        assert len(snapshot.payload['sections']) >= 4
        assert len(session_obj.tasks) == 6

    detail = teacher.get(f"/teacher/guest-sessions/{session_id}")
    assert detail.status_code == 200
    assert 'id="close"' in detail.get_data(as_text=True)
    assert 'id="confirm-modal"' in detail.get_data(as_text=True)

    closed = teacher.post(f"/teacher/guest-sessions/{session_id}/close")
    assert closed.status_code == 200
    assert app.test_client().get(f"/guest/code/{payload['code']}").status_code == 410
    other_teacher = app.test_client()
    login_as(other_teacher, role_users['creator_id'], 'creator')
    assert other_teacher.post(f"/teacher/guest-sessions/{session_id}/close").status_code == 404
    reopened = teacher.post(f"/teacher/guest-sessions/{session_id}/reopen", json={"hours": 12})
    assert reopened.status_code == 200
    assert reopened.get_json()["status"] == "active"
    extended = teacher.post(f"/teacher/guest-sessions/{session_id}/extend", json={"hours": 48})
    assert extended.status_code == 200

    rotated = teacher.post(f"/teacher/guest-sessions/{session_id}/rotate-link")
    assert rotated.status_code == 200
    new_token = _token(rotated.get_json()["link"])
    assert new_token != old_token
    assert rotated.get_json()['code'] == new_token
    assert app.test_client().get(f"/guest/s/{old_token}").status_code == 404
    assert app.test_client().get(f"/guest/s/{new_token}").status_code == 200


def test_teacher_list_can_rebuild_public_link_from_persisted_code(app, role_users):
    teacher = app.test_client()
    login_as(teacher, role_users['tutor_id'], 'tutor')
    created = teacher.post('/teacher/guest-sessions', json={
        'session_type': 'INTRO_LESSON',
        'template_key': 'intro_platform_tour',
    }).get_json()

    page = teacher.get('/teacher/guest-sessions')

    assert page.status_code == 200
    assert f'/guest/code/{created["code"]}' in page.get_data(as_text=True)


def test_guest_state_multi_file_and_scoped_timeline(app, role_users, tmp_path):
    app.config['GUEST_UPLOAD_ROOT'] = str(tmp_path)
    teacher = app.test_client()
    login_as(teacher, role_users['tutor_id'], 'tutor')
    created = teacher.post('/teacher/guest-sessions', json={'session_type': 'TRIAL_EXAM', 'template_key': 'trial_ege_full_2'})
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


def test_guest_python_workspace_uses_safe_ege_libraries_and_own_task(app, role_users):
    teacher = app.test_client()
    login_as(teacher, role_users['tutor_id'], 'tutor')
    created = teacher.post('/teacher/guest-sessions', json={
        'session_type': 'TRIAL_EXAM', 'template_key': 'trial_ege_full_1',
    }).get_json()
    guest = app.test_client()
    assert guest.post(f"/guest/s/{created['code']}/join", json={'display_name': 'Кодер'}).status_code == 200
    with app.app_context():
        session_obj = GuestSession.query.filter_by(access_code=created['code']).one()
        own_task = session_obj.tasks[0]
    ran = guest.post(
        f"/guest/s/{created['code']}/api/responses/{own_task.id}/run-code",
        json={'code': 'import math\nprint(math.isqrt(20))'},
    )
    assert ran.status_code == 200
    assert ran.get_json()['stdout'] == '4'
    forbidden = guest.post(
        f"/guest/s/{created['code']}/api/responses/{own_task.id}/run-code",
        json={'code': 'import os'},
    )
    assert forbidden.status_code == 200
    assert 'недоступен в песочнице' in forbidden.get_json()['stderr']


def test_trial_templates_have_full_variant_and_teacher_report(app, role_users):
    teacher = app.test_client()
    login_as(teacher, role_users['tutor_id'], 'tutor')
    created = teacher.post('/teacher/guest-sessions', json={'session_type': 'TRIAL_EXAM', 'template_key': 'trial_ege_full_3'})
    assert created.status_code == 200
    payload = created.get_json()
    code = payload['code']
    guest = app.test_client()
    joined = guest.post(f'/guest/s/{code}/join', json={'display_name': 'Report guest'})
    assert joined.status_code == 200
    with app.app_context():
        session_obj = GuestSession.query.filter_by(access_code=code).one()
        assert len(session_obj.tasks) == 27
        assert [task.metadata_json['task_number'] for task in session_obj.tasks] == list(range(1, 28))
        assert any(task.metadata_json['attachments'] for task in session_obj.tasks)
        assert all(task.metadata_json['source_url'].startswith('https://kompege.ru/task') for task in session_obj.tasks)
        task_six = next(task for task in session_obj.tasks if task.metadata_json['task_number'] == 6)
        task_nineteen = next(task for task in session_obj.tasks if task.metadata_json['task_number'] == 19)
        task_twenty = next(task for task in session_obj.tasks if task.metadata_json['task_number'] == 20)
        task_twenty_one = next(task for task in session_obj.tasks if task.metadata_json['task_number'] == 21)
        assert 'answerWrap' not in task_six.prompt and '<iframe' not in task_six.prompt and '>38<' not in task_six.prompt
        assert 'Задание 20' not in task_nineteen.prompt and 'Задание 21' not in task_nineteen.prompt
        assert 'Задание 21' not in task_twenty.prompt and 'Задание 19' not in task_twenty_one.prompt
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
        assert review.report['summary']['total'] == 27
        assert review.report['summary']['unanswered'] == 26


def test_guest_workspace_hides_bank_source_and_uses_scoped_attachment_url(app, role_users):
    teacher = app.test_client()
    login_as(teacher, role_users['tutor_id'], 'tutor')
    created = teacher.post('/teacher/guest-sessions', json={
        'session_type': 'TRIAL_EXAM', 'template_key': 'trial_ege_full_1',
    }).get_json()
    guest = app.test_client()
    assert guest.post(f"/guest/s/{created['code']}/join", json={'display_name': 'Проверка интерфейса'}).status_code == 200
    page = guest.get(f"/guest/s/{created['code']}/work")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'Источник условия' not in html
    with app.app_context():
        session_obj = GuestSession.query.filter_by(access_code=created['code']).one()
        file_task = next(task for task in session_obj.tasks if task.metadata_json['attachments'])
    assert f"/guest/s/{created['code']}/attachments/{file_task.id}/0" in html
    assert guest.get(f"/guest/s/{created['code']}/attachments/{file_task.id}/999").status_code == 404


def test_session_content_settings_are_enforced_and_form_booleans_normalized(app, role_users, tmp_path):
    app.config['GUEST_UPLOAD_ROOT'] = str(tmp_path)
    teacher = app.test_client()
    login_as(teacher, role_users['tutor_id'], 'tutor')
    created = teacher.post('/teacher/guest-sessions', data={
        'session_type': 'TRIAL_EXAM',
        'template_key': 'trial_ege_full_1',
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
    workspace = guest.get(f"/guest/s/{payload['code']}/work")
    assert workspace.status_code == 200
    html = workspace.get_data(as_text=True)
    assert '<textarea data-comment' not in html
    assert '<input data-file' not in html
    assert '<canvas data-canvas' not in html
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
    first = teacher.post('/teacher/guest-sessions', json={'session_type': 'TRIAL_EXAM', 'template_key': 'trial_ege_full_1'}).get_json()
    second = teacher.post('/teacher/guest-sessions', json={'session_type': 'TRIAL_EXAM', 'template_key': 'trial_ege_full_2'}).get_json()
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


def test_intro_guest_onboarding_review_and_conversion_e2e(app, role_users):
    teacher = app.test_client()
    login_as(teacher, role_users['tutor_id'], 'tutor')
    created = teacher.post('/teacher/guest-sessions', json={
        'session_type': 'INTRO_LESSON',
        'template_key': 'intro_platform_tour',
    }).get_json()
    code = created['code']
    guest = app.test_client()

    assert guest.get(f'/guest/code/{code}').status_code == 302
    joined = guest.post(f'/guest/s/{code}/join', json={'display_name': 'Будущий ученик'})
    assert joined.status_code == 200
    workspace_url = joined.get_json()['link']
    assert guest.get(workspace_url).status_code == 200
    onboarding = guest.post(f'/guest/s/{code}/onboarding', json={'completed': True, 'step': 'finish'})
    assert onboarding.status_code == 200 and onboarding.get_json()['onboarding_state']['completed'] is True

    with app.app_context():
        session_obj = GuestSession.query.filter_by(access_code=code).one()
        participant = session_obj.participants[0]
        first_task = session_obj.tasks[0]
    assert guest.post(f'/guest/s/{code}/api/responses/{first_task.id}', json={
        'answer_text': first_task.expected_answer,
    }).status_code == 200
    submitted = guest.post(f'/guest/s/{code}/submit', json={'force': True})
    assert submitted.status_code == 200
    assert guest.get(submitted.get_json()['result_url']).status_code == 200

    reviewed = teacher.post(
        f'/teacher/guest-sessions/{created["id"]}/participants/{participant.id}/review',
        json={'recommendation': 'Запланировать первую полноценную диагностику'},
    )
    assert reviewed.status_code == 200
    converted = teacher.post(f'/teacher/guest-sessions/{created["id"]}/participants/{participant.id}/convert')
    assert converted.status_code == 200 and converted.get_json()['status'] == 'converted'
    repeated = teacher.post(f'/teacher/guest-sessions/{created["id"]}/participants/{participant.id}/convert')
    assert repeated.status_code == 200 and repeated.get_json()['student_id'] == converted.get_json()['student_id']

    with app.app_context():
        persisted = GuestSession.query.get(created['id']).participants[0]
        assert persisted.status == 'converted'
        assert persisted.converted_student_id == converted.get_json()['student_id']


def test_guest_result_and_teacher_review_render_workspace_evidence(app, role_users):
    teacher = app.test_client()
    login_as(teacher, role_users['tutor_id'], 'tutor')
    created = teacher.post('/teacher/guest-sessions', json={
        'session_type': 'INTRO_LESSON', 'template_key': 'intro_platform_tour',
    }).get_json()
    guest = app.test_client()
    assert guest.post(f"/guest/s/{created['code']}/join", json={'display_name': 'Кодер'}).status_code == 200
    with app.app_context():
        session_obj = GuestSession.query.get(created['id'])
        participant_id = session_obj.participants[0].id
        task = session_obj.tasks[0]
    assert guest.post(f"/guest/s/{created['code']}/api/responses/{task.id}", json={
        'answer_text': task.expected_answer,
        'answer_json': {'workspace_code': 'print(\"Привет, BooStudy!\")'},
        'comment': 'Проверил решение в редакторе.',
    }).status_code == 200
    assert guest.post(f"/guest/s/{created['code']}/api/responses/{task.id}/drawing", json={
        'version': 2, 'dataUrl': 'data:image/jpeg;base64,aGVsbG8=',
        'shapes': [{'type': 'line', 'a': {'x': 1, 'y': 1}, 'b': {'x': 2, 'y': 2}}],
    }).status_code == 200
    assert guest.post(
        f"/guest/s/{created['code']}/api/responses/{task.id}/files",
        data={'file': (BytesIO(b'guest notes'), 'solution.txt')}, content_type='multipart/form-data',
    ).status_code == 200
    submitted = guest.post(f"/guest/s/{created['code']}/submit", json={'force': True}).get_json()
    result_html = guest.get(submitted['result_url']).get_data(as_text=True)
    assert 'guest-result-hero' in result_html
    assert 'guest-result-card' in result_html
    assert 'Задание №1' in result_html
    assert 'без ответа' in result_html
    assert 'ege.task_' not in result_html
    review_html = teacher.get(f"/teacher/guest-sessions/{created['id']}").get_data(as_text=True)
    assert 'Код ученика' in review_html
    assert 'Привет, BooStudy!' in review_html
    assert 'Вложения ученика' in review_html and 'solution.txt' in review_html
    assert 'Холст ученика' in review_html
    assert 'data:image/jpeg;base64,aGVsbG8=' in review_html
    assert 'review-task group' in review_html


def test_trial_join_hides_access_deadline_but_keeps_exam_timer(app, role_users):
    teacher = app.test_client()
    login_as(teacher, role_users['tutor_id'], 'tutor')
    created = teacher.post('/teacher/guest-sessions', json={
        'session_type': 'TRIAL_EXAM', 'template_key': 'trial_ege_full_1',
    }).get_json()
    join_html = teacher.get(f"/guest/code/{created['code']}", follow_redirects=True).get_data(as_text=True)
    assert 'видит только преподаватель' in join_html
    assert '⌛ до ' not in join_html
    assert 'guest-session-timer.js' in join_html


def test_timed_trial_force_submits_on_next_guest_request(app, role_users):
    teacher = app.test_client()
    login_as(teacher, role_users['tutor_id'], 'tutor')
    created = teacher.post('/teacher/guest-sessions', json={
        'session_type': 'TRIAL_EXAM', 'template_key': 'trial_ege_full_1',
    }).get_json()
    guest = app.test_client()
    assert guest.post(f"/guest/s/{created['code']}/join", json={'display_name': 'Таймер'}).status_code == 200
    with app.app_context():
        session_obj = GuestSession.query.get(created['id'])
        participant = session_obj.participants[0]
        participant_id = participant.id
        assert session_obj.settings['timed'] is True
        assert session_obj.settings['expected_duration_minutes'] == 235
        participant.joined_at = utc_now() - timedelta(minutes=session_obj.settings['expected_duration_minutes'] + 1)
        task_id = session_obj.tasks[0].id
        db.session.commit()
    state = guest.get(f"/guest/s/{created['code']}/api/state")
    assert state.status_code == 200 and state.get_json()['participant']['status'] == 'submitted'
    assert state.get_json()['session']['timed'] is True
    assert state.get_json()['session']['deadline']
    assert guest.post(f"/guest/s/{created['code']}/api/responses/{task_id}", json={'answer_text': 'int'}).status_code == 409
    with app.app_context():
        assert GuestReview.query.filter_by(session_id=created['id'], participant_id=participant_id).one().status == 'pending'
