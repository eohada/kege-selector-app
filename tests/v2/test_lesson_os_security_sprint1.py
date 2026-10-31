"""Tests for BooStudy OS Sprint 1: Security, Access Control & Window Synchronization Hardening.

Covers:
- P0-04: Server-side isolation of teacher's private overlay layer (no leaks to student, full persistence & rehydration for teacher).
- P1-03: Board clear & stroke deletion authorization (students cannot clear board, cannot delete teacher strokes).
- P2-02: Strict RBAC authorization in /lesson namespace (no insecure fallbacks, outsiders blocked, students blocked from teacher UI controls).
"""

import pytest
from app import db
from app.models import User, UserProfile
from tests.v2.test_lesson_room_interactive import _create_lesson_context
from tests.v2.test_role_lifecycle_recovery import login_as


def _get_or_create_outsider(app):
    with app.app_context():
        outsider = User.query.filter_by(username="sprint1_outsider").first()
        if not outsider:
            outsider = User(username="sprint1_outsider", role="student")
            outsider.set_password("outsider123")
            db.session.add(outsider)
            db.session.flush()
            profile = UserProfile(user_id=outsider.id, first_name="Outsider", last_name="User")
            db.session.add(profile)
            db.session.commit()
        return outsider.id


def test_p0_04_teacher_layer_isolation_and_rehydration(app, role_users):
    """Teacher layer strokes/objects must never leak to student via socket, snapshot, or REST,

    while teacher retains persistence and full rehydration.
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
        conn.emit("whiteboard_join", {"lesson_id": lesson_id}, namespace="/lesson")
        return conn

    try:
        teacher_sock = connect(teacher_http)
        student_sock = connect(student_http)

        # Clear initial snapshot/presence packets from queues
        teacher_sock.get_received("/lesson")
        student_sock.get_received("/lesson")

        # 1. Teacher creates a PRIVATE note on the teacher layer
        teacher_note = {
            "id": "note_teacher_private_1",
            "page_id": "page_1",
            "type": "note",
            "layer": "teacher",
            "text": "Private teacher solution hint: answer is 42",
            "userId": role_users["tutor_id"],
        }
        teacher_sock.emit("board_stroke", {
            "lesson_id": lesson_id,
            "stroke": teacher_note,
        }, namespace="/lesson")

        # Check student socket: MUST NOT receive any board_stroke with layer == 'teacher'
        student_received = student_sock.get_received("/lesson")
        leaked_strokes = [
            item for item in student_received
            if item["name"] == "board_stroke" and (item["args"][0].get("stroke") or {}).get("layer") == "teacher"
        ]
        assert len(leaked_strokes) == 0, f"LEAK DETECTED: Student received teacher private stroke: {leaked_strokes}"

        # 2. Student connects / reconnects: board_snapshot MUST NOT contain teacher layer strokes
        reconnected_student_sock = connect(student_http)
        snap_events = [
            item for item in reconnected_student_sock.get_received("/lesson")
            if item["name"] == "board_snapshot"
        ]
        assert len(snap_events) > 0
        student_snapshot_strokes = snap_events[-1]["args"][0].get("strokes", [])
        assert not any(s.get("layer") == "teacher" for s in student_snapshot_strokes), (
            f"LEAK in student board_snapshot: {student_snapshot_strokes}"
        )

        # 3. Teacher reconnects: board_snapshot MUST contain the teacher layer stroke
        reconnected_teacher_sock = connect(teacher_http)
        teacher_snap_events = [
            item for item in reconnected_teacher_sock.get_received("/lesson")
            if item["name"] == "board_snapshot"
        ]
        assert len(teacher_snap_events) > 0
        teacher_snapshot_strokes = teacher_snap_events[-1]["args"][0].get("strokes", [])
        assert any(s.get("id") == "note_teacher_private_1" for s in teacher_snapshot_strokes), (
            "Teacher lost private stroke on rehydration!"
        )

        # 4. REST API isolation: /api/lessons/<id>/board-summary
        # Student request:
        student_resp = student_http.get(f"/api/lessons/{lesson_id}/board-summary")
        assert student_resp.status_code == 200
        student_data = student_resp.get_json()
        assert not any(s.get("layer") == "teacher" for s in student_data.get("strokes", [])), (
            "LEAK: REST board-summary returned teacher layer strokes to student!"
        )

        # Teacher request:
        teacher_resp = teacher_http.get(f"/api/lessons/{lesson_id}/board-summary")
        assert teacher_resp.status_code == 200
        teacher_data = teacher_resp.get_json()
        assert any(s.get("id") == "note_teacher_private_1" for s in teacher_data.get("strokes", [])), (
            "Teacher cannot see their own private layer strokes in REST board-summary!"
        )

        # 5. Student attempts to spoof layer: "teacher" on board_stroke
        spoof_stroke = {
            "id": "student_spoof_stroke",
            "page_id": "page_1",
            "type": "stroke",
            "layer": "teacher",
            "points": [{"x": 10, "y": 10}],
            "userId": role_users["student_user_id"],
        }
        student_sock.emit("board_stroke", {
            "lesson_id": lesson_id,
            "stroke": spoof_stroke,
        }, namespace="/lesson")

        # Verify on backend that spoof_stroke layer was coerced to 'student'
        from app.lessons.lesson_socket import _load_cached_board_strokes
        cached = _load_cached_board_strokes(lesson_id)
        assert cached.get("student_spoof_stroke", {}).get("layer") == "student", (
            "Security bypass: Student successfully wrote to teacher layer!"
        )

    finally:
        for s in sockets:
            if s.is_connected("/lesson"):
                s.disconnect("/lesson")


def test_p1_03_board_clear_and_delete_protection(app, role_users):
    """Students cannot clear the board or delete teacher strokes."""
    lesson_id, _ = _create_lesson_context(app, role_users)
    teacher_http = app.test_client()
    student_http = app.test_client()
    login_as(teacher_http, role_users["tutor_id"], "tutor")
    login_as(student_http, role_users["student_user_id"], "student")

    sockets = []

    def connect(http_client):
        conn = app.socketio.test_client(app, flask_test_client=http_client, namespace="/lesson")
        sockets.append(conn)
        conn.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
        conn.emit("whiteboard_join", {"lesson_id": lesson_id}, namespace="/lesson")
        return conn

    try:
        teacher_sock = connect(teacher_http)
        student_sock = connect(student_http)

        # Teacher creates a public stroke and a private stroke
        teacher_sock.emit("board_stroke", {
            "lesson_id": lesson_id,
            "stroke": {
                "id": "teacher_public_stroke_1",
                "page_id": "page_1",
                "type": "stroke",
                "layer": "student",
                "userId": role_users["tutor_id"],
            },
        }, namespace="/lesson")
        teacher_sock.emit("board_stroke", {
            "lesson_id": lesson_id,
            "stroke": {
                "id": "teacher_private_stroke_2",
                "page_id": "page_1",
                "type": "stroke",
                "layer": "teacher",
                "userId": role_users["tutor_id"],
            },
        }, namespace="/lesson")

        # Student creates their own stroke
        student_sock.emit("board_stroke", {
            "lesson_id": lesson_id,
            "stroke": {
                "id": "student_own_stroke_1",
                "page_id": "page_1",
                "type": "stroke",
                "layer": "student",
                "userId": role_users["student_user_id"],
            },
        }, namespace="/lesson")

        from app.lessons.lesson_socket import _load_cached_board_strokes
        cached = _load_cached_board_strokes(lesson_id)
        assert "teacher_public_stroke_1" in cached
        assert "teacher_private_stroke_2" in cached
        assert "student_own_stroke_1" in cached

        # 1. Student attempts to CLEAR the board
        student_sock.get_received("/lesson")
        student_sock.emit("board_action", {
            "lesson_id": lesson_id,
            "action": "clear",
        }, namespace="/lesson")

        err_events = [
            item for item in student_sock.get_received("/lesson")
            if item["name"] == "whiteboard_error"
        ]
        assert len(err_events) > 0, "Student clear action was not rejected with whiteboard_error!"
        assert "Очистка доски доступна только преподавателю" in err_events[0]["args"][0].get("message", "")

        # Verify board strokes are intact
        cached = _load_cached_board_strokes(lesson_id)
        assert "teacher_public_stroke_1" in cached, "Teacher stroke was wiped by student clear!"
        assert "teacher_private_stroke_2" in cached, "Teacher private stroke was wiped by student clear!"

        # 2. Student attempts to DELETE teacher's stroke
        student_sock.emit("board_action", {
            "lesson_id": lesson_id,
            "action": "delete",
            "stroke_ids": ["teacher_public_stroke_1", "teacher_private_stroke_2"],
        }, namespace="/lesson")

        cached = _load_cached_board_strokes(lesson_id)
        assert "teacher_public_stroke_1" in cached, "Unauthorized deletion: student deleted teacher public stroke!"
        assert "teacher_private_stroke_2" in cached, "Unauthorized deletion: student deleted teacher private stroke!"

        # 3. Student deletes their OWN stroke -> should succeed
        student_sock.emit("board_action", {
            "lesson_id": lesson_id,
            "action": "delete",
            "stroke_ids": ["student_own_stroke_1"],
        }, namespace="/lesson")

        cached = _load_cached_board_strokes(lesson_id)
        assert "student_own_stroke_1" not in cached, "Student could not delete their own stroke!"

        # 4. Student attempts page creation -> rejected
        student_sock.emit("board_action", {
            "lesson_id": lesson_id,
            "action": "page_create",
            "page": {"id": "page_unauthorized", "title": "Hacked"},
        }, namespace="/lesson")
        err_events = [
            item for item in student_sock.get_received("/lesson")
            if item["name"] == "whiteboard_error"
        ]
        assert any("Управление страницами доступно только преподавателю" in e["args"][0].get("message", "") for e in err_events)

        # 5. Teacher clears the board -> should succeed
        teacher_sock.emit("board_action", {
            "lesson_id": lesson_id,
            "action": "clear",
        }, namespace="/lesson")
        cached = _load_cached_board_strokes(lesson_id)
        assert len(cached) == 0, "Teacher clear action failed!"

    finally:
        for s in sockets:
            if s.is_connected("/lesson"):
                s.disconnect("/lesson")


def test_p2_02_strict_rbac_and_outsider_protection(app, role_users):
    """RBAC validation: outsiders cannot join or send events; students cannot execute teacher UI controls."""
    lesson_id, _ = _create_lesson_context(app, role_users)
    outsider_id = _get_or_create_outsider(app)

    teacher_http = app.test_client()
    student_http = app.test_client()
    outsider_http = app.test_client()

    login_as(teacher_http, role_users["tutor_id"], "tutor")
    login_as(student_http, role_users["student_user_id"], "student")
    login_as(outsider_http, outsider_id, "student")

    sockets = []

    def connect(http_client):
        conn = app.socketio.test_client(app, flask_test_client=http_client, namespace="/lesson")
        sockets.append(conn)
        return conn

    try:
        # 1. Outsider attempts to join the lesson room
        outsider_sock = connect(outsider_http)
        outsider_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
        outsider_sock.emit("whiteboard_join", {"lesson_id": lesson_id}, namespace="/lesson")

        # Outsider should receive error or not be added to room presence
        from app.lessons.lesson_socket import _lesson_presence
        presence = _lesson_presence.get(lesson_id, {})
        assert outsider_id not in presence, "Security failure: Outsider was admitted into lesson presence!"

        # 2. Student attempts teacher master control actions
        student_sock = connect(student_http)
        student_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
        student_sock.emit("whiteboard_join", {"lesson_id": lesson_id}, namespace="/lesson")
        student_sock.get_received("/lesson")

        # Student tries "freeze_student"
        student_sock.emit("lesson_room_ui", {
            "lesson_id": lesson_id,
            "kind": "freeze_student",
            "state": True,
        }, namespace="/lesson")

        err_events = [
            item for item in student_sock.get_received("/lesson")
            if item["name"] == "whiteboard_error"
        ]
        assert len(err_events) > 0, "Student freeze_student action was not rejected!"
        assert "Недостаточно прав: действие доступно только преподавателю" in err_events[0]["args"][0].get("message", "")

        # Student tries "focus_board"
        student_sock.emit("lesson_room_ui", {
            "lesson_id": lesson_id,
            "kind": "focus_board",
            "state": True,
        }, namespace="/lesson")
        err_events = [
            item for item in student_sock.get_received("/lesson")
            if item["name"] == "whiteboard_error"
        ]
        assert any("Недостаточно прав: действие доступно только преподавателю" in e["args"][0].get("message", "") for e in err_events)

        # 3. Teacher executes "focus_board" -> succeeds
        teacher_sock = connect(teacher_http)
        teacher_sock.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
        teacher_sock.emit("whiteboard_join", {"lesson_id": lesson_id}, namespace="/lesson")

        student_sock.get_received("/lesson")
        teacher_sock.emit("lesson_room_ui", {
            "lesson_id": lesson_id,
            "kind": "focus_board",
            "state": True,
        }, namespace="/lesson")

        # Student should receive lesson_room_ui from teacher
        student_received = student_sock.get_received("/lesson")
        focus_events = [
            item for item in student_received
            if item["name"] == "lesson_room_ui" and item["args"][0].get("kind") == "focus_board"
        ]
        assert len(focus_events) > 0, "Teacher focus_board was not delivered to student!"

    finally:
        for s in sockets:
            if s.is_connected("/lesson"):
                s.disconnect("/lesson")
