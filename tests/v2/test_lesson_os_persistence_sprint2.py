"""Tests for BooStudy OS Sprint 2: Durable Code, VirtualFS & Reliable Persistence.

Covers:
- P0-01: Stale write rejection, revision tracking, conflict detection on concurrent code edits.
- P0-02: Tab exit flush & emergency state durability (fast exit, full VFS persistence).
- P1-01: Multi-file VirtualFS CRUD (create, update, rename, delete, tab switch) persisted to PostgreSQL.
- Server restart survival: Clearing in-memory cache and rehydrating full multi-file VFS on join.
- Concurrency safety: Mutating whiteboard (_studio) and code (_os_workspace) without clobbering.
- Strict authorization: Outsiders and students with student_code_editing=False blocked from modifying VFS.
"""

import pytest
from app import db
from app.models import Lesson, User, UserProfile
from app.lessons.lesson_socket import (
    _lesson_code_state,
    _load_cached_code_state,
    _persist_cached_code_state,
    _room_control,
)
from app.lessons.routes import _save_lesson_studio_state
from tests.v2.test_lesson_room_interactive import _create_lesson_context
from tests.v2.test_role_lifecycle_recovery import login_as


def _get_or_create_outsider(app):
    with app.app_context():
        outsider = User.query.filter_by(username="sprint2_outsider").first()
        if not outsider:
            outsider = User(username="sprint2_outsider", role="student")
            outsider.set_password("outsider123")
            db.session.add(outsider)
            db.session.flush()
            profile = UserProfile(user_id=outsider.id, first_name="Outsider", last_name="User")
            db.session.add(profile)
            db.session.commit()
        return outsider.id


def test_vfs_multi_file_crud_and_persistence(app, role_users):
    """Multi-file VirtualFS operations (create, update, rename, delete) must be tracked,

    acknowledged with monotonically increasing revisions, and persisted to PostgreSQL.
    """
    lesson_id, _ = _create_lesson_context(app, role_users)
    teacher_http = app.test_client()
    student_http = app.test_client()
    login_as(teacher_http, role_users["tutor_id"], "tutor")
    login_as(student_http, role_users["student_user_id"], "student")

    sockets = []

    def connect(http_client):
        conn = app.socketio.test_client(app, flask_test_client=http_client, namespace="/lesson")
        sockets.append(conn)
        assert conn.is_connected("/lesson")
        conn.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
        conn.emit("lesson_code_join", {"lesson_id": lesson_id, "file_name": "main.py", "code": "# Init main"}, namespace="/lesson")
        return conn

    try:
        teacher_sock = connect(teacher_http)
        student_sock = connect(student_http)

        # Clear initial packets
        teacher_sock.get_received("/lesson")
        student_sock.get_received("/lesson")

        # 1. Create helper.py
        teacher_sock.emit("lesson_vfs_file_create", {
            "lesson_id": lesson_id,
            "file_name": "helper.py",
            "code": "def solve(): return 42\n",
        }, namespace="/lesson")

        # Verify teacher received ack
        teacher_events = teacher_sock.get_received("/lesson")
        acks = [e["args"][0] for e in teacher_events if e["name"] == "lesson_code_ack"]
        assert len(acks) >= 1
        assert acks[-1]["file_name"] == "helper.py"
        rev1 = acks[-1]["revision"]
        assert rev1 >= 1

        # Verify student received creation event
        student_events = student_sock.get_received("/lesson")
        creates = [e["args"][0] for e in student_events if e["name"] == "lesson_vfs_file_create"]
        assert len(creates) >= 1
        assert "helper.py" in creates[-1]["files"]
        assert "main.py" in creates[-1]["files"]

        # 2. Update helper.py code
        teacher_sock.emit("lesson_code_update", {
            "lesson_id": lesson_id,
            "file_name": "helper.py",
            "code": "def solve(): return 100\n",
            "base_revision": rev1,
        }, namespace="/lesson")

        teacher_events = teacher_sock.get_received("/lesson")
        acks = [e["args"][0] for e in teacher_events if e["name"] == "lesson_code_ack"]
        assert len(acks) >= 1
        rev2 = acks[-1]["revision"]
        assert rev2 > rev1

        # 3. Rename helper.py -> utils.py
        teacher_sock.emit("lesson_vfs_file_rename", {
            "lesson_id": lesson_id,
            "old_name": "helper.py",
            "new_name": "utils.py",
        }, namespace="/lesson")

        teacher_events = teacher_sock.get_received("/lesson")
        acks = [e["args"][0] for e in teacher_events if e["name"] == "lesson_code_ack"]
        assert len(acks) >= 1
        rev3 = acks[-1]["revision"]
        assert rev3 > rev2

        student_events = student_sock.get_received("/lesson")
        renames = [e["args"][0] for e in student_events if e["name"] == "lesson_vfs_file_rename"]
        assert len(renames) >= 1
        assert "utils.py" in renames[-1]["files"]
        assert "helper.py" not in renames[-1]["files"]

        # 4. Flush persistence to PostgreSQL
        with app.app_context():
            _persist_cached_code_state(lesson_id)
            lesson = Lesson.query.get(lesson_id)
            stored = (lesson.review_summaries or {}).get("_os_workspace") or {}
            assert stored is not None
            files = stored.get("files", {})
            assert "utils.py" in files
            assert "helper.py" not in files
            assert "main.py" in files
            assert files["utils.py"] == "def solve(): return 100\n"
            assert stored.get("revision") == rev3

        # 5. Delete utils.py
        teacher_sock.emit("lesson_vfs_file_delete", {
            "lesson_id": lesson_id,
            "file_name": "utils.py",
        }, namespace="/lesson")

        teacher_events = teacher_sock.get_received("/lesson")
        acks = [e["args"][0] for e in teacher_events if e["name"] == "lesson_code_ack"]
        assert len(acks) >= 1
        rev4 = acks[-1]["revision"]
        assert rev4 > rev3

        with app.app_context():
            _persist_cached_code_state(lesson_id)
            lesson = Lesson.query.get(lesson_id)
            stored = (lesson.review_summaries or {}).get("_os_workspace") or {}
            files = stored.get("files", {})
            assert "utils.py" not in files
            assert "main.py" in files

    finally:
        for s in sockets:
            try:
                s.disconnect(namespace="/lesson")
            except Exception:
                pass


def test_vfs_rehydration_after_process_restart(app, role_users):
    """When server process restarts (simulated by clearing in-memory cache),

    all files in VirtualFS, open tabs, active file, and revision must be restored from PostgreSQL.
    """
    lesson_id, _ = _create_lesson_context(app, role_users)

    # 1. Populate workspace in PostgreSQL with multiple files
    with app.app_context():
        lesson = Lesson.query.get(lesson_id)
        summaries = dict(lesson.review_summaries or {})
        summaries["_os_workspace"] = {
            "files": {
                "main.py": "import algos\nprint(algos.calc())\n",
                "algos.py": "def calc(): return 999\n",
                "data.txt": "10 20 30 40 50",
            },
            "open_tabs": ["main.py", "algos.py", "data.txt"],
            "active_file": "algos.py",
            "revision": 15,
            "version": 15,
            "updated_at": 1729738000000,
        }
        lesson.review_summaries = summaries
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(lesson, "review_summaries")
        db.session.commit()

        # Evict memory cache (simulating process restart)
        _lesson_code_state.pop(lesson_id, None)
        assert lesson_id not in _lesson_code_state

    # 2. Student connects via Socket.IO
    student_http = app.test_client()
    login_as(student_http, role_users["student_user_id"], "student")
    sock = app.socketio.test_client(app, flask_test_client=student_http, namespace="/lesson")
    try:
        assert sock.is_connected("/lesson")
        sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
        sock.emit("lesson_code_join", {"lesson_id": lesson_id}, namespace="/lesson")

        events = sock.get_received("/lesson")
        snapshots = [e["args"][0] for e in events if e["name"] == "lesson_code_snapshot"]
        assert len(snapshots) >= 1, "Snapshot was not emitted to connecting student"
        snap = snapshots[-1]

        # Verify full VFS rehydration
        assert "files" in snap
        assert "main.py" in snap["files"]
        assert "algos.py" in snap["files"]
        assert "data.txt" in snap["files"]
        assert snap["files"]["algos.py"] == "def calc(): return 999\n"
        assert snap["files"]["data.txt"] == "10 20 30 40 50"
        assert snap["active_file"] == "algos.py"
        assert snap["revision"] == 15
        assert set(snap["open_tabs"]) == {"main.py", "algos.py", "data.txt"}

        # Verify memory cache is now rehydrated
        assert lesson_id in _lesson_code_state
        assert _lesson_code_state[lesson_id]["revision"] == 15
    finally:
        sock.disconnect(namespace="/lesson")


def test_stale_write_rejection_and_conflict_detection(app, role_users):
    """P0-01: When an edit arrives with a stale base_revision and diverging code,

    the server must reject the silent overwrite and emit a lesson_code_conflict event.
    """
    lesson_id, _ = _create_lesson_context(app, role_users)
    teacher_http = app.test_client()
    login_as(teacher_http, role_users["tutor_id"], "tutor")

    sock = app.socketio.test_client(app, flask_test_client=teacher_http, namespace="/lesson")
    try:
        sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
        sock.emit("lesson_code_join", {
            "lesson_id": lesson_id,
            "file_name": "main.py",
            "code": "version_1 = True",
        }, namespace="/lesson")
        sock.get_received("/lesson")

        # Advance revision to 5
        for i in range(2, 6):
            sock.emit("lesson_code_update", {
                "lesson_id": lesson_id,
                "file_name": "main.py",
                "code": f"version_{i} = True",
                "base_revision": i - 1,
            }, namespace="/lesson")
        
        events = sock.get_received("/lesson")
        acks = [e["args"][0] for e in events if e["name"] == "lesson_code_ack"]
        current_rev = acks[-1]["revision"]
        assert current_rev >= 5

        # Now simulate a stale concurrent write with base_revision: 2 and diverging code
        sock.emit("lesson_code_update", {
            "lesson_id": lesson_id,
            "file_name": "main.py",
            "code": "stale_diverging_code = True",
            "base_revision": 2,
        }, namespace="/lesson")

        conflict_events = sock.get_received("/lesson")
        conflicts = [e["args"][0] for e in conflict_events if e["name"] == "lesson_code_conflict"]
        assert len(conflicts) >= 1, "Stale diverging write was not flagged as a conflict!"
        conflict = conflicts[-1]
        assert conflict["file_name"] == "main.py"
        assert conflict["server_revision"] == current_rev
        assert conflict["rejected_base_revision"] == 2
        assert "version_5 = True" in conflict["server_code"]

        # Verify server state was NOT clobbered by stale write
        assert _lesson_code_state[lesson_id]["files"]["main.py"] == "version_5 = True"

        # Now submit with fresh revision: must succeed
        sock.emit("lesson_code_update", {
            "lesson_id": lesson_id,
            "file_name": "main.py",
            "code": "version_6 = True",
            "base_revision": current_rev,
        }, namespace="/lesson")

        fresh_events = sock.get_received("/lesson")
        fresh_acks = [e["args"][0] for e in fresh_events if e["name"] == "lesson_code_ack"]
        assert len(fresh_acks) >= 1
        assert fresh_acks[-1]["revision"] == current_rev + 1
        assert _lesson_code_state[lesson_id]["files"]["main.py"] == "version_6 = True"
    finally:
        sock.disconnect(namespace="/lesson")


def test_http_autosave_vfs_and_conflict_handling(app, role_users):
    """The /studio/os-code REST endpoint must accept multi-file VirtualFS payloads,

    reject stale base_revisions with 409 Conflict, and keep memory and DB in sync.
    """
    lesson_id, _ = _create_lesson_context(app, role_users)
    teacher_http = app.test_client()
    login_as(teacher_http, role_users["tutor_id"], "tutor")

    # 1. GET initial code
    res_get = teacher_http.get(f"/lesson/{lesson_id}/studio/os-code")
    assert res_get.status_code == 200
    data_get = res_get.get_json()
    assert data_get["success"] is True
    assert "files" in data_get
    initial_rev = data_get.get("revision", 1)

    # 2. POST multi-file VirtualFS payload
    vfs_payload = {
        "files": {
            "main.py": "print('from REST')",
            "module.py": "def foo(): pass",
        },
        "open_tabs": ["main.py", "module.py"],
        "active_file": "module.py",
        "base_revision": initial_rev,
    }
    res_post = teacher_http.post(f"/lesson/{lesson_id}/studio/os-code", json=vfs_payload)
    assert res_post.status_code == 200
    data_post = res_post.get_json()
    assert data_post["success"] is True
    new_rev = data_post["revision"]
    assert new_rev > initial_rev
    assert data_post["files_count"] == 2

    # Verify PostgreSQL persistence
    with app.app_context():
        lesson = Lesson.query.get(lesson_id)
        stored = lesson.review_summaries.get("_os_workspace")
        assert stored["files"]["main.py"] == "print('from REST')"
        assert stored["files"]["module.py"] == "def foo(): pass"
        assert stored["active_file"] == "module.py"
        assert stored["revision"] == new_rev

        # Verify in-memory cache is synced with HTTP save
        mem_state = _lesson_code_state.get(lesson_id)
        assert mem_state is not None
        assert mem_state["files"]["module.py"] == "def foo(): pass"
        assert mem_state["revision"] == new_rev

    # 3. POST with stale base_revision (e.g. initial_rev while server is at new_rev)
    stale_payload = {
        "files": {
            "main.py": "stale overwrite attempt",
        },
        "base_revision": initial_rev,
    }
    res_stale = teacher_http.post(f"/lesson/{lesson_id}/studio/os-code", json=stale_payload)
    assert res_stale.status_code == 409
    data_stale = res_stale.get_json()
    assert data_stale["conflict"] is True
    assert data_stale["current_revision"] == new_rev

    # Verify DB was NOT overwritten
    with app.app_context():
        lesson = Lesson.query.get(lesson_id)
        stored = lesson.review_summaries.get("_os_workspace")
        assert stored["files"]["main.py"] == "print('from REST')"


def test_concurrent_summaries_mutation_safety(app, role_users):
    """Mutations to whiteboard state (_studio) and code workspace (_os_workspace)

    must not overwrite or corrupt each other inside Lesson.review_summaries.
    """
    lesson_id, _ = _create_lesson_context(app, role_users)
    teacher_http = app.test_client()
    login_as(teacher_http, role_users["tutor_id"], "tutor")

    with app.app_context():
        lesson = Lesson.query.get(lesson_id)

        # 1. Write whiteboard state
        board_state = {"board": {"strokes": [{"id": "s1", "tool": "pen"}], "revision": 3}}
        _save_lesson_studio_state(lesson, board_state)

    # 2. Save code via HTTP
    teacher_http.post(f"/lesson/{lesson_id}/studio/os-code", json={
        "files": {"main.py": "x = 42\n"},
        "active_file": "main.py",
        "open_tabs": ["main.py"],
    })

    # 3. Write another whiteboard update
    with app.app_context():
        lesson = Lesson.query.get(lesson_id)
        board_state["board"]["strokes"].append({"id": "s2", "tool": "rectangle"})
        _save_lesson_studio_state(lesson, board_state)

    # 4. Trigger code persistence
    with app.app_context():
        _persist_cached_code_state(lesson_id)

        lesson = Lesson.query.get(lesson_id)
        summaries = lesson.review_summaries or {}

        # Both keys MUST be present and uncorrupted!
        assert "_studio" in summaries, "_studio key was clobbered by code persistence!"
        assert "_os_workspace" in summaries, "_os_workspace key was clobbered by studio persistence!"

        assert len(summaries["_studio"]["board"]["strokes"]) == 2
        assert summaries["_os_workspace"]["files"]["main.py"] == "x = 42\n"


def test_vfs_authorization_checks(app, role_users):
    """Outsiders and unauthorized students cannot modify VirtualFS."""
    lesson_id, _ = _create_lesson_context(app, role_users)
    outsider_id = _get_or_create_outsider(app)

    outsider_http = app.test_client()
    login_as(outsider_http, outsider_id, "student")

    # 1. Outsider blocked from HTTP save
    res = outsider_http.post(f"/lesson/{lesson_id}/studio/os-code", json={"code": "hack()"})
    assert res.status_code == 403

    # 2. Student with student_code_editing = False blocked from modifying code
    student_http = app.test_client()
    login_as(student_http, role_users["student_user_id"], "student")

    # Set student_code_editing = False in control state
    with app.app_context():
        from app.lessons.lesson_socket import _lesson_control_cache
        _lesson_control_cache[lesson_id] = (
            9999999999.0,
            {"code_sync": True, "student_code_editing": False},
        )

    # Student HTTP save must be 403
    res_student = student_http.post(f"/lesson/{lesson_id}/studio/os-code", json={"code": "student_hack()"})
    assert res_student.status_code == 403

    # Student Socket.IO edit must be ignored
    sock = app.socketio.test_client(app, flask_test_client=student_http, namespace="/lesson")
    try:
        sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
        sock.emit("lesson_code_update", {
            "lesson_id": lesson_id,
            "file_name": "main.py",
            "code": "student_unauthorized_edit = True",
        }, namespace="/lesson")

        events = sock.get_received("/lesson")
        acks = [e["args"][0] for e in events if e["name"] == "lesson_code_ack"]
        assert len(acks) == 0, "Student without editing permission received a save ack!"
    finally:
        sock.disconnect(namespace="/lesson")
