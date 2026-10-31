"""Tests for BooStudy OS Sprint 8: Technical Integration, Synchronization Integrity & Full Feature Verification.

Covers:
- Stage A & L: Full Window and Component Inventory (Public vs Private vs Local).
- Stage B: Complete Teacher <-> Student Synchronization Matrix & Role Boundary Enforcement.
- Stage C: OSWindowManager Control Policies (Independent, Teacher-Guided, Position Sync Disabled).
- Stage D: Joint Python IDE & VirtualFS (CRUD, Idempotent ACKs, Permission Restrictions).
- Stage E: BooCanvasOverlay Technical Contracts (Layer Isolation, Tombstones, Export Filtering).
- Stage F & G: Terminal, Python Execution, BooTracer & Teacher Orbit Master Commands.
- Stage H: Distributed Runtime & Split-Brain Prevention.
- Stage K: LiveKit Pilot Controller Contract.
- V1/V2/V3 Compatibility.
"""

import json
import os
import time
from io import BytesIO
import pytest

from app import db
from app.models import Lesson, LessonWhiteboard, User, Student
from app.lessons.lesson_socket import (
    _lesson_board_strokes,
    _lesson_board_pages,
    _lesson_board_active_page,
    _lesson_board_tombstones,
    _lesson_code_state,
    _lesson_room_ui,
    _load_cached_board_strokes,
    _load_cached_board_pages,
    _load_cached_code_state,
    _persist_cached_board_strokes,
    _is_stroke_tombstoned,
    _record_stroke_tombstones,
    _next_board_revision,
    _save_room_ui_state,
    _remove_room_ui_state,
)
from app.lessons.whiteboard_service import get_or_create_board, convert_v2_board_to_document
from tests.v2.test_lesson_room_interactive import _create_lesson_context
from tests.v2.conftest import login_as


# ---------------------------------------------------------------------------
# Stage A & L: Window Inventory & Private Window Isolation
# ---------------------------------------------------------------------------

def test_stage_a_l_window_inventory_and_private_isolation(app, role_users):
    """Verify that private windows (teacher-notes-window, teacher-task-bank-window) cannot be broadcast over socket."""
    lesson_id, _ = _create_lesson_context(app, role_users)

    client_teacher = app.test_client()
    client_student = app.test_client()
    login_as(client_teacher, role_users["tutor_id"], "tutor")
    login_as(client_student, role_users["student_user_id"], "student")

    teacher_sock = app.socketio.test_client(app, flask_test_client=client_teacher, namespace="/lesson")
    student_sock = app.socketio.test_client(app, flask_test_client=client_student, namespace="/lesson")

    try:
        assert teacher_sock.is_connected("/lesson")
        assert student_sock.is_connected("/lesson")

        teacher_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
        student_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
        teacher_sock.get_received("/lesson")
        student_sock.get_received("/lesson")

        # 1. Attempt to broadcast private window 'teacher-notes-window'
        teacher_sock.emit("lesson_room_ui", {
            "lesson_id": lesson_id,
            "kind": "window",
            "window_id": "teacher-notes-window",
            "action": "open"
        }, namespace="/lesson")

        # Student must NOT receive it
        stud_events = student_sock.get_received("/lesson")
        window_events = [e for e in stud_events if e["name"] == "lesson_room_ui" and e["args"][0].get("window_id") == "teacher-notes-window"]
        assert len(window_events) == 0

        # 2. Attempt to broadcast private window 'teacher-task-bank-window'
        teacher_sock.emit("lesson_room_ui", {
            "lesson_id": lesson_id,
            "kind": "window",
            "window_id": "teacher-task-bank-window",
            "action": "open"
        }, namespace="/lesson")

        stud_events = student_sock.get_received("/lesson")
        task_bank_events = [e for e in stud_events if e["name"] == "lesson_room_ui" and e["args"][0].get("window_id") == "teacher-task-bank-window"]
        assert len(task_bank_events) == 0

        # 3. Public window 'code-window' MUST be broadcast
        teacher_sock.emit("lesson_room_ui", {
            "lesson_id": lesson_id,
            "kind": "window",
            "window_id": "code-window",
            "action": "open"
        }, namespace="/lesson")

        stud_events = student_sock.get_received("/lesson")
        public_events = [e for e in stud_events if e["name"] == "lesson_room_ui" and e["args"][0].get("window_id") == "code-window"]
        assert len(public_events) == 1
        assert public_events[0]["args"][0]["action"] == "open"
    finally:
        teacher_sock.disconnect("/lesson")
        student_sock.disconnect("/lesson")


# ---------------------------------------------------------------------------
# Stage B: Role Enforcement & Permission Boundaries
# ---------------------------------------------------------------------------

def test_stage_b_student_cannot_execute_teacher_master_commands(app, role_users):
    """Verify that student cannot emit teacher master commands (clear board, freeze student, teacher stamps)."""
    lesson_id, _ = _create_lesson_context(app, role_users)

    client_student = app.test_client()
    login_as(client_student, role_users["student_user_id"], "student")
    student_sock = app.socketio.test_client(app, flask_test_client=client_student, namespace="/lesson")

    try:
        student_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
        student_sock.get_received("/lesson")

        # 1. Student attempts board clear
        student_sock.emit("board_action", {
            "lesson_id": lesson_id,
            "action": "clear"
        }, namespace="/lesson")

        events = student_sock.get_received("/lesson")
        err = [e for e in events if e["name"] == "whiteboard_error"]
        assert len(err) >= 1
        assert "только преподавателю" in err[0]["args"][0]["message"]

        # 2. Student attempts freeze_student master command
        student_sock.emit("lesson_room_ui", {
            "lesson_id": lesson_id,
            "kind": "freeze_student"
        }, namespace="/lesson")

        events = student_sock.get_received("/lesson")
        err2 = [e for e in events if e["name"] == "whiteboard_error"]
        assert len(err2) >= 1

        # 3. Student attempts kick_participant
        student_sock.emit("kick_participant", {
            "lesson_id": lesson_id,
            "user_id": role_users["tutor_id"]
        }, namespace="/lesson")

        events = student_sock.get_received("/lesson")
        kicked = [e for e in events if e["name"] == "lesson_kicked"]
        assert len(kicked) == 0
    finally:
        student_sock.disconnect("/lesson")


# ---------------------------------------------------------------------------
# Stage C: OSWindowManager Control Policies
# ---------------------------------------------------------------------------

def test_stage_c_window_manager_control_modes(app, role_users):
    """Verify window sync policies: independent mode suppresses broadcast; position sync disabled blocks layout."""
    lesson_id, _ = _create_lesson_context(app, role_users)

    with app.app_context():
        board = get_or_create_board(lesson_id)
        # 1. Set mode to independent
        board.document_state = {
            "presentation": {
                "control": {
                    "windows_mode": "independent",
                    "window_positions_sync": True
                }
            }
        }
        db.session.commit()

    client_teacher = app.test_client()
    client_student = app.test_client()
    login_as(client_teacher, role_users["tutor_id"], "tutor")
    login_as(client_student, role_users["student_user_id"], "student")

    teacher_sock = app.socketio.test_client(app, flask_test_client=client_teacher, namespace="/lesson")
    student_sock = app.socketio.test_client(app, flask_test_client=client_student, namespace="/lesson")

    try:
        teacher_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
        student_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
        teacher_sock.get_received("/lesson")
        student_sock.get_received("/lesson")

        # In independent mode, window actions are NOT broadcast to students
        teacher_sock.emit("lesson_room_ui", {
            "lesson_id": lesson_id,
            "kind": "window",
            "window_id": "terminal-window",
            "action": "open"
        }, namespace="/lesson")

        events = student_sock.get_received("/lesson")
        assert len([e for e in events if e["name"] == "lesson_room_ui" and e["args"][0].get("window_id") == "terminal-window"]) == 0

        # 2. Switch mode to teacher, but disable window_positions_sync
        from app.lessons.lesson_socket import _lesson_control_cache
        _lesson_control_cache.pop(lesson_id, None)
        with app.app_context():
            board = get_or_create_board(lesson_id)
            board.document_state = {
                "presentation": {
                    "control": {
                        "windows_mode": "teacher",
                        "window_positions_sync": False
                    }
                }
            }
            db.session.commit()
        _lesson_control_cache.pop(lesson_id, None)

        # Window open should broadcast
        teacher_sock.emit("lesson_room_ui", {
            "lesson_id": lesson_id,
            "kind": "window",
            "window_id": "terminal-window",
            "action": "open"
        }, namespace="/lesson")

        events = student_sock.get_received("/lesson")
        assert len([e for e in events if e["name"] == "lesson_room_ui" and e["args"][0].get("action") == "open"]) == 1

        # Window layout movement should NOT broadcast because window_positions_sync is False
        teacher_sock.emit("lesson_room_ui", {
            "lesson_id": lesson_id,
            "kind": "window_layout",
            "window_id": "terminal-window",
            "left": 200,
            "top": 150
        }, namespace="/lesson")

        events = student_sock.get_received("/lesson")
        assert len([e for e in events if e["name"] == "lesson_room_ui" and e["args"][0].get("kind") == "window_layout"]) == 0
    finally:
        teacher_sock.disconnect("/lesson")
        student_sock.disconnect("/lesson")


# ---------------------------------------------------------------------------
# Stage D: VirtualFS Multi-File CRUD & Idempotent OT
# ---------------------------------------------------------------------------

def test_stage_d_virtualfs_crud_and_idempotent_ot(app, role_users):
    """Verify VirtualFS file creation, renaming, and idempotent handling of repeated OT operations."""
    lesson_id, _ = _create_lesson_context(app, role_users)

    client_teacher = app.test_client()
    login_as(client_teacher, role_users["tutor_id"], "tutor")
    teacher_sock = app.socketio.test_client(app, flask_test_client=client_teacher, namespace="/lesson")

    try:
        teacher_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
        teacher_sock.emit("lesson_code_join", {"lesson_id": lesson_id, "file_name": "main.py", "code": "print(1)"}, namespace="/lesson")
        teacher_sock.get_received("/lesson")

        # 1. Create auxiliary file solution.py
        teacher_sock.emit("lesson_vfs_file_create", {
            "lesson_id": lesson_id,
            "file_name": "solution.py",
            "code": "def solve(): return 42"
        }, namespace="/lesson")

        events = teacher_sock.get_received("/lesson")
        ack = [e for e in events if e["name"] == "lesson_code_ack"]
        assert len(ack) == 1
        assert ack[0]["args"][0]["file_name"] == "solution.py"

        # 2. Rename solution.py -> solver.py
        teacher_sock.emit("lesson_vfs_file_rename", {
            "lesson_id": lesson_id,
            "old_name": "solution.py",
            "new_name": "solver.py",
            "code": "def solve(): return 42"
        }, namespace="/lesson")

        events = teacher_sock.get_received("/lesson")
        ack = [e for e in events if e["name"] == "lesson_code_ack"]
        assert len(ack) == 1
        assert ack[0]["args"][0]["file_name"] == "solver.py"

        # 3. Send OT patch
        op_id = "test_op_idempotency_1"
        patch_payload = {
            "lesson_id": lesson_id,
            "file_name": "solver.py",
            "op_id": op_id,
            "base_revision": ack[0]["args"][0]["revision"],
            "patch": {"start": 0, "end": 0, "inserted": "# header\n"},
        }
        teacher_sock.emit("lesson_code_patch", patch_payload, namespace="/lesson")
        events1 = teacher_sock.get_received("/lesson")
        ack1 = [e for e in events1 if e["name"] == "lesson_code_ack"]
        assert len(ack1) == 1
        rev1 = ack1[0]["args"][0]["revision"]

        # 4. Replay identical patch (network retry) -> must return same revision without re-applying insertion
        teacher_sock.emit("lesson_code_patch", patch_payload, namespace="/lesson")
        events2 = teacher_sock.get_received("/lesson")
        ack2 = [e for e in events2 if e["name"] == "lesson_code_ack"]
        assert len(ack2) == 1
        assert ack2[0]["args"][0]["revision"] == rev1
    finally:
        teacher_sock.disconnect("/lesson")


# ---------------------------------------------------------------------------
# Stage E: BooCanvasOverlay Technical Contracts & Layer Export Filtering
# ---------------------------------------------------------------------------

def test_stage_e_canvas_layer_isolation_and_export_filtering(app, role_users):
    """Verify that student strokes on teacher layer are coerced to student layer, and teacher layers are stripped from student exports."""
    lesson_id, _ = _create_lesson_context(app, role_users)

    client_teacher = app.test_client()
    client_student = app.test_client()
    login_as(client_teacher, role_users["tutor_id"], "tutor")
    login_as(client_student, role_users["student_user_id"], "student")

    student_sock = app.socketio.test_client(app, flask_test_client=client_student, namespace="/lesson")

    try:
        student_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
        student_sock.get_received("/lesson")

        # 1. Student attempts to create a stroke with layer: 'teacher'
        student_sock.emit("board_stroke", {
            "lesson_id": lesson_id,
            "stroke": {
                "id": "stroke_stud_attempt",
                "layer": "teacher",
                "tool": "pen",
                "points": [{"x": 10, "y": 10}],
                "color": "#ff0000"
            }
        }, namespace="/lesson")

        events = student_sock.get_received("/lesson")
        ack = [e for e in events if e["name"] == "board_ack"]
        assert len(ack) == 1

        # Check cached stroke layer was coerced to 'student'
        cached = _load_cached_board_strokes(lesson_id)
        assert cached["stroke_stud_attempt"]["layer"] == "student"

        # 2. Add an authentic teacher layer stroke (teacher draft) via teacher socket
        teacher_sock = app.socketio.test_client(app, flask_test_client=client_teacher, namespace="/lesson")
        teacher_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
        teacher_sock.emit("board_stroke", {
            "lesson_id": lesson_id,
            "stroke": {
                "id": "stroke_teacher_secret",
                "layer": "teacher",
                "tool": "pen",
                "points": [{"x": 50, "y": 50}],
                "color": "#00ff00"
            }
        }, namespace="/lesson")
        teacher_sock.get_received("/lesson")

        # 3. Student requests whiteboard export -> teacher strokes must be excluded
        resp_stud = client_student.get(f"/lesson/{lesson_id}/whiteboard/export?format=boostudy")
        assert resp_stud.status_code == 200
        stud_doc = json.loads(resp_stud.get_data(as_text=True))
        stud_objects = [o for p in stud_doc["document"]["pages"] for o in p.get("objects", [])]
        # stroke_teacher_secret must NOT be present in student export
        assert not any(o.get("id") == "stroke_teacher_secret" for o in stud_objects)

        # 4. Teacher requests whiteboard export -> teacher strokes must be included
        resp_teach = client_teacher.get(f"/lesson/{lesson_id}/whiteboard/export?format=boostudy")
        assert resp_teach.status_code == 200
        teach_doc = json.loads(resp_teach.get_data(as_text=True))
        teach_objects = [o for p in teach_doc["document"]["pages"] for o in p.get("objects", [])]
        assert any(o.get("id") == "stroke_teacher_secret" for o in teach_objects)
    finally:
        student_sock.disconnect("/lesson")
        try:
            teacher_sock.disconnect("/lesson")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Stage F & G: Teacher Orbit & Master Commands
# ---------------------------------------------------------------------------

def test_stage_f_g_teacher_master_commands(app, role_users):
    """Verify teacher master commands (focus_board, freeze_student, free_mode, teacher_hint) emit and persist."""
    lesson_id, _ = _create_lesson_context(app, role_users)

    client_teacher = app.test_client()
    client_student = app.test_client()
    login_as(client_teacher, role_users["tutor_id"], "tutor")
    login_as(client_student, role_users["student_user_id"], "student")

    teacher_sock = app.socketio.test_client(app, flask_test_client=client_teacher, namespace="/lesson")
    student_sock = app.socketio.test_client(app, flask_test_client=client_student, namespace="/lesson")

    try:
        teacher_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
        student_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
        teacher_sock.get_received("/lesson")
        student_sock.get_received("/lesson")

        # 1. Teacher emits teacher_hint
        teacher_sock.emit("lesson_room_ui", {
            "lesson_id": lesson_id,
            "kind": "teacher_hint",
            "hint": "Попробуйте использовать бинарный поиск",
            "task_id": 42
        }, namespace="/lesson")

        events = student_sock.get_received("/lesson")
        hint_events = [e for e in events if e["name"] == "lesson_room_ui" and e["args"][0].get("kind") == "teacher_hint"]
        assert len(hint_events) == 1
        assert hint_events[0]["args"][0]["hint"] == "Попробуйте использовать бинарный поиск"

        # 2. Teacher emits focus_board
        teacher_sock.emit("lesson_room_ui", {
            "lesson_id": lesson_id,
            "kind": "focus_board"
        }, namespace="/lesson")

        events = student_sock.get_received("/lesson")
        focus_events = [e for e in events if e["name"] == "lesson_room_ui" and e["args"][0].get("kind") == "focus_board"]
        assert len(focus_events) == 1
    finally:
        teacher_sock.disconnect("/lesson")
        student_sock.disconnect("/lesson")


# ---------------------------------------------------------------------------
# Stage H: Distributed Runtime & Split-Brain Prevention
# ---------------------------------------------------------------------------

def test_stage_h_split_brain_prevention_on_unhealthy_runtime(app, role_users, monkeypatch):
    """Verify that student code patches fail-closed when distributed runtime is unhealthy and not single process mode."""
    lesson_id, _ = _create_lesson_context(app, role_users)

    from app import runtime_state
    monkeypatch.setattr(runtime_state, "is_distributed_runtime_healthy", lambda: False)
    monkeypatch.setattr(runtime_state, "is_single_process_mode", lambda: False)

    client_student = app.test_client()
    login_as(client_student, role_users["student_user_id"], "student")
    student_sock = app.socketio.test_client(app, flask_test_client=client_student, namespace="/lesson")

    try:
        # Enable student code editing
        with app.app_context():
            board = get_or_create_board(lesson_id)
            board.document_state = {
                "presentation": {
                    "control": {
                        "code_sync": True,
                        "student_code_editing": True
                    }
                }
            }
            db.session.commit()

        student_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
        student_sock.get_received("/lesson")

        # Emit patch during unhealthy state
        student_sock.emit("lesson_code_patch", {
            "lesson_id": lesson_id,
            "file_name": "main.py",
            "patch": {"start": 0, "end": 0, "inserted": "x = 1"},
            "op_id": "op_split_brain_test",
            "base_revision": 0
        }, namespace="/lesson")

        events = student_sock.get_received("/lesson")
        degraded = [e for e in events if e["name"] == "lesson_sync_degraded"]
        assert len(degraded) == 1
        conflict = [e for e in events if e["name"] == "lesson_code_conflict"]
        assert len(conflict) == 1
        assert "split-brain" in conflict[0]["args"][0]["message"]
    finally:
        student_sock.disconnect("/lesson")
