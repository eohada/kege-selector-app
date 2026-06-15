from __future__ import annotations

import logging
import threading
from typing import Any
from time import time

logger = logging.getLogger(__name__)

_workspace_rooms: dict[str, dict[int, dict[str, Any]]] = {}
_workspace_state: dict[str, dict[str, Any]] = {}
_workspace_history_limit = 250
_workspace_autosave_timers: dict[str, threading.Timer] = {}
_workspace_autosave_lock = threading.Lock()


def _room_key(context_type: str, context_id: int | None, assignment_task_id: int | None) -> str:
    return f"{(context_type or 'demo').strip().lower()}:{context_id if context_id is not None else 'none'}:{assignment_task_id if assignment_task_id is not None else 'none'}"


def get_workspace_live_state(ctx) -> dict[str, Any]:
    room = _room_key(ctx.context_type, ctx.context_id, ctx.assignment_task_id)
    state = dict(_workspace_state.get(room, {}) or {})
    state.pop("history", None)
    return state


def _workspace_autosave_key(ctx) -> str:
    return _room_key(ctx.context_type, ctx.context_id, ctx.assignment_task_id)


def _schedule_workspace_autosave(ctx, code: str, answer: str = "", frames: list[dict[str, Any]] | None = None) -> None:
    from .service import autosave_workspace_snapshot, WORKSPACE_AUTOSAVE_DEBOUNCE_SECONDS

    key = _workspace_autosave_key(ctx)

    def _flush():
        with _workspace_autosave_lock:
            _workspace_autosave_timers.pop(key, None)
        try:
            autosave_workspace_snapshot(ctx, code, answer, frames=frames, source="autosave")
        except Exception as exc:
            logger.warning("workspace autosave failed for %s: %s", key, exc)

    with _workspace_autosave_lock:
        old = _workspace_autosave_timers.pop(key, None)
        if old is not None:
            try:
                old.cancel()
            except Exception:
                pass
        timer = threading.Timer(WORKSPACE_AUTOSAVE_DEBOUNCE_SECONDS, _flush)
        timer.daemon = True
        _workspace_autosave_timers[key] = timer
        timer.start()


def _cache_workspace_snapshot(
    ctx,
    code: str,
    answer: str = "",
    frames: list[dict[str, Any]] | None = None,
    *,
    version: int | None = None,
    source: str = "live",
    ui_state: dict[str, Any] | None = None,
) -> None:
    from .service import cache_workspace_snapshot

    try:
        cache_workspace_snapshot(ctx, code, answer, frames=frames, source=source, version=version, ui_state=ui_state)
    except Exception as exc:
        logger.warning("workspace snapshot cache failed for %s: %s", _workspace_autosave_key(ctx), exc)


def register_task_workspace_socket(socketio) -> None:
    from flask import request
    from flask_login import current_user
    from flask_socketio import join_room

    def _resolve_room(data: dict[str, Any]) -> tuple[str, Any] | tuple[None, None]:
        from .service import resolve_workspace_context

        context_type = (data.get("context_type") or "demo").strip().lower()
        context_id = data.get("context_id")
        assignment_task_id = data.get("assignment_task_id")
        try:
            ctx = resolve_workspace_context(current_user, context_type, context_id, assignment_task_id)
        except Exception:
            return None, None
        return _room_key(ctx.context_type, ctx.context_id, ctx.assignment_task_id), ctx

    def _participant_payload() -> dict[str, Any]:
        display_name = getattr(current_user, "display_name", None) or getattr(current_user, "full_name", None) or getattr(current_user, "username", "user")
        is_creator = getattr(current_user, "is_creator", lambda: False)()
        is_admin = getattr(current_user, "is_admin", lambda: False)()
        is_teacher = getattr(current_user, "is_teacher", lambda: False)() or getattr(current_user, "is_tutor", lambda: False)()
        role = "creator" if is_creator else "admin" if is_admin else "teacher" if is_teacher else "student"
        return {
            "user_id": current_user.id,
            "username": current_user.username,
            "display_name": display_name,
            "role": role,
            "color": "#8b5cf6" if role in {"creator", "admin"} else "#05aec9" if role == "teacher" else "#18b96c",
            "cursor": {"start": 0, "end": 0, "line": 0, "column": 0, "panel": "editor", "ts": int(time() * 1000)},
        }

    def _emit_presence(room: str) -> None:
        participants_by_user: dict[int, dict[str, Any]] = {}
        for participant in _workspace_rooms.get(room, {}).values():
            user_id = participant.get("user_id")
            if user_id is None:
                continue
            try:
                user_key = int(user_id)
            except (TypeError, ValueError):
                continue
            current = participants_by_user.get(user_key)
            current_ts = int((current or {}).get("cursor", {}).get("ts") or (current or {}).get("ts") or 0)
            participant_ts = int((participant.get("cursor") or {}).get("ts") or participant.get("ts") or 0)
            if current is None or participant_ts >= current_ts:
                participants_by_user[user_key] = participant
        participants = list(participants_by_user.values())
        socketio.emit(
            "workspace_presence",
            {"room": room, "participants": participants, "ts": int(time() * 1000)},
            room=room,
            namespace="/task-workspace",
        )

    def _set_room_state(room: str, payload: dict[str, Any]) -> None:
        current = _workspace_state.get(room, {})
        current.update(payload or {})
        current["updated_at"] = int(time() * 1000)
        _workspace_state[room] = current

    def _ensure_room_state(room: str, ctx) -> dict[str, Any]:
        from .service import load_cached_workspace_snapshot

        cached = load_cached_workspace_snapshot(ctx) or {}
        state = _workspace_state.setdefault(
            room,
            {
                "code": cached.get("code") or getattr(ctx, "code", "") or "",
                "answer": cached.get("answer") or getattr(ctx, "plain_answer", "") or "",
                "version": int(cached.get("version") or 0),
                "history": [],
                "updated_at": int(cached.get("updated_at") or int(time() * 1000)),
                "playback_frames": cached.get("frames") or [],
                "ui_state": cached.get("ui_state") or {},
            },
        )
        state.setdefault("code", getattr(ctx, "code", "") or "")
        state.setdefault("answer", getattr(ctx, "plain_answer", "") or "")
        state.setdefault("version", 0)
        state.setdefault("history", [])
        state.setdefault("updated_at", int(time() * 1000))
        state.setdefault("playback_frames", [])
        state.setdefault("ui_state", {})
        return state

    def _transform_position(pos: int, op: dict[str, Any]) -> int:
        start = int(op.get("start") or 0)
        end = int(op.get("end") or start)
        inserted_len = len(str(op.get("inserted") or ""))
        removed_len = max(0, end - start)
        delta = inserted_len - removed_len
        if pos <= start:
            return pos
        if pos >= end:
            return max(0, pos + delta)
        return start + inserted_len

    def _transform_range(start: int, end: int, history: list[dict[str, Any]], base_version: int) -> tuple[int, int]:
        next_start = max(0, int(start or 0))
        next_end = max(next_start, int(end or next_start))
        for op in history:
            if int(op.get("version") or 0) <= base_version:
                continue
            next_start = _transform_position(next_start, op)
            next_end = _transform_position(next_end, op)
            if next_end < next_start:
                next_end = next_start
        return next_start, next_end

    def _cursor_payload(data: dict[str, Any]) -> dict[str, Any]:
        return {
            "start": int(data.get("cursor_start", data.get("start", 0)) or 0),
            "end": int(data.get("cursor_end", data.get("end", data.get("cursor_start", 0))) or 0),
            "line": int(data.get("cursor_line", data.get("line", 0)) or 0),
            "column": int(data.get("cursor_column", data.get("column", 0)) or 0),
            "panel": str(data.get("cursor_panel", data.get("panel", "editor")) or "editor"),
            "client_id": str(data.get("client_id") or ""),
            "ts": int(time() * 1000),
        }

    def _ui_payload(data: dict[str, Any], current_state: dict[str, Any] | None = None) -> dict[str, Any]:
        current_state = current_state or {}
        current_ui = dict(current_state.get("ui_state") or {})
        incoming = dict(data.get("ui_state") or {})
        if "active_tab" in data:
            incoming["active_tab"] = str(data.get("active_tab") or "editor")
        if "scroll_top" in data:
            incoming["scroll_top"] = max(0, int(data.get("scroll_top") or 0))
        if "scroll_left" in data:
            incoming["scroll_left"] = max(0, int(data.get("scroll_left") or 0))
        if "playback_index" in data:
            incoming["playback_index"] = max(0, int(data.get("playback_index") or 0))
        if "playback_speed" in data:
            incoming["playback_speed"] = max(0.25, float(data.get("playback_speed") or 1))
        if "cursor_start" in data or "start" in data:
            incoming["cursor_start"] = int(data.get("cursor_start", data.get("start", 0)) or 0)
        if "cursor_end" in data or "end" in data:
            incoming["cursor_end"] = int(data.get("cursor_end", data.get("end", data.get("cursor_start", 0))) or 0)
        if "cursor_line" in data or "line" in data:
            incoming["cursor_line"] = int(data.get("cursor_line", data.get("line", 0)) or 0)
        if "cursor_column" in data or "column" in data:
            incoming["cursor_column"] = int(data.get("cursor_column", data.get("column", 0)) or 0)
        current_ui.update({k: v for k, v in incoming.items() if v is not None})
        current_ui["ts"] = int(time() * 1000)
        return current_ui

    def _update_participant_cursor(room: str, sid, data: dict[str, Any]) -> dict[str, Any]:
        participants = _workspace_rooms.setdefault(room, {})
        payload = participants.get(sid) or _participant_payload()
        payload["cursor"] = _cursor_payload(data)
        payload["ui_state"] = _ui_payload(data, _workspace_state.get(room, {}))
        participants[sid] = payload
        return payload

    @socketio.on("connect", namespace="/task-workspace")
    def _on_connect():
        if not current_user.is_authenticated:
            return False
        return True

    @socketio.on("disconnect", namespace="/task-workspace")
    def _on_disconnect():
        if not current_user.is_authenticated:
            return
        sid = getattr(request, "sid", None)
        for room, members in list(_workspace_rooms.items()):
            if sid in members:
                members.pop(sid, None)
                _emit_presence(room)
                if not members:
                    del _workspace_rooms[room]
                break

    @socketio.on("join_workspace", namespace="/task-workspace")
    def _on_join_workspace(data):
        if not current_user.is_authenticated:
            return
        room, ctx = _resolve_room(data or {})
        if not room or not ctx:
            return
        join_room(room)
        sid = getattr(request, "sid", 0)
        participants = _workspace_rooms.setdefault(room, {})
        participants[sid] = {**_participant_payload(), "cursor": {**_participant_payload()["cursor"]}}
        state = _ensure_room_state(room, ctx)
        _cache_workspace_snapshot(
            ctx,
            state.get("code") or "",
            state.get("answer") or "",
            frames=state.get("playback_frames") or [],
            version=int(state.get("version") or 0),
            source="join",
            ui_state=state.get("ui_state") or {},
        )
        _emit_presence(room)
        socketio.emit(
            "workspace_snapshot",
            {
                "room": room,
                "state": {**ctx.as_payload(), **state},
            },
            room=request.sid,
            namespace="/task-workspace",
        )

    @socketio.on("workspace_cursor_update", namespace="/task-workspace")
    def _on_workspace_cursor_update(data):
        if not current_user.is_authenticated:
            return
        room, ctx = _resolve_room(data or {})
        if not room or not ctx:
            return
        sid = getattr(request, "sid", 0)
        payload = _update_participant_cursor(room, sid, data or {})
        state = _ensure_room_state(room, ctx)
        state["ui_state"] = _ui_payload(data or {}, state)
        _workspace_state[room] = state
        _cache_workspace_snapshot(
            ctx,
            state.get("code") or "",
            state.get("answer") or "",
            frames=state.get("playback_frames") or [],
            version=int(state.get("version") or 0),
            source="cursor",
            ui_state=state.get("ui_state") or {},
        )
        socketio.emit(
            "workspace_cursor_update",
            {
                "room": room,
                "user_id": payload["user_id"],
                "username": payload["username"],
                "display_name": payload["display_name"],
                "role": payload["role"],
                "color": payload["color"],
                "cursor": payload["cursor"],
                "client_id": payload["cursor"].get("client_id"),
            },
            room=room,
            namespace="/task-workspace",
            include_self=False,
        )

    @socketio.on("workspace_draft_update", namespace="/task-workspace")
    def _on_workspace_draft_update(data):
        if not current_user.is_authenticated:
            return
        room, ctx = _resolve_room(data or {})
        if not room or not ctx:
            return
        state = _ensure_room_state(room, ctx)
        incoming_code = (data.get("code") or "")[:100_000]
        incoming_answer = (data.get("answer") or "")[:20_000]
        playback_frames = data.get("playback_frames") or []
        changed = False
        if incoming_answer != str(state.get("answer") or ""):
            state["answer"] = incoming_answer
            changed = True
        if playback_frames:
            state["playback_frames"] = playback_frames
        state["ui_state"] = _ui_payload(data or {}, state)
        # Full drafts are now a recovery path only. Code collaboration goes through
        # workspace_patch so old full snapshots do not overwrite newer typing.
        if data.get("force_code_snapshot"):
            state["code"] = incoming_code
            state["version"] = int(state.get("version") or 0) + 1
            state["history"] = []
            changed = True
        if changed:
            state["updated_at"] = int(data.get("updated_at") or int(time() * 1000))
            _workspace_state[room] = state
            _cache_workspace_snapshot(
                ctx,
                state.get("code") or "",
                state.get("answer") or "",
                frames=state.get("playback_frames") or [],
                version=int(state.get("version") or 0),
                source="draft",
                ui_state=state.get("ui_state") or {},
            )
            _schedule_workspace_autosave(
                ctx,
                state.get("code") or "",
                state.get("answer") or "",
                frames=state.get("playback_frames") or [],
            )
        payload = {
            "room": room,
            "context_type": ctx.context_type,
            "context_id": ctx.context_id,
            "assignment_task_id": ctx.assignment_task_id,
            "student_user_id": ctx.student_user_id,
            "student_id": ctx.student_id,
            "code": state.get("code") or "",
            "answer": state.get("answer") or "",
            "playback_frames": state.get("playback_frames") or [],
            "ui_state": state.get("ui_state") or {},
            "version": int(state.get("version") or 0),
            "updated_at": data.get("updated_at"),
            "sender_id": current_user.id,
            "sender_username": current_user.username,
            "client_id": str(data.get("client_id") or ""),
        }
        socketio.emit(
            "workspace_draft_updated",
            payload,
            room=room,
            namespace="/task-workspace",
            include_self=False,
        )

    @socketio.on("workspace_patch", namespace="/task-workspace")
    def _on_workspace_patch(data):
        if not current_user.is_authenticated:
            return
        room, ctx = _resolve_room(data or {})
        if not room or not ctx:
            return
        try:
            start = max(0, int(data.get("start") or 0))
            end = max(start, int(data.get("end") or start))
            inserted = str(data.get("inserted") or "")[:10_000]
            previous = str(data.get("previous") or "")
            next_value = str(data.get("next") or "")
            full_code = str(data.get("full_code") or "")[:100_000]
        except Exception:
            return
        sid = getattr(request, "sid", 0)
        participant = _update_participant_cursor(room, sid, data or {})
        current = _ensure_room_state(room, ctx)
        code = str(current.get("code") or "")
        base_version = max(0, int(data.get("base_version") or current.get("version") or 0))
        op_id = str(data.get("op_id") or "")
        history = list(current.get("history") or [])
        if full_code:
            next_code = full_code
            prefix_len = 0
            limit = min(len(code), len(full_code))
            while prefix_len < limit and code[prefix_len] == full_code[prefix_len]:
                prefix_len += 1
            suffix_len = 0
            while (
                len(code) - 1 - suffix_len >= prefix_len
                and len(full_code) - 1 - suffix_len >= prefix_len
                and code[len(code) - 1 - suffix_len] == full_code[len(full_code) - 1 - suffix_len]
            ):
                suffix_len += 1
            start = prefix_len
            end = max(prefix_len, len(code) - suffix_len)
            inserted = full_code[prefix_len:len(full_code) - suffix_len]
        else:
            if base_version < int(current.get("version") or 0):
                start, end = _transform_range(start, end, history, base_version)
            start = min(start, len(code))
            end = min(max(start, end), len(code))
            next_code = code[:start] + inserted + code[end:]
        next_version = int(current.get("version") or 0) + 1
        op = {
            "version": next_version,
            "op_id": op_id,
            "user_id": current_user.id,
            "start": start,
            "end": end,
            "inserted": inserted,
            "updated_at": int(data.get("updated_at") or int(time() * 1000)),
        }
        history.append(op)
        if len(history) > _workspace_history_limit:
            history = history[-_workspace_history_limit:]
        _set_room_state(room, {"code": next_code, "version": next_version, "history": history, "ui_state": _ui_payload(data or {}, current)})
        _cache_workspace_snapshot(
            ctx,
            next_code,
            current.get("answer") or "",
            frames=current.get("playback_frames") or [],
            version=next_version,
            source="patch",
            ui_state=_workspace_state.get(room, {}).get("ui_state") or {},
        )
        _schedule_workspace_autosave(
            ctx,
            next_code,
            current.get("answer") or "",
            frames=current.get("playback_frames") or [],
        )
        socketio.emit(
            "workspace_patch",
            {
                "room": room,
                "user_id": current_user.id,
                "username": current_user.username,
                "client_id": str(data.get("client_id") or ""),
                "op_id": op_id,
                "version": next_version,
                "base_version": base_version,
                "start": start,
                "end": end,
                "inserted": inserted,
                "code_after": next_code,
                "cursor": participant.get("cursor") or {},
                "display_name": participant.get("display_name"),
                "role": participant.get("role"),
                "color": participant.get("color"),
                "updated_at": _workspace_state.get(room, {}).get("updated_at"),
                "ui_state": _workspace_state.get(room, {}).get("ui_state") or {},
            },
            room=room,
            namespace="/task-workspace",
            include_self=True,
        )
        socketio.emit(
            "workspace_snapshot",
            {
                "room": room,
                "state": {**ctx.as_payload(), **_workspace_state.get(room, {})},
                "saved_by": current_user.id,
                "client_id": str(data.get("client_id") or ""),
            },
            room=room,
            namespace="/task-workspace",
        )

    @socketio.on("workspace_saved", namespace="/task-workspace")
    def _on_workspace_saved(data):
        if not current_user.is_authenticated:
            return
        room, ctx = _resolve_room(data or {})
        if not room or not ctx:
            return
        state = _ensure_room_state(room, ctx)
        socketio.emit(
            "workspace_snapshot",
            {
                "room": room,
                "state": {**ctx.as_payload(), **state},
                "saved_by": current_user.id,
                "client_id": str(data.get("client_id") or ""),
            },
            room=room,
            namespace="/task-workspace",
        )


def emit_workspace_snapshot(socketio, ctx, *, saved_by: int | None = None) -> None:
    try:
        room = _room_key(ctx.context_type, ctx.context_id, ctx.assignment_task_id)
        socketio.emit(
            "workspace_snapshot",
            {
                "room": room,
                "state": {**ctx.as_payload(), **_workspace_state.get(room, {})},
                "saved_by": saved_by,
            },
            room=room,
            namespace="/task-workspace",
        )
    except Exception as e:
        logger.warning("emit_workspace_snapshot failed: %s", e)
