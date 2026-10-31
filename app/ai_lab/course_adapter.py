"""Adapter for explicitly allowlisted synthetic BooStudy course rows."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any

from flask import current_app, has_app_context
from sqlalchemy import func

from app.ai_lab.config import setting
from app.ai_lab.provider import is_local_ai_lab_enabled
from core.db_models import (
    ExamSkill,
    LearningItem,
    LearningTrajectory,
    LearningTrajectoryVersion,
    Lesson,
    LessonTask,
    MOSCOW_TZ,
    Tasks,
    TrajectoryModule,
    db,
)


def _adapter_enabled() -> bool:
    if not has_app_context() or not is_local_ai_lab_enabled():
        return False
    value = current_app.config.get("AI_LAB_COURSE_ADAPTER_ENABLED")
    if value is None:
        value = setting("AI_LAB_COURSE_ADAPTER_ENABLED", "false")
    return value is True or str(value).strip().lower() in {"1", "true", "yes", "on"}


def _allowed_course_ids() -> set[int]:
    if not has_app_context():
        return set()
    raw = current_app.config.get("AI_LAB_SYNTHETIC_COURSE_IDS")
    if raw is None:
        raw = setting("AI_LAB_SYNTHETIC_COURSE_IDS", "")
    if isinstance(raw, str):
        values = raw.split(",")
    elif isinstance(raw, (list, tuple, set)):
        values = raw
    else:
        values = []
    result = set()
    for value in values:
        try:
            course_id = int(value)
        except (TypeError, ValueError):
            continue
        if course_id > 0:
            result.add(course_id)
    return result


def _allowed_copy_ids() -> set[int]:
    if not has_app_context():
        return set()
    raw = current_app.config.get("AI_LAB_SYNTHETIC_COURSE_COPY_IDS")
    if raw is None:
        raw = setting("AI_LAB_SYNTHETIC_COURSE_COPY_IDS", "")
    values = raw.split(",") if isinstance(raw, str) else raw if isinstance(raw, (list, tuple, set)) else []
    result = set()
    for value in values:
        try:
            course_id = int(value)
        except (TypeError, ValueError):
            continue
        if course_id > 0:
            result.add(course_id)
    # Ordinary teacher assignments are created after the safe backend starts.
    # Admit only active copies of an explicitly allowlisted master, created by
    # an allowlisted actor for an allowlisted synthetic learner in the verified DB.
    from app.ai_lab.database_safety import has_verified_safe_ai_lab_db
    if not _adapter_enabled() or not has_verified_safe_ai_lab_db():
        return result
    from app.ai_lab.platform_homework import _allowlisted_actor_ids, _allowlisted_user_ids
    from app.models import Student, User
    actors = _allowlisted_actor_ids()
    learners = _allowlisted_user_ids()
    templates = _allowed_course_ids()
    if not actors or not learners or not templates:
        return result
    assigned = (LearningTrajectory.query.filter(
        LearningTrajectory.is_template.is_(False),
        LearningTrajectory.status == "active",
        LearningTrajectory.parent_course_id.in_(templates),
        LearningTrajectory.created_by_user_id.in_(actors),
    ).all())
    for copy in assigned:
        student = db.session.get(Student, int(copy.student_id or 0))
        learner = db.session.get(User, int(student.user_id or 0)) if student and student.user_id else None
        if (learner and int(learner.id) in learners and learner.role == "student"
                and str(learner.username or "").casefold().startswith(("demo_", "synthetic_"))):
            result.add(int(copy.course_id))
    return result


def resolve_course_version_at(course_id: int, observed_at: datetime | None) -> dict[str, Any]:
    """Resolve the copy version that existed when an attempt was assigned or observed."""
    course = db.session.get(LearningTrajectory, int(course_id))
    if (not course or int(course_id) not in _allowed_copy_ids()
            or course.is_template or not course.student_id):
        return {"status": "unverified", "course_version": None,
                "reason": "Индивидуальная копия не прошла проверку safe allowlist."}
    current_version = max(1, int(course.current_version or 1))
    if observed_at is None:
        if current_version == 1:
            return {"status": "resolved", "course_version": 1,
                    "reason": "Копия не меняла версию после создания."}
        return {"status": "unverified", "course_version": None,
                "reason": "Для попытки нет временной отметки, позволяющей определить версию программы."}

    def local_naive(value: datetime) -> datetime:
        return (value.astimezone(MOSCOW_TZ).replace(tzinfo=None)
                if value.tzinfo is not None else value)

    observed = local_naive(observed_at)
    snapshots = (LearningTrajectoryVersion.query.filter_by(course_id=int(course_id))
                 .order_by(LearningTrajectoryVersion.version_number.asc(),
                           LearningTrajectoryVersion.created_at.asc()).all())
    if current_version == 1 and not snapshots:
        return {"status": "resolved", "course_version": 1,
                "reason": "Попытка относится к единственной версии копии."}
    if not snapshots:
        return {"status": "unverified", "course_version": None,
                "reason": "История версий копии отсутствует; источник исторической версии не установлен."}

    resolved_version = 1
    for snapshot_row in snapshots:
        snapshot = snapshot_row.snapshot if isinstance(snapshot_row.snapshot, dict) else {}
        try:
            source_version = int(snapshot.get("snapshot_of_course_version") or snapshot_row.version_number)
        except (TypeError, ValueError):
            return {"status": "unverified", "course_version": None,
                    "reason": "Запись истории версии не содержит проверяемый номер исходной версии."}
        if source_version >= current_version:
            continue
        boundary_at = snapshot_row.created_at
        if not boundary_at:
            return {"status": "unverified", "course_version": None,
                    "reason": "История изменения не содержит времени перехода версии."}
        if source_version != resolved_version:
            return {"status": "unverified", "course_version": None,
                    "reason": "В истории есть пропуск версий; точный источник попытки неизвестен."}
        boundary = local_naive(boundary_at)
        if observed < boundary:
            return {"status": "resolved", "course_version": resolved_version,
                    "reason": "Попытка произошла до первого следующего изменения курса."}
        if observed == boundary:
            return {"status": "unverified", "course_version": None,
                    "reason": "Время попытки совпадает с границей смены версии."}
        resolved_version = source_version + 1

    if resolved_version != current_version:
        return {"status": "unverified", "course_version": None,
                "reason": "История версий не подтверждает полный путь от момента попытки до текущей версии."}
    return {"status": "resolved", "course_version": resolved_version,
            "reason": "Версия восстановлена по отметке создания снимка перехода курса."}


def _require_copy_actor_scope(actor_id: int, student_id: int) -> None:
    """Ensure ordinary synthetic teachers can mutate only their linked learner's copy."""
    from app.ai_lab.platform_homework import _allowlisted_actor_ids
    from app.models import Student, User
    from app.utils.relationship_scope import can_user_access_student

    actor = db.session.get(User, int(actor_id))
    role = str(getattr(actor, "role", "") or "").casefold()
    if role not in {"teacher", "tutor"}:
        return
    student = db.session.get(Student, int(student_id))
    learner = db.session.get(User, int(student.user_id or 0)) if student and student.user_id else None
    if (int(actor_id) not in _allowlisted_actor_ids() or not student or not learner
            or learner.role != "student"
            or not str(learner.username or "").casefold().startswith(("demo_", "synthetic_"))
            or not can_user_access_student(actor, student_user_id=int(learner.id),
                                            student_platform_id=int(student.student_id))):
        raise ValueError("Преподаватель не имеет разрешённой связи с этим synthetic-учеником.")


def synthetic_lesson_task_binding_options(lesson_id: int, actor_user_id: int) -> list[dict[str, Any]]:
    """Expose exact criterion choices only for an assigned, allowlisted safe-mode lesson."""
    from app.ai_lab.database_safety import has_verified_safe_ai_lab_db
    from app.ai_lab.platform_homework import _allowlisted_actor_ids, _allowlisted_task_author_ids
    from app.ai_lab.provider import is_local_ai_lab_enabled
    from core.db_models import LearningTrajectory, Lesson, db

    if (not has_verified_safe_ai_lab_db() or not is_local_ai_lab_enabled()
            or int(actor_user_id) not in _allowlisted_actor_ids()
            or int(actor_user_id) not in _allowlisted_task_author_ids()):
        return []
    lesson = db.session.get(Lesson, int(lesson_id))
    if (not lesson or str(lesson.status or "").casefold() not in {"planned", "scheduled", "in_progress"}
            or not lesson.student_id or not lesson.learning_trajectory_id):
        return []
    course_id = int(lesson.learning_trajectory_id)
    if course_id not in _allowed_copy_ids():
        return []
    resolution = resolve_assigned_synthetic_copy(int(lesson.student_id))
    copy = resolution.get("copy") if resolution.get("status") == "resolved" else None
    course = db.session.get(LearningTrajectory, course_id)
    if (not copy or int(copy.course_id) != course_id
            or int(copy.student_id or 0) != int(lesson.student_id)
            or not course or int(course.current_version or 1) < 1):
        return []

    options: list[dict[str, Any]] = []
    for skill in lesson.skills or []:
        if not skill.is_active or not str(skill.topic_code or "").startswith("ege.inf."):
            continue
        try:
            criteria = skill.mastery_criteria if isinstance(skill.mastery_criteria, list) else json.loads(skill.mastery_criteria or "[]")
        except (TypeError, ValueError):
            continue
        if not isinstance(criteria, list):
            continue
        skill_id = f"exam-skill:{int(skill.skill_id)}"
        for criterion in criteria:
            if not isinstance(criterion, dict):
                continue
            criterion_id = str(criterion.get("key") or "")
            if not criterion_id or not re.fullmatch(r"[a-z0-9_-]{1,100}", criterion_id):
                continue
            description = str(criterion.get("description") or criterion.get("name") or criterion_id).strip()
            options.append({
                "selection_id": f"{skill_id}::{criterion_id}",
                "course_id": course_id,
                "course_version": int(course.current_version or 1),
                "lesson_id": int(lesson.lesson_id),
                "skill_id": skill_id,
                "topic_code": str(skill.topic_code),
                "criterion_id": criterion_id,
                "label": f"{skill.title or skill.topic or skill.topic_code} · {description}",
            })
    return options


def _course_evidence_semantics_snapshot(*, course_id: int, course_version: int,
                                        lesson: Lesson) -> dict[str, Any]:
    """Capture the objective, skill, criterion, task and checker before a revision."""
    from app.ai_lab.course_evidence import build_semantic_record
    from app.ai_lab.platform_homework import _allowlisted_task_author_ids, _task_fingerprint

    skill_by_id = {f"exam-skill:{int(item.skill_id)}": item for item in (lesson.skills or []) if item.is_active}
    entries = []
    allowed_authors = _allowlisted_task_author_ids()
    if not allowed_authors:
        return {"contract": "boostudy.course-evidence-snapshot.v1", "course_id": int(course_id),
                "course_version": int(course_version), "lesson_id": int(lesson.lesson_id), "entries": []}
    tasks = (Tasks.query.filter_by(bank_category="synthetic_adaptive_draft")
             .filter(Tasks.created_by_id.in_(allowed_authors)).order_by(Tasks.task_id.asc()).all())
    for task in tasks:
        spec = task.answer_spec if isinstance(task.answer_spec, dict) else {}
        binding = spec.get("synthetic_course_skill_binding")
        if not isinstance(binding, dict):
            continue
        if binding.get("contract") == "boostudy.synthetic-course-source-skill.v1":
            from app.ai_lab.analytics import _synthetic_master_task_link
            course = db.session.get(LearningTrajectory, int(course_id))
            matched = _synthetic_master_task_link(task, binding, course, lesson)
            if not matched:
                continue
            skill, criterion_id = matched
        elif binding.get("contract") == "boostudy.synthetic-course-skill.v1":
            try:
                bound_course_id = int(binding.get("course_id"))
                bound_lesson_id = int(binding.get("lesson_id"))
            except (TypeError, ValueError):
                continue
            skill_id = str(binding.get("skill_id") or "")
            skill = skill_by_id.get(skill_id)
            criterion_id = str(binding.get("criterion_id") or "")
            if (bound_course_id != int(course_id) or bound_lesson_id != int(lesson.lesson_id) or not skill
                    or str(binding.get("topic_code") or "") != str(skill.topic_code or "")
                    or binding.get("task_fingerprint") != _task_fingerprint(task)):
                continue
        else:
            continue
        criteria = skill.mastery_criteria
        if isinstance(criteria, str):
            try:
                criteria = json.loads(criteria or "[]")
            except (TypeError, ValueError):
                continue
        if not isinstance(criteria, list):
            continue
        for criterion in criteria:
            if not isinstance(criterion, dict) or str(criterion.get("key") or "") != criterion_id:
                continue
            grading_mode = str(spec.get("grading_mode") or spec.get("type") or "method_unrecorded")
            row = build_semantic_record(
                course_id=course_id, course_version=course_version, lesson=lesson, skill=skill,
                criterion_id=str(criterion["key"]), task=task, grading_method=grading_mode,
                expected_answer=task.answer, max_score=task.max_score,
                test_set_id=binding.get("code_judge_test_set_id"),
                test_set_version=binding.get("code_judge_test_set_version"),
                rubric_version=binding.get("rubric_version"),
            )
            row["task_fingerprint"] = str(binding["task_fingerprint"])
            entries.append(row)
    return {"contract": "boostudy.course-evidence-snapshot.v1", "course_id": int(course_id),
            "course_version": int(course_version), "lesson_id": int(lesson.lesson_id),
            "entries": entries}


def _course_evidence_semantics_by_lesson(*, course_id: int, course_version: int) -> list[dict[str, Any]]:
    course = db.session.get(LearningTrajectory, int(course_id))
    if not course or course.is_template or not course.student_id:
        return []
    lessons = (Lesson.query.filter_by(
        learning_trajectory_id=int(course_id), student_id=int(course.student_id),
    ).order_by(Lesson.course_order_index.asc(), Lesson.lesson_id.asc()).all())
    return [
        _course_evidence_semantics_snapshot(
            course_id=int(course_id), course_version=int(course_version), lesson=lesson,
        )
        for lesson in lessons
    ]


def compare_course_task_semantics(*, course_id: int, source_version: int, lesson_id: int,
                                  skill_id: str, criterion_id: str, task_id: int,
                                  task_fingerprint: str) -> dict[str, Any]:
    """Compare historical evidence to the live copy without guessing old semantics."""
    from app.ai_lab.course_evidence import compare_semantic_records

    course = db.session.get(LearningTrajectory, int(course_id))
    lesson = Lesson.query.filter_by(lesson_id=int(lesson_id), learning_trajectory_id=int(course_id)).first()
    if not course or not lesson or int(course.current_version or 1) < 1:
        return {"status": "unverified", "matches": [], "mismatches": ["current_course_context_missing"],
                "reason": "Текущая копия или урок недоступны для сравнения."}
    skill = next((item for item in (lesson.skills or [])
                  if item.is_active and f"exam-skill:{int(item.skill_id)}" == str(skill_id)), None)
    if not skill:
        return {"status": "incompatible", "matches": [], "mismatches": ["stable_skill_missing"],
                "reason": "Стабильный навык больше не связан с этим уроком."}
    current_snapshot = _course_evidence_semantics_snapshot(
        course_id=int(course_id), course_version=int(course.current_version or 1), lesson=lesson,
    )
    def find_entry(snapshot: Any) -> dict[str, Any] | None:
        entries = snapshot.get("entries") if isinstance(snapshot, dict) else None
        return next((item for item in entries if isinstance(item, dict)
                     and int(item.get("task_id") or 0) == int(task_id)
                     and item.get("course_skill_id") == str(skill_id)
                     and item.get("criterion_id") == str(criterion_id)), None) if isinstance(entries, list) else None

    def version_entry(snapshot_payload: Any) -> tuple[dict[str, Any] | None, bool]:
        if not isinstance(snapshot_payload, dict):
            return None, False
        coverage = snapshot_payload.get("evidence_semantics_by_lesson")
        if isinstance(coverage, list):
            lesson_snapshot = next((item for item in coverage if isinstance(item, dict)
                                    and int(item.get("lesson_id") or 0) == int(lesson_id)), None)
            if lesson_snapshot:
                return find_entry(lesson_snapshot), True
            return None, bool(snapshot_payload.get("evidence_semantics_coverage_complete"))
        legacy = snapshot_payload.get("evidence_semantics")
        if (isinstance(legacy, dict)
                and int(legacy.get("lesson_id") or 0) == int(lesson_id)):
            return find_entry(legacy), True
        return None, False

    current_entry = find_entry(current_snapshot)
    if not current_entry:
        return {"status": "incompatible", "matches": [], "mismatches": ["current_task_criterion_binding_missing"],
                "reason": "Текущая версия не содержит эту связь задания с критерием."}
    if str(current_entry.get("task_fingerprint") or "") != str(task_fingerprint or ""):
        return {"status": "incompatible", "matches": [], "mismatches": ["task_condition_changed"],
                "reason": "Отпечаток условия или сохранённой спецификации задания изменился."}
    if int(source_version) == int(course.current_version or 1):
        return {"status": "compatible", "matches": [
            "course_id", "lesson_id", "course_skill_id", "topic_code", "criterion_id", "task_id",
            "lesson_objective_fingerprint", "criteria_fingerprint", "task_condition_fingerprint",
            "assessment_method", "checker_fingerprint",
        ], "mismatches": [], "reason": "Событие относится к текущей версии и точной действующей связи."}

    versions = LearningTrajectoryVersion.query.filter_by(course_id=int(course_id)).all()
    snapshots_by_source_version: dict[int, list[dict[str, Any]]] = {}
    for version in versions:
        payload = version.snapshot if isinstance(version.snapshot, dict) else {}
        try:
            source = int(payload.get("snapshot_of_course_version") or 0)
        except (TypeError, ValueError):
            continue
        if source > 0:
            snapshots_by_source_version.setdefault(source, []).append(payload)

    accumulated_matches: list[str] = []
    for version_number in range(int(source_version), int(course.current_version or 1)):
        candidates = snapshots_by_source_version.get(version_number, [])
        if len(candidates) != 1:
            return {"status": "unverified", "matches": [],
                    "mismatches": ["version_semantic_snapshot_missing_or_ambiguous"],
                    "reason": "Не для каждого перехода версии сохранён однозначный снимок; результат остаётся в истории навыка."}
        source_entry, source_lesson_covered = version_entry(candidates[0])
        if not source_lesson_covered:
            return {"status": "unverified", "matches": [],
                    "mismatches": ["source_lesson_semantic_snapshot_missing"],
                    "reason": "В снимке версии нет полного описания этого урока."}
        if not source_entry:
            return {"status": "incompatible", "matches": [],
                    "mismatches": ["source_task_criterion_binding_missing"],
                    "reason": "В исходной версии не было этой проверяемой связи задания с критерием."}
        if str(source_entry.get("task_fingerprint") or "") != str(task_fingerprint or ""):
            return {"status": "incompatible", "matches": [],
                    "mismatches": ["source_task_binding_changed"],
                    "reason": "Событие не совпадает с отпечатком задания в исходной версии."}

        if version_number + 1 == int(course.current_version or 1):
            next_entry = current_entry
        else:
            next_candidates = snapshots_by_source_version.get(version_number + 1, [])
            if len(next_candidates) != 1:
                return {"status": "unverified", "matches": [],
                        "mismatches": ["intermediate_semantic_snapshot_missing_or_ambiguous"],
                        "reason": "Нельзя проверить семантику каждого промежуточного изменения курса."}
            next_entry, next_lesson_covered = version_entry(next_candidates[0])
            if not next_lesson_covered:
                return {"status": "unverified", "matches": [],
                        "mismatches": ["intermediate_lesson_semantic_snapshot_missing"],
                        "reason": "Для промежуточной версии нет полного снимка этого урока."}
            if not next_entry:
                return {"status": "incompatible", "matches": [],
                        "mismatches": ["intermediate_task_criterion_binding_missing"],
                        "reason": "В промежуточной версии связь задания с критерием отсутствовала."}
        comparison = compare_semantic_records(source_entry, source_entry, next_entry)
        if comparison.get("status") != "compatible":
            return comparison
        accumulated_matches.extend(comparison.get("matches") or [])
    return {"status": "compatible", "matches": list(dict.fromkeys(accumulated_matches)),
            "mismatches": [],
            "reason": "Семантика критерия, упражнения и проверяющего совпадает на каждом сохранённом переходе версии."}


def apply_teacher_time_plan_edits(time_plan: dict[str, Any] | None, *, action: str,
                                 stage_minutes: dict[str, int] | None = None,
                                 stage_purpose: str | None = None) -> dict[str, Any]:
    """Apply bounded teacher edits to a Tutor Core plan without changing protected stages."""
    if not isinstance(time_plan, dict) or time_plan.get("status") != "redistributed":
        raise ValueError("План нельзя редактировать: preview не разрешает изменение структуры урока.")
    original = time_plan.get("original_segments")
    proposed = time_plan.get("proposed_segments")
    inserted = time_plan.get("inserted_segment")
    if not isinstance(original, list) or not isinstance(proposed, list) or not isinstance(inserted, dict):
        raise ValueError("В preview отсутствует проверяемая структура этапов.")
    inserted_id = str(inserted.get("id") or "")
    if not inserted_id:
        raise ValueError("В preview не указан новый этап.")
    edits = stage_minutes or {}
    allowed_ids = {inserted_id}
    original_by_id = {str(item.get("id") or ""): item for item in original if isinstance(item, dict)}
    if len(original_by_id) != len(original):
        raise ValueError("В исходном плане есть повторяющиеся или пустые ID этапов.")
    for item in original:
        if (not item.get("mandatory", True) and int(item.get("flexible_minutes") or 0) > 0
                and str(item.get("flexible_reason") or "").strip()):
            allowed_ids.add(str(item["id"]))
    if set(edits) - allowed_ids:
        raise ValueError("Можно менять только явно гибкие этапы и новый этап Tutor Core.")

    proposed_by_id = {str(item.get("id") or ""): dict(item) for item in proposed if isinstance(item, dict)}
    if len(proposed_by_id) != len(proposed) or inserted_id not in proposed_by_id:
        raise ValueError("Предлагаемый план содержит повторяющиеся этапы или не содержит новый этап.")
    changed = [dict(item) for item in proposed]
    changed_by_id = {str(item["id"]): item for item in changed}
    cuts = []
    total_cut = 0
    for segment_id, source in original_by_id.items():
        try:
            original_minutes = int(source.get("minutes") or 0)
            current_minutes = int(proposed_by_id[segment_id].get("minutes") or 0)
            requested = edits.get(segment_id, current_minutes)
            if type(requested) is not int:
                raise ValueError
            flexible = int(source.get("flexible_minutes") or 0)
        except (KeyError, TypeError, ValueError):
            raise ValueError("Время этапа должно быть целым числом минут.")
        if segment_id in edits:
            minimum = max(1, original_minutes - flexible)
            if (source.get("mandatory", True) or flexible <= 0
                    or not str(source.get("flexible_reason") or "").strip()
                    or requested < minimum or requested > original_minutes):
                raise ValueError("Этап нельзя менять: разрешены только минуты из его явно описанного гибкого резерва.")
        if requested <= 0:
            raise ValueError("У каждого этапа должна остаться положительная длительность.")
        changed_by_id[segment_id]["minutes"] = requested
        cut = original_minutes - requested
        if cut < 0:
            raise ValueError("Нельзя увеличить этап за счёт обязательных частей занятия.")
        if cut:
            cuts.append({"segment_id": segment_id, "minutes": cut,
                         "reason": str(source["flexible_reason"]).strip()})
            total_cut += cut

    inserted_minutes = edits.get(inserted_id, int(inserted.get("minutes") or 0))
    if type(inserted_minutes) is not int or not 5 <= inserted_minutes <= 20 or inserted_minutes != total_cut:
        raise ValueError("Новый этап должен занимать 5–20 минут и полностью компенсироваться гибкими этапами.")
    purpose = str(stage_purpose if stage_purpose is not None else inserted.get("purpose") or "").strip()
    if len(purpose) < 20 or len(purpose) > 500:
        raise ValueError("Описание нового учебного этапа должно содержать от 20 до 500 символов.")
    updated_inserted = {**inserted, "minutes": inserted_minutes, "purpose": purpose}
    changed_by_id[inserted_id].update(updated_inserted)
    lesson_minutes = int(time_plan.get("lesson_minutes") or 0)
    if lesson_minutes <= 0 or sum(int(item.get("minutes") or 0) for item in changed) != lesson_minutes:
        raise ValueError("Сумма этапов должна точно совпадать с длительностью урока.")
    result = {**time_plan, "cuts": cuts, "proposed_segments": changed,
              "inserted_segment": updated_inserted, "planned_lesson_minutes": lesson_minutes,
              "adaptation_minutes": inserted_minutes, "total_with_separate_activity": lesson_minutes,
              "teacher_edits": {"stage_minutes": {key: edits[key] for key in sorted(edits)},
                                "stage_purpose": purpose}}
    return result


def _saved_lesson_pedagogy_structure(lesson: Lesson, *, allow_legacy_segments: bool = False) -> dict[str, Any] | None:
    try:
        scenario = json.loads(str(lesson.studio_scenario or ""))
    except (TypeError, ValueError):
        scenario = None
    if (isinstance(scenario, dict)
            and scenario.get("contract") == "boostudy.lesson-pedagogy.v1"):
        return scenario
    if (allow_legacy_segments and isinstance(scenario, dict)
            and isinstance(scenario.get("segments"), list)):
        return scenario
    saved_summaries = getattr(lesson, "review_summaries", None)
    summaries = saved_summaries if isinstance(saved_summaries, dict) else {}
    saved = summaries.get("_tutor_core_pedagogy")
    if isinstance(saved, dict) and saved.get("contract") == "boostudy.lesson-pedagogy.v1":
        return saved
    return None


def _validated_time_plan(lesson: Lesson, time_plan: dict[str, Any] | None,
                         action: str, exercise_id: str) -> dict[str, Any]:
    if not isinstance(time_plan, dict) or time_plan.get("status") != "redistributed":
        raise ValueError("Изменение урока запрещено: preview не содержит безопасного перераспределения по этапам.")
    saved_contract = _saved_lesson_pedagogy_structure(lesson, allow_legacy_segments=True)
    source = (json.loads(json.dumps(saved_contract, ensure_ascii=False))
              if saved_contract is not None else None)
    if not isinstance(source, dict) or not isinstance(source.get("segments"), list):
        raise ValueError("Изменение урока запрещено: исходный педагогический контракт не содержит структурированных этапов.")
    normalize = lambda rows: [
        {"id": str(row.get("id") or ""), "minutes": int(row.get("minutes") or 0)}
        for row in rows if isinstance(row, dict)
    ] if isinstance(rows, list) else []
    original = normalize(time_plan.get("original_segments"))
    proposed = time_plan.get("proposed_segments")
    proposed_normalized = normalize(proposed)
    duration = int(lesson.duration or 60)
    if (not original or original != normalize(source["segments"]) or not proposed_normalized
            or sum(row["minutes"] for row in proposed_normalized) != duration
            or int(time_plan.get("lesson_minutes") or 0) != duration):
        raise ValueError("Изменение урока запрещено: план не совпадает с исходными этапами или длительностью.")
    cuts = time_plan.get("cuts")
    if not isinstance(cuts, list) or not cuts or any(
        not isinstance(row, dict) or not row.get("segment_id") or not row.get("reason")
        or int(row.get("minutes") or 0) <= 0
        for row in cuts
    ):
        raise ValueError("Изменение урока запрещено: для каждого сокращения нужно обоснование.")
    if action not in {"targeted_diagnostic_and_review", "diagnostic_without_mastery_claim",
                      "extension_with_alternative_method"}:
        raise ValueError("Для выбранного действия не предусмотрено изменение плана.")
    if any(row["minutes"] < 0 for row in proposed_normalized):
        raise ValueError("Изменение урока запрещено: продолжительность этапа не может быть отрицательной.")
    original_by_id = {str(item.get("id")): item for item in source["segments"] if isinstance(item, dict)}
    proposed_by_id = {str(item.get("id")): item for item in proposed if isinstance(item, dict)}
    if len(original_by_id) != len(source["segments"]) or len(proposed_by_id) != len(proposed):
        raise ValueError("Изменение урока запрещено: идентификаторы этапов должны быть уникальными.")
    cut_minutes: dict[str, int] = {}
    for cut in cuts:
        segment_id = str(cut["segment_id"])
        source_segment = original_by_id.get(segment_id)
        proposed_segment = proposed_by_id.get(segment_id)
        try:
            amount = int(cut.get("minutes") or 0)
            flexible = int((source_segment or {}).get("flexible_minutes") or 0)
        except (TypeError, ValueError):
            amount = flexible = 0
        if (not source_segment or not proposed_segment or source_segment.get("mandatory", True)
                or not str(source_segment.get("flexible_reason") or "").strip()
                or amount > flexible or int(source_segment.get("minutes") or 0) - amount < 1
                or int(source_segment.get("minutes") or 0) - amount
                != int(proposed_segment.get("minutes") or 0)):
            raise ValueError("Изменение урока запрещено: этап не объявлен гибким или сокращение превышает его явный резерв.")
        cut_minutes[segment_id] = cut_minutes.get(segment_id, 0) + amount
        if cut_minutes[segment_id] > flexible:
            raise ValueError("Изменение урока запрещено: суммарное сокращение превышает резерв этапа.")
    inserted = time_plan.get("inserted_segment")
    inserted_id = str((inserted or {}).get("id") or "") if isinstance(inserted, dict) else ""
    proposed_inserted = proposed_by_id.get(inserted_id)
    if (not inserted_id or inserted_id in original_by_id or inserted_id not in proposed_by_id
            or int(proposed_by_id[inserted_id].get("minutes") or 0) != sum(cut_minutes.values())
            or int(inserted.get("minutes") or 0) != sum(cut_minutes.values())
             or not 5 <= sum(cut_minutes.values()) <= 20
            or str(inserted.get("exercise_id") or "") != str(exercise_id or "")
             or len(str(inserted.get("purpose") or "").strip()) < 20
             or len(str(inserted.get("purpose") or "").strip()) > 500
            or proposed_inserted != inserted
            or [str(row.get("id") or "") for row in proposed if isinstance(row, dict)].count(inserted_id) != 1):
        raise ValueError("Изменение урока запрещено: добавленный этап не компенсирует явно разрешённые сокращения.")
    original_ids = list(original_by_id)
    proposed_ids = [str(row.get("id") or "") for row in proposed if isinstance(row, dict)]
    if proposed_ids != original_ids[:proposed_ids.index(inserted_id)] + [inserted_id] + original_ids[proposed_ids.index(inserted_id):]:
        raise ValueError("Изменение урока запрещено: нельзя переставлять или удалять исходные этапы.")
    for segment_id, original_segment in original_by_id.items():
        proposed_segment = proposed_by_id.get(segment_id)
        expected_minutes = int(original_segment.get("minutes") or 0) - cut_minutes.get(segment_id, 0)
        original_content = {key: value for key, value in original_segment.items() if key != "minutes"}
        proposed_content = {key: value for key, value in (proposed_segment or {}).items() if key != "minutes"}
        if (not proposed_segment or int(proposed_segment.get("minutes") or 0) != expected_minutes
                or original_content != proposed_content):
            raise ValueError("Изменение урока запрещено: обнаружено необоснованное сокращение или изменение этапа.")
    source["segments"] = proposed
    source.setdefault("adaptation_history", []).append({
        "contract": "boostudy.tutor-time-adjustment.v1", "action": action,
        "cuts": cuts, "inserted_segment": time_plan.get("inserted_segment"),
    })
    return source


def _validated_guided_focus(lesson: Lesson, course: LearningTrajectory, skill_id: str,
                            exercise: dict[str, Any], teacher_focus_text: str) -> tuple[dict[str, Any], str]:
    """Validate an already-planned, exposed-but-unanswered item as guided lesson content."""
    focus = str(teacher_focus_text or "").strip()
    if len(focus) < 30 or len(focus) > 1_500:
        raise ValueError("Фокус урока должен содержать от 30 до 1500 символов.")
    if exercise.get("guided_only") is not True or exercise.get("independent_diagnostic") is not False:
        raise ValueError("Это упражнение нельзя использовать как независимое; нужен отдельный guided-фокус.")
    try:
        task_id = int(exercise.get("task_id"))
    except (TypeError, ValueError):
        raise ValueError("Не удалось подтвердить задание для направленного разбора.")
    from app.ai_lab.platform_homework import _allowlisted_task_author_ids, _task_fingerprint
    from app.task_bank.answer_safety import answer_appears_in_labeled_example
    from core.db_models import AssignmentTask, LessonTaskAttempt, Submission

    task = db.session.get(Tasks, task_id)
    link = LessonTask.query.filter_by(lesson_id=lesson.lesson_id, task_id=task_id).first()
    if (not task or not link or not link.is_visible_to_student
            or int(task.created_by_id or 0) not in _allowlisted_task_author_ids()
            or task.bank_category != "synthetic_adaptive_draft"
            or not str(task.source_key or "").startswith("boostudy.synthetic.adaptive-v1/")
            or not task.is_active or not task.answer
            or str(link.status or "").casefold() not in {"", "pending", "assigned"}
            or link.student_answer or link.student_submission
            or LessonTaskAttempt.query.filter_by(lesson_task_id=link.lesson_task_id).count()
            or AssignmentTask.query.join(Submission, Submission.assignment_id == AssignmentTask.assignment_id)
            .filter(AssignmentTask.task_id == task_id, Submission.student_id == int(lesson.student_id or 0)).count()):
        raise ValueError("Задание уже использовано, изменено или не относится к доступному будущему занятию.")
    if answer_appears_in_labeled_example(task.content_html, task.answer):
        raise ValueError("Эталон попал в условие; задание нельзя использовать в плане ученика.")
    if str(exercise.get("exercise_id") or "") != f"task:{task_id}":
        raise ValueError("Идентификатор упражнения не совпадает с записью банка.")
    if _task_fingerprint(task) != str(exercise.get("task_fingerprint") or ""):
        raise ValueError("Содержание упражнения изменилось после preview.")
    spec = task.answer_spec if isinstance(task.answer_spec, dict) else {}
    binding = spec.get("synthetic_course_skill_binding")
    if spec.get("type") != "short_answer" or spec.get("grading_mode") != "exact":
        raise ValueError("Для упражнения не найден поддерживаемый точный проверяющий.")
    topic_code = str(exercise.get("topic_code") or "")
    criterion_ids = {str(value) for value in exercise.get("criterion_ids", [])}
    lesson_skill = next((item for item in (lesson.skills or [])
                         if f"exam-skill:{int(item.skill_id)}" == skill_id), None)
    if not lesson_skill or topic_code != str(lesson_skill.topic_code or ""):
        raise ValueError("Навык и тема задания не совпадают с целевым уроком.")
    contract = (binding or {}).get("contract") if isinstance(binding, dict) else None
    if contract == "boostudy.synthetic-course-skill.v1":
        exact_binding = (
            int(binding.get("course_id") or 0) == int(course.course_id)
            and int(binding.get("course_version") or 0) == int(course.current_version or 1)
            and int(binding.get("lesson_id") or 0) == int(lesson.lesson_id)
            and str(binding.get("skill_id") or "") == skill_id
            and str(binding.get("criterion_id") or "") in criterion_ids
            and str(binding.get("topic_code") or "") == topic_code
            and str(binding.get("task_fingerprint") or "") == _task_fingerprint(task)
        )
    elif contract == "boostudy.synthetic-course-source-skill.v1":
        from app.ai_lab.analytics import _synthetic_master_task_link
        mapped = _synthetic_master_task_link(task, binding, course, lesson)
        exact_binding = bool(
            mapped
            and f"exam-skill:{int(mapped[0].skill_id)}" == skill_id
            and str(mapped[1]) in criterion_ids
            and str(mapped[0].topic_code or "") == topic_code
        )
    else:
        exact_binding = False
    structure = None
    try:
        structure = json.loads(str(lesson.studio_scenario or ""))
    except (TypeError, ValueError):
        pass
    planned_item = next((item for item in (structure or {}).get("exercises", [])
                         if isinstance(item, dict) and int(item.get("task_id") or 0) == task_id), None)
    if (not exact_binding or not isinstance(structure, dict) or not isinstance(planned_item, dict)
            or planned_item.get("source_type") != "platform_task"
            or planned_item.get("assessment_method") != "platform_exact_answer"
            or str(planned_item.get("role") or "") != "classwork"
            or not criterion_ids & {str(value) for value in planned_item.get("criterion_ids", [])}
            or str(exercise.get("teacher_expected_answer") or "") != str(task.answer)
            or (exercise.get("verification") or {}).get("method") != "BooStudy exact-answer checker"):
        raise ValueError("План урока, критерий, версия и точный checker не подтверждают это упражнение.")
    prior_overlay = structure.get("tutor_core_adaptive_focus")
    if prior_overlay:
        raise ValueError("В этом будущем уроке уже сохранён адаптивный фокус; повтор запрещён.")
    item = {
        "contract": "boostudy.tutor-core-guided-focus.v1",
        "focus": focus,
        "skill_id": skill_id,
        "criterion_ids": sorted(criterion_ids),
        "exercise_id": str(exercise["exercise_id"]),
        "exercise_title": str(exercise.get("title") or ""),
        "exercise_exposure": "prompt_visible_unanswered_guided_only",
        "independent_diagnostic": False,
        "duration_minutes": int(lesson.duration or 60),
    }
    structure["tutor_core_adaptive_focus"] = item
    structure.setdefault("adaptation_history", []).append({
        "contract": "boostudy.tutor-core-guided-focus.v1",
        "action": "teacher_focus_overlay",
        "exercise_id": str(exercise["exercise_id"]),
    })
    note = (
        f"Фокус преподавателя · {str(exercise.get('title') or 'упражнение')}.\n{focus}\n"
        "Условие уже показывалось ученику; использовать только как совместный разбор, "
        "не как независимую диагностику или новое подтверждение навыка. Время и этапы урока не меняются."
    )
    return structure, note


def _validated_exercise_sequence(lesson: Lesson, course: LearningTrajectory, skill_id: str,
                                 sequence: Any, requested_roles: dict[int, str] | None) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    from app.ai_lab.analytics import _synthetic_master_task_link
    from app.ai_lab.platform_homework import _allowlisted_task_author_ids, _task_fingerprint
    from core.db_models import AssignmentTask, LessonTaskAttempt, Submission

    if not isinstance(sequence, list) or len(sequence) != 2 or not isinstance(requested_roles, dict):
        raise ValueError("Для изменения последовательности нужны два упражнения и выбранные роли.")
    items = {int(item.get("task_id") or 0): item for item in sequence if isinstance(item, dict)}
    roles = {int(task_id): str(role or "").strip().lower() for task_id, role in requested_roles.items()}
    if len(items) != 2 or set(roles) != set(items) or set(roles.values()) != {"classwork", "homework"}:
        raise ValueError("В плане должно остаться ровно одно классное упражнение и одно домашнее.")
    old_roles = {task_id: str(item.get("current_role") or "").strip().lower()
                 for task_id, item in items.items()}
    if set(old_roles.values()) != {"classwork", "homework"} or roles == old_roles:
        raise ValueError("Выбранное распределение не меняет две однозначно связанные исходные роли.")
    common_criteria = set.intersection(*[
        {str(value) for value in item.get("criterion_ids", []) if value}
        for item in items.values()
    ])
    if len(common_criteria) != 1 or any(item.get("course_skill_id") != skill_id for item in items.values()):
        raise ValueError("Оба упражнения должны проверять один критерий того же навыка.")
    allowed_authors = _allowlisted_task_author_ids()
    if not allowed_authors:
        raise ValueError("Нет разрешённого автора synthetic-заданий.")

    try:
        scenario = json.loads(str(lesson.studio_scenario or ""))
    except (TypeError, ValueError):
        scenario = None
    if not isinstance(scenario, dict) or not isinstance(scenario.get("exercises"), list):
        raise ValueError("Будущий урок не содержит структурированного списка упражнений.")
    scenario_items = {int(item.get("task_id") or 0): item for item in scenario["exercises"]
                      if isinstance(item, dict) and str(item.get("task_id") or "").isdigit()}
    validated = []
    for task_id, item in items.items():
        task = db.session.get(Tasks, task_id)
        link = LessonTask.query.filter_by(lesson_id=int(lesson.lesson_id), task_id=task_id).with_for_update().first()
        spec = task.answer_spec if task and isinstance(task.answer_spec, dict) else {}
        binding = spec.get("synthetic_course_skill_binding")
        mapped = _synthetic_master_task_link(task, binding, course, lesson) if task and isinstance(binding, dict) else None
        if (not task or not link or not link.is_visible_to_student
                or str(link.assignment_type or "").strip().lower() != old_roles[task_id]
                or str(link.status or "").casefold() not in {"", "pending", "assigned"}
                or link.student_answer or link.student_submission
                or LessonTaskAttempt.query.filter_by(lesson_task_id=link.lesson_task_id).count()
                or AssignmentTask.query.join(Submission, Submission.assignment_id == AssignmentTask.assignment_id)
                .filter(AssignmentTask.task_id == task_id, Submission.student_id == int(lesson.student_id)).count()
                or int(task.created_by_id or 0) not in allowed_authors
                or task.bank_category != "synthetic_adaptive_draft"
                or not str(task.source_key or "").startswith("boostudy.synthetic.adaptive-v1/")
                or not task.is_active or not task.answer
                or spec.get("type") != "short_answer" or spec.get("grading_mode") != "exact"
                or str(item.get("task_fingerprint") or "") != _task_fingerprint(task)
                or not mapped or f"exam-skill:{int(mapped[0].skill_id)}" != skill_id
                or str(mapped[1]) not in common_criteria
                or str(item.get("topic_code") or "") != str(mapped[0].topic_code or "")):
            raise ValueError("Упражнение изменено, уже использовано или не прошло точную проверку связи и checker.")
        scenario_item = scenario_items.get(task_id)
        if (not scenario_item or str(scenario_item.get("role") or "").lower() != old_roles[task_id]
                or str(scenario_item.get("assessment_method") or "") != "platform_exact_answer"):
            raise ValueError("Структура упражнения изменилась после предпросмотра.")
        validated.append({"task_id": task_id, "lesson_task_id": int(link.lesson_task_id),
                          "from": old_roles[task_id], "to": roles[task_id],
                          "task_fingerprint": _task_fingerprint(task)})

    for item in validated:
        scenario_items[item["task_id"]]["role"] = item["to"]
    criterion_id = next(iter(common_criteria))
    scenario.setdefault("adaptation_history", []).append({
        "contract": "boostudy.tutor-core-exercise-sequence.v1",
        "action": "exercise_sequence_adjustment", "skill_id": skill_id,
        "criterion_id": criterion_id, "roles": validated,
        "duration_minutes": int(lesson.duration or 60),
    })
    return scenario, validated, criterion_id


def resolve_assigned_synthetic_copy(student_id: int) -> dict[str, Any]:
    """Resolve one active, explicitly allowlisted student copy without guessing.

    Historical Tutor Core demos may also create student-linked trajectory rows.
    They are not assignments unless they are active copies of an allowlisted
    template. Multiple active copies are reported as ambiguous; no latest-row
    selection is performed.
    """
    if not _adapter_enabled() or type(student_id) is not int or student_id <= 0:
        return {"status": "unavailable", "copy": None, "candidate_ids": []}

    allowed_courses = _allowed_course_ids()
    allowed_copies = _allowed_copy_ids()
    if not allowed_courses or not allowed_copies:
        return {"status": "not_allowlisted", "copy": None, "candidate_ids": []}

    active_copies = (LearningTrajectory.query.filter_by(
        student_id=student_id, is_template=False, status="active",
    ).filter(LearningTrajectory.parent_course_id.isnot(None))
        .order_by(LearningTrajectory.course_id.asc()).all())
    if not active_copies:
        return {"status": "no_active_copy", "copy": None, "candidate_ids": []}

    eligible = []
    for copy in active_copies:
        parent_id = int(copy.parent_course_id or 0)
        if int(copy.course_id) not in allowed_copies or parent_id not in allowed_courses:
            continue
        parent = db.session.get(LearningTrajectory, parent_id)
        if (parent and parent.is_template and parent.student_id is None
                and str(parent.status or "").casefold() == "active"):
            eligible.append(copy)

    if len(active_copies) > 1:
        return {
            "status": "ambiguous_active_copies",
            "copy": None,
            "candidate_ids": [int(item.course_id) for item in active_copies],
            "eligible_ids": [int(item.course_id) for item in eligible],
        }
    if len(eligible) == 1:
        return {
            "status": "resolved",
            "copy": eligible[0],
            "candidate_ids": [int(eligible[0].course_id)],
            "eligible_ids": [int(eligible[0].course_id)],
        }
    return {
        "status": "active_copy_not_allowlisted",
        "copy": None,
        "candidate_ids": [int(item.course_id) for item in active_copies],
        "eligible_ids": [],
    }


def _validated_unassigned_platform_task_link(*, lesson: Lesson, course: LearningTrajectory,
                                            student_id: int, skill_id: str,
                                            exercise: dict[str, Any]) -> LessonTask:
    """Recheck a hidden, exact-version LessonTask before making it student-visible."""
    if exercise.get("source_type") != "platform_task":
        raise ValueError("Новый этап можно связать только с сохранённым заданием из банка курса.")
    from app.models import Student
    student = Student.query.filter_by(student_id=student_id).first()
    if not student or not student.user_id:
        raise ValueError("Не удалось подтвердить синтетического ученика для нового задания.")
    structure = _saved_lesson_pedagogy_structure(lesson)
    if not isinstance(structure, dict):
        raise ValueError("Структура будущего урока изменилась после preview.")
    from app.ai_lab.tutor_core import _verified_lesson_task_candidates
    candidates = _verified_lesson_task_candidates(
        {"lesson_id": int(lesson.lesson_id), "status": str(lesson.status or ""),
         "started_at": lesson.started_at, "pedagogical_structure": structure},
        course_id=int(course.course_id), course_version=int(course.current_version or 1),
        skill_id=skill_id, profile_id=f"platform-student:{int(student.user_id)}",
        student_id=student_id,
    )
    try:
        task_id = int(exercise.get("task_id") or 0)
        lesson_task_id = int(exercise.get("lesson_task_id") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("В preview отсутствует сохранённая связь задания с уроком.") from exc
    candidate = next((item for item in candidates
                       if int(item.get("task_id") or 0) == task_id
                       and int(item.get("lesson_task_id") or 0) == lesson_task_id), None)
    exact_fields = ("exercise_id", "task_fingerprint", "course_skill_id", "topic_code", "prompt",
                    "teacher_expected_answer")
    if (not candidate or candidate.get("previous_usage", {}).get("previously_used", True)
            or any(str(candidate.get(key) or "") != str(exercise.get(key) or "") for key in exact_fields)
            or {str(item) for item in candidate.get("criterion_ids") or []}
               != {str(item) for item in exercise.get("criterion_ids") or []}
            or (candidate.get("verification") or {}).get("method") != "BooStudy exact-answer checker"):
        raise ValueError("Задание уже использовано, изменилось или не прошло точную повторную проверку.")
    link = LessonTask.query.filter_by(
        lesson_task_id=lesson_task_id, lesson_id=lesson.lesson_id, task_id=task_id,
    ).with_for_update().first()
    if (not link or link.is_visible_to_student
            or str(link.status or "").casefold() not in {"", "pending", "assigned"}
            or link.student_answer or link.student_submission):
        raise ValueError("Задание уже доступно ученику или в нём появилась учебная активность.")
    return link


def apply_tutor_copy_adjustment(*, actor_id: int, course_id: int, student_id: int,
                                expected_version: int, lesson_id: int, skill_id: str,
                                action: str, evidence_refs: list[str],
                                exercise_snapshot: dict[str, Any] | None = None,
                                exercise_sequence: list[dict[str, Any]] | None = None,
                                exercise_roles: dict[int, str] | None = None,
                                time_plan: dict[str, Any] | None = None,
                                teacher_focus_text: str | None = None) -> dict[str, Any] | None:
    """Apply a deterministic teacher-approved note to one allowlisted synthetic copy."""
    if not _adapter_enabled() or course_id not in _allowed_copy_ids():
        return None
    _require_copy_actor_scope(actor_id, student_id)
    course = LearningTrajectory.query.filter_by(
        course_id=course_id, student_id=student_id, is_template=False,
    ).with_for_update().first()
    if (course is None or course.parent_course_id not in _allowed_course_ids()
            or int(course.current_version or 1) != int(expected_version)):
        raise ValueError("Индивидуальная копия отсутствует, не разрешена или изменилась после предложения.")
    parent = LearningTrajectory.query.filter_by(
        course_id=course.parent_course_id, is_template=True, student_id=None,
    ).first()
    if parent is None:
        raise ValueError("Исходный шаблон копии не прошёл проверку изоляции.")
    lesson = Lesson.query.filter_by(
        lesson_id=lesson_id, learning_trajectory_id=course_id, student_id=student_id,
    ).with_for_update().first()
    if (lesson is None or str(lesson.status or "").casefold() not in {"planned", "scheduled"}
            or lesson.started_at is not None
            or skill_id not in {f"exam-skill:{item.skill_id}" for item in (lesson.skills or [])}):
        raise ValueError("Целевой урок уже начат, не принадлежит копии или не связан с подтверждённым навыком.")
    exercise = exercise_snapshot if isinstance(exercise_snapshot, dict) else {}
    exercise_title = str(exercise.get("title") or "").strip()
    exercise_prompt = str(exercise.get("prompt") or "").strip()
    verification = exercise.get("verification") if isinstance(exercise.get("verification"), dict) else {}
    expected_answer = exercise.get("teacher_expected_answer")
    lesson_skill = next((item for item in (lesson.skills or [])
                         if f"exam-skill:{item.skill_id}" == skill_id), None)
    exposed_task_link = None
    if action in {"targeted_diagnostic_and_review", "diagnostic_without_mastery_claim",
                  "extension_with_alternative_method"}:
        if (not exercise.get("exercise_id") or len(exercise_title) > 200 or not exercise_title
                or not exercise_prompt or len(exercise_prompt) > 12_000
                or exercise.get("course_skill_id") != skill_id
                or not lesson_skill or str(exercise.get("topic_code") or "") != str(lesson_skill.topic_code or "")
                or expected_answer is None):
            raise ValueError("Предлагаемое упражнение не прошло проверку связи с навыком и проверяемым ответом.")
        if exercise.get("source_type") == "platform_task":
            if (verification.get("status") != "configured_exact_checker"
                    or verification.get("method") != "BooStudy exact-answer checker"):
                raise ValueError("Платформенное упражнение не подтверждено точным штатным проверяющим.")
            exposed_task_link = _validated_unassigned_platform_task_link(
                lesson=lesson, course=course, student_id=student_id,
                skill_id=skill_id, exercise=exercise,
            )
        elif (exercise.get("source_type") != "practice_generator"
              or verification.get("status") != "verified"
              or verification.get("method") != "existing AI Practice deterministic checker"):
            raise ValueError("Для изменения урока требуется сохранённое задание с поддерживаемым проверяющим.")
    if action == "teacher_focus_overlay":
        if not exercise.get("exercise_id") or not exercise_title or not exercise_prompt or len(exercise_prompt) > 12_000:
            raise ValueError("Для фокуса урока требуется существующее проверяемое упражнение.")
        updated_scenario, note = _validated_guided_focus(
            lesson, course, skill_id, exercise, str(teacher_focus_text or ""),
        )
    elif action == "exercise_sequence_adjustment":
        updated_scenario, validated_roles, criterion_id = _validated_exercise_sequence(
            lesson, course, skill_id, exercise_sequence, exercise_roles,
        )
        note = (
            f"Перераспределены роли двух упражнений по критерию «{criterion_id}». "
            "Цели, критерии, этапы и продолжительность сохранены; условия уже видны ученику и не считаются независимой диагностикой."
        )
    elif action == "targeted_diagnostic_and_review":
        inserted = (time_plan or {}).get("inserted_segment") or {}
        note = (f"Этап индивидуальной адаптации Tutor Core ({int(inserted.get('minutes') or 0)} минут): "
                f"{str(inserted.get('purpose') or '').strip()} Основные учебные цели сохраняются.")
    elif action == "diagnostic_without_mastery_claim":
        inserted = (time_plan or {}).get("inserted_segment") or {}
        note = (f"Диагностический этап Tutor Core ({int(inserted.get('minutes') or 0)} минут): "
                f"{str(inserted.get('purpose') or '').strip()} Единичный результат не подтверждает "
                "ни освоение, ни устойчивое затруднение.")
    elif action == "extension_with_alternative_method":
        inserted = (time_plan or {}).get("inserted_segment") or {}
        note = (f"Этап проверки переноса ({int(inserted.get('minutes') or 0)} минут): "
                f"{str(inserted.get('purpose') or '').strip()} Это наблюдение по одному упражнению, "
                "а не утверждение полного освоения.")
    elif action != "teacher_focus_overlay":
        raise ValueError("Для этого действия нет разрешённого изменения индивидуального плана.")
    if action not in {"teacher_focus_overlay", "exercise_sequence_adjustment"}:
        note += (
            f"\nПроверяемое упражнение: {exercise_title}.\n"
            f"{exercise_prompt}\n"
            f"Тип ответа: {exercise.get('answer_type') or 'не указан'}. "
            "Проверка использует существующий детерминированный checker AI Practice; ожидаемый ответ остаётся в преподавательском черновике."
        )
    refs = list(dict.fromkeys(str(ref).strip() for ref in evidence_refs
                              if isinstance(ref, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", ref.strip())))
    if not refs or len(refs) > 20 or len(refs) != len([ref for ref in evidence_refs if isinstance(ref, str) and ref.strip()]):
        raise ValueError("Для изменения плана нужны ссылки на сохранённые подтверждённые события.")
    old_scenario = str(lesson.studio_scenario or "")
    try:
        old_structure = json.loads(old_scenario)
    except (TypeError, ValueError):
        old_structure = {}
    summaries_before = dict(lesson.review_summaries or {}) if isinstance(lesson.review_summaries, dict) else {}
    old_pedagogy_structure = summaries_before.get("_tutor_core_pedagogy")
    if not isinstance(old_pedagogy_structure, dict):
        old_pedagogy_structure = None
    history = (old_structure.get("adaptation_history") or []) if isinstance(old_structure, dict) else []
    has_sequence = any(isinstance(item, dict)
                       and item.get("contract") == "boostudy.tutor-core-exercise-sequence.v1"
                       for item in history)
    has_focus = bool((old_structure or {}).get("tutor_core_adaptive_focus"))
    if ("boostudy.tutor-time-adjustment.v1" in old_scenario
            or (action == "teacher_focus_overlay" and has_focus)
            or (action == "exercise_sequence_adjustment" and has_sequence)
            or (action not in {"teacher_focus_overlay", "exercise_sequence_adjustment"}
                and "boostudy.tutor-core-guided-focus.v1" in old_scenario)):
        raise ValueError("В целевом уроке уже есть адаптация Tutor Core; повторное применение запрещено.")
    if action not in {"teacher_focus_overlay", "exercise_sequence_adjustment"}:
        updated_scenario = _validated_time_plan(
            lesson, time_plan, action, str(exercise.get("exercise_id") or ""),
        )
    if action != "exercise_sequence_adjustment":
        updated_scenario["adaptation_history"][-1].update({
        "skill_id": skill_id,
        "evidence_refs": refs,
        "exercise_id": str(exercise.get("exercise_id")),
        "teacher_note": note,
        })
    else:
        updated_scenario["adaptation_history"][-1].update({
            "evidence_refs": refs, "teacher_note": note,
        })
    new_pedagogy_structure = None
    summaries_after = None
    time_action = action not in {"teacher_focus_overlay", "exercise_sequence_adjustment"}
    if (time_action and updated_scenario.get("contract") == "boostudy.lesson-pedagogy.v1"):
        new_pedagogy_structure = updated_scenario
        summaries_after = dict(summaries_before)
        summaries_after["_tutor_core_pedagogy"] = updated_scenario
        # The lesson editor stores the canonical structure separately from its plain-text agenda.
        # Keep that agenda intact while making Tutor Core and the editor read the same updated contract.
        if not (isinstance(old_structure, dict)
                and old_structure.get("contract") == "boostudy.lesson-pedagogy.v1"):
            updated_scenario = old_scenario
    new_scenario = (updated_scenario if isinstance(updated_scenario, str) else
                    json.dumps(updated_scenario, ensure_ascii=False, separators=(",", ":")))
    if len(new_scenario.encode("utf-8")) > 32_768:
        raise ValueError("План целевого урока превышает допустимый размер; изменение остановлено.")
    latest = db.session.query(func.max(LearningTrajectoryVersion.version_number)).filter_by(course_id=course_id).scalar()
    snapshot_version = max(int(course.current_version or 1), int(latest or 0) + 1)
    before = int(course.current_version or 1)
    evidence_snapshots_by_lesson = _course_evidence_semantics_by_lesson(
        course_id=course_id, course_version=before,
    )
    lesson_count = Lesson.query.filter_by(
        learning_trajectory_id=course_id, student_id=student_id,
    ).count()
    if not lesson_count or len(evidence_snapshots_by_lesson) != lesson_count:
        raise ValueError("Изменение остановлено: не удалось сохранить семантический снимок всех уроков копии.")
    evidence_snapshot = next((item for item in evidence_snapshots_by_lesson
                              if int(item.get("lesson_id") or 0) == int(lesson_id)), None)
    if evidence_snapshot is None:
        raise ValueError("Изменение остановлено: снимок целевого урока отсутствует.")
    db.session.add(LearningTrajectoryVersion(
        course_id=course_id,
        version_number=snapshot_version,
        reason="Tutor Core: снимок индивидуального плана перед решением преподавателя",
        created_by_user_id=actor_id,
        snapshot={"kind": "tutor_core_copy_snapshot.v2", "lesson_id": lesson_id,
                  "studio_scenario": old_scenario, "student_id": student_id,
                  "pedagogical_structure": old_pedagogy_structure,
                  "source_template_id": int(course.parent_course_id),
                  "snapshot_of_course_version": before,
                  "evidence_semantics": evidence_snapshot,
                  "evidence_semantics_by_lesson": evidence_snapshots_by_lesson,
                  "evidence_semantics_coverage_complete": True,
                  "task_visibility_before": ({
                      "lesson_task_id": int(exposed_task_link.lesson_task_id),
                      "task_id": int(exposed_task_link.task_id),
                      "is_visible_to_student": bool(exposed_task_link.is_visible_to_student),
                  } if exposed_task_link else None),
                  "exercise_roles_before": ([{"task_id": item["task_id"], "role": item["from"]}
                                             for item in validated_roles]
                                            if action == "exercise_sequence_adjustment" else []),
                  "decision": action,
                  "selected_exercise_id": (str(exercise.get("exercise_id"))
                                            if exercise.get("exercise_id") else None)},
    ))
    old_hash = hashlib.sha256(old_scenario.encode("utf-8")).hexdigest()
    if action == "exercise_sequence_adjustment":
        for item in validated_roles:
            link = db.session.get(LessonTask, int(item["lesson_task_id"]))
            if not link or int(link.lesson_id) != int(lesson.lesson_id):
                raise ValueError("Связь упражнения с уроком изменилась до сохранения решения.")
            link.assignment_type = str(item["to"])
    if exposed_task_link:
        exposed_task_link.is_visible_to_student = True
    lesson.studio_scenario = new_scenario
    if summaries_after is not None:
        lesson.review_summaries = summaries_after
    course.current_version = snapshot_version + 1
    db.session.flush()
    return {
        "course_id": course_id, "student_id": student_id, "lesson_id": lesson_id,
        "skill_id": skill_id, "action": action, "old_scenario": old_scenario,
        "old_pedagogical_structure": old_pedagogy_structure,
        "new_pedagogical_structure_sha256": (
            hashlib.sha256(json.dumps(new_pedagogy_structure, ensure_ascii=False,
                                     sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
            if new_pedagogy_structure is not None else None
        ),
        "new_scenario_sha256": hashlib.sha256(new_scenario.encode("utf-8")).hexdigest(),
        "old_scenario_sha256": old_hash, "old_course_version": before,
        "snapshot_version": snapshot_version, "new_course_version": int(course.current_version),
        "evidence_refs": refs, "source_template_id": int(course.parent_course_id),
        "selected_exercise_id": (str(exercise.get("exercise_id"))
                                  if exercise.get("exercise_id") else None),
        "target_lesson_title": str(lesson.topic or ""),
        "teacher_focus": str(teacher_focus_text or "").strip() if action == "teacher_focus_overlay" else None,
        "old_exercise_roles": ([{"task_id": item["task_id"], "role": item["from"]}
                                for item in validated_roles]
                               if action == "exercise_sequence_adjustment" else []),
        "new_exercise_roles": ([{"task_id": item["task_id"], "role": item["to"]}
                                for item in validated_roles]
                               if action == "exercise_sequence_adjustment" else []),
        "time_plan_change": ({
            "original_segments": time_plan.get("original_segments"),
            "proposed_segments": time_plan.get("proposed_segments"),
            "cuts": time_plan.get("cuts"),
            "inserted_segment": time_plan.get("inserted_segment"),
            "total_minutes": time_plan.get("lesson_minutes"),
        } if action not in {"teacher_focus_overlay", "exercise_sequence_adjustment"}
            and isinstance(time_plan, dict) else None),
        "task_visibility_change": ({
            "lesson_task_id": int(exposed_task_link.lesson_task_id),
            "task_id": int(exposed_task_link.task_id),
            "before": False,
            "after": True,
        } if exposed_task_link else None),
        "exercise_usage_scope": "guided_existing_lesson_item_not_independent"
        if action == "teacher_focus_overlay" else None,
    }


def rollback_tutor_copy_adjustment(*, actor_id: int, change: dict[str, Any]) -> dict[str, Any] | None:
    """Restore a copied lesson only while its applied text and version are unchanged."""
    try:
        course_id, student_id, lesson_id = int(change["course_id"]), int(change["student_id"]), int(change["lesson_id"])
    except (KeyError, TypeError, ValueError):
        return None
    if not _adapter_enabled() or course_id not in _allowed_copy_ids():
        return None
    _require_copy_actor_scope(actor_id, student_id)
    course = LearningTrajectory.query.filter_by(
        course_id=course_id, student_id=student_id, is_template=False,
    ).with_for_update().first()
    lesson = Lesson.query.filter_by(
        lesson_id=lesson_id, learning_trajectory_id=course_id, student_id=student_id,
    ).with_for_update().first()
    if (course is None or lesson is None or course.parent_course_id not in _allowed_course_ids()
            or int(course.current_version or 1) != int(change.get("new_course_version") or -1)):
        raise ValueError("Индивидуальный план изменился после применения; безопасное восстановление остановлено.")
    if int(change.get("source_template_id") or 0) != int(course.parent_course_id or 0):
        raise ValueError("Исходный шаблон индивидуальной копии изменился; восстановление остановлено.")
    current = str(lesson.studio_scenario or "")
    if hashlib.sha256(current.encode("utf-8")).hexdigest() != change.get("new_scenario_sha256"):
        raise ValueError("Сценарий урока изменился после применения; безопасное восстановление остановлено.")
    summaries_current = dict(lesson.review_summaries or {}) if isinstance(lesson.review_summaries, dict) else {}
    current_pedagogy = summaries_current.get("_tutor_core_pedagogy")
    expected_pedagogy_hash = change.get("new_pedagogical_structure_sha256")
    if expected_pedagogy_hash:
        current_pedagogy_hash = (hashlib.sha256(json.dumps(
            current_pedagogy, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest() if isinstance(current_pedagogy, dict) else None)
        if current_pedagogy_hash != expected_pedagogy_hash:
            raise ValueError("Педагогическая структура изменилась после применения; безопасное восстановление остановлено.")
    if str(lesson.status or "").casefold() not in {"planned", "scheduled"} or lesson.started_at is not None:
        raise ValueError("Откат доступен только до начала адаптированного урока; история проведённого занятия сохраняется.")
    old_roles = change.get("old_exercise_roles") or []
    new_roles = change.get("new_exercise_roles") or []
    role_links = []
    visibility_link = None
    visibility_change = change.get("task_visibility_change")
    if visibility_change:
        from core.db_models import AssignmentTask, LessonTaskAttempt, Submission
        link = LessonTask.query.filter_by(
            lesson_task_id=int(visibility_change.get("lesson_task_id") or 0),
            lesson_id=lesson_id, task_id=int(visibility_change.get("task_id") or 0),
        ).with_for_update().first()
        if (not link or bool(link.is_visible_to_student) is not bool(visibility_change.get("after"))
                or bool(visibility_change.get("before")) is not False
                or str(link.status or "").casefold() not in {"", "pending", "assigned"}
                or link.student_answer or link.student_submission
                or LessonTaskAttempt.query.filter_by(lesson_task_id=link.lesson_task_id).count()
                or AssignmentTask.query.join(Submission, Submission.assignment_id == AssignmentTask.assignment_id)
                .filter(AssignmentTask.task_id == int(visibility_change.get("task_id") or 0),
                        Submission.student_id == student_id).count()):
            raise ValueError("После адаптации задание уже открыто ученику или появилась попытка; безопасный откат остановлен.")
        visibility_link = link
    if old_roles or new_roles:
        if (len(old_roles) != 2 or len(new_roles) != 2
                or str(lesson.status or "").casefold() not in {"planned", "scheduled"}
                or lesson.started_at is not None):
            raise ValueError("Откат ролей разрешён только для не начатого урока с полной историей изменения.")
        from core.db_models import LessonTaskAttempt
        expected_new = {int(item["task_id"]): str(item["role"]) for item in new_roles}
        restore = {int(item["task_id"]): str(item["role"]) for item in old_roles}
        if set(expected_new) != set(restore):
            raise ValueError("История ролей не позволяет однозначно восстановить исходный план.")
        for task_id, expected_role in expected_new.items():
            link = LessonTask.query.filter_by(lesson_id=lesson_id, task_id=task_id).with_for_update().first()
            if (not link or str(link.assignment_type or "").lower() != expected_role
                    or str(link.status or "").casefold() not in {"", "pending", "assigned"}
                    or link.student_answer or link.student_submission
                    or LessonTaskAttempt.query.filter_by(lesson_task_id=link.lesson_task_id).count()):
                raise ValueError("После применения уже появилась учебная активность; безопасный откат ролей остановлен.")
            role_links.append((link, restore[task_id]))
    latest = db.session.query(func.max(LearningTrajectoryVersion.version_number)).filter_by(course_id=course_id).scalar()
    snapshot_version = max(int(course.current_version or 1), int(latest or 0) + 1)
    before = int(course.current_version or 1)
    evidence_snapshots_by_lesson = _course_evidence_semantics_by_lesson(
        course_id=course_id, course_version=before,
    )
    lesson_count = Lesson.query.filter_by(
        learning_trajectory_id=course_id, student_id=student_id,
    ).count()
    if not lesson_count or len(evidence_snapshots_by_lesson) != lesson_count:
        raise ValueError("Откат остановлен: не удалось сохранить семантический снимок всех уроков копии.")
    evidence_snapshot = next((item for item in evidence_snapshots_by_lesson
                              if int(item.get("lesson_id") or 0) == int(lesson_id)), None)
    if evidence_snapshot is None:
        raise ValueError("Откат остановлен: снимок целевого урока отсутствует.")
    db.session.add(LearningTrajectoryVersion(
        course_id=course_id, version_number=snapshot_version,
        reason="Tutor Core: снимок индивидуального плана перед восстановлением",
        created_by_user_id=actor_id,
        snapshot={"kind": "tutor_core_copy_rollback_snapshot.v2", "lesson_id": lesson_id,
                  "studio_scenario": current, "student_id": student_id,
                  "pedagogical_structure": current_pedagogy if isinstance(current_pedagogy, dict) else None,
                  "source_template_id": int(course.parent_course_id or 0),
                  "snapshot_of_course_version": before,
                  "evidence_semantics": evidence_snapshot,
                  "evidence_semantics_by_lesson": evidence_snapshots_by_lesson,
                  "evidence_semantics_coverage_complete": True,
                  "exercise_roles_before": new_roles,
                  "task_visibility_before": ({
                      "lesson_task_id": int(visibility_link.lesson_task_id),
                      "task_id": int(visibility_link.task_id),
                      "is_visible_to_student": bool(visibility_link.is_visible_to_student),
                  } if visibility_link else None)},
    ))
    for link, restored_role in role_links:
        link.assignment_type = restored_role
    if visibility_link:
        visibility_link.is_visible_to_student = bool(visibility_change.get("before"))
    lesson.studio_scenario = str(change.get("old_scenario") or "")
    restored_pedagogy = change.get("old_pedagogical_structure")
    if expected_pedagogy_hash:
        if isinstance(restored_pedagogy, dict):
            summaries_current["_tutor_core_pedagogy"] = restored_pedagogy
        else:
            summaries_current.pop("_tutor_core_pedagogy", None)
        lesson.review_summaries = summaries_current
    course.current_version = snapshot_version + 1
    db.session.flush()
    return {"course_id": course_id, "student_id": student_id, "lesson_id": lesson_id,
            "restored_course_version": int(course.current_version),
            "restored_scenario_sha256": hashlib.sha256(lesson.studio_scenario.encode("utf-8")).hexdigest(),
            "restored_pedagogical_structure": restored_pedagogy if expected_pedagogy_hash else None,
            "restored_exercise_roles": old_roles,
            "restored_task_visibility": ({
                "lesson_task_id": int(visibility_link.lesson_task_id),
                "task_id": int(visibility_link.task_id),
                "is_visible_to_student": bool(visibility_link.is_visible_to_student),
            } if visibility_link else None)}


def list_synthetic_learning_trajectories() -> list[dict[str, Any]]:
    """List only explicitly allowlisted master-course rows; never student plans."""
    if not _adapter_enabled():
        return []
    allowed_ids = _allowed_course_ids()
    if not allowed_ids:
        return []
    rows = (db.session.query(LearningTrajectory.course_id, LearningTrajectory.title,
                             LearningTrajectory.current_version)
            .filter(LearningTrajectory.course_id.in_(allowed_ids),
                    LearningTrajectory.is_template.is_(True),
                    LearningTrajectory.student_id.is_(None))
            .order_by(LearningTrajectory.title.asc(), LearningTrajectory.course_id.asc()).all())
    return [{"course_id": row.course_id, "title": row.title, "version": row.current_version}
            for row in rows]


def _block_text(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [text for item in value for text in _block_text(item)]
    if not isinstance(value, dict):
        return []
    result = []
    for key in ("text", "markdown", "content"):
        text = value.get(key)
        if isinstance(text, str) and text.strip():
            result.append(text.strip())
    result.extend(_block_text(value.get("children")))
    return result


def _plain_task_text(content_html: str | None) -> str:
    if not content_html:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", content_html)).strip()[:4_000]


def export_synthetic_learning_trajectory(course_id: int) -> dict[str, Any] | None:
    """Project a synthetic master course onto the AI Course v1 input contract.

    The allowlist is an explicit local-test-database boundary. Only public course
    structure/material columns are selected; student notes, answers and submissions
    are never read. The function has no write path.
    """
    if not _adapter_enabled() or course_id not in _allowed_course_ids():
        return None
    course = db.session.query(
        LearningTrajectory.course_id, LearningTrajectory.title, LearningTrajectory.subject,
        LearningTrajectory.description, LearningTrajectory.learning_goal, LearningTrajectory.expected_result,
        LearningTrajectory.current_version,
    ).filter(
        LearningTrajectory.course_id == course_id, LearningTrajectory.is_template.is_(True),
        LearningTrajectory.student_id.is_(None),
    ).first()
    if course is None:
        return None

    modules = (db.session.query(TrajectoryModule.module_id, TrajectoryModule.title,
                               TrajectoryModule.description, TrajectoryModule.learning_result,
                               TrajectoryModule.order_index)
               .filter(TrajectoryModule.course_id == course.course_id)
               .order_by(TrajectoryModule.order_index.asc(), TrajectoryModule.module_id.asc()).all())
    module_by_id = {module.module_id: module for module in modules}
    lessons = (db.session.query(Lesson.lesson_id, Lesson.course_module_id, Lesson.course_order_index,
                                Lesson.topic, Lesson.content, Lesson.content_blocks, Lesson.updated_at)
               .filter(Lesson.learning_trajectory_id == course.course_id, Lesson.student_id.is_(None))
               .order_by(Lesson.course_order_index.asc(), Lesson.lesson_id.asc()).all())
    lesson_by_id = {lesson.lesson_id: lesson for lesson in lessons}
    learning_items = (db.session.query(LearningItem.item_id, LearningItem.module_id, LearningItem.lesson_id,
                                       LearningItem.skill_id, LearningItem.item_type, LearningItem.title,
                                       LearningItem.why_now, LearningItem.order_index)
                      .filter(LearningItem.course_id == course.course_id)
                      .order_by(LearningItem.order_index.asc(), LearningItem.item_id.asc()).all())

    linked_skill_ids = {item.skill_id for item in learning_items if item.skill_id}
    skills = {item.skill_id: item for item in db.session.query(
        ExamSkill.skill_id, ExamSkill.prerequisite_skill_id, ExamSkill.prerequisite_ids
    ).filter(ExamSkill.skill_id.in_(linked_skill_ids)).all()} if linked_skill_ids else {}
    topic_for_module = {module_id: f"boostudy-module:{module_id}" for module_id in module_by_id}
    skill_to_topic = {}
    for item in learning_items:
        if item.module_id in topic_for_module and item.skill_id:
            skill_to_topic.setdefault(item.skill_id, topic_for_module[item.module_id])

    topics = []
    goals = []
    for index, module in enumerate(modules, 1):
        topic_id = topic_for_module[module.module_id]
        module_skills = [item.skill_id for item in learning_items if item.module_id == module.module_id and item.skill_id]
        prerequisites = []
        for skill_id in module_skills:
            skill = skills.get(skill_id)
            prerequisite_ids = list(skill.prerequisite_ids or []) if skill else []
            if skill and skill.prerequisite_skill_id:
                prerequisite_ids.append(skill.prerequisite_skill_id)
            for prerequisite_id in prerequisite_ids:
                prerequisite_topic = skill_to_topic.get(prerequisite_id)
                if prerequisite_topic and prerequisite_topic != topic_id:
                    prerequisites.append(prerequisite_topic)
        topics.append({"topic_id": topic_id, "title": module.title, "order": index,
                       "prerequisite_ids": list(dict.fromkeys(prerequisites)),
                       "skill_id": f"exam-skill:{module_skills[0]}" if module_skills else None,
                       "source_module_id": module.module_id})
        if module.learning_result and module.learning_result.strip():
            goals.append({"goal_id": f"boostudy-goal:module:{module.module_id}",
                          "text": module.learning_result.strip(), "topic_ids": [topic_id]})
    if course.learning_goal and course.learning_goal.strip():
        goals.append({"goal_id": f"boostudy-goal:course:{course.course_id}",
                      "text": course.learning_goal.strip(), "topic_ids": [item["topic_id"] for item in topics]})
    if course.expected_result and course.expected_result.strip():
        goals.append({"goal_id": f"boostudy-result:course:{course.course_id}",
                      "text": course.expected_result.strip(), "topic_ids": [item["topic_id"] for item in topics]})

    materials = []
    for lesson in lessons:
        topic_id = topic_for_module.get(lesson.course_module_id)
        content = "\n\n".join([lesson.topic.strip() if lesson.topic else "", lesson.content.strip() if lesson.content else "",
                                  "\n".join(_block_text(lesson.content_blocks))]).strip()
        if not content:
            continue
        updated_at = lesson.updated_at.isoformat() if lesson.updated_at else str(course.current_version)
        materials.append({"material_id": f"boostudy-lesson:{lesson.lesson_id}", "title": lesson.topic or f"Урок {lesson.lesson_id}",
                          "topic_id": topic_id, "content": content, "material_version": updated_at,
                          "source_lesson_id": lesson.lesson_id, "source_module_id": lesson.course_module_id})

    assignment_ids_by_lesson: dict[int, list[dict[str, Any]]] = {}
    lesson_ids = list(lesson_by_id)
    if lesson_ids:
        lesson_tasks = (db.session.query(LessonTask.lesson_id, LessonTask.task_id, LessonTask.assignment_type)
                        .filter(LessonTask.lesson_id.in_(lesson_ids)).all())
        synthetic_task_ids = {task_id for _, task_id, _ in lesson_tasks}
        tasks = {task.task_id: task for task in db.session.query(
            Tasks.task_id, Tasks.bank_category, Tasks.content_html, Tasks.knowledge_node_id, Tasks.difficulty_level
        ).filter(Tasks.task_id.in_(synthetic_task_ids), Tasks.bank_category == "ai_lab_synthetic").all()} if synthetic_task_ids else {}
        for lesson_id, task_id, assignment_type in lesson_tasks:
            task = tasks.get(task_id)
            if task is None:
                continue
            lesson = lesson_by_id.get(lesson_id)
            topic_id = topic_for_module.get(lesson.course_module_id) if lesson else None
            assignment_ids_by_lesson.setdefault(lesson_id, []).append({
                "assignment_id": f"boostudy-task:{task.task_id}",
                "title": f"Синтетическое задание {task.task_id}",
                "topic_id": topic_id,
                "skill_id": f"exam-skill:{task.knowledge_node_id}" if task.knowledge_node_id else None,
                "assignment_type": assignment_type,
                "difficulty": task.difficulty_level,
                "description": _plain_task_text(task.content_html),
            })
    assignments = [assignment for lesson_id, values in assignment_ids_by_lesson.items() for assignment in values]
    for item in learning_items:
        if item.item_type not in {"assignment", "practice", "homework", "assessment"}:
            continue
        assignments.append({"assignment_id": f"learning-item:{item.item_id}", "title": item.title,
                            "topic_id": topic_for_module.get(item.module_id),
                            "skill_id": f"exam-skill:{item.skill_id}" if item.skill_id else None,
                            "difficulty": None, "description": item.why_now or ""})

    snapshot = {
        "course_id": f"synthetic-boostudy-course-{course.course_id}",
        "course_version": int(course.current_version or 1),
        "title": course.title,
        "topics": topics,
        "learning_goals": goals,
        "materials": materials,
        "assignments": assignments,
        "source_identity": {"source_table": "Courses/LearningTrajectory", "source_course_id": course.course_id,
                            "source_version": int(course.current_version or 1)},
    }
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    snapshot["source_identity"]["content_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return snapshot


def apply_synthetic_lesson_material(course_id: int, lesson_id: int, expected_material: str,
                                    proposed_content: str) -> dict[str, Any] | None:
    """Apply an explicitly reviewed text change to one allowlisted synthetic lesson."""
    if not _adapter_enabled() or course_id not in _allowed_course_ids():
        return None
    course = LearningTrajectory.query.filter_by(
        course_id=course_id, is_template=True, student_id=None,
    ).with_for_update().first()
    lesson = Lesson.query.filter_by(
        lesson_id=lesson_id, learning_trajectory_id=course_id, student_id=None,
    ).with_for_update().first()
    if course is None or lesson is None:
        return None
    if _block_text(lesson.content_blocks):
        raise ValueError("Материал содержит блоки конструктора; автоматическое применение к нему недоступно.")
    current_material = "\n\n".join([
        lesson.topic.strip() if lesson.topic else "",
        lesson.content.strip() if lesson.content else "",
    ]).strip()
    if current_material != expected_material:
        raise ValueError("Материал изменился после анализа. Запустите новый анализ курса.")
    content = str(proposed_content or "").strip()
    if not content or len(content.encode("utf-8")) > 32_768:
        raise ValueError("Предлагаемый материал пуст или превышает 32 КБ.")
    if re.search(r"</?[a-z][^>]*>|<!--|<!doctype", content, re.IGNORECASE):
        raise ValueError("HTML-разметка в AI-предложении запрещена; сохраните материал в безопасном Markdown.")
    old_content = lesson.content or ""
    old_version = int(course.current_version or 1)
    lesson.content = content
    course.current_version = old_version + 1
    db.session.flush()
    return {
        "course_id": course_id,
        "lesson_id": lesson_id,
        "old_content": old_content,
        "new_content": content,
        "old_content_sha256": hashlib.sha256(old_content.encode("utf-8")).hexdigest(),
        "new_content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "old_course_version": old_version,
        "new_course_version": old_version + 1,
    }


def rollback_synthetic_lesson_material(change: dict[str, Any]) -> int | None:
    """Restore a reviewed change only if the lesson still contains that exact version."""
    try:
        course_id, lesson_id = int(change["course_id"]), int(change["lesson_id"])
    except (KeyError, TypeError, ValueError):
        return None
    if not _adapter_enabled() or course_id not in _allowed_course_ids():
        return None
    course = LearningTrajectory.query.filter_by(
        course_id=course_id, is_template=True, student_id=None,
    ).with_for_update().first()
    lesson = Lesson.query.filter_by(
        lesson_id=lesson_id, learning_trajectory_id=course_id, student_id=None,
    ).with_for_update().first()
    if course is None or lesson is None:
        return None
    current_hash = hashlib.sha256((lesson.content or "").encode("utf-8")).hexdigest()
    if current_hash != change.get("new_content_sha256"):
        raise ValueError("Материал изменился после принятия; безопасный откат остановлен.")
    lesson.content = str(change.get("old_content") or "")
    course.current_version = int(course.current_version or 1) + 1
    db.session.flush()
    return int(course.current_version)
