"""Teacher-facing comparison of assigned synthetic course trajectories."""

from __future__ import annotations

import html
import json
import re
from typing import Any


def _plain_text(value: Any, *, limit: int = 160) -> str:
    text = html.unescape(re.sub(r"<[^>]*>", " ", str(value or "")))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit].rstrip()


def _pedagogy_signature(lesson: Any) -> tuple:
    raw = getattr(lesson, "studio_scenario", None)
    try:
        payload = json.loads(raw or "{}") if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    objective = payload.get("objective") if isinstance(payload.get("objective"), dict) else {}
    criteria = payload.get("criteria") if isinstance(payload.get("criteria"), list) else []
    prerequisites = payload.get("prerequisites") if isinstance(payload.get("prerequisites"), list) else []
    exercises = payload.get("exercises") if isinstance(payload.get("exercises"), list) else []
    return (
        str(objective.get("text") or "").strip(),
        tuple(sorted((str(item.get("label") or "").strip(),
                      str(item.get("observable_outcome") or item.get("evidence") or "").strip(),
                      str(item.get("assessment_method") or "").strip())
                     for item in criteria if isinstance(item, dict))),
        tuple(sorted((str(item.get("label") or "").strip(),
                      str(item.get("status") or "").strip())
                     for item in prerequisites if isinstance(item, dict))),
        tuple(sorted((str(item.get("title") or "").strip(),
                      str(item.get("role") or "").strip(),
                      tuple(sorted(str(value) for value in (item.get("criterion_ids") or [])),))
                     for item in exercises if isinstance(item, dict))),
    )


def _lesson_signature(lesson: Any) -> dict[str, Any]:
    tasks = []
    for item in getattr(lesson, "homework_tasks", None) or []:
        task = getattr(item, "task", None)
        if not task:
            continue
        tasks.append((str(item.assignment_type or "homework"), _plain_text(task.content_html, limit=120)))
    return {
        "topic": str(getattr(lesson, "topic", None) or "").strip(),
        "content": _plain_text(getattr(lesson, "content", None), limit=600),
        "duration": int(getattr(lesson, "duration", None) or 60),
        "skills": tuple(sorted(f"exam-skill:{int(skill.skill_id)}" for skill in (lesson.skills or [])
                                if getattr(skill, "is_active", True))),
        "pedagogy": _pedagogy_signature(lesson),
        "exercises": tuple(sorted(tasks)),
    }


def compare_lesson_plans(base_plan: list[dict[str, Any]], copy_plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compare semantic lesson fields without treating IDs or version labels as content."""
    base_by_order = {int(row["order"]): row for row in base_plan if row.get("order") is not None}
    copy_by_order = {int(row["order"]): row for row in copy_plan if row.get("order") is not None}
    labels = {
        "topic": "Тема занятия",
        "content": "Учебное содержание",
        "duration": "Продолжительность",
        "skills": "Связанные навыки",
        "pedagogy": "Цель, критерии и этапы",
        "exercises": "Набор упражнений",
    }
    changes = []
    for order in sorted(set(base_by_order) | set(copy_by_order)):
        original = base_by_order.get(order)
        current = copy_by_order.get(order)
        if original is None or current is None:
            changes.append({
                "order": order,
                "title": str((current or original).get("topic") or (current or original).get("title") or f"Занятие {order}"),
                "fields": ["Занятие добавлено в индивидуальную программу" if original is None
                           else "Занятие отсутствует в индивидуальной программе"],
            })
            continue
        changed_fields = [labels[key] for key in labels
                          if original.get(key) != current.get(key)]
        if changed_fields:
            changes.append({
                "order": order,
                "title": str(current.get("topic") or original.get("topic") or f"Занятие {order}"),
                "fields": changed_fields,
            })
    return changes


def _course_semantics(course: Any) -> list[dict[str, Any]]:
    from core.db_models import Lesson

    lessons = Lesson.query.filter_by(learning_trajectory_id=int(course.course_id))\
        .order_by(Lesson.course_order_index.asc(), Lesson.lesson_id.asc()).all()
    return [{"order": int(item.course_order_index or 0), **_lesson_signature(item)} for item in lessons]


def _used_exercises(case: dict[str, Any]) -> list[str]:
    from core.db_models import LessonTaskAttempt, Tasks, db

    task_ids: set[int] = set()
    attempt_ids: dict[int, set[str]] = {}
    direct_event_tasks: dict[int, set[str]] = {}
    identified_events: set[str] = set()
    event_ids = {
        str(item.get("event_id"))
        for item in (case.get("evidence") or [])
        if isinstance(item, dict) and item.get("event_id")
    }
    for event in case.get("evidence") or []:
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("event_id") or "")
        match = re.search(r":task:(\d+)$", event_id)
        if match:
            task_id = int(match.group(1))
            task_ids.add(task_id)
            direct_event_tasks.setdefault(task_id, set()).add(event_id)
        match = re.fullmatch(r"lesson-classwork-attempt:(\d+)", event_id)
        if match:
            attempt_ids.setdefault(int(match.group(1)), set()).add(event_id)
    if attempt_ids:
        attempts = LessonTaskAttempt.query.filter(
            LessonTaskAttempt.attempt_id.in_(attempt_ids)
        ).all()
        for attempt in attempts:
            if attempt.lesson_task and attempt.lesson_task.task_id:
                task_id = int(attempt.lesson_task.task_id)
                task_ids.add(task_id)
                identified_events.update(attempt_ids.get(int(attempt.attempt_id), set()))
    tasks = Tasks.query.filter(Tasks.task_id.in_(task_ids)).all() if task_ids else []
    task_labels = {
        int(task.task_id): _plain_text(task.content_html, limit=115) or "Условие без текстовой подписи"
        for task in tasks
    }
    identified_events.update(
        event_id
        for task_id, event_ids_for_task in direct_event_tasks.items()
        if task_id in task_labels
        for event_id in event_ids_for_task
    )
    labels = sorted(set(task_labels.values()))
    # Count source events, not task IDs: repeated attempts remain distinct evidence,
    # while several events for one exercise do not inflate the number of unknowns.
    unlabelled = len(event_ids - identified_events)
    if unlabelled:
        labels.append(f"Ещё {unlabelled} наблюдений без сохранённой привязки к названию задания")
    return labels


def build_teacher_cohort_comparison(cases: list[dict[str, Any]], *, selected_profile_id: str,
                                    actor_user_id: int) -> dict[str, Any]:
    """Compare only active, already-resolved copies visible to the current teacher."""
    from app.ai_lab.course_adapter import resolve_assigned_synthetic_copy
    from app.ai_lab.trajectory_profile import build_teacher_trajectory_profile
    from app.ai_lab.tutor_core import tutor_history
    from core.db_models import LearningTrajectory, LearningTrajectoryVersion, Lesson, Student, User, db

    case_by_profile = {str(case.get("profile_id")): case for case in cases if isinstance(case, dict)}
    selected = case_by_profile.get(str(selected_profile_id))
    if not selected:
        return {"status": "unavailable", "reason": "У текущего преподавателя нет доступа к этому synthetic-профилю.", "learners": []}
    selected_course_id = int(selected.get("course_copy_id") or 0)
    course = db.session.get(LearningTrajectory, selected_course_id) if selected_course_id else None
    if (not course or course.is_template or not course.parent_course_id
            or int(course.student_id or 0) != int(selected.get("student_id") or 0)):
        return {"status": "unavailable", "reason": "Связь ученика с индивидуальной копией не подтверждена.", "learners": []}
    resolved = resolve_assigned_synthetic_copy(int(course.student_id))
    if resolved.get("status") != "resolved" or int((resolved.get("copy") or {}).course_id or 0) != selected_course_id:
        return {"status": "unavailable", "reason": "Действующая индивидуальная копия неоднозначна или не разрешена.", "learners": []}
    base = db.session.get(LearningTrajectory, int(course.parent_course_id))
    if not base or not base.is_template:
        return {"status": "unavailable", "reason": "Базовая программа для этой копии не подтверждена.", "learners": []}
    base_plan = _course_semantics(base)

    learners = []
    for case in cases:
        course_id = int(case.get("course_copy_id") or 0)
        copy = db.session.get(LearningTrajectory, course_id) if course_id else None
        if (not copy or copy.is_template or int(copy.parent_course_id or 0) != int(base.course_id)
                or int(copy.student_id or 0) != int(case.get("student_id") or 0)):
            continue
        actual_resolution = resolve_assigned_synthetic_copy(int(copy.student_id))
        if actual_resolution.get("status") != "resolved" or int((actual_resolution.get("copy") or {}).course_id or 0) != course_id:
            continue
        try:
            user_id = int(str(case.get("profile_id") or "").rsplit(":", 1)[-1])
        except (TypeError, ValueError):
            continue
        user = db.session.get(User, user_id)
        if not user:
            continue
        student = db.session.get(Student, int(case.get("student_id") or copy.student_id or 0))
        if not student or int(student.user_id or 0) != int(user.id):
            continue
        event_rows = [item for item in (case.get("evidence") or []) if isinstance(item, dict)]
        confirmed = [item for item in event_rows if item.get("evidence_status") in {"technical_confirmed", "expert_confirmed"}]
        conflicted = [item for item in event_rows if item.get("evidence_status") == "conflicted"]
        eligible = [item for item in event_rows if item.get("curriculum_eligibility") == "eligible"]
        current_plan = _course_semantics(copy)
        changes = compare_lesson_plans(base_plan, current_plan)
        future_lesson = (Lesson.query.filter(
            Lesson.learning_trajectory_id == course_id,
            Lesson.status.in_(("draft", "planned", "scheduled")),
        ).order_by(Lesson.course_order_index.asc(), Lesson.lesson_id.asc()).first())
        last_order = max((int(row.get("order") or 0) for row in current_plan), default=0)
        trajectory = build_teacher_trajectory_profile(case, limit=5)
        history = tutor_history(int(actor_user_id), str(case.get("profile_id") or ""))[-3:]
        history_rows = [{
            "decision": str(item.get("decision") or "Ожидает решения"),
            "created_at": str(item.get("created_at") or ""),
            "title": str(((item.get("proposal") or {}).get("proposal") or {}).get("title") or "Предложение Tutor Core"),
            "rollback": bool(item.get("rollback_at")),
        } for item in history]
        version_rows = (LearningTrajectoryVersion.query.filter_by(course_id=course_id)
                        .order_by(LearningTrajectoryVersion.version_number.desc()).limit(5).all())
        version_history = [{
            "version": int(item.version_number),
            "reason": str(item.reason or "Изменение курса"),
            "created_at": str(item.created_at or ""),
        } for item in version_rows]
        manual_plan_history = []
        for history_lesson in Lesson.query.filter_by(learning_trajectory_id=course_id).all():
            summaries = history_lesson.review_summaries if isinstance(history_lesson.review_summaries, dict) else {}
            entries = summaries.get("_teacher_manual_plan_changes") or []
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                manual_plan_history.append({
                    "lesson_order": int(history_lesson.course_order_index or 0),
                    "lesson_title": str(history_lesson.topic or "Занятие"),
                    "reason": str(entry.get("reason") or "Основание не сохранено"),
                    "source_version": entry.get("source_course_version"),
                    "effective_version": entry.get("effective_course_version"),
                    "created_at": str(entry.get("created_at") or ""),
                })
        manual_plan_history.sort(key=lambda item: item["created_at"], reverse=True)
        skill_rows = []
        if trajectory.get("status") == "available":
            for lesson_row in trajectory.get("trajectory_items") or []:
                if not lesson_row.get("is_selected_start"):
                    continue
                skill_rows = [{
                    "title": item.get("title") or "Навык без названия",
                    "state": ("Есть наблюдение по критерию этого урока" if item.get("direct_lesson_evidence_count")
                              else "История навыка есть, но доказательства для этого урока нет"
                              if item.get("history_observations")
                              else "Пока неизвестно — допустимых наблюдений нет"),
                    "observations": int(item.get("history_observations") or 0),
                } for item in lesson_row.get("skills") or []]
        learners.append({
            "profile_id": str(case.get("profile_id") or ""),
            "user_id": int(user.id),
            "display_name": str(student.name or user.username),
            "course_id": course_id,
            "course_title": str(copy.title or "Индивидуальная программа"),
            "course_version": int(copy.current_version or 1),
            "editable_lesson_id": int(future_lesson.lesson_id) if future_lesson else None,
            "next_course_order": last_order + 10,
            "has_future_lesson": bool(future_lesson),
            "is_selected": str(case.get("profile_id")) == str(selected_profile_id),
            "lesson_changes": changes[:8],
            "changed_lesson_count": len(changes),
            "evidence_count": len(event_rows),
            "confirmed_count": len(confirmed),
            "conflicted_count": len(conflicted),
            "eligible_count": len(eligible),
            "unknown_count": sum(1 for item in event_rows if item.get("evidence_status") in {None, "unknown", "insufficient_data"}),
            "skill_states": skill_rows,
            "used_exercises": _used_exercises(case),
            "next_lessons": trajectory.get("trajectory_items") or [],
            "trajectory_status": trajectory.get("status"),
            "trajectory_reason": str(trajectory.get("reason") or ""),
            "recommendation": str((case.get("proposal") or {}).get("text") or "План сохранить; оснований для изменения не установлено."),
            "recommendation_action": str((case.get("proposal") or {}).get("action") or "maintain_plan"),
            "decision_history": history_rows,
            "version_history": version_history,
            "manual_plan_history": manual_plan_history[:5],
            "uncertainty": str((case.get("proposal") or {}).get("uncertainty") or
                               "Технические результаты описывают конкретные проверки; самостоятельность и освоение требуют отдельных данных."),
        })
    learners.sort(key=lambda item: (not item["is_selected"], item["display_name"].casefold()))
    return {
        "status": "available",
        "base_title": str(base.title or "Базовая программа"),
        "base_course_id": int(base.course_id),
        "base_version": int(base.current_version or 1),
        "learners": learners,
        "note": "Показываются только назначенные synthetic-копии, доступные текущему преподавателю. История событий, следующая последовательность и календарное расписание — разные данные.",
    }
