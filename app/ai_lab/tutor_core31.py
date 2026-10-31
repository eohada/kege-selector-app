"""Versioned, subject-agnostic interpretation of saved synthetic learning evidence."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.ai_lab.learning_evidence import (
    EVIDENCE_CONTRACT_VERSION,
    EvidenceContractError,
    merge_evidence_events,
)
from core.db_models import ExamSkill, Student, User


TUTOR_CORE31_VERSION = "boostudy.tutor-core.v3.1"
CONFIRMED = {"technical_confirmed", "expert_confirmed"}
SOURCE_LABELS = {
    "ai_homework": "Домашняя работа BooStudy",
    "ai_lesson_intelligence": "Наблюдение AI Lesson, подтверждённое преподавателем",
    "ai_classwork": "Работа в Lesson Room",
    "ai_practice": "Свободная практика BooStudy",
}
ASSISTANCE_LABELS = {
    "independent": "Самостоятельно",
    "neutral_organizational": "Организационная помощь",
    "general_rule_reminder": "Напоминание общего правила",
    "leading_question": "Наводящий вопрос",
    "substantive_hint": "Содержательная подсказка",
    "partial_solution": "Часть решения показана",
    "full_solution": "Решение объяснено полностью",
    "no_platform_hint": "Подсказка BooStudy не запрашивалась; внешняя помощь неизвестна",
}


def _task_key(event: dict[str, Any]) -> str | None:
    refs = event.get("platform_refs") or {}
    task_id = refs.get("task_id")
    if task_id:
        return f"task:{task_id}"
    assignment_task_id = refs.get("assignment_task_id")
    return f"assignment-task:{assignment_task_id}" if assignment_task_id else None


def _skill_results(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_skill: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if event["evidence_status"] not in CONFIRMED:
            continue
        skill_ids = event.get("skill_ids") or []
        for criterion in event.get("criteria") or []:
            skill_id = criterion.get("skill_id")
            if not skill_id and len(skill_ids) == 1:
                skill_id = skill_ids[0]
            if (not skill_id or criterion.get("status") not in {"met", "not_met"}
                    or criterion.get("evidence_status") not in CONFIRMED):
                continue
            by_skill[skill_id].append(_result_record(event, skill_id, criterion["status"], criterion.get("reason")))

        # An overall full score is evidence only when the event maps to one skill.
        # A partial total cannot identify which of several skills was missed.
        outcome = event.get("outcome") or {}
        if (not event.get("criteria") and len(skill_ids) == 1
                and outcome.get("status") == "complete"
                and outcome.get("score") is not None
                and outcome.get("maximum") is not None
                and outcome["score"] == outcome["maximum"]):
            by_skill[skill_ids[0]].append(_result_record(event, skill_ids[0], "met", "Полный результат подтверждён источником."))

    for skill_id, rows in by_skill.items():
        unique: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            unique[(row["event_id"], row["result"])] = row
        by_skill[skill_id] = sorted(unique.values(), key=lambda row: (row["occurred_at"], row["event_id"]))
    return by_skill


def _result_record(event: dict[str, Any], skill_id: str, result: str, reason: str) -> dict[str, Any]:
    assistance = event.get("assistance")
    help_level = assistance.get("level") if isinstance(assistance, dict) else None
    fixture = (event.get("provenance") or {}).get("synthetic_fixture_binding")
    assistance_source_kind = (
        "platform_hint_log" if event.get("source_module") == "ai_practice" and isinstance(assistance, dict)
        else "synthetic_fixture_label" if fixture and isinstance(assistance, dict)
        else "unrecorded"
    )
    return {
        "event_id": event["event_id"],
        "source_record_id": event["source_record_id"],
        "occurred_at": event["occurred_at"],
        "skill_id": skill_id,
        "result": result,
        "task_key": _task_key(event),
        "assistance_level": help_level,
        "assistance_source_kind": assistance_source_kind,
        "source_module": event["source_module"],
        "method": (event.get("provenance") or {}).get("method") or "Метод источника не указан.",
        "reason": reason or "Основание критерия не указано источником.",
    }


def _skill_state(skill_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    confirmed_successes = [row for row in rows if row["result"] == "met"]
    confirmed_errors = [row for row in rows if row["result"] == "not_met"]
    independent_successes = [row for row in confirmed_successes if row["assistance_level"] == "independent"]
    independent_task_keys = {row["task_key"] for row in independent_successes if row["task_key"]}
    latest = rows[-1]

    if latest["result"] == "not_met":
        state = "contradictory_recent_error" if confirmed_successes else (
            "repeated_difficulty" if len({row["task_key"] for row in confirmed_errors if row["task_key"]}) >= 2 else "single_difficulty"
        )
    elif len(independent_task_keys) >= 2:
        state = "repeated_independent_success"
    elif confirmed_errors:
        state = "mixed_history_progress"
    elif latest["assistance_level"] == "independent":
        state = "single_independent_success"
    elif latest["assistance_level"] == "no_platform_hint":
        state = "success_help_unobserved"
    elif latest["assistance_level"]:
        state = "success_after_help"
    else:
        state = "success_help_unrecorded"

    state_label = {
        "contradictory_recent_error": "Новый результат расходится с прежними успехами",
        "repeated_difficulty": "Затруднение повторилось на разных заданиях",
        "single_difficulty": "Зафиксирована одна ошибка",
        "repeated_independent_success": "Повторный самостоятельный успех на разных заданиях",
        "mixed_history_progress": "История содержит ошибки и более поздние успехи",
        "single_independent_success": "Один самостоятельный успех",
        "success_after_help": "Успех после помощи",
        "success_help_unrecorded": "Результат подтверждён, характер помощи не записан",
        "success_help_unobserved": "Ответ верный; подсказка BooStudy не запрашивалась, внешняя помощь неизвестна",
    }[state]
    if latest["assistance_source_kind"] == "synthetic_fixture_label":
        state_label += " · по метке сценария, не по журналу платформы"

    display_title = None
    if skill_id.startswith("exam-skill:") and skill_id.partition(":")[2].isdigit():
        exam_skill = ExamSkill.query.filter_by(skill_id=int(skill_id.partition(":")[2])).first()
        display_title = str(getattr(exam_skill, "title", "") or "").strip() or None
    elif skill_id.startswith("ege."):
        matches = ExamSkill.query.filter_by(topic_code=skill_id, is_active=True).all()
        if len(matches) == 1:
            display_title = str(matches[0].title or "").strip() or None
    if not display_title:
        from app.ai_lab.practice import practice_skill_title
        display_title = practice_skill_title(skill_id)

    return {
        "skill_id": skill_id,
        "display_title": display_title or "Навык без названия в каталоге",
        "state": state,
        "state_label": state_label,
        "confirmed_event_count": len(rows),
        "success_count": len(confirmed_successes),
        "error_count": len(confirmed_errors),
        "independent_success_count": len(independent_successes),
        "distinct_independent_tasks": len(independent_task_keys),
        "latest_result": latest["result"],
        "latest_event_id": latest["event_id"],
        "history": rows,
    }


def evaluate_learning_history(raw_events: list[dict[str, Any]], subject_id: str) -> dict[str, Any]:
    """Describe observed evidence without turning it into a mastery percentage."""
    bundle = merge_evidence_events([raw_events], allowed_subject_ids={subject_id})
    states = [_skill_state(skill_id, rows) for skill_id, rows in sorted(_skill_results(bundle["events"]).items())]
    return {
        "subject_id": subject_id,
        "event_count": bundle["event_count"],
        "duplicate_count": bundle["duplicate_count"],
        "skills": states,
    }


def _decision_for(states: list[dict[str, Any]]) -> dict[str, Any]:
    if not states:
        return {
            "action": "keep_plan_insufficient_evidence",
            "known": ["Нет подтверждённых результатов, связанных с конкретным навыком."],
            "unknown": ["Не установлено, какие навыки ученик может выполнить самостоятельно."],
            "why": "Без проверяемого события оснований менять учебный план нет.",
            "alternatives": ["Сохранить план", "Получить проверяемую попытку с привязкой к навыку"],
            "time_impact": "Не рассчитывался: индивидуальная программа к событиям не привязана.",
            "teacher_review_required": True,
        }

    latest_row = max(
        (row for state in states for row in state["history"]),
        key=lambda row: (row["occurred_at"], row["event_id"]),
    )
    latest_states = [state for state in states if any(
        row["event_id"] == latest_row["event_id"] for row in state["history"]
    )]
    state_codes = {state["state"] for state in latest_states}
    if state_codes & {"contradictory_recent_error", "repeated_difficulty"}:
        action = "teacher_review_and_diagnostic"
        why = "История содержит подтверждённое расхождение или повтор ошибки; единичный результат не стирает прежние свидетельства."
    elif state_codes == {"repeated_independent_success"}:
        action = "keep_plan"
        why = "Есть самостоятельные успехи на разных заданиях; автоматическое изменение программы не требуется."
    elif state_codes & {"success_after_help", "single_independent_success", "mixed_history_progress"}:
        action = "independent_transfer_check"
        why = "Следующий полезный шаг — проверить тот же навык на новом условии без содержательной подсказки; прежние ошибки сохраняются в истории."
    elif "success_help_unrecorded" in state_codes:
        action = "keep_plan_capture_help_context"
        why = "Результат проверки подтверждён, но источник не записал характер помощи; самостоятельность не выводится."
    else:
        action = "keep_plan_collect_more_evidence"
        why = "Данных пока мало для изменения содержания курса; наблюдение сохраняется как ограниченный сигнал."
    independent_tasks = max((state["distinct_independent_tasks"] for state in latest_states), default=0)
    return {
        "action": action,
        "known": [state["state_label"] for state in latest_states]
        + [f"Подтверждённых событий по последнему затронутому навыку: {len(latest_states[0]['history'])}."]
        + ([f"Самостоятельный успех зафиксирован на {independent_tasks} разных заданиях."] if independent_tasks else []),
        "unknown": (["Характер помощи не записан источником."] if any(
            row["assistance_level"] is None
            for state in latest_states for row in state["history"]
        ) else []),
        "why": why,
        "evidence_refs": sorted({row["event_id"] for state in latest_states for row in state["history"]}),
        "alternatives": ["Оставить план без изменений", "Провести короткую независимую диагностику"],
        "time_impact": "Не рассчитывался: для этих событий не найдена связанная версия индивидуального плана.",
        "teacher_review_required": True,
    }


def compare_learning_history(raw_events: list[dict[str, Any]], subject_id: str) -> dict[str, Any]:
    """Recompute the same subject's state before and after its latest saved event."""
    bundle = merge_evidence_events([raw_events], allowed_subject_ids={subject_id})
    events = bundle["events"]
    before = evaluate_learning_history(events[:-1], subject_id) if events else evaluate_learning_history([], subject_id)
    after = evaluate_learning_history(events, subject_id)
    before_by_skill = {item["skill_id"]: item for item in before["skills"]}
    after_by_skill = {item["skill_id"]: item for item in after["skills"]}
    changes = []
    for skill_id in sorted(set(before_by_skill) | set(after_by_skill)):
        old = before_by_skill.get(skill_id)
        new = after_by_skill.get(skill_id)
        changes.append({
            "skill_id": skill_id,
            "before": old["state_label"] if old else "До этого события подтверждений не было",
            "after": new["state_label"] if new else "Недостаточно данных",
            "changed": (old or {}).get("state") != (new or {}).get("state"),
        })
    latest = events[-1] if events else None
    return {
        "before": before,
        "after": after,
        "changes": changes,
        "latest_event": _event_summary(latest) if latest else None,
        "decision": _decision_for(after["skills"]),
    }


def _event_summary(event: dict[str, Any], curriculum_evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    assistance = event.get("assistance")
    level = assistance.get("level") if isinstance(assistance, dict) else None
    refs = event.get("platform_refs") or {}
    fixture = (event.get("provenance") or {}).get("synthetic_fixture_binding") or {}
    assistance_source_kind = (
        "platform_hint_log" if event["source_module"] == "ai_practice" and isinstance(assistance, dict)
        else "synthetic_fixture_label" if fixture and isinstance(assistance, dict)
        else "unrecorded"
    )
    assistance_source_label = (
        "Журнал фиксирует подсказки BooStudy; внешняя помощь не наблюдалась"
        if assistance_source_kind == "platform_hint_log"
        else
        "Метка синтетического сценария; фактическая помощь платформы не проверялась"
        if assistance_source_kind == "synthetic_fixture_label"
        else "Источник помощи не записан"
    )
    outcome = event.get("outcome") or {}
    return {
        "event_id": event["event_id"],
        "source_record_id": event["source_record_id"],
        "source_module": event["source_module"],
        "source_label": SOURCE_LABELS.get(event["source_module"], "Другой подтверждённый источник"),
        "occurred_at": event["occurred_at"],
        "evidence_status": event["evidence_status"],
        "evidence_label": ("Технически подтверждено" if event["evidence_status"] == "technical_confirmed"
                           else "Недостаточно данных" if event["evidence_status"] == "insufficient_data"
                           else "Требует экспертного решения"),
        "outcome": outcome,
        "score": outcome.get("score"),
        "maximum": outcome.get("maximum"),
        "skill_ids": event["skill_ids"],
        "assistance_level": level,
        "assistance_label": ASSISTANCE_LABELS.get(level, "Не записано"),
        "assistance_source_kind": assistance_source_kind,
        "assistance_source_label": assistance_source_label,
        "assistance_source_refs": assistance.get("source_refs", []) if isinstance(assistance, dict) else [],
        "method": (event.get("provenance") or {}).get("method") or "Не указано",
        "evaluation_revision": (
            (event.get("provenance") or {}).get("evaluation_revision")
            or {"status": "legacy_unknown"}
        ) if event.get("source_module") == "ai_homework" else None,
        "curriculum_skill_mappings": (curriculum_evidence or {}).get("curriculum_skill_mappings", []),
        "curriculum_eligibility": (curriculum_evidence or {}).get("curriculum_eligibility"),
        "curriculum_exclusion_reason": (curriculum_evidence or {}).get("curriculum_exclusion_reason"),
        "attempt_admissibility": (curriculum_evidence or {}).get("attempt_admissibility"),
        "attempt_review_supported": bool((curriculum_evidence or {}).get("attempt_review_supported")),
        "curriculum_mapping_reason": (curriculum_evidence or {}).get("curriculum_mapping_reason"),
        "skill_evidence_use": (curriculum_evidence or {}).get("skill_evidence_use"),
        "version_compatibility": (curriculum_evidence or {}).get("version_compatibility"),
        "limitations": event["limitations"],
        "criteria": event.get("criteria") or [],
        "fixture_key": fixture.get("fixture_key"),
        "fixture_mapping_status": fixture.get("knowledge_status"),
        "fixture_course_id": fixture.get("course_id"),
        "fixture_course_version": fixture.get("course_version"),
        "platform_refs": refs,
        "submission_url": f"/submissions/{refs['submission_id']}" if refs.get("submission_id") else None,
        "assignment_id": refs.get("assignment_id"),
        "task_id": refs.get("task_id"),
        "lesson_url": f"/lesson/{refs['lesson_id']}/view" if refs.get("lesson_id") else None,
    }


def _synthetic_subject_id(event: dict[str, Any], user_cache: dict[int, bool]) -> bool:
    subject_id = event.get("subject_id") or ""
    prefix = "platform-student:"
    if not subject_id.startswith(prefix) or not subject_id[len(prefix):].isdigit():
        return False
    user_id = int(subject_id[len(prefix):])
    if user_id not in user_cache:
        user = User.query.filter_by(id=user_id).first()
        student = Student.query.filter_by(user_id=user_id).first() if user else None
        user_cache[user_id] = bool(
            user and student and str(user.username or "").startswith(("demo_", "synthetic_"))
        )
    return user_cache[user_id]


def _knowledge_for_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from app.ai_lab.knowledge_base import list_knowledge_entries

    entries = {item["stable_key"]: item for item in list_knowledge_entries(include_content=False)}
    used: dict[str, dict[str, Any]] = {}
    for event in events:
        provenance = event.get("provenance") or {}
        fixture = provenance.get("synthetic_fixture_binding") or {}
        if fixture:
            key = fixture.get("knowledge_stable_key")
            used[key] = {
                "stable_key": key,
                "title": fixture.get("knowledge_title"),
                "version": fixture.get("knowledge_version"),
                "editorial_status": fixture.get("knowledge_status"),
                "source_titles": fixture.get("knowledge_source_titles") or [],
                "used_as_student_evidence": event.get("evidence_status") in CONFIRMED,
                "mapping_kind": "Связь задания с навыком задана синтетической фикстурой; это не экспертная привязка ЕГЭ.",
            }
            continue
        practice_ref = provenance.get("practice_knowledge_ref") or {}
        practice_key = practice_ref.get("stable_key") if isinstance(practice_ref, dict) else None
        practice_entry = entries.get(practice_key) if practice_key else None
        if practice_entry and event.get("source_module") == "ai_practice":
            used[practice_key] = {
                "stable_key": practice_key,
                "title": practice_entry["title"],
                "version": practice_ref.get("version"),
                "editorial_status": practice_ref.get("status"),
                "source_titles": [item["title"] for item in practice_entry["source_refs"]],
                "used_as_student_evidence": False,
                "mapping_kind": "Ссылка генератора на материал Knowledge Base; не доказывает, что ученик использовал или изучил этот материал.",
            }
        binding = provenance.get("platform_task_binding") or {}
        key = binding.get("knowledge_stable_key")
        entry = entries.get(key) if key else None
        if entry:
            used[key] = {
                "stable_key": key,
                "title": entry["title"],
                "version": entry["version_no"],
                "editorial_status": entry["status"],
                "source_titles": [item["title"] for item in entry["source_refs"]],
                "used_as_student_evidence": False,
                "mapping_kind": "Source-checked связь задания с материалом.",
            }
    return sorted(used.values(), key=lambda item: item["stable_key"])


def _profile_card(subject_id: str, events: list[dict[str, Any]], ordinal: int, actor_user_id: int) -> dict[str, Any]:
    comparison = compare_learning_history(events, subject_id)
    ordered = [item for item in events]
    effect_start = max(0, len(ordered) - 8)
    event_effects = _event_effects(
        ordered[effect_start:], subject_id, preceding_events=ordered[:effect_start]
    )
    unverified_index = next((index for index in range(len(ordered) - 1, -1, -1)
                             if ordered[index]["evidence_status"] not in CONFIRMED), None)
    state_a_index = unverified_index if unverified_index is not None else max(0, len(ordered) - 2)
    state_a = _state_checkpoint(ordered[:state_a_index + 1], subject_id,
                                ordered[state_a_index]["event_id"] if ordered else None)
    state_a["label"] = ("После события с недостаточными данными" if unverified_index is not None
                         else "Перед последним событием" if len(ordered) > 1
                         else "До появления дополнительного подтверждения")
    state_b = _state_checkpoint(ordered, subject_id, ordered[-1]["event_id"] if ordered else None)
    state_b["label"] = "После последнего сохранённого события"
    curriculum = _synthetic_curriculum_context(subject_id, ordered, comparison["decision"], actor_user_id)
    if curriculum.get("status") == "linked":
        comparison["decision"]["time_impact"] = curriculum["time_impact"]
    curriculum_events = {
        str(item.get("event_id")): item
        for item in curriculum.get("event_evidence", [])
        if isinstance(item, dict) and item.get("event_id")
    }
    user_id = int(subject_id.rsplit(":", 1)[-1])
    user = User.query.filter_by(id=user_id).first()
    student = Student.query.filter_by(user_id=user_id).first()
    return {
        "label": (getattr(student, "name", None) or getattr(user, "username", None)
                  or f"Синтетический профиль {ordinal}"),
        "subject_id": subject_id,
        "student_id": int(student.student_id) if student else None,
        "student_url": f"/teacher/students/{student.student_id}" if student else None,
        "state_a": state_a,
        "state_b": state_b,
        "event_count": len(events),
        "comparison": comparison,
        "events": [_event_summary(item, curriculum_events.get(str(item.get("event_id"))))
                   for item in events[-8:]],
        "event_effects": event_effects[-8:],
        "history_truncated": len(events) > 8,
        "knowledge": _knowledge_for_events(events),
        "curriculum": curriculum,
        "curriculum_status": curriculum.get("status", "not_linked"),
    }


def _state_checkpoint(events: list[dict[str, Any]], subject_id: str, event_id: str | None) -> dict[str, Any]:
    result = evaluate_learning_history(events, subject_id)
    return {
        "event_id": event_id,
        "skills": result["skills"],
        "decision": _decision_for(result["skills"]),
    }


def _event_effects(
    events: list[dict[str, Any]],
    subject_id: str,
    *,
    preceding_events: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    effects = []
    history = list(preceding_events or [])
    before_state = _state_checkpoint(history, subject_id, None)
    for event in events:
        history.append(event)
        after_state = _state_checkpoint(history, subject_id, event["event_id"])
        before = before_state["decision"]["action"]
        after = after_state["decision"]["action"]
        before_by_skill = {item["skill_id"]: item for item in before_state["skills"]}
        after_by_skill = {item["skill_id"]: item for item in after_state["skills"]}
        changed_skill_count = sum(
            (before_by_skill.get(skill_id) or {}).get("state")
            != (after_by_skill.get(skill_id) or {}).get("state")
            for skill_id in set(before_by_skill) | set(after_by_skill)
        )
        changed = changed_skill_count > 0
        effects.append({
            "event_id": event["event_id"],
            "evidence_status": event["evidence_status"],
            "decision_before": before,
            "decision_after": after,
            "changed_skill_count": changed_skill_count,
            "changed": changed,
            "effect_label": ("Состояние и предложение не изменились: недостаточно проверенных данных."
                             if event["evidence_status"] not in CONFIRMED and before == after
                             else "Изменение вычислено по сохранённому подтверждённому событию."
                             if changed else "Подтверждённое состояние навыков не изменилось."),
        })
        before_state = after_state
    return effects


def _platform_curriculum_context(subject_id: str, actor_user_id: int) -> dict[str, Any]:
    from app.ai_lab.tutor_core import _platform_profile_cases

    case = next((item for item in _platform_profile_cases(actor_user_id)
                 if item.get("profile_id") == subject_id), None)
    resolution = (case or {}).get("curriculum_resolution") or {}
    if resolution.get("status") == "ambiguous_active_copies":
        return {
            "status": "ambiguous_curriculum",
            "proposal_status": "not_available",
            "candidate_course_ids": list(resolution.get("candidate_ids") or []),
            "proposal_reason": (case or {}).get("proposal", {}).get("text")
                               or "У ученика несколько активных индивидуальных копий. Для адаптации требуется явный выбор курса.",
        }
    if resolution.get("status") == "active_copy_not_allowlisted":
        return {
            "status": "course_not_allowlisted",
            "proposal_status": "not_available",
            "candidate_course_ids": list(resolution.get("candidate_ids") or []),
            "proposal_reason": (case or {}).get("proposal", {}).get("text")
                               or "Активная индивидуальная копия не разрешена в synthetic safe mode.",
        }
    if not case or not case.get("course_copy_id"):
        return {
            "status": "not_linked",
            "proposal_status": "not_available",
            "proposal_reason": (case or {}).get("proposal", {}).get("text")
                               or "Индивидуальная копия курса не найдена в явном синтетическом allowlist.",
        }

    lesson = case.get("next_lesson")
    if not lesson:
        return {
            "status": "no_next_lesson",
            "proposal_status": "not_available",
            "proposal_reason": (case.get("proposal") or {}).get("text")
                               or "В индивидуальной копии нет следующего незавершённого урока.",
        }

    proposal = case.get("proposal") if isinstance(case.get("proposal"), dict) else {}
    allocation = proposal.get("time_allocation") if isinstance(proposal.get("time_allocation"), dict) else {}
    duration = int(lesson.get("duration_minutes") or 60)
    planned_minutes = int(allocation.get("planned_lesson_minutes") or duration)
    adaptation_minutes = int(allocation.get("adaptation_minutes") or 0)
    action = str(proposal.get("action") or "maintain_plan")
    proposed_structure = proposal.get("proposed_structure")
    selected_exercise = proposal.get("selected_exercise")
    time_plan = proposal.get("time_plan") if isinstance(proposal.get("time_plan"), dict) else {}
    plan_after = (
        proposed_structure
        if action != "maintain_plan" and time_plan.get("status") == "redistributed"
        and isinstance(proposed_structure, list) and selected_exercise
        and sum(int(item.get("minutes") or 0) for item in proposed_structure if isinstance(item, dict)) == duration
        else None
    )
    original_structure = proposal.get("original_structure")
    if not isinstance(original_structure, list) or not original_structure:
        original_structure = [{"id": "whole_lesson", "title": "Исходная разбивка не сохранена", "minutes": duration}]
    separate_activity = (
        proposal.get("separate_activity")
        if time_plan.get("status") == "separate_activity" and selected_exercise else None
    )
    lesson_id = int(lesson["lesson_id"])
    course_id = int(case["course_copy_id"])
    return {
        "status": "linked",
        "source": "platform_course_copy",
        "course_id": course_id,
        "course_title": str(case.get("course_title") or "Индивидуальная синтетическая копия"),
        "course_version": int(case.get("course_version") or 1),
        "module_id": lesson.get("module_id"),
        "module_title": str(lesson.get("module_title") or "Модуль не указан в данных урока"),
        "lesson_id": lesson_id,
        "lesson_topic": str(lesson.get("title") or lesson.get("topic") or "Следующий запланированный урок"),
        "learning_goal": str(proposal.get("learning_goal") or ""),
        "learning_goal_source": str(proposal.get("learning_goal_source") or "not_available"),
        "objective_criteria": list(proposal.get("objective_criteria") or []),
        "criteria_coverage": list(proposal.get("criteria_coverage") or []),
        "exercise_audit": list(proposal.get("exercise_audit") or []),
        "prerequisites": list(proposal.get("prerequisites") or []),
        "prerequisites_recorded": bool(proposal.get("prerequisites_recorded")),
        "lesson_content": str(proposal.get("original_content") or ""),
        "lesson_homework": str(proposal.get("original_homework") or ""),
        "attached_exercise_count": int(lesson.get("attached_exercise_count") or 0),
        "curriculum_ready": bool(proposal.get("curriculum_ready")),
        "curriculum_blockers": list(proposal.get("curriculum_blockers") or []),
        "curriculum_structure_status": str(proposal.get("curriculum_structure_status") or "incomplete"),
        "curriculum_structure_errors": list(proposal.get("curriculum_structure_errors") or []),
        "refusal_code": proposal.get("refusal_code"),
        "refusal_causes": list(proposal.get("refusal_causes") or []),
        "recommended_next_step": str(proposal.get("recommended_next_step") or ""),
        "curriculum_warnings": list(proposal.get("curriculum_warnings") or []),
        "structured_exercise_count": int(lesson.get("structured_exercise_count") or 0),
        "course_learning_goal": str(proposal.get("course_learning_goal") or ""),
        "course_learning_goal_placeholder": bool(proposal.get("course_learning_goal_placeholder")),
        "selection_basis": resolution.get("selection_basis"),
        "original_structure_saved": bool(proposal.get("original_structure_saved")),
        "lesson_duration": duration,
        "lesson_url": f"/lesson/{lesson_id}/view",
        "student_url": f"/teacher/students/{int(case['student_id'])}",
        "plan_before": original_structure,
        "plan_after": plan_after,
        "plan_before_total": duration,
        "plan_after_total": duration if plan_after else None,
        "proposal_status": ("not_applied" if plan_after else
                            "separate_activity_requires_teacher_scheduling" if separate_activity else
                            "keep_existing_plan"),
        "proposal_reason": str(proposal.get("text") or "Сохранить существующий план: оснований для изменения нет."),
        "selected_exercise": selected_exercise if plan_after or separate_activity else None,
        "separate_activity": separate_activity,
        "time_plan": time_plan,
        "exercise_alternatives": list(proposal.get("exercise_alternatives") or []) if plan_after or separate_activity else [],
        "event_evidence": list(case.get("evidence") or []),
        "event_evidence_count": len(case.get("evidence") or []),
        "next_check": "Результат следующей проверки должен быть сохранён без содержательной подсказки; не считать один ответ доказательством освоения.",
        "time_impact": (
            f"Сохранённый план: {duration} минут. Перераспределение не обосновано; отдельная проверка занимает "
            f"{int(time_plan.get('separate_activity_minutes') or 0)} минут, всего при её проведении "
            f"{int(time_plan.get('total_with_separate_activity') or duration)} минут. Урок и его этапы остаются прежними."
            if separate_activity else
            f"Исходный план: {duration} минут; предлагается {planned_minutes} минут основного содержания и "
            f"{adaptation_minutes} минут проверки, итого {duration} минут. Сокращения перечислены по этапам."
            if plan_after else
            f"Связанный урок длится {duration} минут; план оставлен без изменений."
        ),
        "mapping_limit": "Навык сопоставлен по каноническому ExamSkill ID или точному уникальному topic_code; результат проверки одного упражнения не означает освоение навыка.",
        "preview_available": bool(case.get("can_generate")),
        "proposal_available": bool(case.get("can_generate") and (plan_after or separate_activity)),
        "evidence_refs": list(case.get("source_refs") or []),
        "skill_summary": case.get("skill_summary"),
    }


def _select_historical_fixture_context(events: list[dict[str, Any]]) -> dict[str, Any]:
    contexts: dict[tuple[str, str, int, int, int], dict[str, Any]] = {}
    for event in events:
        fixture = (event.get("provenance") or {}).get("synthetic_fixture_binding")
        if not isinstance(fixture, dict):
            continue
        identity = (
            str(fixture["fixture_run_key"]), str(fixture["fixture_key"]),
            int(fixture["course_id"]), int(fixture["course_version"]), int(fixture["lesson_id"]),
        )
        contexts.setdefault(identity, fixture)
    if not contexts:
        return {"status": "not_found", "fixture": None, "candidate_contexts": []}
    if len(contexts) > 1:
        return {
            "status": "ambiguous",
            "fixture": None,
            "candidate_contexts": [
                {"fixture_run_key": key[0], "fixture_key": key[1], "course_id": key[2],
                 "course_version": key[3], "lesson_id": key[4]}
                for key in sorted(contexts)
            ],
        }
    return {"status": "resolved", "fixture": next(iter(contexts.values())), "candidate_contexts": []}


def _synthetic_curriculum_context(subject_id: str, events: list[dict[str, Any]], decision: dict[str, Any],
                                 actor_user_id: int) -> dict[str, Any]:
    from core.db_models import AiLabTutorDemo, Lesson, LearningTrajectory, Student, TrajectoryModule, db

    user_id = int(subject_id.rsplit(":", 1)[-1])
    student = Student.query.filter_by(user_id=user_id).first()
    if student:
        from app.ai_lab.course_adapter import resolve_assigned_synthetic_copy

        resolution = resolve_assigned_synthetic_copy(int(student.student_id))
        if resolution.get("status") == "resolved":
            return _platform_curriculum_context(subject_id, actor_user_id)
        if resolution.get("status") == "ambiguous_active_copies":
            return {
                "status": "ambiguous_curriculum",
                "proposal_status": "not_available",
                "candidate_course_ids": resolution.get("candidate_ids", []),
                "proposal_reason": "У ученика несколько активных индивидуальных копий. Для адаптации требуется явный выбор курса.",
            }
        if resolution.get("status") == "active_copy_not_allowlisted":
            return {
                "status": "course_not_allowlisted",
                "proposal_status": "not_available",
                "candidate_course_ids": resolution.get("candidate_ids", []),
                "proposal_reason": "Активная индивидуальная копия не разрешена в synthetic safe mode; историческая фикстура не подменяет её.",
            }

    fixture_resolution = _select_historical_fixture_context(events)
    if fixture_resolution["status"] == "ambiguous":
        return {
            "status": "ambiguous_historical_fixtures",
            "proposal_status": "not_available",
            "candidate_contexts": fixture_resolution["candidate_contexts"],
            "proposal_reason": "Для исторического воспроизведения найдено несколько контекстов курса; требуется явный выбор фикстуры.",
        }
    fixture = fixture_resolution.get("fixture")
    if not fixture:
        return _platform_curriculum_context(subject_id, actor_user_id)
    demo = db.session.get(AiLabTutorDemo, fixture["fixture_run_key"])
    course = db.session.get(LearningTrajectory, fixture["course_id"])
    lesson = db.session.get(Lesson, fixture["lesson_id"])
    module = db.session.get(TrajectoryModule, lesson.course_module_id) if lesson and lesson.course_module_id else None
    metadata = demo.metadata_json if demo and isinstance(demo.metadata_json, dict) else {}
    plan_map = metadata.get("lesson_plans") if isinstance(metadata.get("lesson_plans"), dict) else {}
    plan = plan_map.get(str(fixture["lesson_id"])) if isinstance(plan_map, dict) else None
    segments = plan.get("segments") if isinstance(plan, dict) else None
    if (not student or not course or not lesson or not demo or course.course_id == 3
            or int(course.student_id or 0) != int(student.student_id)
            or int(demo.student_user_id or 0) != user_id or int(demo.student_id or 0) != int(student.student_id)
            or int(demo.course_id or 0) != int(course.course_id)
            or int(lesson.learning_trajectory_id or 0) != int(course.course_id)
            or int(lesson.student_id or 0) != int(student.student_id)
            or not isinstance(segments, list)):
        return {"status": "stale_link", "proposal_status": "not_available"}
    normalized_segments = []
    for item in segments:
        if (not isinstance(item, dict) or not isinstance(item.get("id"), str)
                or not isinstance(item.get("title"), str) or type(item.get("minutes")) is not int
                or item["minutes"] <= 0):
            return {"status": "invalid_plan", "proposal_status": "not_available"}
        normalized_segments.append({"id": item["id"], "title": item["title"], "minutes": item["minutes"]})
    original_total = sum(item["minutes"] for item in normalized_segments)
    duration = int(lesson.duration or course.default_lesson_duration or 0)
    if duration != 60 or original_total != duration or int(course.current_version or 1) < 1:
        return {"status": "invalid_plan", "proposal_status": "not_available"}

    proposed = [dict(item) for item in normalized_segments]
    proposal_allowed = (
        decision.get("action") == "independent_transfer_check"
        and fixture.get("fixture_key") == "game-strategy-transfer"
        and any(event.get("evidence_status") in CONFIRMED
                and (event.get("provenance") or {}).get("synthetic_fixture_binding", {}).get("fixture_key") == "game-strategy-transfer"
                and (event.get("assistance") or {}).get("level") == "substantive_hint" for event in events)
    )
    replaced = False
    if proposal_allowed:
        for index, item in enumerate(proposed):
            if item["id"] == "guided_practice" and item["minutes"] >= 10:
                practice_minutes = item["minutes"] - 10
                proposal_segment = {"id": "independent_transfer_check", "title": "Самостоятельная проверка переноса на новую игровую позицию", "minutes": 10}
                proposed[index:index + 1] = ([proposal_segment] if practice_minutes == 0 else [proposal_segment, {
                    "id": item["id"], "title": item["title"], "minutes": practice_minutes,
                }])
                replaced = True
                break
    proposal_total = sum(item["minutes"] for item in proposed)
    return {
        "status": "linked",
        "source": "historical_fixture",
        "course_id": int(course.course_id),
        "course_title": str(course.title),
        "course_version": int(course.current_version or 1),
        "module_id": int(module.module_id) if module else None,
        "module_title": str(module.title) if module else None,
        "lesson_id": int(lesson.lesson_id),
        "lesson_topic": str(lesson.topic or ""),
        "lesson_duration": duration,
        "lesson_url": f"/lesson/{lesson.lesson_id}/view",
        "student_url": f"/teacher/students/{student.student_id}",
        "plan_before": normalized_segments,
        "plan_after": proposed if replaced and proposal_total == original_total else None,
        "plan_before_total": original_total,
        "plan_after_total": proposal_total if replaced else None,
        "proposal_status": "not_applied" if replaced else "keep_existing_plan",
        "proposal_reason": ("Синтетическая фикстура помечает более поздний результат как полученный после содержательной подсказки; фактическая помощь платформы не подтверждена. Самостоятельный перенос ещё не проверен."
                            if replaced else "Сохранённые события не дают достаточного основания менять это занятие."),
        "next_check": ("Предложить новую позицию с другими числами, не давать содержательную подсказку и сохранить ответ через штатную сдачу платформы."
                       if replaced else None),
        "time_impact": (f"В плане урока {duration} минут 10 минут самостоятельной проверки занимают часть практики; новая сумма остаётся {proposal_total} минут. Предложение не применено."
                        if replaced else f"Связанный урок длится {duration} минут; план оставлен без изменений."),
        "mapping_limit": "Курс, задания и связи с навыком созданы для локальной синтетической приёмки; это не изменение курса 3 и не экспертно утверждённая программа.",
    }


def get_tutor_core31_state(actor_user_id: int) -> dict[str, Any]:
    from app.ai_lab.analytics import stored_lesson_task_evidence, stored_platform_homework_evidence
    from app.ai_lab.lesson_intelligence import stored_lesson_evidence
    from app.ai_lab.practice import stored_ai_practice_evidence
    from app.ai_lab.provider import is_local_ai_lab_enabled

    if not is_local_ai_lab_enabled():
        raise EvidenceContractError("Tutor Core 3.1 доступен только в локальной AI Lab.")
    homework = stored_platform_homework_evidence(actor_user_id=actor_user_id)
    lessons = stored_lesson_evidence(actor_user_id=actor_user_id)
    classwork = stored_lesson_task_evidence(actor_user_id=actor_user_id)
    practice = stored_ai_practice_evidence(actor_user_id=actor_user_id)
    user_cache: dict[int, bool] = {}
    accepted = [event for event in homework + lessons + classwork + practice if _synthetic_subject_id(event, user_cache)]
    rejected_count = len(homework) + len(lessons) + len(classwork) + len(practice) - len(accepted)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if accepted:
        bundle = merge_evidence_events([accepted], allowed_subject_ids={item["subject_id"] for item in accepted})
        for event in bundle["events"]:
            grouped[event["subject_id"]].append(event)
    learners = [
        _profile_card(subject_id, events, index, actor_user_id)
        for index, (subject_id, events) in enumerate(sorted(grouped.items()), 1)
    ]
    return {
        "version": TUTOR_CORE31_VERSION,
        "evidence_contract": EVIDENCE_CONTRACT_VERSION,
        "model_calls": 0,
        "synthetic_scope": "События берутся только из локального allowlist синтетических User → Student профилей.",
        "learners": learners,
        "totals": {
            "profiles": len(learners),
            "events": sum(len(events) for events in grouped.values()),
            "excluded_unmatched_events": rejected_count,
            "knowledge_links": sum(len(item["knowledge"]) for item in learners),
        },
        "integrations": [
            {"source": "Домашняя работа + Code Judge", "status": "connected", "detail": "Считываются подтверждённые отчёты sandbox Code Judge и повторно проверенные точные ответы. Связи синтетических заданий с навыками помечены отдельно и не считаются экспертными."},
            {"source": "AI Lesson", "status": "teacher_confirmed_only", "detail": "В поток попадают только наблюдения с явным решением преподавателя и тем же синтетическим субъектом."},
            {"source": "Классная работа в Lesson Room", "status": "connected" if classwork else "available_no_events",
             "detail": "В синтетическом режиме читаются сохранённые попытки по заданиям типа classwork. Засчитывается только штатная точная проверка; связь с навыком и помощь в комнате остаются неизвестными."},
            {"source": "AI Practice", "status": "connected" if practice else "available_no_events",
             "detail": "Сохранённые попытки входят в Learning Evidence v2. Навык разрешается по точному ExamSkill ID или уникальному topic_code; семейства без точного соответствия остаются несопоставленными."},
            {"source": "Ручная оценка", "status": "explicit_revision_audit",
             "detail": "Новые ручные оценки имеют отдельную ревизию с методом и автором; исправления замещают текущую запись, а предыдущие остаются в аудите. Для старых записей без ревизии происхождение неизвестно; reviewed_at не используется как доказательство."},
            {"source": "Curriculum", "status": "explicit_synthetic_copy_required", "detail": "Предложения могут ссылаться только на единственную индивидуальную копию разрешённого синтетического шаблона и связанные с уроком ExamSkills; исходный курс не меняется."},
            {"source": "Tutor Core 3.0", "status": "historical_demo", "detail": "Сохранённая шестичастная фикстура доступна отдельно как техническая демонстрация, не как учебный курс."},
        ],
        "limits": [
            "Подтверждённый итог ограниченного Code Judge набора — техническое свидетельство на этих тестах, а не доказательство полной корректности.",
            "Точные текстовые ответы подтверждают только результат штатного эталонного сравнения; синтетическая связь с навыком не прошла экспертную приёмку.",
            "Не записанная источником помощь остаётся неизвестной; система не приписывает результат самостоятельной работе.",
            "Стадии освоения не выводятся из короткой истории и не задаются общими процентами.",
            "Предложения строятся только для однозначно разрешённой активной индивидуальной копии; базовый шаблон и другие копии не изменяются.",
            "Сценарии Tutor Core 3.0 — разработческие фикстуры, не независимая контрольная серия.",
        ],
    }
