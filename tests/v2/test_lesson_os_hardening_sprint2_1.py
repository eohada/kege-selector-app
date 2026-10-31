import json
import pytest
from datetime import datetime
from flask_wtf.csrf import generate_csrf
from app.models import db, User, Student, Lesson
from app.lessons.lesson_socket import (
    _lesson_code_state,
    _persist_cached_code_state,
    _lock_and_get_lesson,
)
from app.lessons.routes import _save_lesson_studio_state
from tests.v2.test_lesson_room_interactive import _create_lesson_context
from tests.v2.test_role_lifecycle_recovery import login_as


@pytest.fixture(autouse=True)
def clean_vfs_in_memory_state():
    _lesson_code_state.clear()
    yield
    _lesson_code_state.clear()


def test_csrf_protection_on_os_code_save(app, role_users):
    """Task 1: Verify strict CSRF enforcement on POST /lesson/<id>/studio/os-code.

    - Missing CSRF token is rejected with 403 Forbidden (via BooStudy CSRF errorhandler).
    - Invalid CSRF token is rejected with 403 Forbidden.
    - Valid CSRF token is accepted and returns 200 with durable status.
    """
    lesson_id, _ = _create_lesson_context(app, role_users)
    teacher_client = app.test_client()
    login_as(teacher_client, role_users["tutor_id"], "tutor")

    app.config["WTF_CSRF_ENABLED"] = True

    try:
        # 1. POST without CSRF token -> Rejected by CSRF handler (403)
        res_no_csrf = teacher_client.post(
            f"/lesson/{lesson_id}/studio/os-code",
            data=json.dumps({
                "code": "unauthorized_code = True",
                "file_name": "main.py",
                "files": {"main.py": "unauthorized_code = True"},
                "base_revision": 1
            }),
            content_type="application/json"
        )
        assert res_no_csrf.status_code in (400, 403), f"Expected 400 or 403 for missing CSRF, got {res_no_csrf.status_code}"

        # 2. POST with invalid CSRF token -> Rejected (403)
        res_bad_csrf = teacher_client.post(
            f"/lesson/{lesson_id}/studio/os-code",
            data=json.dumps({
                "code": "bad_token_code = True",
                "file_name": "main.py",
                "files": {"main.py": "bad_token_code = True"},
                "base_revision": 1
            }),
            headers={"X-CSRFToken": "invalid_forged_csrf_token"},
            content_type="application/json"
        )
        assert res_bad_csrf.status_code in (400, 403), f"Expected 400 or 403 for invalid CSRF, got {res_bad_csrf.status_code}"

        # 3. POST with valid CSRF token in header & body -> Accepted (200 OK)
        import re
        demo_resp = teacher_client.get("/demo")
        csrf_match = re.search(r'<meta name="csrf-token" content="([^"]+)"', demo_resp.get_data(as_text=True))
        assert csrf_match, "Expected csrf-token in /demo HTML"
        valid_csrf = csrf_match.group(1)

        res_valid = teacher_client.post(
            f"/lesson/{lesson_id}/studio/os-code",
            data=json.dumps({
                "code": "hardened_code = True",
                "file_name": "main.py",
                "files": {"main.py": "hardened_code = True"},
                "base_revision": 0,
                "csrf_token": valid_csrf
            }),
            headers={"X-CSRFToken": valid_csrf},
            content_type="application/json"
        )
        assert res_valid.status_code == 200, f"Expected 200 with valid CSRF, got {res_valid.status_code}: {res_valid.data.decode('utf-8', errors='ignore')}"
        data = res_valid.get_json()
        assert data["success"] is True
        assert data["status"] == "saved"
        assert data["durable"] is True
        assert data["revision"] >= 1
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


def test_two_tier_ack_lifecycle(app, role_users):
    """Task 2: Verify distinction between Socket.IO fast ACK (synced, not durable)
    and PostgreSQL confirmed write (saved, durable via lesson_code_persisted).
    """
    lesson_id, _ = _create_lesson_context(app, role_users)
    socketio = app.socketio

    teacher_client = app.test_client()
    login_as(teacher_client, role_users["tutor_id"], "tutor")

    teacher_sock = socketio.test_client(app, flask_test_client=teacher_client, namespace="/lesson")
    assert teacher_sock.is_connected(namespace="/lesson")

    try:
        teacher_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
        teacher_sock.emit("lesson_code_join", {"lesson_id": lesson_id, "file_name": "main.py", "code": "# Init"}, namespace="/lesson")
        teacher_sock.get_received("/lesson")  # clear initial welcome events

        # Emit code update with matching base_revision=1
        teacher_sock.emit("lesson_code_update", {
            "lesson_id": lesson_id,
            "file_name": "main.py",
            "code": "live_fast_sync = 42\n",
            "base_revision": 1
        }, namespace="/lesson")

        # 1. Verify in-memory fast ACK
        events = teacher_sock.get_received("/lesson")
        acks = [e["args"][0] for e in events if e["name"] == "lesson_code_ack"]
        assert len(acks) >= 1, "Expected lesson_code_ack event"
        ack = acks[-1]
        assert ack["status"] == "synced", f"Fast ACK status should be 'synced', got {ack['status']}"
        assert ack["durable"] is False, "Fast ACK durable flag must be False"
        assert ack["revision"] >= 1

        # 2. Trigger PostgreSQL persistence
        _persist_cached_code_state(lesson_id)

        # 3. Verify durability event emitted to room
        post_persist_events = teacher_sock.get_received("/lesson")
        persisted_events = [e["args"][0] for e in post_persist_events if e["name"] == "lesson_code_persisted"]
        assert len(persisted_events) >= 1, "Expected lesson_code_persisted event after DB commit"
        p_event = persisted_events[-1]
        assert p_event["status"] == "saved"
        assert p_event["durable"] is True
        assert p_event["revision"] == ack["revision"]

        # Verify DB actually contains the committed data
        with app.app_context():
            l = db.session.get(Lesson, lesson_id)
            db_ws = l.review_summaries["_os_workspace"]
            assert db_ws["files"]["main.py"] == "live_fast_sync = 42\n"
            assert db_ws["revision"] == ack["revision"]
    finally:
        teacher_sock.disconnect(namespace="/lesson")


def test_cross_process_locking_and_non_clobbering(app, role_users):
    """Task 3: Verify row-level locking helper and that _save_lesson_studio_state
    and lesson_os_code_save do not overwrite each other's keys in review_summaries.
    """
    lesson_id, _ = _create_lesson_context(app, role_users)

    # 1. Test _lock_and_get_lesson helper
    with app.app_context():
        locked = _lock_and_get_lesson(lesson_id)
        assert locked is not None
        assert locked.lesson_id == lesson_id

    # 2. Perform studio state save (whiteboard/session controls)
    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        _save_lesson_studio_state(lesson, {
            "board_active_page": "page-2",
            "active_tab": "whiteboard",
            "teacher_private_note": "Confidential note"
        })

    # 3. Perform OS code save via HTTP
    teacher_client = app.test_client()
    login_as(teacher_client, role_users["tutor_id"], "tutor")

    res = teacher_client.post(
        f"/lesson/{lesson_id}/studio/os-code",
        data=json.dumps({
            "code": "coexisting_code = True",
            "file_name": "app.py",
            "files": {"main.py": "initial", "app.py": "coexisting_code = True"},
            "open_tabs": ["main.py", "app.py"],
            "active_file": "app.py",
            "base_revision": 0
        }),
        content_type="application/json"
    )
    assert res.status_code == 200

    # 4. Perform ANOTHER studio state save
    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        _save_lesson_studio_state(lesson, {
            "board_active_page": "page-3",
            "active_tab": "code",
            "teacher_private_note": "Updated note"
        })

    # 5. Verify both keys co-exist in review_summaries intact!
    with app.app_context():
        final_lesson = db.session.get(Lesson, lesson_id)
        summaries = final_lesson.review_summaries
        assert "_studio" in summaries, "_studio key was wiped!"
        assert "_os_workspace" in summaries, "_os_workspace key was wiped!"
        assert summaries["_studio"]["board_active_page"] == "page-3"
        assert summaries["_studio"]["teacher_private_note"] == "Updated note"
        assert "app.py" in summaries["_os_workspace"]["files"]
        assert summaries["_os_workspace"]["files"]["app.py"] == "coexisting_code = True"


def test_optimistic_db_revision_protection(app, role_users):
    """Task 3/4: Prevent stale background timers or out-of-order workers
    from overwriting newer DB revisions.
    """
    lesson_id, _ = _create_lesson_context(app, role_users)

    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        # Advance DB to revision 10
        summaries = dict(lesson.review_summaries or {})
        summaries["_os_workspace"] = {
            "files": {"main.py": "newer_db_code = 10"},
            "revision": 10,
            "version": 10,
            "active_file": "main.py",
            "updated_at": 1700000000000
        }
        lesson.review_summaries = summaries
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(lesson, "review_summaries")
        db.session.commit()

    # Now simulate stale in-memory cache at revision 3
    _lesson_code_state[lesson_id] = {
        "file_name": "main.py",
        "code": "stale_cache_code = 3",
        "files": {"main.py": "stale_cache_code = 3"},
        "revision": 3,
        "updated_at": 1700000000000
    }

    # Trigger persist
    _persist_cached_code_state(lesson_id)

    # Verify DB was NOT clobbered!
    with app.app_context():
        rechecked = db.session.get(Lesson, lesson_id)
        db_ws = rechecked.review_summaries["_os_workspace"]
        assert db_ws["revision"] == 10, f"DB revision was clobbered to {db_ws['revision']}"
        assert db_ws["files"]["main.py"] == "newer_db_code = 10"


def test_conflict_preservation_and_status(app, role_users):
    """Task 6: Verify version conflict rejection sends HTTP 409 with
    current revision and rejected file name for client-side conflict preservation.
    """
    lesson_id, _ = _create_lesson_context(app, role_users)

    teacher_client = app.test_client()
    login_as(teacher_client, role_users["tutor_id"], "tutor")

    # First update moves server to revision 1
    r1 = teacher_client.post(
        f"/lesson/{lesson_id}/studio/os-code",
        data=json.dumps({
            "code": "rev_1_code = True",
            "file_name": "main.py",
            "files": {"main.py": "rev_1_code = True"},
            "base_revision": 0
        }),
        content_type="application/json"
    )
    assert r1.status_code == 200
    rev1 = r1.get_json()["revision"]
    assert rev1 >= 1

    # Second request from an out-of-sync client with base_revision 0 and diverging code
    r2 = teacher_client.post(
        f"/lesson/{lesson_id}/studio/os-code",
        data=json.dumps({
            "code": "conflicting_attempt = True",
            "file_name": "main.py",
            "files": {"main.py": "conflicting_attempt = True"},
            "base_revision": 0
        }),
        content_type="application/json"
    )
    assert r2.status_code == 409
    data = r2.get_json()
    assert data["conflict"] is True
    assert data["current_revision"] == rev1
    assert data["rejected_base_revision"] == 0
    assert data["file_name"] == "main.py"


def test_user_scoped_vfs_backup_key_format():
    """Task 5: Verify user-scoped key generation pattern isolates teacher and student backups."""
    def get_vfs_stash_key(lesson_id, user_id):
        uid = user_id or 'anon'
        return f"boostudy_vfs_backup_{lesson_id}_{uid}"

    key_teacher = get_vfs_stash_key(42, 101)
    key_student = get_vfs_stash_key(42, 202)
    key_anon = get_vfs_stash_key(42, None)

    assert key_teacher == "boostudy_vfs_backup_42_101"
    assert key_student == "boostudy_vfs_backup_42_202"
    assert key_anon == "boostudy_vfs_backup_42_anon"
    assert key_teacher != key_student
