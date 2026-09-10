from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from flask import abort

from app.models import db
from app.auth.rbac_utils import get_user_scope
from app.utils.relationship_scope import can_user_access_student
from app.utils.jinja_filters import (
    normalize_task_attachments,
    normalize_task_content_assets,
    prepare_task_content_html,
)
from app.runtime_state import get_json, set_json, delete as redis_delete
from core.db_models import (
    Answer,
    CodePlaybackTrace,
    Assignment,
    AssignmentTask,
    CodeWorkspaceVersion,
    Lesson,
    LessonTask,
    Submission,
    Tasks,
)


MMR_POLICY_LABELS = {
    "manual_confirm": "Учитывать после подтверждения преподавателя",
    "always": "Учитывается в ммр",
    "never": "Не учитывать в ммр",
}

WORKSPACE_AUTOSAVE_DEBOUNCE_SECONDS = 2.0
WORKSPACE_CACHE_TTL_SECONDS = 24 * 60 * 60
ANSWER_TYPES = {"code", "short_answer", "single_choice", "matching", "long_answer"}
WORKSPACE_MODES = {"answer", "code"}


def _normalize_answer_spec(task: Tasks) -> dict[str, Any]:
    """Expose only a safe, validated answer UI contract to the student."""
    raw = getattr(task, "answer_spec", None)
    spec = dict(raw) if isinstance(raw, dict) else {}
    answer_type = str(spec.get("type") or "").strip().lower()
    if answer_type not in ANSWER_TYPES:
        answer_type = "code" if (task.starter_code or "").strip() else "short_answer"

    options = spec.get("options") if isinstance(spec.get("options"), list) else []
    normalized_options = []
    for index, option in enumerate(options[:30], start=1):
        if isinstance(option, dict):
            value = str(option.get("value") or option.get("id") or index).strip()
            label = str(option.get("label") or option.get("text") or value).strip()
        else:
            value = str(option).strip()
            label = value
        if value and label:
            normalized_options.append({"value": value[:500], "label": label[:1000]})

    pairs = spec.get("pairs") if isinstance(spec.get("pairs"), list) else []
    normalized_pairs = []
    for index, pair in enumerate(pairs[:30], start=1):
        if not isinstance(pair, dict):
            continue
        left = str(pair.get("left") or pair.get("label") or "").strip()
        key = str(pair.get("key") or pair.get("id") or chr(64 + index)).strip()
        if left and key:
            normalized_pairs.append({"key": key[:32], "left": left[:1000]})

    if answer_type == "single_choice" and not normalized_options:
        answer_type = "short_answer"
    if answer_type == "matching" and (not normalized_pairs or not normalized_options):
        answer_type = "short_answer"

    raw_modes = spec.get("workspace_modes", spec.get("workspaceModes"))
    modes = []
    if isinstance(raw_modes, (list, tuple)):
        for mode in raw_modes:
            normalized_mode = str(mode or "").strip().lower()
            if normalized_mode in WORKSPACE_MODES and normalized_mode not in modes:
                modes.append(normalized_mode)
    if not modes:
        # Existing EGE cards predate the explicit workspace contract.  Python is
        # a legitimate calculation tool for their standard answers, while an
        # explicit teacher configuration still remains authoritative.
        if raw_modes is None and answer_type != "code":
            modes = ["answer", "code"]
        else:
            modes = ["code"] if answer_type == "code" else ["answer"]

    requested_default = str(
        spec.get("default_workspace_mode", spec.get("defaultWorkspaceMode", ""))
    ).strip().lower()
    default_workspace_mode = requested_default if requested_default in modes else modes[0]

    return {
        "type": answer_type,
        "prompt": str(spec.get("prompt") or "").strip()[:500],
        "placeholder": str(spec.get("placeholder") or "").strip()[:500],
        "options": normalized_options,
        "pairs": normalized_pairs,
        "workspace_modes": modes,
        "default_workspace_mode": default_workspace_mode,
    }


def _visible_task_hints(task: Tasks) -> list[dict[str, str]]:
    """Tasks.hints is teacher-authored data; absent/invalid data produces no UI card."""
    raw = getattr(task, "hints", None)
    values = raw if isinstance(raw, list) else []
    hints = []
    for index, item in enumerate(values[:10], start=1):
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("body") or item.get("hint") or "").strip()
            title = str(item.get("title") or f"Подсказка {index}").strip()
        else:
            text = str(item or "").strip()
            title = f"Подсказка {index}"
        if text:
            hints.append({"title": title[:160], "text": text[:4000]})
    return hints


def _to_aware_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _workspace_cache_key(ctx: "WorkspaceContext") -> str:
    return f"workspace:snapshot:{ctx.context_type}:{ctx.context_id or 'none'}:{ctx.task_id}:{ctx.student_user_id or 'none'}:{ctx.assignment_task_id or 'none'}"


def _workspace_lock_key(ctx: "WorkspaceContext") -> str:
    return f"workspace:autosave:{ctx.context_type}:{ctx.context_id or 'none'}:{ctx.task_id}:{ctx.student_user_id or 'none'}:{ctx.assignment_task_id or 'none'}"


def _workspace_db_state_key(ctx: "WorkspaceContext") -> tuple:
    return (
        ctx.context_type,
        ctx.context_id,
        ctx.task_id,
        ctx.student_user_id,
        ctx.student_id,
        ctx.assignment_task_id,
        ctx.answer_id,
    )


def _workspace_snapshot_payload(
    ctx: "WorkspaceContext",
    code: str,
    answer: str,
    frames=None,
    *,
    source: str = "autosave",
    version: int | None = None,
    ui_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "context_type": ctx.context_type,
        "context_id": ctx.context_id,
        "task_id": ctx.task_id,
        "student_user_id": ctx.student_user_id,
        "student_id": ctx.student_id,
        "lesson_task_id": ctx.lesson_task_id,
        "submission_id": ctx.submission_id,
        "assignment_task_id": ctx.assignment_task_id,
        "answer_id": ctx.answer_id,
        "code": code or "",
        "answer": answer or "",
        "frames": frames or [],
        "source": source,
        "version": int(version or 0),
        "ui_state": ui_state or {},
    }


def cache_workspace_snapshot(
    ctx: "WorkspaceContext",
    code: str,
    answer: str = "",
    frames: list[dict[str, Any]] | None = None,
    *,
    source: str = "autosave",
    version: int | None = None,
    ui_state: dict[str, Any] | None = None,
) -> None:
    try:
        payload = _workspace_snapshot_payload(ctx, code, answer, frames, source=source, version=version, ui_state=ui_state)
        set_json(_workspace_cache_key(ctx), payload, ttl_seconds=WORKSPACE_CACHE_TTL_SECONDS)
    except Exception:
        return


def load_cached_workspace_snapshot(ctx: "WorkspaceContext") -> dict[str, Any] | None:
    try:
        data = get_json(_workspace_cache_key(ctx))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def clear_cached_workspace_snapshot(ctx: "WorkspaceContext") -> None:
    try:
        redis_delete(_workspace_cache_key(ctx))
    except Exception:
        return


@dataclass
class WorkspaceContext:
    context_type: str
    context_id: int | None
    task_id: int
    task: Tasks
    title: str
    subtitle: str
    source_label: str
    return_url: str | None = None
    student_id: int | None = None
    student_user_id: int | None = None
    lesson_task_id: int | None = None
    submission_id: int | None = None
    assignment_task_id: int | None = None
    answer_id: int | None = None
    code: str = ""
    plain_answer: str = ""
    mmr_policy: str = "manual_confirm"
    can_edit: bool = True
    can_review: bool = False
    timer_seconds_left: int | None = None
    mmr_value: int = 1000
    task_position: int | None = None
    task_count: int = 1
    completed_task_count: int = 0
    previous_task: dict[str, Any] | None = None
    next_task: dict[str, Any] | None = None
    assignment_title: str = ""

    def as_payload(self) -> dict[str, Any]:
        answer_spec = _normalize_answer_spec(self.task)
        attachments = normalize_task_attachments(self.task.attached_files)
        return {
            "context_type": self.context_type,
            "context_id": self.context_id,
            "task_id": self.task_id,
            "title": self.title,
            "subtitle": self.subtitle,
            "source_label": self.source_label,
            "assignment_title": self.assignment_title or self.title,
            "return_url": self.return_url,
            "student_id": self.student_id,
            "student_user_id": self.student_user_id,
            "lesson_task_id": self.lesson_task_id,
            "submission_id": self.submission_id,
            "assignment_task_id": self.assignment_task_id,
            "answer_id": self.answer_id,
            "code": self.code,
            "plain_answer": self.plain_answer,
            "starter_code": self.task.starter_code or "",
            "presentation_mode": "code" if answer_spec["default_workspace_mode"] == "code" else "standard",
            "answer_spec": answer_spec,
            "hints": _visible_task_hints(self.task),
            "attachments": attachments,
            "max_score": int(self.task.max_score or 1),
            "task_number": self.task.task_number,
            "difficulty": self.task.difficulty_label,
            "content_html": normalize_task_content_assets(
                prepare_task_content_html(self.task.content_html or ""),
                self.task.attached_files,
                self.task.source_url,
            ),
            "mmr_policy": self.mmr_policy,
            "mmr_policy_label": MMR_POLICY_LABELS.get(self.mmr_policy, MMR_POLICY_LABELS["manual_confirm"]),
            "can_edit": self.can_edit,
            "can_review": self.can_review,
            "timer_seconds_left": self.timer_seconds_left,
            "mmr_value": self.mmr_value,
            "task_position": self.task_position,
            "task_count": self.task_count,
            "completed_task_count": self.completed_task_count,
            "previous_task": self.previous_task,
            "next_task": self.next_task,
            "answer_hint": self.task.answer or "",
            "playback": load_workspace_trace_payload(self),
            "versions": load_workspace_versions_payload(self),
        }


def _has_teacher_scope(user) -> bool:
    scope = get_user_scope(user)
    return bool(
        scope.get("can_see_all")
        or getattr(user, "is_creator", lambda: False)()
        or getattr(user, "is_admin", lambda: False)()
        or getattr(user, "is_chief_admin", lambda: False)()
        or getattr(user, "is_tutor", lambda: False)()
    )


def _resolve_lesson_task_context(user, lesson_task_id: int) -> WorkspaceContext:
    lesson_task = (
        LessonTask.query.options(
            db.joinedload(LessonTask.task),
            db.joinedload(LessonTask.lesson).joinedload(Lesson.student),
        )
        .filter_by(lesson_task_id=lesson_task_id)
        .first_or_404()
    )
    lesson = lesson_task.lesson
    student = lesson.student if lesson else None
    if not student or not can_user_access_student(user, student_user_id=student.user_id):
        abort(403)
    is_student_owner = getattr(user, "is_student", lambda: False)() and user.id == student.user_id
    can_review = _has_teacher_scope(user)
    is_parent = getattr(user, "is_parent", lambda: False)()
    can_edit = is_student_owner and (lesson_task.status or "pending") in {"pending", "returned", "assigned", "in_progress"} and not is_parent
    mmr_policy = "manual_confirm"
    if (lesson_task.assignment_type or "homework") != "classwork":
        mmr_policy = "always"
    return WorkspaceContext(
        context_type="lesson_task",
        context_id=lesson_task.lesson_task_id,
        task_id=lesson_task.task_id,
        task=lesson_task.task,
        title=f"{'Классная работа' if lesson_task.assignment_type == 'classwork' else 'Задание урока'} · задача #{lesson_task.task_id}",
        subtitle=f"Урок #{lesson.lesson_id} · {student.user.username if student.user else 'ученик'}",
        source_label="Урок / классная работа",
        assignment_title=(lesson.title if lesson and getattr(lesson, "title", None) else "Задание урока"),
        return_url=f"/lesson/{lesson.lesson_id}/classwork-tasks",
        student_id=student.student_id,
        student_user_id=student.user_id,
        lesson_task_id=lesson_task.lesson_task_id,
        code=lesson_task.student_submission or lesson_task.task.starter_code or "",
        plain_answer=lesson_task.student_answer or "",
        mmr_policy=mmr_policy,
        can_edit=can_edit,
        can_review=can_review,
    )


def _resolve_submission_task_context(user, submission_id: int, assignment_task_id: int) -> WorkspaceContext:
    submission = (
        Submission.query.options(
            db.joinedload(Submission.assignment).joinedload(Assignment.tasks).joinedload(AssignmentTask.task),
            db.joinedload(Submission.answers),
            db.joinedload(Submission.student),
        )
        .filter_by(submission_id=submission_id)
        .first_or_404()
    )
    student = submission.student
    if not student:
        abort(404)
    is_owner = getattr(user, "is_student", lambda: False)() and user.id == student.user_id
    if not is_owner and not can_user_access_student(user, student_user_id=student.user_id):
        abort(403)
    assignment_task = next(
        (item for item in submission.assignment.tasks if item.assignment_task_id == assignment_task_id),
        None,
    )
    if not assignment_task:
        abort(404)
    answer = next(
        (item for item in (submission.answers or []) if item.assignment_task_id == assignment_task.assignment_task_id),
        None,
    )
    can_review = _has_teacher_scope(user)
    is_parent = getattr(user, "is_parent", lambda: False)()
    normalized_status = (submission.status or "").strip().upper()
    # Открытие Workspace — это начало работы. Нельзя показывать ученику редактор,
    # а затем бесконечно отвечать 403 на его автосохранения до отдельного клика «Старт».
    can_edit = is_owner and normalized_status in {"ASSIGNED", "IN_PROGRESS", "RETURNED"} and not is_parent
    if can_edit and normalized_status == "RETURNED":
        revision_task_ids = {
            int(item.assignment_task_id)
            for item in (submission.answers or [])
            if getattr(item, "needs_revision", False) and getattr(item, "assignment_task_id", None) is not None
        }
        # Historical returned submissions did not have per-task flags and
        # intentionally remain fully editable. New returns reopen only the
        # tasks explicitly selected by the teacher.
        if revision_task_ids:
            can_edit = int(assignment_task.assignment_task_id) in revision_task_ids

    timer_seconds_left = None
    if normalized_status != "RETURNED" and submission.started_at and submission.assignment.time_limit_minutes:
        from core.db_models import utc_now
        limit_sec = submission.assignment.time_limit_minutes * 60
        started_at = _to_aware_utc(submission.started_at)
        elapsed = (_to_aware_utc(utc_now()) - started_at).total_seconds() if started_at else 0
        timer_seconds_left = max(0, int(limit_sec - elapsed))

    ordered_tasks = sorted(submission.assignment.tasks or [], key=lambda item: (item.order_index, item.assignment_task_id))
    current_index = next(
        (index for index, item in enumerate(ordered_tasks) if item.assignment_task_id == assignment_task.assignment_task_id),
        0,
    )
    completed_task_ids = {
        int(item.assignment_task_id)
        for item in (submission.answers or [])
        if getattr(item, "assignment_task_id", None) is not None
        and (str(getattr(item, "value", "") or "").strip() or str(getattr(item, "student_code", "") or "").strip())
    }

    def navigation_item(item: AssignmentTask) -> dict[str, Any]:
        return {
            "assignment_task_id": item.assignment_task_id,
            "task_id": item.task_id,
            "position": next(index + 1 for index, candidate in enumerate(ordered_tasks) if candidate.assignment_task_id == item.assignment_task_id),
            "title": (item.task.title if item.task and getattr(item.task, "title", None) else f"Задача {item.task_id}"),
        }

    return WorkspaceContext(
        context_type="submission_task",
        context_id=submission.submission_id,
        task_id=assignment_task.task_id,
        task=assignment_task.task,
        title=f"{submission.assignment.title} · задача #{assignment_task.task_id}",
        subtitle=f"{student.user.username if student.user else 'ученик'} · {submission.assignment.assignment_type}",
        source_label="Работа / задание",
        assignment_title=submission.assignment.title or "Работа",
        return_url="/submissions",
        student_id=student.student_id,
        student_user_id=student.user_id,
        submission_id=submission.submission_id,
        assignment_task_id=assignment_task.assignment_task_id,
        answer_id=answer.answer_id if answer else None,
        code=(answer.student_code if answer else "") or assignment_task.task.starter_code or "",
        plain_answer=(answer.value if answer else "") or "",
        mmr_policy="always",
        can_edit=can_edit,
        can_review=can_review,
        timer_seconds_left=timer_seconds_left,
        task_position=current_index + 1,
        task_count=len(ordered_tasks),
        completed_task_count=len(completed_task_ids),
        previous_task=navigation_item(ordered_tasks[current_index - 1]) if current_index > 0 else None,
        next_task=navigation_item(ordered_tasks[current_index + 1]) if current_index + 1 < len(ordered_tasks) else None,
    )


def resolve_workspace_context(user, context_type: str, context_id: int | None = None, assignment_task_id: int | None = None) -> WorkspaceContext:
    kind = (context_type or "").strip().lower()
    if kind == "lesson_task":
        if context_id is None:
            abort(400, "Не указан lesson_task_id")
        ctx = _resolve_lesson_task_context(user, int(context_id))
    elif kind == "submission_task":
        if context_id is None or assignment_task_id is None:
            abort(400, "Не указаны submission_id / assignment_task_id")
        ctx = _resolve_submission_task_context(user, int(context_id), int(assignment_task_id))
    elif kind == "demo":
        abort(404, "Демонстрационный workspace недоступен в живой платформе")
    else:
        abort(404, "Неизвестный тип workspace")

    # Вычисляем текущий MMR
    if user and user.is_authenticated and ctx.task and ctx.task.task_number:
        from core.db_models import UserTaskMMR
        try:
            mmr_row = UserTaskMMR.query.filter_by(user_id=user.id, task_type=int(ctx.task.task_number or 0)).first()
            ctx.mmr_value = int(mmr_row.mmr) if mmr_row else 1000
        except Exception:
            ctx.mmr_value = 1000
    else:
        ctx.mmr_value = 1000

    return ctx


def save_workspace_code(ctx: WorkspaceContext, code: str, answer: str = "", frames: list[dict[str, Any]] | None = None) -> None:
    code = (code or "")[:100_000]
    answer = (answer or "")[:20_000]
    try:
        if ctx.context_type == "lesson_task" and ctx.lesson_task_id:
            lesson_task = LessonTask.query.get_or_404(ctx.lesson_task_id)
            lesson_task.student_submission = code
            lesson_task.student_answer = answer
            save_workspace_trace(ctx, frames=frames, meta={"source": "server-save", "code_length": len(code), "answer_length": len(answer)})
            save_workspace_version(ctx, code=code, answer=answer, source="manual" if frames else "autosave")
            cache_workspace_snapshot(ctx, code, answer, frames=frames, source="manual" if frames else "autosave")
            db.session.commit()
            return
        if ctx.context_type == "submission_task" and ctx.submission_id and ctx.assignment_task_id:
            submission = Submission.query.get_or_404(ctx.submission_id)
            if (submission.status or "").strip().upper() == "ASSIGNED":
                from core.db_models import utc_now
                submission.status = "IN_PROGRESS"
                submission.started_at = submission.started_at or utc_now()
            answer_row = Answer.query.filter_by(
                submission_id=ctx.submission_id,
                assignment_task_id=ctx.assignment_task_id,
            ).first()
            if not answer_row:
                assignment_task = AssignmentTask.query.get_or_404(ctx.assignment_task_id)
                answer_row = Answer(
                    submission_id=ctx.submission_id,
                    assignment_task_id=ctx.assignment_task_id,
                    max_score=assignment_task.max_score,
                )
                db.session.add(answer_row)
            answer_row.student_code = code
            answer_row.value = answer
            from core.db_models import utc_now

            answer_row.student_code_saved_at = utc_now()
            save_workspace_trace(
                ctx,
                frames=frames,
                meta={"source": "server-save", "code_length": len(code), "answer_length": len(answer)},
            )
            save_workspace_version(ctx, code=code, answer=answer, source="manual" if frames else "autosave")
            cache_workspace_snapshot(ctx, code, answer, frames=frames, source="manual" if frames else "autosave")
            db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def save_workspace_draft(ctx: WorkspaceContext, code: str, answer: str = "", frames: list[dict[str, Any]] | None = None) -> None:
    """Persist workspace draft/history without changing the student's submitted answer."""
    code = (code or "")[:100_000]
    answer = (answer or "")[:20_000]
    try:
        save_workspace_trace(ctx, frames=frames, meta={"source": "workspace-draft", "code_length": len(code), "answer_length": len(answer)})
        save_workspace_version(ctx, code=code, answer=answer, source="draft")
        cache_workspace_snapshot(ctx, code, answer, frames=frames, source="draft")
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def _trace_lookup(ctx: WorkspaceContext):
    query = CodePlaybackTrace.query.filter_by(
        context_type=ctx.context_type,
        context_id=ctx.context_id,
        task_id=ctx.task_id,
    )
    if ctx.context_type == "submission_task" and ctx.answer_id:
        query = query.filter(db.or_(CodePlaybackTrace.answer_id == ctx.answer_id, CodePlaybackTrace.answer_id.is_(None)))
    if ctx.student_id:
        query = query.filter_by(student_id=ctx.student_id)
    return query.order_by(CodePlaybackTrace.updated_at.desc(), CodePlaybackTrace.trace_id.desc())


def load_workspace_trace_payload(ctx: WorkspaceContext) -> dict[str, Any]:
    try:
        trace = _trace_lookup(ctx).first()
    except Exception:
        return {"trace_id": None, "frames": [], "meta": {}, "updated_at": None, "frame_count": 0}
    if not trace:
        return {"trace_id": None, "frames": [], "meta": {}, "updated_at": None}
    frames = trace.frames or []
    return {
        "trace_id": trace.trace_id,
        "frames": frames,
        "meta": trace.meta or {},
        "updated_at": trace.updated_at.isoformat() if trace.updated_at else None,
        "frame_count": len(frames),
    }


def save_workspace_trace(ctx: WorkspaceContext, frames: list[dict[str, Any]] | None = None, meta: dict[str, Any] | None = None) -> CodePlaybackTrace:
    try:
        trace = _trace_lookup(ctx).first()
    except Exception:
        trace = None
    if not trace:
        trace = CodePlaybackTrace(
            context_type=ctx.context_type,
            context_id=ctx.context_id,
            task_id=ctx.task_id,
            student_user_id=ctx.student_user_id,
            student_id=ctx.student_id,
            answer_id=ctx.answer_id,
            frames=frames or [],
            meta=meta or {},
        )
        db.session.add(trace)
    else:
        if frames is not None:
            trace.frames = frames
        if meta:
            merged = dict(trace.meta or {})
            merged.update(meta)
            trace.meta = merged
    return trace


def _version_lookup(ctx: WorkspaceContext):
    query = CodeWorkspaceVersion.query.filter_by(
        context_type=ctx.context_type,
        context_id=ctx.context_id,
        task_id=ctx.task_id,
    )
    if ctx.context_type == "submission_task" and ctx.answer_id:
        query = query.filter(db.or_(CodeWorkspaceVersion.answer_id == ctx.answer_id, CodeWorkspaceVersion.answer_id.is_(None)))
    if ctx.student_id:
        query = query.filter_by(student_id=ctx.student_id)
    return query.order_by(CodeWorkspaceVersion.created_at.desc(), CodeWorkspaceVersion.version_id.desc())


def load_workspace_versions_payload(ctx: WorkspaceContext) -> dict[str, Any]:
    try:
        versions = _version_lookup(ctx).limit(20).all()
    except Exception:
        return {"items": [], "count": 0}
    items = []
    for version in versions:
        items.append({
            "version_id": version.version_id,
            "created_at": version.created_at.isoformat() if version.created_at else None,
            "source": version.source,
            "code": version.code or "",
            "answer": version.answer or "",
            "preview": (version.code or "")[:240],
        })
    return {"items": items, "count": len(items)}


def restore_workspace_version(ctx: WorkspaceContext, version_id: int) -> dict[str, Any]:
    """Restore an owned workspace version as a new, auditable snapshot."""
    version = _version_lookup(ctx).filter_by(version_id=int(version_id)).first()
    if not version:
        abort(404, "Версия Workspace не найдена")
    code = version.code or ""
    answer = version.answer or ""
    save_workspace_code(ctx, code, answer)
    save_workspace_version(ctx, code=code, answer=answer, source="restore")
    cache_workspace_snapshot(ctx, code, answer, source="restore")
    db.session.commit()
    return {"code": code, "answer": answer, "versions": load_workspace_versions_payload(ctx)}


def load_workspace_state_payload(ctx: WorkspaceContext) -> dict[str, Any]:
    """Return the latest authoritative workspace snapshot for live collaboration."""
    try:
        from .socket import get_workspace_live_state
        live_state = get_workspace_live_state(ctx)
    except Exception:
        live_state = {}

    latest_version = None
    try:
        latest_version = _version_lookup(ctx).first()
    except Exception:
        latest_version = None

    trace_payload = load_workspace_trace_payload(ctx)
    cached_state = load_cached_workspace_snapshot(ctx) or {}

    code = live_state.get("code") or cached_state.get("code") or ctx.code or ""
    answer = live_state.get("answer") or cached_state.get("answer") or ctx.plain_answer or ""
    ui_state = live_state.get("ui_state") or cached_state.get("ui_state") or {}
    updated_at = live_state.get("updated_at") or cached_state.get("updated_at")
    version_id = live_state.get("version_id") or cached_state.get("version_id")
    source = live_state.get("source") or cached_state.get("source")
    version = max(int(live_state.get("version") or 0), int(cached_state.get("version") or 0))

    if latest_version and not live_state:
        code = latest_version.code or code
        answer = latest_version.answer or answer
        updated_at = latest_version.created_at.isoformat() if latest_version.created_at else None
        version_id = latest_version.version_id
        source = latest_version.source
    elif latest_version:
        version_id = version_id or latest_version.version_id
        source = source or latest_version.source

    return {
        "context_type": ctx.context_type,
        "context_id": ctx.context_id,
        "task_id": ctx.task_id,
        "code": code,
        "answer": answer,
        "updated_at": updated_at,
        "version_id": version_id,
        "source": source,
        "version": version,
        "ui_state": ui_state,
        "versions": load_workspace_versions_payload(ctx),
        "playback": trace_payload,
    }


def save_workspace_version(ctx: WorkspaceContext, code: str, answer: str = "", source: str = "autosave") -> CodeWorkspaceVersion:
    try:
        version = CodeWorkspaceVersion(
            context_type=ctx.context_type,
            context_id=ctx.context_id,
            student_user_id=ctx.student_user_id,
            student_id=ctx.student_id,
            task_id=ctx.task_id,
            answer_id=ctx.answer_id,
            code=code or "",
            answer=answer or "",
            source=source or "autosave",
            snapshot={
                "code_length": len(code or ""),
                "answer_length": len(answer or ""),
                "mmr_policy": ctx.mmr_policy,
            },
        )
        db.session.add(version)
        return version
    except Exception:
        return None


def autosave_workspace_snapshot(
    ctx: WorkspaceContext,
    code: str,
    answer: str = "",
    frames: list[dict[str, Any]] | None = None,
    *,
    source: str = "autosave",
    ui_state: dict[str, Any] | None = None,
) -> None:
    """
    Best-effort autosave. Writes to Redis immediately and to PostgreSQL as a
    workspace draft. It must not silently turn collaborative code into a
    submitted lesson/submission answer.
    """
    cache_workspace_snapshot(ctx, code, answer, frames=frames, source=source, ui_state=ui_state)
    try:
        save_workspace_draft(ctx, code, answer=answer, frames=frames)
    except Exception:
        # The caller already has Redis state; DB flush can be retried later.
        return
