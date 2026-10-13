from __future__ import annotations

import time
import base64
import uuid
import re

from flask import Blueprint, abort, current_app, jsonify, render_template, request, session
from flask_login import login_required

from app.models import db
from core.db_models import User, Lesson, LessonTask, Submission, AssignmentTask, Answer, StudentWorkspaceFile, TaskCanvasDrawing

from app.assignments.routes import _collect_sandbox_files
from app.limiter import limiter
from app.sandbox.python_runner import normalize_leading_tabs_to_spaces, run_python_sandbox
from app.workspace.routes import _read_file_bytes, _write_workspace_bytes

from .error_hints import explain_python_error
from .service import (
    resolve_workspace_context,
    save_workspace_code,
    load_workspace_versions_payload,
    load_workspace_state_payload,
    restore_workspace_version,
    load_workspace_notes,
    save_workspace_version,
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

    # Check for interactive secret achievements
    achievement_unlocked = None
    from core.db_models import Student
    student = Student.query.filter_by(user_id=actor.id).first()
    if student:
        from app.utils.achievement_service import process_achievement_event
        if stderr:
            if 'RecursionError' in stderr:
                res = process_achievement_event(student, 'python_error', event_data={'error_type': 'RecursionError'})
                if res.get('unlocked'): achievement_unlocked = res.get('achievement')
            elif 'ZeroDivisionError' in stderr:
                res = process_achievement_event(student, 'python_error', event_data={'error_type': 'ZeroDivisionError'})
                if res.get('unlocked'): achievement_unlocked = res.get('achievement')
            
            if 'SyntaxError' in stderr:
                session['_had_syntax_error'] = True
        else:
            if session.pop('_had_syntax_error', None):
                res = process_achievement_event(student, 'syntax_recovery')
                if res.get('unlocked'): achievement_unlocked = res.get('achievement')
            if 'import this' in code or (stdout and 'The Zen of Python' in stdout):
                res = process_achievement_event(student, 'zen_python')
                if res.get('unlocked'): achievement_unlocked = res.get('achievement')

    payload = {
        "success": True,
        "stdout": stdout,
        "stderr": stderr,
        "stderr_explained": explain_python_error(stderr),
        "elapsed_ms": elapsed_ms,
        "status": "error" if stderr else "ok",
        "achievement_unlocked": achievement_unlocked,
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
    save_workspace_code(ctx, data.get("code") or "", data.get("answer") or "", frames=frames, notes=data.get("notes"))
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


@task_workspace_bp.route("/api/notes", methods=["GET", "POST"])
@login_required
def workspace_notes_api():
    data = request.get_json(silent=True) or {} if request.method == "POST" else request.args
    ctx = resolve_workspace_context(
        _workspace_actor(), data.get("context_type", ""), data.get("context_id"), data.get("assignment_task_id")
    )
    if request.method == "GET":
        return jsonify({"success": True, "notes": load_workspace_notes(ctx)})
    if not ctx.can_edit:
        abort(403)
    notes = str(data.get("notes") or "")
    if len(notes) > 20_000:
        return jsonify({"success": False, "error": "Заметка слишком длинная"}), 400
    state = load_workspace_state_payload(ctx)
    save_workspace_version(ctx, state["code"], state["answer"], source="notes", notes=notes)
    db.session.commit()
    return jsonify({"success": True, "notes": notes})


@task_workspace_bp.route("/api/bridge", methods=["GET", "POST"])
@login_required
def workspace_bridge_api():
    actor = _workspace_actor()
    data = request.get_json(silent=True) or {} if request.method == "POST" else request.args
    ctx = resolve_workspace_context(actor, data.get("context_type", ""), data.get("context_id"), data.get("assignment_task_id"))
    if ctx.context_type != "submission_task":
        abort(400)
    submission = db.session.get(Submission, ctx.submission_id)
    lesson_id = submission.assignment.lesson_id if submission and submission.assignment else None
    lesson = db.session.get(Lesson, lesson_id) if lesson_id else None
    lesson_tasks = []
    if lesson and lesson.student_id == ctx.student_id:
        lesson_tasks = LessonTask.query.filter_by(lesson_id=lesson.lesson_id).order_by(LessonTask.lesson_task_id).all()
    if request.method == "GET":
        return jsonify({
            "success": True,
            "lesson": {"id": lesson.lesson_id, "title": lesson.topic or "Урок", "url": f"/lesson/{lesson.lesson_id}/room"} if lesson else None,
            "lesson_os_code": bool(((lesson.review_summaries or {}).get("_os_workspace") or {}).get("code")) if lesson else False,
            "lesson_tasks": [{"id": item.lesson_task_id, "title": (getattr(item.task, "title", None) or f"Задание {item.task_id}")} for item in lesson_tasks],
            "assignment_tasks": [item for item in ctx.tasks_nav if item["assignment_task_id"] != ctx.assignment_task_id],
        })
    if not ctx.can_edit or actor.id != ctx.student_user_id:
        abort(403)
    if data.get("direction") == "to_lesson":
        if not lesson:
            abort(404)
        current_state = load_workspace_state_payload(ctx)
        note_parts = [current_state["notes"]]
        if data.get("include_code", True) and current_state["code"].strip():
            note_parts.append(f"Код из задания {ctx.task_position}:\n```python\n{current_state['code']}\n```")
        start = f"[Домашняя работа #{ctx.submission_id} · задание {ctx.task_position}]"
        end = "[/Домашняя работа]"
        existing = re.sub(re.escape(start) + r".*?" + re.escape(end), "", lesson.student_notes or "", flags=re.DOTALL).strip()
        block = "\n\n".join(part.strip() for part in note_parts if part.strip())
        merged = (existing + "\n\n" + start + "\n" + block + "\n" + end).strip()
        if len(merged) > 20_000:
            return jsonify({"success": False, "error": "В заметках урока не хватает места для переноса"}), 400
        lesson.student_notes = merged
        db.session.commit()
        return jsonify({"success": True, "message": "Заметки и код сохранены в OS урока"})
    source_type = str(data.get("source_type") or "")
    source_id = data.get("source_id")
    source_ctx = None
    if source_type == "lesson_notes":
        if not lesson:
            abort(404)
        source_notes = lesson.student_notes or ""
        source_state = None
    elif source_type == "lesson_os":
        if not lesson or source_id != lesson.lesson_id:
            abort(403)
        stored_os = (lesson.review_summaries or {}).get("_os_workspace") or {}
        source_state = {"code": stored_os.get("code") or ""}
        source_notes = lesson.student_notes or ""
    elif source_type == "lesson_task":
        if not any(item.lesson_task_id == source_id for item in lesson_tasks):
            abort(403)
        source_ctx = resolve_workspace_context(actor, "lesson_task", source_id)
        source_state = load_workspace_state_payload(source_ctx)
        source_notes = source_state["notes"]
    elif source_type == "assignment_task":
        if not any(item["assignment_task_id"] == source_id for item in ctx.tasks_nav):
            abort(403)
        source_ctx = resolve_workspace_context(actor, "submission_task", ctx.submission_id, source_id)
        source_state = load_workspace_state_payload(source_ctx)
        source_notes = source_state["notes"]
    else:
        abort(400)
    target_state = load_workspace_state_payload(ctx)
    merged_notes = "\n\n".join(part for part in [target_state["notes"].strip(), source_notes.strip()] if part)[:20_000]
    copied_code = source_state["code"] if source_state and data.get("include_code", True) else target_state["code"]
    save_workspace_version(ctx, copied_code, target_state["answer"], source="transfer", notes=merged_notes)
    if source_state and data.get("include_code", True):
        answer_row = Answer.query.filter_by(submission_id=ctx.submission_id, assignment_task_id=ctx.assignment_task_id).first()
        if not answer_row:
            assignment_task = db.session.get(AssignmentTask, ctx.assignment_task_id)
            answer_row = Answer(
                submission_id=ctx.submission_id,
                assignment_task_id=ctx.assignment_task_id,
                max_score=assignment_task.max_score,
            )
            db.session.add(answer_row)
        answer_row.student_code = copied_code
    if source_ctx is not None:
        source_kind = "lesson" if source_type == "lesson_task" else f"submission_task_{source_id}"
        target_kind = f"submission_task_{ctx.assignment_task_id}"
        source_files = StudentWorkspaceFile.query.filter_by(
            user_id=ctx.student_user_id, task_id=source_ctx.task_id,
            context_type=source_kind, context_id=source_ctx.context_id,
        ).all()
        if not source_files and source_type == "assignment_task" and sum(item["task_id"] == source_ctx.task_id for item in ctx.tasks_nav) == 1:
            source_files = StudentWorkspaceFile.query.filter_by(
                user_id=ctx.student_user_id, task_id=source_ctx.task_id,
                context_type="submission", context_id=ctx.submission_id,
            ).all()
        target_files = StudentWorkspaceFile.query.filter_by(
            user_id=ctx.student_user_id, task_id=ctx.task_id,
            context_type=target_kind, context_id=ctx.submission_id,
        ).all()
        if sum(item["task_id"] == ctx.task_id for item in ctx.tasks_nav) == 1:
            target_files += StudentWorkspaceFile.query.filter_by(
                user_id=ctx.student_user_id, task_id=ctx.task_id,
                context_type="submission", context_id=ctx.submission_id,
            ).all()
        names = {item.current_filename for item in target_files}
        for item in source_files:
            file_bytes = _read_file_bytes(item)
            if file_bytes is None:
                db.session.rollback()
                return jsonify({"success": False, "error": f"Не удалось скопировать файл {item.current_filename}"}), 409
            name = item.current_filename
            if name in names:
                stem, dot, ext = name.rpartition(".")
                stem = stem if dot else name
                ext = "." + ext if dot else ""
                name = f"{stem}-копия-{item.id}{ext}"
            names.add(name)
            storage_path = _write_workspace_bytes(file_bytes, ctx.student_user_id, ctx.task_id, f"{uuid.uuid4().hex}_{name}")
            db.session.add(StudentWorkspaceFile(
                user_id=ctx.student_user_id, task_id=ctx.task_id,
                context_type=target_kind, context_id=ctx.submission_id,
                original_filename=item.original_filename, current_filename=name,
                storage_path=storage_path, file_size=len(file_bytes),
                mime_type=item.mime_type, is_from_task=False,
            ))
        drawing = TaskCanvasDrawing.query.filter_by(
            user_id=ctx.student_user_id, task_id=source_ctx.task_id,
            context_type=source_kind, context_id=source_ctx.context_id,
        ).first()
        if drawing and data.get("include_canvas", True):
            target_drawing = TaskCanvasDrawing.query.filter_by(
                user_id=ctx.student_user_id, task_id=ctx.task_id,
                context_type=target_kind, context_id=ctx.submission_id,
            ).first()
            if not target_drawing:
                target_drawing = TaskCanvasDrawing(
                    user_id=ctx.student_user_id, task_id=ctx.task_id,
                    context_type=target_kind, context_id=ctx.submission_id,
                )
                db.session.add(target_drawing)
            target_drawing.strokes_json = drawing.strokes_json
            target_drawing.thumbnail_url = drawing.thumbnail_url
    db.session.commit()
    return jsonify({"success": True, "message": "Материалы скопированы в пространство задания"})
