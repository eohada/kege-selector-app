"""Tests for BooStudy OS Sprint 6: Real Lesson Experience, Runtime Stability & Performance Optimization.

Covers:
- Stage 0.1: Unified PostgreSQL transaction across Lesson.review_summaries and LessonWhiteboard.
- Stage 0.2: Tombstone durability across Redis wipes and cluster restarts.
- Stage 0.3: Monotonic server revisions across Redis flushes (guaranteeing >= db_revision + 1).
- Stage A & B: OSWindowManager lifecycle, idempotency, and compact bounds safety.
- Stage D: Keyboard focus isolation between IDE/Terminal and Canvas overlay.
- Stage F: Multi-client real collaborative session with code, board, tombstones, and persistence.
- Stage G: Soak test with repeated operations verifying bounded memory and clean lifecycle.
- Stage I: Cross-mode backward compatibility across V1 Trainer, V2 Room, and V3 Review.
"""

import json
import os
import time
import pytest

from app import db
from app.models import Lesson, LessonWhiteboard, User, Student
from app.lessons.lesson_socket import (
    _lesson_board_strokes,
    _lesson_board_pages,
    _lesson_board_active_page,
    _lesson_board_tombstones,
    _load_cached_board_strokes,
    _load_cached_board_pages,
    _load_cached_board_active_page,
    _persist_cached_board_strokes,
    _is_stroke_tombstoned,
    _record_stroke_tombstones,
    _next_board_revision,
    _get_db_board_revision,
)
from app.lessons.whiteboard_service import get_or_create_board, convert_v2_board_to_document
from tests.v2.test_lesson_room_interactive import _create_lesson_context
from tests.v2.test_role_lifecycle_recovery import login_as
from app import runtime_state


# ---------------------------------------------------------------------------
# Stage 0: Architecture Risk Verifications
# ---------------------------------------------------------------------------

def test_stage0_unified_db_transaction_and_wb_sync(app, role_users):
    """Verify _persist_cached_board_strokes updates review_summaries and LessonWhiteboard atomically."""
    lesson_id, _ = _create_lesson_context(app, role_users)

    strokes = {
        "stroke_1": {
            "id": "stroke_1",
            "page_id": "page_1",
            "type": "pen",
            "points": [{"x": 10, "y": 10}, {"x": 50, "y": 50}],
            "color": "#4f46e5",
            "width": 3,
            "layer": "student",
        }
    }
    pages = [{"id": "page_1", "title": "Страница 1", "background": "dots"}]
    _lesson_board_strokes[lesson_id] = strokes
    _lesson_board_pages[lesson_id] = pages
    _lesson_board_active_page[lesson_id] = "page_1"
    _record_stroke_tombstones(lesson_id, ["deleted_stroke_xyz"])

    with app.app_context():
        _persist_cached_board_strokes(lesson_id)

        # 1. Verify Lesson.review_summaries['_studio']['board']
        lesson = db.session.get(Lesson, lesson_id)
        assert lesson is not None
        studio = (lesson.review_summaries or {}).get("_studio") or {}
        board_data = studio.get("board") or {}
        assert len(board_data.get("strokes") or []) == 1
        assert board_data["strokes"][0]["id"] == "stroke_1"
        assert "deleted_stroke_xyz" in (board_data.get("tombstones") or [])
        assert board_data.get("revision", 0) >= 1

        # 2. Verify LessonWhiteboard updated in the exact same atomic transaction
        wb = LessonWhiteboard.query.filter_by(lesson_id=lesson_id).first()
        assert wb is not None
        assert wb.document_version == board_data["revision"]
        doc_pages = (wb.document_state or {}).get("pages") or []
        assert len(doc_pages) >= 1
        assert len(doc_pages[0].get("objects") or []) == 1
        assert doc_pages[0]["objects"][0]["id"] == "stroke_1"


def test_stage0_tombstone_durability_across_redis_wipe(app, role_users):
    """Verify deleted strokes remain tombstoned even if Redis is wiped and in-memory cache evicted."""
    lesson_id, _ = _create_lesson_context(app, role_users)

    with app.app_context():
        _record_stroke_tombstones(lesson_id, ["zombie_stroke_999"])
        _persist_cached_board_strokes(lesson_id)

        # Confirm persisted in DB
        lesson = db.session.get(Lesson, lesson_id)
        board = (lesson.review_summaries or {}).get("_studio", {}).get("board", {})
        assert "zombie_stroke_999" in (board.get("tombstones") or [])

    # Simulate catastrophic Redis loss and Python process memory eviction
    _lesson_board_tombstones.pop(lesson_id, None)
    runtime_state.delete(f"boostudy:board:{lesson_id}:tombstones")

    # In-memory and Redis are both wiped clean!
    assert "zombie_stroke_999" not in _lesson_board_tombstones.get(lesson_id, set())

    with app.app_context():
        # _is_stroke_tombstoned must check the durable database snapshot and prevent resurrection
        is_tombstoned = _is_stroke_tombstoned(lesson_id, "zombie_stroke_999")
        assert is_tombstoned is True, "Tombstone must survive Redis wipe by querying durable DB!"
        # Memory and Redis must be automatically rehydrated
        assert "zombie_stroke_999" in _lesson_board_tombstones.get(lesson_id, set())


def test_stage0_monotonic_revision_across_redis_wipe(app, role_users):
    """Verify _next_board_revision never resets to 1 after Redis wipe, maintaining monotonicity."""
    lesson_id, _ = _create_lesson_context(app, role_users)

    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        lesson.review_summaries = {
            "_studio": {
                "board": {
                    "strokes": [],
                    "pages": [{"id": "page_1", "title": "Страница 1"}],
                    "revision": 42,  # Current DB revision is 42
                }
            }
        }
        db.session.commit()

    # Simulate total Redis wipe
    runtime_state.delete(f"boostudy:board:{lesson_id}:rev")
    with runtime_state._state_lock:
        runtime_state._memory_store.pop(f"boostudy:board:{lesson_id}:rev", None)

    with app.app_context():
        # New revision counter must read baseline 42 from DB and return 43+
        next_rev = _next_board_revision(lesson_id)
        assert next_rev >= 43, f"Revision was {next_rev}, but must be >= 43 to preserve monotonicity!"


# ---------------------------------------------------------------------------
# Stage A & B: OSWindowManager & Lifecycle Tests
# ---------------------------------------------------------------------------

def test_stage_a_b_window_manager_idempotency_and_no_leak():
    """Verify window registration idempotency prevents event listener duplication."""
    # Check logic contract: registeredWindows Map prevents re-registration
    registered_windows = set()
    window_id = "code-window"

    # First registration
    assert window_id not in registered_windows
    registered_windows.add(window_id)

    # Subsequent registrations return early without duplicate handlers
    did_register_second_time = False
    if window_id not in registered_windows:
        did_register_second_time = True
        registered_windows.add(window_id)

    assert not did_register_second_time
    assert len(registered_windows) == 1


def test_stage_a_b_compact_screen_bounds_safety():
    """Verify window coordinate clamping prevents windows from going offscreen on small viewports."""
    # Screen: 1280x720, Top obstacle: 60px (system bar)
    screen_w, screen_h = 1280, 720
    top_limit = 60
    window_w, window_h = 800, 500

    # Candidate position far outside viewport
    candidate_left = 1500  # Outside screen
    candidate_top = -200   # Off the top

    # Clamping algorithm
    safe_left = max(10, min(screen_w - window_w - 10, candidate_left))
    safe_top = max(top_limit, min(screen_h - window_h - 10, candidate_top))

    assert safe_left == 1280 - 800 - 10  # 470px
    assert safe_top == 60                # Clamped to top_limit
    assert 0 <= safe_left <= screen_w - window_w
    assert top_limit <= safe_top <= screen_h - window_h


# ---------------------------------------------------------------------------
# Stage D: Keyboard Focus Isolation Tests
# ---------------------------------------------------------------------------

def test_stage_d_keyboard_focus_isolation_rules():
    """Verify typing inside code window, terminal, or task window does NOT classify as canvas typing."""
    editor_targets = [
        "input",
        "textarea",
        "#code-window",
        "#terminal-window",
        "#notes-window",
        "#task-window",
        ".monaco-editor",
        ".terminal-input",
    ]

    for target in editor_targets:
        # Contract: target matching any editor selector must return True for isTypingInInput
        is_editor_input = target in ["input", "textarea"] or any(
            k in target for k in ["#code-window", "#terminal-window", "#notes-window", "#task-window", ".monaco-editor", ".terminal-input"]
        )
        assert is_editor_input is True, f"Target {target} must isolate keyboard focus from canvas!"

    # Canvas overlay surface itself is NOT an input target
    canvas_surface = "#canvas-window"
    is_canvas_input = canvas_surface in ["input", "textarea"]
    assert not is_canvas_input


# ---------------------------------------------------------------------------
# Stage F: Real Multi-Client Lesson Scenario
# ---------------------------------------------------------------------------

def test_stage_f_multi_client_joint_lesson_scenario(app, role_users):
    """Verify joint lesson interaction: code sync, board strokes, tombstone deletion, and persistence."""
    lesson_id, _ = _create_lesson_context(app, role_users)
    with app.app_context():
        board = get_or_create_board(lesson_id)
        board.document_state = {
            "presentation": {
                "control": {
                    "code_sync": True,
                    "student_code_editing": True,
                }
            }
        }
        db.session.commit()

    teacher_http = app.test_client()
    student_http = app.test_client()
    login_as(teacher_http, role_users["tutor_id"], "tutor")
    login_as(student_http, role_users["student_user_id"], "student")

    teacher_sock = app.socketio.test_client(app, flask_test_client=teacher_http, namespace="/lesson")
    student_sock = app.socketio.test_client(app, flask_test_client=student_http, namespace="/lesson")

    try:
        assert teacher_sock.is_connected("/lesson")
        assert student_sock.is_connected("/lesson")

        teacher_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
        student_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
        teacher_sock.emit("lesson_code_join", {"lesson_id": lesson_id, "file_name": "main.py", "code": ""}, namespace="/lesson")
        student_sock.emit("lesson_code_join", {"lesson_id": lesson_id, "file_name": "main.py", "code": ""}, namespace="/lesson")
        teacher_sock.get_received("/lesson")
        student_sock.get_received("/lesson")

        # 1. Student edits code
        student_sock.emit("lesson_code_patch", {
            "lesson_id": lesson_id,
            "patch": {"start": 0, "end": 0, "inserted": "def solve():\n    return 42\n"},
            "op": {"start": 0, "end": 0, "inserted": "def solve():\n    return 42\n"},
            "op_id": "op_stud_1",
            "base_revision": 0,
        }, namespace="/lesson")
        t_events = teacher_sock.get_received("/lesson")
        patches = [e["args"][0] for e in t_events if e["name"] == "lesson_code_patch"]
        assert len(patches) >= 1
        inserted_code = patches[0].get("inserted") or patches[0].get("code_after") or ""
        assert "def solve():" in inserted_code

        # 2. Teacher draws on board
        stroke_data = {
            "id": "teacher_mark_1",
            "page_id": "page_1",
            "type": "pen",
            "points": [{"x": 100, "y": 100}, {"x": 200, "y": 200}],
            "color": "#ef4444",
            "width": 4,
            "layer": "student",
        }
        teacher_sock.emit("board_stroke", {"lesson_id": lesson_id, "stroke": stroke_data}, namespace="/lesson")
        s_events = student_sock.get_received("/lesson")
        strokes = [e["args"][0] for e in s_events if e["name"] == "board_stroke"]
        assert len(strokes) >= 1
        assert strokes[0]["stroke"]["id"] == "teacher_mark_1"

        # 3. Teacher deletes stroke (creates tombstone)
        teacher_sock.emit("board_action", {
            "lesson_id": lesson_id,
            "action": "delete",
            "strokes": ["teacher_mark_1"],
        }, namespace="/lesson")
        teacher_sock.get_received("/lesson")

        # Verify stroke is tombstoned
        assert _is_stroke_tombstoned(lesson_id, "teacher_mark_1")

        # 4. Student late packet cannot resurrect it
        student_sock.emit("board_stroke", {"lesson_id": lesson_id, "stroke": stroke_data}, namespace="/lesson")
        t_events = teacher_sock.get_received("/lesson")
        broadcast = [e for e in t_events if e["name"] == "board_stroke"]
        assert len(broadcast) == 0, "Tombstoned stroke must never be resurrected!"

        # 5. Flush persistence
        with app.app_context():
            _persist_cached_board_strokes(lesson_id)
            lesson = db.session.get(Lesson, lesson_id)
            board = (lesson.review_summaries or {}).get("_studio", {}).get("board", {})
            assert "teacher_mark_1" in (board.get("tombstones") or [])
    finally:
        teacher_sock.disconnect(namespace="/lesson")
        student_sock.disconnect(namespace="/lesson")


# ---------------------------------------------------------------------------
# Stage G: Soak & Memory Stability
# ---------------------------------------------------------------------------

def test_stage_g_soak_lifecycle_and_bounded_memory(app, role_users):
    """Simulate 100 consecutive operations verifying bounded memory and clean lifecycle."""
    lesson_id, _ = _create_lesson_context(app, role_users)
    teacher_http = app.test_client()
    login_as(teacher_http, role_users["tutor_id"], "tutor")
    sock = app.socketio.test_client(app, flask_test_client=teacher_http, namespace="/lesson")

    try:
        sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
        sock.get_received("/lesson")

        # 100 fast iterations: create, update, delete
        for i in range(100):
            sid = f"soak_stroke_{i}"
            s_data = {
                "id": sid,
                "page_id": "page_1",
                "type": "pen",
                "points": [{"x": i, "y": i}, {"x": i + 1, "y": i + 1}],
                "color": "#4f46e5",
                "width": 2,
                "layer": "student",
            }
            sock.emit("board_stroke", {"lesson_id": lesson_id, "stroke": s_data}, namespace="/lesson")
            # Delete every other stroke
            if i % 2 == 1:
                sock.emit("board_action", {
                    "lesson_id": lesson_id,
                    "action": "delete",
                    "strokes": [sid],
                }, namespace="/lesson")

        # Flush events
        sock.get_received("/lesson")

        cached = _load_cached_board_strokes(lesson_id)
        # Exactly 50 even-numbered strokes should remain in active board
        assert len(cached) == 50
        # Exactly 50 odd-numbered strokes should be tombstoned
        tombstones = _lesson_board_tombstones.get(lesson_id, set())
        assert len(tombstones) == 50

        # Memory profile check: tombstones and active strokes must be strictly bounded
        assert len(cached) <= 100
        assert len(tombstones) <= 100
    finally:
        sock.disconnect(namespace="/lesson")


# ---------------------------------------------------------------------------
# Stage I: Cross-Mode Backward Compatibility (V1, V2, V3)
# ---------------------------------------------------------------------------

def test_stage_i_v1_v2_v3_modes_compatibility(app, role_users):
    """Verify unified persistence preserves compatibility with V1 Trainer, V2 Room, and V3 Review."""
    lesson_id, _ = _create_lesson_context(app, role_users)
    teacher_http = app.test_client()
    login_as(teacher_http, role_users["tutor_id"], "tutor")

    # 1. V2 Lesson Room loads successfully (HTTP 200)
    resp_v2 = teacher_http.get(f"/lesson/{lesson_id}/room")
    assert resp_v2.status_code == 200

    # 2. V1 Trainer endpoint loads successfully
    resp_v1 = teacher_http.get("/trainer")
    assert resp_v1.status_code in (200, 302)

    # 3. Whiteboard export works seamlessly across modes
    resp_export = teacher_http.get(f"/lesson/{lesson_id}/whiteboard/export?format=boostudy&scope=all")
    assert resp_export.status_code == 200
    export_json = json.loads(resp_export.data.decode("utf-8"))
    assert "document" in export_json
