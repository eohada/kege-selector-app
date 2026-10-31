"""BooStudy OS — Final Technical Confidence Pass: Adversarial Synchronization, Orbit & Recovery Suite.

Verifies:
1. Concurrent adversarial operations (code edit + canvas drawing, task switch + VFS save).
2. Teacher Orbit `freeze_student` real server-authoritative enforcement (blocks code, VFS, board strokes, whiteboard ops, REST save).
3. Legacy vs New Code Protocols (revision protection, race with OT, conflict resolution).
4. Board Tombstones & stale re-delivery rejection (preventing object resurrection).
5. Private Teacher Data Defense-in-Depth (Socket.IO events, snapshots, export filtering, private window isolation).
6. Cold-restart persistence durability & recovery from PostgreSQL (VirtualFS & BooCanvasOverlay).
"""

import json
import time
import pytest
from io import BytesIO

from app import db
from app.models import Lesson, LessonWhiteboard, User, Student
from app.lessons.lesson_socket import (
    _lesson_board_strokes,
    _lesson_board_pages,
    _lesson_board_active_page,
    _lesson_board_tombstones,
    _lesson_code_state,
    _lesson_room_ui,
    _lesson_control_cache,
    _load_cached_board_strokes,
    _load_cached_code_state,
    _persist_cached_board_strokes,
    _schedule_persist_cached_code_state,
    _is_stroke_tombstoned,
    _record_stroke_tombstones,
    _next_board_revision,
    _save_room_ui_state,
    _remove_room_ui_state,
    _room_control,
)
from tests.v2.test_lesson_room_interactive import _create_lesson_context
from tests.v2.conftest import login_as


def test_adversarial_concurrent_code_and_board(app, role_users):
    """Test that concurrent teacher code OT patches and student canvas strokes do not collide or corrupt state."""
    lesson_id, _ = _create_lesson_context(app, role_users)

    client_teacher = app.test_client()
    client_student = app.test_client()
    login_as(client_teacher, role_users["tutor_id"], "tutor")
    login_as(client_student, role_users["student_user_id"], "student")

    teacher_sock = app.socketio.test_client(app, flask_test_client=client_teacher, namespace="/lesson")
    student_sock = app.socketio.test_client(app, flask_test_client=client_student, namespace="/lesson")

    teacher_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
    student_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
    _ = teacher_sock.get_received("/lesson")
    _ = student_sock.get_received("/lesson")

    # 1. Teacher initializes code
    teacher_sock.emit("lesson_code_join", {"lesson_id": lesson_id, "code": "def solve():\n    pass\n"}, namespace="/lesson")
    _ = teacher_sock.get_received("/lesson")

    # 2. Interleaved operations: Teacher patches code while Student draws
    teacher_sock.emit("lesson_code_patch", {
        "lesson_id": lesson_id,
        "file_name": "main.py",
        "base_revision": 1,
        "op_id": "op_teach_1",
        "patch": {"start": 19, "end": 23, "inserted": "return 42"}
    }, namespace="/lesson")

    student_sock.emit("board_stroke", {
        "lesson_id": lesson_id,
        "stroke": {"id": "stroke_student_c1", "points": [10, 10, 20, 20], "color": "#2563eb", "layer": "student"}
    }, namespace="/lesson")

    teacher_sock.emit("lesson_code_patch", {
        "lesson_id": lesson_id,
        "file_name": "main.py",
        "base_revision": 2,
        "op_id": "op_teach_2",
        "patch": {"start": 28, "end": 28, "inserted": "\nprint(solve())"}
    }, namespace="/lesson")

    # Verify teacher received code ACKs
    t_events = teacher_sock.get_received("/lesson")
    t_acks = [e for e in t_events if e["name"] == "lesson_code_ack"]
    assert len(t_acks) >= 1
    assert t_acks[-1]["args"][0]["status"] == "synced"

    # Verify student received board ACK
    s_events = student_sock.get_received("/lesson")
    s_acks = [e for e in s_events if e["name"] == "board_ack"]
    assert len(s_acks) >= 1

    # Verify final states in memory/cache
    code_state = _load_cached_code_state(lesson_id)
    assert code_state["revision"] >= 3
    assert "return 42" in code_state["files"]["main.py"]

    board_strokes = _load_cached_board_strokes(lesson_id)
    assert "stroke_student_c1" in board_strokes


def test_adversarial_freeze_student_real_server_enforcement(app, role_users):
    """Test that Teacher Orbit freeze_student actively blocks student code, VFS, board and REST operations."""
    lesson_id, _ = _create_lesson_context(app, role_users)

    client_teacher = app.test_client()
    client_student = app.test_client()
    login_as(client_teacher, role_users["tutor_id"], "tutor")
    login_as(client_student, role_users["student_user_id"], "student")

    teacher_sock = app.socketio.test_client(app, flask_test_client=client_teacher, namespace="/lesson")
    student_sock = app.socketio.test_client(app, flask_test_client=client_student, namespace="/lesson")

    teacher_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
    student_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")

    # Grant student editing initially
    teacher_sock.emit("whiteboard_operation", {
        "lesson_id": lesson_id,
        "operation": {
            "type": "control.update",
            "control": {"student_code_editing": True, "board_locked": False, "code_sync": True}
        }
    }, namespace="/lesson")
    _ = teacher_sock.get_received("/lesson")
    _ = student_sock.get_received("/lesson")

    # 1. Teacher issues freeze_student
    teacher_sock.emit("lesson_room_ui", {
        "lesson_id": lesson_id,
        "kind": "freeze_student"
    }, namespace="/lesson")

    s_events = student_sock.get_received("/lesson")
    freeze_events = [e for e in s_events if e["name"] == "lesson_room_ui" and e["args"][0].get("kind") == "freeze_student"]
    assert len(freeze_events) == 1

    # Verify server control state
    ctrl = _room_control(lesson_id)
    assert ctrl.get("freeze_student") is True

    # 2. Student attempts forbidden operations while frozen
    # A. Code OT patch
    student_sock.emit("lesson_code_patch", {
        "lesson_id": lesson_id,
        "file_name": "main.py",
        "base_revision": 1,
        "op_id": "op_student_frozen",
        "patch": {"start": 0, "end": 0, "inserted": "# hacked"}
    }, namespace="/lesson")
    err_events = [e for e in student_sock.get_received("/lesson") if e["name"] == "whiteboard_error"]
    assert len(err_events) >= 1
    assert "заблокировано" in err_events[0]["args"][0]["message"]

    # B. Board stroke
    student_sock.emit("board_stroke", {
        "lesson_id": lesson_id,
        "stroke": {"id": "stroke_frozen_student", "points": [50, 50], "layer": "student"}
    }, namespace="/lesson")
    err_events = [e for e in student_sock.get_received("/lesson") if e["name"] == "whiteboard_error"]
    assert any("заблокировано" in e["args"][0]["message"] for e in err_events)
    assert "stroke_frozen_student" not in _load_cached_board_strokes(lesson_id)

    # C. VFS create file
    student_sock.emit("lesson_vfs_file_create", {
        "lesson_id": lesson_id,
        "file_name": "frozen_hack.py",
        "code": "print('fail')"
    }, namespace="/lesson")
    err_events = [e for e in student_sock.get_received("/lesson") if e["name"] == "whiteboard_error"]
    assert any("заблокировано" in e["args"][0]["message"] for e in err_events)
    assert "frozen_hack.py" not in (_load_cached_code_state(lesson_id) or {}).get("files", {})

    # D. REST Autosave
    res = client_student.post(f"/lesson/{lesson_id}/studio/os-code", json={
        "code": "# rest hack while frozen",
        "file_name": "main.py"
    })
    assert res.status_code == 403

    # E. Student attempts spoofed free_mode
    student_sock.emit("lesson_room_ui", {
        "lesson_id": lesson_id,
        "kind": "free_mode"
    }, namespace="/lesson")
    spoof_err = [e for e in student_sock.get_received("/lesson") if e["name"] == "whiteboard_error"]
    assert any("Недостаточно прав" in e["args"][0]["message"] for e in spoof_err)
    # Still frozen
    assert _room_control(lesson_id).get("freeze_student") is True

    # 3. Teacher issues genuine free_mode
    teacher_sock.emit("lesson_room_ui", {
        "lesson_id": lesson_id,
        "kind": "free_mode"
    }, namespace="/lesson")
    _ = student_sock.get_received("/lesson")
    assert _room_control(lesson_id).get("freeze_student") is False

    # Now student can draw and edit code again
    student_sock.emit("board_stroke", {
        "lesson_id": lesson_id,
        "stroke": {"id": "stroke_unfrozen", "points": [1, 2, 3], "layer": "student"}
    }, namespace="/lesson")
    s_ack = [e for e in student_sock.get_received("/lesson") if e["name"] == "board_ack"]
    assert len(s_ack) >= 1
    assert "stroke_unfrozen" in _load_cached_board_strokes(lesson_id)


def test_legacy_code_update_revision_protection_and_race(app, role_users):
    """Test that legacy lesson_code_update cannot silently overwrite newer OT revisions or bypass checks."""
    lesson_id, _ = _create_lesson_context(app, role_users)

    client_teacher = app.test_client()
    client_student = app.test_client()
    login_as(client_teacher, role_users["tutor_id"], "tutor")
    login_as(client_student, role_users["student_user_id"], "student")

    teacher_sock = app.socketio.test_client(app, flask_test_client=client_teacher, namespace="/lesson")
    student_sock = app.socketio.test_client(app, flask_test_client=client_student, namespace="/lesson")

    teacher_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
    student_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")

    # Allow student editing
    teacher_sock.emit("whiteboard_operation", {
        "lesson_id": lesson_id,
        "operation": {
            "type": "control.update",
            "control": {"student_code_editing": True, "code_sync": True}
        }
    }, namespace="/lesson")
    _ = teacher_sock.get_received("/lesson")
    _ = student_sock.get_received("/lesson")

    # Teacher sets initial code
    teacher_sock.emit("lesson_code_join", {
        "lesson_id": lesson_id,
        "code": "a = 10\nb = 20\n",
        "file_name": "main.py"
    }, namespace="/lesson")
    _ = teacher_sock.get_received("/lesson")

    # Teacher applies OT patch (advancing to revision 2)
    teacher_sock.emit("lesson_code_patch", {
        "lesson_id": lesson_id,
        "file_name": "main.py",
        "base_revision": 1,
        "op_id": "op_teach_adv",
        "patch": {"start": 0, "end": 6, "inserted": "a = 999"}
    }, namespace="/lesson")
    _ = teacher_sock.get_received("/lesson")

    code_state = _load_cached_code_state(lesson_id)
    assert code_state["revision"] >= 2
    assert "a = 999" in code_state["files"]["main.py"]

    # 1. Student sends legacy lesson_code_update with outdated base_revision = 1
    student_sock.emit("lesson_code_update", {
        "lesson_id": lesson_id,
        "file_name": "main.py",
        "base_revision": 1,
        "code": "STALE OVERWRITE FROM LEGACY CLIENT"
    }, namespace="/lesson")

    s_events = student_sock.get_received("/lesson")
    conflicts = [e for e in s_events if e["name"] == "lesson_code_conflict"]
    assert len(conflicts) == 1
    assert conflicts[0]["args"][0]["server_revision"] >= 2
    assert "STALE OVERWRITE" not in _load_cached_code_state(lesson_id)["files"]["main.py"]

    # 2. Student sends legacy lesson_code_update without base_revision
    student_sock.emit("lesson_code_update", {
        "lesson_id": lesson_id,
        "file_name": "main.py",
        "code": "ANOTHER ATTEMPT WITHOUT BASE REVISION"
    }, namespace="/lesson")

    s_events = student_sock.get_received("/lesson")
    conflicts_nobase = [e for e in s_events if e["name"] == "lesson_code_conflict"]
    assert len(conflicts_nobase) == 1
    assert "ANOTHER ATTEMPT" not in _load_cached_code_state(lesson_id)["files"]["main.py"]

    # 3. REST save with outdated base_revision returns 409
    res = client_student.post(f"/lesson/{lesson_id}/studio/os-code", json={
        "code": "REST OUTDATED CODE",
        "file_name": "main.py",
        "base_revision": 1
    })
    assert res.status_code == 409
    assert res.get_json()["conflict"] is True


def test_adversarial_tombstones_and_stale_operations(app, role_users):
    """Test that deleted board strokes generate permanent tombstones and cannot be resurrected."""
    lesson_id, _ = _create_lesson_context(app, role_users)

    client_teacher = app.test_client()
    client_student = app.test_client()
    login_as(client_teacher, role_users["tutor_id"], "tutor")
    login_as(client_student, role_users["student_user_id"], "student")

    teacher_sock = app.socketio.test_client(app, flask_test_client=client_teacher, namespace="/lesson")
    student_sock = app.socketio.test_client(app, flask_test_client=client_student, namespace="/lesson")

    teacher_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
    student_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")

    # 1. Teacher creates a stroke
    stroke_id = "stroke_victim_42"
    teacher_sock.emit("board_stroke", {
        "lesson_id": lesson_id,
        "stroke": {"id": stroke_id, "points": [10, 20, 30], "layer": "student"}
    }, namespace="/lesson")
    _ = teacher_sock.get_received("/lesson")

    assert stroke_id in _load_cached_board_strokes(lesson_id)

    # 2. Teacher deletes the stroke
    teacher_sock.emit("board_action", {
        "lesson_id": lesson_id,
        "action": "delete",
        "stroke_ids": [stroke_id]
    }, namespace="/lesson")
    _ = teacher_sock.get_received("/lesson")

    # Verify tombstone recorded
    assert _is_stroke_tombstoned(lesson_id, stroke_id)
    assert stroke_id not in _load_cached_board_strokes(lesson_id)

    # 3. Student resends stale packet with the deleted stroke ID
    student_sock.emit("board_stroke", {
        "lesson_id": lesson_id,
        "stroke": {"id": stroke_id, "points": [10, 20, 30, 40], "layer": "student"}
    }, namespace="/lesson")

    # Verify stroke is NOT resurrected
    assert stroke_id not in _load_cached_board_strokes(lesson_id)


def test_teacher_orbit_master_commands_and_reconnect(app, role_users):
    """Test that master commands (focus_board, task_switch) broadcast to students and survive reconnect."""
    lesson_id, _ = _create_lesson_context(app, role_users)

    client_teacher = app.test_client()
    client_student = app.test_client()
    login_as(client_teacher, role_users["tutor_id"], "tutor")
    login_as(client_student, role_users["student_user_id"], "student")

    teacher_sock = app.socketio.test_client(app, flask_test_client=client_teacher, namespace="/lesson")
    student_sock = app.socketio.test_client(app, flask_test_client=client_student, namespace="/lesson")

    teacher_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
    student_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
    _ = teacher_sock.get_received("/lesson")
    _ = student_sock.get_received("/lesson")

    # 1. Teacher issues focus_board
    teacher_sock.emit("lesson_room_ui", {
        "lesson_id": lesson_id,
        "kind": "focus_board"
    }, namespace="/lesson")

    s_events = student_sock.get_received("/lesson")
    focus_events = [e for e in s_events if e["name"] == "lesson_room_ui" and e["args"][0].get("kind") == "focus_board"]
    assert len(focus_events) == 1

    # 2. Teacher issues task_switch
    teacher_sock.emit("lesson_room_ui", {
        "lesson_id": lesson_id,
        "kind": "task_switch",
        "task_id": 9999
    }, namespace="/lesson")

    s_events2 = student_sock.get_received("/lesson")
    task_events = [e for e in s_events2 if e["name"] == "lesson_room_ui" and e["args"][0].get("kind") == "task_switch"]
    assert len(task_events) == 1
    assert task_events[0]["args"][0]["task_id"] == 9999

    # 3. Teacher issues timer_sync
    teacher_sock.emit("lesson_room_ui", {
        "lesson_id": lesson_id,
        "kind": "orbit_timer_sync",
        "action": "start",
        "seconds": 300,
        "isRunning": True
    }, namespace="/lesson")
    _ = student_sock.get_received("/lesson")

    # 4. Student disconnects and reconnects
    student_sock.disconnect(namespace="/lesson")

    student_sock2 = app.socketio.test_client(app, flask_test_client=client_student, namespace="/lesson")
    student_sock2.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")

    reconnect_events = student_sock2.get_received("/lesson")
    ui_states = [e for e in reconnect_events if e["name"] == "lesson_room_ui_state"]
    assert len(ui_states) >= 1
    # Check timer state was restored
    timer_payload = next((e["args"][0] for e in ui_states if e["args"][0].get("kind") == "orbit_timer_sync"), None)
    assert timer_payload is not None
    assert timer_payload.get("seconds") == 300


def test_private_teacher_data_defense_in_depth(app, role_users):
    """Test defense-in-depth isolation of teacher layers, notes and export."""
    lesson_id, _ = _create_lesson_context(app, role_users)

    client_teacher = app.test_client()
    client_student = app.test_client()
    login_as(client_teacher, role_users["tutor_id"], "tutor")
    login_as(client_student, role_users["student_user_id"], "student")

    teacher_sock = app.socketio.test_client(app, flask_test_client=client_teacher, namespace="/lesson")
    student_sock = app.socketio.test_client(app, flask_test_client=client_student, namespace="/lesson")

    teacher_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
    student_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
    _ = teacher_sock.get_received("/lesson")
    _ = student_sock.get_received("/lesson")

    # 1. Teacher creates private stroke on layer="teacher"
    teacher_sock.emit("board_stroke", {
        "lesson_id": lesson_id,
        "stroke": {"id": "stroke_teacher_secret", "points": [1, 2, 3], "layer": "teacher"}
    }, namespace="/lesson")

    # Teacher gets confirmation
    _ = teacher_sock.get_received("/lesson")

    # Student MUST NOT have received the teacher-layer stroke
    s_events = student_sock.get_received("/lesson")
    s_strokes = [e for e in s_events if e["name"] == "board_stroke"]
    assert len(s_strokes) == 0

    # 2. Student connects freshly: board_snapshot must filter out teacher strokes
    student_sock2 = app.socketio.test_client(app, flask_test_client=client_student, namespace="/lesson")
    student_sock2.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")

    s2_events = student_sock2.get_received("/lesson")
    snapshot = next(e["args"][0] for e in s2_events if e["name"] == "board_snapshot")
    assert not any(s.get("layer") == "teacher" for s in snapshot.get("strokes", []))

    # 3. Student attempts to export board: teacher layer must be omitted
    res = client_student.get(f"/lesson/{lesson_id}/whiteboard/export")
    assert res.status_code == 200
    export_data = json.loads(res.data)
    for stroke in export_data.get("strokes", []):
        assert stroke.get("layer") != "teacher"

    # 4. Student attempts to broadcast private teacher window
    student_sock.emit("lesson_room_ui", {
        "lesson_id": lesson_id,
        "kind": "window",
        "window_id": "teacher-notes-window",
        "action": "open"
    }, namespace="/lesson")

    t_events = teacher_sock.get_received("/lesson")
    leaked_windows = [e for e in t_events if e["name"] == "lesson_room_ui" and e["args"][0].get("window_id") == "teacher-notes-window"]
    assert len(leaked_windows) == 0


def test_persistence_durability_and_cold_restart_recovery(app, role_users):
    """Test that all VirtualFS and Whiteboard data persists to PostgreSQL and fully recovers after cold cache wipe."""
    lesson_id, _ = _create_lesson_context(app, role_users)

    client_teacher = app.test_client()
    login_as(client_teacher, role_users["tutor_id"], "tutor")
    teacher_sock = app.socketio.test_client(app, flask_test_client=client_teacher, namespace="/lesson")
    teacher_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")

    # 1. Create multi-file VFS project
    teacher_sock.emit("lesson_vfs_file_create", {
        "lesson_id": lesson_id,
        "file_name": "solution.py",
        "code": "def solve():\n    return 'durable'\n"
    }, namespace="/lesson")
    _ = teacher_sock.get_received("/lesson")

    # 2. Create board strokes and tombstone
    teacher_sock.emit("board_stroke", {
        "lesson_id": lesson_id,
        "stroke": {"id": "stroke_cold_1", "points": [100, 200], "layer": "student"}
    }, namespace="/lesson")
    teacher_sock.emit("board_stroke", {
        "lesson_id": lesson_id,
        "stroke": {"id": "stroke_to_delete", "points": [300, 400], "layer": "student"}
    }, namespace="/lesson")
    teacher_sock.emit("board_action", {
        "lesson_id": lesson_id,
        "action": "delete",
        "stroke_ids": ["stroke_to_delete"]
    }, namespace="/lesson")
    _ = teacher_sock.get_received("/lesson")

    # Force synchronous flush to PostgreSQL
    _persist_cached_board_strokes(lesson_id)
    from app.lessons.lesson_socket import _persist_cached_code_state
    _persist_cached_code_state(lesson_id)

    # 3. Simulate total crash / cold restart: Wipe all in-memory caches and Redis keys for this lesson
    _lesson_code_state.pop(lesson_id, None)
    _lesson_board_strokes.pop(lesson_id, None)
    _lesson_board_pages.pop(lesson_id, None)
    _lesson_board_active_page.pop(lesson_id, None)
    _lesson_board_tombstones.pop(lesson_id, None)
    _lesson_room_ui.pop(lesson_id, None)
    _lesson_control_cache.pop(lesson_id, None)

    from app.runtime_state import delete as redis_del
    from app.lessons.lesson_socket import _code_state_key, _board_state_key, _board_tombstones_key, _room_ui_key
    redis_del(_code_state_key(lesson_id))
    redis_del(_board_state_key(lesson_id))
    redis_del(_board_tombstones_key(lesson_id))
    redis_del(_room_ui_key(lesson_id))

    # 4. Verify VirtualFS recovers from PostgreSQL _os_workspace
    recovered_code = _load_cached_code_state(lesson_id)
    assert recovered_code is not None
    assert "solution.py" in recovered_code["files"]
    assert "durable" in recovered_code["files"]["solution.py"]

    # 5. Verify Whiteboard recovers strokes from PostgreSQL LessonWhiteboard & _studio
    recovered_board = _load_cached_board_strokes(lesson_id)
    assert "stroke_cold_1" in recovered_board
    assert "stroke_to_delete" not in recovered_board

    # 6. Verify Tombstone persists across cold wipe
    assert _is_stroke_tombstoned(lesson_id, "stroke_to_delete") is True


def test_invariant1_teacher_and_student_stale_snapshot_vs_ot_and_force(app, role_users):
    """
    Invariant 1: Legacy full snapshots without base_revision (or outdated) from either
    teacher or student cannot silently clobber newer OT revisions.
    Explicit 'force' replacement requires teacher authorization.
    """
    lesson_id, _ = _create_lesson_context(app, role_users)

    client_teacher = app.test_client()
    client_student = app.test_client()
    login_as(client_teacher, role_users["tutor_id"], "tutor")
    login_as(client_student, role_users["student_user_id"], "student")

    teacher_sock = app.socketio.test_client(app, flask_test_client=client_teacher, namespace="/lesson")
    student_sock = app.socketio.test_client(app, flask_test_client=client_student, namespace="/lesson")

    teacher_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
    student_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")

    # Enable student code editing
    teacher_sock.emit("whiteboard_operation", {
        "lesson_id": lesson_id,
        "operation": {
            "type": "control.update",
            "control": {"student_code_editing": True, "code_sync": True}
        }
    }, namespace="/lesson")
    _ = teacher_sock.get_received("/lesson")
    _ = student_sock.get_received("/lesson")

    # Initial code established by teacher at revision 1
    teacher_sock.emit("lesson_code_join", {
        "lesson_id": lesson_id,
        "code": "val = 1\n",
        "file_name": "main.py"
    }, namespace="/lesson")
    _ = teacher_sock.get_received("/lesson")
    _ = student_sock.get_received("/lesson")

    # Student issues OT patch advancing server state to revision 2
    student_sock.emit("lesson_code_patch", {
        "lesson_id": lesson_id,
        "file_name": "main.py",
        "base_revision": 1,
        "op_id": "op_stud_ot_1",
        "patch": {"start": 6, "end": 7, "inserted": "999"}
    }, namespace="/lesson")
    _ = student_sock.get_received("/lesson")
    _ = teacher_sock.get_received("/lesson")

    code_state = _load_cached_code_state(lesson_id)
    assert code_state["revision"] >= 2
    assert "val = 999" in code_state["files"]["main.py"]

    # 1. Teacher legacy client sends stale snapshot without base_revision and without force
    teacher_sock.emit("lesson_code_update", {
        "lesson_id": lesson_id,
        "file_name": "main.py",
        "code": "val = 1\n# teacher old snapshot"
    }, namespace="/lesson")
    t_events = teacher_sock.get_received("/lesson")
    t_conflicts = [e for e in t_events if e["name"] == "lesson_code_conflict"]
    assert len(t_conflicts) == 1
    assert t_conflicts[0]["args"][0]["server_revision"] >= 2
    # Verify student's code was NOT clobbered
    assert "val = 999" in _load_cached_code_state(lesson_id)["files"]["main.py"]

    # 2. Teacher client sends REST autosave without base_revision and without force
    res_t = client_teacher.post(f"/lesson/{lesson_id}/studio/os-code", json={
        "code": "val = 1\n# teacher rest stale",
        "file_name": "main.py"
    })
    assert res_t.status_code == 409
    assert res_t.get_json()["conflict"] is True
    assert "val = 999" in _load_cached_code_state(lesson_id)["files"]["main.py"]

    # 3. Student sends stale legacy snapshot without base_revision
    student_sock.emit("lesson_code_update", {
        "lesson_id": lesson_id,
        "file_name": "main.py",
        "code": "val = 1\n# student stale"
    }, namespace="/lesson")
    s_events = student_sock.get_received("/lesson")
    s_conflicts = [e for e in s_events if e["name"] == "lesson_code_conflict"]
    assert len(s_conflicts) == 1

    # 4. Student sends REST autosave without base_revision
    res_s = client_student.post(f"/lesson/{lesson_id}/studio/os-code", json={
        "code": "val = 1\n# student rest stale",
        "file_name": "main.py"
    })
    assert res_s.status_code == 409

    # 5. Student attempts spoofed 'force: True'
    student_sock.emit("lesson_code_update", {
        "lesson_id": lesson_id,
        "file_name": "main.py",
        "code": "val = 0\n# student spoofed force",
        "force": True
    }, namespace="/lesson")
    s_events_force = [e for e in student_sock.get_received("/lesson") if e["name"] == "lesson_code_conflict"]
    assert len(s_events_force) == 1

    res_s_force = client_student.post(f"/lesson/{lesson_id}/studio/os-code", json={
        "code": "val = 0\n# student rest spoofed force",
        "file_name": "main.py",
        "force": True
    })
    assert res_s_force.status_code == 409

    # 6. Teacher uses authorized 'force: True' via Socket.IO
    teacher_sock.emit("lesson_code_update", {
        "lesson_id": lesson_id,
        "file_name": "main.py",
        "code": "val = 777\n# intentional teacher replace",
        "force": True
    }, namespace="/lesson")
    _ = teacher_sock.get_received("/lesson")
    code_state_after_force = _load_cached_code_state(lesson_id)
    assert "val = 777" in code_state_after_force["files"]["main.py"]

    # 7. Teacher uses authorized 'force: True' via REST
    res_t_force = client_teacher.post(f"/lesson/{lesson_id}/studio/os-code", json={
        "code": "val = 888\n# intentional teacher rest replace",
        "file_name": "main.py",
        "force": True
    })
    assert res_t_force.status_code == 200
    assert "val = 888" in _load_cached_code_state(lesson_id)["files"]["main.py"]


def test_invariant2_freeze_full_path_consistency_and_reconnect(app, role_users):
    """
    Invariant 2: Full path freeze consistency:
    freeze_student -> Redis room_ui -> _room_control() -> Socket.IO guards -> REST /studio/os-code -> reconnect -> free_mode.
    Ensures 'freeze', 'is_frozen' and 'freeze_student' map identically and REST disallows save whenever Socket.IO denies editing.
    """
    lesson_id, _ = _create_lesson_context(app, role_users)

    client_teacher = app.test_client()
    client_student = app.test_client()
    login_as(client_teacher, role_users["tutor_id"], "tutor")
    login_as(client_student, role_users["student_user_id"], "student")

    teacher_sock = app.socketio.test_client(app, flask_test_client=client_teacher, namespace="/lesson")
    student_sock = app.socketio.test_client(app, flask_test_client=client_student, namespace="/lesson")

    teacher_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
    student_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")

    # Initial state: allow editing
    teacher_sock.emit("whiteboard_operation", {
        "lesson_id": lesson_id,
        "operation": {
            "type": "control.update",
            "control": {"student_code_editing": True, "board_locked": False, "code_sync": True}
        }
    }, namespace="/lesson")
    _ = teacher_sock.get_received("/lesson")
    _ = student_sock.get_received("/lesson")

    # Baseline: Student can save via REST and edit via Socket.IO
    res_base = client_student.post(f"/lesson/{lesson_id}/studio/os-code", json={
        "code": "# baseline student code",
        "file_name": "main.py",
        "base_revision": 0
    })
    assert res_base.status_code == 200

    # 1. Teacher issues freeze_student
    teacher_sock.emit("lesson_room_ui", {
        "lesson_id": lesson_id,
        "kind": "freeze_student"
    }, namespace="/lesson")
    _ = teacher_sock.get_received("/lesson")

    # Check mapping in _room_control and Redis
    from app.lessons.lesson_socket import _get_room_ui_state
    redis_freeze = _get_room_ui_state(lesson_id, "freeze")
    assert redis_freeze is not None
    assert redis_freeze.get("is_frozen") is True
    assert redis_freeze.get("freeze_student") is True

    ctrl = _room_control(lesson_id)
    assert ctrl.get("freeze_student") is True
    assert ctrl.get("is_frozen") is True

    # Student immediately blocked on REST save (HTTP 403)
    res_frozen = client_student.post(f"/lesson/{lesson_id}/studio/os-code", json={
        "code": "# frozen student save",
        "file_name": "main.py",
        "base_revision": 1
    })
    assert res_frozen.status_code == 403

    # Student immediately blocked on Socket.IO OT patch
    student_sock.emit("lesson_code_patch", {
        "lesson_id": lesson_id,
        "file_name": "main.py",
        "base_revision": 1,
        "op_id": "op_stud_blocked",
        "patch": {"start": 0, "end": 0, "inserted": "# blocked"}
    }, namespace="/lesson")
    errs = [e for e in student_sock.get_received("/lesson") if e["name"] == "whiteboard_error"]
    assert len(errs) >= 1
    assert "заблокировано" in errs[0]["args"][0]["message"]

    # 2. Student disconnects and reconnects
    student_sock.disconnect(namespace="/lesson")
    student_sock_reconnected = app.socketio.test_client(app, flask_test_client=client_student, namespace="/lesson")
    student_sock_reconnected.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")

    reconnect_events = student_sock_reconnected.get_received("/lesson")
    ui_states = [e for e in reconnect_events if e["name"] == "lesson_room_ui_state"]
    freeze_sync = [e for e in ui_states if e["args"][0].get("kind") in {"freeze_student", "freeze"} and e["args"][0].get("is_frozen")]
    assert len(freeze_sync) >= 1

    # Operations still blocked after reconnect
    res_reconnect = client_student.post(f"/lesson/{lesson_id}/studio/os-code", json={
        "code": "# post reconnect save",
        "file_name": "main.py",
        "base_revision": 1
    })
    assert res_reconnect.status_code == 403

    # 3. Teacher issues free_mode
    teacher_sock.emit("lesson_room_ui", {
        "lesson_id": lesson_id,
        "kind": "free_mode"
    }, namespace="/lesson")
    _ = teacher_sock.get_received("/lesson")
    _ = student_sock_reconnected.get_received("/lesson")

    # Verify Redis and _room_control updated immediately
    assert _get_room_ui_state(lesson_id, "freeze") is None
    ctrl_unfrozen = _room_control(lesson_id)
    assert ctrl_unfrozen.get("freeze_student") is False
    assert ctrl_unfrozen.get("is_frozen") is False

    # Student REST save succeeds (HTTP 200)
    res_unfrozen = client_student.post(f"/lesson/{lesson_id}/studio/os-code", json={
        "code": "# unfrozen success",
        "file_name": "main.py",
        "base_revision": 1
    })
    assert res_unfrozen.status_code == 200

    # 4. Teacher issues kind='freeze' with is_frozen=True (verifying alternative kind format)
    teacher_sock.emit("lesson_room_ui", {
        "lesson_id": lesson_id,
        "kind": "freeze",
        "is_frozen": True
    }, namespace="/lesson")
    _ = teacher_sock.get_received("/lesson")

    assert _room_control(lesson_id).get("freeze_student") is True
    res_freeze2 = client_student.post(f"/lesson/{lesson_id}/studio/os-code", json={
        "code": "# freeze2 attempt",
        "file_name": "main.py",
        "base_revision": 2
    })
    assert res_freeze2.status_code == 403

    # Teacher lifts with kind='freeze', is_frozen=False
    teacher_sock.emit("lesson_room_ui", {
        "lesson_id": lesson_id,
        "kind": "freeze",
        "is_frozen": False
    }, namespace="/lesson")
    _ = teacher_sock.get_received("/lesson")
    assert _room_control(lesson_id).get("freeze_student") is False
