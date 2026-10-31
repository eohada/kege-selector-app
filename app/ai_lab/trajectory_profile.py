"""Teacher-facing, read-only view of an assigned synthetic learning trajectory."""

from __future__ import annotations

from typing import Any


CONFIRMED_STATUSES = {"technical_confirmed", "expert_confirmed"}
CONFIRMED_CRITERION_STATUSES = {"met", "not_met"}
VERSION_COMPATIBLE_STATUSES = {"same_version_exact_binding", "compatible"}


def _int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _item_evidence(event: dict[str, Any], *, course_id: int, course_version: int,
                   lesson_id: int, skill_id: str) -> bool:
    if (event.get("curriculum_eligibility") != "eligible"
            or event.get("evidence_status") not in CONFIRMED_STATUSES):
        return False
    review = event.get("attempt_admissibility")
    if isinstance(review, dict) and review.get("pedagogically_eligible") is False:
        return False
    context = event.get("course_context")
    if not isinstance(context, dict):
        return False
    if (_int(context.get("course_id")) != course_id
            or _int(context.get("lesson_id")) != lesson_id):
        return False
    source_version = _int(context.get("course_version"))
    compatibility = event.get("version_compatibility") or context.get("semantic_compatibility") or {}
    if source_version == course_version:
        if compatibility.get("status") not in VERSION_COMPATIBLE_STATUSES:
            return False
    elif compatibility.get("status") != "compatible":
        return False
    if skill_id not in (event.get("course_skill_ids") or []):
        return False
    return any(
        isinstance(criterion, dict)
        and criterion.get("skill_id") == skill_id
        and criterion.get("status") in CONFIRMED_CRITERION_STATUSES
        and criterion.get("evidence_status") in CONFIRMED_STATUSES
        for criterion in (event.get("criteria") or [])
    )


def build_teacher_trajectory_profile(case: dict[str, Any] | None, *, limit: int = 5) -> dict[str, Any]:
    """Summarize the active copy, next curriculum items and admissible evidence.

    Lesson selection is supplied by Tutor Core's existing course-sequence service.
    The returned window is curriculum context only; it does not represent calendar
    dates, schedule state, mastery, or an applied course change.
    """
    case = case if isinstance(case, dict) else {}
    from app.ai_lab.tutor_core31 import ASSISTANCE_LABELS, SOURCE_LABELS

    course_id = _int(case.get("course_copy_id") or case.get("course_id"))
    course_version = _int(case.get("course_version"))
    next_lesson = case.get("next_lesson") if isinstance(case.get("next_lesson"), dict) else {}
    start_lesson_id = _int(next_lesson.get("lesson_id"))
    raw_plan = case.get("current_plan")
    if not course_id or not course_version or not isinstance(raw_plan, list):
        return {
            "status": "unavailable",
            "reason": "Нет однозначно выбранной индивидуальной копии и снимка её учебного плана.",
            "trajectory_items": [],
            "evidence": [],
        }
    if not start_lesson_id:
        return {
            "status": "unavailable",
            "reason": "В индивидуальной программе сейчас нет следующего урока, выбранного штатной последовательностью.",
            "trajectory_items": [],
            "evidence": [],
        }

    plan = [item for item in raw_plan if isinstance(item, dict) and _int(item.get("lesson_id"))]
    plan.sort(key=lambda item: (_int(item.get("order")) or 0, _int(item.get("lesson_id")) or 0))
    start_index = next((index for index, item in enumerate(plan)
                        if _int(item.get("lesson_id")) == start_lesson_id), None)
    if start_index is None:
        return {
            "status": "unavailable",
            "reason": "Выбранный штатной последовательностью урок отсутствует в текущем снимке плана.",
            "trajectory_items": [],
            "evidence": [],
        }

    try:
        max_items = min(5, max(1, int(limit)))
    except (TypeError, ValueError):
        max_items = 5
    history_by_course_skill: dict[str, list[dict[str, Any]]] = {}
    for row in case.get("stable_skill_history") or []:
        if not isinstance(row, dict):
            continue
        for skill_id in row.get("course_skill_ids") or []:
            history_by_course_skill.setdefault(str(skill_id), []).append(row)

    evidence_rows = [row for row in (case.get("evidence") or []) if isinstance(row, dict)]
    items = []
    for position, lesson in enumerate(plan[start_index:start_index + max_items]):
        lesson_id = _int(lesson.get("lesson_id"))
        sequence_state = lesson.get("sequence_state") if isinstance(lesson.get("sequence_state"), dict) else {}
        skills = []
        skill_ids = lesson.get("skill_ids") if isinstance(lesson.get("skill_ids"), list) else []
        titles = lesson.get("skill_titles") if isinstance(lesson.get("skill_titles"), list) else []
        for skill_index, raw_skill_id in enumerate(skill_ids):
            skill_id = str(raw_skill_id or "")
            histories = history_by_course_skill.get(skill_id, [])
            observation_count = sum(_int(item.get("confirmed_item_observations")) or 0 for item in histories)
            met_count = sum(_int(item.get("met")) or 0 for item in histories)
            not_met_count = sum(_int(item.get("not_met")) or 0 for item in histories)
            directly_bound_ids = {
                str(event.get("event_id")) for event in evidence_rows
                if lesson_id and _item_evidence(
                    event, course_id=course_id, course_version=course_version,
                    lesson_id=lesson_id, skill_id=skill_id,
                )
            }
            skills.append({
                "skill_id": skill_id,
                "title": str(titles[skill_index] if skill_index < len(titles) else "").strip()
                         or "Навык без названия",
                "history_observations": observation_count,
                "history_met": met_count,
                "history_not_met": not_met_count,
                "direct_lesson_evidence_count": len(directly_bound_ids),
                "interpretation": (
                    "Результаты относятся к этому уроку и критерию по точной связи, но не доказывают освоение навыка."
                    if directly_bound_ids else
                    "Есть история по тому же ID навыка; отдельное подтверждение для этого урока отсутствует."
                    if observation_count else
                    "Нет допустимых подтверждённых наблюдений по этому навыку. Это неизвестность, а не установленный пробел."
                ),
            })
        items.append({
            "lesson_id": lesson_id,
            "order": _int(lesson.get("order")),
            "title": str(lesson.get("title") or lesson.get("topic") or f"Урок {lesson_id}"),
            "duration_minutes": _int(lesson.get("duration_minutes")) or 60,
            "is_selected_start": position == 0,
            "sequence_state_label": (
                "Отложено преподавателем" if sequence_state.get("state") == "deferred"
                else ""
            ),
            "sequence_reason": str(sequence_state.get("reason") or ""),
            "skills": skills,
        })

    event_views = []
    evidence_status_labels = {
        "technical_confirmed": "Технически подтверждено",
        "expert_confirmed": "Подтверждено экспертом",
        "insufficient_data": "Недостаточно данных для подтверждения",
        "conflicted": "Есть конфликт доказательств",
    }
    method_labels = {
        "exact_match": "Сравнение с эталонным ответом",
        "code_judge": "Изолированная проверка Code Judge",
        "manual_review": "Ручная проверка преподавателем",
        "teacher_review": "Решение преподавателя",
    }
    lesson_scope_labels = {
        "criterion_observation_for_this_item_only": "Проверенный критерий конкретного урока",
        "another_lesson_same_version": "Другой урок той же версии курса",
        "older_course_version_semantically_compatible": "Предыдущая версия: семантическая совместимость подтверждена",
        "older_course_version_skill_history_only": "Предыдущая версия: только история навыка",
        "stable_skill_history_without_lesson_binding": "История навыка без привязки к уроку",
        "not_usable_for_skill_or_current_lesson_state": "Не используется для вывода по навыку или уроку",
    }
    for event in evidence_rows[-8:]:
        review = event.get("attempt_admissibility") if isinstance(event.get("attempt_admissibility"), dict) else {}
        course_eligible = event.get("curriculum_eligibility") == "eligible"
        explicitly_excluded = review.get("pedagogically_eligible") is False or not course_eligible
        exclusion_reason = (
            review.get("reason") or review.get("label")
            if review.get("pedagogically_eligible") is False
            else event.get("curriculum_mapping_reason") or event.get("curriculum_exclusion_reason")
            if not course_eligible else None
        )
        if explicitly_excluded and not exclusion_reason:
            exclusion_reason = "Причина исключения не указана в сохранённой записи."
        evidence_status = str(event.get("evidence_status") or "unknown")
        if explicitly_excluded:
            eligibility_label = "Исключено из педагогических выводов"
        elif evidence_status not in CONFIRMED_STATUSES:
            eligibility_label = "Сохранено, но не подтверждено как проверенный результат"
        else:
            eligibility_label = "Проверенный результат в истории; применимость к уроку проверяется отдельно"
        method = str(event.get("method") or "").strip()
        raw_scope = str(event.get("lesson_evidence_scope") or "not_established")
        assistance_level = str(event.get("assistance_level") or "")
        event_views.append({
            "event_id": str(event.get("event_id") or ""),
            "source": SOURCE_LABELS.get(str(event.get("source_module") or ""), "Источник не указан"),
            "occurred_at": str(event.get("occurred_at") or ""),
            "evidence_status": evidence_status,
            "evidence_status_label": evidence_status_labels.get(evidence_status, "Статус проверки не установлен"),
            "score": event.get("score"),
            "maximum": event.get("maximum"),
            "method": method_labels.get(method, method.replace("_", " ").capitalize() if method else "Способ проверки не указан"),
            "assistance_label": ASSISTANCE_LABELS.get(assistance_level, "Характер помощи не записан"),
            "eligibility_label": eligibility_label,
            "exclusion_reason": str(exclusion_reason or ""),
            "lesson_scope": lesson_scope_labels.get(raw_scope, "Применимость к уроку не установлена"),
            "reason": str(event.get("reason") or "Основание результата не сохранено."),
        })

    return {
        "status": "available",
        "course_id": course_id,
        "course_title": str(case.get("course_title") or "Индивидуальная копия курса"),
        "course_version": course_version,
        "start_lesson_id": start_lesson_id,
        "trajectory_items": items,
        "evidence": list(reversed(event_views)),
        "scope_note": (
            "Элементы показаны в порядке учебного плана, начиная с урока, выбранного штатной логикой последовательности курса. "
            "Это не расписание и не изменение текущего занятия. История по навыку не равна освоению; "
            "точная связь с уроком учитывает версию, критерий и проверяющий результат."
        ),
        "proposal_scope_note": (
            "Это обзор ближайших элементов для преподавателя. Существующее предложение Tutor Core и его решение "
            "относятся только к явно указанному целевому уроку; остальные элементы здесь не меняются."
        ),
    }
