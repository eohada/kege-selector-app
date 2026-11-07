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


def _teacher_room(lesson_id: int) -> str:
    return f"lesson:{lesson_id}:teachers"


def _student_room(lesson_id: int) -> str:
    return f"lesson:{lesson_id}:students"


LESSON_CACHE_TTL = 7 * 86400  # 7 days


def _code_state_key(lesson_id: int, page_id: str | None = None) -> str:
    if page_id:
        return f"boostudy:lesson:{lesson_id}:page:{page_id}:code_state"
    return f"boostudy:lesson:{lesson_id}:code_state"


def _get_code_state_cache(lesson_id: int, page_id: str | None = None) -> dict[str, Any] | None:
    if page_id:
        return _lesson_code_state.get((lesson_id, str(page_id)))
    return _lesson_code_state.get((lesson_id, None)) or _lesson_code_state.get(lesson_id)


def _set_code_state_cache(lesson_id: int, state_or_page: Any, state: dict[str, Any] | None = None, page_id: str | None = None) -> None:
    if state is None and isinstance(state_or_page, dict):
        actual_state = state_or_page
        actual_page = page_id
    elif isinstance(state, dict):
        actual_page = state_or_page
        actual_state = state
    else:
        actual_state = state_or_page if isinstance(state_or_page, dict) else (state or {})
        actual_page = page_id or (state_or_page if isinstance(state_or_page, str) else None)

    _lesson_code_state[(lesson_id, str(actual_page) if actual_page else None)] = actual_state
    if not actual_page or str(actual_page) == 'page_1':
        _lesson_code_state[lesson_id] = actual_state


def _board_state_key(lesson_id: int) -> str:
    return f"boostudy:lesson:{lesson_id}:board_state"


def _room_ui_key(lesson_id: int) -> str:
    return f"boostudy:lesson:{lesson_id}:room_ui"


def _presence_key(lesson_id: int) -> str:
    return f"boostudy:lesson:{lesson_id}:presence"


def _connections_key(lesson_id: int, user_id: int) -> str:
    return f"boostudy:lesson:{lesson_id}:connections:{user_id}"


def _prune_stale_connections(lesson_id: int) -> list[dict[str, Any]]:
    presence, _ = _prune_stale_connections_with_status(lesson_id)
    return presence


def _prune_stale_connections_with_status(lesson_id: int) -> tuple[list[dict[str, Any]], bool]:
    from app.runtime_state import hgetall_json, smembers, srem, scard, hdel, is_connection_lease_active
    all_users = hgetall_json(_presence_key(lesson_id))
    if not all_users:
        return list(_lesson_presence.get(lesson_id, {}).values()), False

    modified = False
    for uid_str in list(all_users.keys()):
        if not str(uid_str).isdigit():
            continue
        uid = int(uid_str)
        conn_sids = smembers(_connections_key(lesson_id, uid))
        if conn_sids:
            for sid in conn_sids:
                if not is_connection_lease_active(sid):
                    srem(_connections_key(lesson_id, uid), sid)
                    modified = True
            rem = scard(_connections_key(lesson_id, uid))
            if rem == 0:
                hdel(_presence_key(lesson_id), uid_str)
                all_users.pop(uid_str, None)
                if lesson_id in _lesson_presence:
                    _lesson_presence[lesson_id].pop(uid, None)
                modified = True
        else:
            hdel(_presence_key(lesson_id), uid_str)
            all_users.pop(uid_str, None)
            if lesson_id in _lesson_presence:
                _lesson_presence[lesson_id].pop(uid, None)
            modified = True

    if modified and lesson_id in _lesson_presence:
        current_uids = {int(k) for k in all_users.keys() if str(k).isdigit()}
        for stale_uid in list(_lesson_presence[lesson_id].keys()):
            if stale_uid not in current_uids:
                _lesson_presence[lesson_id].pop(stale_uid, None)
    return list(all_users.values()), modified


def _register_user_presence(lesson_id: int, user_id: int, sid: str, presence_info: dict[str, Any]) -> list[dict[str, Any]]:
    from app.runtime_state import sadd, hset_json, set_connection_lease
    set_connection_lease(sid, {"user_id": user_id, "lesson_id": lesson_id}, ttl_seconds=30)
    sadd(_connections_key(lesson_id, user_id), sid, ttl_seconds=LESSON_CACHE_TTL)
    hset_json(_presence_key(lesson_id), str(user_id), presence_info, ttl_seconds=LESSON_CACHE_TTL)
    _lesson_presence.setdefault(lesson_id, {})[user_id] = presence_info
    return _prune_stale_connections(lesson_id)


def _unregister_user_presence(lesson_id: int, user_id: int, sid: str) -> tuple[list[dict[str, Any]], bool]:
    from app.runtime_state import srem, scard, hdel, delete_connection_lease
    delete_connection_lease(sid)
    srem(_connections_key(lesson_id, user_id), sid)
    rem_count = scard(_connections_key(lesson_id, user_id))
    if rem_count == 0:
        hdel(_presence_key(lesson_id), str(user_id))
        if lesson_id in _lesson_presence:
            _lesson_presence[lesson_id].pop(user_id, None)

    presence_list = _prune_stale_connections(lesson_id)
    return presence_list, len(presence_list) == 0


def _get_active_presence(lesson_id: int) -> list[dict[str, Any]]:
    return _prune_stale_connections(lesson_id)


def _get_all_room_ui(lesson_id: int) -> list[dict[str, Any]]:
    from app.runtime_state import hgetall_json
    redis_ui = hgetall_json(_room_ui_key(lesson_id))
    if redis_ui:
        _lesson_room_ui[lesson_id] = redis_ui
        return list(redis_ui.values())
    return list(_lesson_room_ui.get(lesson_id, {}).values())


def _save_room_ui_state(lesson_id: int, state_key: str, payload: dict[str, Any]) -> None:
    from app.runtime_state import hset_json
    _lesson_room_ui.setdefault(lesson_id, {})[state_key] = payload
    hset_json(_room_ui_key(lesson_id), state_key, payload, ttl_seconds=LESSON_CACHE_TTL)


def _remove_room_ui_state(lesson_id: int, state_key: str) -> None:
    from app.runtime_state import hdel
    _lesson_room_ui.setdefault(lesson_id, {}).pop(state_key, None)
    hdel(_room_ui_key(lesson_id), state_key)


def _get_room_ui_state(lesson_id: int, state_key: str) -> dict[str, Any] | None:
    from app.runtime_state import hget_json
    val = hget_json(_room_ui_key(lesson_id), state_key)
    if isinstance(val, dict):
        return val
    return _lesson_room_ui.get(lesson_id, {}).get(state_key)


def _remove_all_room_ui(lesson_id: int) -> None:
    from app.runtime_state import delete as redis_del
    _lesson_room_ui.pop(lesson_id, None)
    redis_del(_room_ui_key(lesson_id))


def _get_lesson_auth(lesson_id: int) -> tuple[Any, str | None]:
    """Returns (lesson, role) if authenticated user has access to lesson, else (None, None)."""
    try:
        from app.lessons.routes import _whiteboard_access
        return _whiteboard_access(int(lesson_id))
    except Exception:
        return None, None


def _get_banned_participants(lesson_id: int) -> list[dict[str, Any]]:
    try:
        from core.db_models import LessonParticipantBan, User
        from app.models import UserProfile, Student
        bans = (
            LessonParticipantBan.query.filter_by(lesson_id=int(lesson_id), is_active=True)
            .order_by(LessonParticipantBan.banned_at.desc())
            .all()
        )
        res = []
        for b in bans:
            u = User.query.get(b.user_id)
            name = ""
            if u:
                st = Student.query.filter_by(user_id=u.id).first()
                prof = UserProfile.query.filter_by(user_id=u.id).first()
                if st and st.name:
                    name = st.name
                elif prof:
                    name = f"{prof.first_name or ''} {prof.last_name or ''}".strip()
                if not name:
                    name = u.username or f"User #{b.user_id}"
            res.append({
                "user_id": b.user_id,
                "name": name or f"User #{b.user_id}",
                "banned_at": b.banned_at.isoformat() if b.banned_at else None,
                "reason": getattr(b, "reason", None) or "Исключён преподавателем",
            })
        return res
    except Exception as e:
        logger.warning("_get_banned_participants error for lesson %s: %s", lesson_id, e)
        return []


def _presence_payload(lesson_id: int, presence_list: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if presence_list is None:
        presence_list = _prune_stale_connections(lesson_id)
    return {
        "lesson_id": int(lesson_id),
        "presence": presence_list,
        "banned": _get_banned_participants(lesson_id),
    }


def emit_lesson_presence(lesson_id: int) -> None:
    try:
        from flask import current_app
        sio = getattr(current_app, "socketio", None) or globals().get("socketio")
        if sio:
            sio.emit(
                "lesson_presence",
                _presence_payload(lesson_id),
                room=_room(lesson_id),
                namespace="/lesson",
            )
    except Exception as e:
        logger.warning("emit_lesson_presence failed for lesson %s: %s", lesson_id, e)


def _load_cached_board_data(lesson_id: int) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    from app.runtime_state import get_json, set_json
    redis_board = get_json(_board_state_key(lesson_id))
    if isinstance(redis_board, dict) and ("strokes" in redis_board or "pages" in redis_board):
        strokes = dict(redis_board.get("strokes") or {})
        pages = list(redis_board.get("pages") or [{"id": "page_1", "title": "Страница 1", "background": "dots"}])
        active = str(redis_board.get("active_page_id") or "page_1")
        _lesson_board_strokes[lesson_id] = strokes
        _lesson_board_pages[lesson_id] = pages
        _lesson_board_active_page[lesson_id] = active
        return strokes, pages, active

    if lesson_id not in _lesson_board_strokes:
        _lesson_board_strokes[lesson_id] = {}
        _lesson_board_pages[lesson_id] = [{"id": "page_1", "title": "Страница 1", "background": "dots"}]
        _lesson_board_active_page[lesson_id] = "page_1"

        def _fetch_board():
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
                tombstones = board.get("tombstones") or []
                if isinstance(tombstones, list) and tombstones:
                    _record_stroke_tombstones(lesson_id, [str(t) for t in tombstones])
                rev = int(board.get("revision") or 0)
                from app.runtime_state import get_redis_client, _state_lock, _memory_store
                client = get_redis_client()
                if client is not None:
                    try:
                        cur_rev = client.get(f"boostudy:board:{lesson_id}:rev")
                        if cur_rev is None or int(cur_rev) < rev:
                            client.set(f"boostudy:board:{lesson_id}:rev", rev)
                    except Exception:
                        pass
                with _state_lock:
                    mem_rev = int(_memory_store.get(f"boostudy:board:{lesson_id}:rev") or 0)
                    if mem_rev < rev:
                        _memory_store[f"boostudy:board:{lesson_id}:rev"] = rev
                set_json(_board_state_key(lesson_id), {
                    "strokes": _lesson_board_strokes[lesson_id],
                    "pages": _lesson_board_pages[lesson_id],
                    "active_page_id": _lesson_board_active_page[lesson_id],
                }, ttl_seconds=LESSON_CACHE_TTL)

        try:
            from flask import current_app
            if not current_app and _flask_app:
                with _flask_app.app_context():
                    _fetch_board()
            else:
                _fetch_board()
        except Exception as e:
            logger.warning("Error loading cached board data for lesson %s: %s", lesson_id, e)
    return (
        _lesson_board_strokes[lesson_id],
        _lesson_board_pages.get(lesson_id) or [{"id": "page_1", "title": "Страница 1", "background": "dots"}],
        _lesson_board_active_page.get(lesson_id) or "page_1",
    )


def _sync_cached_board_to_redis(lesson_id: int) -> None:
    from app.runtime_state import set_json
    try:
        set_json(_board_state_key(lesson_id), {
            "strokes": _lesson_board_strokes.get(lesson_id, {}),
            "pages": _lesson_board_pages.get(lesson_id) or [{"id": "page_1", "title": "Страница 1", "background": "dots"}],
            "active_page_id": _lesson_board_active_page.get(lesson_id) or "page_1",
        }, ttl_seconds=LESSON_CACHE_TTL)
    except Exception as e:
        logger.warning("Error syncing board state to Redis for lesson %s: %s", lesson_id, e)


def _load_cached_board_strokes(lesson_id: int) -> dict[str, Any]:
    return _load_cached_board_data(lesson_id)[0]


def _load_cached_board_pages(lesson_id: int) -> list[dict[str, Any]]:
    return _load_cached_board_data(lesson_id)[1]


def _load_cached_board_active_page(lesson_id: int) -> str:
    return _load_cached_board_data(lesson_id)[2]


_lesson_board_tombstones: dict[int, set[str]] = {}


def _board_tombstones_key(lesson_id: int) -> str:
    return f"boostudy:board:{lesson_id}:tombstones"


def _is_stroke_tombstoned(lesson_id: int, stroke_id: str) -> bool:
    if not stroke_id:
        return False
    if stroke_id in _lesson_board_tombstones.get(lesson_id, set()):
        return True
    from app.runtime_state import smembers
    tombstones = smembers(_board_tombstones_key(lesson_id))
    if tombstones and stroke_id in tombstones:
        _lesson_board_tombstones.setdefault(lesson_id, set()).add(stroke_id)
        return True
    # If not in cache or Redis, verify durable database snapshot
    try:
        from app.models import Lesson
        lesson = Lesson.query.get(lesson_id)
        if lesson:
            from app.lessons.routes import _lesson_studio_state
            state = _lesson_studio_state(lesson)
            db_tombstones = set((state.get("board") or {}).get("tombstones") or [])
            if stroke_id in db_tombstones:
                _record_stroke_tombstones(lesson_id, [stroke_id])
                return True
    except Exception:
        pass
    return False


def _record_stroke_tombstones(lesson_id: int, stroke_ids: list[str]) -> None:
    if not stroke_ids:
        return
    _lesson_board_tombstones.setdefault(lesson_id, set()).update(str(s) for s in stroke_ids)
    from app.runtime_state import sadd
    sadd(_board_tombstones_key(lesson_id), *[str(s) for s in stroke_ids], ttl_seconds=LESSON_CACHE_TTL)


def _get_db_board_revision(lesson_id: int) -> int:
    try:
        from app.models import Lesson
        lesson = Lesson.query.get(lesson_id)
        if lesson:
            from app.lessons.routes import _lesson_studio_state
            state = _lesson_studio_state(lesson)
            return int((state.get("board") or {}).get("revision") or 0)
    except Exception:
        pass
    return 0


def _next_board_revision(lesson_id: int) -> int:
    from app.runtime_state import get_redis_client, _state_lock, _memory_store
    rev_key = f"boostudy:board:{lesson_id}:rev"
    client = get_redis_client()
    if client is not None:
        try:
            if not client.exists(rev_key):
                base_rev = _get_db_board_revision(lesson_id)
                client.set(rev_key, base_rev)
            return int(client.incr(rev_key))
        except Exception:
            pass
    with _state_lock:
        if rev_key not in _memory_store:
            base_rev = _get_db_board_revision(lesson_id)
            _memory_store[rev_key] = base_rev
        cur = int(_memory_store.get(rev_key) or 0) + 1
        _memory_store[rev_key] = cur
        return cur


_flask_app = None
_socketio_instance = None
_lesson_persist_timers: dict[int, Any] = {}
_lesson_persist_lock = RLock()
_lesson_code_persist_timers: dict[int, Any] = {}
_lesson_code_persist_lock = RLock()


def _lock_and_get_lesson(lesson_id: int):
    from app.models import Lesson, db
    query = db.session.query(Lesson).filter(Lesson.lesson_id == lesson_id)
    try:
        bind = db.session.get_bind()
        if bind and bind.dialect.name == "postgresql":
            query = query.with_for_update()
    except Exception:
        pass
    return query.first()


def emit_lesson_code_persisted(lesson_id: int, payload: dict) -> None:
    try:
        from flask import current_app
        sio = getattr(current_app, "socketio", None) or _socketio_instance
        if sio:
            sio.emit("lesson_code_persisted", payload, room=_room(lesson_id), namespace="/lesson")
    except Exception as e:
        logger.warning("emit_lesson_code_persisted failed: %s", e)


def _schedule_persist_cached_code_state(lesson_id: int, page_id: str | None = None, delay: float = 1.0) -> None:
    from threading import Timer
    timer_key = (lesson_id, str(page_id) if page_id else None)
    with _lesson_code_persist_lock:
        existing = _lesson_code_persist_timers.get(timer_key)
        if existing:
            try:
                existing.cancel()
            except Exception:
                pass
        t = Timer(delay, _persist_cached_code_state, args=[lesson_id, page_id])
        t.daemon = True
        _lesson_code_persist_timers[timer_key] = t
        t.start()


def _load_cached_code_state(lesson_id: int, page_id: str | None = None) -> dict[str, Any] | None:
    from app.runtime_state import get_json, set_json, get_dirty_code
    ckey = _code_state_key(lesson_id, page_id)
    redis_state = get_json(ckey)
    if isinstance(redis_state, dict) and redis_state:
        _set_code_state_cache(lesson_id, page_id, redis_state)
        dirty = get_dirty_code(lesson_id)
        if dirty and dirty.get("revision"):
            _schedule_persist_cached_code_state(lesson_id, page_id=page_id, delay=0.5)
        return redis_state

    cached = _get_code_state_cache(lesson_id, page_id)
    if cached:
        return cached

    def _fetch():
        from app.models import Lesson
        lesson = Lesson.query.get(lesson_id)
        if lesson:
            summaries = getattr(lesson, "review_summaries", None) or {}
            page_workspaces = summaries.get("_os_page_workspaces") or {}
            stored = None
            if page_id and page_id in page_workspaces:
                stored = page_workspaces[page_id]
            elif not page_id or str(page_id) == "page_1":
                stored = summaries.get("_os_workspace")
            elif summaries.get("_os_workspace"):
                board_doc = getattr(getattr(lesson, "whiteboard", None), "document_state", None) or {}
                pages = board_doc.get("pages") or []
                if pages and pages[0].get("id") == str(page_id):
                    stored = summaries.get("_os_workspace")

            if not stored:
                stored = {
                    "files": {"main.py": ""},
                    "open_tabs": ["main.py"],
                    "active_file": "main.py",
                    "code": "",
                    "file_name": "main.py",
                    "revision": 1,
                    "version": 1,
                }

            if isinstance(stored, dict) and stored:
                raw_files = stored.get("files")
                files_dict: dict[str, str] = {}
                if isinstance(raw_files, dict) and raw_files:
                    files_dict = {str(k)[:120]: str(v)[:100000] for k, v in raw_files.items()}
                elif stored.get("code") is not None:
                    fname = str(stored.get("file_name") or "main.py")[:120]
                    files_dict[fname] = str(stored.get("code") or "")[:100000]

                if not files_dict:
                    files_dict["main.py"] = ""

                raw_tabs = stored.get("open_tabs")
                open_tabs: list[str] = []
                if isinstance(raw_tabs, list) and raw_tabs:
                    open_tabs = [str(t)[:120] for t in raw_tabs if str(t)[:120] in files_dict]
                if not open_tabs:
                    open_tabs = list(files_dict.keys())[:1]

                active_file = str(stored.get("active_file") or stored.get("file_name") or open_tabs[0])[:120]
                deleted_files = list(stored.get("deleted_files") or [])
                for df in deleted_files:
                    files_dict.pop(df, None)
                    if df in open_tabs:
                        open_tabs.remove(df)
                if not files_dict:
                    files_dict["main.py"] = ""
                if not open_tabs:
                    open_tabs = ["main.py"]
                if active_file not in files_dict:
                    active_file = open_tabs[0]

                rev = int(stored.get("revision") or stored.get("version") or 1)
                state = {
                    "file_name": active_file,
                    "code": files_dict.get(active_file, ""),
                    "files": files_dict,
                    "open_tabs": open_tabs,
                    "active_file": active_file,
                    "deleted_files": deleted_files,
                    "revision": rev,
                    "version": rev,
                    "page_id": str(page_id) if page_id else None,
                    "updated_at": stored.get("updated_at") or int(time() * 1000),
                    "last_modified_by": stored.get("last_modified_by"),
                }
                _set_code_state_cache(lesson_id, page_id, state)
                set_json(ckey, state, ttl_seconds=LESSON_CACHE_TTL)
                return state
        return None

    try:
        from flask import current_app
        if not current_app and _flask_app:
            with _flask_app.app_context():
                return _fetch()
        else:
            return _fetch()
    except Exception as e:
        logger.warning("Error loading cached code state for lesson %s page %s: %s", lesson_id, page_id, e)
    return _get_code_state_cache(lesson_id, page_id)


def _update_cached_code_state(lesson_id: int, state: dict[str, Any], page_id: str | None = None) -> None:
    from app.runtime_state import set_json
    p_id = str(page_id) if page_id else state.get("page_id")
    _set_code_state_cache(lesson_id, p_id, state)
    set_json(_code_state_key(lesson_id, p_id), state, ttl_seconds=LESSON_CACHE_TTL)


def _persist_cached_code_state(lesson_id: int, page_id: str | None = None) -> None:
    timer_key = (lesson_id, str(page_id) if page_id else None)
    with _lesson_code_persist_lock:
        _lesson_code_persist_timers.pop(timer_key, None)
        _lesson_code_persist_timers.pop(lesson_id, None)

    def _do_persist():
        try:
            from app.models import Lesson, db
            from sqlalchemy.orm.attributes import flag_modified
            operation_lock = _lesson_operation_locks.setdefault(lesson_id, RLock())
            with operation_lock:
                state = _get_code_state_cache(lesson_id, page_id)
                if not state:
                    return
                lesson = _lock_and_get_lesson(lesson_id)
                if not lesson:
                    return
                summaries = dict(getattr(lesson, "review_summaries", None) or {})
                active_file = str(state.get("active_file") or state.get("file_name") or "main.py")[:120]
                files_dict = dict(state.get("files") or {})
                if active_file not in files_dict and "code" in state:
                    files_dict[active_file] = state["code"]
                open_tabs = list(state.get("open_tabs") or [active_file])
                revision = int(state.get("revision") or state.get("version") or 1)

                page_workspaces = dict(summaries.get("_os_page_workspaces") or {})
                cur_page_ws = page_workspaces.get(str(page_id)) if page_id else summaries.get("_os_workspace") or {}
                db_rev = int((cur_page_ws or {}).get("revision") or (cur_page_ws or {}).get("version") or 0)
                if db_rev > revision:
                    logger.info("Persist skipped for lesson %s page %s: DB revision %s > cache revision %s", lesson_id, page_id, db_rev, revision)
                    return

                deleted_files = list(state.get("deleted_files") or [])
                workspace_data = {
                    "files": files_dict,
                    "deleted_files": deleted_files,
                    "open_tabs": open_tabs,
                    "active_file": active_file,
                    "code": files_dict.get(active_file, ""),
                    "file_name": active_file,
                    "revision": revision,
                    "version": revision,
                    "page_id": str(page_id) if page_id else None,
                    "updated_at": state.get("updated_at") or int(time() * 1000),
                    "last_modified_by": state.get("last_modified_by"),
                }
                if page_id:
                    page_workspaces[str(page_id)] = workspace_data
                    summaries["_os_page_workspaces"] = page_workspaces
                if not page_id or str(page_id) == "page_1":
                    summaries["_os_workspace"] = workspace_data

                lesson.review_summaries = summaries
                flag_modified(lesson, "review_summaries")
                db.session.commit()
                from app.runtime_state import clear_dirty_code
                clear_dirty_code(lesson_id, expected_revision=revision)
                logger.debug("Persisted code state for lesson %s page %s (rev %s, %s files)", lesson_id, page_id, revision, len(files_dict))

                emit_lesson_code_persisted(lesson_id, {
                    "lesson_id": lesson_id,
                    "page_id": str(page_id) if page_id else None,
                    "file_name": active_file,
                    "revision": revision,
                    "updated_at": workspace_data.get("updated_at"),
                    "status": "saved",
                    "durable": True,
                })
        except Exception as e:
            logger.warning("Error persisting cached code state for lesson %s page %s: %s", lesson_id, page_id, e)

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
        except Exception as e:
            logger.warning("Error persisting cached code state outside app context for lesson %s page %s: %s", lesson_id, page_id, e)
        except Exception:
            _do_persist()


def _revalidate_distributed_state(lesson_id: int) -> None:
    """
    Called when Redis connectivity is restored.
    Compares PostgreSQL state with Redis state, reconciles without letting stale state
    overwrite newer state, clears dirty flags conditionally, and broadcasts lesson_sync_restored.
    """
    from app.runtime_state import is_distributed_runtime_healthy, set_json, get_json, clear_dirty_code
    if not is_distributed_runtime_healthy():
        return

    def _do_revalidate():
        from app.models import Lesson
        lesson = Lesson.query.get(lesson_id)
        if not lesson:
            return
        summaries = getattr(lesson, "review_summaries", None) or {}
        stored = summaries.get("_os_workspace") or {}
        db_rev = int(stored.get("revision") or stored.get("version") or 0)

        redis_state = get_json(_code_state_key(lesson_id)) or {}
        redis_rev = int(redis_state.get("revision") or redis_state.get("version") or 0)

        if db_rev >= redis_rev and db_rev > 0:
            # DB is authoritative or newer (e.g. teacher saved while Redis was degraded)
            authoritative_state = stored
            set_json(_code_state_key(lesson_id), authoritative_state, ttl_seconds=LESSON_CACHE_TTL)
            _lesson_code_state[lesson_id] = authoritative_state
            clear_dirty_code(lesson_id, expected_revision=db_rev)
        elif redis_rev > db_rev:
            # Redis is newer: do not clobber newer Redis state with older DB state
            authoritative_state = redis_state
            _lesson_code_state[lesson_id] = authoritative_state
            _schedule_persist_cached_code_state(lesson_id, delay=0.1)
        else:
            authoritative_state = redis_state or stored
            if authoritative_state:
                _lesson_code_state[lesson_id] = authoritative_state

        if authoritative_state:
            try:
                from flask import current_app
                sio = getattr(current_app, "socketio", None) or _socketio_instance
                if sio:
                    sio.emit("lesson_sync_restored", {
                        "lesson_id": lesson_id,
                        "revision": authoritative_state.get("revision", 1),
                        "message": "Распределённая синхронизация восстановлена. Состояние актуализировано.",
                    }, room=_room(lesson_id), namespace="/lesson")
                    sio.emit("lesson_code_snapshot", {"lesson_id": lesson_id, **authoritative_state}, room=_room(lesson_id), namespace="/lesson")
            except Exception as e:
                logger.warning("Error emitting lesson_sync_restored: %s", e)

    try:
        from flask import current_app
        if not current_app and _flask_app:
            with _flask_app.app_context():
                _do_revalidate()
        else:
            _do_revalidate()
    except Exception as e:
        logger.warning("Error in _revalidate_distributed_state for lesson %s: %s", lesson_id, e)


def _schedule_persist_cached_board_strokes(lesson_id: int, delay: float = 1.2) -> None:
    _sync_cached_board_to_redis(lesson_id)
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
            from app.lessons.lesson_socket import _lock_and_get_lesson, _lesson_operation_locks
            from sqlalchemy.orm.attributes import flag_modified

            operation_lock = _lesson_operation_locks.setdefault(lesson_id, RLock())
            with operation_lock:
                target_lesson = _lock_and_get_lesson(lesson_id)
                if not target_lesson:
                    target_lesson = Lesson.query.get(lesson_id)
                if target_lesson:
                    from app.lessons.routes import (
                        _lesson_studio_state,
                        _lesson_studio_state_for_viewer,
                    )
                    summaries = dict(getattr(target_lesson, "review_summaries", None) or {})
                    state = dict(summaries.get("_studio") or {})
                    strokes = list(_lesson_board_strokes.get(lesson_id, {}).values())
                    pages = _lesson_board_pages.get(lesson_id) or [{"id": "page_1", "title": "Страница 1", "background": "dots"}]
                    active_page_id = _lesson_board_active_page.get(lesson_id) or "page_1"
                    board = dict(state.get("board") or {})
                    rev = int(board.get("revision") or 0) + 1
                    tombstones = list(_lesson_board_tombstones.get(lesson_id, set()))

                    state["board"] = {
                        "strokes": strokes,
                        "pages": pages,
                        "active_page_id": active_page_id,
                        "tombstones": tombstones,
                        "revision": rev,
                        "updated_at": moscow_now().isoformat(),
                    }
                    summaries["_studio"] = state
                    target_lesson.review_summaries = summaries
                    flag_modified(target_lesson, "review_summaries")

                    # Keep LessonWhiteboard synchronized in the exact same atomic transaction with PostgreSQL row locking
                    try:
                        from app.models import LessonWhiteboard
                        from app.lessons.whiteboard_service import convert_v2_board_to_document, default_document
                        bind = db.session.get_bind()
                        wb_query = db.session.query(LessonWhiteboard).filter(LessonWhiteboard.lesson_id == lesson_id)
                        if bind and bind.dialect.name == "postgresql":
                            wb_query = wb_query.with_for_update()
                        wb = wb_query.first()
                        if wb is None:
                            wb = LessonWhiteboard(
                                lesson_id=lesson_id,
                                miro_board_id=f"local-{lesson_id}",
                                board_name=f"Комната урока #{lesson_id}",
                                provider="boostudy",
                                document_state=default_document(),
                                document_version=0,
                                is_active=True,
                                allow_student_edit=True,
                            )
                            db.session.add(wb)
                        wb.document_state = convert_v2_board_to_document(strokes, pages, active_page_id, include_teacher=True)
                        wb.document_version = rev
                        wb.updated_at = moscow_now()
                    except Exception as wb_err:
                        logger.warning("Error syncing LessonWhiteboard for lesson %s: %s", lesson_id, wb_err)

                    db.session.commit()

                    emit_lesson_studio_updated(
                        target_lesson.lesson_id,
                        _lesson_studio_state_for_viewer(state, is_teacher=False),
                        status=getattr(target_lesson, "status", None),
                    )
                    emit_lesson_private_note_updated(target_lesson.lesson_id, state.get("teacher_private_note") or "")
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
    if cached and now - cached[0] < 5.0:
        ctrl = dict(cached[1])
    else:
        try:
            from app.lessons.whiteboard_service import get_or_create_board, normalize_document
            from app.models import db
            db.session.expire_all()
            board = get_or_create_board(lesson_id)
            ctrl = dict(normalize_document(board.document_state).get("presentation", {}).get("control", {}))
            _lesson_control_cache[lesson_id] = (now, dict(ctrl))
        except Exception:
            ctrl = {}
    ctrl = dict(ctrl)
    freeze_state = _get_room_ui_state(lesson_id, "freeze")
    if isinstance(freeze_state, dict) and (freeze_state.get("is_frozen") or freeze_state.get("freeze_student")):
        ctrl["freeze_student"] = True
        ctrl["is_frozen"] = True
    else:
        ctrl["freeze_student"] = False
        ctrl["is_frozen"] = False
    return ctrl


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


def _utf16_to_py_offset(s: str, utf16_idx: int) -> int:
    b = s.encode("utf-16-le")
    byte_offset = min(len(b), max(0, utf16_idx * 2))
    return len(b[:byte_offset].decode("utf-16-le", errors="ignore"))


def _py_to_utf16_offset(s: str, py_idx: int) -> int:
    sub = s[:max(0, py_idx)]
    return len(sub.encode("utf-16-le")) // 2


def _ot_transform_position(pos: int, op: dict[str, Any], is_tie_breaker: bool = False) -> int:
    s = int(op.get("start") or 0)
    e = int(op.get("end") or s)
    ins_len = len(str(op.get("inserted") or ""))
    del_len = max(0, e - s)
    delta = ins_len - del_len
    if pos < s:
        return pos
    if pos > e:
        return max(0, pos + delta)
    if pos == s:
        return s + ins_len if is_tie_breaker else s
    return s + ins_len


def _ot_transform_op(op_to_transform: dict[str, Any], concurrent_op: dict[str, Any], is_tie_breaker: bool = False) -> dict[str, Any]:
    s1 = int(op_to_transform.get("start") or 0)
    e1 = int(op_to_transform.get("end") or s1)
    s2 = int(concurrent_op.get("start") or 0)
    e2 = int(concurrent_op.get("end") or s2)
    ins2_len = len(str(concurrent_op.get("inserted") or ""))
    del2_len = max(0, e2 - s2)
    delta2 = ins2_len - del2_len

    if e1 <= s2:
        if e1 == s2 and s1 == e1 and s2 == e2 and is_tie_breaker:
            return {"start": s1 + ins2_len, "end": e1 + ins2_len, "inserted": op_to_transform.get("inserted", "")}
        return {"start": s1, "end": e1, "inserted": op_to_transform.get("inserted", "")}
    if s1 >= e2:
        return {"start": max(0, s1 + delta2), "end": max(0, e1 + delta2), "inserted": op_to_transform.get("inserted", "")}

    new_s = s1 if s1 < s2 else s2 + ins2_len
    new_e = max(0, e1 + delta2) if e1 > e2 else s2 + ins2_len
    if new_e < new_s:
        new_e = new_s
    return {"start": new_s, "end": new_e, "inserted": op_to_transform.get("inserted", "")}


def is_user_banned_from_lesson(lesson_id: int, user_id: int) -> bool:
    """Check if user has an active ban from this lesson in Redis or DB."""
    try:
        from app.runtime_state import get_redis_client
        client = get_redis_client()
        if client:
            if bool(client.sismember(f"lesson:{lesson_id}:banned_users", str(user_id))):
                return True
    except Exception:
        pass
    try:
        from core.db_models import LessonParticipantBan
        ban = LessonParticipantBan.query.filter_by(
            lesson_id=int(lesson_id),
            user_id=int(user_id),
            is_active=True,
        ).first()
        if ban:
            try:
                from app.runtime_state import get_redis_client
                client = get_redis_client()
                if client:
                    client.sadd(f"lesson:{lesson_id}:banned_users", str(user_id))
            except Exception:
                pass
            return True
    except Exception:
        pass
    return False


def register_lesson_socket(socketio, app=None) -> None:
    global _flask_app, _socketio_instance
    _socketio_instance = socketio
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
            if is_current_connection or uid in users:
                presence_list, is_empty = _unregister_user_presence(lid, uid, request.sid)
                _lesson_control_cache.pop(lid, None)
                socketio.emit(
                    "lesson_presence",
                    _presence_payload(lid, presence_list),
                    room=_room(lid),
                    namespace="/lesson",
                )
                if is_empty:
                    _remove_all_room_ui(lid)
                    _persist_cached_code_state(lid)
                    _persist_cached_board_strokes(lid)
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
        lesson, role = _get_lesson_auth(lesson_id)
        if not lesson or not role:
            return
        room = _room(lesson_id)
        from flask_socketio import join_room, leave_room
        # One browser connection represents one active lesson room. Leaving an old
        # room prevents presence and transient events leaking after navigation.
        for previous_lesson_id, users in list(_lesson_presence.items()):
            if previous_lesson_id == lesson_id or current_user.id not in users:
                continue
            leave_room(_room(previous_lesson_id))
            leave_room(_teacher_room(previous_lesson_id))
            leave_room(_student_room(previous_lesson_id))
            previous_strokes = _live_strokes.get(previous_lesson_id, {})
            for stroke_key in [key for key in previous_strokes if key.startswith(f"{current_user.id}:")]:
                previous_strokes.pop(stroke_key, None)
            if not previous_strokes:
                _live_strokes.pop(previous_lesson_id, None)
            presence_list, _ = _unregister_user_presence(previous_lesson_id, current_user.id, request.sid)
            _lesson_control_cache.pop(previous_lesson_id, None)
            socketio.emit(
                "lesson_presence",
                _presence_payload(previous_lesson_id, presence_list),
                room=_room(previous_lesson_id),
                namespace="/lesson",
            )
        join_room(room)
        join_room(f"lesson_{lesson_id}_user_{current_user.id}")
        if role == "teacher":
            join_room(_teacher_room(lesson_id))
        else:
            join_room(_student_room(lesson_id))
        if current_user.is_student() and getattr(lesson, 'student', None):
            if not getattr(lesson, 'student_late', False):
                try:
                    from app.utils.achievement_service import grant_achievement
                    grant_achievement(lesson.student, 'lesson_on_time', commit=True)
                except Exception:
                    pass
        uinfo = _resolve_user_presence_info(current_user)
        presence_info = {
            "user_id": current_user.id,
            "sid": request.sid,
            "tab": "theory",
            "role": role,
            "name": uinfo["name"],
            "school_class": uinfo["school_class"],
            "color": _pointer_colors[int(current_user.id) % len(_pointer_colors)],
            "client_id": None,
            "page_id": None,
            "follow": False,
        }
        # Зарегистрировать в распределённом хранилище и локальной памяти
        presence_list = _register_user_presence(lesson_id, current_user.id, request.sid, presence_info)
        # Отправить текущему клиенту список присутствующих и их вкладки
        socketio.emit("lesson_presence", _presence_payload(lesson_id, presence_list), room=request.sid, namespace="/lesson")
        # Остальным в комнате — обновлённый список (включая нового участника)
        socketio.emit(
            "lesson_presence",
            _presence_payload(lesson_id, presence_list),
            room=room,
            namespace="/lesson",
            include_self=False,
        )
        # Воспроизвести текущее состояние интерфейса комнаты (окна, режимы)
        room_ui_list = _get_all_room_ui(lesson_id)
        for ui_payload in room_ui_list:
            if role != "teacher" and isinstance(ui_payload, dict):
                win_id = ui_payload.get("window_id")
                if win_id in {"teacher-task-bank-window", "teacher-notes-window", "lesson-info-window"}:
                    continue
            socketio.emit("lesson_room_ui_state", ui_payload, room=request.sid, namespace="/lesson")
        # Воспроизвести текущие штрихи и страницы доски
        board_strokes = list(_load_cached_board_strokes(lesson_id).values())
        if role != "teacher":
            board_strokes = [s for s in board_strokes if isinstance(s, dict) and s.get("layer") != "teacher"]
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
        uinfo = _resolve_user_presence_info(current_user)
        previous = _lesson_presence.get(lesson_id, {}).get(current_user.id, {})
        new_presence = {
            **previous,
            "user_id": current_user.id,
            "sid": request.sid,
            "tab": tab,
            "role": previous.get("role") or uinfo["role"],
            "name": uinfo["name"],
            "school_class": uinfo["school_class"],
            "color": previous.get("color") or _pointer_colors[int(current_user.id) % len(_pointer_colors)],
        }
        presence_list = _register_user_presence(lesson_id, current_user.id, request.sid, new_presence)
        socketio.emit(
            "lesson_presence",
            _presence_payload(lesson_id, presence_list),
            room=_room(lesson_id),
            namespace="/lesson",
        )

    @socketio.on("board_stroke", namespace="/lesson")
    def _on_board_stroke(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        lesson_id = (data or {}).get("lesson_id")
        stroke = (data or {}).get("stroke")
        if not lesson_id or not stroke or not isinstance(stroke, dict):
            return
        try:
            lesson_id = int(lesson_id)
        except (TypeError, ValueError):
            return
        lesson, role = _get_lesson_auth(lesson_id)
        if not lesson or not role or role == "parent":
            return

        stroke_layer = stroke.get("layer")
        if role != "teacher":
            from app.runtime_state import is_distributed_runtime_healthy, is_single_process_mode
            if not is_distributed_runtime_healthy() and not is_single_process_mode():
                socketio.emit("whiteboard_error", {
                    "message": "Синхронизация доски временно недоступна. Рисование ограничено во избежание split-brain."
                }, room=request.sid, namespace="/lesson")
                return
            control = _room_control(lesson_id)
            if control.get("freeze_student") or control.get("board_locked"):
                socketio.emit("whiteboard_error", {"message": "Рисование заблокировано преподавателем"}, room=request.sid, namespace="/lesson")
                return
            if stroke_layer == "teacher":
                stroke["layer"] = "student"
                stroke_layer = "student"

        stroke_id = str(stroke.get("id") or "")
        if stroke_id:
            if _is_stroke_tombstoned(lesson_id, stroke_id):
                return  # Dropped! Late or replayed packet cannot resurrect deleted object.

            if not stroke.get("page_id"):
                stroke["page_id"] = "page_1"
            if not stroke.get("userId") and not stroke.get("user_id"):
                stroke["userId"] = current_user.id
            cached = _load_cached_board_strokes(lesson_id)
            if stroke_id in cached:
                existing = cached[stroke_id]
                if role != "teacher" and existing.get("layer") == "teacher":
                    return
                cached[stroke_id] = {**existing, **stroke, "src": stroke.get("src") or existing.get("src")}
            else:
                cached[stroke_id] = stroke

            server_rev = _next_board_revision(lesson_id)
            stroke["revision"] = server_rev
            _schedule_persist_cached_board_strokes(lesson_id)
        else:
            server_rev = _next_board_revision(lesson_id)

        target_room = _teacher_room(lesson_id) if stroke_layer == "teacher" else _room(lesson_id)
        socketio.emit(
            "board_stroke",
            {
                "lesson_id": lesson_id,
                "stroke": stroke,
                "user_id": current_user.id,
                "client_stroke_id": data.get("client_stroke_id"),
                "server_revision": server_rev,
            },
            room=target_room,
            namespace="/lesson",
            include_self=False,
        )
        socketio.emit(
            "board_ack",
            {
                "lesson_id": lesson_id,
                "stroke_id": stroke_id,
                "client_stroke_id": data.get("client_stroke_id"),
                "revision": server_rev,
                "status": "synced",
            },
            room=request.sid,
            namespace="/lesson",
        )

    @socketio.on("board_action", namespace="/lesson")
    def _on_board_action(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        lesson_id = (data or {}).get("lesson_id")
        action = (data or {}).get("action")
        if not lesson_id or not action:
            return
        try:
            lesson_id = int(lesson_id)
        except (TypeError, ValueError):
            return
        lesson, role = _get_lesson_auth(lesson_id)
        if not lesson or not role or role == "parent":
            return

        board_strokes = _load_cached_board_strokes(lesson_id)
        if role != "teacher":
            from app.runtime_state import is_distributed_runtime_healthy, is_single_process_mode
            if not is_distributed_runtime_healthy() and not is_single_process_mode():
                socketio.emit("whiteboard_error", {
                    "message": "Синхронизация доски временно недоступна. Действия с доской ограничены во избежание split-brain."
                }, room=request.sid, namespace="/lesson")
                return
            control = _room_control(lesson_id)
            if control.get("freeze_student") or control.get("board_locked"):
                socketio.emit("whiteboard_error", {"message": "Действия с доской заблокированы преподавателем"}, room=request.sid, namespace="/lesson")
                return
        if action == "update":
            raw_strokes = data.get("strokes") or []
            if not isinstance(raw_strokes, list):
                return
            student_updates = []
            teacher_updates = []
            for s in raw_strokes:
                if not isinstance(s, dict):
                    continue
                sid = str(s.get("id") or "")
                if not sid or _is_stroke_tombstoned(lesson_id, sid):
                    continue
                cached_s = board_strokes.get(sid)
                if role != "teacher":
                    if cached_s and cached_s.get("layer") == "teacher":
                        continue
                    if s.get("layer") == "teacher":
                        s["layer"] = "student"
                    if cached_s:
                        owner = str(cached_s.get("userId") or cached_s.get("user_id") or "")
                        if owner and owner != str(current_user.id):
                            continue
                if cached_s:
                    if not s.get("src") and cached_s.get("src"):
                        s["src"] = cached_s["src"]
                    if not s.get("page_id") and cached_s.get("page_id"):
                        s["page_id"] = cached_s["page_id"]
                elif not s.get("page_id"):
                    s["page_id"] = "page_1"
                board_strokes[sid] = s
                if s.get("layer") == "teacher":
                    teacher_updates.append(s)
                else:
                    student_updates.append(s)
            if not student_updates and not teacher_updates:
                return
            server_rev = _next_board_revision(lesson_id)
            _schedule_persist_cached_board_strokes(lesson_id)
            if student_updates:
                socketio.emit(
                    "board_action",
                    {
                        "lesson_id": lesson_id,
                        "action": "update",
                        "strokes": student_updates,
                        "server_revision": server_rev,
                    },
                    room=_room(lesson_id),
                    namespace="/lesson",
                    include_self=False,
                )
            if teacher_updates:
                socketio.emit(
                    "board_action",
                    {
                        "lesson_id": lesson_id,
                        "action": "update",
                        "strokes": teacher_updates,
                        "server_revision": server_rev,
                    },
                    room=_teacher_room(lesson_id),
                    namespace="/lesson",
                    include_self=False,
                )
            socketio.emit(
                "board_ack",
                {
                    "lesson_id": lesson_id,
                    "action": "update",
                    "revision": server_rev,
                    "status": "synced",
                },
                room=request.sid,
                namespace="/lesson",
            )
            return
        elif action == "delete":
            raw_del_ids = data.get("strokes") or data.get("stroke_ids") or []
            if not isinstance(raw_del_ids, list):
                return
            del_ids = []
            deleted_teacher_layers = 0
            for sid in raw_del_ids:
                s_id_str = str(sid)
                cached_s = board_strokes.get(s_id_str)
                if role != "teacher":
                    if not cached_s:
                        continue
                    if cached_s.get("layer") == "teacher":
                        continue
                    owner = str(cached_s.get("userId") or cached_s.get("user_id") or "")
                    if owner and owner != str(current_user.id):
                        continue
                if cached_s and cached_s.get("layer") == "teacher":
                    deleted_teacher_layers += 1
                del_ids.append(s_id_str)
            if not del_ids:
                return
            for sid in del_ids:
                board_strokes.pop(sid, None)
            _record_stroke_tombstones(lesson_id, del_ids)
            server_rev = _next_board_revision(lesson_id)
            _schedule_persist_cached_board_strokes(lesson_id)
            target_room = _teacher_room(lesson_id) if (deleted_teacher_layers == len(del_ids) and deleted_teacher_layers > 0) else _room(lesson_id)
            socketio.emit(
                "board_action",
                {
                    "lesson_id": lesson_id,
                    "action": "delete",
                    "strokes": del_ids,
                    "stroke_ids": del_ids,
                    "server_revision": server_rev,
                },
                room=target_room,
                namespace="/lesson",
                include_self=False,
            )
            socketio.emit(
                "board_ack",
                {
                    "lesson_id": lesson_id,
                    "action": "delete",
                    "stroke_ids": del_ids,
                    "revision": server_rev,
                    "status": "synced",
                },
                room=request.sid,
                namespace="/lesson",
            )
            return
        elif action == "clear":
            if role != "teacher":
                socketio.emit("whiteboard_error", {"message": "Очистка доски доступна только преподавателю"}, room=request.sid, namespace="/lesson")
                return
            target_page_id = data.get("page_id")
            cleared_ids = []
            if target_page_id:
                to_delete = [sid for sid, s in board_strokes.items() if s.get("page_id") == target_page_id]
                for sid in to_delete:
                    board_strokes.pop(sid, None)
                    cleared_ids.append(sid)
            else:
                cleared_ids = list(board_strokes.keys())
                _lesson_board_strokes[lesson_id] = {}
            _record_stroke_tombstones(lesson_id, cleared_ids)
            server_rev = _next_board_revision(lesson_id)
            _schedule_persist_cached_board_strokes(lesson_id)
            socketio.emit(
                "board_action",
                {
                    "lesson_id": lesson_id,
                    "action": "clear",
                    "page_id": target_page_id,
                    "server_revision": server_rev,
                },
                room=_room(lesson_id),
                namespace="/lesson",
                include_self=False,
            )
            socketio.emit(
                "board_ack",
                {
                    "lesson_id": lesson_id,
                    "action": "clear",
                    "revision": server_rev,
                    "status": "synced",
                },
                room=request.sid,
                namespace="/lesson",
            )
            return
        elif action in {"page_create", "page_delete", "page_rename", "page_bg"}:
            if role != "teacher":
                socketio.emit("whiteboard_error", {"message": "Управление страницами доступно только преподавателю"}, room=request.sid, namespace="/lesson")
                return
            if action == "page_create":
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
                        _record_stroke_tombstones(lesson_id, to_delete)
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

            server_rev = _next_board_revision(lesson_id)
            socketio.emit(
                "board_action",
                {
                    "lesson_id": lesson_id,
                    "action": action,
                    "page_id": data.get("page_id"),
                    "page": data.get("page"),
                    "title": data.get("title"),
                    "background": data.get("background"),
                    "server_revision": server_rev,
                },
                room=_room(lesson_id),
                namespace="/lesson",
                include_self=False,
            )
            socketio.emit(
                "board_ack",
                {
                    "lesson_id": lesson_id,
                    "action": action,
                    "revision": server_rev,
                    "status": "synced",
                },
                room=request.sid,
                namespace="/lesson",
            )
            return
        elif action == "page_switch":
            sw_page_id = str(data.get("page_id") or "")
            if sw_page_id:
                _lesson_board_active_page[lesson_id] = sw_page_id
                _schedule_persist_cached_board_strokes(lesson_id)
            server_rev = _next_board_revision(lesson_id)
            socketio.emit(
                "board_action",
                {
                    "lesson_id": lesson_id,
                    "action": action,
                    "page_id": sw_page_id,
                    "server_revision": server_rev,
                },
                room=_room(lesson_id),
                namespace="/lesson",
                include_self=False,
            )
            socketio.emit(
                "board_ack",
                {
                    "lesson_id": lesson_id,
                    "action": action,
                    "revision": server_rev,
                    "status": "synced",
                },
                room=request.sid,
                namespace="/lesson",
            )
            return

    @socketio.on("whiteboard_join", namespace="/lesson")
    def _on_whiteboard_join(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        try:
            lesson_id = int((data or {}).get("lesson_id"))
            _lesson, role = _get_lesson_auth(lesson_id)
            if not _lesson or not role:
                socketio.emit("whiteboard_error", {"message": "Доступ к уроку запрещён"}, room=request.sid, namespace="/lesson")
                return
            if role != "teacher" and is_user_banned_from_lesson(lesson_id, current_user.id):
                socketio.emit(
                    "lesson_kicked",
                    {
                        "lesson_id": lesson_id,
                        "user_id": current_user.id,
                        "message": "Вы исключены из этого урока преподавателем.",
                        "redirect_url": "/schedule",
                    },
                    room=request.sid,
                    namespace="/lesson",
                )
                from flask_socketio import disconnect
                disconnect()
                return
            from flask_socketio import join_room
            join_room(_room(lesson_id))
            join_room(f"lesson_{lesson_id}_user_{current_user.id}")
            if role == "teacher":
                join_room(_teacher_room(lesson_id))
            from app.lessons.whiteboard_service import board_payload, get_or_create_board, can_student_edit_page
            board = get_or_create_board(lesson_id)
            identity = _lesson_presence.setdefault(lesson_id, {}).setdefault(current_user.id, {})
            uinfo = _resolve_user_presence_info(current_user)
            identity.update({
                "user_id": current_user.id,
                "sid": request.sid,
                "role": role,
                "name": uinfo["name"],
                "school_class": uinfo["school_class"],
                "client_id": (data or {}).get("client_id"),
                "page_id": (data or {}).get("page_id"),
                "follow": bool((data or {}).get("follow")),
                "color": identity.get("color") or _pointer_colors[int(current_user.id) % len(_pointer_colors)],
            })
            snapshot_payload = board_payload(board)
            active_page_id = snapshot_payload.get("document", {}).get("active_page_id")
            ctrl = _room_control(lesson_id)
            if "document" in snapshot_payload and isinstance(snapshot_payload["document"], dict):
                pres = snapshot_payload["document"].setdefault("presentation", {})
                if isinstance(pres, dict):
                    doc_ctrl = pres.setdefault("control", {})
                    if isinstance(doc_ctrl, dict):
                        doc_ctrl.update(ctrl)
            snapshot_payload["permissions"] = {
                "role": role,
                "can_edit": role == "teacher" or (role == "student" and can_student_edit_page(snapshot_payload.get("document", {}), active_page_id)),
                "can_present": role == "teacher",
                "can_lock": role == "teacher",
                "control": ctrl,
            }
            socketio.emit(
                "whiteboard_snapshot",
                {"lesson_id": lesson_id, **snapshot_payload},
                room=request.sid,
                namespace="/lesson",
            )
            socketio.emit(
                "lesson_presence",
                _presence_payload(lesson_id, list(_lesson_presence.get(lesson_id, {}).values())),
                room=_room(lesson_id),
                namespace="/lesson",
            )
            room_ui_list = _get_all_room_ui(lesson_id)
            for ui_payload in room_ui_list:
                if role != "teacher" and isinstance(ui_payload, dict):
                    win_id = ui_payload.get("window_id")
                    if win_id in {"teacher-task-bank-window", "teacher-notes-window", "lesson-info-window", "homework-window"}:
                        continue
                socketio.emit("lesson_room_ui_state", ui_payload, room=request.sid, namespace="/lesson")
            board_strokes = list(_load_cached_board_strokes(lesson_id).values())
            if role != "teacher":
                board_strokes = [s for s in board_strokes if isinstance(s, dict) and s.get("layer") != "teacher"]
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
            if not code_state:
                code_state = _load_cached_code_state(lesson_id)
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
        if target_user_id == current_user.id:
            return
        try:
            from app.lessons.routes import _whiteboard_access
            _lesson, role = _whiteboard_access(lesson_id)
            if role != "teacher":
                return
        except Exception:
            return

        # 1. Authoritative DB ban
        from core.db_models import LessonParticipantBan, utc_now
        try:
            existing_ban = LessonParticipantBan.query.filter_by(
                lesson_id=lesson_id,
                user_id=target_user_id,
                is_active=True,
            ).first()
            if not existing_ban:
                new_ban = LessonParticipantBan(
                    lesson_id=lesson_id,
                    user_id=target_user_id,
                    banned_by_user_id=current_user.id,
                    is_active=True,
                    banned_at=utc_now(),
                )
                db.session.add(new_ban)
                db.session.commit()
        except Exception as ban_err:
            db.session.rollback()
            logger.warning("Failed to persist LessonParticipantBan: %s", ban_err)

        # 2. Redis ban set
        try:
            from app.runtime_state import get_redis_client
            client = get_redis_client()
            if client:
                client.sadd(f"lesson:{lesson_id}:banned_users", str(target_user_id))
        except Exception as red_err:
            logger.warning("Failed to set Redis ban: %s", red_err)

        # 3. LiveKit participant ejection if enabled
        try:
            from app.services.livekit_service import LiveKitService
            LiveKitService.admin_remove_participant(
                room_name=f"lesson-{lesson_id}",
                identity=f"user-{target_user_id}",
            )
        except Exception as lk_err:
            logger.debug("LiveKit admin_remove_participant: %s", lk_err)

        from app.runtime_state import smembers, hdel, delete
        conn_sids = set(smembers(_connections_key(lesson_id, target_user_id)) or [])
        target_info = _lesson_presence.get(lesson_id, {}).pop(target_user_id, None)
        if target_info and target_info.get("sid"):
            conn_sids.add(target_info["sid"])

        kick_payload = {
            "lesson_id": lesson_id,
            "user_id": target_user_id,
            "message": "Преподаватель завершил ваше участие в этом уроке.",
            "redirect_url": "/schedule",
        }
        for sid in conn_sids:
            try:
                socketio.emit("lesson_kicked", kick_payload, room=sid, namespace="/lesson")
            except Exception:
                pass
        socketio.emit("lesson_kicked", kick_payload, room=f"lesson_{lesson_id}_user_{target_user_id}", namespace="/lesson")
        socketio.emit("lesson_kicked", kick_payload, room=f"lesson-{lesson_id}", namespace="/lesson")
        socketio.emit("lesson_kicked", kick_payload, room=_room(lesson_id), namespace="/lesson")

        server = getattr(socketio, 'server', None)
        def _deferred_disconnect():
            import time
            time.sleep(0.6)
            for sid in conn_sids:
                try:
                    if server:
                        server.disconnect(sid, namespace="/lesson")
                    else:
                        socketio.disconnect(sid=sid, namespace="/lesson")
                except Exception:
                    pass
        import threading
        threading.Thread(target=_deferred_disconnect, daemon=True).start()

        hdel(_presence_key(lesson_id), str(target_user_id))
        delete(_connections_key(lesson_id, target_user_id))
        if lesson_id in _lesson_presence:
            _lesson_presence[lesson_id].pop(target_user_id, None)

        presence_list = _prune_stale_connections(lesson_id)
        socketio.emit(
            "lesson_presence",
            _presence_payload(lesson_id, presence_list),
            room=_room(lesson_id),
            namespace="/lesson",
        )

    @socketio.on("unban_participant", namespace="/lesson")
    def _on_unban_participant(data):
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

        from core.db_models import LessonParticipantBan, utc_now
        try:
            active_bans = LessonParticipantBan.query.filter_by(
                lesson_id=lesson_id,
                user_id=target_user_id,
                is_active=True,
            ).all()
            for b in active_bans:
                b.is_active = False
                b.unbanned_at = utc_now()
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.warning("Failed to deactivate LessonParticipantBan: %s", e)

        try:
            from app.runtime_state import get_redis_client
            client = get_redis_client()
            if client:
                client.srem(f"lesson:{lesson_id}:banned_users", str(target_user_id))
        except Exception as e:
            logger.warning("Failed to srem from Redis banned set: %s", e)

        socketio.emit(
            "lesson_unbanned",
            {"lesson_id": lesson_id, "user_id": target_user_id},
            room=_room(lesson_id),
            namespace="/lesson",
        )
        emit_lesson_presence(lesson_id)

    @socketio.on("lesson_room_ui", namespace="/lesson")
    def _on_lesson_room_ui(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        try:
            lesson_id = int((data or {}).get("lesson_id"))
            role = (_lesson_presence.get(lesson_id, {}).get(current_user.id) or {}).get("role")
            if not role:
                _lesson, role = _get_lesson_auth(lesson_id)
            if not role:
                socketio.emit("whiteboard_error", {"message": "Доступ к уроку запрещён"}, room=request.sid, namespace="/lesson")
                return
            kind = str((data or {}).get("kind") or "")

            standard_kinds = {"mode", "window", "window_layout", "window_order", "run", "run_start", "terminal_output", "terminal_tab", "focus_suggestion_ack"}
            tracer_kinds = {"tracer_state", "tracer_window", "tracer_run", "tracer_breakpoint", "tracer_step", "tracer_input_submit", "tracer_restart"}
            orbit_kinds = {
                "orbit_beacon", "orbit_stamp", "orbit_stamp_move", "orbit_stamp_remove",
                "orbit_sticky", "orbit_sticky_input", "orbit_sticky_move", "orbit_sticky_remove",
                "orbit_timer_sync", "orbit_calc_sync", "orbit_laser", "orbit_laser_stop", "orbit_cheat_sync"
            }
            teacher_master_kinds = {
                "focus_board", "freeze_student", "free_mode", "freeze", "teacher_stamp", "teacher_hint",
                "blitz_start", "blitz_update", "blitz_end", "teacher_answer_vis", "task_switch",
                "show_here", "focus_suggestion", "set_focus", "terminal_close"
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
            is_window_action = kind in {"window", "window_layout", "window_order"}
            is_orbit_action = kind in orbit_kinds
            is_ack_action = kind in {"focus_suggestion_ack"}
            is_teacher_action = kind in teacher_master_kinds
            is_teacher_user = (role == "teacher")

            if is_teacher_action and not is_teacher_user:
                socketio.emit("whiteboard_error", {"message": "Недостаточно прав: действие доступно только преподавателю"}, room=request.sid, namespace="/lesson")
                return

            if role == "student" and is_tracer_action and control.get("freeze_student"):
                socketio.emit("whiteboard_error", {"message": "Действия заблокированы преподавателем"}, room=request.sid, namespace="/lesson")
                return

            if is_window_action:
                target_win = str((data or {}).get("window_id") or "")
                if target_win in {"teacher-task-bank-window", "teacher-notes-window", "lesson-info-window", "homework-window"}:
                    return  # Defense-in-depth: Private teacher windows are strictly never broadcast
                if target_win != "tracer-window":
                    if win_mode == "independent":
                        return
                    if win_mode == "teacher" and not is_teacher_user:
                        socketio.emit("whiteboard_error", {"message": "Управление окнами закреплено за преподавателем"}, room=request.sid, namespace="/lesson")
                        return
                    if win_mode == "student" and is_teacher_user:
                        socketio.emit("whiteboard_error", {"message": "Управление окнами передано ученику"}, room=request.sid, namespace="/lesson")
                        return
                    if kind == "window_layout":
                        if control.get("window_positions_sync") is False:
                            return
                        try:
                            if "left" in (data or {}) and (data or {})["left"] is not None:
                                (data or {})["left"] = int(round(float((data or {})["left"])))
                            if "top" in (data or {}) and (data or {})["top"] is not None:
                                (data or {})["top"] = int(round(float((data or {})["top"])))
                            if "width" in (data or {}) and (data or {})["width"] is not None:
                                (data or {})["width"] = max(100, int(round(float((data or {})["width"]))))
                            if "height" in (data or {}) and (data or {})["height"] is not None:
                                (data or {})["height"] = max(80, int(round(float((data or {})["height"]))))
                        except (ValueError, TypeError):
                            return
                    allowed_ctrl = control.get("windows_allowed")
                    if allowed_ctrl and target_win not in allowed_ctrl and not is_teacher_user:
                        return

            if not (is_window_action or is_student_run or is_student_tracer or is_orbit_action or is_teacher_user or is_ack_action):
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
                "notes-window", "theory-window", "reference-window", "files-window",
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
            elif kind == "window_order":
                window_id = str((data or {}).get("window_id") or "")[:64]
                if window_id not in allowed_windows:
                    return
                payload["window_id"] = window_id
            elif kind == "window_layout":
                window_id = str((data or {}).get("window_id") or "")[:64]
                if window_id not in allowed_windows:
                    return
                phase = str((data or {}).get("phase") or ("move" if (data or {}).get("transient") else "commit"))
                payload.update({
                    "window_id": window_id,
                    "phase": phase,
                    "left": (data or {}).get("left"),
                    "top": (data or {}).get("top"),
                    "width": (data or {}).get("width"),
                    "height": (data or {}).get("height"),
                    "is_maximized": bool((data or {}).get("is_maximized")),
                })
                if "drag_id" in (data or {}):
                    payload["drag_id"] = str((data or {}).get("drag_id"))[:64]
                if "seq" in (data or {}):
                    try:
                        payload["seq"] = int((data or {}).get("seq"))
                    except (ValueError, TypeError):
                        pass
                if "transient" in (data or {}):
                    payload["transient"] = bool((data or {}).get("transient"))
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
                if "run_id" in (data or {}):
                    payload["run_id"] = str(data["run_id"])[:64]
                if "seq" in (data or {}):
                    try:
                        payload["seq"] = int(data["seq"])
                    except (ValueError, TypeError):
                        pass
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
                    "worldX", "worldY", "isBoard",
                    "label", "type", "typeClass", "icon", "iconClass", "color",
                    "text", "expr", "val", "points", "duration", "started_at",
                    "remaining", "hint", "tier", "visible", "answer", "task_id",
                    "seconds", "isRunning", "isOpen", "mode", "user_name",
                    "is_frozen", "freeze_student", "target_focus", "target_user_id",
                    "command_id", "created_at", "page_id", "file_name"
                ):
                    if field in (data or {}):
                        payload[field] = data[field]

            # Persistence management for room_ui state
            persistent_state_kinds = {"orbit_stamp", "teacher_stamp", "orbit_sticky", "orbit_timer_sync", "orbit_calc_sync", "orbit_cheat_sync", "blitz_start", "teacher_answer_vis"}
            if kind in persistent_state_kinds:
                action = str(payload.get("action") or "")
                if action == "close":
                    if kind == "orbit_timer_sync":
                        _remove_room_ui_state(lesson_id, "timer")
                    elif kind == "orbit_calc_sync":
                        _remove_room_ui_state(lesson_id, "calc")
                    elif kind == "orbit_cheat_sync":
                        _remove_room_ui_state(lesson_id, "cheat")
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
                    _save_room_ui_state(lesson_id, state_key, payload)
            elif kind in {"orbit_stamp_move", "orbit_sticky_move", "orbit_sticky_input"}:
                base_kind = "orbit_stamp" if "stamp" in kind else "orbit_sticky"
                item_id = str(payload.get("id") or "default")
                state_key = f"{base_kind}:{item_id}"
                room_state = _lesson_room_ui.setdefault(lesson_id, {})
                if state_key in room_state:
                    room_state[state_key].update(payload)
                    _save_room_ui_state(lesson_id, state_key, room_state[state_key])
            elif kind in {"orbit_stamp_remove", "orbit_sticky_remove", "blitz_end"}:
                if kind == "blitz_end":
                    _remove_room_ui_state(lesson_id, "blitz")
                else:
                    item_id = str(payload.get("id") or "default")
                    _remove_room_ui_state(lesson_id, f"orbit_stamp:{item_id}")
                    _remove_room_ui_state(lesson_id, f"teacher_stamp:{item_id}")
                    _remove_room_ui_state(lesson_id, f"orbit_sticky:{item_id}")
            elif kind in {"mode", "terminal_output", "terminal_tab", "window", "window_layout", "window_order", "tracer_state", "tracer_window", "tracer_run", "tracer_breakpoint", "tracer_restart"}:
                if kind == "tracer_breakpoint":
                    curr_tracer = _lesson_room_ui.get(lesson_id, {}).get("tracer_state")
                    if curr_tracer:
                        curr_tracer["breakpoints"] = payload.get("breakpoints", [])
                        _save_room_ui_state(lesson_id, "tracer_state", curr_tracer)
                    else:
                        _save_room_ui_state(lesson_id, "tracer_state", {"kind": "tracer_state", "breakpoints": payload.get("breakpoints", []), "lesson_id": lesson_id})
                else:
                    is_transient_layout = (kind == "window_layout" and payload.get("phase") in {"move", "resize"})
                    if not is_transient_layout:
                        state_key = (
                            "mode" if kind == "mode"
                            else "terminal_output" if kind == "terminal_output"
                            else "terminal_tab" if kind == "terminal_tab"
                            else "tracer_state" if kind == "tracer_state"
                            else "tracer_window" if kind == "tracer_window"
                            else "tracer_run" if kind == "tracer_run"
                            else "tracer_restart" if kind == "tracer_restart"
                            else "window_order" if kind == "window_order"
                            else f"window_layout:{payload.get('window_id', 'main')}" if kind == "window_layout"
                            else f"window:{payload.get('window_id', 'main')}"
                        )
                        _save_room_ui_state(lesson_id, state_key, payload)
            elif kind in {"freeze_student", "freeze"}:
                val = (data or {}).get("is_frozen")
                if val is None:
                    val = (data or {}).get("freeze_student")
                if val is None:
                    val = payload.get("is_frozen")
                if val is None:
                    val = True if kind == "freeze_student" else False
                is_frozen = bool(val)
                if is_frozen:
                    payload["is_frozen"] = True
                    payload["freeze_student"] = True
                    _save_room_ui_state(lesson_id, "freeze", payload)
                else:
                    payload["is_frozen"] = False
                    payload["freeze_student"] = False
                    _remove_room_ui_state(lesson_id, "freeze")
                if lesson_id in _lesson_control_cache:
                    ts, c = _lesson_control_cache[lesson_id]
                    c["freeze_student"] = is_frozen
                    c["is_frozen"] = is_frozen
                    _lesson_control_cache[lesson_id] = (ts, c)
                else:
                    _lesson_control_cache.pop(lesson_id, None)
            elif kind == "free_mode":
                payload["is_frozen"] = False
                payload["freeze_student"] = False
                _remove_room_ui_state(lesson_id, "freeze")
                if lesson_id in _lesson_control_cache:
                    ts, c = _lesson_control_cache[lesson_id]
                    c["freeze_student"] = False
                    c["is_frozen"] = False
                    _lesson_control_cache[lesson_id] = (ts, c)
                else:
                    _lesson_control_cache.pop(lesson_id, None)

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
            page_id = str((data or {}).get("page_id") or "page_1")
            identity = _lesson_presence.get(lesson_id, {}).get(current_user.id)
            if identity:
                role = identity.get("role", "student")
            else:
                _lesson, role = __import__("app.lessons.routes", fromlist=["_whiteboard_access"])._whiteboard_access(lesson_id)
            incoming_code = str((data or {}).get("code") or "")[:100000]
            incoming_file = str((data or {}).get("file_name") or "main.py")[:120]
            incoming_files = (data or {}).get("files")
            incoming_tabs = (data or {}).get("open_tabs")

            current = _load_cached_code_state(lesson_id, page_id=page_id)

            if role == "parent":
                if current:
                    socketio.emit("lesson_code_snapshot", {"lesson_id": lesson_id, "page_id": page_id, **current}, room=request.sid, namespace="/lesson")
                return

            if current is None:
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
                    "revision": 1,
                    "version": 1,
                    "updated_at": int(time() * 1000),
                    "last_modified_by": current_user.id,
                }
                _update_cached_code_state(lesson_id, current, page_id=page_id)
                _schedule_persist_cached_code_state(lesson_id, page_id=page_id, delay=1.0)
            else:
                if "files" not in current:
                    current["files"] = {current.get("file_name", "main.py"): current.get("code", "")}
                if "open_tabs" not in current:
                    current["open_tabs"] = [current.get("file_name", "main.py")]
                if "active_file" not in current:
                    current["active_file"] = current.get("file_name", "main.py")
                if "revision" not in current:
                    current["revision"] = int(current.get("version") or 1)
                _update_cached_code_state(lesson_id, current, page_id=page_id)

            if current:
                socketio.emit("lesson_code_snapshot", {"lesson_id": lesson_id, "page_id": page_id, **current}, room=request.sid, namespace="/lesson")
        except Exception as error:
            logger.warning("lesson_code_join failed: %s", error)

    @socketio.on("lesson_code_patch", namespace="/lesson")
    def _on_lesson_code_patch(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        try:
            lesson_id = int((data or {}).get("lesson_id"))
            page_id = str((data or {}).get("page_id") or ((data or {}).get("patch") or {}).get("page_id") or "page_1")
            identity = _lesson_presence.get(lesson_id, {}).get(current_user.id)
            if identity:
                role = identity.get("role", "student")
            else:
                _lesson, role = __import__("app.lessons.routes", fromlist=["_whiteboard_access"])._whiteboard_access(lesson_id)
            control = _room_control(lesson_id)
            if role == "parent" or not control.get("code_sync") or (role != "teacher" and (not control.get("student_code_editing") or control.get("freeze_student"))):
                if role == "student" and control.get("freeze_student"):
                    socketio.emit("whiteboard_error", {"message": "Редактирование кода заблокировано преподавателем"}, room=request.sid, namespace="/lesson")
                return

            patch_dict = (data or {}).get("patch") or (data or {}).get("op") or {}
            file_name = str((data or {}).get("file_name") or patch_dict.get("file_name") or "main.py")[:120]
            op_id = str((data or {}).get("op_id") or patch_dict.get("op_id") or f"op_{int(time() * 1000)}")
            client_id = str((data or {}).get("client_id") or patch_dict.get("client_id") or "")
            base_revision = int((data or {}).get("base_revision") or patch_dict.get("base_revision") or 0)
            start = max(0, int(patch_dict.get("start") if "start" in patch_dict else (data or {}).get("start") or 0))
            end = max(start, int(patch_dict.get("end") if "end" in patch_dict else (data or {}).get("end") or start))
            inserted = str(patch_dict.get("inserted") if "inserted" in patch_dict else (data or {}).get("inserted") or "")[:50000]
            cursor = (data or {}).get("cursor") or patch_dict.get("cursor") or {}

            from app.runtime_state import is_distributed_runtime_healthy, is_single_process_mode, set_dirty_code, atomic_cas_json
            is_healthy = is_distributed_runtime_healthy()
            if not is_healthy and not is_single_process_mode():
                socketio.emit("lesson_sync_degraded", {
                    "lesson_id": lesson_id,
                    "page_id": page_id,
                    "degraded": True,
                    "reason": "distributed_runtime_unavailable",
                    "message": "Распределённая синхронизация временно недоступна. Совместное редактирование ограничено во избежание split-brain.",
                }, room=_room(lesson_id), namespace="/lesson")
                if role != "teacher":
                    curr_rev = int((_load_cached_code_state(lesson_id, page_id=page_id) or {}).get("revision") or 0)
                    socketio.emit("lesson_code_conflict", {
                        "lesson_id": lesson_id,
                        "page_id": page_id,
                        "file_name": file_name,
                        "server_revision": curr_rev,
                        "rejected_base_revision": base_revision,
                        "message": "Синхронизация временно недоступна (сбой брокера сообщений). Совместное редактирование заблокировано во избежание split-brain."
                    }, room=request.sid, namespace="/lesson")
                    return

            def _apply_patch(curr):
                c_dict = dict(curr or {})
                if not c_dict:
                    loaded = _load_cached_code_state(lesson_id, page_id=page_id)
                    c_dict = dict(loaded or {})
                c_rev = int(c_dict.get("revision") or c_dict.get("version") or 0)
                f_dict = dict(c_dict.get("files") or {})
                history = list(c_dict.get("history") or [])
                deleted_files = list(c_dict.get("deleted_files") or [])

                if file_name in deleted_files or (file_name != "main.py" and file_name not in f_dict):
                    return {
                        "file_deleted": True,
                        "file_name": file_name,
                        "revision": c_rev,
                        "deleted_files": deleted_files,
                    }, False

                for past_op in history:
                    if past_op.get("op_id") == op_id:
                        return {
                            "already_applied": True,
                            "revision": past_op.get("revision", c_rev),
                            "file_name": file_name,
                            "op_id": op_id,
                        }, False

                file_text = str(f_dict.get(file_name) or "")

                if history:
                    min_history_rev = int(history[0].get("revision") or 0)
                    if base_revision < min_history_rev - 1:
                        return {
                            "resync_required": True,
                            "server_revision": c_rev,
                            "file_name": file_name,
                        }, True

                concurrent_ops = [
                    op for op in history
                    if op.get("file_name") == file_name
                    and int(op.get("revision") or 0) > base_revision
                    and (not client_id or op.get("client_id") != client_id)
                ]

                cur_start = start
                cur_end = end
                for c_op in concurrent_ops:
                    is_tie_breaker = bool(client_id and c_op.get("client_id") and client_id > str(c_op.get("client_id")))
                    transformed = _ot_transform_op(
                        {"start": cur_start, "end": cur_end, "inserted": inserted},
                        c_op,
                        is_tie_breaker=is_tie_breaker,
                    )
                    cur_start = transformed["start"]
                    cur_end = transformed["end"]

                py_start = _utf16_to_py_offset(file_text, cur_start)
                py_end = _utf16_to_py_offset(file_text, cur_end)
                py_start = min(py_start, len(file_text))
                py_end = min(max(py_start, py_end), len(file_text))

                next_text = file_text[:py_start] + inserted + file_text[py_end:]
                f_dict[file_name] = next_text

                n_rev = c_rev + 1
                tabs = list(c_dict.get("open_tabs") or [file_name])
                if file_name not in tabs:
                    tabs.append(file_name)

                applied_op = {
                    "op_id": op_id,
                    "client_id": client_id,
                    "user_id": current_user.id,
                    "file_name": file_name,
                    "revision": n_rev,
                    "base_revision": base_revision,
                    "start": cur_start,
                    "end": cur_end,
                    "inserted": inserted,
                    "updated_at": int(time() * 1000),
                }
                history.append(applied_op)
                if len(history) > 100:
                    history = history[-100:]

                res_state = {
                    "file_name": file_name,
                    "code": next_text if c_dict.get("active_file", file_name) == file_name else c_dict.get("code", ""),
                    "files": f_dict,
                    "open_tabs": tabs,
                    "active_file": c_dict.get("active_file") or file_name,
                    "deleted_files": deleted_files,
                    "revision": n_rev,
                    "version": n_rev,
                    "history": history,
                    "updated_at": int(time() * 1000),
                    "last_modified_by": current_user.id,
                    "_last_applied_op": applied_op,
                    "_next_text": next_text,
                    "_transformed_start": cur_start,
                    "_transformed_end": cur_end,
                }
                return res_state, False

            cas_res = atomic_cas_json(_code_state_key(lesson_id, page_id=page_id), _apply_patch, ttl_seconds=LESSON_CACHE_TTL)
            if not cas_res or cas_res.get("resync_required"):
                curr_state = _load_cached_code_state(lesson_id, page_id=page_id) or {}
                socketio.emit("lesson_code_snapshot", {"lesson_id": lesson_id, "page_id": page_id, **curr_state}, room=request.sid, namespace="/lesson")
                return

            if cas_res.get("file_deleted"):
                curr_state = _load_cached_code_state(lesson_id, page_id=page_id) or {}
                socketio.emit("lesson_vfs_file_delete", {
                    "lesson_id": lesson_id,
                    "page_id": page_id,
                    "user_id": current_user.id,
                    "file_name": file_name,
                    "open_tabs": curr_state.get("open_tabs", ["main.py"]),
                    "active_file": curr_state.get("active_file", "main.py"),
                    "files": curr_state.get("files", {}),
                    "deleted_files": curr_state.get("deleted_files", []),
                    "revision": curr_state.get("revision", 0),
                }, room=request.sid, namespace="/lesson")
                return

            if cas_res.get("already_applied"):
                socketio.emit("lesson_code_ack", {
                    "lesson_id": lesson_id,
                    "page_id": page_id,
                    "file_name": file_name,
                    "op_id": op_id,
                    "revision": cas_res.get("revision"),
                    "status": "already_applied",
                }, room=request.sid, namespace="/lesson")
                return

            new_rev = cas_res["revision"]
            next_text = cas_res.get("_next_text", cas_res.get("files", {}).get(file_name, ""))
            trans_start = cas_res.get("_transformed_start", start)
            trans_end = cas_res.get("_transformed_end", end)

            _set_code_state_cache(lesson_id, cas_res, page_id=page_id)
            set_dirty_code(lesson_id, new_rev, author_id=current_user.id)
            _schedule_persist_cached_code_state(lesson_id, page_id=page_id, delay=1.5)

            socketio.emit("lesson_code_patch", {
                "lesson_id": lesson_id,
                "page_id": page_id,
                "file_name": file_name,
                "op_id": op_id,
                "client_id": client_id,
                "user_id": current_user.id,
                "revision": new_rev,
                "base_revision": base_revision,
                "start": trans_start,
                "end": trans_end,
                "inserted": inserted,
                "code_after": next_text,
                "cursor": cursor,
            }, room=_room(lesson_id), namespace="/lesson", include_self=False)

            socketio.emit("lesson_code_ack", {
                "lesson_id": lesson_id,
                "page_id": page_id,
                "file_name": file_name,
                "op_id": op_id,
                "revision": new_rev,
                "status": "synced",
            }, room=request.sid, namespace="/lesson")
        except Exception as error:
            logger.warning("lesson_code_patch failed: %s", error)

    @socketio.on("lesson_code_update", namespace="/lesson")
    def _on_lesson_code_update(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        try:
            lesson_id = int((data or {}).get("lesson_id"))
            page_id = str((data or {}).get("page_id") or "page_1")
            identity = _lesson_presence.get(lesson_id, {}).get(current_user.id)
            if identity:
                role = identity.get("role", "student")
            else:
                _lesson, role = __import__("app.lessons.routes", fromlist=["_whiteboard_access"])._whiteboard_access(lesson_id)
            control = _room_control(lesson_id)
            if role == "parent" or not control.get("code_sync") or (role != "teacher" and (not control.get("student_code_editing") or control.get("freeze_student"))):
                if role == "student" and control.get("freeze_student"):
                    socketio.emit("whiteboard_error", {"message": "Редактирование кода заблокировано преподавателем"}, room=request.sid, namespace="/lesson")
                return
            throttle_key = f"{lesson_id}:{page_id}:{current_user.id}:{request.sid}"
            now = monotonic()
            _lesson_code_update_emit_at[throttle_key] = now
            code = str((data or {}).get("code") or "")[:100000]
            file_name = str((data or {}).get("file_name") or "main.py")[:120]
            base_revision = (data or {}).get("base_revision")

            from app.runtime_state import is_distributed_runtime_healthy, is_single_process_mode, set_dirty_code, atomic_cas_json
            is_healthy = is_distributed_runtime_healthy()
            if not is_healthy and not is_single_process_mode():
                socketio.emit("lesson_sync_degraded", {
                    "lesson_id": lesson_id,
                    "page_id": page_id,
                    "degraded": True,
                    "reason": "distributed_runtime_unavailable",
                    "message": "Распределённая синхронизация временно недоступна. Совместное редактирование ограничено во избежание split-brain.",
                }, room=_room(lesson_id), namespace="/lesson")
                if role != "teacher":
                    curr_rev = int((_load_cached_code_state(lesson_id, page_id=page_id) or {}).get("revision") or 0)
                    socketio.emit("lesson_code_conflict", {
                        "lesson_id": lesson_id,
                        "page_id": page_id,
                        "file_name": file_name,
                        "server_revision": curr_rev,
                        "rejected_base_revision": base_revision,
                        "rejected_code": code,
                        "message": "Синхронизация временно недоступна (сбой брокера сообщений). Совместное редактирование заблокировано во избежание split-brain."
                    }, room=request.sid, namespace="/lesson")
                    return

            force = bool((data or {}).get("force")) and role == "teacher"

            def _apply_code_update(curr):
                c_dict = dict(curr or {})
                c_rev = int(c_dict.get("revision") or c_dict.get("version") or 0)
                f_dict = dict(c_dict.get("files") or {})
                if not force:
                    if base_revision is not None:
                        try:
                            base_int = int(base_revision)
                            if base_int < c_rev:
                                srv_code = f_dict.get(file_name, "")
                                if code != srv_code:
                                    return {"conflict": True, "server_revision": c_rev, "server_code": srv_code, "rejected_base": base_int}, True
                        except (ValueError, TypeError):
                            pass
                    elif c_rev > 0:
                        srv_code = f_dict.get(file_name, "")
                deleted_files = list(c_dict.get("deleted_files") or [])
                if file_name in deleted_files or (file_name != "main.py" and file_name not in f_dict):
                    return {"conflict": False, "deleted": True, "server_revision": c_rev, "deleted_files": deleted_files}, True
                n_rev = c_rev + 1
                f_dict[file_name] = code
                tabs = list(c_dict.get("open_tabs") or [file_name])
                if file_name not in tabs:
                    tabs.append(file_name)
                res_state = {
                    "file_name": file_name,
                    "code": code,
                    "files": f_dict,
                    "open_tabs": tabs,
                    "active_file": file_name,
                    "deleted_files": deleted_files,
                    "revision": n_rev,
                    "version": n_rev,
                    "updated_at": int(time() * 1000),
                    "last_modified_by": current_user.id,
                }
                return res_state, False

            cas_res = atomic_cas_json(_code_state_key(lesson_id, page_id=page_id), _apply_code_update, ttl_seconds=LESSON_CACHE_TTL)
            if cas_res and cas_res.get("deleted"):
                curr_state = _load_cached_code_state(lesson_id, page_id=page_id) or {}
                socketio.emit("lesson_vfs_file_delete", {
                    "lesson_id": lesson_id,
                    "page_id": page_id,
                    "user_id": current_user.id,
                    "file_name": file_name,
                    "open_tabs": curr_state.get("open_tabs", ["main.py"]),
                    "active_file": curr_state.get("active_file", "main.py"),
                    "files": curr_state.get("files", {}),
                    "deleted_files": curr_state.get("deleted_files", []),
                    "revision": curr_state.get("revision", 0),
                }, room=request.sid, namespace="/lesson")
                return
            if cas_res and cas_res.get("conflict"):
                socketio.emit("lesson_code_conflict", {
                    "lesson_id": lesson_id,
                    "page_id": page_id,
                    "file_name": file_name,
                    "server_revision": cas_res["server_revision"],
                    "rejected_base_revision": cas_res.get("rejected_base"),
                    "server_code": cas_res.get("server_code", ""),
                    "rejected_code": code,
                    "message": "Конфликт версий: файл был изменён другим участником."
                }, room=request.sid, namespace="/lesson")
                return

            if not cas_res:
                curr_state = _load_cached_code_state(lesson_id, page_id=page_id) or {}
                cas_res, abort = _apply_code_update(curr_state)
                if abort and cas_res and cas_res.get("deleted"):
                    socketio.emit("lesson_vfs_file_delete", {
                        "lesson_id": lesson_id,
                        "page_id": page_id,
                        "user_id": current_user.id,
                        "file_name": file_name,
                        "open_tabs": curr_state.get("open_tabs", ["main.py"]),
                        "active_file": curr_state.get("active_file", "main.py"),
                        "files": curr_state.get("files", {}),
                        "deleted_files": curr_state.get("deleted_files", []),
                        "revision": curr_state.get("revision", 0),
                    }, room=request.sid, namespace="/lesson")
                    return
                if abort and cas_res and cas_res.get("conflict"):
                    socketio.emit("lesson_code_conflict", {
                        "lesson_id": lesson_id,
                        "page_id": page_id,
                        "file_name": file_name,
                        "server_revision": cas_res["server_revision"],
                        "rejected_base_revision": cas_res.get("rejected_base"),
                        "server_code": cas_res.get("server_code", ""),
                        "rejected_code": code,
                        "message": "Конфликт версий: файл был изменён другим участником."
                    }, room=request.sid, namespace="/lesson")
                    return

            state = cas_res
            _set_code_state_cache(lesson_id, state, page_id=page_id)
            set_dirty_code(lesson_id, state["revision"], current_user.id)

            ack_status = "degraded" if not is_healthy and not is_single_process_mode() else "synced"
            socketio.emit("lesson_code_ack", {
                "lesson_id": lesson_id,
                "page_id": page_id,
                "file_name": file_name,
                "revision": state["revision"],
                "status": ack_status,
                "durable": False
            }, room=request.sid, namespace="/lesson")

            socketio.emit("lesson_code_update", {
                "lesson_id": lesson_id,
                "page_id": page_id,
                "user_id": current_user.id,
                **state
            }, room=_room(lesson_id), namespace="/lesson", include_self=False)

            _schedule_persist_cached_code_state(lesson_id, page_id=page_id, delay=1.0)
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
            if identity:
                role = identity.get("role", "student")
            else:
                _, auth_role = _get_lesson_auth(lesson_id)
                role = auth_role or "student"
            control = _room_control(lesson_id)
            if role == "parent" or not control.get("code_sync") or (role != "teacher" and (not control.get("student_code_editing") or control.get("freeze_student"))):
                if role == "student" and control.get("freeze_student"):
                    socketio.emit("whiteboard_error", {"message": "Редактирование кода заблокировано преподавателем"}, room=request.sid, namespace="/lesson")
                return

            file_name = str((data or {}).get("file_name") or "").strip()[:120]
            file_name = file_name.replace("/", "").replace("\\", "").replace("\0", "").strip()
            if not file_name:
                return
            code = str((data or {}).get("code") or "")[:100000]

            from app.runtime_state import is_distributed_runtime_healthy, is_single_process_mode, set_dirty_code
            is_healthy = is_distributed_runtime_healthy()
            if not is_healthy and not is_single_process_mode():
                socketio.emit("lesson_sync_degraded", {
                    "lesson_id": lesson_id,
                    "degraded": True,
                    "reason": "distributed_runtime_unavailable",
                    "message": "Распределённая синхронизация временно недоступна. Управление файлами ограничено во избежание split-brain.",
                }, room=_room(lesson_id), namespace="/lesson")
                if role != "teacher":
                    curr_rev = int((_load_cached_code_state(lesson_id) or {}).get("revision") or 0)
                    socketio.emit("lesson_code_conflict", {
                        "lesson_id": lesson_id,
                        "file_name": file_name,
                        "server_revision": curr_rev,
                        "reason": "distributed_sync_unavailable",
                        "message": "Синхронизация временно недоступна (сбой брокера сообщений). Создание файлов заблокировано во избежание split-brain."
                    }, room=request.sid, namespace="/lesson")
                    return

            curr_state = _load_cached_code_state(lesson_id) or {}
            files_dict = dict(curr_state.get("files") or {})
            files_dict[file_name] = code
            open_tabs = list(curr_state.get("open_tabs") or [])
            if file_name not in open_tabs:
                open_tabs.append(file_name)

            deleted_files = [f for f in (curr_state.get("deleted_files") or []) if f != file_name]

            new_rev = int(curr_state.get("revision") or curr_state.get("version") or 0) + 1
            state = {
                "file_name": file_name,
                "code": code,
                "files": files_dict,
                "open_tabs": open_tabs,
                "active_file": file_name,
                "deleted_files": deleted_files,
                "revision": new_rev,
                "version": new_rev,
                "updated_at": int(time() * 1000),
                "last_modified_by": current_user.id,
            }
            _update_cached_code_state(lesson_id, state)
            set_dirty_code(lesson_id, new_rev, current_user.id)

            ack_status = "degraded" if not is_healthy and not is_single_process_mode() else "synced"
            socketio.emit("lesson_code_ack", {
                "lesson_id": lesson_id,
                "file_name": file_name,
                "revision": new_rev,
                "status": ack_status,
                "durable": False
            }, room=request.sid, namespace="/lesson")

            socketio.emit("lesson_vfs_file_create", {
                "lesson_id": lesson_id,
                "user_id": current_user.id,
                "file_name": file_name,
                "code": code,
                "open_tabs": open_tabs,
                "active_file": file_name,
                "files": files_dict,
                "deleted_files": deleted_files,
                "revision": new_rev,
                "is_ack": True,
            }, room=request.sid, namespace="/lesson")

            socketio.emit("lesson_vfs_file_create", {
                "lesson_id": lesson_id,
                "user_id": current_user.id,
                "file_name": file_name,
                "code": code,
                "open_tabs": open_tabs,
                "active_file": file_name,
                "files": files_dict,
                "deleted_files": deleted_files,
                "revision": new_rev,
                "is_ack": False,
            }, room=_room(lesson_id), namespace="/lesson", include_self=False)

            _schedule_persist_cached_code_state(lesson_id, delay=0.1)
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
            if role == "parent" or not control.get("code_sync") or (role != "teacher" and (not control.get("student_code_editing") or control.get("freeze_student"))):
                if role == "student" and control.get("freeze_student"):
                    socketio.emit("whiteboard_error", {"message": "Редактирование кода заблокировано преподавателем"}, room=request.sid, namespace="/lesson")
                return

            old_name = str((data or {}).get("old_name") or "").strip()[:120]
            new_name = str((data or {}).get("new_name") or "").strip()[:120]
            new_name = new_name.replace("/", "").replace("\\", "").replace("\0", "").strip()
            if not old_name or not new_name or old_name == new_name or old_name == "main.py":
                return

            from app.runtime_state import is_distributed_runtime_healthy, is_single_process_mode, set_dirty_code
            is_healthy = is_distributed_runtime_healthy()
            if not is_healthy and not is_single_process_mode():
                socketio.emit("lesson_sync_degraded", {
                    "lesson_id": lesson_id,
                    "degraded": True,
                    "reason": "distributed_runtime_unavailable",
                    "message": "Распределённая синхронизация временно недоступна. Управление файлами ограничено во избежание split-brain.",
                }, room=_room(lesson_id), namespace="/lesson")
                if role != "teacher":
                    curr_rev = int((_load_cached_code_state(lesson_id) or {}).get("revision") or 0)
                    socketio.emit("lesson_code_conflict", {
                        "lesson_id": lesson_id,
                        "file_name": new_name,
                        "server_revision": curr_rev,
                        "reason": "distributed_sync_unavailable",
                        "message": "Синхронизация временно недоступна (сбой брокера сообщений). Переименование файлов заблокировано во избежание split-brain."
                    }, room=request.sid, namespace="/lesson")
                    return

            curr_state = _load_cached_code_state(lesson_id) or {}
            files_dict = dict(curr_state.get("files") or {})
            if old_name not in files_dict:
                if curr_state.get("file_name") == old_name and curr_state.get("code") is not None:
                    files_dict[old_name] = str(curr_state.get("code") or "")
                elif (data or {}).get("code") is not None:
                    files_dict[old_name] = str((data or {}).get("code") or "")
                else:
                    return
            code = files_dict.pop(old_name, str((data or {}).get("code") or ""))
            files_dict[new_name] = code
            open_tabs = [new_name if t == old_name else t for t in (curr_state.get("open_tabs") or [])]
            active_file = new_name if curr_state.get("active_file") == old_name else curr_state.get("active_file", new_name)

            new_rev = int(curr_state.get("revision") or curr_state.get("version") or 0) + 1
            state = {
                "file_name": active_file,
                "code": files_dict.get(active_file, ""),
                "files": files_dict,
                "open_tabs": open_tabs,
                "active_file": active_file,
                "revision": new_rev,
                "version": new_rev,
                "updated_at": int(time() * 1000),
                "last_modified_by": current_user.id,
            }
            _update_cached_code_state(lesson_id, state)
            set_dirty_code(lesson_id, new_rev, current_user.id)

            ack_status = "degraded" if not is_healthy and not is_single_process_mode() else "synced"
            socketio.emit("lesson_code_ack", {
                "lesson_id": lesson_id,
                "file_name": new_name,
                "revision": new_rev,
                "status": ack_status,
                "durable": False
            }, room=request.sid, namespace="/lesson")

            socketio.emit("lesson_vfs_file_rename", {
                "lesson_id": lesson_id,
                "user_id": current_user.id,
                "old_name": old_name,
                "new_name": new_name,
                "open_tabs": open_tabs,
                "active_file": active_file,
                "files": files_dict,
                "revision": new_rev,
            }, room=_room(lesson_id), namespace="/lesson", include_self=False)

            _schedule_persist_cached_code_state(lesson_id, delay=0.1)
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
            if identity:
                role = identity.get("role", "student")
            else:
                _, auth_role = _get_lesson_auth(lesson_id)
                role = auth_role or "student"
            control = _room_control(lesson_id)
            if role == "parent" or not control.get("code_sync") or (role != "teacher" and (not control.get("student_code_editing") or control.get("freeze_student"))):
                if role == "student" and control.get("freeze_student"):
                    socketio.emit("whiteboard_error", {"message": "Редактирование кода заблокировано преподавателем"}, room=request.sid, namespace="/lesson")
                return

            file_name = str((data or {}).get("file_name") or "").strip()[:120]
            if not file_name or file_name == "main.py":
                return

            from app.runtime_state import is_distributed_runtime_healthy, is_single_process_mode, set_dirty_code
            is_healthy = is_distributed_runtime_healthy()
            if not is_healthy and not is_single_process_mode():
                socketio.emit("lesson_sync_degraded", {
                    "lesson_id": lesson_id,
                    "degraded": True,
                    "reason": "distributed_runtime_unavailable",
                    "message": "Распределённая синхронизация временно недоступна. Управление файлами ограничено во избежание split-brain.",
                }, room=_room(lesson_id), namespace="/lesson")
                if role != "teacher":
                    curr_rev = int((_load_cached_code_state(lesson_id) or {}).get("revision") or 0)
                    socketio.emit("lesson_code_conflict", {
                        "lesson_id": lesson_id,
                        "file_name": file_name,
                        "server_revision": curr_rev,
                        "reason": "distributed_sync_unavailable",
                        "message": "Синхронизация временно недоступна (сбой брокера сообщений). Удаление файлов заблокировано во избежание split-brain."
                    }, room=request.sid, namespace="/lesson")
                    return

            curr_state = _load_cached_code_state(lesson_id) or {}
            files_dict = dict(curr_state.get("files") or {})
            files_dict.pop(file_name, None)
            open_tabs = [t for t in (curr_state.get("open_tabs") or []) if t != file_name]
            if not open_tabs:
                open_tabs = ["main.py"]
            active_file = curr_state.get("active_file")
            if active_file == file_name:
                active_file = open_tabs[0]

            deleted_files = list(curr_state.get("deleted_files") or [])
            if file_name not in deleted_files:
                deleted_files.append(file_name)

            new_rev = int(curr_state.get("revision") or curr_state.get("version") or 0) + 1
            state = {
                "file_name": active_file,
                "code": files_dict.get(active_file, ""),
                "files": files_dict,
                "open_tabs": open_tabs,
                "active_file": active_file,
                "deleted_files": deleted_files,
                "revision": new_rev,
                "version": new_rev,
                "updated_at": int(time() * 1000),
                "last_modified_by": current_user.id,
            }
            _update_cached_code_state(lesson_id, state)
            set_dirty_code(lesson_id, new_rev, current_user.id)

            ack_status = "degraded" if not is_healthy and not is_single_process_mode() else "synced"
            socketio.emit("lesson_code_ack", {
                "lesson_id": lesson_id,
                "file_name": file_name,
                "revision": new_rev,
                "status": ack_status,
                "durable": False
            }, room=request.sid, namespace="/lesson")

            socketio.emit("lesson_vfs_file_delete", {
                "lesson_id": lesson_id,
                "user_id": current_user.id,
                "file_name": file_name,
                "open_tabs": open_tabs,
                "active_file": active_file,
                "files": files_dict,
                "deleted_files": deleted_files,
                "revision": new_rev,
                "is_ack": True,
            }, room=request.sid, namespace="/lesson")

            socketio.emit("lesson_vfs_file_delete", {
                "lesson_id": lesson_id,
                "user_id": current_user.id,
                "file_name": file_name,
                "open_tabs": open_tabs,
                "active_file": active_file,
                "files": files_dict,
                "deleted_files": deleted_files,
                "revision": new_rev,
                "is_ack": False,
            }, room=_room(lesson_id), namespace="/lesson", include_self=False)

            _schedule_persist_cached_code_state(lesson_id, delay=0.1)
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
            curr_state = _load_cached_code_state(lesson_id) or {}
            files_dict = dict(curr_state.get("files") or {})
            deleted_files = list(curr_state.get("deleted_files") or [])
            if file_name != "main.py" and (file_name not in files_dict or file_name in deleted_files):
                if file_name in deleted_files:
                    active_fallback = "main.py"
                    curr_state["active_file"] = active_fallback
                    _update_cached_code_state(lesson_id, curr_state)
                    socketio.emit("lesson_vfs_tab_switch", {
                        "lesson_id": lesson_id,
                        "user_id": current_user.id,
                        "file_name": active_fallback,
                        "open_tabs": curr_state.get("open_tabs", ["main.py"]),
                        "active_file": active_fallback,
                        "revision": curr_state.get("revision", 0),
                    }, room=request.sid, namespace="/lesson")
                return
            curr_state["active_file"] = file_name
            curr_state["file_name"] = file_name
            open_tabs = list(curr_state.get("open_tabs") or [])
            if file_name not in open_tabs:
                open_tabs.append(file_name)
                curr_state["open_tabs"] = open_tabs

            _update_cached_code_state(lesson_id, curr_state)

            socketio.emit("lesson_vfs_tab_switch", {
                "lesson_id": lesson_id,
                "user_id": current_user.id,
                "file_name": file_name,
                "open_tabs": open_tabs,
            }, room=_room(lesson_id), namespace="/lesson", include_self=False)
        except Exception as error:
            logger.warning("lesson_vfs_tab_switch failed: %s", error)

    @socketio.on("presence_heartbeat", namespace="/lesson")
    def _on_presence_heartbeat(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        from app.runtime_state import refresh_connection_lease
        refresh_connection_lease(request.sid)
        lesson_id = (data or {}).get("lesson_id")
        if lesson_id:
            try:
                lid = int(lesson_id)
                presence_list, modified = _prune_stale_connections_with_status(lid)
                if modified:
                    socketio.emit(
                        "lesson_presence",
                        _presence_payload(lid, presence_list),
                        room=_room(lid),
                        namespace="/lesson",
                    )
            except Exception:
                pass

    @socketio.on("lesson_sync_ping", namespace="/lesson")
    def _on_lesson_sync_ping(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        try:
            lesson_id = int((data or {}).get("lesson_id") or 0)
            if not lesson_id:
                return
            from app.runtime_state import refresh_connection_lease
            refresh_connection_lease(request.sid)
            state = _load_cached_code_state(lesson_id) or {}
            rev = int(state.get("revision") or state.get("version") or 0)
            active_page = _load_cached_board_active_page(lesson_id)
            socketio.emit("lesson_sync_pong", {
                "lesson_id": lesson_id,
                "revision": rev,
                "active_page_id": active_page,
            }, room=request.sid, namespace="/lesson")
        except Exception as error:
            logger.warning("lesson_sync_ping failed: %s", error)

    @socketio.on("lesson_code_resync", namespace="/lesson")
    def _on_lesson_code_resync(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        try:
            lesson_id = int((data or {}).get("lesson_id") or 0)
            if not lesson_id:
                return
            page_id = str((data or {}).get("page_id") or "page_1")
            current = _load_cached_code_state(lesson_id, page_id=page_id)
            if current:
                socketio.emit("lesson_code_snapshot", {"lesson_id": lesson_id, "page_id": page_id, **current}, room=request.sid, namespace="/lesson")
        except Exception as error:
            logger.warning("lesson_code_resync failed: %s", error)

    @socketio.on("lesson_code_cursor", namespace="/lesson")
    def _on_lesson_code_cursor(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        try:
            lesson_id = int((data or {}).get("lesson_id"))
            page_id = str((data or {}).get("page_id") or "page_1")
            throttle_key = f"{lesson_id}:{page_id}:{current_user.id}:{request.sid}"
            now = monotonic()
            if now - _lesson_code_cursor_emit_at.get(throttle_key, 0.0) < 0.010:
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
                    "page_id": page_id,
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
            if role != "teacher":
                control = _room_control(lesson_id)
                if control.get("freeze_student") or control.get("board_locked"):
                    socketio.emit("whiteboard_error", {"message": "Операции на доске заблокированы преподавателем"}, room=request.sid, namespace="/lesson")
                    return
                if operation.get("type") in {"object.lock", "presentation.update"}:
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
            _presence_payload(lesson_id, list(_lesson_presence[lesson_id].values())),
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
            stroke_payload = payload.get("stroke") or {}
            is_teacher_layer = payload.get("layer") == "teacher" or (isinstance(stroke_payload, dict) and stroke_payload.get("layer") == "teacher")
            if is_teacher_layer and role != "teacher":
                is_teacher_layer = False
                payload["layer"] = "student"
                if isinstance(payload.get("stroke"), dict):
                    payload["stroke"]["layer"] = "student"
            target_room = _teacher_room(lesson_id) if is_teacher_layer else _room(lesson_id)
            socketio.emit("whiteboard_live_stroke", outgoing, room=target_room, namespace="/lesson", include_self=False)
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
                "is_mobile": bool(payload.get("is_mobile", False)),
                "device": str(payload.get("device") or "desktop")[:16],
                "terminal_open": bool(payload.get("terminal_open", False)),
                "updated_at": int(time() * 1000),
            }
            socketio.emit("whiteboard_viewport", outgoing, room=_room(lesson_id), namespace="/lesson", include_self=False)
        except Exception as error:
            logger.warning("whiteboard_viewport failed: %s", error)

    @socketio.on("whiteboard_show_here", namespace="/lesson")
    def _on_whiteboard_show_here(data):
        _sync_socket_user()
        if not current_user.is_authenticated:
            return
        try:
            payload = data or {}
            lesson_id = int(payload.get("lesson_id"))
            role = (_lesson_presence.get(lesson_id, {}).get(current_user.id) or {}).get("role")
            if not role:
                _lesson, role = _get_lesson_auth(lesson_id)
            if role != "teacher":
                socketio.emit("whiteboard_error", {"message": "Показать здесь доступно только преподавателю"}, room=request.sid, namespace="/lesson")
                return

            outgoing = {
                "lesson_id": lesson_id,
                "teacher_id": current_user.id,
                "target_user_id": payload.get("target_user_id"),
                "page_id": str(payload.get("page_id") or "")[:96],
                "world_x": float(payload.get("world_x") or 0),
                "world_y": float(payload.get("world_y") or 0),
                "world_w": float(payload.get("world_w") or 0),
                "world_h": float(payload.get("world_h") or 0),
                "center_x": float(payload.get("center_x") or 0),
                "center_y": float(payload.get("center_y") or 0),
                "scale": float(payload.get("scale") or 1.0),
                "timestamp": int(time() * 1000),
            }
            socketio.emit("whiteboard_show_here", outgoing, room=_room(lesson_id), namespace="/lesson", include_self=False)
        except Exception as error:
            logger.warning("whiteboard_show_here failed: %s", error)


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
        sio = getattr(current_app, "socketio", None) or _socketio_instance
        if sio:
            payload = {
                "lesson_id": lesson_id,
                "assignment_type": (assignment_type or "homework"),
            }
            if task:
                teacher_task = dict(task)
                student_task = dict(task)
                if not student_task.get("answer_visible_to_student", False):
                    student_task["answer"] = ""
                sio.emit("lesson_tasks_updated", {**payload, "task": teacher_task}, room=_teacher_room(lesson_id), namespace="/lesson")
                sio.emit("lesson_tasks_updated", {**payload, "task": student_task}, room=_student_room(lesson_id), namespace="/lesson")
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
        sio = getattr(current_app, "socketio", None) or _socketio_instance
        if not sio:
            return
        if roles == {"teacher"}:
            sio.emit(event, payload, room=_teacher_room(int(lesson_id)), namespace="/lesson")
            return
        if roles == {"teacher", "student"}:
            sio.emit(event, payload, room=_room(int(lesson_id)), namespace="/lesson")
            return
        active_users = _get_active_presence(int(lesson_id))
        for info in active_users:
            participant_id = info.get("user_id")
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
