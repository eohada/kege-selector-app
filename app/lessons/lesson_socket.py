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
_lesson_board_strokes: dict[int, dict[str, dict[str, Any]]] = {}
_lesson_camera_state: dict[int, dict[str, Any]] = {}
_lesson_room_ui: dict[int, dict[str, dict[str, Any]]] = {}
_lesson_code_state: dict[int, dict[str, Any]] = {}
_lesson_code_cursor_emit_at: dict[str, float] = {}
_lesson_code_update_emit_at: dict[str, float] = {}
_lesson_pointer_emit_at: dict[str, float] = {}
_lesson_laser_emit_at: dict[str, float] = {}
_lesson_control_cache: dict[int, tuple[float, dict[str, Any]]] = {}
_lesson_operation_locks: dict[int, RLock] = {}
_pointer_colors = ('#4f46e5', '#0f766e', '#c2410c', '#be123c', '#7c3aed', '#0369a1')


_lesson_board_pages: dict[int, list[dict[str, Any]]] = {}
_lesson_board_active_page: dict[int, str] = {}


def _room(lesson_id: int) -> str:
    return f"lesson:{lesson_id}"


def _load_cached_board_data(lesson_id: int) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    if lesson_id not in _lesson_board_strokes:
        _lesson_board_strokes[lesson_id] = {}
        _lesson_board_pages[lesson_id] = [{"id": "page_1", "title": "Страница 1", "background": "dots"}]
        _lesson_board_active_page[lesson_id] = "page_1"
        try:
            from app.models import Lesson
            lesson = Lesson.query.get(lesson_id)
            if lesson:
                from app.lessons.routes import _lesson_studio_state
                state = _lesson_studio_state(lesson)
                board = state.get("board") or {}
                strokes = board.get("strokes") or []
                for s in strokes:
                    if isinstance(s, dict):
                        sid = str(s.get("id") or s.get("stroke_id") or len(_lesson_board_strokes[lesson_id]))
                        _lesson_board_strokes[lesson_id][sid] = s
                pages = board.get("pages")
                if isinstance(pages, list) and pages:
                    _lesson_board_pages[lesson_id] = pages
                active = board.get("active_page_id")
                if active:
                    _lesson_board_active_page[lesson_id] = str(active)
        except Exception as e:
            logger.warning("Error loading cached board data for lesson %s: %s", lesson_id, e)
    return (
        _lesson_board_strokes[lesson_id],
        _lesson_board_pages.get(lesson_id) or [{"id": "page_1", "title": "Страница 1", "background": "dots"}],
        _lesson_board_active_page.get(lesson_id) or "page_1",
    )


def _load_cached_board_strokes(lesson_id: int) -> dict[str, Any]:
    return _load_cached_board_data(lesson_id)[0]


def _load_cached_board_pages(lesson_id: int) -> list[dict[str, Any]]:
    return _load_cached_board_data(lesson_id)[1]


def _load_cached_board_active_page(lesson_id: int) -> str:
    return _load_cached_board_data(lesson_id)[2]


_flask_app = None
_lesson_persist_timers: dict[int, Any] = {}
_lesson_persist_lock = RLock()


def _schedule_persist_cached_board_strokes(lesson_id: int, delay: float = 1.2) -> None:
    from threading import Timer
    with _lesson_persist_lock:
        existing = _lesson_persist_timers.get(lesson_id)
        if existing:
            try:
                existing.cancel()
            except Exception:
                pass
        t = Timer(delay, _persist_cached_board_strokes, args=[lesson_id])
        t.daemon = True
        _lesson_persist_timers[lesson_id] = t
        t.start()


def _persist_cached_board_strokes(lesson_id: int) -> None:
    with _lesson_persist_lock:
        _lesson_persist_timers.pop(lesson_id, None)

    def _do_persist():
        try:
            from app.models import Lesson, db, moscow_now
            lesson = Lesson.query.get(lesson_id)
            if lesson:
                from app.lessons.routes import _lesson_studio_state, _save_lesson_studio_state
                state = _lesson_studio_state(lesson)
                strokes = list(_lesson_board_strokes.get(lesson_id, {}).values())
                pages = _lesson_board_pages.get(lesson_id) or [{"id": "page_1", "title": "Страница 1", "background": "dots"}]
                active_page_id = _lesson_board_active_page.get(lesson_id) or "page_1"
                board = state.get("board") or {}
                rev = int(board.get("revision") or 0) + 1
                state["board"] = {
                    "strokes": strokes,
                    "pages": pages,
                    "active_page_id": active_page_id,
                    "revision": rev,
                    "updated_at": moscow_now().isoformat(),
                }
                _save_lesson_studio_state(lesson, state)
                db.session.commit()
        except Exception as e:
            logger.warning("Error persisting cached board strokes for lesson %s: %s", lesson_id, e)

    global _flask_app
    if _flask_app:
        with _flask_app.app_context():
            _do_persist()
    else:
        try:
            from flask import current_app
            if current_app:
                with current_app.app_context():
                    _do_persist()
            else:
                _do_persist()
        except Exception:
            _do_persist()



def _room_control(lesson_id: int) -> dict[str, Any]:
    cached = _lesson_control_cache.get(lesson_id)
    now = monotonic()
    if cached and now - cached[0] < 10.0:
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


def _resolve_user_presence_info(user) -> dict[str, Any]:
    role = "teacher"
    if user.is_student():
        role = "student"
    elif user.is_parent():
        role = "parent"
    from app.models import UserProfile, Student
    profile = UserProfile.query.filter_by(user_id=user.id).first()
    student = Student.query.filter_by(user_id=user.id).first() if user.is_student() else None
    name = ""
    school_class = None
    if student:
        name = student.name or ""
        school_class = student.school_class
    if not name and profile:
        name = f"{profile.first_name or ''} {profile.last_name or ''}".strip()
    if not name:
        name = user.username or user.email or "Участник"
    return {
        "user_id": user.id,
        "role": role,
        "name": name,
        "school_class": school_class,
    }


def register_lesson_socket(socketio, app=None) -> None:
    global _flask_app
    if app is not None:
        _flask_app = app
    else:
        try:
            from flask import current_app
            _flask_app = getattr(socketio, 'app', None) or (current_app._get_current_object() if current_app else None)
        except Exception:
            _flask_app = getattr(socketio, 'app', None)

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
        uinfo = _resolve_user_presence_info(current_user)
        _lesson_presence[lesson_id][current_user.id] = {
            "user_id": current_user.id,
            "sid": request.sid,
            "tab": "theory",
            "role": uinfo["role"],
            "name": uinfo["name"],
            "school_class": uinfo["school_class"],
            "color": _pointer_colors[int(current_user.id) % len(_pointer_colors)],
            "client_id": None,
            "page_id": None,
            "follow": False,
        }
        # Отправить текущему клиенту список присутствующих и их вкладки
        presence_list = list(_lesson_presence[lesson_id].values())
        socketio.emit("lesson_presence", {"lesson_id": lesson_id, "presence": presence_list}, room=request.sid, namespace="/lesson")
        # Остальным в комнате — обновлённый список (включая нового участника)
        socketio.emit(
            "lesson_presence",
            {"lesson_id": lesson_id, "presence": presence_list},
            room=room,
            namespace="/lesson",
            include_self=False,
        )
        # Воспроизвести текущее состояние интерфейса комнаты (окна, режимы)
        room_ui = _lesson_room_ui.get(lesson_id) or {}
        for ui_payload in room_ui.values():
            socketio.emit("lesson_room_ui_state", ui_payload, room=request.sid, namespace="/lesson")
        # Воспроизвести текущие штрихи и страницы доски
        board_strokes = list(_load_cached_board_strokes(lesson_id).values())
        board_pages = _load_cached_board_pages(lesson_id)
        active_page_id = _load_cached_board_active_page(lesson_id)
        socketio.emit(
            "board_snapshot",
            {
                "lesson_id": lesson_id,
                "strokes": board_strokes,
                "pages": board_pages,
                "active_page_id": active_page_id,
            },
            room=request.sid,
            namespace="/lesson",
        )
        # Воспроизвести текущую позицию камеры доски
        camera_state = _lesson_camera_state.get(lesson_id)
        if camera_state:
            socketio.emit("whiteboard_live_camera", camera_state, room=request.sid, namespace="/lesson")

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
        uinfo = _resolve_user_presence_info(current_user)
        previous = _lesson_presence.get(lesson_id, {}).get(current_user.id, {})
        _lesson_presence[lesson_id][current_user.id] = {
            **previous,
            "user_id": current_user.id,
            "tab": tab,
            "role": uinfo["role"],
            "name": uinfo["name"],
            "school_class": uinfo["school_class"],
            "color": previous.get("color") or _pointer_colors[int(current_user.id) % len(_pointer_colors)],
        }
        presence_list = list(_lesson_presence[lesson_id].values())
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
        stroke_id = str(stroke.get("id") or "")
        if stroke_id:
            if not stroke.get("page_id"):
                stroke["page_id"] = "page_1"
            cached = _load_cached_board_strokes(lesson_id)
            if stroke_id in cached:
                existing = cached[stroke_id]
                cached[stroke_id] = {**stroke, **existing, "src": stroke.get("src") or existing.get("src")}
            else:
                cached[stroke_id] = stroke
            _schedule_persist_cached_board_strokes(lesson_id)
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
        board_strokes = _load_cached_board_strokes(lesson_id)
        if action == "update":
            for s in (data.get("strokes") or []):
                sid = str((s or {}).get("id") or "")
                if sid:
                    if sid in board_strokes:
                        if not (s or {}).get("src") and board_strokes[sid].get("src"):
                            s["src"] = board_strokes[sid]["src"]
                        if not (s or {}).get("page_id") and board_strokes[sid].get("page_id"):
                            s["page_id"] = board_strokes[sid]["page_id"]
                    elif not (s or {}).get("page_id"):
                        s["page_id"] = "page_1"
                    board_strokes[sid] = s
            _schedule_persist_cached_board_strokes(lesson_id)
        elif action == "delete":
            del_ids = data.get("strokes") or data.get("stroke_ids") or []
            for sid in del_ids:
                board_strokes.pop(str(sid), None)
            _schedule_persist_cached_board_strokes(lesson_id)
        elif action == "clear":
            target_page_id = data.get("page_id")
            if target_page_id:
                to_delete = [sid for sid, s in board_strokes.items() if s.get("page_id") == target_page_id]
                for sid in to_delete:
                    board_strokes.pop(sid, None)
            else:
                _lesson_board_strokes[lesson_id] = {}
            _schedule_persist_cached_board_strokes(lesson_id)
        elif action == "page_create":
            new_page = data.get("page")
            if isinstance(new_page, dict) and new_page.get("id"):
                pages = _load_cached_board_pages(lesson_id)
                if not any(p.get("id") == new_page.get("id") for p in pages):
                    pages.append({
                        "id": str(new_page.get("id")),
                        "title": str(new_page.get("title") or f"Страница {len(pages) + 1}"),
                        "background": str(new_page.get("background") or "dots"),
                    })
                    _lesson_board_pages[lesson_id] = pages
                    _schedule_persist_cached_board_strokes(lesson_id)
        elif action == "page_delete":
            del_page_id = str(data.get("page_id") or "")
            if del_page_id:
                pages = _load_cached_board_pages(lesson_id)
                if len(pages) > 1:
                    _lesson_board_pages[lesson_id] = [p for p in pages if p.get("id") != del_page_id]
                    to_delete = [sid for sid, s in board_strokes.items() if s.get("page_id") == del_page_id]
                    for sid in to_delete:
                        board_strokes.pop(sid, None)
                    _schedule_persist_cached_board_strokes(lesson_id)
        elif action == "page_switch":
            sw_page_id = str(data.get("page_id") or "")
            if sw_page_id:
                _lesson_board_active_page[lesson_id] = sw_page_id
                _schedule_persist_cached_board_strokes(lesson_id)
        elif action == "page_bg":
            bg_page_id = str(data.get("page_id") or "")
            bg_val = str(data.get("background") or "dots")
            if bg_page_id:
                pages = _load_cached_board_pages(lesson_id)
                for p in pages:
                    if p.get("id") == bg_page_id:
                        p["background"] = bg_val
                _schedule_persist_cached_board_strokes(lesson_id)
        elif action == "page_rename":
            rn_page_id = str(data.get("page_id") or "")
            rn_title = str(data.get("title") or "").strip()
            if rn_page_id and rn_title:
                pages = _load_cached_board_pages(lesson_id)
                for p in pages:
                    if p.get("id") == rn_page_id:
                        p["title"] = rn_title[:120]
                _schedule_persist_cached_board_strokes(lesson_id)

        socketio.emit(
            "board_action",
            {
                "lesson_id": lesson_id,
                "action": action,
                "strokes": data.get("strokes"),
                "stroke_ids": data.get("stroke_ids"),
                "objects": data.get("objects"),
                "object_id": data.get("object_id"),
                "width": data.get("width"),
                "height": data.get("height"),
                "page_id": data.get("page_id"),
                "page": data.get("page"),
                "title": data.get("title"),
                "background": data.get("background"),
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
            from flask_socketio import join_room
            join_room(_room(lesson_id))
            from app.lessons.routes import _whiteboard_access
            _lesson, role = _whiteboard_access(lesson_id)
            from app.lessons.whiteboard_service import board_payload, get_or_create_board, can_student_edit_page
            board = get_or_create_board(lesson_id)
            identity = _lesson_presence.setdefault(lesson_id, {}).setdefault(current_user.id, {})
            uinfo = _resolve_user_presence_info(current_user)
            identity.update({
                "user_id": current_user.id,
                "sid": request.sid,
                "role": uinfo["role"],
                "name": uinfo["name"],
                "school_class": uinfo["school_class"],
                "client_id": (data or {}).get("client_id"),
                "page_id": (data or {}).get("page_id"),
                "follow": bool((data or {}).get("follow")),
                "color": identity.get("color") or _pointer_colors[int(current_user.id) % len(_pointer_colors)],
            })
            snapshot_payload = board_payload(board)
            active_page_id = snapshot_payload.get("document", {}).get("active_page_id")
            snapshot_payload["permissions"] = {
                "role": role,
                "can_edit": role == "teacher" or (role == "student" and can_student_edit_page(snapshot_payload.get("document", {}), active_page_id)),
                "can_present": role == "teacher",
                "can_lock": role == "teacher",
                "control": snapshot_payload.get("document", {}).get("presentation", {}).get("control", {}),
            }
            socketio.emit(
                "whiteboard_snapshot",
                {"lesson_id": lesson_id, **snapshot_payload},
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
            board_strokes = list(_load_cached_board_strokes(lesson_id).values())
            board_pages = _load_cached_board_pages(lesson_id)
            active_page_id = _load_cached_board_active_page(lesson_id)
            socketio.emit(
                "board_snapshot",
                {
                    "lesson_id": lesson_id,
                    "strokes": board_strokes,
                    "pages": board_pages,
                    "active_page_id": active_page_id,
                },
                room=request.sid,
                namespace="/lesson",
            )
            camera_state = _lesson_camera_state.get(lesson_id)
            if camera_state:
                socketio.emit("whiteboard_live_camera", camera_state, room=request.sid, namespace="/lesson")
            code_state = _lesson_code_state.get(lesson_id)
            if code_state:
                socketio.emit("lesson_code_snapshot", {"lesson_id": lesson_id, **code_state}, room=request.sid, namespace="/lesson")
        except Exception as error:
            logger.warning("whiteboard_join failed: %s", error)

    @socketio.on("kick_participant", namespace="/lesson")
    def _on_kick_participant(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        lesson_id = (data or {}).get("lesson_id")
        target_user_id = (data or {}).get("user_id")
        if not lesson_id or not target_user_id:
            return
        try:
            lesson_id = int(lesson_id)
            target_user_id = int(target_user_id)
        except (TypeError, ValueError):
            return
        try:
            from app.lessons.routes import _whiteboard_access
            _lesson, role = _whiteboard_access(lesson_id)
            if role != "teacher":
                return
        except Exception:
            return

        target_info = _lesson_presence.get(lesson_id, {}).pop(target_user_id, None)
        target_sid = target_info.get("sid") if target_info else None

        kick_payload = {
            "lesson_id": lesson_id,
            "user_id": target_user_id,
            "message": "Преподаватель завершил ваше участие в этом уроке.",
            "redirect_url": "/schedule",
        }
        if target_sid:
            socketio.emit("lesson_kicked", kick_payload, room=target_sid, namespace="/lesson")
        socketio.emit("lesson_kicked", kick_payload, room=_room(lesson_id), namespace="/lesson")

        socketio.emit(
            "lesson_presence",
            {"lesson_id": lesson_id, "presence": list(_lesson_presence.get(lesson_id, {}).values())},
            room=_room(lesson_id),
            namespace="/lesson",
        )

    @socketio.on("lesson_room_ui", namespace="/lesson")
    def _on_lesson_room_ui(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        try:
            lesson_id = int((data or {}).get("lesson_id"))
            role = (_lesson_presence.get(lesson_id, {}).get(current_user.id) or {}).get("role")
            if not role:
                _lesson, role = __import__("app.lessons.routes", fromlist=["_whiteboard_access"])._whiteboard_access(lesson_id)
            kind = str((data or {}).get("kind") or "")

            standard_kinds = {"mode", "window", "window_layout", "run", "run_start", "terminal_output", "terminal_tab"}
            tracer_kinds = {"tracer_state", "tracer_window", "tracer_run", "tracer_breakpoint", "tracer_step", "tracer_input_submit"}
            orbit_kinds = {
                "orbit_beacon", "orbit_stamp", "orbit_stamp_move", "orbit_stamp_remove",
                "orbit_sticky", "orbit_sticky_input", "orbit_sticky_move", "orbit_sticky_remove",
                "orbit_timer_sync", "orbit_calc_sync", "orbit_laser", "orbit_laser_stop", "orbit_cheat_sync"
            }
            teacher_master_kinds = {
                "focus_board", "freeze_student", "free_mode", "teacher_stamp", "teacher_hint",
                "blitz_start", "blitz_update", "blitz_end", "teacher_answer_vis", "task_switch"
            }

            if kind not in (standard_kinds | orbit_kinds | teacher_master_kinds | tracer_kinds):
                return

            control = _room_control(lesson_id)
            win_mode = control.get("windows_mode") or ("independent" if control.get("windows_sync") is False else "teacher")
            is_student_run = (
                role == "student"
                and control.get("student_code_editing")
                and kind in {"run", "run_start", "terminal_output", "terminal_tab"}
            )
            is_student_tracer = (
                role == "student"
                and not control.get("freeze_student")
                and kind in tracer_kinds
            )
            is_tracer_action = kind in tracer_kinds
            is_window_action = kind in {"window", "window_layout"}
            is_orbit_action = kind in orbit_kinds
            is_teacher_action = kind in teacher_master_kinds

            if is_teacher_action and role != "teacher":
                socketio.emit("whiteboard_error", {"message": "Недостаточно прав: действие доступно только преподавателю"}, room=request.sid, namespace="/lesson")
                return

            if role == "student" and is_tracer_action and control.get("freeze_student"):
                socketio.emit("whiteboard_error", {"message": "Действия заблокированы преподавателем"}, room=request.sid, namespace="/lesson")
                return

            if is_window_action:
                target_win = str((data or {}).get("window_id") or "")
                if target_win != "tracer-window":
                    if win_mode == "independent":
                        return
                    if win_mode == "teacher" and role != "teacher":
                        socketio.emit("whiteboard_error", {"message": "Управление окнами закреплено за преподавателем"}, room=request.sid, namespace="/lesson")
                        return
                    if win_mode == "student" and role == "teacher":
                        socketio.emit("whiteboard_error", {"message": "Управление окнами передано ученику"}, room=request.sid, namespace="/lesson")
                        return
                    if kind == "window_layout" and control.get("window_positions_sync") is False:
                        return
                    allowed_ctrl = control.get("windows_allowed")
                    if allowed_ctrl and target_win not in allowed_ctrl and role != "teacher":
                        return

            if not (is_window_action or is_student_run or is_student_tracer or is_orbit_action or role == "teacher"):
                socketio.emit("whiteboard_error", {"message": "Недостаточно прав для управления интерфейсом комнаты"}, room=request.sid, namespace="/lesson")
                return

            if kind == "mode" and not _teacher_control_enabled(control, "teacher_controls_mode"):
                return
            if kind in {"run", "run_start"} and not (control.get("auto_open_terminal_on_run") or control.get("terminal_sync")):
                return
            if kind == "terminal_output" and not control.get("terminal_sync"):
                return

            payload = {"lesson_id": lesson_id, "kind": kind, "updated_at": int(time() * 1000)}
            allowed_windows = {
                "task-window", "terminal-window", "code-window", "lesson-info-window",
                "teacher-notes-window", "notes-window", "theory-window", "reference-window", "files-window",
                "tracer-window"
            }
            if kind == "mode":
                mode = str((data or {}).get("mode") or "code")
                if mode not in {"code", "board"}:
                    return
                payload["mode"] = mode
            elif kind == "window":
                window_id = str((data or {}).get("window_id") or "")[:64]
                action = str((data or {}).get("action") or "")
                if window_id not in allowed_windows or action not in {"open", "minimize"}:
                    return
                payload.update({"window_id": window_id, "action": action})
            elif kind == "window_layout":
                window_id = str((data or {}).get("window_id") or "")[:64]
                if window_id not in allowed_windows:
                    return
                payload.update({
                    "window_id": window_id,
                    "left": (data or {}).get("left"),
                    "top": (data or {}).get("top"),
                    "width": (data or {}).get("width"),
                    "height": (data or {}).get("height"),
                    "is_maximized": bool((data or {}).get("is_maximized")),
                })
            elif kind == "terminal_tab":
                tab = str((data or {}).get("tab") or "output")[:32]
                if tab not in {"output", "problems"}:
                    return
                payload["tab"] = tab
            elif kind == "terminal_output":
                payload.update({
                    "file_name": str((data or {}).get("file_name") or "main.py")[:120],
                    "output": str((data or {}).get("output") or "")[:200000],
                    "duration": str((data or {}).get("duration") or "")[:32],
                    "exit_code": int((data or {}).get("exit_code") or 0),
                    "is_error": bool((data or {}).get("is_error")),
                })
            elif kind in {"run", "run_start"}:
                code = str((data or {}).get("code") or "")[:100000]
                payload.update({"file_name": str((data or {}).get("file_name") or "main.py")[:120], "code": code})
            elif kind in tracer_kinds:
                if (data or {}).get("step") is not None:
                    payload["step"] = int(data["step"])
                if (data or {}).get("playing") is not None:
                    payload["playing"] = bool(data["playing"])
                if (data or {}).get("speed") is not None:
                    try:
                        payload["speed"] = float(data["speed"])
                    except (ValueError, TypeError):
                        payload["speed"] = 1.0
                if "file_name" in (data or {}):
                    payload["file_name"] = str(data["file_name"] or "main.py")[:120]
                if "is_open" in (data or {}):
                    payload["is_open"] = bool(data["is_open"])
                if "is_detached" in (data or {}):
                    payload["is_detached"] = bool(data["is_detached"])
                if "code" in (data or {}):
                    payload["code"] = str(data["code"] or "")[:100000]
                if "breakpoints" in (data or {}):
                    raw_bp = data.get("breakpoints")
                    if isinstance(raw_bp, (list, tuple, set)):
                        bps = []
                        for b in raw_bp:
                            try:
                                num = int(b)
                                if 1 <= num <= 50000:
                                    bps.append(num)
                            except (ValueError, TypeError):
                                pass
                        payload["breakpoints"] = bps[:500]
                if "inputs" in (data or {}):
                    raw_in = data.get("inputs")
                    if isinstance(raw_in, (list, tuple)):
                        payload["inputs"] = [str(x)[:200] for x in raw_in[:100]]
                if "input_val" in (data or {}):
                    payload["input_val"] = str(data["input_val"])[:500]
                if "action" in (data or {}):
                    payload["action"] = str(data["action"])[:32]
                if "line" in (data or {}):
                    try:
                        payload["line"] = int(data["line"])
                    except (ValueError, TypeError):
                        pass
            else:
                # Orbit and Master actions
                uinfo = _resolve_user_presence_info(current_user)
                payload["author"] = str((data or {}).get("author") or uinfo.get("name") or "Участник")[:60]
                payload["author_role"] = role
                for field in (
                    "id", "action", "x", "y", "maxW", "maxH", "left", "top",
                    "label", "type", "typeClass", "icon", "iconClass", "color",
                    "text", "expr", "val", "points", "duration", "started_at",
                    "remaining", "hint", "tier", "visible", "answer", "task_id",
                    "seconds", "isRunning", "isOpen", "mode", "user_name"
                ):
                    if field in (data or {}):
                        payload[field] = data[field]

            # Persistence management for room_ui state
            persistent_state_kinds = {"orbit_stamp", "teacher_stamp", "orbit_sticky", "orbit_timer_sync", "orbit_calc_sync", "orbit_cheat_sync", "blitz_start", "teacher_answer_vis"}
            if kind in persistent_state_kinds:
                room_state = _lesson_room_ui.setdefault(lesson_id, {})
                action = str(payload.get("action") or "")
                if action == "close":
                    if kind == "orbit_timer_sync":
                        room_state.pop("timer", None)
                    elif kind == "orbit_calc_sync":
                        room_state.pop("calc", None)
                    elif kind == "orbit_cheat_sync":
                        room_state.pop("cheat", None)
                else:
                    item_id = str(payload.get("id") or "default")
                    state_key = (
                        "blitz" if kind == "blitz_start"
                        else "timer" if kind == "orbit_timer_sync"
                        else "calc" if kind == "orbit_calc_sync"
                        else "cheat" if kind == "orbit_cheat_sync"
                        else "answer_vis" if kind == "teacher_answer_vis"
                        else f"{kind}:{item_id}"
                    )
                    room_state[state_key] = payload
            elif kind in {"orbit_stamp_move", "orbit_sticky_move", "orbit_sticky_input"}:
                room_state = _lesson_room_ui.setdefault(lesson_id, {})
                base_kind = "orbit_stamp" if "stamp" in kind else "orbit_sticky"
                item_id = str(payload.get("id") or "default")
                state_key = f"{base_kind}:{item_id}"
                if state_key in room_state:
                    room_state[state_key].update(payload)
            elif kind in {"orbit_stamp_remove", "orbit_sticky_remove", "blitz_end"}:
                room_state = _lesson_room_ui.get(lesson_id, {})
                if kind == "blitz_end":
                    room_state.pop("blitz", None)
                else:
                    item_id = str(payload.get("id") or "default")
                    room_state.pop(f"orbit_stamp:{item_id}", None)
                    room_state.pop(f"teacher_stamp:{item_id}", None)
                    room_state.pop(f"orbit_sticky:{item_id}", None)
            elif kind in {"mode", "terminal_output", "terminal_tab", "window", "window_layout", "tracer_state", "tracer_window", "tracer_run", "tracer_breakpoint"}:
                room_state = _lesson_room_ui.setdefault(lesson_id, {})
                if kind == "tracer_state" and payload.get("is_open") is False:
                    room_state.pop("tracer_state", None)
                elif kind == "tracer_breakpoint":
                    if "tracer_state" in room_state:
                        room_state["tracer_state"]["breakpoints"] = payload.get("breakpoints", [])
                    else:
                        room_state["tracer_state"] = {"kind": "tracer_state", "breakpoints": payload.get("breakpoints", []), "lesson_id": lesson_id}
                else:
                    state_key = (
                        "mode" if kind == "mode"
                        else "terminal_output" if kind == "terminal_output"
                        else "terminal_tab" if kind == "terminal_tab"
                        else "tracer_state" if kind == "tracer_state"
                        else "tracer_window" if kind == "tracer_window"
                        else "tracer_run" if kind == "tracer_run"
                        else f"window_layout:{payload['window_id']}" if kind == "window_layout"
                        else f"window:{payload['window_id']}"
                    )
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
            identity = _lesson_presence.get(lesson_id, {}).get(current_user.id)
            if identity:
                role = identity.get("role", "student")
            else:
                _lesson, role = __import__("app.lessons.routes", fromlist=["_whiteboard_access"])._whiteboard_access(lesson_id)
            incoming_code = str((data or {}).get("code") or "")[:100000]
            incoming_file = str((data or {}).get("file_name") or "main.py")[:120]
            incoming_files = (data or {}).get("files")
            incoming_tabs = (data or {}).get("open_tabs")
            current = _lesson_code_state.get(lesson_id)
            if role == "parent":
                if current:
                    socketio.emit("lesson_code_snapshot", {"lesson_id": lesson_id, **current}, room=request.sid, namespace="/lesson")
                return
            if current is None and role == "teacher":
                initial_files = {}
                if isinstance(incoming_files, dict) and incoming_files:
                    initial_files = {str(k)[:120]: str(v)[:100000] for k, v in incoming_files.items()}
                elif incoming_code:
                    initial_files[incoming_file] = incoming_code
                else:
                    initial_files["main.py"] = ""

                initial_tabs = [incoming_file]
                if isinstance(incoming_tabs, list) and incoming_tabs:
                    initial_tabs = [str(t)[:120] for t in incoming_tabs if str(t)[:120] in initial_files]
                if not initial_tabs:
                    initial_tabs = list(initial_files.keys())[:1]

                current = {
                    "file_name": incoming_file,
                    "code": initial_files.get(incoming_file, incoming_code),
                    "files": initial_files,
                    "open_tabs": initial_tabs,
                    "active_file": incoming_file,
                    "version": 1,
                    "updated_at": int(time() * 1000),
                }
                _lesson_code_state[lesson_id] = current
            elif current is not None:
                # Гарантируем наличие структуры files в current
                if "files" not in current:
                    current["files"] = {current.get("file_name", "main.py"): current.get("code", "")}
                if "open_tabs" not in current:
                    current["open_tabs"] = [current.get("file_name", "main.py")]
                if "active_file" not in current:
                    current["active_file"] = current.get("file_name", "main.py")

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
            identity = _lesson_presence.get(lesson_id, {}).get(current_user.id)
            if identity:
                role = identity.get("role", "student")
            else:
                _lesson, role = __import__("app.lessons.routes", fromlist=["_whiteboard_access"])._whiteboard_access(lesson_id)
            control = _room_control(lesson_id)
            if role == "parent" or not control.get("code_sync") or (role != "teacher" and not control.get("student_code_editing")):
                return
            throttle_key = f"{lesson_id}:{current_user.id}:{request.sid}"
            now = monotonic()
            _lesson_code_update_emit_at[throttle_key] = now
            code = str((data or {}).get("code") or "")[:100000]
            file_name = str((data or {}).get("file_name") or "main.py")[:120]

            curr_state = _lesson_code_state.get(lesson_id) or {}
            files_dict = dict(curr_state.get("files") or {})
            files_dict[file_name] = code
            open_tabs = list(curr_state.get("open_tabs") or [file_name])
            if file_name not in open_tabs:
                open_tabs.append(file_name)

            state = {
                "file_name": file_name,
                "code": code,
                "files": files_dict,
                "open_tabs": open_tabs,
                "active_file": file_name,
                "version": int(curr_state.get("version") or 0) + 1,
                "updated_at": int(time() * 1000),
            }
            _lesson_code_state[lesson_id] = state
            socketio.emit("lesson_code_update", {"lesson_id": lesson_id, "user_id": current_user.id, **state}, room=_room(lesson_id), namespace="/lesson", include_self=False)
        except Exception as error:
            logger.warning("lesson_code_update failed: %s", error)

    @socketio.on("lesson_vfs_file_create", namespace="/lesson")
    def _on_lesson_vfs_file_create(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        try:
            lesson_id = int((data or {}).get("lesson_id"))
            identity = _lesson_presence.get(lesson_id, {}).get(current_user.id)
            role = identity.get("role", "student") if identity else "student"
            control = _room_control(lesson_id)
            if role == "parent" or not control.get("code_sync") or (role != "teacher" and not control.get("student_code_editing")):
                return

            file_name = str((data or {}).get("file_name") or "").strip()[:120]
            if not file_name:
                return
            code = str((data or {}).get("code") or "")[:100000]

            curr_state = _lesson_code_state.get(lesson_id) or {}
            files_dict = dict(curr_state.get("files") or {})
            files_dict[file_name] = code
            open_tabs = list(curr_state.get("open_tabs") or [])
            if file_name not in open_tabs:
                open_tabs.append(file_name)

            state = {
                "file_name": file_name,
                "code": code,
                "files": files_dict,
                "open_tabs": open_tabs,
                "active_file": file_name,
                "version": int(curr_state.get("version") or 0) + 1,
                "updated_at": int(time() * 1000),
            }
            _lesson_code_state[lesson_id] = state
            socketio.emit("lesson_vfs_file_create", {
                "lesson_id": lesson_id,
                "user_id": current_user.id,
                "file_name": file_name,
                "code": code,
                "open_tabs": open_tabs,
                "active_file": file_name,
                "files": files_dict,
            }, room=_room(lesson_id), namespace="/lesson", include_self=False)
        except Exception as error:
            logger.warning("lesson_vfs_file_create failed: %s", error)

    @socketio.on("lesson_vfs_file_rename", namespace="/lesson")
    def _on_lesson_vfs_file_rename(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        try:
            lesson_id = int((data or {}).get("lesson_id"))
            identity = _lesson_presence.get(lesson_id, {}).get(current_user.id)
            role = identity.get("role", "student") if identity else "student"
            control = _room_control(lesson_id)
            if role == "parent" or not control.get("code_sync") or (role != "teacher" and not control.get("student_code_editing")):
                return

            old_name = str((data or {}).get("old_name") or "").strip()[:120]
            new_name = str((data or {}).get("new_name") or "").strip()[:120]
            if not old_name or not new_name or old_name == new_name:
                return

            curr_state = _lesson_code_state.get(lesson_id) or {}
            files_dict = dict(curr_state.get("files") or {})
            code = files_dict.pop(old_name, str((data or {}).get("code") or ""))
            files_dict[new_name] = code
            open_tabs = [new_name if t == old_name else t for t in (curr_state.get("open_tabs") or [])]
            active_file = new_name if curr_state.get("active_file") == old_name else curr_state.get("active_file", new_name)

            state = {
                "file_name": active_file,
                "code": files_dict.get(active_file, ""),
                "files": files_dict,
                "open_tabs": open_tabs,
                "active_file": active_file,
                "version": int(curr_state.get("version") or 0) + 1,
                "updated_at": int(time() * 1000),
            }
            _lesson_code_state[lesson_id] = state
            socketio.emit("lesson_vfs_file_rename", {
                "lesson_id": lesson_id,
                "user_id": current_user.id,
                "old_name": old_name,
                "new_name": new_name,
                "open_tabs": open_tabs,
                "active_file": active_file,
                "files": files_dict,
            }, room=_room(lesson_id), namespace="/lesson", include_self=False)
        except Exception as error:
            logger.warning("lesson_vfs_file_rename failed: %s", error)

    @socketio.on("lesson_vfs_file_delete", namespace="/lesson")
    def _on_lesson_vfs_file_delete(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        try:
            lesson_id = int((data or {}).get("lesson_id"))
            identity = _lesson_presence.get(lesson_id, {}).get(current_user.id)
            role = identity.get("role", "student") if identity else "student"
            control = _room_control(lesson_id)
            if role == "parent" or not control.get("code_sync") or (role != "teacher" and not control.get("student_code_editing")):
                return

            file_name = str((data or {}).get("file_name") or "").strip()[:120]
            if not file_name or file_name == "main.py":
                return

            curr_state = _lesson_code_state.get(lesson_id) or {}
            files_dict = dict(curr_state.get("files") or {})
            files_dict.pop(file_name, None)
            open_tabs = [t for t in (curr_state.get("open_tabs") or []) if t != file_name]
            if not open_tabs:
                open_tabs = ["main.py"]
            active_file = curr_state.get("active_file")
            if active_file == file_name:
                active_file = open_tabs[0]

            state = {
                "file_name": active_file,
                "code": files_dict.get(active_file, ""),
                "files": files_dict,
                "open_tabs": open_tabs,
                "active_file": active_file,
                "version": int(curr_state.get("version") or 0) + 1,
                "updated_at": int(time() * 1000),
            }
            _lesson_code_state[lesson_id] = state
            socketio.emit("lesson_vfs_file_delete", {
                "lesson_id": lesson_id,
                "user_id": current_user.id,
                "file_name": file_name,
                "open_tabs": open_tabs,
                "active_file": active_file,
                "files": files_dict,
            }, room=_room(lesson_id), namespace="/lesson", include_self=False)
        except Exception as error:
            logger.warning("lesson_vfs_file_delete failed: %s", error)

    @socketio.on("lesson_vfs_tab_switch", namespace="/lesson")
    def _on_lesson_vfs_tab_switch(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        try:
            lesson_id = int((data or {}).get("lesson_id"))
            control = _room_control(lesson_id)
            if not control.get("code_sync"):
                return

            file_name = str((data or {}).get("file_name") or "main.py")[:120]
            curr_state = _lesson_code_state.get(lesson_id) or {}
            curr_state["active_file"] = file_name
            curr_state["file_name"] = file_name
            open_tabs = list(curr_state.get("open_tabs") or [])
            if file_name not in open_tabs:
                open_tabs.append(file_name)
                curr_state["open_tabs"] = open_tabs

            socketio.emit("lesson_vfs_tab_switch", {
                "lesson_id": lesson_id,
                "user_id": current_user.id,
                "file_name": file_name,
                "open_tabs": open_tabs,
            }, room=_room(lesson_id), namespace="/lesson", include_self=False)
        except Exception as error:
            logger.warning("lesson_vfs_tab_switch failed: %s", error)

    @socketio.on("lesson_code_cursor", namespace="/lesson")
    def _on_lesson_code_cursor(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        try:
            lesson_id = int((data or {}).get("lesson_id"))
            throttle_key = f"{lesson_id}:{current_user.id}:{request.sid}"
            now = monotonic()
            if now - _lesson_code_cursor_emit_at.get(throttle_key, 0.0) < 0.025:
                return
            _lesson_code_cursor_emit_at[throttle_key] = now
            control = _room_control(lesson_id)
            if control.get("cursor_sync") is False:
                return
            identity = _lesson_presence.get(lesson_id, {}).get(current_user.id)
            if not identity:
                _whiteboard_access = __import__("app.lessons.routes", fromlist=["_whiteboard_access"])._whiteboard_access
                _whiteboard_access(lesson_id)
            identity = _lesson_presence.get(lesson_id, {}).get(current_user.id, {})
            raw_start = int((data or {}).get("start", 0))
            raw_end = int((data or {}).get("end", raw_start))
            is_hidden = bool((data or {}).get("hidden")) or raw_start < 0
            socketio.emit(
                "lesson_code_cursor",
                {
                    "lesson_id": lesson_id,
                    "user_id": current_user.id,
                    "name": identity.get("name") or getattr(current_user, "username", None) or "Участник",
                    "color": identity.get("color") or _pointer_colors[int(current_user.id) % len(_pointer_colors)],
                    "file_name": str((data or {}).get("file_name") or "main.py")[:120],
                    "hidden": is_hidden,
                    "cursor": {
                        "start": -1 if is_hidden else max(0, raw_start),
                        "end": -1 if is_hidden else max(0, raw_end),
                    },
                },
                room=_room(lesson_id),
                namespace="/lesson",
                include_self=False,
            )
        except Exception:
            return

    @socketio.on("whiteboard_operation", namespace="/lesson")
    def _on_whiteboard_operation(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        try:
            lesson_id = int((data or {}).get("lesson_id"))
            from flask_socketio import join_room
            join_room(_room(lesson_id))
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
            phase = str(payload.get("phase") or payload.get("action") or "")
            if phase not in {"start", "move", "end", "cancel"}:
                raise WhiteboardOperationError("Некорректная фаза live-штриха")
            stroke_id = str(payload.get("stroke_id") or "")[:96]
            page_id = str(payload.get("page_id") or "")[:96]
            if not page_id:
                try:
                    board_doc = normalize_document(get_or_create_board(lesson_id).document_state)
                    page_id = str(board_doc.get("active_page_id") or (board_doc.get("pages", [{}])[0].get("id") or "page_1"))
                except Exception:
                    page_id = "page_1"
            if not stroke_id:
                raise WhiteboardOperationError("Live-штрих не содержит идентификатор")
            key = f"{current_user.id}:{stroke_id}"
            lesson_strokes = _live_strokes.setdefault(lesson_id, {})
            existing = lesson_strokes.get(key)
            fast_path = phase == "move" and existing is not None
            if not fast_path:
                role = (_lesson_presence.get(lesson_id, {}).get(current_user.id) or {}).get("role")
                if not role:
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
            raw_points = payload.get("points")
            if isinstance(raw_points, list):
                points = raw_points
            elif isinstance(payload.get("point"), dict):
                points = [payload.get("point")]
            else:
                points = []
            if len(points) > 128:
                points = points[-128:]
            safe_points = []
            for point in points:
                if not isinstance(point, dict):
                    continue
                try:
                    x = float(point.get("x"))
                    y = float(point.get("y"))
                except (TypeError, ValueError):
                    continue
                if abs(x) > 100000 or abs(y) > 100000:
                    continue
                safe_points.append({"x": x, "y": y})
            if fast_path:
                style = existing["style"]
                page_id = existing["page_id"]
            else:
                style_payload = payload.get("style") if isinstance(payload.get("style"), dict) else {}
                style = {
                    "color": str(style_payload.get("color") or payload.get("color") or "#4f46e5")[:16],
                    "size": min(48, max(1, float(style_payload.get("size") or payload.get("width") or 4))),
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
            if existing and sequence > 0 and sequence <= existing.get("seq", 0):
                return
            if phase == "start" or not existing:
                existing = {"user_id": current_user.id, "sid": request.sid, "role": role, "seq": sequence or 1, "points": 0, "style": style, "page_id": page_id, "frame_id": payload.get("frame_id")}
                lesson_strokes[key] = existing
            else:
                existing["seq"] = sequence if sequence > 0 else (existing.get("seq", 0) + 1)
            existing["points"] += len(safe_points)
            if existing["points"] > 8192:
                lesson_strokes.pop(key, None)
                raise WhiteboardOperationError("Live-штрих слишком длинный")
            profile = _lesson_presence.get(lesson_id, {}).get(current_user.id, {})
            outgoing = {
                "lesson_id": lesson_id,
                "stroke_id": stroke_id,
                "page_id": page_id,
                "frame_id": payload.get("frame_id"),
                "phase": phase,
                "action": phase,
                "seq": existing.get("seq", sequence),
                "points": safe_points,
                "style": style,
                "stroke": payload.get("stroke"),
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
            if role not in ("teacher", "student"):
                return
            if role == "student" and _room_control(lesson_id).get("student_editing") is False:
                socketio.emit("whiteboard_error", {"message": "Рисование на доске отключено"}, room=request.sid, namespace="/lesson")
                return
            pointer = payload.get("pointer") if isinstance(payload.get("pointer"), dict) else {}
            socketio.emit(
                "whiteboard_live_laser",
                {
                    "lesson_id": lesson_id,
                    "user_id": current_user.id,
                    "client_id": payload.get("client_id"),
                    "page_id": payload.get("page_id"),
                    "pointer": pointer,
                    "visible": payload.get("visible", True),
                    "color": payload.get("color"),
                    "width": payload.get("width") or payload.get("size"),
                    "is_start": bool(payload.get("is_start")),
                    "is_hover": bool(payload.get("is_hover")),
                },
                room=_room(lesson_id),
                namespace="/lesson",
                include_self=False,
            )
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
            role = (_lesson_presence.get(lesson_id, {}).get(current_user.id) or {}).get("role")
            if not role:
                _lesson, role = __import__("app.lessons.routes", fromlist=["_whiteboard_access"])._whiteboard_access(lesson_id)
            if role not in ("teacher", "student"):
                return
            if role == "student" and _room_control(lesson_id).get("student_editing") is False:
                return
            camera = payload.get("camera") if isinstance(payload.get("camera"), dict) else {}
            outgoing = {
                "lesson_id": lesson_id,
                "client_id": payload.get("client_id"),
                "page_id": str(payload.get("page_id") or "")[:96],
                "frame_id": payload.get("frame_id"),
                "seq": int(payload.get("seq") or 0),
                "camera": {
                    "pan_x": max(-100000, min(100000, float(camera.get("pan_x") or 0))),
                    "pan_y": max(-100000, min(100000, float(camera.get("pan_y") or 0))),
                    "scale": max(.35, min(2.5, float(camera.get("scale") or 1))),
                },
            }
            _lesson_camera_state[lesson_id] = outgoing
            socketio.emit("whiteboard_live_camera", outgoing, room=_room(lesson_id), namespace="/lesson", include_self=False)
        except Exception as error:
            logger.warning("whiteboard_live_camera failed: %s", error)

    @socketio.on("whiteboard_viewport", namespace="/lesson")
    def _on_whiteboard_viewport(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        try:
            payload = data or {}
            lesson_id = int(payload.get("lesson_id"))
            identity = _lesson_presence.get(lesson_id, {}).get(current_user.id)
            if not identity:
                _whiteboard_access = __import__("app.lessons.routes", fromlist=["_whiteboard_access"])._whiteboard_access
                _whiteboard_access(lesson_id)
                identity = _lesson_presence.get(lesson_id, {}).get(current_user.id, {})
            role = identity.get("role", "student")
            name = identity.get("name") or getattr(current_user, "username", None) or "Участник"
            color = identity.get("color") or _pointer_colors[int(current_user.id) % len(_pointer_colors)]
            outgoing = {
                "lesson_id": lesson_id,
                "user_id": current_user.id,
                "role": role,
                "name": name,
                "color": color,
                "page_id": str(payload.get("page_id") or "")[:96],
                "mode": str(payload.get("mode") or "board")[:16],
                "viewport": {
                    "world_x": float(payload.get("world_x") or 0),
                    "world_y": float(payload.get("world_y") or 0),
                    "world_w": max(10, float(payload.get("world_w") or 100)),
                    "world_h": max(10, float(payload.get("world_h") or 100)),
                },
                "updated_at": int(time() * 1000),
            }
            socketio.emit("whiteboard_viewport", outgoing, room=_room(lesson_id), namespace="/lesson", include_self=False)
        except Exception as error:
            logger.warning("whiteboard_viewport failed: %s", error)

    @socketio.on("whiteboard_reaction", namespace="/lesson")
    def _on_whiteboard_reaction(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        try:
            lesson_id = int((data or {}).get("lesson_id"))
            from flask_socketio import join_room
            join_room(_room(lesson_id))
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
