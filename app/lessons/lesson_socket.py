# Real-time комната урока: обновления без перезагрузки, синхронизация вкладок.
# Используется Flask-SocketIO, namespace /lesson.

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# lesson_id -> { user_id: { 'tab': str, 'role': 'teacher'|'student'|'parent', 'name': str } }
_lesson_presence: dict[int, dict[int, dict[str, Any]]] = {}


def _room(lesson_id: int) -> str:
    return f"lesson:{lesson_id}"


def register_lesson_socket(socketio) -> None:
    from flask import request
    from flask_login import current_user
    from app.utils.relationship_scope import get_confirmed_student_user_ids_for_parent

    @socketio.on("connect", namespace="/lesson")
    def _on_connect():
        if not current_user.is_authenticated:
            return False
        return True

    @socketio.on("disconnect", namespace="/lesson")
    def _on_disconnect():
        if not current_user.is_authenticated:
            return
        uid = current_user.id
        for lid, users in list(_lesson_presence.items()):
            if uid in users:
                del users[uid]
                if not users:
                    del _lesson_presence[lid]
                socketio.emit(
                    "lesson_presence",
                    {"lesson_id": lid, "presence": list(users.values())},
                    room=_room(lid),
                    namespace="/lesson",
                )

    @socketio.on("join_lesson", namespace="/lesson")
    def _on_join_lesson(data):
        if not current_user.is_authenticated:
            return
        lesson_id = data.get("lesson_id")
        if lesson_id is None:
            return
        try:
            lesson_id = int(lesson_id)
        except (TypeError, ValueError):
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
            del users[current_user.id]
            if not users:
                del _lesson_presence[previous_lesson_id]
            socketio.emit(
                "lesson_presence",
                {"lesson_id": previous_lesson_id, "presence": list(users.values())},
                room=_room(previous_lesson_id),
                namespace="/lesson",
            )
        join_room(room)
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
        _lesson_presence[lesson_id][current_user.id] = {"tab": "theory", "role": role, "name": name}
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
        _lesson_presence[lesson_id][current_user.id] = {"tab": tab, "role": role, "name": name}
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


def emit_lesson_tasks_updated(lesson_id: int, assignment_type: str) -> None:
    try:
        from flask import current_app
        sio = getattr(current_app, "socketio", None)
        if sio:
            sio.emit(
                "lesson_tasks_updated",
                {"lesson_id": lesson_id, "assignment_type": (assignment_type or "homework")},
                room=_room(lesson_id),
                namespace="/lesson",
            )
    except Exception as e:
        logger.warning("emit_lesson_tasks_updated failed: %s", e)


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


def emit_lesson_studio_updated(lesson_id: int, state: dict) -> None:
    """Synchronize the teacher's lesson controls with the student's studio."""
    try:
        from flask import current_app
        sio = getattr(current_app, "socketio", None)
        if sio:
            sio.emit(
                "lesson_studio_updated",
                {"lesson_id": lesson_id, "state": state},
                room=_room(lesson_id),
                namespace="/lesson",
            )
    except Exception as e:
        logger.warning("emit_lesson_studio_updated failed: %s", e)


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
