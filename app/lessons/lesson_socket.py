# Real-time комната урока: обновления без перезагрузки, синхронизация вкладок.
# Используется Flask-SocketIO, namespace /lesson.

from __future__ import annotations

import logging
from threading import RLock
from time import monotonic, time
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

# lesson_id -> { user_id: { 'sid': str, 'tab': str, 'role': 'teacher'|'student'|'parent', 'name': str } }
_lesson_presence: dict[int, dict[int, dict[str, Any]]] = {}
_live_strokes: dict[int, dict[str, dict[str, Any]]] = {}
_lesson_room_ui: dict[int, dict[str, dict[str, Any]]] = {}
_lesson_code_state: dict[int, dict[str, Any]] = {}
_lesson_code_cursor_emit_at: dict[str, float] = {}
_lesson_code_update_emit_at: dict[str, float] = {}
_lesson_pointer_emit_at: dict[str, float] = {}
_lesson_laser_emit_at: dict[str, float] = {}
_lesson_control_cache: dict[int, tuple[float, dict[str, Any]]] = {}
_lesson_operation_locks: dict[int, RLock] = {}
_pointer_colors = ('#4f46e5', '#0f766e', '#c2410c', '#be123c', '#7c3aed', '#0369a1')


def _room(lesson_id: int) -> str:
    return f"lesson:{lesson_id}"


def _room_control(lesson_id: int) -> dict[str, Any]:
    cached = _lesson_control_cache.get(lesson_id)
    now = monotonic()
    if cached and now - cached[0] < 0.35:
        return cached[1]
    try:
        from app.lessons.whiteboard_service import get_or_create_board, normalize_document
        board = get_or_create_board(lesson_id)
        control = normalize_document(board.document_state).get("presentation", {}).get("control", {})
        _lesson_control_cache[lesson_id] = (now, control)
        return control
    except Exception:
        return {}


def _teacher_control_enabled(control: dict[str, Any], key: str) -> bool:
    mode = control.get("mode") or "hybrid"
    if mode == "guided":
        return True
    if mode == "free":
        return False
    return bool(control.get(key))


def register_lesson_socket(socketio) -> None:
    from flask import request
    from flask_login import current_user
    from app.utils.relationship_scope import get_confirmed_student_user_ids_for_parent

    def _sync_socket_user() -> None:
        from flask import g, session
        sess_uid = session.get('_user_id')
        cached = getattr(g, '_login_user', None)
        if cached is not None:
            if sess_uid is None or str(getattr(cached, 'id', None)) != str(sess_uid):
                g.pop('_login_user', None)

    @socketio.on("connect", namespace="/lesson")
    def _on_connect():
        _sync_socket_user()
        if not current_user.is_authenticated:
            return False
        return True

    @socketio.on("disconnect", namespace="/lesson")
    def _on_disconnect():
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        uid = current_user.id
        for lid, users in list(_lesson_presence.items()):
            identity = users.get(uid, {})
            is_current_connection = bool(identity and identity.get("sid") == request.sid)
            cursor_prefix = f"{lid}:{uid}:"
            for cursor_key in [key for key in _lesson_code_cursor_emit_at if key.startswith(cursor_prefix)]:
                _lesson_code_cursor_emit_at.pop(cursor_key, None)
            for code_key in [key for key in _lesson_code_update_emit_at if key.startswith(cursor_prefix)]:
                _lesson_code_update_emit_at.pop(code_key, None)
            pointer_prefix = f"{lid}:{uid}:"
            for pointer_key in [key for key in _lesson_pointer_emit_at if key.startswith(pointer_prefix)]:
                _lesson_pointer_emit_at.pop(pointer_key, None)
            for laser_key in [key for key in _lesson_laser_emit_at if key.startswith(pointer_prefix)]:
                _lesson_laser_emit_at.pop(laser_key, None)
            active_strokes = _live_strokes.get(lid, {})
            for stroke_key, stroke in list(active_strokes.items()):
                if not stroke_key.startswith(f"{uid}:") or (stroke.get("sid") and stroke.get("sid") != request.sid):
                    continue
                stroke_id = stroke_key.split(":", 1)[1]
                socketio.emit(
                    "whiteboard_live_stroke",
                    {"lesson_id": lid, "stroke_id": stroke_id, "phase": "cancel", "user_id": uid},
                    room=_room(lid),
                    namespace="/lesson",
                    include_self=False,
                )
                active_strokes.pop(stroke_key, None)
            if not active_strokes:
                _live_strokes.pop(lid, None)
            if is_current_connection and uid in users:
                del users[uid]
                if not users:
                    del _lesson_presence[lid]
                _lesson_control_cache.pop(lid, None)
                socketio.emit(
                    "lesson_presence",
                    {"lesson_id": lid, "presence": list(users.values())},
                    room=_room(lid),
                    namespace="/lesson",
                )
            if not users:
                _lesson_room_ui.pop(lid, None)
                _lesson_code_state.pop(lid, None)

    @socketio.on("join_lesson", namespace="/lesson")
    def _on_join_lesson(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        lesson_id = data.get("lesson_id")
        if lesson_id is None:
            return
        try:
            lesson_id = int(lesson_id)
        except Exception:
            return
        from app.models import Lesson
        lesson = Lesson.query.get(lesson_id)
        if not lesson:
            return
        # Проверка доступа: преподаватель или ученик этого урока / родитель
        from app.lessons.routes import get_user_scope, _get_current_lesson_student
        from app.models import Student
        scope = get_user_scope(current_user)
        if current_user.is_student():
            if not _get_current_lesson_student(lesson):
                return
        elif current_user.is_parent():
            child_ids = get_confirmed_student_user_ids_for_parent(current_user.id)
            if lesson.student_id not in child_ids:
                return
        else:
            if not scope.get("can_see_all"):
                from app.lessons.routes import _resolve_accessible_student_ids
                allowed = _resolve_accessible_student_ids(scope)
                if lesson.student_id not in allowed:
                    return
        room = _room(lesson_id)
        from flask_socketio import join_room, leave_room
        # One browser connection represents one active lesson room. Leaving an old
        # room prevents presence and transient events leaking after navigation.
        for previous_lesson_id, users in list(_lesson_presence.items()):
            if previous_lesson_id == lesson_id or current_user.id not in users:
                continue
            leave_room(_room(previous_lesson_id))
            previous_strokes = _live_strokes.get(previous_lesson_id, {})
            for stroke_key in [key for key in previous_strokes if key.startswith(f"{current_user.id}:")]:
                previous_strokes.pop(stroke_key, None)
            if not previous_strokes:
                _live_strokes.pop(previous_lesson_id, None)
            del users[current_user.id]
            if not users:
                del _lesson_presence[previous_lesson_id]
                _lesson_control_cache.pop(previous_lesson_id, None)
            socketio.emit(
                "lesson_presence",
                {"lesson_id": previous_lesson_id, "presence": list(users.values())},
                room=_room(previous_lesson_id),
                namespace="/lesson",
            )
        join_room(room)
        if current_user.is_student() and getattr(lesson, 'student', None):
            if not getattr(lesson, 'student_late', False):
                try:
                    from app.utils.achievement_service import grant_achievement
                    grant_achievement(lesson.student, 'lesson_on_time', commit=True)
                except Exception:
                    pass
        if lesson_id not in _lesson_presence:
            _lesson_presence[lesson_id] = {}
        role = "teacher"
        if current_user.is_student():
            role = "student"
        elif current_user.is_parent():
            role = "parent"
        from app.models import UserProfile
        profile = UserProfile.query.filter_by(user_id=current_user.id).first()
        name = f"{profile.first_name or ''} {profile.last_name or ''}".strip() if profile else ""
        if not name:
            name = current_user.username or current_user.email or "Участник"
        _lesson_presence[lesson_id][current_user.id] = {
            "sid": request.sid,
            "tab": "theory",
            "role": role,
            "name": name,
            "color": _pointer_colors[int(current_user.id) % len(_pointer_colors)],
            "client_id": None,
            "page_id": None,
            "follow": False,
        }
        # Отправить текущему клиенту список присутствующих и их вкладки
        presence_list = [
            {"user_id": uid, "tab": info["tab"], "role": info["role"], "name": info["name"]}
            for uid, info in _lesson_presence[lesson_id].items()
        ]
        socketio.emit("lesson_presence", {"lesson_id": lesson_id, "presence": presence_list}, room=request.sid, namespace="/lesson")
        # Остальным в комнате — обновлённый список (включая нового участника)
        socketio.emit(
            "lesson_presence",
            {"lesson_id": lesson_id, "presence": presence_list},
            room=room,
            namespace="/lesson",
            include_self=False,
        )

    @socketio.on("tab_changed", namespace="/lesson")
    def _on_tab_changed(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        lesson_id = data.get("lesson_id")
        tab = (data.get("tab") or "theory").strip() or "theory"
        if lesson_id is None:
            return
        try:
            lesson_id = int(lesson_id)
        except (TypeError, ValueError):
            return
        if lesson_id not in _lesson_presence:
            _lesson_presence[lesson_id] = {}
        role = "teacher"
        if current_user.is_student():
            role = "student"
        elif current_user.is_parent():
            role = "parent"
        from app.models import UserProfile
        profile = UserProfile.query.filter_by(user_id=current_user.id).first()
        name = f"{profile.first_name or ''} {profile.last_name or ''}".strip() if profile else ""
        if not name:
            name = current_user.username or current_user.email or "Участник"
        previous = _lesson_presence.get(lesson_id, {}).get(current_user.id, {})
        _lesson_presence[lesson_id][current_user.id] = {
            **previous,
            "tab": tab,
            "role": role,
            "name": name,
            "color": previous.get("color") or _pointer_colors[int(current_user.id) % len(_pointer_colors)],
        }
        presence_list = [
            {"user_id": uid, "tab": info["tab"], "role": info["role"], "name": info["name"]}
            for uid, info in _lesson_presence[lesson_id].items()
        ]
        socketio.emit(
            "lesson_presence",
            {"lesson_id": lesson_id, "presence": presence_list},
            room=_room(lesson_id),
            namespace="/lesson",
        )

    @socketio.on("board_stroke", namespace="/lesson")
    def _on_board_stroke(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        lesson_id = data.get("lesson_id")
        stroke = data.get("stroke")
        if not lesson_id or not stroke:
            return
        try:
            lesson_id = int(lesson_id)
        except (TypeError, ValueError):
            return
        socketio.emit(
            "board_stroke",
            {
                "lesson_id": lesson_id,
                "stroke": stroke,
                "user_id": current_user.id,
                "client_stroke_id": data.get("client_stroke_id")
            },
            room=_room(lesson_id),
            namespace="/lesson",
            include_self=False,
        )

    @socketio.on("board_action", namespace="/lesson")
    def _on_board_action(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        lesson_id = data.get("lesson_id")
        action = data.get("action")
        if not lesson_id or not action:
            return
        try:
            lesson_id = int(lesson_id)
        except (TypeError, ValueError):
            return
        socketio.emit(
            "board_action",
            {
                "lesson_id": lesson_id,
                "action": action,
                "strokes": data.get("strokes")
            },
            room=_room(lesson_id),
            namespace="/lesson",
            include_self=False,
        )

    @socketio.on("whiteboard_join", namespace="/lesson")
    def _on_whiteboard_join(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        try:
            lesson_id = int((data or {}).get("lesson_id"))
            from app.lessons.routes import _whiteboard_access
            _whiteboard_access(lesson_id)
            from app.lessons.whiteboard_service import board_payload, get_or_create_board
            board = get_or_create_board(lesson_id)
            identity = _lesson_presence.setdefault(lesson_id, {}).setdefault(current_user.id, {})
            identity.update({
                "sid": request.sid,
                "client_id": (data or {}).get("client_id"),
                "page_id": (data or {}).get("page_id"),
                "follow": bool((data or {}).get("follow")),
                "color": identity.get("color") or _pointer_colors[int(current_user.id) % len(_pointer_colors)],
            })
            socketio.emit(
                "whiteboard_snapshot",
                {"lesson_id": lesson_id, **board_payload(board)},
                room=request.sid,
                namespace="/lesson",
            )
            socketio.emit(
                "lesson_presence",
                {"lesson_id": lesson_id, "presence": list(_lesson_presence.get(lesson_id, {}).values())},
                room=_room(lesson_id),
                namespace="/lesson",
            )
            room_ui = _lesson_room_ui.get(lesson_id) or {}
            for ui_payload in room_ui.values():
                socketio.emit("lesson_room_ui_state", ui_payload, room=request.sid, namespace="/lesson")
            code_state = _lesson_code_state.get(lesson_id)
            if code_state:
                socketio.emit("lesson_code_snapshot", {"lesson_id": lesson_id, **code_state}, room=request.sid, namespace="/lesson")
        except Exception as error:
            logger.warning("whiteboard_join failed: %s", error)

    @socketio.on("lesson_room_ui", namespace="/lesson")
    def _on_lesson_room_ui(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        try:
            lesson_id = int((data or {}).get("lesson_id"))
            _lesson, role = __import__("app.lessons.routes", fromlist=["_whiteboard_access"])._whiteboard_access(lesson_id)
            if role != "teacher":
                socketio.emit("whiteboard_error", {"message": "Только преподаватель может управлять интерфейсом комнаты"}, room=request.sid, namespace="/lesson")
                return
            kind = str((data or {}).get("kind") or "")
            if kind not in {"mode", "window", "run"}:
                return
            control = _room_control(lesson_id)
            if kind == "window" and not _teacher_control_enabled(control, "teacher_controls_windows"):
                return
            if kind == "mode" and not _teacher_control_enabled(control, "teacher_controls_mode"):
                return
            if kind == "run" and not control.get("auto_open_terminal_on_run"):
                return
            payload = {"lesson_id": lesson_id, "kind": kind, "updated_at": int(time() * 1000)}
            if kind == "mode":
                mode = str((data or {}).get("mode") or "code")
                if mode not in {"code", "board"}:
                    return
                payload["mode"] = mode
            elif kind == "window":
                window_id = str((data or {}).get("window_id") or "")[:64]
                action = str((data or {}).get("action") or "")
                if window_id not in {"task-window", "terminal-window", "lesson-info-window", "teacher-notes-window", "notes-window", "theory-window", "reference-window"} or action not in {"open", "minimize"}:
                    return
                payload.update({"window_id": window_id, "action": action})
            else:
                code = str((data or {}).get("code") or "")[:100000]
                payload.update({"file_name": str((data or {}).get("file_name") or "main.py")[:120], "code": code})
            # A run command is transient: replaying it to a late joiner would
            # unexpectedly execute the teacher's old code again.
            if kind != "run":
                room_state = _lesson_room_ui.setdefault(lesson_id, {})
                state_key = "mode" if kind == "mode" else f"window:{payload['window_id']}"
                room_state[state_key] = payload
            socketio.emit("lesson_room_ui", payload, room=_room(lesson_id), namespace="/lesson", include_self=False)
        except Exception as error:
            logger.warning("lesson_room_ui failed: %s", error)

    @socketio.on("lesson_code_join", namespace="/lesson")
    def _on_lesson_code_join(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        try:
            lesson_id = int((data or {}).get("lesson_id"))
            _lesson, role = __import__("app.lessons.routes", fromlist=["_whiteboard_access"])._whiteboard_access(lesson_id)
            incoming_code = str((data or {}).get("code") or "")[:100000]
            incoming_file = str((data or {}).get("file_name") or "main.py")[:120]
            current = _lesson_code_state.get(lesson_id)
            if role == "parent":
                if current:
                    socketio.emit("lesson_code_snapshot", {"lesson_id": lesson_id, **current}, room=request.sid, namespace="/lesson")
                return
            if current is None and role == "teacher" and incoming_code:
                current = {"file_name": incoming_file, "code": incoming_code, "version": int((current or {}).get("version") or 0) + 1, "updated_at": int(time() * 1000)}
                _lesson_code_state[lesson_id] = current
            if current:
                socketio.emit("lesson_code_snapshot", {"lesson_id": lesson_id, **current}, room=request.sid, namespace="/lesson")
        except Exception as error:
            logger.warning("lesson_code_join failed: %s", error)

    @socketio.on("lesson_code_update", namespace="/lesson")
    def _on_lesson_code_update(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        try:
            lesson_id = int((data or {}).get("lesson_id"))
            _lesson, role = __import__("app.lessons.routes", fromlist=["_whiteboard_access"])._whiteboard_access(lesson_id)
            control = _room_control(lesson_id)
            if role == "parent" or not control.get("code_sync") or (role != "teacher" and not control.get("student_code_editing")):
                return
            throttle_key = f"{lesson_id}:{current_user.id}:{request.sid}"
            now = monotonic()
            if now - _lesson_code_update_emit_at.get(throttle_key, 0.0) < 0.05:
                return
            _lesson_code_update_emit_at[throttle_key] = now
            code = str((data or {}).get("code") or "")[:100000]
            state = {"file_name": str((data or {}).get("file_name") or "main.py")[:120], "code": code, "version": int((_lesson_code_state.get(lesson_id) or {}).get("version") or 0) + 1, "updated_at": int(time() * 1000)}
            _lesson_code_state[lesson_id] = state
            socketio.emit("lesson_code_update", {"lesson_id": lesson_id, "user_id": current_user.id, **state}, room=_room(lesson_id), namespace="/lesson", include_self=False)
        except Exception as error:
            logger.warning("lesson_code_update failed: %s", error)

    @socketio.on("lesson_code_cursor", namespace="/lesson")
    def _on_lesson_code_cursor(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        try:
            lesson_id = int((data or {}).get("lesson_id"))
            _whiteboard_access = __import__("app.lessons.routes", fromlist=["_whiteboard_access"])._whiteboard_access
            throttle_key = f"{lesson_id}:{current_user.id}:{request.sid}"
            now = monotonic()
            if now - _lesson_code_cursor_emit_at.get(throttle_key, 0.0) < 0.032:
                return
            _lesson_code_cursor_emit_at[throttle_key] = now
            _whiteboard_access(lesson_id)
            control = _room_control(lesson_id)
            if not control.get("cursor_sync"):
                return
            identity = _lesson_presence.get(lesson_id, {}).get(current_user.id, {})
            socketio.emit("lesson_code_cursor", {"lesson_id": lesson_id, "user_id": current_user.id, "name": identity.get("name") or "Участник", "color": identity.get("color") or _pointer_colors[int(current_user.id) % len(_pointer_colors)], "file_name": str((data or {}).get("file_name") or "main.py")[:120], "cursor": {"start": max(0, int((data or {}).get("start") or 0)), "end": max(0, int((data or {}).get("end") or 0))}}, room=_room(lesson_id), namespace="/lesson", include_self=False)
        except Exception:
            return

    @socketio.on("whiteboard_operation", namespace="/lesson")
    def _on_whiteboard_operation(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        try:
            lesson_id = int((data or {}).get("lesson_id"))
            from app.lessons.routes import _whiteboard_access
            _lesson, role = _whiteboard_access(lesson_id)
            if role == "parent":
                socketio.emit("whiteboard_error", {"message": "Недостаточно прав для изменения доски"}, room=request.sid, namespace="/lesson")
                return
            from app.lessons.whiteboard_service import (
                WhiteboardConflict,
                WhiteboardOperationError,
                get_or_create_board,
                persist_operations,
            )
            board = get_or_create_board(lesson_id)
            operation = dict((data or {}).get("operation") or {})
            operation.setdefault("operation_id", uuid4().hex)
            if role != "teacher" and operation.get("type") in {"object.lock", "presentation.update"}:
                socketio.emit("whiteboard_error", {"message": "Эта операция доступна только преподавателю"}, room=request.sid, namespace="/lesson")
                return
            operation_lock = _lesson_operation_locks.setdefault(lesson_id, RLock())
            with operation_lock:
                result, accepted = persist_operations(
                    board,
                    [operation],
                    current_user.id,
                    (data or {}).get("client_id"),
                    (data or {}).get("base_version"),
                    role,
                )
            socketio.emit(
                "whiteboard_ack",
                {"lesson_id": lesson_id, "operation_id": operation["operation_id"], "version": result["version"]},
                room=request.sid,
                namespace="/lesson",
            )
            socketio.emit(
                "whiteboard_operations",
                {
                    "lesson_id": lesson_id,
                    "client_id": (data or {}).get("client_id"),
                    "version": result["version"],
                    "operations": [operation] if accepted else [],
                },
                room=f"lesson:{lesson_id}",
                namespace="/lesson",
                include_self=False,
            )
            if operation.get("type") in {"control.update", "presentation.update"}:
                if operation.get("type") == "control.update":
                    _lesson_control_cache[lesson_id] = (
                        monotonic(),
                        result["document"].get("presentation", {}).get("control", {}),
                    )
                socketio.emit(
                    "whiteboard_control",
                    {
                        "lesson_id": lesson_id,
                        "presentation": result["document"].get("presentation", {}),
                    },
                    room=f"lesson:{lesson_id}",
                    namespace="/lesson",
                    include_self=False,
                )
        except WhiteboardConflict as conflict:
            socketio.emit(
                "whiteboard_conflict",
                {"lesson_id": lesson_id, "version": conflict.version, "document": conflict.document},
                room=request.sid,
                namespace="/lesson",
            )
        except Exception as error:
            logger.warning("whiteboard_operation failed: %s", error)
            socketio.emit("whiteboard_error", {"message": str(error), "operation_id": operation.get("operation_id")}, room=request.sid, namespace="/lesson")

    @socketio.on("whiteboard_pointer", namespace="/lesson")
    def _on_whiteboard_pointer(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        try:
            lesson_id = int((data or {}).get("lesson_id"))
            throttle_key = f"{lesson_id}:{current_user.id}:{request.sid}"
            now = monotonic()
            if now - _lesson_pointer_emit_at.get(throttle_key, 0.0) < 0.016:
                return
            _lesson_pointer_emit_at[throttle_key] = now
            identity = _lesson_presence.get(lesson_id, {}).get(current_user.id, {})
            if not identity:
                from app.lessons.routes import _whiteboard_access
                _whiteboard_access(lesson_id)
            if _room_control(lesson_id).get("cursor_sync") is False:
                return
        except Exception:
            return
        identity = _lesson_presence.get(lesson_id, {}).get(current_user.id, {})
        socketio.emit(
            "whiteboard_pointer",
            {
                "lesson_id": lesson_id,
                "user_id": current_user.id,
                "name": identity.get("name") or getattr(current_user, "username", None) or "Участник",
                "color": identity.get("color") or _pointer_colors[int(current_user.id) % len(_pointer_colors)],
                "page_id": (data or {}).get("page_id"),
                "pointer": (data or {}).get("pointer") or {},
            },
            room=f"lesson:{lesson_id}",
            namespace="/lesson",
            include_self=False,
        )

    @socketio.on("whiteboard_presence_update", namespace="/lesson")
    def _on_whiteboard_presence_update(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        try:
            lesson_id = int((data or {}).get("lesson_id"))
            _whiteboard_access = __import__("app.lessons.routes", fromlist=["_whiteboard_access"])._whiteboard_access
            _whiteboard_access(lesson_id)
        except Exception:
            return
        identity = _lesson_presence.setdefault(lesson_id, {}).setdefault(current_user.id, {})
        identity.update({
            "page_id": (data or {}).get("page_id"),
            "follow": bool((data or {}).get("follow")),
        })
        socketio.emit(
            "lesson_presence",
            {"lesson_id": lesson_id, "presence": list(_lesson_presence[lesson_id].values())},
            room=_room(lesson_id),
            namespace="/lesson",
        )

    @socketio.on("whiteboard_live_stroke", namespace="/lesson")
    def _on_whiteboard_live_stroke(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        from app.lessons.routes import _whiteboard_access
        from app.lessons.whiteboard_service import WhiteboardOperationError, get_or_create_board, normalize_document, validate_operation_permissions
        try:
            payload = data or {}
            lesson_id = int(payload.get("lesson_id"))
            phase = str(payload.get("phase") or "")
            if phase not in {"start", "move", "end", "cancel"}:
                raise WhiteboardOperationError("Некорректная фаза live-штриха")
            stroke_id = str(payload.get("stroke_id") or "")[:96]
            page_id = str(payload.get("page_id") or "")[:96]
            if not stroke_id or not page_id:
                raise WhiteboardOperationError("Live-штрих не содержит идентификатор")
            key = f"{current_user.id}:{stroke_id}"
            lesson_strokes = _live_strokes.setdefault(lesson_id, {})
            existing = lesson_strokes.get(key)
            fast_path = phase == "move" and existing is not None
            if not fast_path:
                _lesson, role = _whiteboard_access(lesson_id)
                if role == "parent":
                    raise WhiteboardOperationError("Родитель не может рисовать на доске")
                control = _room_control(lesson_id)
                if control.get("live_strokes") is False:
                    return
            else:
                role = existing.get("role", "student")
                if _room_control(lesson_id).get("live_strokes") is False:
                    return
            points = payload.get("points") if isinstance(payload.get("points"), list) else []
            if len(points) > 32:
                raise WhiteboardOperationError("Слишком большой пакет точек")
            safe_points = []
            for point in points:
                if not isinstance(point, dict):
                    continue
                x = float(point.get("x"))
                y = float(point.get("y"))
                if abs(x) > 100000 or abs(y) > 100000:
                    raise WhiteboardOperationError("Координаты live-штриха выходят за допустимый диапазон")
                safe_points.append({"x": x, "y": y})
            if fast_path:
                style = existing["style"]
                page_id = existing["page_id"]
            else:
                style_payload = payload.get("style") if isinstance(payload.get("style"), dict) else {}
                style = {
                    "color": str(style_payload.get("color") or "#4f46e5")[:16],
                    "size": min(48, max(1, float(style_payload.get("size") or 4))),
                    "opacity": min(1, max(.1, float(style_payload.get("opacity") if style_payload.get("opacity") is not None else 1))),
                    "eraser": bool(style_payload.get("eraser")),
                }
                board = get_or_create_board(lesson_id)
                validate_operation_permissions(
                    normalize_document(board.document_state),
                    {"type": "object.create", "page_id": page_id, "object": {"type": "stroke", "data": {"frame_id": payload.get("frame_id")}}},
                    role,
                )
            sequence = int(payload.get("seq") or 0)
            if existing and sequence <= existing["seq"]:
                return
            if phase == "start":
                existing = {"user_id": current_user.id, "sid": request.sid, "role": role, "seq": sequence, "points": 0, "style": style, "page_id": page_id, "frame_id": payload.get("frame_id")}
                lesson_strokes[key] = existing
            elif not existing:
                return
            else:
                existing["seq"] = sequence
            existing["points"] += len(safe_points)
            if existing["points"] > 4096:
                lesson_strokes.pop(key, None)
                raise WhiteboardOperationError("Live-штрих слишком длинный")
            profile = _lesson_presence.get(lesson_id, {}).get(current_user.id, {})
            outgoing = {
                "lesson_id": lesson_id,
                "stroke_id": stroke_id,
                "page_id": page_id,
                "frame_id": payload.get("frame_id"),
                "phase": phase,
                "seq": sequence,
                "points": safe_points,
                "style": style,
                "user_id": current_user.id,
                "name": profile.get("name") or getattr(current_user, "username", None) or "Участник",
                "color": profile.get("color") or _pointer_colors[int(current_user.id) % len(_pointer_colors)],
            }
            socketio.emit("whiteboard_live_stroke", outgoing, room=_room(lesson_id), namespace="/lesson", include_self=False)
            if phase in {"end", "cancel"}:
                lesson_strokes.pop(key, None)
        except Exception as error:
            socketio.emit("whiteboard_error", {"message": str(error)}, room=request.sid, namespace="/lesson")

    @socketio.on("whiteboard_live_laser", namespace="/lesson")
    def _on_whiteboard_live_laser(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        try:
            payload = data or {}
            lesson_id = int(payload.get("lesson_id"))
            throttle_key = f"{lesson_id}:{current_user.id}:{request.sid}"
            now = monotonic()
            if now - _lesson_laser_emit_at.get(throttle_key, 0.0) < 0.016:
                return
            _lesson_laser_emit_at[throttle_key] = now
            identity = _lesson_presence.get(lesson_id, {}).get(current_user.id, {})
            if identity:
                role = identity.get("role")
            else:
                _lesson, role = __import__("app.lessons.routes", fromlist=["_whiteboard_access"])._whiteboard_access(lesson_id)
            if role != "teacher":
                socketio.emit("whiteboard_error", {"message": "Лазер доступен только преподавателю"}, room=request.sid, namespace="/lesson")
                return
            if _room_control(lesson_id).get("cursor_sync") is False:
                return
            pointer = payload.get("pointer") if isinstance(payload.get("pointer"), dict) else {}
            point = {"x": float(pointer.get("x")), "y": float(pointer.get("y"))}
            socketio.emit("whiteboard_live_laser", {"lesson_id": lesson_id, "user_id": current_user.id, "page_id": payload.get("page_id"), "pointer": point, "visible": payload.get("visible", True)}, room=_room(lesson_id), namespace="/lesson", include_self=False)
        except Exception as error:
            socketio.emit("whiteboard_error", {"message": str(error)}, room=request.sid, namespace="/lesson")

    @socketio.on("whiteboard_live_camera", namespace="/lesson")
    def _on_whiteboard_live_camera(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        try:
            payload = data or {}
            lesson_id = int(payload.get("lesson_id"))
            _lesson, role = __import__("app.lessons.routes", fromlist=["_whiteboard_access"])._whiteboard_access(lesson_id)
            if role != "teacher":
                return
            camera = payload.get("camera") if isinstance(payload.get("camera"), dict) else {}
            outgoing = {
                "lesson_id": lesson_id,
                "page_id": str(payload.get("page_id") or "")[:96],
                "frame_id": payload.get("frame_id"),
                "seq": int(payload.get("seq") or 0),
                "camera": {
                    "pan_x": max(-100000, min(100000, float(camera.get("pan_x") or 0))),
                    "pan_y": max(-100000, min(100000, float(camera.get("pan_y") or 0))),
                    "scale": max(.35, min(2.5, float(camera.get("scale") or 1))),
                },
            }
            socketio.emit("whiteboard_live_camera", outgoing, room=_room(lesson_id), namespace="/lesson", include_self=False)
        except Exception as error:
            logger.warning("whiteboard_live_camera failed: %s", error)

    @socketio.on("whiteboard_reaction", namespace="/lesson")
    def _on_whiteboard_reaction(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        try:
            lesson_id = int((data or {}).get("lesson_id"))
            from app.lessons.routes import _whiteboard_access
            _whiteboard_access(lesson_id)
        except Exception:
            return
        reaction = (data or {}).get("reaction") or "Поддерживаю"
        if current_user.is_student():
            try:
                from core.db_models import Student
                from app.utils.achievement_service import grant_achievement
                stu = Student.query.filter_by(user_id=current_user.id).first()
                if stu:
                    grant_achievement(stu, 'lesson_chat_active', commit=True)
            except Exception:
                pass
        identity = _lesson_presence.get(lesson_id, {}).get(current_user.id, {})
        socketio.emit(
            "whiteboard_reaction",
            {
                "lesson_id": lesson_id,
                "user_id": current_user.id,
                "name": identity.get("name") or getattr(current_user, "username", None) or "Участник",
                "reaction": str(reaction)[:32],
            },
            room=f"lesson:{lesson_id}",
            namespace="/lesson",
            include_self=False,
        )


def emit_lesson_tasks_updated(lesson_id: int, assignment_type: str, task: dict | None = None) -> None:
    try:
        from flask import current_app
        sio = getattr(current_app, "socketio", None)
        if sio:
            payload = {
                "lesson_id": lesson_id,
                "assignment_type": (assignment_type or "homework"),
            }
            if task:
                payload["task"] = task
            if task and _lesson_presence.get(lesson_id):
                # The teacher receives the answer, while students and parents
                # only receive it after the teacher explicitly reveals it.
                for participant in _lesson_presence[lesson_id].values():
                    sid = participant.get("sid")
                    if not sid:
                        continue
                    participant_payload = dict(payload)
                    participant_task = dict(task)
                    if participant.get("role") != "teacher" and not participant_task.get("answer_visible_to_student", False):
                        participant_task["answer"] = ""
                    participant_payload["task"] = participant_task
                    sio.emit("lesson_tasks_updated", participant_payload, room=sid, namespace="/lesson")
            else:
                sio.emit(
                    "lesson_tasks_updated",
                    payload,
                    room=_room(lesson_id),
                    namespace="/lesson",
                )
    except Exception as e:
        logger.warning("emit_lesson_tasks_updated failed: %s", e)


def emit_lesson_finished(lesson_id: int, payload: dict = None) -> None:
    """Notify student and room participants immediately when teacher completes lesson."""
    try:
        from flask import current_app
        sio = getattr(current_app, "socketio", None)
        if sio:
            sio.emit(
                "lesson_finished",
                payload or {"lesson_id": lesson_id},
                room=_room(lesson_id),
                namespace="/lesson",
            )
    except Exception as e:
        logger.warning("emit_lesson_finished failed: %s", e)


def emit_lesson_message_new(lesson_id: int, payload: dict) -> None:
    try:
        from flask import current_app
        sio = getattr(current_app, "socketio", None)
        if sio:
            sio.emit(
                "lesson_message_new",
                {"lesson_id": lesson_id, "message": payload},
                room=_room(lesson_id),
                namespace="/lesson",
            )
    except Exception as e:
        logger.warning("emit_lesson_message_new failed: %s", e)


def emit_lesson_studio_updated(lesson_id: int, state: dict, status: str | None = None) -> None:
    """Synchronize the teacher's lesson controls with the student's studio."""
    try:
        from flask import current_app
        sio = getattr(current_app, "socketio", None)
        if sio:
            sio.emit(
                "lesson_studio_updated",
                {"lesson_id": lesson_id, "state": state, "status": status},
                room=_room(lesson_id),
                namespace="/lesson",
            )
    except Exception as e:
        logger.warning("emit_lesson_studio_updated failed: %s", e)


def _emit_lesson_role_event(lesson_id: int, event: str, payload: dict, roles: set[str], *, user_id: int | None = None) -> None:
    """Send private lesson-room data only to the intended participant roles."""
    try:
        from flask import current_app
        sio = getattr(current_app, "socketio", None)
        if not sio:
            return
        for participant_id, info in _lesson_presence.get(int(lesson_id), {}).items():
            if info.get("role") not in roles and participant_id != user_id:
                continue
            sid = info.get("sid")
            if sid:
                sio.emit(event, payload, room=sid, namespace="/lesson")
    except Exception as exc:
        logger.warning("%s failed: %s", event, exc)


def emit_lesson_student_notes_updated(lesson_id: int, notes: str, author_id: int | None = None) -> None:
    _emit_lesson_role_event(
        lesson_id,
        "lesson_student_notes_updated",
        {"lesson_id": lesson_id, "notes": notes or "", "author_id": author_id},
        {"teacher", "student"},
        user_id=author_id,
    )


def emit_lesson_private_note_updated(lesson_id: int, note: str) -> None:
    _emit_lesson_role_event(
        lesson_id,
        "lesson_private_note_updated",
        {"lesson_id": lesson_id, "note": note or ""},
        {"teacher"},
    )


def emit_lesson_studio_pointer(lesson_id: int, pointer: dict) -> None:
    """Send a transient board/page pointer without writing high-frequency events to PostgreSQL."""
    try:
        from flask import current_app
        sio = getattr(current_app, "socketio", None)
        if sio:
            sio.emit(
                "lesson_studio_pointer",
                {"lesson_id": lesson_id, "pointer": pointer},
                room=_room(lesson_id),
                namespace="/lesson",
            )
    except Exception as exc:
        logger.warning("emit_lesson_studio_pointer failed: %s", exc)
