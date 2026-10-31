from __future__ import annotations

import re
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
from app.task_bank.answer_safety import student_safe_content_html
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
ANSWER_TYPES = {"code", "short_answer", "single_choice", "multiple_choice", "matching", "long_answer"}
WORKSPACE_MODES = {"answer", "code", "canvas"}


def _normalize_assignment_task_heading(content_html: str, assignment_type: str | None) -> str:
    label = {
        "homework": "Домашняя",
        "classwork": "Классная",
    }.get(str(assignment_type or "").strip().lower())
    if not label:
        return content_html

    return re.sub(
        r"(?i)(>\s*)(?:классная|домашняя)(\s+работа)?(\s*[·•:—-])",
        lambda match: f"{match.group(1)}{label}{match.group(2) or ''}{match.group(3)}",
        content_html,
        count=1,
    )


def _normalize_answer_spec(task: Tasks) -> dict[str, Any]:
    """Expose only a safe, validated answer UI contract to the student."""
    raw = getattr(task, "answer_spec", None)
    spec = dict(raw) if isinstance(raw, dict) else {}
    answer_type = str(spec.get("type") or "").strip().lower()
    has_expected_answer = bool((getattr(task, "answer", None) or "").strip())
    if answer_type not in ANSWER_TYPES:
        if getattr(task, "task_type", None) == "code":
            answer_type = "code"
        elif (task.starter_code or "").strip():
            answer_type = "code"
        elif has_expected_answer:
            answer_type = "long_answer" if "\n" in (getattr(task, "answer", None) or "").strip() else "short_answer"
        else:
            answer_type = "short_answer"

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
    if answer_type == "multiple_choice" and not normalized_options:
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
        # Existing EGE cards predate the explicit workspace contract. Python is
        # a legitimate calculation tool for their standard answers, while an
        # explicit teacher configuration still remains authoritative.
        if raw_modes is None:
            modes = ["answer", "code"]
        elif has_expected_answer or answer_type != "code":
            modes = ["answer", "code"]
        else:
            modes = ["code"] if answer_type == "code" else ["answer"]

    if "canvas" not in modes:
        modes.append("canvas")

    # Even if raw_modes was somehow limited to code only, if task has an expected answer,
    # student must not be deprived of entering their answer!
    if has_expected_answer and "answer" not in modes:
        modes.insert(0, "answer")

    requested_default = str(
        spec.get("default_workspace_mode", spec.get("defaultWorkspaceMode", ""))
    ).strip().lower()
    if requested_default in modes:
        default_workspace_mode = requested_default
    elif (task.starter_code or "").strip() and "code" in modes:
        default_workspace_mode = "code"
    elif "answer" in modes:
        default_workspace_mode = "answer"
    else:
        default_workspace_mode = modes[0]

    return {
        "type": answer_type,
        "grading_mode": "manual" if str(spec.get("grading_mode") or "").lower() == "manual" else "auto",
        "language": str(spec.get("language") or "python").strip()[:32],
        "prompt": str(spec.get("prompt") or "").strip()[:500],
        "placeholder": str(spec.get("placeholder") or "").strip()[:500],
        "options": normalized_options,
        "pairs": normalized_pairs,
        "workspace_modes": modes,
        "default_workspace_mode": default_workspace_mode,
        "has_expected_answer": has_expected_answer,
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
    revision: int | None = None,
    files: dict[str, Any] | None = None,
    open_tabs: list[str] | None = None,
    active_file: str | None = None,
    ui_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clean_files = dict(files) if isinstance(files, dict) and files else {}
    if "main.py" not in clean_files:
        clean_files["main.py"] = code if (not active_file or active_file == "main.py") else ""
    clean_tabs = [str(t) for t in open_tabs if str(t) in clean_files] if isinstance(open_tabs, list) and open_tabs else []
    if not clean_tabs:
        clean_tabs = ["main.py"] if "main.py" in clean_files else list(clean_files.keys())[:1]
    clean_active = str(active_file) if (active_file and active_file in clean_files) else clean_tabs[0]
    if clean_active in clean_files and code is not None:
        clean_files[clean_active] = code
    rev = int(revision or version or 1)
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
        "version": rev,
        "revision": rev,
        "files": clean_files,
        "open_tabs": clean_tabs,
        "active_file": clean_active,
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
    revision: int | None = None,
    files: dict[str, Any] | None = None,
    open_tabs: list[str] | None = None,
    active_file: str | None = None,
    ui_state: dict[str, Any] | None = None,
) -> None:
    try:
        payload = _workspace_snapshot_payload(
            ctx, code, answer, frames,
            source=source, version=version, revision=revision,
            files=files, open_tabs=open_tabs, active_file=active_file,
            ui_state=ui_state
        )
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


def _safe_parse_json(val: Any) -> Any:
    if not val or not isinstance(val, str):
        return None
    try:
        import json
        return json.loads(val)
    except Exception:
        return None


def _render_task_solution(raw_text: str | None) -> str:
    if not raw_text or not raw_text.strip():
        return ""
    text = raw_text.strip()
    try:
        import markdown
        if "```" not in text and any(text.startswith(kw) for kw in ("import ", "from ", "def ", "for ", "with ", "while ", "print(")):
            text = f"```python\n{text}\n```"
        return markdown.markdown(text, extensions=["fenced_code", "tables"])
    except Exception:
        import html
        return f"<pre><code>{html.escape(text)}</code></pre>"


def _extract_task_correct_answer(task: Tasks | None, answer_override: str | None = None) -> str:
    if answer_override and str(answer_override).strip():
        return str(answer_override).strip()
    if not task:
        return ""
    if task.answer and str(task.answer).strip():
        return str(task.answer).strip()

    spec = getattr(task, "answer_spec", None)
    if isinstance(spec, dict):
        correct_values = spec.get("correct_values")
        if isinstance(correct_values, (list, tuple)):
            values = sorted({str(value).strip() for value in correct_values if str(value).strip()})
            if values:
                import json
                return json.dumps(values, ensure_ascii=False)
        if spec.get("correct_value") is not None and str(spec.get("correct_value")).strip():
            return str(spec.get("correct_value")).strip()
        if spec.get("correct_answer") is not None and str(spec.get("correct_answer")).strip():
            return str(spec.get("correct_answer")).strip()
        if spec.get("answer") is not None and str(spec.get("answer")).strip():
            return str(spec.get("answer")).strip()
        pairs = spec.get("pairs")
        if isinstance(pairs, list):
            pairs_map = {}
            for p in pairs:
                if isinstance(p, dict) and p.get("key") and (p.get("correct_value") or p.get("value")):
                    pairs_map[str(p["key"])] = str(p.get("correct_value") or p.get("value"))
            if pairs_map:
                import json
                return json.dumps(pairs_map, ensure_ascii=False)
    return ""


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
    tasks_nav: list[dict[str, Any]] | None = None
    submission_meta: dict[str, Any] | None = None
    task_meta: dict[str, Any] | None = None
    is_reviewed: bool = False
    is_manual: bool = False
    answer_score: int | None = None
    answer_max_score: int = 1
    nav_status: str = "unanswered"
    teacher_comment: str | None = None
    submission_teacher_feedback: str | None = None
    correct_answer: str | None = None
    solution_html: str | None = None
    solution_code: str | None = None
    parsed_answer: Any = None
    parsed_correct_answer: Any = None
    linked_lesson_id: int | None = None
    is_task_correct: bool = False
    is_published: bool = False
    answer_visibility_allowed: bool | None = None
    needs_revision: bool = False
    submission_can_submit: bool = True
    has_saved_code: bool = False

    def as_payload(self) -> dict[str, Any]:
        answer_spec = _normalize_answer_spec(self.task) if self.task else {"default_workspace_mode": "code", "fields": []}
        attachments = normalize_task_attachments(self.task.attached_files) if self.task else []
        is_python_bank = bool(self.task and getattr(self.task, "bank_category", "exam") == "python_practice")
        safe_task_meta = dict(self.task_meta or {})
        if is_python_bank and not self.can_review:
            safe_task_meta.pop("topics", None)
            safe_task_meta.pop("difficulty_label", None)
        # Teacher review has its own permission. An explicit lesson answer rule
        # takes precedence over a student's grading state.
        if self.can_review:
            can_see_solution = True
        elif self.answer_visibility_allowed is not None:
            can_see_solution = bool(self.answer_visibility_allowed and not self.needs_revision)
        elif self.context_type == "submission_task":
            can_see_solution = bool(
                not self.needs_revision and (
                    self.is_task_correct or (self.is_published and self.is_reviewed)
                )
            )
        else:
            can_see_solution = bool(not self.needs_revision and (self.is_task_correct or (self.is_published and self.is_reviewed)))

        safe_correct_answer = (self.correct_answer or _extract_task_correct_answer(self.task) or "") if (can_see_solution and self.task) else ""
        safe_solution_html = (self.solution_html or "") if can_see_solution else ""
        safe_solution_code = (self.solution_code or "") if can_see_solution else ""
        content_html, answer_disclosed_in_example = student_safe_content_html(
            self.task.content_html if self.task else "",
            self.correct_answer or (_extract_task_correct_answer(self.task) if self.task else ""),
            allow_review_details=can_see_solution,
        )
        safe_content_html = normalize_task_content_assets(
            prepare_task_content_html(content_html),
            self.task.attached_files,
            self.task.source_url,
        ) if self.task and not answer_disclosed_in_example else content_html
        if self.context_type == "submission_task" and self.submission_meta:
            safe_content_html = _normalize_assignment_task_heading(
                safe_content_html,
                self.submission_meta.get("assignment_type"),
            )
        safe_parsed_correct_answer = None
        if can_see_solution:
            safe_parsed_correct_answer = self.parsed_correct_answer or _safe_parse_json(safe_correct_answer)
        safe_task_meta["correct_answer"] = safe_correct_answer if can_see_solution else ""

        ws_files = load_workspace_multi_file_state(self)
        ws_state = load_workspace_state_payload(self)
        return {
            "context_type": self.context_type,
            "context_id": self.context_id,
            "task_id": self.task_id,
            "title": self.title,
            "subtitle": self.subtitle,
            "source_label": self.source_label if self.can_review or not is_python_bank else None,
            "assignment_title": self.assignment_title or self.title,
            "return_url": self.return_url,
            "student_id": self.student_id,
            "student_user_id": self.student_user_id,
            "lesson_task_id": self.lesson_task_id,
            "submission_id": self.submission_id,
            "assignment_task_id": self.assignment_task_id,
            "linked_lesson_id": self.linked_lesson_id,
            "answer_id": self.answer_id,
            "code": self.code,
            "plain_answer": self.plain_answer,
            "starter_code": (self.task.starter_code or "") if self.task else "",
            "presentation_mode": "code" if answer_spec.get("default_workspace_mode") == "code" else "standard",
            "answer_spec": answer_spec,
            "hints": _visible_task_hints(self.task) if self.task else [],
            "attachments": attachments,
            "max_score": int(self.task.max_score or 1) if self.task else 1,
            "task_number": None if is_python_bank else self.task.task_number if self.task else None,
            "task_title": str(getattr(self.task, "title", "") or "").strip() if self.task else "",
            "difficulty": getattr(self.task, "difficulty_label", "") if self.task and (self.can_review or not is_python_bank) else "",
            "content_html": safe_content_html,
            "task_content_blocked": answer_disclosed_in_example,
            "mmr_policy": self.mmr_policy,
            "mmr_policy_label": MMR_POLICY_LABELS.get(self.mmr_policy, MMR_POLICY_LABELS["manual_confirm"]),
            "can_edit": self.can_edit,
            "submission_can_submit": self.submission_can_submit,
            "can_review": self.can_review,
            "can_see_solution": can_see_solution,
            "is_task_correct": self.is_task_correct,
            "is_published": self.is_published,
            "needs_revision": self.needs_revision,
            "is_reviewed": self.is_reviewed,
            "is_manual": self.is_manual,
            "answer_score": self.answer_score,
            "answer_max_score": self.answer_max_score,
            "nav_status": self.nav_status,
            "timer_seconds_left": self.timer_seconds_left,
            "mmr_value": self.mmr_value,
            "task_position": self.task_position,
            "task_count": self.task_count,
            "completed_task_count": self.completed_task_count,
            "previous_task": self.previous_task,
            "next_task": self.next_task,
            "tasks_nav": self.tasks_nav or [],
            "submission_meta": self.submission_meta or {},
            "task_meta": safe_task_meta,
            "answer_hint": safe_correct_answer,
            "correct_answer": safe_correct_answer,
            "teacher_comment": self.teacher_comment or "",
            "submission_teacher_feedback": self.submission_teacher_feedback or "",
            "solution_html": safe_solution_html,
            "solution_code": safe_solution_code,
            "parsed_answer": self.parsed_answer,
            "parsed_correct_answer": safe_parsed_correct_answer,
            "task": {
                "answer": safe_correct_answer,
            },
            "playback": load_workspace_trace_payload(self),
            "versions": load_workspace_versions_payload(self),
            "workspace_files": ws_files,
            "workspace_state": ws_state,
            "files": ws_files.get("files", {}),
            "archived_files": {
                fname: fcontent
                for fname, fcontent in (ws_files.get("files") or {}).items()
                if fname != "main.py"
            },
            "has_saved_code": self.has_saved_code,
            "open_tabs": ws_files.get("open_tabs", ["main.py"]),
            "active_file": ws_files.get("active_file", "main.py"),
            "revision": ws_files.get("revision", 1),
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


def _explicit_lesson_answer_visibility(
    *,
    student_id: int | None,
    lesson_id: int | None,
    task_id: int | None,
    assignment_type: str | None,
    is_error_review: bool = False,
) -> bool | None:
    """Return the explicit answer rule for an exact student/lesson/task link."""
    if not student_id or not lesson_id or not task_id:
        return None

    from core.db_models import Lesson

    links = (
        LessonTask.query.join(Lesson, Lesson.lesson_id == LessonTask.lesson_id)
        .filter(
            Lesson.student_id == int(student_id),
            Lesson.lesson_id == int(lesson_id),
            LessonTask.task_id == int(task_id),
            LessonTask.assignment_type == str(assignment_type or "homework"),
            LessonTask.is_error_review == bool(is_error_review),
        )
        .all()
    )
    if not links:
        return None
    return all(bool(link.is_answer_visible_to_student) for link in links)


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
    if is_student_owner and not bool(lesson_task.is_visible_to_student):
        abort(404)
    is_parent = getattr(user, "is_parent", lambda: False)()
    is_editable_status = (lesson_task.status or "pending") in {"pending", "returned", "assigned", "in_progress"}
    can_edit = ((is_student_owner and is_editable_status) or can_review) and not is_parent
    mmr_policy = "manual_confirm"
    if (lesson_task.assignment_type or "homework") != "classwork":
        mmr_policy = "always"
    lesson_sol = getattr(lesson_task.task, "task_solution", None) if lesson_task and lesson_task.task else None
    lesson_sol_text = getattr(lesson_sol, "solution_text", "") or ""
    lesson_sol_html = _render_task_solution(lesson_sol_text) if lesson_sol_text else ""
    lesson_correct_ans = _extract_task_correct_answer(lesson_task.task) if lesson_task else ""
    lesson_reviewed_at = getattr(lesson_task, "reviewed_at", None)
    lesson_is_reviewed = bool(lesson_reviewed_at is not None or (lesson_task.status or "") in {"graded", "reviewed", "completed", "accepted"})
    lesson_answer_score = getattr(lesson_task, "score", None)
    task_max = lesson_task.task.max_score if lesson_task and lesson_task.task and hasattr(lesson_task.task, "max_score") else 1
    lesson_max_score = int(getattr(lesson_task, "max_score", None) or task_max or 1)
    lesson_is_correct = bool(lesson_answer_score is not None and lesson_answer_score >= lesson_max_score and lesson_max_score > 0)

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
        is_task_correct=lesson_is_correct,
        is_published=bool(lesson_task.is_visible_to_student),
        answer_visibility_allowed=bool(lesson_task.is_answer_visible_to_student),
        needs_revision=False,
        is_reviewed=lesson_is_reviewed,
        answer_score=lesson_answer_score,
        answer_max_score=lesson_max_score,
        teacher_comment=lesson_task.teacher_comment or "",
        correct_answer=lesson_correct_ans,
        solution_html=lesson_sol_html,
        parsed_answer=_safe_parse_json(lesson_task.student_answer),
        parsed_correct_answer=_safe_parse_json(lesson_correct_ans),
    )


def _is_task_manual_review(t_at: AssignmentTask | None, t_t: Tasks | None) -> bool:
    if t_at and getattr(t_at, "requires_manual_grading", False):
        return True
    if not t_t:
        return False
    raw_spec = getattr(t_t, "answer_spec", None)
    if isinstance(raw_spec, dict):
        if raw_spec.get("type") == "code":
            return str(raw_spec.get("grading_mode") or "manual").lower() != "auto"
        if raw_spec.get("type") == "long_answer":
            return True
    if getattr(t_t, "verification_type", None) == "manual":
        return True
    if getattr(t_t, "task_type", None) in {"code", "long_answer"}:
        return True
    try:
        norm_spec = _normalize_answer_spec(t_t)
        if norm_spec.get("type") in {"code", "long_answer"}:
            return True
    except Exception:
        pass
    if isinstance(raw_spec, dict) and raw_spec.get("type") in {"code", "long_answer"}:
        return True
    if t_t.course_id is not None and t_t.task_number is not None:
        try:
            from core.db_models import CourseTaskTemplate
            tpl = CourseTaskTemplate.query.filter_by(
                course_id=t_t.course_id,
                task_number=t_t.task_number,
            ).first()
            if tpl and getattr(tpl, "requires_manual_review", False):
                return True
        except Exception:
            pass
    return False


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
    answer_visibility_allowed = _explicit_lesson_answer_visibility(
        student_id=student.student_id,
        lesson_id=getattr(submission.assignment, "lesson_id", None),
        task_id=getattr(assignment_task, "task_id", None),
        assignment_type=getattr(submission.assignment, "assignment_type", None),
        is_error_review=getattr(assignment_task, "is_error_review", False),
    )
    answer = next(
        (item for item in (submission.answers or []) if item.assignment_task_id == assignment_task.assignment_task_id),
        None,
    )
    can_review = _has_teacher_scope(user)
    is_parent = getattr(user, "is_parent", lambda: False)()
    normalized_status = (submission.status or "").strip().upper()
    # Открытие Workspace — это начало работы. Нельзя показывать ученику редактор,
    # а затем бесконечно отвечать 403 на его автосохранения до отдельного клика «Старт».
    # The demo has a dedicated editable retry submission. It may already be
    # graded when a visitor refreshes an old browser tab, but the canonical
    # route must still be recoverable from that tab without exposing a dead
    # read-only workspace.
    is_demo_retry = (
        bool(getattr(user, "is_demo_user", False))
        and getattr(getattr(submission, "assignment", None), "title", "") == "Исправление: след по алгоритму"
    )
    revision_task_ids: set[int] = set()
    if normalized_status == "RETURNED":
        revision_task_ids = {
            int(item.assignment_task_id)
            for item in (submission.answers or [])
            if getattr(item, "needs_revision", False) and getattr(item, "assignment_task_id", None) is not None
        }

    can_edit = (
        is_owner and (normalized_status in {"ASSIGNED", "IN_PROGRESS", "RETURNED"} or is_demo_retry)
        and not is_parent
    )
    submission_can_submit = bool(can_edit)
    if can_edit and normalized_status == "RETURNED" and revision_task_ids:
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

    from flask import url_for

    def navigation_item(item: AssignmentTask) -> dict[str, Any]:
        return {
            "assignment_task_id": item.assignment_task_id,
            "task_id": item.task_id,
            "position": next(index + 1 for index, candidate in enumerate(ordered_tasks) if candidate.assignment_task_id == item.assignment_task_id),
            "title": (item.task.title if item.task and getattr(item.task, "title", None) else f"Задача {item.task_id}"),
            "url": url_for(
                'task_workspace.workspace_page',
                context_type='submission_task',
                context_id=submission.submission_id,
                assignment_task_id=item.assignment_task_id,
            ),
        }

    tasks_nav = []
    current_nav_status = "unanswered"
    current_is_reviewed = False
    current_is_manual = False
    current_answer_score = None
    current_max_score = int(getattr(assignment_task, "max_score", 1) or 1)

    for idx, t_item in enumerate(ordered_tasks):
        t_ans = next((a for a in (submission.answers or []) if a.assignment_task_id == t_item.assignment_task_id), None)
        t_task = getattr(t_item, "task", None)
        is_manual = _is_task_manual_review(t_item, t_task)
        has_answer = bool(
            t_ans and (
                str(getattr(t_ans, 'value', '') or '').strip()
                or str(getattr(t_ans, 'student_code', '') or '').strip()
            )
        )
        t_score = getattr(t_ans, "score", None) if t_ans else None
        t_max_score = int(getattr(t_item, "max_score", 1) or 1)
        submitted_separately = bool(t_ans and getattr(t_ans, "submitted_separately_at", None))
        is_reviewed = bool(t_ans and getattr(t_ans, "reviewed_at", None) is not None) or (
            normalized_status == "GRADED" and t_ans is not None and t_score is not None
        ) or (submitted_separately and not is_manual and t_score is not None)

        t_needs_revision = False
        if normalized_status == "RETURNED":
            if revision_task_ids:
                t_needs_revision = int(t_item.assignment_task_id) in revision_task_ids
            else:
                t_needs_revision = True

        if t_needs_revision:
            item_nav_status = "returned"
        elif is_reviewed:
            if t_score is not None and t_score >= t_max_score and t_max_score > 0:
                item_nav_status = "correct"
            elif t_score is not None and t_score == 0:
                item_nav_status = "wrong"
            elif t_score is not None and t_max_score >= 2 and 0 < t_score < t_max_score:
                item_nav_status = "partial"
            elif t_score is not None and t_score > 0:
                item_nav_status = "correct"
            else:
                item_nav_status = "wrong"
        elif submitted_separately:
            item_nav_status = "pending_review"
        else:
            if has_answer:
                if normalized_status in {"SUBMITTED", "NEEDS_MANUAL_REVIEW", "GRADED"}:
                    item_nav_status = "pending_review"
                else:
                    item_nav_status = "draft"
            else:
                item_nav_status = "unanswered"

        is_current = (t_item.assignment_task_id == assignment_task.assignment_task_id)
        if is_current:
            current_nav_status = item_nav_status
            current_is_reviewed = is_reviewed
            current_is_manual = is_manual
            current_answer_score = t_score
            current_max_score = t_max_score

        tasks_nav.append({
            "assignment_task_id": t_item.assignment_task_id,
            "task_id": t_item.task_id,
            "position": idx + 1,
            "is_current": is_current,
            "is_completed": has_answer,
            "is_reviewed": is_reviewed,
            "is_manual": is_manual,
            "needs_revision": t_needs_revision,
            "score": t_score,
            "teacher_comment": getattr(t_ans, "teacher_comment", None) if t_ans else None,
            "max_score": t_max_score,
            "nav_status": item_nav_status,
            "url": url_for(
                'task_workspace.workspace_page',
                context_type='submission_task',
                context_id=submission.submission_id,
                assignment_task_id=t_item.assignment_task_id
            ),
        })

    attempts_list = []
    for att in sorted(submission.attempts or [], key=lambda a: a.attempt_no or 0):
        att_entry = {
            "attempt_id": att.attempt_id,
            "attempt_no": att.attempt_no,
            "submitted_at": att.submitted_at.isoformat() if att.submitted_at else None,
            "graded_at": att.graded_at.isoformat() if att.graded_at else None,
            "status": att.status,
            "total_score": att.total_score,
            "max_score": att.max_score,
            "percentage": att.percentage,
            "teacher_feedback": att.teacher_feedback or "",
        }
        if att.attempt_data and isinstance(att.attempt_data, dict):
            # Pass full snapshot to review mode / teacher
            if can_review:
                att_entry["attempt_data"] = att.attempt_data
            else:
                # Student view: safe snapshot (answers, code, student files)
                att_entry["attempt_data"] = {
                    "tasks": {
                        k: {
                            "answer": v.get("answer", ""),
                            "student_code": v.get("student_code", ""),
                            "files": v.get("files", {}),
                            "open_tabs": v.get("open_tabs", ["main.py"]),
                            "score": v.get("score"),
                            "max_score": v.get("max_score"),
                            "is_correct": v.get("is_correct"),
                        }
                        for k, v in (att.attempt_data.get("tasks") or {}).items()
                    },
                    "total_score": att.total_score,
                    "max_score": att.max_score,
                    "percentage": att.percentage,
                    "status": att.status,
                }
        attempts_list.append(att_entry)

    submission_meta = {
        "assignment_id": submission.assignment.assignment_id,
        "assignment_type": submission.assignment.assignment_type or 'homework',
        "submitted_at": submission.submitted_at,
        "deadline": submission.assignment.deadline,
        "attempts_used": len(submission.attempts or []),
        "effective_max_attempts": submission.assignment.get_effective_max_attempts() if hasattr(submission.assignment, 'get_effective_max_attempts') else 1,
        "attempts": attempts_list,
        "student_name": student.name if student else (student.user.username if student and student.user else "Ученик"),
        "student_avatar": student.user.avatar_url if student and student.user and student.user.avatar_url else None,
        "status_label": "В процессе" if can_edit else ("На доработке" if normalized_status == "RETURNED" else ("Проверено" if normalized_status == "GRADED" else "На проверке")),
        "is_late": bool(submission.is_late),
        "is_overtime": bool(submission.is_overtime),
        "is_reviewed": current_is_reviewed,
        "is_graded": (normalized_status == "GRADED"),
        "is_returned": (normalized_status == "RETURNED"),
        "returned_task_count": len(revision_task_ids) if revision_task_ids else (1 if normalized_status == "RETURNED" else 0),
        "is_pending_review": (normalized_status in {"SUBMITTED", "NEEDS_MANUAL_REVIEW"} or (current_is_manual and not current_is_reviewed)),
        "teacher_feedback": (submission.teacher_feedback if submission and submission.teacher_feedback else "") or "",
    }

    topics_list = []
    if assignment_task.task:
        try:
            topics_list = [t.name for t in (assignment_task.task.topics or []) if getattr(t, 'name', None)]
        except Exception:
            topics_list = []

    teacher_comment = (answer.teacher_comment if answer and answer.teacher_comment else "") or ""
    submission_teacher_feedback = (submission.teacher_feedback if submission and submission.teacher_feedback else "") or ""
    correct_ans = _extract_task_correct_answer(assignment_task.task, assignment_task.answer_override) if assignment_task else ""
    sol_obj = getattr(assignment_task.task, "task_solution", None) if assignment_task and assignment_task.task else None
    solution_text = getattr(sol_obj, "solution_text", "") or ""
    solution_html = _render_task_solution(solution_text) if solution_text else ""
    parsed_student_ans = _safe_parse_json(answer.value) if answer and answer.value else None
    parsed_correct_ans = _safe_parse_json(correct_ans) if correct_ans else None

    task_attempts_used = int(getattr(answer, "attempts_used", 0) or 0) if answer else 0
    attempts_per_task = bool(getattr(submission.assignment, "attempts_per_task", False))
    allow_separate_submission = bool(getattr(submission.assignment, "allow_separate_submission", False))
    try:
        task_max_attempts = int(submission.assignment.get_effective_max_attempts_for_task(assignment_task))
    except Exception:
        task_max_attempts = 1
    can_submit_separately = bool(
        is_owner
        and can_edit
        and not is_demo_retry
        and allow_separate_submission
        and attempts_per_task
        and normalized_status in {"ASSIGNED", "IN_PROGRESS", "RETURNED"}
        and task_attempts_used < task_max_attempts
    )

    task_meta = {
        "verification_type": "Ручная проверка" if current_is_manual else "Автопроверка",
        "max_score": current_max_score,
        "topics": topics_list,
        "solution_language": "Python",
        "difficulty_label": assignment_task.task.difficulty_label if assignment_task.task else "medium",
        "is_reviewed": current_is_reviewed,
        "is_manual": current_is_manual,
        "score": current_answer_score,
        "teacher_comment": teacher_comment,
        "correct_answer": correct_ans if can_review else "",
        "attempts_used": task_attempts_used,
        "max_attempts": task_max_attempts,
        "can_submit_separately": can_submit_separately,
    }

    is_task_correct = bool(
        (current_answer_score is not None and current_answer_score >= current_max_score and current_max_score > 0)
        or (answer and getattr(answer, "is_correct", False) is True)
    )
    if normalized_status == "RETURNED":
        if revision_task_ids:
            needs_revision = bool(getattr(answer, "needs_revision", False))
        else:
            needs_revision = True
    else:
        needs_revision = False
    is_published = bool(getattr(submission, "results_published_at", None))

    has_saved_code = False
    resolved_student_code = None
    if answer and answer.student_code is not None:
        resolved_student_code = str(answer.student_code)
        has_saved_code = True
    elif submission.submission_id:
        try:
            from core.db_models import SubmissionAttempt
            last_att = (
                SubmissionAttempt.query.filter_by(submission_id=submission.submission_id)
                .order_by(SubmissionAttempt.attempt_no.desc())
                .first()
            )
            if last_att and last_att.attempt_data:
                ad = last_att.attempt_data
                if isinstance(ad, str):
                    import json
                    ad = json.loads(ad)
                if isinstance(ad, dict):
                    t_data = (ad.get("tasks") or {}).get(str(assignment_task.assignment_task_id))
                    if isinstance(t_data, dict):
                        if t_data.get("student_code") is not None:
                            resolved_student_code = str(t_data.get("student_code"))
                            has_saved_code = True
                        elif t_data.get("files") and "main.py" in t_data.get("files"):
                            resolved_student_code = str(t_data.get("files")["main.py"])
                            has_saved_code = True
        except Exception:
            pass

    if has_saved_code and resolved_student_code is not None:
        final_code = resolved_student_code
    else:
        starter = (assignment_task.task.starter_code if assignment_task.task else "") or ""
        final_code = starter

    resolved_plain_answer = (answer.value if answer and answer.value is not None else "")
    if not resolved_plain_answer and submission.submission_id:
        try:
            from core.db_models import SubmissionAttempt
            last_att = (
                SubmissionAttempt.query.filter_by(submission_id=submission.submission_id)
                .order_by(SubmissionAttempt.attempt_no.desc())
                .first()
            )
            if last_att and last_att.attempt_data:
                ad = last_att.attempt_data
                if isinstance(ad, str):
                    import json
                    ad = json.loads(ad)
                if isinstance(ad, dict):
                    t_data = (ad.get("tasks") or {}).get(str(assignment_task.assignment_task_id))
                    if isinstance(t_data, dict) and t_data.get("answer"):
                        resolved_plain_answer = str(t_data.get("answer"))
        except Exception:
            pass

    return WorkspaceContext(
        context_type="submission_task",
        context_id=submission.submission_id,
        task_id=assignment_task.task_id,
        task=assignment_task.task,
        title=f"{submission.assignment.title} · задача #{assignment_task.task_id}",
        subtitle=f"{student.user.username if student.user else 'ученик'} · {submission.assignment.assignment_type}",
        source_label="Работа / задание",
        assignment_title=submission.assignment.title or "Работа",
        return_url=url_for('assignments.submission_grade_view', submission_id=submission.submission_id) if can_review else "/submissions",
        student_id=student.student_id,
        student_user_id=student.user_id,
        submission_id=submission.submission_id,
        assignment_task_id=assignment_task.assignment_task_id,
        answer_id=answer.answer_id if answer else None,
        code=final_code,
        plain_answer=resolved_plain_answer or "",
        has_saved_code=has_saved_code,
        mmr_policy="always",
        can_edit=can_edit,
        submission_can_submit=submission_can_submit,
        can_review=can_review,
        is_task_correct=is_task_correct,
        is_published=is_published,
        answer_visibility_allowed=answer_visibility_allowed,
        needs_revision=needs_revision,
        is_reviewed=current_is_reviewed,
        is_manual=current_is_manual,
        answer_score=current_answer_score,
        answer_max_score=current_max_score,
        nav_status=current_nav_status,
        timer_seconds_left=timer_seconds_left,
        task_position=current_index + 1,
        task_count=len(ordered_tasks),
        completed_task_count=len(completed_task_ids),
        previous_task=navigation_item(ordered_tasks[current_index - 1]) if current_index > 0 else None,
        next_task=navigation_item(ordered_tasks[current_index + 1]) if current_index + 1 < len(ordered_tasks) else None,
        tasks_nav=tasks_nav,
        submission_meta=submission_meta,
        task_meta=task_meta,
        teacher_comment=teacher_comment,
        submission_teacher_feedback=submission_teacher_feedback,
        correct_answer=correct_ans,
        solution_html=solution_html,
        parsed_answer=parsed_student_ans,
        parsed_correct_answer=parsed_correct_ans,
        linked_lesson_id=getattr(submission.assignment, "lesson_id", None),
    )


def _resolve_lesson_context(user, lesson_id: int) -> WorkspaceContext:
    from app.models import Lesson
    lesson = Lesson.query.get_or_404(lesson_id)
    student = lesson.student
    is_student_owner = getattr(user, "is_student", lambda: False)() and student and user.id == student.user_id
    can_review = _has_teacher_scope(user)
    is_parent = getattr(user, "is_parent", lambda: False)()
    can_edit = (is_student_owner or can_review) and not is_parent
    return WorkspaceContext(
        context_type="lesson",
        context_id=lesson.lesson_id,
        task_id=None,
        task=None,
        title=f"Свободная практика · Урок #{lesson.lesson_id}",
        subtitle=f"Урок #{lesson.lesson_id} · {student.user.username if student and student.user else 'ученик'}",
        source_label="Свободный редактор урока",
        assignment_title=(lesson.topic or "Свободная практика"),
        return_url=f"/lesson/{lesson.lesson_id}/room",
        student_id=student.student_id if student else None,
        student_user_id=student.user_id if student else None,
        code="",
        plain_answer="",
        can_edit=can_edit,
        can_review=can_review,
    )


def resolve_workspace_context(user, context_type: str, context_id: int | None = None, assignment_task_id: int | None = None) -> WorkspaceContext:
    kind = (context_type or "").strip().lower()
    if kind == "lesson_task":
        if context_id is None:
            abort(400, "Не указан lesson_task_id")
        ctx = _resolve_lesson_task_context(user, int(context_id))
    elif kind == "lesson":
        if context_id is None:
            abort(400, "Не указан lesson_id")
        ctx = _resolve_lesson_context(user, int(context_id))
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


def save_workspace_code(
    ctx: WorkspaceContext,
    code: str,
    answer: str | None = None,
    frames: list[dict[str, Any]] | None = None,
    notes: str | None = None,
    files: dict[str, Any] | None = None,
    open_tabs: list[str] | None = None,
    active_file: str | None = None,
    revision: int | None = None,
) -> int:
    code = (code or "")[:100_000]
    if answer is not None:
        answer = str(answer)[:20_000]
    curr_mf = load_workspace_multi_file_state(ctx)
    curr_rev = int(curr_mf.get("revision", 1))
    if revision is not None and revision > 0 and revision < curr_rev:
        raise ValueError(f"Stale revision {revision} < current {curr_rev}")
    new_rev = max(curr_rev, int(revision or 0)) + 1

    if ctx.context_type == "submission_task":
        clean_files = dict(curr_mf.get("files") or {})
        if files is not None and isinstance(files, dict):
            clean_files.update(files)
        clean_files["main.py"] = code
        clean_tabs = ["main.py"]
        clean_active = "main.py"
    else:
        if files is not None:
            clean_files = dict(files) if isinstance(files, dict) else {}
        else:
            clean_files = dict(curr_mf.get("files") or {})

        if "main.py" not in clean_files:
            clean_files["main.py"] = code if (not active_file or active_file == "main.py") else ""

        if open_tabs is not None:
            clean_tabs = [str(t) for t in open_tabs if str(t) in clean_files] if isinstance(open_tabs, list) else []
        else:
            clean_tabs = [str(t) for t in (curr_mf.get("open_tabs") or []) if str(t) in clean_files]
        if not clean_tabs:
            clean_tabs = ["main.py"] if "main.py" in clean_files else list(clean_files.keys())[:1]

        if active_file is not None:
            clean_active = str(active_file) if str(active_file) in clean_files else clean_tabs[0]
        else:
            clean_active = str(curr_mf.get("active_file") or clean_tabs[0])

        if clean_active in clean_files and code is not None:
            clean_files[clean_active] = code

    try:
        if ctx.context_type == "lesson" and ctx.context_id:
            cache_workspace_snapshot(
                ctx, code, answer or "", frames=frames, source="manual" if frames else "autosave",
                revision=new_rev, files=clean_files, open_tabs=clean_tabs, active_file=clean_active
            )
            return new_rev
        if ctx.context_type == "lesson_task" and ctx.lesson_task_id:
            lesson_task = LessonTask.query.get_or_404(ctx.lesson_task_id)
            lesson_task.student_submission = clean_files.get("main.py", lesson_task.student_submission or code)
            if answer is not None:
                lesson_task.student_answer = answer
            effective_answer = lesson_task.student_answer if answer is None else answer
            save_workspace_trace(ctx, frames=frames, meta={"source": "server-save", "code_length": len(code), "answer_length": len(effective_answer or "")})
            save_workspace_version(
                ctx, code=code, answer=effective_answer or "", source="manual" if frames else "autosave", notes=notes,
                files=clean_files, open_tabs=clean_tabs, active_file=clean_active, revision=new_rev
            )
            cache_workspace_snapshot(
                ctx, code, effective_answer or "", frames=frames, source="manual" if frames else "autosave",
                revision=new_rev, files=clean_files, open_tabs=clean_tabs, active_file=clean_active
            )
            db.session.commit()
            return new_rev
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
            db.session.flush()
            if not ctx.answer_id:
                ctx.answer_id = answer_row.answer_id
            answer_row.student_code = clean_files.get("main.py", answer_row.student_code or code)
            if answer is not None:
                answer_row.value = answer
            effective_answer = answer_row.value if answer is None else answer
            from core.db_models import utc_now

            answer_row.student_code_saved_at = utc_now()
            save_workspace_trace(
                ctx,
                frames=frames,
                meta={"source": "server-save", "code_length": len(code), "answer_length": len(effective_answer or "")},
            )
            save_workspace_version(
                ctx, code=code, answer=effective_answer or "", source="manual" if frames else "autosave", notes=notes,
                files=clean_files, open_tabs=clean_tabs, active_file=clean_active, revision=new_rev
            )
            cache_workspace_snapshot(
                ctx, code, effective_answer or "", frames=frames, source="manual" if frames else "autosave",
                revision=new_rev, files=clean_files, open_tabs=clean_tabs, active_file=clean_active
            )
            db.session.commit()
            return new_rev
        return new_rev
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


def _trace_lookup(ctx: WorkspaceContext, *, legacy: bool = False):
    scope_id = ctx.context_id if legacy or ctx.context_type != "submission_task" else ctx.assignment_task_id
    query = CodePlaybackTrace.query.filter_by(
        context_type=ctx.context_type,
        context_id=scope_id,
        task_id=ctx.task_id,
    )
    if legacy and ctx.context_type == "submission_task" and ctx.answer_id:
        query = query.filter(db.or_(CodePlaybackTrace.answer_id == ctx.answer_id, CodePlaybackTrace.answer_id.is_(None)))
    if ctx.student_id:
        query = query.filter_by(student_id=ctx.student_id)
    return query.order_by(CodePlaybackTrace.updated_at.desc(), CodePlaybackTrace.trace_id.desc())


def load_workspace_trace_payload(ctx: WorkspaceContext) -> dict[str, Any]:
    try:
        trace = _trace_lookup(ctx).first()
        if not trace and ctx.context_type == "submission_task":
            trace = _trace_lookup(ctx, legacy=True).first()
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
            context_id=ctx.assignment_task_id if ctx.context_type == "submission_task" else ctx.context_id,
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


def _version_lookup(ctx: WorkspaceContext, *, legacy: bool = False):
    scope_id = ctx.context_id if legacy or ctx.context_type != "submission_task" else ctx.assignment_task_id
    query = CodeWorkspaceVersion.query.filter_by(
        context_type=ctx.context_type,
        context_id=scope_id,
        task_id=ctx.task_id,
    )
    if legacy and ctx.context_type == "submission_task" and ctx.answer_id:
        query = query.filter(db.or_(CodeWorkspaceVersion.answer_id == ctx.answer_id, CodeWorkspaceVersion.answer_id.is_(None)))
    if ctx.student_id:
        query = query.filter_by(student_id=ctx.student_id)
    query = query.order_by(CodeWorkspaceVersion.created_at.desc(), CodeWorkspaceVersion.version_id.desc())
    if not legacy and ctx.context_type == "submission_task" and not query.first():
        return _version_lookup(ctx, legacy=True)
    return query


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


def load_workspace_multi_file_state(ctx: WorkspaceContext) -> dict[str, Any]:
    cached_state = load_cached_workspace_snapshot(ctx) or {}
    files = cached_state.get("files")
    open_tabs = cached_state.get("open_tabs")
    active_file = cached_state.get("active_file")
    revision = cached_state.get("revision") or cached_state.get("version")

    if not files:
        latest = None
        try:
            latest = _version_lookup(ctx).first()
        except Exception:
            pass
        if latest and isinstance(latest.snapshot, dict):
            files = latest.snapshot.get("files")
            open_tabs = latest.snapshot.get("open_tabs")
            active_file = latest.snapshot.get("active_file")
            revision = latest.snapshot.get("revision")
        elif latest and isinstance(latest.snapshot, str):
            try:
                import json
                snap = json.loads(latest.snapshot)
                if isinstance(snap, dict):
                    files = snap.get("files")
                    open_tabs = snap.get("open_tabs")
                    active_file = snap.get("active_file")
                    revision = snap.get("revision")
            except Exception:
                pass

    if not files and ctx.context_type == "submission_task" and ctx.submission_id:
        try:
            from core.db_models import SubmissionAttempt
            attempts = (
                SubmissionAttempt.query.filter_by(submission_id=ctx.submission_id)
                .order_by(SubmissionAttempt.attempt_no.desc())
                .all()
            )
            for att in attempts:
                att_data = att.attempt_data
                if isinstance(att_data, str):
                    try:
                        import json
                        att_data = json.loads(att_data)
                    except Exception:
                        att_data = None
                if isinstance(att_data, dict):
                    tasks = att_data.get("tasks") or {}
                    task_info = tasks.get(str(ctx.assignment_task_id)) or tasks.get(int(ctx.assignment_task_id or 0))
                    if isinstance(task_info, dict):
                        att_files = task_info.get("files")
                        if isinstance(att_files, dict) and att_files:
                            files = att_files
                            open_tabs = task_info.get("open_tabs")
                            active_file = task_info.get("active_file")
                            break
                        elif task_info.get("student_code"):
                            files = {"main.py": task_info["student_code"]}
                            open_tabs = ["main.py"]
                            active_file = "main.py"
                            break
        except Exception:
            pass

    if not files and ctx.code:
        files = {"main.py": ctx.code}
        open_tabs = ["main.py"]
        active_file = "main.py"

    # For submission_task, preserve access to historical secondary files (archived files)
    if ctx.context_type == "submission_task" and not any(fname != "main.py" for fname in (files or {})):
        try:
            for ver in _version_lookup(ctx).all():
                ver_snap = ver.snapshot
                if isinstance(ver_snap, str):
                    try:
                        import json
                        ver_snap = json.loads(ver_snap)
                    except Exception:
                        ver_snap = None
                if isinstance(ver_snap, dict) and ver_snap.get("files"):
                    extra = {k: v for k, v in ver_snap["files"].items() if k != "main.py"}
                    if extra:
                        files = dict(files or {"main.py": ctx.code or ""})
                        files.update(extra)
                        break
            if ctx.submission_id and not any(fname != "main.py" for fname in (files or {})):
                from core.db_models import SubmissionAttempt
                for att in SubmissionAttempt.query.filter_by(submission_id=ctx.submission_id).order_by(SubmissionAttempt.attempt_no.desc()).all():
                    att_data = att.attempt_data
                    if isinstance(att_data, str):
                        try:
                            import json
                            att_data = json.loads(att_data)
                        except Exception:
                            att_data = None
                    if isinstance(att_data, dict):
                        tasks = att_data.get("tasks") or {}
                        t_info = tasks.get(str(ctx.assignment_task_id)) or tasks.get(int(ctx.assignment_task_id or 0))
                        if isinstance(t_info, dict) and isinstance(t_info.get("files"), dict):
                            extra = {k: v for k, v in t_info["files"].items() if k != "main.py"}
                            if extra:
                                files = dict(files or {"main.py": ctx.code or ""})
                                files.update(extra)
                                break
        except Exception:
            pass

    default_code = ctx.code or (ctx.task.starter_code if ctx.task else "") or ""
    if not isinstance(files, dict) or not files:
        files = {"main.py": default_code}
    if not isinstance(open_tabs, list) or not open_tabs:
        open_tabs = ["main.py"]
    if not active_file or active_file not in files:
        active_file = open_tabs[0] if open_tabs else "main.py"
    if revision is None:
        revision = 1

    return {
        "files": files,
        "open_tabs": open_tabs,
        "active_file": active_file,
        "revision": int(revision),
    }


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
    mf_state = load_workspace_multi_file_state(ctx)

    active_code = mf_state["files"].get(mf_state["active_file"]) or ""
    code = live_state.get("code") or cached_state.get("code") or active_code or ctx.code or ""
    answer = live_state.get("answer") or cached_state.get("answer") or ctx.plain_answer or ""
    ui_state = live_state.get("ui_state") or cached_state.get("ui_state") or {}
    updated_at = live_state.get("updated_at") or cached_state.get("updated_at")
    version_id = live_state.get("version_id") or cached_state.get("version_id")
    source = live_state.get("source") or cached_state.get("source")
    version = max(int(live_state.get("version") or 0), int(cached_state.get("version") or 0), mf_state["revision"])

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
        "notes": load_workspace_notes(ctx),
        "updated_at": updated_at,
        "version_id": version_id,
        "source": source,
        "version": version,
        "revision": version,
        "files": mf_state["files"],
        "open_tabs": mf_state["open_tabs"],
        "active_file": mf_state["active_file"],
        "ui_state": ui_state,
        "versions": load_workspace_versions_payload(ctx),
        "playback": trace_payload,
    }


def load_workspace_notes(ctx: WorkspaceContext) -> str:
    # Notes are an independent OS app. Code/answer autosaves may carry an
    # older snapshot, so the latest explicit notes save is authoritative.
    explicit = _version_lookup(ctx).filter(CodeWorkspaceVersion.source.in_(("notes", "transfer"))).first()
    if explicit and isinstance(explicit.snapshot, dict) and "notes" in explicit.snapshot:
        return str(explicit.snapshot["notes"] or "")
    for version in _version_lookup(ctx).limit(100).all():
        snapshot = version.snapshot if isinstance(version.snapshot, dict) else {}
        if "notes" in snapshot:
            return str(snapshot["notes"] or "")
    return ""


def save_workspace_version(
    ctx: WorkspaceContext,
    code: str,
    answer: str = "",
    source: str = "autosave",
    notes: str | None = None,
    files: dict[str, Any] | None = None,
    open_tabs: list[str] | None = None,
    active_file: str | None = None,
    revision: int | None = None,
) -> CodeWorkspaceVersion:
    try:
        curr_mf = load_workspace_multi_file_state(ctx)
        if files is not None:
            clean_files = dict(files) if isinstance(files, dict) else {}
        else:
            clean_files = dict(curr_mf.get("files") or {})

        if "main.py" not in clean_files:
            clean_files["main.py"] = code if (not active_file or active_file == "main.py") else ""

        if open_tabs is not None:
            clean_tabs = [str(t) for t in open_tabs if str(t) in clean_files] if isinstance(open_tabs, list) else []
        else:
            clean_tabs = [str(t) for t in (curr_mf.get("open_tabs") or []) if str(t) in clean_files]
        if not clean_tabs:
            clean_tabs = ["main.py"] if "main.py" in clean_files else list(clean_files.keys())[:1]

        if active_file is not None:
            clean_active = str(active_file) if str(active_file) in clean_files else clean_tabs[0]
        else:
            clean_active = str(curr_mf.get("active_file") or clean_tabs[0])

        if clean_active in clean_files and code is not None:
            clean_files[clean_active] = code
        rev = int(revision or 1)
        version = CodeWorkspaceVersion(
            context_type=ctx.context_type,
            context_id=ctx.assignment_task_id if ctx.context_type == "submission_task" else ctx.context_id,
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
                "notes": str(notes)[:20_000] if notes is not None else load_workspace_notes(ctx),
                "files": clean_files,
                "open_tabs": clean_tabs,
                "active_file": clean_active,
                "revision": rev,
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
