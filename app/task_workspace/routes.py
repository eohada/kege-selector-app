from __future__ import annotations

import time
import base64

from flask import Blueprint, abort, current_app, jsonify, render_template, request, session
from flask_login import login_required

from app.models import db
from core.db_models import User

from app.assignments.routes import _collect_sandbox_files
from app.limiter import limiter
from app.sandbox.python_runner import normalize_leading_tabs_to_spaces, run_python_sandbox

from .error_hints import explain_python_error
from .service import (
    resolve_workspace_context,
    save_workspace_code,
    load_workspace_versions_payload,
    load_workspace_state_payload,
    restore_workspace_version,
)
from .socket import emit_workspace_snapshot


task_workspace_bp = Blueprint("task_workspace", __name__, url_prefix="/task-workspace")


def _workspace_actor() -> User:
    """Resolve a fresh actor instead of relying on an expired login instance."""
    try:
        actor_id = int(session.get("_user_id"))
    except (TypeError, ValueError):
        abort(401)
    actor = db.session.get(User, actor_id)
    if not actor or not actor.is_active:
        abort(401)
    return actor


@task_workspace_bp.route("/")
@login_required
def workspace_page():
    context_type = (request.args.get("context_type") or "").strip()
    if not context_type:
        abort(400, "Workspace открывается из задания или урока.")
    context_id = request.args.get("context_id", type=int)
    assignment_task_id = request.args.get("assignment_task_id", type=int)
    ctx = resolve_workspace_context(_workspace_actor(), context_type, context_id, assignment_task_id)
    return render_template("task_workspace.html", workspace=ctx.as_payload())


@task_workspace_bp.route("/api/context")
@login_required
def workspace_context_api():
    context_type = (request.args.get("context_type") or "").strip()
    if not context_type:
        abort(400, "Workspace открывается из задания или урока.")
    context_id = request.args.get("context_id", type=int)
    assignment_task_id = request.args.get("assignment_task_id", type=int)
    ctx = resolve_workspace_context(_workspace_actor(), context_type, context_id, assignment_task_id)
    return jsonify({"success": True, "workspace": ctx.as_payload()})


@task_workspace_bp.route("/api/run", methods=["POST"])
@login_required
@limiter.limit("40/minute")
def workspace_run_api():
    data = request.get_json(silent=True) or {}
    actor = _workspace_actor()
    ctx = resolve_workspace_context(
        actor,
        (data.get("context_type") or "").strip(),
        data.get("context_id"),
        data.get("assignment_task_id"),
    )
    code = normalize_leading_tabs_to_spaces(data.get("code") or "")
    if not code.strip():
        return jsonify({"success": False, "error": "Код пустой"}), 400
    started = time.perf_counter()
    task_files = _collect_sandbox_files(task_id=ctx.task_id, user_id=actor.id)
    stdout, stderr, turtle_b64 = run_python_sandbox(code, task_files=task_files)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    payload = {
        "success": True,
        "stdout": stdout,
        "stderr": stderr,
        "stderr_explained": explain_python_error(stderr),
        "elapsed_ms": elapsed_ms,
        "status": "error" if stderr else "ok",
    }
    if turtle_b64:
        payload["turtle_image_b64"] = turtle_b64
        try:
            raw = base64.b64decode(turtle_b64[:128] + "===")
            payload["turtle_image_mime"] = "image/svg+xml" if raw.lstrip().startswith(b"<svg") else "image/png"
        except Exception:
            payload["turtle_image_mime"] = "image/png"
    return jsonify(payload)


@task_workspace_bp.route("/api/save", methods=["POST"])
@login_required
@limiter.limit("80/minute")
def workspace_save_api():
    data = request.get_json(silent=True) or {}
    actor = _workspace_actor()
    ctx = resolve_workspace_context(
        actor,
        (data.get("context_type") or "").strip(),
        data.get("context_id"),
        data.get("assignment_task_id"),
    )
    if not ctx.can_edit:
        return jsonify({"success": False, "error": "Нет прав на сохранение"}), 403
    # The editor sends playback frames only when there is a new trace chunk.
    # An ordinary code autosave must not erase the already persisted history.
    frames = data.get("playback_frames")
    save_workspace_code(ctx, data.get("code") or "", data.get("answer") or "", frames=frames)
    versions = load_workspace_versions_payload(ctx)
    try:
        emit_workspace_snapshot(
            current_app.socketio,
            ctx,
            saved_by=actor.id,
            client_id=str(data.get("client_id") or ""),
        )
    except Exception:
        pass
    return jsonify({"success": True, "saved": "server", "versions": versions})


@task_workspace_bp.route("/api/versions")
@login_required
def workspace_versions_api():
    context_type = (request.args.get("context_type") or "").strip()
    if not context_type:
        abort(400, "Workspace открывается из задания или урока.")
    context_id = request.args.get("context_id", type=int)
    assignment_task_id = request.args.get("assignment_task_id", type=int)
    ctx = resolve_workspace_context(_workspace_actor(), context_type, context_id, assignment_task_id)
    return jsonify({"success": True, "versions": load_workspace_versions_payload(ctx)})


@task_workspace_bp.route("/api/versions/<int:version_id>/restore", methods=["POST"])
@login_required
@limiter.limit("20/minute")
def workspace_restore_version_api(version_id):
    data = request.get_json(silent=True) or {}
    actor = _workspace_actor()
    ctx = resolve_workspace_context(
        actor,
        (data.get("context_type") or "").strip(),
        data.get("context_id"),
        data.get("assignment_task_id"),
    )
    if not ctx.can_edit:
        return jsonify({"success": False, "error": "Нет прав на восстановление версии"}), 403
    restored = restore_workspace_version(ctx, version_id)
    try:
        emit_workspace_snapshot(current_app.socketio, ctx, saved_by=actor.id)
    except Exception:
        pass
    return jsonify({"success": True, **restored})


@task_workspace_bp.route("/api/state")
@login_required
def workspace_state_api():
    context_type = (request.args.get("context_type") or "").strip()
    if not context_type:
        abort(400, "Workspace открывается из задания или урока.")
    context_id = request.args.get("context_id", type=int)
    assignment_task_id = request.args.get("assignment_task_id", type=int)
    ctx = resolve_workspace_context(_workspace_actor(), context_type, context_id, assignment_task_id)
    return jsonify({"success": True, "state": load_workspace_state_payload(ctx)})
