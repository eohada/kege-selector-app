from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_workspace_rooms: dict[str, set[int]] = {}


def _room_key(context_type: str, context_id: int | None, assignment_task_id: int | None) -> str:
    return f"{(context_type or 'demo').strip().lower()}:{context_id if context_id is not None else 'none'}:{assignment_task_id if assignment_task_id is not None else 'none'}"


def register_task_workspace_socket(socketio) -> None:
    from flask import request
    from flask_login import current_user
    from flask_socketio import join_room, leave_room

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
                members.discard(sid)
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
        _workspace_rooms.setdefault(room, set()).add(getattr(request, "sid", 0))
        socketio.emit(
            "workspace_snapshot",
            {
                "room": room,
                "state": ctx.as_payload(),
            },
            room=request.sid,
            namespace="/task-workspace",
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
            "answer": (data.get("answer") or "")[:20_000],
            "playback_frames": data.get("playback_frames") or [],
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
                "state": ctx.as_payload(),
                "saved_by": saved_by,
            },
            room=room,
            namespace="/task-workspace",
        )
    except Exception as e:
        logger.warning("emit_workspace_snapshot failed: %s", e)
