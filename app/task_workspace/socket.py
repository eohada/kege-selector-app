from __future__ import annotations

import logging
from typing import Any
from time import time

logger = logging.getLogger(__name__)

_workspace_rooms: dict[str, dict[int, dict[str, Any]]] = {}
_workspace_state: dict[str, dict[str, Any]] = {}


def _room_key(context_type: str, context_id: int | None, assignment_task_id: int | None) -> str:
    return f"{(context_type or 'demo').strip().lower()}:{context_id if context_id is not None else 'none'}:{assignment_task_id if assignment_task_id is not None else 'none'}"


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
        role = "creator" if getattr(current_user, "is_creator", False) else "admin" if getattr(current_user, "is_admin", False) else "teacher" if getattr(current_user, "is_teacher", False) else "student"
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
        if room not in _workspace_state:
            _workspace_state[room] = {"code": getattr(ctx, "code", "") or "", "answer": getattr(ctx, "plain_answer", "") or ""}
        _emit_presence(room)
        socketio.emit(
            "workspace_snapshot",
            {
                "room": room,
                "state": {**ctx.as_payload(), **_workspace_state.get(room, {})},
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
        participants = _workspace_rooms.setdefault(room, {})
        payload = participants.get(sid) or _participant_payload()
        payload["cursor"] = {
            "start": int(data.get("start") or 0),
            "end": int(data.get("end") or 0),
            "line": int(data.get("line") or 0),
            "column": int(data.get("column") or 0),
            "panel": str(data.get("panel") or "editor"),
            "ts": int(time() * 1000),
        }
        participants[sid] = payload
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
        payload = {
            "room": room,
            "context_type": ctx.context_type,
            "context_id": ctx.context_id,
            "assignment_task_id": ctx.assignment_task_id,
            "student_user_id": ctx.student_user_id,
            "student_id": ctx.student_id,
            "code": (data.get("code") or "")[:100_000],
            "playback_frames": data.get("playback_frames") or [],
            "updated_at": data.get("updated_at"),
            "sender_id": current_user.id,
            "sender_username": current_user.username,
        }
        _set_room_state(room, {"code": payload["code"]})
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
        current = _workspace_state.get(room) or {}
        code = str(current.get("code") or "")
        if previous and code and previous not in code:
            if next_value:
                _set_room_state(room, {"code": next_value})
                socketio.emit(
                    "workspace_patch",
                    {
                        "room": room,
                        "user_id": current_user.id,
                        "username": current_user.username,
                        "start": 0,
                        "end": len(code),
                        "inserted": next_value,
                        "updated_at": _workspace_state.get(room, {}).get("updated_at"),
                    },
                    room=room,
                    namespace="/task-workspace",
                    include_self=False,
                )
                return
        start = min(start, len(code))
        end = min(max(start, end), len(code))
        next_code = code[:start] + inserted + code[end:]
        _set_room_state(room, {"code": next_code})
        socketio.emit(
            "workspace_patch",
            {
                "room": room,
                "user_id": current_user.id,
                "username": current_user.username,
                "start": start,
                "end": end,
                "inserted": inserted,
                "updated_at": _workspace_state.get(room, {}).get("updated_at"),
            },
            room=room,
            namespace="/task-workspace",
            include_self=False,
        )

    @socketio.on("workspace_saved", namespace="/task-workspace")
    def _on_workspace_saved(data):
        if not current_user.is_authenticated:
            return
        room, ctx = _resolve_room(data or {})
        if not room or not ctx:
            return
        socketio.emit(
            "workspace_snapshot",
            {
                "room": room,
                "state": ctx.as_payload(),
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
