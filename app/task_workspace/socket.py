from __future__ import annotations

import logging
from typing import Any
from time import time

logger = logging.getLogger(__name__)

_workspace_rooms: dict[str, dict[int, dict[str, Any]]] = {}
_workspace_state: dict[str, dict[str, Any]] = {}
_workspace_history_limit = 250


def _room_key(context_type: str, context_id: int | None, assignment_task_id: int | None) -> str:
    return f"{(context_type or 'demo').strip().lower()}:{context_id if context_id is not None else 'none'}:{assignment_task_id if assignment_task_id is not None else 'none'}"


def get_workspace_live_state(ctx) -> dict[str, Any]:
    room = _room_key(ctx.context_type, ctx.context_id, ctx.assignment_task_id)
    state = dict(_workspace_state.get(room, {}) or {})
    state.pop("history", None)
    return state


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
        participants = list(_workspace_rooms.get(room, {}).values())
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
        state = _workspace_state.setdefault(
            room,
            {
                "code": getattr(ctx, "code", "") or "",
                "answer": getattr(ctx, "plain_answer", "") or "",
                "version": 0,
                "history": [],
                "updated_at": int(time() * 1000),
            },
        )
        state.setdefault("code", getattr(ctx, "code", "") or "")
        state.setdefault("answer", getattr(ctx, "plain_answer", "") or "")
        state.setdefault("version", 0)
        state.setdefault("history", [])
        state.setdefault("updated_at", int(time() * 1000))
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
            "ts": int(time() * 1000),
        }

    def _update_participant_cursor(room: str, sid, data: dict[str, Any]) -> dict[str, Any]:
        participants = _workspace_rooms.setdefault(room, {})
        payload = participants.get(sid) or _participant_payload()
        payload["cursor"] = _cursor_payload(data)
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
            "version": int(state.get("version") or 0),
            "updated_at": data.get("updated_at"),
            "sender_id": current_user.id,
            "sender_username": current_user.username,
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
        except Exception:
            return
        sid = getattr(request, "sid", 0)
        participant = _update_participant_cursor(room, sid, data or {})
        current = _ensure_room_state(room, ctx)
        code = str(current.get("code") or "")
        base_version = max(0, int(data.get("base_version") or current.get("version") or 0))
        op_id = str(data.get("op_id") or "")
        history = list(current.get("history") or [])
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
        _set_room_state(room, {"code": next_code, "version": next_version, "history": history})
        socketio.emit(
            "workspace_patch",
            {
                "room": room,
                "user_id": current_user.id,
                "username": current_user.username,
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
