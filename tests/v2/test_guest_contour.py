"""Регрессионный контракт гостевой сессии.

Проверяет не внешний вид, а границы доступа и необратимость сдачи — именно те
места, где гостевой режим легко случайно превратить в обычную авторизацию.
"""

from urllib.parse import urlparse

from app import db
from app.models import GuestSession, GuestTask
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
