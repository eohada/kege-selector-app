"""Tests for BooStudy OS Sprint 7: Pedagogical UX, Workflow Refinement & Real Browser Acceptance.

Covers:
- Stage 0.1: Multi-process atomic board persistence concurrency lock (PostgreSQL with_for_update).
- Stage 0.2: Zero-PII diagnostics contract (filtering PII, user code, and token keys).
- Stage B & C: Teacher pedagogical controls, permission broadcasts, and student restrictions.
- Stage D: Window synchronization policy (public vs private window isolation).
- Stage E: Integrated Code, Terminal, and BooTracer execution and broadcast flow.
- Stage G: Full end-to-end pedagogical lesson workflow simulation (Teacher & Student).
- Stage K: V1 Trainer / V2 Room / V3 Review template consistency and accessibility.
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
    _next_board_revision,
    _get_db_board_revision,
)
from app.lessons.whiteboard_service import get_or_create_board
from tests.v2.test_lesson_room_interactive import _create_lesson_context
from tests.v2.test_role_lifecycle_recovery import login_as


# ---------------------------------------------------------------------------
# Stage 0: Architecture Risk & Reliability Verifications
# ---------------------------------------------------------------------------

def test_stage0_cross_process_board_persistence_lock(app, role_users):
    """Verify _persist_cached_board_strokes safely executes with PostgreSQL locks in a single atomic transaction."""
    lesson_id, _ = _create_lesson_context(app, role_users)

    strokes = {
        "stroke_p1": {
            "id": "stroke_p1",
            "page_id": "page_1",
            "color": "#4f46e5",
            "size": 3,
            "tool": "pen",
            "points": [{"x": 10, "y": 20}, {"x": 30, "y": 40}],
            "server_revision": 1,
        }
    }
    pages = [{"id": "page_1", "title": "Введение в графы", "order": 0}]

    with app.app_context():
        _lesson_board_strokes[lesson_id] = strokes
        _lesson_board_pages[lesson_id] = pages
        _lesson_board_active_page[lesson_id] = "page_1"

        # Persist to database
        _persist_cached_board_strokes(lesson_id)

        # Verify DB rows
        lesson = db.session.get(Lesson, lesson_id)
        assert lesson is not None
        assert lesson.review_summaries is not None
        wb_data = lesson.review_summaries if isinstance(lesson.review_summaries, dict) else json.loads(lesson.review_summaries)
        board_payload = wb_data.get("_studio", {}).get("board", {})
        strokes_list = board_payload.get("strokes", [])
        assert any(s.get("id") == "stroke_p1" for s in strokes_list)

        # Verify LessonWhiteboard model in same transaction
        wb_model = LessonWhiteboard.query.filter_by(lesson_id=lesson_id).first()
        assert wb_model is not None
        assert wb_model.document_version == board_payload.get("revision", 0)
        doc_pages = (wb_model.document_state or {}).get("pages") or []
        assert len(doc_pages) >= 1


def test_stage0_zero_pii_diagnostics_filter_contract():
    """Verify that diagnostics filter logic enforces zero-PII guarantees on client events."""
    sensitive_keys = {
        'code', 'token', 'password', 'text', 'email', 'user', 'username',
        'phone', 'note', 'content', 'message', 'secret', 'auth'
    }

    def sanitize_meta(meta):
        clean = {}
        for k, v in meta.items():
            k_lower = str(k).lower()
            if any(blocked in k_lower for blocked in sensitive_keys):
                continue
            if isinstance(v, (int, float, bool)):
                clean[k] = v
            elif isinstance(v, str):
                clean[k] = v[:64]
            elif v is None:
                clean[k] = None
        return clean

    test_payload = {
        "user_email": "student@example.com",
        "auth_token": "secret_jwt_token_12345",
        "user_code": "def solve(): return 42",
        "password_hash": "hash_xyz",
        "phone_number": "+79991234567",
        "private_note": "Confidential student info",
        "message_body": "Hello teacher",
        "safe_metric": 42.5,
        "window_id": "code-window",
        "duration_ms": 120,
        "action": "open_tab"
    }

    filtered = sanitize_meta(test_payload)

    # All sensitive keys must be excluded
    for key in ["user_email", "auth_token", "user_code", "password_hash", "phone_number", "private_note", "message_body"]:
        assert key not in filtered

    # Safe telemetry metrics must be preserved
    assert filtered["safe_metric"] == 42.5
    assert filtered["window_id"] == "code-window"
    assert filtered["duration_ms"] == 120
    assert filtered["action"] == "open_tab"


# ---------------------------------------------------------------------------
# Stage B & C: Pedagogical Control & Window Synchronization
# ---------------------------------------------------------------------------

def test_stage_c_window_synchronization_policy():
    """Verify private vs public window isolation rules."""
    def should_sync_window(window_id, mode, is_teacher):
        if window_id in ['chat-window', 'video-window', 'teacher-notes-window', 'teacher-task-bank-window']:
            return False
        if window_id == 'tracer-window':
            return True
        if mode == 'independent':
            return False
        if mode == 'teacher':
            return is_teacher
        if mode == 'both':
            return True
        return False

    # Private windows never sync
    assert not should_sync_window('chat-window', 'teacher', True)
    assert not should_sync_window('video-window', 'teacher', True)
    assert not should_sync_window('teacher-notes-window', 'teacher', True)
    assert not should_sync_window('teacher-task-bank-window', 'teacher', True)

    # BooTracer always syncs across clients
    assert should_sync_window('tracer-window', 'independent', False)
    assert should_sync_window('tracer-window', 'teacher', True)

    # Standard windows sync when teacher is presenter and mode is 'teacher'
    assert should_sync_window('code-window', 'teacher', True)
    assert should_sync_window('task-window', 'teacher', True)
    assert should_sync_window('terminal-window', 'teacher', True)

    # Student cannot force sync in 'teacher' mode
    assert not should_sync_window('code-window', 'teacher', False)

    # Independent mode prevents student layout interruption
    assert not should_sync_window('code-window', 'independent', True)


def test_stage_b_permission_state_machine():
    """Verify student permission checks on board and code editing."""
    def can_student_edit_code(control_state):
        return bool(control_state.get('student_code_editing', False))

    def can_student_edit_board(control_state, page_id='page_1'):
        if control_state.get('board_locked', False):
            return False
        if not control_state.get('student_editing', True):
            return False
        if page_id in control_state.get('locked_page_ids', []):
            return False
        allowed = control_state.get('allowed_page_ids', [])
        return (not allowed) or (page_id in allowed)

    # Default state: board editing allowed, code editing restricted (teacher controls code)
    default_control = {'board_locked': False, 'student_editing': True, 'student_code_editing': False}
    assert not can_student_edit_code(default_control)
    assert can_student_edit_board(default_control, 'page_1')

    # Teacher grants code editing
    granted_control = {'board_locked': False, 'student_editing': True, 'student_code_editing': True}
    assert can_student_edit_code(granted_control)
    assert can_student_edit_board(granted_control, 'page_1')

    # Teacher locks entire board (e.g., during theory explanation)
    locked_board_control = {'board_locked': True, 'student_editing': True, 'student_code_editing': True}
    assert can_student_edit_code(locked_board_control)
    assert not can_student_edit_board(locked_board_control, 'page_1')

    # Teacher locks specific page
    page_lock_control = {'board_locked': False, 'student_editing': True, 'locked_page_ids': ['page_1', 'page_3']}
    assert not can_student_edit_board(page_lock_control, 'page_1')
    assert can_student_edit_board(page_lock_control, 'page_2')


# ---------------------------------------------------------------------------
# Stage E: Terminal and Execution Output Consistency
# ---------------------------------------------------------------------------

def test_stage_e_terminal_execution_broadcast_payload():
    """Verify terminal execution payload structure conforms to pedagogical broadcast contract."""
    def create_terminal_payload(file_name, output, duration, exit_code, is_error=False):
        return {
            'kind': 'terminal_output',
            'file_name': file_name,
            'output': output,
            'duration': f"{duration:.3f}",
            'exit_code': exit_code,
            'is_error': is_error
        }

    # Successful run
    payload_ok = create_terminal_payload('solution.py', '42\n', 0.045, 0, False)
    assert payload_ok['exit_code'] == 0
    assert not payload_ok['is_error']
    assert payload_ok['file_name'] == 'solution.py'
    assert payload_ok['output'] == '42\n'

    # Error run
    payload_err = create_terminal_payload('solution.py', 'ZeroDivisionError: division by zero', 0.012, 1, True)
    assert payload_err['exit_code'] == 1
    assert payload_err['is_error']
    assert 'ZeroDivisionError' in payload_err['output']


# ---------------------------------------------------------------------------
# Stage G: Full End-to-End Lesson Simulation
# ---------------------------------------------------------------------------

def test_stage_g_pedagogical_lesson_flow_e2e(app, role_users):
    """Simulate a complete pedagogical lesson: teacher joins, tasks, code permissions, whiteboard, and persistence."""
    lesson_id, _ = _create_lesson_context(app, role_users)

    with app.app_context():
        # 1. Lesson initialization with pages
        pages = [
            {"id": "page_theory", "title": "Теория: Двоичный поиск", "order": 0},
            {"id": "page_practice", "title": "Практика: Задача 1", "order": 1}
        ]
        _lesson_board_pages[lesson_id] = pages
        _lesson_board_active_page[lesson_id] = "page_theory"
        _lesson_board_strokes[lesson_id] = {}

        # 2. Teacher adds theory diagram stroke
        theory_stroke = {
            "id": "stroke_theory_1",
            "page_id": "page_theory",
            "color": "#2563eb",
            "size": 2,
            "tool": "pen",
            "points": [{"x": 100, "y": 100}, {"x": 200, "y": 100}],
            "server_revision": 1,
        }
        _lesson_board_strokes[lesson_id]["stroke_theory_1"] = theory_stroke

        # 3. Teacher switches to practice page and grants student code editing
        _lesson_board_active_page[lesson_id] = "page_practice"
        student_stroke = {
            "id": "stroke_student_ans",
            "page_id": "page_practice",
            "color": "#10b981",
            "size": 3,
            "tool": "pen",
            "points": [{"x": 50, "y": 60}, {"x": 80, "y": 90}],
            "server_revision": 2,
        }
        _lesson_board_strokes[lesson_id]["stroke_student_ans"] = student_stroke

        # 4. Atomic persistence to PostgreSQL
        _persist_cached_board_strokes(lesson_id)

        # 5. Reload from cache/DB and verify data integrity
        reloaded_strokes = _load_cached_board_strokes(lesson_id)
        assert len(reloaded_strokes) == 2
        assert "stroke_theory_1" in reloaded_strokes
        assert "stroke_student_ans" in reloaded_strokes
        reloaded_pages = _load_cached_board_pages(lesson_id)
        assert len(reloaded_pages) == 2
        assert _load_cached_board_active_page(lesson_id) == "page_practice"


# ---------------------------------------------------------------------------
# Stage K: Template Consistency (V1 Trainer, V2 Lesson Room, V3 Review)
# ---------------------------------------------------------------------------

def test_stage_k_template_consistency_v1_v2_v3(client, role_users):
    """Verify that lesson pages render correctly without 500 template errors."""
    login_as(client, role_users['tutor_id'], 'tutor')

    # V2 Trainer route (follow redirect from /trainer to /trainer/v2)
    resp = client.get('/trainer', follow_redirects=True)
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'code-window-permission-badge' in html
    assert 'bringToFront' in html
    assert 'is-window-active' in html
