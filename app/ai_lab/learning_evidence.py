"""Versioned evidence envelope shared by local AI Lab learning modules."""
from __future__ import annotations

import math
import json
import re
import hashlib
from datetime import datetime
from typing import Any


LEGACY_EVIDENCE_CONTRACT_VERSION = "boostudy.learning-evidence.v1"
EVIDENCE_CONTRACT_VERSION = "boostudy.learning-evidence.v2"
LESSON_INTELLIGENCE_CONTRACT_VERSION = "boostudy.lesson-intelligence-output.v2"


def course_skill_criteria_fingerprint(criteria: Any) -> str:
    normalized = criteria if isinstance(criteria, list) else []
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
ASSISTANCE_LEVELS = frozenset({
    "independent",
    "neutral_organizational",
    "general_rule_reminder",
    "leading_question",
    "substantive_hint",
    "partial_solution",
    "full_solution",
    "no_platform_hint",
})
EVIDENCE_STATUSES = frozenset({
    "technical_confirmed",
    "expert_confirmed",
    "ai_inference",
    "hypothesis",
    "insufficient_data",
})
EVIDENCE_SOURCES = frozenset({
    "ai_homework",
    "ai_classwork",
    "ai_analytics",
    "ai_practice",
    "ai_course",
    "ai_lesson_intelligence",
    "ai_tutor_core",
})
CRITERION_STATUSES = frozenset({"met", "not_met", "insufficient_data"})


class EvidenceContractError(ValueError):
    """Raised when an evidence record cannot be trusted as a typed event."""


_NON_HUMAN_EVALUATION_METHODS = {
    "automatic_answer_checker", "python_test_suite", "code_judge",
    "awaiting_teacher_review", "automatic_check_unavailable",
}
_TIMESTAMP_SOURCE_FIELDS = {
    "lesson_task_attempt.submitted_at": "lesson_task_attempt_submitted_at",
    "submission_attempt.submitted_at": "submission_attempt_submitted_at",
    "submission.submitted_at": "submission_submitted_at",
    "answer.submitted_separately_at": "answer_submitted_at",
}
_TIMESTAMP_CONTEXT_FIELDS = {
    "lesson_task_attempt_submitted_at", "lesson_task_planned_at", "lesson_created_at",
    "assignment_published_at", "student_assigned_at", "submission_started_at",
    "submission_submitted_at", "submission_attempt_submitted_at", "submission_graded_at",
    "results_published_at", "answer_submitted_at", "answer_reviewed_at",
    "evaluation_revision_at", "ai_reviewed_at",
}
_TIMESTAMP_FIELD_INTERPRETATIONS = {
    "lesson_task_planned_at": {
        "missing", "inherited_template", "source_record", "source_record_unverified", "conflicting",
    },
}


def merge_evidence_events(
    event_groups: list[list[dict[str, Any]]],
    *,
    allowed_subject_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Normalize and merge source adapters without inferring mastery or hiding conflicts.

    Callers that handle synthetic-only workflows must pass the explicit synthetic
    subject allowlist. Identical duplicate event IDs are collapsed; conflicting
    payloads with one ID fail closed.
    """
    if not isinstance(event_groups, list):
        raise EvidenceContractError("Набор источников должен быть списком событий.")
    merged: dict[str, dict[str, Any]] = {}
    duplicate_count = 0
    for group in event_groups:
        if not isinstance(group, list):
            raise EvidenceContractError("Каждый источник должен передать список событий.")
        for raw in group:
            event = validate_evidence_event(raw)
            if allowed_subject_ids is not None and event["subject_id"] not in allowed_subject_ids:
                raise EvidenceContractError("Источник содержит субъект вне явного allowlist этой симуляции.")
            existing = merged.get(event["event_id"])
            if existing is None:
                merged[event["event_id"]] = event
                continue
            canonical_existing = json.dumps(existing, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            canonical_event = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if canonical_existing != canonical_event:
                raise EvidenceContractError("Один event_id пришёл с противоречащими данными из нескольких источников.")
            duplicate_count += 1
    events = sorted(merged.values(), key=lambda item: (item["occurred_at"], item["event_id"]))
    source_counts: dict[str, int] = {}
    for event in events:
        source_counts[event["source_module"]] = source_counts.get(event["source_module"], 0) + 1
    return {
        "contract_version": EVIDENCE_CONTRACT_VERSION,
        "events": events,
        "event_count": len(events),
        "duplicate_count": duplicate_count,
        "source_counts": source_counts,
    }


def validate_evidence_event(raw: Any) -> dict[str, Any]:
    """Validate and normalize one event without assigning pedagogical meaning."""
    if not isinstance(raw, dict):
        raise EvidenceContractError("Событие должно быть JSON-объектом.")
    source_contract = raw.get("contract_version")
    if source_contract not in {LEGACY_EVIDENCE_CONTRACT_VERSION, EVIDENCE_CONTRACT_VERSION}:
        raise EvidenceContractError("Неизвестная версия контракта учебных доказательств.")

    required_text = (
        "event_id", "subject_id", "source_module", "source_record_id", "occurred_at",
        "evidence_status",
    )
    event: dict[str, Any] = {}
    for field in required_text:
        value = raw.get(field)
        if not isinstance(value, str) or not value.strip():
            raise EvidenceContractError(f"Поле «{field}» обязательно и должно быть непустой строкой.")
        event[field] = value.strip()

    if event["source_module"] not in EVIDENCE_SOURCES:
        raise EvidenceContractError("Поле «source_module» содержит неизвестный модуль.")
    if event["evidence_status"] not in EVIDENCE_STATUSES:
        raise EvidenceContractError("Поле «evidence_status» содержит неизвестный статус доказательства.")
    try:
        occurred_at = datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceContractError("Поле «occurred_at» должно быть датой ISO 8601.") from exc
    if occurred_at.tzinfo is None:
        raise EvidenceContractError("Поле «occurred_at» должно содержать часовой пояс.")
    event["occurred_at"] = occurred_at.isoformat()

    assignment = raw.get("assignment")
    if assignment is not None:
        if not isinstance(assignment, dict):
            raise EvidenceContractError("Поле «assignment» должно быть объектом.")
        assignment_id = assignment.get("id")
        version = assignment.get("version")
        if not isinstance(assignment_id, str) or not assignment_id.strip():
            raise EvidenceContractError("В поле «assignment» укажите стабильный id задания.")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise EvidenceContractError("В поле «assignment.version» укажите положительную версию.")
        event["assignment"] = {"id": assignment_id.strip(), "version": version}
    else:
        event["assignment"] = None

    course_context = raw.get("course_context")
    if course_context is not None:
        if not isinstance(course_context, dict):
            raise EvidenceContractError("Поле «course_context» должно быть объектом.")
        practice_context_fields = {
            "contract", "course_id", "course_version", "lesson_id", "skill_id",
            "course_skill_id", "topic_code",
        }
        if course_context.get("contract") == "boostudy.synthetic-practice-course-context.v1":
            course_id = course_context.get("course_id")
            course_version = course_context.get("course_version")
            lesson_id = course_context.get("lesson_id")
            skill_id = course_context.get("skill_id")
            course_skill_id = course_context.get("course_skill_id")
            topic_code = course_context.get("topic_code")
            if (set(course_context) != practice_context_fields
                    or event["source_module"] != "ai_practice"
                    or not re.fullmatch(r"platform-student:[1-9][0-9]*", event["subject_id"])
                    or any(type(value) is not int or value < 1
                           for value in (course_id, course_version, lesson_id))
                    or not isinstance(skill_id, str)
                    or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,159}", skill_id)
                    or not isinstance(course_skill_id, str)
                    or not re.fullmatch(r"exam-skill:[1-9][0-9]*", course_skill_id)
                    or not isinstance(topic_code, str)
                    or not re.fullmatch(r"ege\.[a-z0-9][a-z0-9._-]{0,157}", topic_code)):
                raise EvidenceContractError("Синтетический контекст AI Practice имеет неверную структуру или значения.")
            event["course_context"] = {
                "contract": "boostudy.synthetic-practice-course-context.v1",
                "course_id": course_id,
                "course_version": course_version,
                "lesson_id": lesson_id,
                "skill_id": skill_id,
                "course_skill_id": course_skill_id,
                "topic_code": topic_code,
            }
        elif course_context.get("contract") == "boostudy.synthetic-homework-course-context.v1":
            fields = {
                "contract", "course_id", "course_version", "lesson_id",
                "course_skill_id", "topic_code", "criteria_fingerprint",
            }
            course_id = course_context.get("course_id")
            course_version = course_context.get("course_version")
            lesson_id = course_context.get("lesson_id")
            course_skill_id = course_context.get("course_skill_id")
            topic_code = course_context.get("topic_code")
            fingerprint = course_context.get("criteria_fingerprint")
            if (set(course_context) != fields
                    or event["source_module"] != "ai_homework"
                    or not re.fullmatch(r"platform-student:[1-9][0-9]*", event["subject_id"])
                    or any(type(value) is not int or value < 1
                           for value in (course_id, course_version, lesson_id))
                    or not isinstance(course_skill_id, str)
                    or not re.fullmatch(r"exam-skill:[1-9][0-9]*", course_skill_id)
                    or not isinstance(topic_code, str)
                    or not re.fullmatch(r"ege\.[a-z0-9][a-z0-9._-]{0,157}", topic_code)
                    or not isinstance(fingerprint, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", fingerprint)):
                raise EvidenceContractError("Контекст домашней работы не содержит точную synthetic-привязку курса, урока, навыка и критериев.")
            event["course_context"] = {
                "contract": "boostudy.synthetic-homework-course-context.v1",
                "course_id": course_id,
                "course_version": course_version,
                "lesson_id": lesson_id,
                "course_skill_id": course_skill_id,
                "topic_code": topic_code,
                "criteria_fingerprint": fingerprint,
            }
        else:
            course_id = course_context.get("course_id")
            course_version = course_context.get("course_version")
            if (set(course_context) != {"course_id", "course_version"}
                    or not isinstance(course_id, str) or not course_id.startswith("synthetic-")
                    or isinstance(course_version, bool) or not isinstance(course_version, int)
                    or course_version < 1):
                raise EvidenceContractError("course_context должен содержать только synthetic-id и положительную версию.")
            event["course_context"] = {"course_id": course_id, "course_version": course_version}

    for field in ("topic_ids", "skill_ids", "limitations"):
        value = raw.get(field, [])
        if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
            raise EvidenceContractError(f"Поле «{field}» должно быть списком непустых строк.")
        event[field] = list(dict.fromkeys(item.strip() for item in value))

    error_codes = raw.get("error_codes", [])
    event["error_codes"] = _string_list(error_codes, "error_codes")

    outcome = raw.get("outcome", {})
    if not isinstance(outcome, dict):
        raise EvidenceContractError("Поле «outcome» должно быть объектом.")
    score = outcome.get("score")
    maximum = outcome.get("maximum")
    if score is not None and not _finite_number(score):
        raise EvidenceContractError("Поле «outcome.score» должно быть конечным числом или null.")
    if maximum is not None and (not _finite_number(maximum) or maximum <= 0):
        raise EvidenceContractError("Поле «outcome.maximum» должно быть положительным конечным числом или null.")
    if score is not None and (maximum is None or score < 0 or score > maximum):
        raise EvidenceContractError("Оценка должна находиться в диапазоне от 0 до максимума.")
    grade_status = outcome.get("status", "unknown")
    if not isinstance(grade_status, str) or not grade_status.strip():
        raise EvidenceContractError("Поле «outcome.status» должно быть непустой строкой.")
    event["outcome"] = {"score": score, "maximum": maximum, "status": grade_status.strip()}

    criteria = raw.get("criteria", [])
    if not isinstance(criteria, list):
        raise EvidenceContractError("Поле «criteria» должно быть списком.")
    normalized_criteria = []
    seen_ids = set()
    for index, item in enumerate(criteria, 1):
        if not isinstance(item, dict):
            raise EvidenceContractError(f"Результат критерия №{index} должен быть объектом.")
        criterion_id = item.get("criterion_id")
        status = item.get("status")
        if not isinstance(criterion_id, str) or not criterion_id.strip():
            raise EvidenceContractError(f"Укажите criterion_id для результата №{index}.")
        criterion_id = criterion_id.strip()
        if criterion_id in seen_ids:
            raise EvidenceContractError(f"Повторяется criterion_id «{criterion_id}».")
        seen_ids.add(criterion_id)
        if status not in CRITERION_STATUSES:
            raise EvidenceContractError(f"У критерия «{criterion_id}» неизвестный статус.")
        earned = item.get("earned")
        criterion_max = item.get("maximum")
        if status == "insufficient_data":
            if earned is not None:
                raise EvidenceContractError(f"Для критерия «{criterion_id}» с недостаточными данными earned должен быть null.")
        elif (not _finite_number(earned) or not _finite_number(criterion_max)
              or criterion_max <= 0 or earned < 0 or earned > criterion_max):
            raise EvidenceContractError(f"Баллы критерия «{criterion_id}» не соответствуют его максимуму.")
        item_evidence_status = item.get("evidence_status", event["evidence_status"])
        if item_evidence_status not in EVIDENCE_STATUSES:
            raise EvidenceContractError(f"У критерия «{criterion_id}» неизвестный статус доказательства.")
        skill_id = item.get("skill_id")
        if skill_id is not None and (not isinstance(skill_id, str) or not skill_id.strip()):
            raise EvidenceContractError(f"У критерия «{criterion_id}» некорректный skill_id.")
        normalized_criteria.append({
            "criterion_id": criterion_id, "earned": earned,
            "maximum": criterion_max, "status": status,
            "evidence_status": item_evidence_status,
            "skill_id": skill_id.strip() if isinstance(skill_id, str) else None,
            "reason": str(item.get("reason") or "").strip(),
            "source_refs": _string_list(item.get("source_refs", []), f"criteria[{index}].source_refs"),
        })
    event["criteria"] = normalized_criteria
    if isinstance(event.get("course_context"), dict) and event["course_context"].get("contract") in {
        "boostudy.synthetic-practice-course-context.v1",
        "boostudy.synthetic-homework-course-context.v1",
    }:
        context = event["course_context"]
        bound_skill_ids = {context["course_skill_id"]}
        if context["contract"] == "boostudy.synthetic-practice-course-context.v1":
            bound_skill_ids.add(context["skill_id"])
        draft_binding = ((raw.get("provenance") or {}).get("synthetic_course_task_binding")
                         if isinstance(raw.get("provenance"), dict) else None)
        unapproved_draft_observation = (
            context["contract"] == "boostudy.synthetic-homework-course-context.v1"
            and isinstance(draft_binding, dict)
            and draft_binding.get("pedagogical_status") == "not_pedagogically_approved"
            and draft_binding.get("skill_id") == context["course_skill_id"]
            and any(item["criterion_id"] == draft_binding.get("criterion_id")
                    and item["skill_id"] is None
                    and item["earned"] is None
                    and item["status"] == "insufficient_data"
                    and item["evidence_status"] == "insufficient_data"
                    for item in normalized_criteria)
            and not bound_skill_ids.intersection(event["skill_ids"])
        )
        if (not unapproved_draft_observation
                and (not bound_skill_ids.intersection(event["skill_ids"])
                     or not any(item["skill_id"] in bound_skill_ids for item in normalized_criteria))):
            raise EvidenceContractError("Контекст практики не совпадает с навыком проверенного события.")

    assistance = raw.get("assistance")
    if assistance is None:
        # Missing source data stays missing; callers must not infer independence.
        event["assistance"] = None
    else:
        if not isinstance(assistance, dict):
            raise EvidenceContractError("Поле «assistance» должно быть объектом или null.")
        level = assistance.get("level")
        if not isinstance(level, str) or level not in ASSISTANCE_LEVELS:
            raise EvidenceContractError("Поле «assistance.level» содержит неизвестный характер помощи.")
        event["assistance"] = {
            "level": level,
            "source_refs": _string_list(assistance.get("source_refs", []), "assistance.source_refs"),
        }

    provenance = raw.get("provenance", {})
    if not isinstance(provenance, dict):
        raise EvidenceContractError("Поле «provenance» должно быть объектом.")
    event["provenance"] = {
        "source_ref": str(provenance.get("source_ref") or "").strip(),
        "payload_hash": str(provenance.get("payload_hash") or "").strip(),
        "model": str(provenance.get("model") or "").strip(),
        "method": str(provenance.get("method") or "").strip(),
    }
    timestamp_context = provenance.get("timestamp_context")
    if timestamp_context is not None:
        if (not isinstance(timestamp_context, dict)
                or set(timestamp_context) not in (
                    {"event_time_source", "timestamps", "context_only"},
                    {"event_time_source", "timestamps", "context_only", "field_interpretations"},
                )):
            raise EvidenceContractError("Контекст времени события имеет неверную структуру.")
        source = timestamp_context.get("event_time_source")
        timestamps = timestamp_context.get("timestamps")
        context_only = timestamp_context.get("context_only")
        interpretations = timestamp_context.get("field_interpretations", {})
        if not isinstance(source, str) or source not in _TIMESTAMP_SOURCE_FIELDS:
            raise EvidenceContractError("Контекст времени события ссылается на неизвестный источник фактической сдачи.")
        if not isinstance(timestamps, dict) or not set(timestamps).issubset(_TIMESTAMP_CONTEXT_FIELDS):
            unknown_fields = sorted(set(timestamps) - _TIMESTAMP_CONTEXT_FIELDS) if isinstance(timestamps, dict) else []
            raise EvidenceContractError(
                "Контекст времени содержит неизвестные временные поля" +
                (f": {', '.join(map(str, unknown_fields))}." if unknown_fields else ".")
            )
        if (not isinstance(context_only, list)
                or any(not isinstance(item, str) or item not in timestamps for item in context_only)
                or len(context_only) != len(set(context_only))):
            raise EvidenceContractError("Контекст времени некорректно отмечает служебные временные поля.")
        if (not isinstance(interpretations, dict)
                or any(field not in _TIMESTAMP_FIELD_INTERPRETATIONS
                       or value not in _TIMESTAMP_FIELD_INTERPRETATIONS[field]
                       for field, value in interpretations.items())):
            raise EvidenceContractError("Контекст времени содержит неизвестную интерпретацию плановой даты.")
        normalized_timestamps = {}
        for name, value in timestamps.items():
            if value is None:
                normalized_timestamps[name] = None
                continue
            if not isinstance(value, str):
                raise EvidenceContractError(f"Метка времени «{name}» должна быть ISO 8601 или null.")
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise EvidenceContractError(f"Метка времени «{name}» должна быть ISO 8601.") from exc
            if parsed.tzinfo is None:
                raise EvidenceContractError(f"Метка времени «{name}» должна содержать часовой пояс.")
            normalized_timestamps[name] = parsed.isoformat()
        source_field = _TIMESTAMP_SOURCE_FIELDS[source]
        source_value = normalized_timestamps.get(source_field)
        if not source_value:
            raise EvidenceContractError("Фактическое время события отсутствует в контексте происхождения.")
        source_time = datetime.fromisoformat(source_value)
        if source_time != occurred_at:
            raise EvidenceContractError("Фактическое время события не совпадает с указанным источником.")
        event["provenance"]["timestamp_context"] = {
            "event_time_source": source,
            "timestamps": normalized_timestamps,
            "context_only": list(context_only),
            "field_interpretations": dict(interpretations),
        }
    evaluation_revision = provenance.get("evaluation_revision")
    if evaluation_revision is not None:
        if (not isinstance(evaluation_revision, dict)
                or evaluation_revision.get("status") != "legacy_unknown"
                and set(evaluation_revision) != {"id", "revision_no", "method", "actor_user_id", "state"}):
            raise EvidenceContractError("Происхождение оценки имеет неверную структуру.")
        if evaluation_revision.get("status") == "legacy_unknown":
            if set(evaluation_revision) != {"status"}:
                raise EvidenceContractError("Историческая оценка без происхождения содержит лишние данные.")
            event["provenance"]["evaluation_revision"] = {"status": "legacy_unknown"}
        else:
            revision_id = evaluation_revision.get("id")
            revision_no = evaluation_revision.get("revision_no")
            actor_id = evaluation_revision.get("actor_user_id")
            method = evaluation_revision.get("method")
            revision_state = evaluation_revision.get("state")
            actor_is_valid = (
                actor_id is None and isinstance(method, str) and method in _NON_HUMAN_EVALUATION_METHODS
                or type(actor_id) is int and actor_id > 0
            )
            if (type(revision_id) is not int or revision_id <= 0
                    or type(revision_no) is not int or revision_no <= 0
                    or not actor_is_valid
                    or not isinstance(method, str) or not re.fullmatch(r"[a-z_]{1,48}", method)
                    or revision_state not in {"current", "voided"}
                    or revision_state == "voided" and (
                            event["evidence_status"] != "insufficient_data"
                            or event["outcome"]["score"] is not None
                            or event["outcome"]["status"] != "insufficient_data"
                            or any(criterion["status"] != "insufficient_data"
                                   or criterion["evidence_status"] != "insufficient_data"
                                   or criterion["earned"] is not None
                                   for criterion in event["criteria"])
                    )):
                raise EvidenceContractError("Происхождение оценки содержит недопустимые значения.")
            event["provenance"]["evaluation_revision"] = {
                "id": revision_id, "revision_no": revision_no, "method": method,
                "actor_user_id": actor_id, "state": revision_state,
            }
    task_binding = provenance.get("platform_task_binding")
    if task_binding is not None:
        binding_fields = {
            "knowledge_stable_key", "knowledge_version", "knowledge_content_sha256",
            "task_id", "content_fingerprint", "source_key", "course_id", "course_version",
            "lesson_id", "skill_id",
        }
        if not isinstance(task_binding, dict) or set(task_binding) != binding_fields:
            raise EvidenceContractError("Точная platform-привязка имеет неверную структуру.")
        integer_fields = ("knowledge_version", "task_id", "course_id", "course_version", "lesson_id")
        if (any(type(task_binding.get(field)) is not int or task_binding[field] <= 0 for field in integer_fields)
                or not isinstance(task_binding.get("knowledge_stable_key"), str)
                or not task_binding["knowledge_stable_key"].strip()
                or len(task_binding["knowledge_stable_key"]) > 160
                or not isinstance(task_binding.get("knowledge_content_sha256"), str)
                or len(task_binding["knowledge_content_sha256"]) != 64
                or any(char not in "0123456789abcdef" for char in task_binding["knowledge_content_sha256"])
                or not isinstance(task_binding.get("content_fingerprint"), str)
                or len(task_binding["content_fingerprint"]) != 64
                or any(char not in "0123456789abcdef" for char in task_binding["content_fingerprint"])
                or not isinstance(task_binding.get("source_key"), str)
                or not task_binding["source_key"]
                or len(task_binding["source_key"]) > 200
                or any(not (char.isascii() and (char.isalnum() or char in "_.:-")) for char in task_binding["source_key"])
                or not isinstance(task_binding.get("skill_id"), str)
                or not task_binding["skill_id"].startswith("exam-skill:")
                or not task_binding["skill_id"][11:].isdigit()
                or int(task_binding["skill_id"][11:]) <= 0):
            raise EvidenceContractError("Точная platform-привязка содержит недопустимые значения.")
        event_task_id = event["event_id"].rsplit(":task:", 1)[-1]
        if (event_task_id != str(task_binding["task_id"])
                or task_binding["skill_id"] not in event["skill_ids"]):
            raise EvidenceContractError("Точная platform-привязка не совпадает с заданием или навыком события.")
        event["provenance"]["platform_task_binding"] = dict(task_binding)
    fixture_binding = provenance.get("synthetic_fixture_binding")
    if fixture_binding is not None:
        fixture_fields = {
            "fixture_run_key", "fixture_key", "knowledge_stable_key", "knowledge_version",
            "knowledge_title", "knowledge_status", "knowledge_source_titles", "knowledge_content_sha256",
            "task_id", "task_content_sha256", "source_key", "course_id", "course_version", "lesson_id", "skill_key",
        }
        if not isinstance(fixture_binding, dict) or set(fixture_binding) != fixture_fields:
            raise EvidenceContractError("Синтетическая fixture-привязка имеет неверную структуру.")
        run_key = fixture_binding.get("fixture_run_key")
        fixture_key = fixture_binding.get("fixture_key")
        stable_key = fixture_binding.get("knowledge_stable_key")
        skill_key = fixture_binding.get("skill_key")
        source_key = fixture_binding.get("source_key")
        source_titles = fixture_binding.get("knowledge_source_titles")
        integer_fields = ("knowledge_version", "task_id", "course_id", "course_version", "lesson_id")
        hashes = ("knowledge_content_sha256", "task_content_sha256")
        if (not isinstance(run_key, str) or not re.fullmatch(r"[a-z0-9_-]{1,80}", run_key)
                or fixture_key not in {"sql-relational-query", "game-strategy-initial", "game-strategy-transfer", "data-quality-manual"}
                or not isinstance(stable_key, str) or not stable_key.startswith("ege.inf.")
                or not isinstance(fixture_binding.get("knowledge_title"), str) or not fixture_binding["knowledge_title"].strip()
                or fixture_binding.get("knowledge_status") not in {"source_checked", "approved"}
                or not isinstance(source_titles, list)
                or any(not isinstance(title, str) or not title.strip() for title in source_titles)
                or not isinstance(skill_key, str) or not re.fullmatch(r"skill\.inf\.[a-z0-9-]{1,100}", skill_key)
                or source_key != f"boostudy.synthetic.tutorcore31.v1/{run_key}/{fixture_key}"
                or any(type(fixture_binding.get(field)) is not int or fixture_binding[field] <= 0 for field in integer_fields)
                or fixture_binding["course_id"] == 3
                or any(not isinstance(fixture_binding.get(field), str)
                       or not re.fullmatch(r"[0-9a-f]{64}", fixture_binding[field]) for field in hashes)):
            raise EvidenceContractError("Синтетическая fixture-привязка содержит недопустимые значения.")
        event_task_id = event["event_id"].rsplit(":task:", 1)[-1]
        if event_task_id != str(fixture_binding["task_id"]) or skill_key not in event["skill_ids"]:
            raise EvidenceContractError("Синтетическая fixture-привязка не совпадает с заданием или навыком события.")
        event["provenance"]["synthetic_fixture_binding"] = dict(fixture_binding)
    course_task_binding = provenance.get("synthetic_course_task_binding")
    selection_fields_present: set[str] = set()
    if course_task_binding is not None:
        required_binding_fields = {
            "contract", "course_id", "course_version", "lesson_id", "task_id",
            "skill_id", "topic_code", "criterion_id", "task_fingerprint",
            "task_content_sha256", "pedagogical_status",
        }
        optional_binding_fields = {
            "assessment_method", "checker_fingerprint", "semantic_compatibility",
            "source_course_id", "source_course_version", "source_lesson_id", "student_id",
            "purpose", "selected_at",
        }
        binding_keys = set(course_task_binding) if isinstance(course_task_binding, dict) else set()
        if (not isinstance(course_task_binding, dict)
                or not required_binding_fields.issubset(binding_keys)
                or not binding_keys.issubset(required_binding_fields | optional_binding_fields)
                or course_task_binding.get("contract") != "boostudy.synthetic-course-task-binding.v1"
                or course_task_binding.get("pedagogical_status") != "not_pedagogically_approved"):
            raise EvidenceContractError("Синтетическая связь задания курса имеет неверную структуру или статус.")
        integer_fields = ("course_id", "course_version", "lesson_id", "task_id")
        if (any(type(course_task_binding.get(field)) is not int or course_task_binding[field] <= 0 for field in integer_fields)
                or not isinstance(course_task_binding.get("skill_id"), str)
                or not re.fullmatch(r"exam-skill:[1-9][0-9]*", course_task_binding["skill_id"])
                or not isinstance(course_task_binding.get("topic_code"), str)
                or not course_task_binding["topic_code"].startswith("ege.inf.")
                or len(course_task_binding["topic_code"]) > 160
                or not isinstance(course_task_binding.get("criterion_id"), str)
                or not re.fullmatch(r"[a-z0-9_-]{1,100}", course_task_binding["criterion_id"])
                or any(not isinstance(course_task_binding.get(field), str)
                       or not re.fullmatch(r"[0-9a-f]{64}", course_task_binding[field])
                       for field in ("task_fingerprint", "task_content_sha256"))
                or event["source_module"] not in {"ai_classwork", "ai_homework"}
                or not str(event["subject_id"]).startswith("platform-student:")):
            raise EvidenceContractError("Синтетическая связь задания курса содержит недопустимые значения.")
        assessment_method = course_task_binding.get("assessment_method")
        checker_fingerprint = course_task_binding.get("checker_fingerprint")
        compatibility = course_task_binding.get("semantic_compatibility")
        if (assessment_method is not None
                and (not isinstance(assessment_method, str) or not assessment_method.strip()
                     or len(assessment_method) > 100)):
            raise EvidenceContractError("Синтетическая связь задания курса содержит недопустимые значения.")
        if (checker_fingerprint is not None
                and (not isinstance(checker_fingerprint, str)
                     or not re.fullmatch(r"[0-9a-f]{64}", checker_fingerprint))):
            raise EvidenceContractError("Синтетическая связь задания курса содержит недопустимые значения.")
        if compatibility is not None:
            if (not isinstance(compatibility, dict)
                    or set(compatibility) != {"status", "matches", "mismatches", "reason"}
                    or compatibility.get("status") not in {"compatible", "incompatible", "unverified"}
                    or not isinstance(compatibility.get("matches"), list)
                    or not isinstance(compatibility.get("mismatches"), list)
                    or any(not isinstance(value, str) or len(value) > 160
                           for value in compatibility["matches"] + compatibility["mismatches"])
                    or not isinstance(compatibility.get("reason"), str)
                    or len(compatibility["reason"]) > 1_000):
                raise EvidenceContractError("Синтетическая связь задания курса содержит недопустимые значения.")
        selection_fields = {
            "source_course_id", "source_course_version", "source_lesson_id", "student_id",
            "purpose", "selected_at",
        }
        selection_fields_present = binding_keys & selection_fields
        if selection_fields_present and selection_fields_present != selection_fields:
            raise EvidenceContractError("Контекст повторного задания должен содержать полную атрибуцию выбора преподавателя.")
        if selection_fields_present:
            try:
                selected_at = datetime.fromisoformat(
                    str(course_task_binding.get("selected_at") or "").replace("Z", "+00:00")
                )
            except (TypeError, ValueError):
                selected_at = None
            selection_ids = ("source_course_id", "source_course_version", "source_lesson_id", "student_id")
            if (any(type(course_task_binding.get(field)) is not int or course_task_binding[field] <= 0
                    for field in selection_ids)
                    or course_task_binding["source_course_id"] == course_task_binding["course_id"]
                    or course_task_binding.get("purpose") != "shared_review"
                    or selected_at is None or selected_at.tzinfo is None
                    or event["source_module"] != "ai_homework"
                    or not compatibility or compatibility.get("status") != "unverified"
                    or "teacher_selected_shared_review" not in compatibility.get("mismatches", [])):
                raise EvidenceContractError("Повторное задание должно оставаться явно непроверенным общим разбором.")
        if event["evidence_status"] in {"technical_confirmed", "expert_confirmed"}:
            criterion = next((item for item in event["criteria"]
                              if item["criterion_id"] == course_task_binding["criterion_id"]), None)
            if course_task_binding["pedagogical_status"] == "not_pedagogically_approved":
                if (not criterion or course_task_binding["skill_id"] in event["skill_ids"]
                        or criterion["skill_id"] is not None
                        or criterion["status"] != "insufficient_data"
                        or criterion["evidence_status"] != "insufficient_data"
                        or criterion["earned"] is not None):
                    raise EvidenceContractError(
                        "Технический результат чернового задания не должен подтверждать учебный критерий."
                    )
            elif (course_task_binding["skill_id"] not in event["skill_ids"] or not criterion
                    or criterion["skill_id"] != course_task_binding["skill_id"]):
                raise EvidenceContractError("Синтетическая связь курса не совпадает с подтверждённым критерием события.")
        event["provenance"]["synthetic_course_task_binding"] = dict(course_task_binding)
    practice_knowledge_ref = provenance.get("practice_knowledge_ref")
    if practice_knowledge_ref is not None:
        fields = {"stable_key", "version", "status"}
        stable_key = practice_knowledge_ref.get("stable_key") if isinstance(practice_knowledge_ref, dict) else None
        version = practice_knowledge_ref.get("version") if isinstance(practice_knowledge_ref, dict) else None
        status = practice_knowledge_ref.get("status") if isinstance(practice_knowledge_ref, dict) else None
        if (event["source_module"] != "ai_practice"
                or not isinstance(practice_knowledge_ref, dict)
                or set(practice_knowledge_ref) != fields
                or not isinstance(stable_key, str)
                or not re.fullmatch(r"ege\.inf\.[a-z0-9.-]{1,140}", stable_key)
                or type(version) is not int or version <= 0
                or status not in {"source_checked", "reviewed", "approved"}
                or stable_key not in event["topic_ids"]):
            raise EvidenceContractError("Привязка упражнения к Knowledge Base содержит недопустимые значения.")
        event["provenance"]["practice_knowledge_ref"] = dict(practice_knowledge_ref)
    platform_refs = raw.get("platform_refs")
    if platform_refs is not None:
        if event["source_module"] != "ai_homework" or not isinstance(platform_refs, dict):
            raise EvidenceContractError("platform_refs допустим только для AI Homework и должен быть объектом.")
        normalized_refs = {}
        required_refs = ("submission_id", "assignment_id", "assignment_task_id", "task_id", "student_id")
        optional_refs = (
            "attempt_id", "review_id", "code_judge_test_set_id", "code_judge_test_set_version",
            "rubric_version", "course_id", "lesson_id",
        )
        for key in required_refs + optional_refs:
            value = platform_refs.get(key)
            if value is None and key in optional_refs:
                normalized_refs[key] = None
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise EvidenceContractError(f"platform_refs.{key} должен быть положительным целым числом.")
            normalized_refs[key] = value
        code_judge_ids = ("code_judge_test_set_id", "code_judge_test_set_version", "rubric_version")
        if any(normalized_refs[key] is not None for key in code_judge_ids) and not all(
                normalized_refs[key] is not None for key in code_judge_ids):
            raise EvidenceContractError("Поля Code Judge в platform_refs должны задаваться вместе.")
        if selection_fields_present and (
                normalized_refs.get("student_id") != course_task_binding["student_id"]
                or normalized_refs.get("course_id") != course_task_binding["course_id"]
                or normalized_refs.get("lesson_id") != course_task_binding["lesson_id"]
                or normalized_refs.get("task_id") != course_task_binding["task_id"]):
            raise EvidenceContractError("Повторное задание не совпадает с атрибуцией ученика, курса или урока.")
        event["platform_refs"] = normalized_refs
    elif selection_fields_present:
        raise EvidenceContractError("Для выбранного повторного задания обязательны ссылки на отправленную работу.")
    return {"contract_version": EVIDENCE_CONTRACT_VERSION, **event}


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise EvidenceContractError(f"Поле «{field}» должно быть списком непустых строк.")
    return list(dict.fromkeys(item.strip() for item in value))


def validate_lesson_intelligence_output(raw: Any) -> dict[str, Any]:
    """Validate the future lesson-analysis output contract; accepts synthetic text only."""
    if not isinstance(raw, dict):
        raise EvidenceContractError("Результат анализа урока должен быть JSON-объектом.")
    if raw.get("contract_version") != LESSON_INTELLIGENCE_CONTRACT_VERSION:
        raise EvidenceContractError("Неизвестная версия контракта анализа урока.")
    lesson_id = raw.get("lesson_id")
    version = raw.get("lesson_version")
    if not isinstance(lesson_id, str) or not lesson_id.strip():
        raise EvidenceContractError("Укажите стабильный lesson_id.")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise EvidenceContractError("lesson_version должна быть положительной.")
    source = raw.get("source")
    if not isinstance(source, dict) or source.get("kind") != "synthetic_text":
        raise EvidenceContractError("Пока разрешён только синтетический текст урока; аудио и LiveKit не подключены.")
    source_ref = source.get("ref")
    if not isinstance(source_ref, str) or not source_ref.strip():
        raise EvidenceContractError("Укажите ссылку на синтетический источник.")
    verification = raw.get("verification_status")
    if verification not in EVIDENCE_STATUSES:
        raise EvidenceContractError("Укажите корректный статус проверки анализа урока.")
    summary = raw.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise EvidenceContractError("Укажите краткое содержание урока.")

    def records(field: str, required: tuple[str, ...]) -> list[dict[str, Any]]:
        values = raw.get(field, [])
        if not isinstance(values, list):
            raise EvidenceContractError(f"Поле «{field}» должно быть списком.")
        result = []
        seen = set()
        for index, item in enumerate(values, 1):
            if not isinstance(item, dict):
                raise EvidenceContractError(f"Элемент {field} №{index} должен быть объектом.")
            normalized = {}
            for key in required:
                value = item.get(key)
                if not isinstance(value, str) or not value.strip():
                    raise EvidenceContractError(f"Укажите {field}[{index}].{key}.")
                if key == "evidence_status" and value not in EVIDENCE_STATUSES:
                    raise EvidenceContractError(f"{field}[{index}].evidence_status содержит неизвестный статус.")
                normalized[key] = value.strip()
            if field == "topics" and item.get("topic_aliases") is not None:
                normalized["topic_aliases"] = _string_list(item["topic_aliases"], f"{field}[{index}].topic_aliases")
            if field == "topics":
                id_resolution_status = item.get("id_resolution_status")
                if id_resolution_status is not None:
                    if not isinstance(id_resolution_status, str) or not id_resolution_status.strip():
                        raise EvidenceContractError(f"{field}[{index}].id_resolution_status должен быть непустой строкой.")
                    normalized["id_resolution_status"] = id_resolution_status.strip()
                variants = item.get("title_variants")
                if variants is not None:
                    normalized["title_variants"] = _string_list(variants, f"{field}[{index}].title_variants")
                conflict = item.get("title_conflict")
                if conflict is not None:
                    if not isinstance(conflict, bool):
                        raise EvidenceContractError(f"{field}[{index}].title_conflict должен быть логическим значением.")
                    normalized["title_conflict"] = conflict
            source_refs = item.get("source_refs")
            if source_refs is not None:
                normalized["source_refs"] = _string_list(source_refs, f"{field}[{index}].source_refs")
            else:
                normalized["source_refs"] = [normalized["source_ref"]]
            if field == "observed_difficulties":
                for key in ("skill_facet_id", "technical_support_status", "semantic_support_status", "semantic_support_reason"):
                    value = item.get(key)
                    if value is not None:
                        if not isinstance(value, str) or not value.strip():
                            raise EvidenceContractError(f"{field}[{index}].{key} должен быть непустой строкой.")
                        normalized[key] = value.strip()
                variants = item.get("description_variants")
                if variants is not None:
                    normalized["description_variants"] = _string_list(variants, f"{field}[{index}].description_variants")
                observation_id = item.get("observation_id")
                if observation_id is not None:
                    if not isinstance(observation_id, str) or not observation_id.strip():
                        raise EvidenceContractError(f"{field}[{index}].observation_id должен быть непустой строкой.")
                    normalized["observation_id"] = observation_id.strip()
                review_status = item.get("review_status")
                if review_status is not None:
                    if review_status not in {"pending", "confirmed", "rejected", "resolution_candidate"}:
                        raise EvidenceContractError(f"{field}[{index}].review_status содержит неизвестный статус.")
                    normalized["review_status"] = review_status
                resolution_status = item.get("resolution_status")
                if resolution_status is not None:
                    if resolution_status not in {
                        "unresolved_or_unknown", "corrected_after_hint", "partial_progress",
                        "independent_application_candidate", "durable_mastery_candidate",
                        "verbal_claim_only", "resolved_in_lesson", "insufficient_evidence",
                    }:
                        raise EvidenceContractError(f"{field}[{index}].resolution_status содержит неизвестный статус.")
                    normalized["resolution_status"] = resolution_status
                resolution_refs = item.get("resolution_source_refs")
                if resolution_refs is not None:
                    normalized["resolution_source_refs"] = _string_list(resolution_refs, f"{field}[{index}].resolution_source_refs")
                durability_status = item.get("durability_status")
                if durability_status is not None:
                    if durability_status not in {"not_established", "candidate_requires_manual_review", "manually_confirmed"}:
                        raise EvidenceContractError(f"{field}[{index}].durability_status содержит неизвестный статус.")
                    normalized["durability_status"] = durability_status
                progress_evidence = item.get("progress_evidence")
                if progress_evidence is not None:
                    if not isinstance(progress_evidence, list) or any(not isinstance(value, dict) for value in progress_evidence):
                        raise EvidenceContractError(f"{field}[{index}].progress_evidence должен быть списком объектов.")
                    normalized["progress_evidence"] = progress_evidence
            identity = normalized.get("observation_id") or normalized[required[0]]
            if identity in seen:
                raise EvidenceContractError(f"В {field} повторяется идентификатор «{identity}».")
            seen.add(identity)
            result.append(normalized)
        return result

    unsupported = raw.get("unsubstantiated_observations", [])
    if not isinstance(unsupported, list):
        raise EvidenceContractError("Поле «unsubstantiated_observations» должно быть списком.")
    unsubstantiated = []
    for index, item in enumerate(unsupported, 1):
        if not isinstance(item, dict) or any(not isinstance(item.get(key), str) or not item[key].strip()
                                              for key in ("skill_id", "description", "reason")):
            raise EvidenceContractError(f"Неподтверждённое наблюдение №{index} имеет неверный формат.")
        unsubstantiated.append({"skill_id": item["skill_id"].strip(), "description": item["description"].strip(),
                                "reason": item["reason"].strip(),
                                "source_refs": _string_list(item.get("source_refs", []), f"unsubstantiated_observations[{index}].source_refs")})
    result = {
        "contract_version": LESSON_INTELLIGENCE_CONTRACT_VERSION,
        "lesson_id": lesson_id.strip(),
        "lesson_version": version,
        "topics": records("topics", ("topic_id", "title", "evidence_status", "source_ref")),
        "content_segments": records("content_segments", ("segment_id", "summary", "evidence_status", "source_ref")),
        "observed_difficulties": records("observed_difficulties", ("skill_id", "description", "evidence_status", "source_ref")),
        "unsubstantiated_observations": unsubstantiated,
        "summary": summary.strip(),
        "source": {"kind": "synthetic_text", "ref": source_ref.strip()},
        "verification_status": verification,
        "limitations": _string_list(raw.get("limitations", []), "limitations"),
    }
    for count_key in ("completed_chunks", "total_chunks"):
        value = raw.get(count_key)
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise EvidenceContractError(f"Поле «{count_key}» должно быть неотрицательным целым числом.")
            result[count_key] = value
    return result
