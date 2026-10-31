"""Read-only analytics over typed AI Lab learning evidence."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import logging
from math import isfinite
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from sqlalchemy import func

from app.ai_lab.learning_evidence import (
    EVIDENCE_CONTRACT_VERSION,
    EVIDENCE_STATUSES,
    EvidenceContractError,
    merge_evidence_events,
    validate_evidence_event,
)

COURSE_ANALYSIS_CONTRACT_VERSION = "boostudy.course-analysis-input.v1"
CONFIRMED = {"technical_confirmed", "expert_confirmed"}
SYNTHETIC_TUTORCORE_FIXTURE_PREFIX = "boostudy.synthetic.tutorcore31.v1/"
SYNTHETIC_TUTORCORE_KNOWLEDGE_KEYS = {
    "sql-relational-query": "ege.inf.sql-relational-query.v1",
    "game-strategy-initial": "ege.inf.game-strategy.v1",
    "game-strategy-transfer": "ege.inf.game-strategy.v1",
    "data-quality-manual": "ege.inf.data-quality-pipeline.v1",
}
_MOSCOW_TZ = ZoneInfo("Europe/Moscow")
_logger = logging.getLogger(__name__)


def _evidence_timestamp(value: Any, *, naive_timezone=timezone.utc) -> datetime | None:
    """Normalize a stored timestamp using the source model's documented timezone."""
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=naive_timezone)
    return value


def _timestamp_context(event_time_source: str, event_time: datetime, *, timestamps: dict[str, Any],
                       context_only: tuple[str, ...] = (),
                       field_interpretations: dict[str, str] | None = None) -> dict[str, Any]:
    """Keep activity, scheduling, publication and review times separate in provenance."""
    normalized = {}
    for name, value in timestamps.items():
        stamp = _evidence_timestamp(value, naive_timezone=(
            _MOSCOW_TZ if name in {"lesson_task_attempt_submitted_at", "lesson_task_planned_at"}
            else timezone.utc
        ))
        normalized[name] = stamp.isoformat() if stamp else None
    return {
        "event_time_source": event_time_source,
        "timestamps": normalized,
        "context_only": list(context_only),
        "field_interpretations": dict(field_interpretations or {}),
    }


def _submission_activity_time(submission: Any, attempt_no: int, *, answer: Any = None):
    """Return the best actual submission timestamp, never assignment/review creation time."""
    if answer is not None:
        answer_time = _evidence_timestamp(getattr(answer, "submitted_separately_at", None))
        if answer_time:
            return answer_time, "answer.submitted_separately_at"
    matching_attempt = next((item for item in (getattr(submission, "attempts", None) or [])
                             if int(getattr(item, "attempt_no", 0) or 0) == int(attempt_no)), None)
    if matching_attempt is not None:
        attempt_time = _evidence_timestamp(getattr(matching_attempt, "submitted_at", None))
        if attempt_time:
            return attempt_time, "submission_attempt.submitted_at"
    submission_time = _evidence_timestamp(getattr(submission, "submitted_at", None))
    if submission_time:
        return submission_time, "submission.submitted_at"
    return None, None


def _planned_activity_time_status(planned_at: datetime | None, occurred_at: datetime,
                                  *, inherited: bool = False) -> str:
    if planned_at is None:
        return "missing"
    if planned_at > occurred_at:
        return "conflicting"
    return "inherited_template" if inherited else "source_record"


def _classwork_planned_date_status(lesson_task: Any, lesson: Any, occurred_at: datetime) -> str:
    """Classify a LessonTask date as planning metadata, never as learner activity."""
    planned = _evidence_timestamp(getattr(lesson_task, "date_assigned", None), naive_timezone=_MOSCOW_TZ)
    if planned is None:
        return _planned_activity_time_status(None, occurred_at)
    try:
        from core.db_models import LearningTrajectory, Lesson, LessonTask, db
        course = db.session.get(LearningTrajectory, int(lesson.learning_trajectory_id or 0))
        if course and course.parent_course_id:
            source_lesson = Lesson.query.filter_by(
                learning_trajectory_id=int(course.parent_course_id),
                course_order_index=int(lesson.course_order_index or 0),
            ).filter(Lesson.student_id.is_(None)).first()
            source_task = (LessonTask.query.filter_by(
                lesson_id=int(source_lesson.lesson_id),
                task_id=int(lesson_task.task_id),
                assignment_type=str(lesson_task.assignment_type or ""),
            ).first() if source_lesson else None)
            source_date = _evidence_timestamp(
                getattr(source_task, "date_assigned", None), naive_timezone=_MOSCOW_TZ,
            )
            if source_date and source_date == planned:
                return _planned_activity_time_status(planned, occurred_at, inherited=True)
    except (TypeError, ValueError, AttributeError):
        return "source_record_unverified"
    return _planned_activity_time_status(planned, occurred_at)


def synthetic_demo_events() -> list[dict[str, Any]]:
    """Small, explicitly synthetic evidence set for local UI and pipeline demos."""
    return [
        _demo_event("edge-case-learner", "demo-sum-multiples", "Условия и границы", "python.boundary_cases", 2, 3,
                    "synthetic.sum-multiples-of-three", "boundary.upper_inclusive", "Не учтено включение правой границы."),
        _demo_event("edge-case-learner", "demo-vowel-count", "Строки и циклы", "python.boundary_cases", 2, 3,
                    "synthetic.ascii-vowel-count", "boundary.empty_input", "Пустая строка не обработана как допустимый вход."),
        _demo_event("edge-case-learner", "demo-clamp-list", "Функции и границы", "python.boundary_cases", 2, 3,
                    "synthetic.clamp-list", "boundary.upper_inclusive", "Верхняя граница обрезки проверяется неверно."),
        _demo_event("edge-case-learner", "demo-loop-success", "Циклы", "python.iteration", 3, 3,
                    "synthetic.sum-multiples-of-three", None, "Цикл корректно проходит весь заданный диапазон."),
        _demo_event("steady-learner", "demo-steady-sum", "Арифметика и условия", "python.boundary_cases", 3, 3,
                    "synthetic.sum-multiples-of-three", None, "Пограничные значения подтверждены тестами."),
        _demo_event("steady-learner", "demo-steady-vowels", "Строки и циклы", "python.iteration", 3, 3,
                    "synthetic.ascii-vowel-count", None, "Все проверки обработки строки пройдены."),
        _demo_event("steady-learner", "demo-steady-clamp", "Функции и границы", "python.functions", 3, 3,
                    "synthetic.clamp-list", None, "Функция возвращает ожидаемый составной результат."),
    ]


def _demo_event(subject_id, event_id, topic, skill_id, score, maximum, assignment_id, error_code, reason):
    failed = error_code is not None
    return {
        "contract_version": EVIDENCE_CONTRACT_VERSION,
        "event_id": event_id,
        "subject_id": subject_id,
        "source_module": "ai_homework",
        "source_record_id": event_id,
        "occurred_at": "2026-10-18T12:00:00+07:00",
        "evidence_status": "technical_confirmed",
        "assignment": {"id": assignment_id, "version": 2},
        "topic_ids": [topic.lower().replace(" ", "-")],
        "skill_ids": [skill_id],
        "error_codes": [error_code] if error_code else [],
        "limitations": ["Синтетический пример; конечный набор тестов не доказывает корректность для всех входов."],
        "outcome": {"score": score, "maximum": maximum, "status": "partial" if failed else "complete"},
        "criteria": [{
            "criterion_id": skill_id,
            "skill_id": skill_id,
            "earned": score,
            "maximum": maximum,
            "status": "not_met" if failed else "met",
            "evidence_status": "technical_confirmed",
            "reason": reason,
            "source_refs": [event_id],
        }],
        "provenance": {"source_ref": event_id, "method": "синтетический пример Code Judge"},
    }


def evidence_from_homework_experiment(experiment: Any, *, subject_id: str | None = None) -> dict[str, Any] | None:
    """Project an isolated AI Lab experiment into the common evidence contract."""
    if getattr(experiment, "status", None) != "succeeded":
        return None
    scenario_id = str(getattr(experiment, "scenario_id", "") or "")
    if not scenario_id:
        return None
    scenario = getattr(experiment, "scenario_snapshot", None) or {}
    input_snapshot = getattr(experiment, "input_snapshot", None) or {}
    quality = getattr(experiment, "quality_json", None) or {}
    result = getattr(experiment, "result_json", None) or {}
    technical = quality.get("technical") or {}
    code_judge = technical.get("code_judge") or {}
    rubric = code_judge.get("rubric") if isinstance(code_judge.get("rubric"), dict) else {}
    confirmed = bool(code_judge)
    event_status = "technical_confirmed" if confirmed else "ai_inference"
    code = str(input_snapshot.get("student_solution") or "")
    import hashlib

    subject_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()[:12] if code else f"run-{experiment.id}"
    assignment_id = str(scenario.get("assignment_id") or scenario_id)
    assignment_version = scenario.get("assignment_version")
    if isinstance(assignment_version, bool) or not isinstance(assignment_version, int) or assignment_version < 1:
        assignment_version = 1
    now = getattr(experiment, "created_at", None) or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    source_criteria = (rubric.get("criteria") or code_judge.get("criteria")) if confirmed else (
        result.get("criterion_scores") or result.get("criteria")
    )
    criteria = []
    error_codes = []
    scenario_criteria = {
        str(item.get("id") or item.get("assignment_criterion_id")): str(item.get("skill_id")).strip()
        for item in (scenario.get("assignment_criteria") or [])
        if isinstance(item, dict) and item.get("skill_id")
    }
    if any(str(item.get("id") or item.get("assignment_criterion_id")) not in scenario_criteria
           for item in (scenario.get("assignment_criteria") or []) if isinstance(item, dict)):
        from app.ai_lab.scenarios import get_python_assignment_source

        canonical = get_python_assignment_source(assignment_id, assignment_version)
        canonical_scenario = canonical.get("scenario") if canonical else None
        scenario_criteria.update({
            str(item.get("id") or item.get("assignment_criterion_id")): str(item["skill_id"]).strip()
            for item in (canonical_scenario or {}).get("assignment_criteria", [])
            if isinstance(item, dict) and item.get("skill_id")
        })
    for index, item in enumerate(source_criteria or [], 1):
        if not isinstance(item, dict):
            continue
        criterion_id = str(item.get("assignment_criterion_id") or item.get("id") or item.get("criterion_id") or f"criterion-{index}")
        maximum = item.get("max_score", item.get("maximum"))
        earned = item.get("score_awarded", item.get("earned", item.get("score")))
        status = item.get("status")
        if status == "insufficient_data" or earned is None:
            criterion_status, earned = "insufficient_data", None
        else:
            try:
                criterion_status = "met" if float(earned) >= float(maximum) else "not_met"
            except (TypeError, ValueError):
                criterion_status, earned = "insufficient_data", None
        if criterion_status == "not_met":
            error_codes.append(criterion_id)
        criteria.append({
            "criterion_id": criterion_id,
            "skill_id": scenario_criteria.get(criterion_id),
            "earned": earned,
            "maximum": maximum,
            "status": criterion_status,
            "evidence_status": event_status,
            "reason": str(item.get("rationale") or item.get("reason") or "Баллы по критерию взяты из сохранённого результата AI Lab."),
            "source_refs": [f"ai-lab-experiment:{experiment.id}"],
        })

    score = (rubric.get("confirmed_score", code_judge.get("score_awarded"))
             if confirmed else result.get("score_awarded"))
    maximum = (rubric.get("max_score", code_judge.get("max_score"))
               if confirmed else result.get("max_score"))
    if maximum is None:
        maximum = scenario.get("max_score")
    score = score if isinstance(score, (int, float)) and not isinstance(score, bool) else None
    maximum = maximum if isinstance(maximum, (int, float)) and not isinstance(maximum, bool) else None
    topic = str(scenario.get("topic") or "")
    skill_ids = list(dict.fromkeys(item["skill_id"] for item in criteria if item.get("skill_id")))
    occurred_at = now.isoformat()
    saved_subject_id = scenario.get("synthetic_subject_id")
    selected_subject_id = subject_id or saved_subject_id
    if (not isinstance(selected_subject_id, str) or not selected_subject_id.startswith("synthetic-")
            or len(selected_subject_id) > 100
            or any(not (char.isalnum() or char in "._-") for char in selected_subject_id)):
        selected_subject_id = f"synthetic-answer:{scenario_id}:{subject_hash}"
    raw = {
        "contract_version": EVIDENCE_CONTRACT_VERSION,
        "event_id": f"ai-lab-experiment:{experiment.id}",
        "subject_id": selected_subject_id,
        "source_module": "ai_homework",
        "source_record_id": f"ai-lab-experiment:{experiment.id}",
        "occurred_at": occurred_at,
        "evidence_status": event_status,
        "assignment": {"id": assignment_id, "version": assignment_version},
        "topic_ids": [topic] if topic else [],
        "skill_ids": skill_ids,
        "error_codes": error_codes,
        "limitations": ["AI Lab использует синтетические задания.", "Конечный набор тестов не является математическим доказательством общей корректности."] if confirmed else ["Оценка основана на выводе модели без подтверждения Code Judge."],
        "outcome": {"score": score, "maximum": maximum, "status": str(result.get("grading_status") or "unknown")},
        "criteria": criteria,
        "provenance": {
            "source_ref": f"ai-lab-experiment:{experiment.id}",
            "model": str(getattr(experiment, "model", "") or ""),
            "method": "Code Judge + AI Homework" if confirmed else "AI Homework inference",
        },
    }
    return validate_evidence_event(raw)


def build_analytics_snapshot(raw_events: Iterable[dict[str, Any]], subject_id: str | None = None) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    issues = []
    for raw in raw_events:
        try:
            event = validate_evidence_event(raw)
        except EvidenceContractError as exc:
            issues.append(str(exc))
            continue
        if subject_id is None or event["subject_id"] == subject_id:
            events.append(event)

    skill_events: dict[str, list[tuple[dict[str, Any], dict[str, Any] | None]]] = defaultdict(list)
    topics: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        mapped_skills = set()
        for criterion in event["criteria"]:
            skill_id = criterion.get("skill_id")
            if skill_id:
                skill_events[skill_id].append((event, criterion))
                mapped_skills.add(skill_id)
        for skill_id in event["skill_ids"]:
            if skill_id not in mapped_skills:
                skill_events[skill_id].append((event, None))
        for topic_id in event["topic_ids"]:
            topics[topic_id].append(event)

    skills = []
    recurring_errors = []
    for skill_id, rows in sorted(skill_events.items()):
        confirmed_rows = [(event, criterion) for event, criterion in rows
                          if event["evidence_status"] in CONFIRMED and criterion
                          and criterion["evidence_status"] in CONFIRMED
                          and criterion["status"] in {"met", "not_met"}]
        failures = [(event, criterion) for event, criterion in confirmed_rows if criterion["status"] == "not_met"]
        qualitative_rows = [(event, criterion) for event, criterion in rows
                            if criterion and criterion["status"] == "insufficient_data"
                            and event["source_module"] == "ai_lesson_intelligence"
                            and event["evidence_status"] in CONFIRMED
                            and criterion["evidence_status"] in CONFIRMED]
        failed_error_assignments: dict[str, set[str]] = defaultdict(set)
        for event, _ in failures:
            assignment = event.get("assignment")
            if not assignment:
                continue
            for code in event["error_codes"]:
                failed_error_assignments[code].add(assignment["id"])
        repeated_error_codes = {
            code for code, assignment_ids in failed_error_assignments.items()
            if len(assignment_ids) >= 2
        }
        assignments = {event["assignment"]["id"] for event, _ in confirmed_rows if event["assignment"]}
        if len(confirmed_rows) >= 3 and len(assignments) >= 2:
            # A repeated code is only a pattern in checker output. It cannot
            # establish why the learner was wrong, so all mixed results stay
            # provisional and require a pedagogical diagnostic.
            status = "demonstrated" if not failures else "developing"
        else:
            status = "insufficient_data"
        error_counts: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event, _ in failures:
            for code in event["error_codes"]:
                error_counts[code].append(event)
        for code, sources in error_counts.items():
            assignments_for_error = {event["assignment"]["id"] for event in sources if event["assignment"]}
            if len(sources) >= 2 and len(assignments_for_error) >= 2:
                recurring_errors.append({
                    "skill_id": skill_id,
                    "code": code,
                    "count": len(sources),
                    "assignment_count": len(assignments_for_error),
                    "source_refs": [event["provenance"].get("source_ref") or event["event_id"] for event in sources],
                    "evidence_status": "technical_confirmed",
                })
        skills.append({
            "skill_id": skill_id,
            "status": status,
            "status_label": {
                "needs_support": "Есть сигнал для педагогической проверки",
                "demonstrated": "Успех подтверждён в проверенных заданиях",
                "developing": "Результаты смешанные; причина затруднения не установлена",
                "insufficient_data": "Недостаточно данных",
            }[status],
            "confirmed_evidence": len(confirmed_rows),
            "assignment_count": len(assignments),
            "met": sum(criterion["status"] == "met" for _, criterion in confirmed_rows),
            "not_met": len(failures),
            "technical_correct_attempts": sum(criterion["status"] == "met" for _, criterion in confirmed_rows),
            "technical_incorrect_attempts": len(failures),
            "observed_difficulty": bool(failures),
            "diagnostic_recommended": status in {"needs_support", "developing", "insufficient_data"},
            "mastery_confirmed": False,
            "repeated_error_codes": sorted(repeated_error_codes),
            "diagnostic_hypothesis": (
                "repeated_error_pattern" if repeated_error_codes else
                "mixed_technical_outcomes" if failures else "no_failure_observed"
            ),
            "diagnostic_hypothesis_confirmed": False,
            "error_cause_confirmed": False,
            "uncertain_evidence": sum(
                1 for event, criterion in rows
                if not criterion or event["evidence_status"] not in CONFIRMED or criterion["evidence_status"] not in CONFIRMED
            ),
            "single_error_warning": bool(failures) and len(failures) < 2,
            "source_refs": list(dict.fromkeys(event["provenance"].get("source_ref") or event["event_id"] for event, _ in confirmed_rows)),
            "qualitative_observations": len(qualitative_rows),
            "qualitative_source_refs": list(dict.fromkeys(
                event["provenance"].get("source_ref") or event["event_id"] for event, _ in qualitative_rows
            )),
        })

    known_skills = {skill["skill_id"] for skill in skills}
    trends = []
    for skill_id in sorted(known_skills):
        rows = sorted([
            (event, criterion) for event, criterion in skill_events[skill_id]
            if criterion and criterion["status"] in {"met", "not_met"}
            and event["evidence_status"] in CONFIRMED and criterion["evidence_status"] in CONFIRMED
        ], key=lambda pair: pair[0]["occurred_at"])
        if len(rows) >= 4:
            split = len(rows) // 2
            first = sum(pair[1]["status"] == "met" for pair in rows[:split]) / split
            later = rows[split:]
            second = sum(pair[1]["status"] == "met" for pair in later) / len(later)
            trends.append({"skill_id": skill_id, "direction": "improving" if second > first else "declining" if second < first else "stable",
                           "sample": len(rows), "first_rate": round(first, 2), "later_rate": round(second, 2)})

    return {
        "subject_id": subject_id,
        "events": len(events),
        "confirmed_events": sum(event["evidence_status"] in CONFIRMED for event in events),
        "confirmed_lesson_observations": sum(
            1 for event in events if event["source_module"] == "ai_lesson_intelligence"
            and event["evidence_status"] in CONFIRMED
        ),
        "skills": skills,
        "topics": [{"topic_id": key, "events": len(value), "confirmed": sum(item["evidence_status"] in CONFIRMED for item in value)} for key, value in sorted(topics.items())],
        "recurring_errors": recurring_errors,
        "trends": trends,
        "uncertainty": {"events_without_confirmation": sum(event["evidence_status"] not in CONFIRMED for event in events), "invalid_events": len(issues), "validation_messages": issues[:10]},
        "method": {
            "confirmed_statuses": sorted(CONFIRMED),
            "minimum_for_skill_state": "3 подтверждённых наблюдения по критерию в 2 разных заданиях",
            "minimum_for_recurring_error": "2 подтверждённых случая в 2 разных заданиях с одинаковым error_code",
            "single_error_rule": "Единичная ошибка не интерпретируется как отсутствие навыка.",
        },
    }


def course_analysis_input(raw_events: Iterable[dict[str, Any]], subject_id: str) -> dict[str, Any]:
    """Read-only, versioned input contract for future course analysis."""
    events = []
    for raw in raw_events:
        event = validate_evidence_event(raw)
        if event["subject_id"] == subject_id:
            events.append(event)
    return {
        "contract_version": COURSE_ANALYSIS_CONTRACT_VERSION,
        "mode": "read_only",
        "subject_id": subject_id,
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "evidence": events,
        "limitations": ["Контракт не разрешает создавать задания или изменять траекторию курса."],
    }


def synthetic_profiles(raw_events: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    subjects = sorted({event["subject_id"] for event in raw_events})
    labels = {"edge-case-learner": "Синтетический профиль · пограничные случаи", "steady-learner": "Синтетический профиль · устойчивое решение"}
    return [{"id": subject, "label": labels.get(subject, f"Синтетический профиль · {subject}")} for subject in subjects]


def stored_homework_evidence(
    limit: int | None = None, batch_size: int = 200, *, actor_user_id: int | None = None
) -> list[dict[str, Any]]:
    """Read all saved AI Lab evidence in bounded DB pages; never reads submissions.

    ``limit`` is an optional cap for callers that explicitly need a sample. Analytics
    defaults to the complete saved history and does not inherit the UI history page size.
    """
    from core.db_models import AiLabExperiment, db

    page_size = max(1, min(int(batch_size), 1_000))
    remaining = None if limit is None else max(0, int(limit))
    upper_id = db.session.query(func.max(AiLabExperiment.id)).scalar() or 0
    last_id = 0
    evidence = []
    while last_id < upper_id and (remaining is None or remaining > 0):
        query = AiLabExperiment.query.filter(
            AiLabExperiment.status == "succeeded", AiLabExperiment.id > last_id,
            AiLabExperiment.id <= upper_id,
        )
        if actor_user_id is not None:
            query = query.filter(AiLabExperiment.actor_user_id == int(actor_user_id))
        records = (query.order_by(AiLabExperiment.id.asc())
                   .limit(page_size if remaining is None else min(page_size, remaining))
                   .all())
        if not records:
            break
        for record in records:
            # Rebuild this derived projection from the immutable experiment snapshot.
            # Older records may have cached an incomplete projection from the former
            # flat Code Judge shape; never rewrite their historical experiment rows.
            item = evidence_from_homework_experiment(record)
            if item:
                evidence.append(item)
        last_id = records[-1].id
        if remaining is not None:
            remaining -= len(records)
    return evidence


def _confirmed_code_judge_report(review_status: str, technical: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Accept only a complete, internally consistent report from the sandbox Runner."""
    rubric = technical.get("rubric") if isinstance(technical.get("rubric"), dict) else {}
    if (review_status not in {"completed", "unavailable"}
            or technical.get("report_type") != "platform_code_judge_evidence_v1"
            or technical.get("status") != "completed"
            or technical.get("run_status") != "complete"):
        return False, rubric

    def number(value: Any) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
            return None
        return float(value)

    test_set_id = technical.get("test_set_id")
    test_set_version = technical.get("test_set_version")
    rubric_version = technical.get("rubric_version")
    passed, failed, total = (technical.get(key) for key in ("passed", "failed", "total"))
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in
               (test_set_id, test_set_version, rubric_version, passed, failed, total)):
        return False, rubric
    if min(test_set_id, test_set_version, rubric_version) < 1 or total < 1 or passed < 0 or failed < 0 or passed + failed != total:
        return False, rubric

    score = number(rubric.get("confirmed_score"))
    confirmed_max = number(rubric.get("confirmed_max_score"))
    maximum = number(rubric.get("max_score"))
    unconfirmed = number(rubric.get("unconfirmed_max_score"))
    criteria = rubric.get("criteria")
    if (score is None or confirmed_max is None or maximum is None or maximum <= 0
            or (unconfirmed is not None and unconfirmed != 0)
            or abs(confirmed_max - maximum) > 0.001 or score < 0 or score > maximum
            or not isinstance(criteria, list) or not criteria):
        return False, rubric

    earned_sum = 0.0
    maximum_sum = 0.0
    for criterion in criteria:
        if not isinstance(criterion, dict) or criterion.get("status") not in {"fulfilled", "not_fulfilled", "met", "not_met"}:
            return False, rubric
        earned = number(criterion.get("score_awarded"))
        criterion_max = number(criterion.get("max_score"))
        if earned is None or criterion_max is None or criterion_max < 0 or earned < 0 or earned > criterion_max:
            return False, rubric
        earned_sum += earned
        maximum_sum += criterion_max
    if abs(earned_sum - score) > 0.001 or abs(maximum_sum - confirmed_max) > 0.001:
        return False, rubric
    return True, rubric


def _synthetic_master_task_link(task, binding: dict[str, Any], course, lesson):
    """Match a draft task from an allowlisted master to its structurally identical copy lesson."""
    from app.ai_lab.course_adapter import _allowed_course_ids, _allowed_copy_ids
    from app.ai_lab.platform_homework import _task_fingerprint
    from core.db_models import LearningTrajectory, Lesson, LessonTask, db

    if (not course or course.is_template or not course.parent_course_id
            or int(course.course_id) not in _allowed_copy_ids()
            or int(course.parent_course_id) not in _allowed_course_ids()):
        return None
    try:
        source_course_id = int(binding.get("source_course_id"))
        source_version = int(binding.get("source_course_version"))
        source_lesson_id = int(binding.get("source_lesson_id"))
        source_order = int(binding.get("source_lesson_order_index"))
    except (TypeError, ValueError):
        return None
    source_course = db.session.get(LearningTrajectory, source_course_id)
    source_lesson = db.session.get(Lesson, source_lesson_id)
    if (source_course_id != int(course.parent_course_id)
            or source_course_id not in _allowed_course_ids()
            or not source_course or not source_course.is_template or source_course.student_id is not None
            or str(source_course.status or "").casefold() != "active"
            or int(source_course.current_version or 1) != source_version
            or not source_lesson or int(source_lesson.learning_trajectory_id or 0) != source_course_id
            or source_lesson.student_id is not None
            or int(source_lesson.course_order_index or 0) != source_order
            or int(lesson.course_order_index or 0) != source_order):
        return None
    def curriculum_scenario(value: Any) -> str | None:
        try:
            parsed = json.loads(value or "{}") if isinstance(value, str) else value
        except (TypeError, ValueError):
            return None
        if not isinstance(parsed, dict):
            return None
        normalized = dict(parsed)
        # Teacher-only overlays are versioned separately and do not rewrite the
        # underlying lesson objective, criteria, exercises, or checker contract.
        for key in ("adaptation_history", "tutor_core_adaptive_focus", "teacher_focus"):
            normalized.pop(key, None)
        exercises = normalized.get("exercises")
        if isinstance(exercises, list):
            # Moving an unchanged, exactly bound task between classwork and
            # homework changes its delivery sequence, not its assessed meaning.
            normalized["exercises"] = [
                ({key: value for key, value in item.items() if key != "role"}
                 if isinstance(item, dict) else item)
                for item in exercises
            ]
        return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    same_lesson = (
        all(getattr(source_lesson, field) == getattr(lesson, field)
            for field in ("topic", "content", "homework", "duration", "lesson_format"))
        and curriculum_scenario(source_lesson.studio_scenario) is not None
        and curriculum_scenario(source_lesson.studio_scenario) == curriculum_scenario(lesson.studio_scenario)
    )
    if not same_lesson:
        return None
    skill_id = str(binding.get("skill_id") or "")
    topic_code = str(binding.get("topic_code") or "")
    def matching_skill(candidate):
        return next((item for item in (candidate.skills or [])
                     if item.is_active and f"exam-skill:{int(item.skill_id)}" == skill_id
                     and str(item.topic_code or "") == topic_code), None)
    source_skill = matching_skill(source_lesson)
    target_skill = matching_skill(lesson)
    if not source_skill or not target_skill:
        return None
    def criteria_value(skill):
        raw = skill.mastery_criteria
        return raw if isinstance(raw, (dict, list)) else json.loads(raw or "[]")
    try:
        source_criteria = criteria_value(source_skill)
        target_criteria = criteria_value(target_skill)
    except (TypeError, ValueError):
        return None
    if json.dumps(source_criteria, sort_keys=True, ensure_ascii=False) != json.dumps(
            target_criteria, sort_keys=True, ensure_ascii=False):
        return None
    criterion_id = str(binding.get("criterion_id") or "")
    if (not isinstance(target_criteria, list)
            or not any(isinstance(item, dict) and str(item.get("key") or "") == criterion_id
                       for item in target_criteria)):
        return None
    if (binding.get("task_fingerprint") != _task_fingerprint(task)
            or not LessonTask.query.filter_by(lesson_id=source_lesson_id, task_id=task.task_id).first()
            or not LessonTask.query.filter_by(lesson_id=lesson.lesson_id, task_id=task.task_id).first()):
        return None
    return target_skill, criterion_id


def _synthetic_master_task_binding(task, binding: dict[str, Any], lesson_id: int, student,
                                  user_id: int, *, assessment_method: str, expected_answer: Any,
                                  max_score: Any, test_set_id: Any, test_set_version: Any,
                                  rubric_version: Any,
                                  observed_at: datetime | None) -> dict[str, Any] | None:
    from app.ai_lab.course_adapter import (
        compare_course_task_semantics, resolve_assigned_synthetic_copy,
        resolve_course_version_at,
    )
    from core.db_models import Lesson, LearningTrajectory, db

    if (not student or int(student.user_id or 0) != int(user_id)
            or not lesson_id or int(student.student_id or 0) <= 0):
        return None
    resolution = resolve_assigned_synthetic_copy(int(student.student_id))
    copy = resolution.get("copy") if resolution.get("status") == "resolved" else None
    lesson = db.session.get(Lesson, int(lesson_id))
    course = db.session.get(LearningTrajectory, int(lesson.learning_trajectory_id or 0)) if lesson else None
    if (not copy or not lesson or not course or int(copy.course_id) != int(course.course_id)
            or int(copy.student_id or 0) != int(student.student_id)
            or int(lesson.student_id or 0) != int(student.student_id)
            or str(lesson.status or "").casefold() not in {"planned", "scheduled", "in_progress", "completed"}):
        return None
    matched = _synthetic_master_task_link(task, binding, course, lesson)
    if not matched:
        return None
    skill, criterion_id = matched
    version_resolution = resolve_course_version_at(int(course.course_id), observed_at)
    if version_resolution.get("status") != "resolved":
        return None
    source_version = int(version_resolution["course_version"])
    compatibility = compare_course_task_semantics(
        course_id=int(course.course_id), source_version=source_version,
        lesson_id=int(lesson.lesson_id), skill_id=f"exam-skill:{int(skill.skill_id)}",
        criterion_id=criterion_id, task_id=int(task.task_id),
        task_fingerprint=str(binding["task_fingerprint"]),
    )
    task_updated = getattr(task, "updated_at", None)
    if observed_at and task_updated:
        comparable_observed = observed_at.replace(tzinfo=None) if observed_at.tzinfo else observed_at
        comparable_updated = task_updated.replace(tzinfo=None) if task_updated.tzinfo else task_updated
        if comparable_updated > comparable_observed:
            compatibility = {
                "status": "unverified", "matches": [], "mismatches": ["task_changed_after_evidence"],
                "reason": "Задание изменялось после попытки; исторический checker восстановить нельзя.",
            }
    return {
        "contract": "boostudy.synthetic-course-task-binding.v1",
        "course_id": int(course.course_id),
        "course_version": source_version,
        "lesson_id": int(lesson.lesson_id),
        "task_id": int(task.task_id),
        "skill_id": f"exam-skill:{int(skill.skill_id)}",
        "topic_code": str(skill.topic_code),
        "criterion_id": criterion_id,
        "semantic_compatibility": compatibility,
        "assessment_method": str(assessment_method or "method_unrecorded"),
        "task_fingerprint": str(binding["task_fingerprint"]),
        "task_content_sha256": hashlib.sha256(str(task.content_html or "").encode("utf-8")).hexdigest(),
        "checker_fingerprint": _course_checker_fingerprint(
            task, assessment_method, expected_answer, max_score,
            test_set_id, test_set_version, rubric_version,
        ),
        "pedagogical_status": "not_pedagogically_approved",
    }


def _synthetic_tutorcore_fixture_binding(task, assignment, submission, user_id: int) -> dict[str, Any] | None:
    """Resolve only the versioned local acceptance fixture; never treat it as an official task map."""
    from app.ai_lab.platform_homework import _task_fingerprint, _truthy, _value
    from app.ai_lab.provider import is_local_ai_lab_enabled
    from core.db_models import AiLabTutorDemo, Lesson, LearningTrajectory, db

    if (not is_local_ai_lab_enabled() or not _truthy(_value("AI_LAB_PLATFORM_HOMEWORK_ENABLED", "false"))
            or task.bank_category != "synthetic_tutor_core"):
        return None
    source_key = str(task.source_key or "")
    if not source_key.startswith(SYNTHETIC_TUTORCORE_FIXTURE_PREFIX):
        return None
    pieces = source_key[len(SYNTHETIC_TUTORCORE_FIXTURE_PREFIX):].split("/")
    if len(pieces) != 2:
        return None
    run_key, fixture_key = pieces
    knowledge_key = SYNTHETIC_TUTORCORE_KNOWLEDGE_KEYS.get(fixture_key)
    if not knowledge_key:
        return None
    lesson = db.session.get(Lesson, assignment.lesson_id) if assignment and assignment.lesson_id else None
    course = db.session.get(LearningTrajectory, lesson.learning_trajectory_id) if lesson and lesson.learning_trajectory_id else None
    demo = db.session.get(AiLabTutorDemo, run_key)
    if (not lesson or not course or not demo or course.course_id == 3
            or int(course.student_id or 0) != int(submission.student_id)
            or int(lesson.student_id or 0) != int(submission.student_id)
            or int(demo.student_user_id or 0) != int(user_id)
            or int(demo.student_id or 0) != int(submission.student_id)
            or int(demo.course_id or 0) != int(course.course_id)
            or int(lesson.learning_trajectory_id or 0) != int(course.course_id)):
        return None
    try:
        from app.ai_lab.knowledge_base import list_knowledge_entries
        from app.ai_lab.platform_homework import _task_fingerprint

        entry = next((item for item in list_knowledge_entries()
                      if item.get("stable_key") == knowledge_key), None)
        if (not entry or entry.get("status") not in {"source_checked", "approved"}
                or not isinstance(entry.get("content"), dict)
                or task.content_fingerprint != _task_fingerprint(task)):
            return None
        skill_key = str((entry["content"].get("assessed_skill") or {}).get("skill_key") or "")
        if not skill_key:
            return None
    except Exception:
        return None
    return {
        "fixture_run_key": run_key,
        "fixture_key": fixture_key,
        "knowledge_stable_key": knowledge_key,
        "knowledge_version": int(entry["version_no"]),
        "knowledge_title": str(entry["title"]),
        "knowledge_status": str(entry["status"]),
        "knowledge_source_titles": [str(item["title"]) for item in (entry.get("source_refs") or []) if item.get("title")],
        "knowledge_content_sha256": str(entry["content_sha256"]),
        "task_id": int(task.task_id),
        "task_content_sha256": str(task.content_fingerprint),
        "source_key": source_key,
        "course_id": int(course.course_id),
        "course_version": int(course.current_version or 1),
        "lesson_id": int(lesson.lesson_id),
        "skill_key": skill_key,
    }


def _synthetic_tutorcore_assistance(binding: dict[str, Any], submission_id: int,
                                    assignment_task_id: int, attempt_id: int | None) -> dict[str, Any] | None:
    """Accept a single immutable assistance record tied to this exact saved attempt and task."""
    from core.db_models import AiLabTutorDemoEvent

    if attempt_id is None:
        return None
    rows = (AiLabTutorDemoEvent.query
            .filter_by(demo_key=binding["fixture_run_key"], scenario_key="platform_assistance")
            .order_by(AiLabTutorDemoEvent.created_at.asc(), AiLabTutorDemoEvent.event_id.asc()).all())
    matches = []
    for row in rows:
        payload = row.event_json if isinstance(row.event_json, dict) else {}
        if (payload.get("submission_id") == int(submission_id)
                and payload.get("assignment_task_id") == int(assignment_task_id)
                and payload.get("attempt_id") == int(attempt_id)
                and payload.get("task_id") == int(binding["task_id"])):
            assistance = payload.get("assistance")
            if isinstance(assistance, dict):
                matches.append(assistance)
    if len(matches) != 1:
        return None
    return matches[0]


def _synthetic_teacher_selected_shared_review(task, binding: dict[str, Any], course, lesson,
                                             *, actor_user_id: int | None,
                                             assignment=None) -> dict[str, Any] | None:
    """Validate an explicit teacher-selected cross-copy item for shared review only."""
    from app.ai_lab.database_safety import has_verified_safe_ai_lab_db
    from app.ai_lab.course_adapter import (
        _allowed_copy_ids, resolve_assigned_synthetic_copy, resolve_course_version_at,
    )
    from app.ai_lab.platform_homework import (
        _allowlisted_actor_ids, _allowlisted_task_author_ids, _task_fingerprint,
    )
    from core.db_models import AssignmentTask, LearningTrajectory, Lesson, LessonTask, db

    if (not has_verified_safe_ai_lab_db() or not course or course.is_template
            or int(course.course_id) not in _allowed_copy_ids()
            or not course.student_id or not lesson
            or int(lesson.learning_trajectory_id or 0) != int(course.course_id)
            or int(lesson.student_id or 0) != int(course.student_id)
            or int(actor_user_id or 0) not in _allowlisted_actor_ids()
            or not task or int(task.created_by_id or 0) not in _allowlisted_task_author_ids()
            or not str(task.bank_category or "").casefold().startswith("synthetic")
            or not str(task.source_key or "").startswith("boostudy.synthetic.adaptive-v1/")
            or binding.get("contract") != "boostudy.synthetic-course-skill.v1"
            or binding.get("pedagogical_status") != "synthetic_draft_not_expert_approved"
            or binding.get("task_fingerprint") != _task_fingerprint(task)):
        return None

    spec = task.answer_spec if isinstance(task.answer_spec, dict) else {}
    if (spec.get("type") != "short_answer" or spec.get("grading_mode") not in {"exact", "auto"}
            or not str(task.answer or "").strip()):
        return None
    target_link_rows = LessonTask.query.filter_by(
        lesson_id=int(lesson.lesson_id), task_id=int(task.task_id),
        assignment_type="homework", is_error_review=False,
    ).all()
    if len(target_link_rows) != 1:
        return None
    target_link = target_link_rows[0]
    try:
        note = json.loads(str(target_link.notes or "{}"))
    except (TypeError, ValueError):
        return None
    if not isinstance(note, dict):
        return None
    provenance = note.get("source_provenance")
    try:
        source_course_id = int(binding.get("course_id"))
        source_version = int(binding.get("course_version"))
        source_lesson_id = int(binding.get("lesson_id"))
        selected_by_user_id = int(note.get("selected_by_user_id") or 0)
        skill_id = str(binding.get("skill_id") or "")
        criterion_id = str(binding.get("criterion_id") or "")
        selected_at = datetime.fromisoformat(str(note.get("selected_at") or "").replace("Z", "+00:00"))
        provenance_course_id = int(provenance.get("course_id") or 0) if isinstance(provenance, dict) else 0
        provenance_course_version = int(provenance.get("course_version") or 0) if isinstance(provenance, dict) else 0
        provenance_lesson_id = int(provenance.get("lesson_id") or 0) if isinstance(provenance, dict) else 0
    except (TypeError, ValueError):
        return None

    source_course = db.session.get(LearningTrajectory, source_course_id)
    source_lesson = db.session.get(Lesson, source_lesson_id)
    source_link = LessonTask.query.filter_by(
        lesson_id=source_lesson_id, task_id=int(task.task_id),
    ).first()
    if (not source_course or source_course.is_template
            or source_course_id not in _allowed_copy_ids()
            or str(source_course.status or "").casefold() != "active"
            or int(source_course.current_version or 1) != source_version
            or not source_lesson or int(source_lesson.learning_trajectory_id or 0) != source_course_id
            or int(source_lesson.student_id or 0) != int(source_course.student_id or 0)
            or not source_link or not target_link
            or not isinstance(note, dict)
            or note.get("contract") != "boostudy.teacher-course-task-selection.v1"
            or note.get("source") != "teacher_manual_task_bank_selection"
            or note.get("purpose") != "shared_review"
            or selected_by_user_id != int(actor_user_id or 0)
            or not str(note.get("teacher_reason") or "").strip()
            or not isinstance(provenance, dict)
            or provenance_course_id != source_course_id
            or provenance_course_version != source_version
            or provenance_lesson_id != source_lesson_id
            or provenance.get("task_fingerprint") != binding.get("task_fingerprint")
            or str(note.get("skill_id") or "") != skill_id
            or str(note.get("criterion_id") or "") != criterion_id):
        return None

    selected_version = resolve_course_version_at(int(course.course_id), selected_at)
    if (selected_version.get("status") != "resolved"
            or int(selected_version.get("course_version") or 0) != int(course.current_version or 1)):
        return None

    if assignment is not None:
        if (int(assignment.lesson_id or 0) != int(lesson.lesson_id)
                or str(assignment.assignment_type or "").casefold() != "homework"
                or not bool(assignment.is_active)):
            return None
        assignment_version = resolve_course_version_at(int(course.course_id), assignment.created_at)
        assignment_binding = note.get("assignment_binding")
        assignment_tasks = AssignmentTask.query.filter_by(
            assignment_id=int(assignment.assignment_id), task_id=int(task.task_id),
        ).count()
        try:
            assignment_binding_matches = (
                isinstance(assignment_binding, dict)
                and assignment_binding.get("contract") == "boostudy.synthetic-assignment-course-binding.v1"
                and int(assignment_binding.get("assignment_id") or 0) == int(assignment.assignment_id)
                and int(assignment_binding.get("course_id") or 0) == int(course.course_id)
                and int(assignment_binding.get("course_version") or 0)
                == int(assignment_version.get("course_version") or 0)
                and int(assignment_binding.get("lesson_id") or 0) == int(lesson.lesson_id)
                and int(assignment_binding.get("student_id") or 0) == int(course.student_id)
                and int(assignment_binding.get("task_id") or 0) == int(task.task_id)
                and str(assignment_binding.get("skill_id") or "") == skill_id
                and str(assignment_binding.get("criterion_id") or "") == criterion_id
                and assignment_binding.get("task_fingerprint") == binding.get("task_fingerprint")
            )
        except (TypeError, ValueError):
            assignment_binding_matches = False
        if (assignment_version.get("status") != "resolved"
                or int(assignment_version.get("course_version") or 0) != int(selected_version["course_version"])
                or not assignment_binding_matches or assignment_tasks != 1):
            return None

    resolved_copy = resolve_assigned_synthetic_copy(int(course.student_id))
    if (resolved_copy.get("status") != "resolved"
            or int((resolved_copy.get("copy") or {}).course_id or 0) != int(course.course_id)):
        return None
    source_skill = next((item for item in (source_lesson.skills or [])
                         if item.is_active and f"exam-skill:{int(item.skill_id)}" == skill_id
                         and str(item.topic_code or "") == str(binding.get("topic_code") or "")), None)
    target_skill = next((item for item in (lesson.skills or [])
                         if item.is_active and f"exam-skill:{int(item.skill_id)}" == skill_id
                         and str(item.topic_code or "") == str(binding.get("topic_code") or "")), None)
    if not source_skill or not target_skill or int(source_skill.skill_id) != int(target_skill.skill_id):
        return None

    def criterion_exists(skill) -> bool:
        try:
            criteria = skill.mastery_criteria if isinstance(skill.mastery_criteria, list) else json.loads(skill.mastery_criteria or "[]")
        except (TypeError, ValueError):
            return False
        return isinstance(criteria, list) and any(
            isinstance(item, dict) and str(item.get("key") or "") == criterion_id
            for item in criteria
        )

    if not criterion_id or not criterion_exists(source_skill) or not criterion_exists(target_skill):
        return None
    return {
        "course_id": int(course.course_id),
        "course_version": int(selected_version["course_version"]),
        "lesson_id": int(lesson.lesson_id),
        "student_id": int(course.student_id),
        "skill_id": skill_id,
        "topic_code": str(target_skill.topic_code),
        "criterion_id": criterion_id,
        "source_course_id": source_course_id,
        "source_course_version": source_version,
        "source_lesson_id": source_lesson_id,
        "purpose": "shared_review",
        "pedagogical_status": "not_pedagogically_approved",
        "selected_at": selected_at.isoformat(),
    }


def _synthetic_course_task_binding(task, lesson_id: int | None, student, user_id: int,
                                  assignment_created_by_id: int | None = None, *,
                                  assignment=None,
                                  observed_at: datetime | None = None,
                                  assessment_method: str = "automatic_answer_checker",
                                  expected_answer: Any = None,
                                  max_score: Any = None,
                                  test_set_id: Any = None,
                                  test_set_version: Any = None,
                                  rubric_version: Any = None) -> dict[str, Any] | None:
    """Resolve an explicit draft-only task-to-criterion link inside one allowlisted course copy."""
    from app.ai_lab.database_safety import has_verified_safe_ai_lab_db
    from app.ai_lab.platform_homework import (
        _allowlisted_actor_ids, _allowlisted_task_author_ids, _allowlisted_user_ids, _task_fingerprint,
    )
    from app.ai_lab.provider import is_local_ai_lab_enabled
    from core.db_models import Lesson, db

    if (not has_verified_safe_ai_lab_db() or not is_local_ai_lab_enabled()
            or user_id not in _allowlisted_user_ids()
            or not task or task.bank_category != "synthetic_adaptive_draft"
            or not str(task.source_key or "").startswith("boostudy.synthetic.adaptive-v1/")
            or task.created_by_id not in _allowlisted_task_author_ids()
            or assignment_created_by_id is not None
            and assignment_created_by_id not in _allowlisted_actor_ids()):
        return None
    spec = task.answer_spec if isinstance(task.answer_spec, dict) else {}
    binding = spec.get("synthetic_course_skill_binding")
    if not isinstance(binding, dict):
        return None
    if binding.get("contract") == "boostudy.synthetic-course-source-skill.v1":
        resolved = _synthetic_master_task_binding(
            task, binding, lesson_id, student, user_id,
            assessment_method=assessment_method, expected_answer=expected_answer,
            max_score=max_score, test_set_id=test_set_id,
            test_set_version=test_set_version, rubric_version=rubric_version,
            observed_at=observed_at,
        )
        return _apply_synthetic_teacher_course_review(
            resolved, task, student, user_id, observed_at, assessment_method,
            expected_answer, max_score, test_set_id, test_set_version, rubric_version,
        )
    if binding.get("contract") != "boostudy.synthetic-course-skill.v1":
        return None
    try:
        copy_id = int(binding.get("course_id"))
        copy_version = int(binding.get("course_version"))
        bound_lesson_id = int(binding.get("lesson_id"))
        skill_id = str(binding.get("skill_id") or "")
        criterion_id = str(binding.get("criterion_id") or "")
    except (TypeError, ValueError):
        return None
    if (not student or int(student.student_id or 0) <= 0
            or int(student.user_id or 0) != user_id or not lesson_id):
        return None
    from app.ai_lab.course_adapter import _allowed_copy_ids, resolve_assigned_synthetic_copy
    if copy_id not in _allowed_copy_ids():
        return None
    resolution = resolve_assigned_synthetic_copy(int(student.student_id))
    copy = resolution.get("copy") if resolution.get("status") == "resolved" else None
    if not copy or int(copy.student_id or 0) != int(student.student_id):
        return None
    lesson = db.session.get(Lesson, int(lesson_id))
    if int(copy.course_id) != copy_id:
        selected = _synthetic_teacher_selected_shared_review(
            task, binding, copy, lesson,
            actor_user_id=assignment_created_by_id, assignment=assignment,
        )
        if not selected:
            return None
        result = {
            "contract": "boostudy.synthetic-course-task-binding.v1",
            **selected,
            "task_id": int(task.task_id),
            "semantic_compatibility": {
                "status": "unverified",
                "matches": [],
                "mismatches": ["teacher_selected_shared_review"],
                "reason": "Преподаватель связал материал с критерием для повторного разбора; его экспертная пригодность и независимость не подтверждены.",
            },
            "assessment_method": str(assessment_method or "automatic_answer_checker"),
            "task_fingerprint": str(binding["task_fingerprint"]),
            "task_content_sha256": hashlib.sha256(str(task.content_html or "").encode("utf-8")).hexdigest(),
            "checker_fingerprint": _course_checker_fingerprint(
                task, assessment_method, expected_answer, max_score,
                test_set_id, test_set_version, rubric_version,
            ),
        }
        return result
    if bound_lesson_id != int(lesson_id):
        return None
    if (not lesson or int(lesson.learning_trajectory_id or 0) != copy_id
            or int(lesson.student_id or 0) != int(student.student_id)
            or str(lesson.status or "").casefold() not in {"planned", "scheduled", "in_progress", "completed"}):
        return None
    skill = next((item for item in (lesson.skills or [])
                  if f"exam-skill:{int(item.skill_id)}" == skill_id and item.is_active), None)
    if not skill:
        return None
    try:
        raw_criteria = skill.mastery_criteria
        criteria = raw_criteria if isinstance(raw_criteria, list) else json.loads(raw_criteria or "[]")
    except (TypeError, ValueError):
        return None
    if int(copy.current_version or 1) == copy_version and not any(
        isinstance(item, dict) and item.get("key") == criterion_id for item in criteria
    ):
        return None
    if binding.get("task_fingerprint") != _task_fingerprint(task):
        return None
    task_hash = hashlib.sha256(str(task.content_html or "").encode("utf-8")).hexdigest()
    from app.ai_lab.course_adapter import compare_course_task_semantics
    compatibility = compare_course_task_semantics(
        course_id=copy_id, source_version=copy_version, lesson_id=bound_lesson_id,
        skill_id=skill_id, criterion_id=criterion_id, task_id=int(task.task_id),
        task_fingerprint=str(binding["task_fingerprint"]),
    )
    task_updated = getattr(task, "updated_at", None)
    if (observed_at and task_updated):
        if task_updated.tzinfo is not None and observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=task_updated.tzinfo)
        elif observed_at.tzinfo is not None and task_updated.tzinfo is None:
            task_updated = task_updated.replace(tzinfo=observed_at.tzinfo)
        if task_updated > observed_at:
            compatibility = {
                "status": "unverified", "matches": [], "mismatches": ["task_changed_after_evidence"],
                "reason": "Задание изменялось после попытки; исторический проверяющий восстановить нельзя.",
            }
    result = {
        "contract": "boostudy.synthetic-course-task-binding.v1",
        "course_id": copy_id,
        "course_version": copy_version,
        "lesson_id": bound_lesson_id,
        "task_id": int(task.task_id),
        "skill_id": skill_id,
        "topic_code": str(skill.topic_code),
        "criterion_id": criterion_id,
        "semantic_compatibility": compatibility,
        "assessment_method": str(assessment_method or "method_unrecorded"),
        "task_fingerprint": str(binding["task_fingerprint"]),
        "task_content_sha256": task_hash,
        "checker_fingerprint": _course_checker_fingerprint(
            task, assessment_method, expected_answer, max_score,
            test_set_id, test_set_version, rubric_version,
        ),
        "pedagogical_status": "not_pedagogically_approved",
    }
    return _apply_synthetic_teacher_course_review(
        result, task, student, user_id, observed_at, assessment_method,
        expected_answer, max_score, test_set_id, test_set_version, rubric_version,
    )


def _course_checker_fingerprint(task, assessment_method, expected_answer, max_score,
                                test_set_id, test_set_version, rubric_version) -> str:
    from app.ai_lab.course_evidence import course_task_checker_fingerprint

    return course_task_checker_fingerprint(
        answer_spec=getattr(task, "answer_spec", None),
        answer=getattr(task, "answer", None),
        expected_answer=expected_answer,
        assessment_method=str(assessment_method or "method_unrecorded"),
        max_score=max_score if max_score is not None else getattr(task, "max_score", None),
        test_set_id=test_set_id,
        test_set_version=test_set_version,
        rubric_version=rubric_version,
    )


def _apply_synthetic_teacher_course_review(binding, task, student, user_id, observed_at,
                                           assessment_method, expected_answer, max_score,
                                           test_set_id, test_set_version, rubric_version):
    """Apply an explicit synthetic teacher mapping only to evidence created after confirmation."""
    if not isinstance(binding, dict) or observed_at is None:
        return binding

    from app.ai_lab.course_adapter import _allowed_copy_ids
    from app.ai_lab.database_safety import has_verified_safe_ai_lab_db
    from app.ai_lab.platform_homework import (
        _allowlisted_actor_ids, _allowlisted_task_author_ids, _allowlisted_user_ids, _task_fingerprint,
    )
    from app.ai_lab.provider import is_local_ai_lab_enabled
    from core.db_models import ExamSkill, LearningTrajectory, Lesson, LessonTask, db

    if (not has_verified_safe_ai_lab_db() or not is_local_ai_lab_enabled()
            or int(user_id or 0) not in _allowlisted_user_ids()
            or int(getattr(task, "created_by_id", 0) or 0) not in _allowlisted_task_author_ids()
            or int(binding.get("course_id") or 0) not in _allowed_copy_ids()):
        return binding

    course = db.session.get(LearningTrajectory, int(binding["course_id"]))
    lesson = db.session.get(Lesson, int(binding["lesson_id"]))
    if (not course or not lesson or int(lesson.learning_trajectory_id or 0) != int(course.course_id)
            or int(lesson.student_id or 0) != int(getattr(student, "student_id", 0) or 0)
            or not LessonTask.query.filter_by(lesson_id=lesson.lesson_id, task_id=task.task_id).first()):
        return binding

    skill_id = str(binding.get("skill_id") or "")
    try:
        numeric_skill_id = int(skill_id.removeprefix("exam-skill:"))
    except (TypeError, ValueError):
        return binding
    skill = db.session.get(ExamSkill, numeric_skill_id)
    if (not skill or not skill.is_active or str(skill.topic_code or "") != str(binding.get("topic_code") or "")
            or not any(item.is_active and int(item.skill_id) == numeric_skill_id for item in (lesson.skills or []))):
        return binding

    observed = _as_aware_datetime(observed_at)
    if observed is None:
        return binding
    summary = lesson.review_summaries if isinstance(lesson.review_summaries, dict) else {}
    history = summary.get("_tutor_core_pedagogy_review_history")
    if not isinstance(history, list):
        return binding
    expected_checker = _course_checker_fingerprint(
        task, assessment_method, expected_answer, max_score,
        test_set_id, test_set_version, rubric_version,
    )
    actual_task_fingerprint = _task_fingerprint(task)
    matching_actions = []
    for event in history:
        if (not isinstance(event, dict)
                or event.get("contract") != "boostudy.teacher-course-task-review.v1"):
            continue
        actor_id = event.get("confirmed_by_user_id") if event.get("status") == "teacher_confirmed" else event.get("revoked_by_user_id")
        try:
            actor_id = int(actor_id or 0)
            event_course_id = int(event.get("course_id") or 0)
            event_lesson_id = int(event.get("lesson_id") or 0)
        except (TypeError, ValueError):
            continue
        if (actor_id <= 0 or actor_id not in _allowlisted_actor_ids()
                or event_course_id != int(course.course_id) or event_lesson_id != int(lesson.lesson_id)):
            continue
        event_at = _as_aware_datetime(event.get("confirmed_at") if event.get("status") == "teacher_confirmed"
                                      else event.get("revoked_at"))
        if event_at is None or event_at > observed:
            continue
        try:
            effective_version = int(event.get("effective_course_version") or 0)
        except (TypeError, ValueError):
            continue
        if effective_version <= 0 or effective_version > int(binding.get("course_version") or 0):
            continue
        event_bindings = event.get("bindings") if event.get("status") == "teacher_confirmed" else []
        if not isinstance(event_bindings, list):
            continue
        fingerprint = hashlib.sha256(json.dumps(
            event_bindings, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        if event.get("status") == "teacher_confirmed" and fingerprint != event.get("binding_fingerprint"):
            continue
        matching_actions.append((event_at, event, effective_version, event_bindings))

    if not matching_actions:
        return binding
    _, latest, reviewed_version, latest_bindings = max(matching_actions, key=lambda item: item[0])
    if latest.get("status") != "teacher_confirmed":
        return binding
    match_found = False
    for row in latest_bindings:
        if not isinstance(row, dict):
            continue
        try:
            row_task_id = int(row.get("task_id") or 0)
        except (TypeError, ValueError):
            continue
        if (row_task_id == int(task.task_id)
                and str(row.get("skill_id") or "") == skill_id
                and str(row.get("topic_code") or "") == str(binding.get("topic_code") or "")
                and str(row.get("criterion_id") or "") == str(binding.get("criterion_id") or "")
                and row.get("task_fingerprint") == actual_task_fingerprint
                and isinstance(row.get("checker_fingerprints"), dict)
                and row["checker_fingerprints"].get(str(assessment_method)) == expected_checker):
            match_found = True
            break
    if not match_found:
        return binding
    binding = dict(binding)
    binding.update({
        "pedagogical_status": "teacher_confirmed",
        "approval_basis": "ordinary_course_editor",
        "review_actor_user_id": int(latest["confirmed_by_user_id"]),
        "reviewed_at": str(latest["confirmed_at"]),
        "review_course_version": reviewed_version,
    })
    return binding


def _as_aware_datetime(value) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _synthetic_homework_course_context(assignment: Any, student: Any,
                                      task_binding: dict[str, Any] | None) -> dict[str, Any] | None:
    if (not assignment or not student or not task_binding
            or not getattr(assignment, "lesson_id", None)
            or not getattr(assignment, "created_at", None)):
        return None
    from app.ai_lab.learning_evidence import course_skill_criteria_fingerprint
    from core.db_models import LearningTrajectory, Lesson, db

    lesson = Lesson.query.filter_by(
        lesson_id=int(assignment.lesson_id), student_id=int(student.student_id),
    ).first()
    if not lesson:
        return None
    course = db.session.get(LearningTrajectory, int(lesson.learning_trajectory_id))
    if (not course or bool(course.is_template)
            or int(course.student_id or 0) != int(student.student_id)):
        return None
    source_course_id = int(task_binding.get("course_id") or 0)
    if source_course_id not in {int(course.course_id), int(course.parent_course_id or 0)}:
        return None
    source_course = db.session.get(LearningTrajectory, source_course_id)
    if (source_course and source_course_id == int(course.parent_course_id or 0)
            and int(source_course.current_version or 1) != int(task_binding.get("course_version") or 0)):
        return None
    course_skill_id = str(task_binding.get("skill_id") or "")
    linked_skills = [skill for skill in (lesson.skills or [])
                     if skill.is_active and f"exam-skill:{int(skill.skill_id)}" == course_skill_id]
    if len(linked_skills) != 1:
        return None

    from app.ai_lab.course_adapter import resolve_course_version_at
    resolution = resolve_course_version_at(int(course.course_id), assignment.created_at)
    if resolution.get("status") != "resolved":
        return None
    course_version = int(resolution["course_version"])
    skill = linked_skills[0]
    if not skill.topic_code:
        return None
    return {
        "contract": "boostudy.synthetic-homework-course-context.v1",
        "course_id": int(course.course_id),
        "course_version": int(course_version),
        "lesson_id": int(lesson.lesson_id),
        "course_skill_id": course_skill_id,
        "topic_code": str(skill.topic_code),
        "criteria_fingerprint": course_skill_criteria_fingerprint(skill.mastery_criteria),
    }


def _synthetic_course_binding_is_approved(binding: dict[str, Any] | None) -> bool:
    """Require explicit pedagogical approval in addition to technical compatibility."""
    if (not isinstance(binding, dict)
            or binding.get("contract") != "boostudy.synthetic-course-task-binding.v1"):
        return False
    compatibility = binding.get("semantic_compatibility")
    if not isinstance(compatibility, dict) or compatibility.get("status") != "compatible":
        return False
    if binding.get("pedagogical_status") == "expert_approved":
        return True
    try:
        review_version = int(binding.get("review_course_version") or 0)
        evidence_version = int(binding.get("course_version") or 0)
        actor_id = int(binding.get("review_actor_user_id") or 0)
    except (TypeError, ValueError):
        return False
    return bool(
        binding.get("pedagogical_status") == "teacher_confirmed"
        and binding.get("approval_basis") == "ordinary_course_editor"
        and actor_id > 0 and binding.get("reviewed_at")
        and review_version > 0 and review_version <= evidence_version
    )


def stored_platform_homework_evidence(*, actor_user_id: int | None = None) -> list[dict[str, Any]]:
    """Project explicitly allow-listed local platform submissions, never arbitrary learners."""
    from app.ai_lab.platform_homework import _allowlisted_actor_ids, _allowlisted_user_ids, _truthy, _value
    from core.db_models import (Answer, Assignment, Submission, SubmissionAiReview,
                                SubmissionAttempt, Student, User, db)
    from app.ai_lab.provider import is_local_ai_lab_enabled

    if not is_local_ai_lab_enabled() or not _truthy(_value("AI_LAB_PLATFORM_HOMEWORK_ENABLED", "false")):
        return []
    allowed_users = _allowlisted_user_ids()
    if not allowed_users or actor_user_id is None:
        return []
    actor = db.session.get(User, int(actor_user_id))
    role = str(getattr(actor, "role", "") or "").strip().casefold()
    admin_view = role in {"admin", "creator", "superadmin", "super_admin"}
    if not admin_view and int(actor_user_id) not in _allowlisted_actor_ids():
        return []

    latest_ids = (
        db.session.query(func.max(SubmissionAiReview.id).label("id"))
        .filter(SubmissionAiReview.provider.in_(("gigachat", "code_judge")))
        .group_by(SubmissionAiReview.submission_id)
        .subquery()
    )
    query = (
        SubmissionAiReview.query
        .join(latest_ids, SubmissionAiReview.id == latest_ids.c.id)
        .join(Submission, Submission.submission_id == SubmissionAiReview.submission_id)
        .join(Assignment, Assignment.assignment_id == Submission.assignment_id)
        .join(Student, Student.student_id == Submission.student_id)
        .filter(Student.user_id.in_(allowed_users))
    )
    if not admin_view:
        query = query.filter(Assignment.created_by_id == int(actor_user_id))
    rows = query.order_by(SubmissionAiReview.created_at.asc(), SubmissionAiReview.id.asc()).limit(2_000).all()
    events = []
    for review in rows:
        submission = review.submission
        assignment = submission.assignment if submission else None
        student = submission.student if submission else None
        user_id = int(getattr(student, "user_id", 0) or 0)
        if not submission or not assignment or user_id not in allowed_users:
            continue
        attempt_no = max(1, int(review.attempt_no or 1))
        occurred_at, event_time_source = _submission_activity_time(submission, attempt_no)
        if occurred_at is None:
            _logger.warning(
                "Skipping homework evidence without an actual submission timestamp: submission_id=%s attempt_no=%s",
                submission.submission_id, attempt_no,
            )
            continue
        matching_attempt = next((attempt for attempt in (submission.attempts or [])
                                 if int(attempt.attempt_no or 0) == attempt_no), None)
        task_rows = [item for item in (review.task_reviews or []) if isinstance(item, dict)]
        for item in task_rows:
            technical = item.get("technical") if isinstance(item.get("technical"), dict) else {}
            complete, rubric = _confirmed_code_judge_report(review.status, technical)
            criteria = []
            for criterion in rubric.get("criteria") or []:
                if not isinstance(criterion, dict):
                    continue
                status_value = criterion.get("status")
                criterion_status = ("met" if complete and status_value in {"fulfilled", "met"} else "not_met"
                                    if complete and status_value in {"not_fulfilled", "not_met"} else "insufficient_data")
                criteria.append({
                    "criterion_id": str(criterion.get("id") or criterion.get("title") or "criterion"),
                    "skill_id": criterion.get("skill_id") if complete else None,
                    "earned": criterion.get("score_awarded") if complete and criterion_status != "insufficient_data" else None,
                    "maximum": criterion.get("max_score"),
                    "status": criterion_status,
                    "evidence_status": "technical_confirmed" if complete and criterion_status != "insufficient_data" else "insufficient_data",
                    "reason": str(criterion.get("rationale") or (
                        "Результат подтверждён запуском Code Judge в sandbox." if complete
                        else "Нет полного подтверждения запуска Code Judge в sandbox; сохранённая AI-оценка не считается техническим доказательством."
                    )),
                    "source_refs": [f"submission:{submission.submission_id}:attempt:{attempt_no}"],
                })
            score = rubric.get("confirmed_score") if complete else None
            maximum = rubric.get("max_score")
            task_id = int(item.get("task_id") or 0)
            assignment_task_id = int(item.get("assignment_task_id") or 0)
            event_id = f"platform-submission:{submission.submission_id}:attempt:{attempt_no}:task:{task_id}"
            events.append({
                "contract_version": EVIDENCE_CONTRACT_VERSION,
                "event_id": event_id,
                "subject_id": f"platform-student:{user_id}",
                "source_module": "ai_homework",
                "source_record_id": f"submission:{submission.submission_id}",
                "occurred_at": occurred_at.isoformat(),
                "evidence_status": "technical_confirmed" if complete else "insufficient_data",
                "assignment": {"id": f"platform-assignment:{assignment.assignment_id}", "version": 1},
                "topic_ids": [],
                "skill_ids": [],
                "error_codes": [],
                "limitations": ["Оценка привязана к сохранённой версии набора Code Judge; конечный набор тестов не доказывает корректность для всех входов."],
                "outcome": {"score": score, "maximum": maximum, "status": "complete" if complete and score == maximum else "partial" if complete else "insufficient_data"},
                "criteria": criteria,
                "skill_ids": list(dict.fromkeys(
                    item["skill_id"] for item in criteria if complete and item.get("skill_id")
                )),
                "provenance": {
                    "source_ref": event_id,
                    "method": "Code Judge по сохранённой сдаче BooStudy" if complete else "Сохранённая сдача без подтверждённого полного запуска Code Judge",
                    "timestamp_context": _timestamp_context(
                        event_time_source, occurred_at,
                        timestamps={
                            "assignment_published_at": assignment.created_at,
                            "student_assigned_at": submission.assigned_at,
                            "submission_started_at": submission.started_at,
                            "submission_submitted_at": submission.submitted_at,
                            "submission_attempt_submitted_at": getattr(matching_attempt, "submitted_at", None),
                            "submission_graded_at": submission.graded_at,
                            "results_published_at": submission.results_published_at,
                            "ai_reviewed_at": review.created_at,
                        },
                        context_only=("assignment_published_at", "student_assigned_at", "submission_started_at",
                                      "submission_graded_at", "results_published_at", "ai_reviewed_at"),
                    ),
                },
                **({"platform_refs": {
                    "submission_id": int(submission.submission_id),
                    "attempt_id": next((int(attempt.attempt_id) for attempt in (submission.attempts or [])
                                         if int(attempt.attempt_no or 0) == attempt_no), None),
                    "assignment_id": int(assignment.assignment_id),
                    "assignment_task_id": assignment_task_id,
                    "task_id": task_id,
                    "student_id": int(submission.student_id),
                    "review_id": int(review.id),
                    "code_judge_test_set_id": technical.get("test_set_id"),
                    "code_judge_test_set_version": technical.get("test_set_version"),
                    "rubric_version": technical.get("rubric_version"),
                }} if complete else {}),
            })
    event_ids = {event["event_id"] for event in events}
    answer_query = (
        Answer.query
        .join(Submission, Submission.submission_id == Answer.submission_id)
        .join(Assignment, Assignment.assignment_id == Submission.assignment_id)
        .join(Student, Student.student_id == Submission.student_id)
        .filter(Student.user_id.in_(allowed_users), Submission.status.in_(("GRADED", "SUBMITTED", "NEEDS_MANUAL_REVIEW")))
    )
    if not admin_view:
        answer_query = answer_query.filter(Assignment.created_by_id == int(actor_user_id))
    answers = answer_query.order_by(Submission.submitted_at.asc(), Answer.answer_id.asc()).limit(5_000).all()
    from core.db_models import AnswerEvaluationRevision
    answer_ids = [int(answer.answer_id) for answer in answers if answer.answer_id is not None]
    evaluations_by_answer = {}
    if answer_ids:
        for revision in (AnswerEvaluationRevision.query
                         .filter(AnswerEvaluationRevision.answer_id.in_(answer_ids))
                         .order_by(AnswerEvaluationRevision.revision_no.desc()).all()):
            evaluations_by_answer.setdefault(int(revision.answer_id), revision)
    from app.ai_lab.knowledge_base import source_checked_platform_task_bindings
    platform_bindings = source_checked_platform_task_bindings()
    for answer in answers:
        submission = answer.submission
        assignment_task = answer.assignment_task
        assignment = submission.assignment if submission else None
        student = submission.student if submission else None
        user_id = int(getattr(student, "user_id", 0) or 0)
        if not submission or not assignment_task or not assignment_task.task or user_id not in allowed_users:
            continue
        task = assignment_task.task
        latest_attempt = max(
            (item for item in (submission.attempts or []) if item.attempt_no is not None),
            key=lambda item: int(item.attempt_no), default=None,
        )
        attempt_no = max(1, int(latest_attempt.attempt_no)) if latest_attempt else 1
        task_id = int(task.task_id)
        assignment_task_id = int(assignment_task.assignment_task_id)
        event_id = f"platform-submission:{submission.submission_id}:attempt:{attempt_no}:task:{task_id}"
        if event_id in event_ids:
            continue
        occurred_at, event_time_source = _submission_activity_time(
            submission, attempt_no, answer=answer,
        )
        if occurred_at is None:
            _logger.warning(
                "Skipping answer evidence without an actual submission timestamp: answer_id=%s submission_id=%s",
                answer.answer_id, submission.submission_id,
            )
            continue
        maximum = answer.max_score if answer.max_score is not None else assignment_task.max_score
        answer_spec = task.answer_spec if isinstance(getattr(task, "answer_spec", None), dict) else {}
        evaluation = evaluations_by_answer.get(int(answer.answer_id))
        manual_revision_for_binding = bool(
            evaluation and evaluation.state == "current" and evaluation.method == "teacher_manual"
            and evaluation.actor_user_id is not None and evaluation.score is not None
        )
        fixture_binding = _synthetic_tutorcore_fixture_binding(task, assignment, submission, user_id)
        synthetic_course_binding = _synthetic_course_task_binding(
            task, assignment.lesson_id if assignment else None, student, user_id,
            assignment.created_by_id if assignment else None,
            assignment=assignment,
            observed_at=(assignment.created_at if assignment and assignment.created_at else occurred_at),
            assessment_method="teacher_manual" if manual_revision_for_binding else "automatic_answer_checker",
            expected_answer=(assignment_task.answer_override if assignment_task.answer_override is not None
                             else getattr(task, "answer", None)),
            max_score=maximum,
        )
        synthetic_course_mapping_unapproved = bool(
            fixture_binding is None and synthetic_course_binding
            and not _synthetic_course_binding_is_approved(synthetic_course_binding)
        )
        if fixture_binding is None and synthetic_course_binding:
            fixture_binding = {
                "fixture_run_key": f"adaptive-v1-{synthetic_course_binding['course_id']}-v{synthetic_course_binding['course_version']}",
                "fixture_key": f"task-{synthetic_course_binding['task_id']}-{synthetic_course_binding['criterion_id']}",
                "knowledge_stable_key": synthetic_course_binding["topic_code"],
                "knowledge_version": 1,
                "knowledge_title": f"Синтетический черновик урока {synthetic_course_binding['lesson_id']}",
                "knowledge_status": "synthetic_draft",
                "knowledge_source_titles": ["Синтетический черновик; не утверждён для обучения."],
                "knowledge_content_sha256": synthetic_course_binding["task_content_sha256"],
                "task_id": synthetic_course_binding["task_id"],
                "task_content_sha256": synthetic_course_binding["task_content_sha256"],
                "source_key": str(task.source_key),
                "course_id": synthetic_course_binding["course_id"],
                "course_version": synthetic_course_binding["course_version"],
                "lesson_id": synthetic_course_binding["lesson_id"],
                "skill_key": synthetic_course_binding["skill_id"],
                "criterion_id": synthetic_course_binding["criterion_id"],
            }
        if fixture_binding is not None:
            attempt = (SubmissionAttempt.query.filter_by(submission_id=submission.submission_id)
                       .order_by(SubmissionAttempt.attempt_no.desc()).first())
            attempt_id = int(attempt.attempt_id) if attempt else None
            attempt_no = int(attempt.attempt_no) if attempt else 1
            evaluation = evaluations_by_answer.get(int(answer.answer_id))
            manual_revision = bool(evaluation and evaluation.state == "current"
                                   and evaluation.method == "teacher_manual"
                                   and evaluation.score is not None and evaluation.max_score is not None
                                   and evaluation.actor_user_id is not None)
            evaluation_voided = bool(evaluation and evaluation.state == "voided")
            manual_review = (
                evaluation_voided
                or bool(getattr(task, "requires_manual_grading", False)
                        or getattr(assignment_task, "requires_manual_grading", False))
            ) and not manual_revision
            answer_type = str((answer_spec.get("type") or "")).strip().casefold()
            checked_result = None
            check_failure = None
            if manual_revision:
                checked_result = (evaluation.is_correct, evaluation.score)
            elif not manual_review and answer_type in {"short_answer", "text", "integer", "number"} and answer.value is not None:
                try:
                    from app.assignments.routes import auto_grade_answer
                    checked_result = auto_grade_answer(answer, assignment_task)
                except Exception as exc:
                    check_failure = type(exc).__name__
            checked_correct = checked_result[0] if isinstance(checked_result, tuple) and len(checked_result) == 2 else None
            checked_score = checked_result[1] if isinstance(checked_result, tuple) and len(checked_result) == 2 else None
            if evaluation and evaluation.state == "voided":
                stored_correct = stored_score = None
            else:
                stored_correct = evaluation.is_correct if evaluation else getattr(answer, "is_correct", None)
                stored_score = evaluation.score if evaluation else getattr(answer, "score", None)
            scores_match = False
            if checked_score is not None and stored_score is not None:
                try:
                    scores_match = abs(float(checked_score) - float(stored_score)) < 1e-9
                except (TypeError, ValueError):
                    scores_match = str(checked_score) == str(stored_score)
            confirmed = (not manual_review and not manual_revision and attempt is not None and checked_correct is not None
                         and stored_correct is not None and bool(checked_correct) == bool(stored_correct)
                         and scores_match)
            manual_confirmed = bool(manual_revision and attempt is not None and maximum is not None
                                    and int(evaluation.max_score) == int(maximum))
            grade_confirmed = confirmed or manual_confirmed
            evidence_status = ("expert_confirmed" if manual_confirmed else
                               "technical_confirmed" if confirmed else "insufficient_data")
            assistance = _synthetic_tutorcore_assistance(
                fixture_binding, int(submission.submission_id), assignment_task_id, attempt_id,
            )
            limitations = ([
                f"Действующая оценка сохранена преподавателем (пользователь {evaluation.actor_user_id}, версия {evaluation.revision_no}); предыдущие оценки остаются в журнале ревизий."
            ] if manual_confirmed else [
                "Подтверждён повторный результат штатного точного автогрейдера на этом синтетическом ответе; эталон и привязка к навыку не проходили экспертную проверку.",
                "Задание и связь с материалом Knowledge Base заданы только для локальной синтетической фикстуры и не являются официальной привязкой ЕГЭ.",
                "Один короткий ответ не доказывает общее освоение навыка или корректность на других формулировках.",
            ]) if grade_confirmed else [
                "Проверяемый балл отсутствует: задача требует ручной оценки, нет записи попытки или штатная повторная проверка не совпала.",
                "Синтетическая привязка к теме не доказывает правильность ответа и не засчитывает навык.",
            ]
            if manual_review:
                limitations.append("Задание помечено для ручной проверки; числовой балл и результат по навыку не выставлялись.")
            if check_failure:
                limitations.append(f"Штатная повторная проверка не выполнилась ({check_failure}); требуется разбор преподавателя.")
            if assistance is None:
                limitations.append("Источник не сохранил однозначную запись помощи для этой попытки; самостоятельность неизвестна.")
            else:
                limitations.append("Характер помощи взят из отдельной неизменяемой записи синтетического сценария и не является наблюдением реальной платформенной подсказки.")
            if synthetic_course_mapping_unapproved:
                limitations.append(
                    "Ответ и балл проверены технически, но черновая привязка задания к критерию не утверждена экспертом; событие не подтверждает этот критерий или навык."
                )
            criterion_status = (
                "met" if confirmed and bool(checked_correct) else
                "not_met" if confirmed else
                "met" if manual_confirmed and int(stored_score) == int(maximum) else
                "not_met" if manual_confirmed and int(stored_score) == 0 else
                "insufficient_data"
            )
            if synthetic_course_mapping_unapproved:
                criterion_status = "insufficient_data"
            criterion_evidence_status = (
                "insufficient_data" if synthetic_course_mapping_unapproved else evidence_status
            )
            event_id = f"platform-submission:{submission.submission_id}:attempt:{attempt_no}:task:{task_id}"
            homework_course_context = (
                _synthetic_homework_course_context(assignment, student, synthetic_course_binding)
                if synthetic_course_binding else
                {"course_id": f"synthetic-{fixture_binding['fixture_run_key']}",
                 "course_version": fixture_binding["course_version"]}
            )
            event = {
                "contract_version": EVIDENCE_CONTRACT_VERSION,
                "event_id": event_id,
                "subject_id": f"platform-student:{user_id}",
                "source_module": "ai_homework",
                "source_record_id": f"submission:{submission.submission_id}",
                "occurred_at": occurred_at.isoformat(),
                "evidence_status": evidence_status,
                "assignment": {"id": f"platform-assignment:{assignment.assignment_id}", "version": 1},
                "course_context": homework_course_context,
                "topic_ids": ([] if synthetic_course_mapping_unapproved
                              else [fixture_binding["knowledge_stable_key"]]),
                "skill_ids": ([] if synthetic_course_mapping_unapproved else [fixture_binding["skill_key"]]),
                "error_codes": [],
                "limitations": limitations,
                "outcome": {
                    "score": stored_score if grade_confirmed else None,
                    "maximum": maximum,
                    "status": ("complete" if grade_confirmed and stored_score == maximum else
                               "partial" if grade_confirmed else "insufficient_data"),
                },
                "criteria": [{
                    "criterion_id": (fixture_binding.get("criterion_id")
                                     or f"assignment-task:{assignment_task_id}"),
                    "skill_id": None if synthetic_course_mapping_unapproved else fixture_binding["skill_key"],
                    "earned": None if synthetic_course_mapping_unapproved else (
                        stored_score if grade_confirmed else None
                    ),
                    "maximum": maximum,
                    "status": criterion_status,
                    "evidence_status": criterion_evidence_status,
                    "reason": (
                        "Ответ и балл подтверждены проверкой конкретного задания, но черновая связь с учебным критерием не утверждена; вывод о критерии не делается."
                        if synthetic_course_mapping_unapproved and grade_confirmed else
                        f"Действующая ручная оценка, ревизия {evaluation.revision_no}, выставлена пользователем {evaluation.actor_user_id}; критерий изолирован от предыдущих ревизий."
                        if manual_confirmed else
                        "Штатный автогрейдер BooStudy повторно вернул сохранённый результат; привязка навыка определена только синтетической фикстурой."
                        if confirmed else
                        "Нет достоверного числового результата; задание остаётся на ручной проверке."
                    ),
                    "source_refs": [f"submission:{submission.submission_id}:answer:{answer.answer_id}"],
                }],
                "assistance": assistance,
                "provenance": {
                    "source_ref": event_id,
                    "method": ("Ручная оценка преподавателя по явной ревизии" if manual_confirmed else
                               "Повторная штатная точная проверка BooStudy в локальной synthetic fixture"
                               if confirmed else "Сохранённая ручная или неподтверждённая попытка; без выставления балла"),
                    "timestamp_context": _timestamp_context(
                        event_time_source, occurred_at,
                        timestamps={
                            "assignment_published_at": assignment.created_at,
                            "student_assigned_at": submission.assigned_at,
                            "submission_started_at": submission.started_at,
                            "submission_submitted_at": submission.submitted_at,
                            "submission_attempt_submitted_at": getattr(latest_attempt, "submitted_at", None),
                            "answer_submitted_at": answer.submitted_separately_at,
                            "answer_reviewed_at": answer.reviewed_at,
                            "evaluation_revision_at": getattr(evaluation, "created_at", None),
                            "results_published_at": submission.results_published_at,
                        },
                        context_only=("assignment_published_at", "student_assigned_at", "submission_started_at",
                                      "answer_reviewed_at", "evaluation_revision_at", "results_published_at"),
                    ),
                    **({"evaluation_revision": {"id": int(evaluation.revision_id),
                                                "revision_no": int(evaluation.revision_no),
                                                "method": evaluation.method,
                                                "actor_user_id": (int(evaluation.actor_user_id)
                                                                  if evaluation.actor_user_id is not None else None),
                                                "state": evaluation.state}}
                       if evaluation else {"evaluation_revision": {"status": "legacy_unknown"}}),
                    **({"synthetic_course_task_binding": dict(synthetic_course_binding)}
                       if synthetic_course_binding else
                       {"synthetic_fixture_binding": dict(fixture_binding)}),
                },
                "platform_refs": {
                    "submission_id": int(submission.submission_id),
                    "attempt_id": attempt_id,
                    "assignment_id": int(assignment.assignment_id),
                    "assignment_task_id": assignment_task_id,
                    "task_id": task_id,
                    "student_id": int(submission.student_id),
                    "review_id": None,
                    "code_judge_test_set_id": None,
                    "code_judge_test_set_version": None,
                    "rubric_version": None,
                    "course_id": int(fixture_binding["course_id"]),
                    "lesson_id": int(fixture_binding["lesson_id"]),
                },
            }
            events.append(event)
            event_ids.add(event_id)
            continue
        binding = next((item for item in platform_bindings
                        if item["task_id"] == task_id
                        and item["content_fingerprint"] == getattr(task, "content_fingerprint", None)
                        and item["source_key"] == getattr(task, "source_key", None)), None)
        checked_result = None
        check_failure = None
        answer_type = str(answer_spec.get("type") or getattr(task, "answer_type", "")).strip().casefold()
        evaluation = evaluations_by_answer.get(int(answer.answer_id))
        manual_revision = bool(evaluation and evaluation.state == "current"
                               and evaluation.method == "teacher_manual"
                               and evaluation.score is not None and evaluation.max_score is not None
                               and evaluation.actor_user_id is not None)
        evaluation_voided = bool(evaluation and evaluation.state == "voided")
        manual_review = (evaluation_voided or bool(getattr(task, "requires_manual_grading", False)
                              or getattr(assignment_task, "requires_manual_grading", False))) and not manual_revision
        if manual_revision:
            checked_result = (evaluation.is_correct, evaluation.score)
        elif (binding and not manual_review and answer_type in {"short_answer", "text", "integer", "number"}
                and answer.value is not None):
            try:
                from app.assignments.routes import auto_grade_answer
                checked_result = auto_grade_answer(answer, assignment_task)
            except Exception as exc:
                check_failure = type(exc).__name__
        checked_correct = checked_result[0] if isinstance(checked_result, tuple) and len(checked_result) == 2 else None
        checked_score = checked_result[1] if isinstance(checked_result, tuple) and len(checked_result) == 2 else None
        if evaluation and evaluation.state == "voided":
            stored_correct = stored_score = None
        else:
            stored_correct = evaluation.is_correct if evaluation else getattr(answer, "is_correct", None)
            stored_score = evaluation.score if evaluation else getattr(answer, "score", None)
        scores_match = False
        if checked_score is not None and stored_score is not None:
            try:
                scores_match = abs(float(checked_score) - float(stored_score)) < 1e-9
            except (TypeError, ValueError):
                scores_match = str(checked_score) == str(stored_score)
        confirmed = (not manual_revision and binding is not None and checked_correct is not None and stored_correct is not None
                     and bool(checked_correct) == bool(stored_correct) and scores_match)
        manual_confirmed = bool(binding is not None and manual_revision and maximum is not None
                                and int(evaluation.max_score) == int(maximum))
        grade_confirmed = confirmed or manual_confirmed
        evidence_status = ("expert_confirmed" if manual_confirmed else
                           "technical_confirmed" if confirmed else "insufficient_data")
        course_context = (_synthetic_homework_course_context(assignment, student, binding)
                          if grade_confirmed else None)
        criterion_status = (
            "met" if confirmed and bool(checked_correct) else
            "not_met" if confirmed else
            "met" if manual_confirmed and int(stored_score) == int(maximum) else
            "not_met" if manual_confirmed and int(stored_score) == 0 else
            "insufficient_data"
        )
        limitations = ([
            f"Действующая ручная оценка сохранена как ревизия {evaluation.revision_no}, автор — пользователь {evaluation.actor_user_id}; история предыдущих оценок сохранена."
        ] if manual_confirmed else [
            "Подтверждена только повторяемость штатной проверки относительно сохранённого эталона; сам эталон не прошёл независимую экспертную проверку.",
            "Одна задача не доказывает освоение навыка, самостоятельность решения или общую корректность знаний ученика.",
        ]) if grade_confirmed else [
            "Нет точной source-checked привязки или повторная штатная проверка не совпала с сохранённой записью; балл не используется как подтверждённое свидетельство навыка."
        ]
        if manual_review:
            limitations.append("Задание помечено для ручной проверки; автогрейдер не запускался.")
        if check_failure:
            limitations.append(f"Штатная повторная проверка недоступна ({check_failure}); требуется разбор преподавателя.")
        criterion_reason = (
            f"Действующая ручная оценка, ревизия {evaluation.revision_no}, автор — пользователь {evaluation.actor_user_id}."
            if manual_confirmed else
            "Штатная проверка ответа BooStudy повторно дала тот же результат и балл; точные ID и отпечаток задания связаны с навыком в source-checked материале."
            if confirmed else
            "Сохранённая оценка не имеет согласованной повторной проверки и точной версии связи с навыком."
        )
        events.append({
            "contract_version": EVIDENCE_CONTRACT_VERSION,
            "event_id": event_id,
            "subject_id": f"platform-student:{user_id}",
            "source_module": "ai_homework",
            "source_record_id": f"submission:{submission.submission_id}",
            "occurred_at": occurred_at.isoformat(),
            "evidence_status": evidence_status,
            "assignment": {"id": f"platform-assignment:{assignment.assignment_id}", "version": 1},
            "course_context": course_context,
            "topic_ids": [],
            "skill_ids": [binding["skill_id"]] if grade_confirmed and criterion_status in {"met", "not_met"} else [],
            "error_codes": [],
            "limitations": limitations,
            "outcome": {
                "score": stored_score if grade_confirmed else None,
                "maximum": maximum,
                "status": ("complete" if grade_confirmed and stored_score == maximum
                           else "partial" if grade_confirmed else "insufficient_data"),
            },
            "criteria": [{
                "criterion_id": f"assignment-task:{assignment_task_id}",
                "skill_id": binding["skill_id"] if grade_confirmed else None,
                "earned": stored_score if grade_confirmed else None,
                "maximum": maximum,
                "status": criterion_status,
                "evidence_status": evidence_status,
                "reason": criterion_reason,
                "source_refs": [f"submission:{submission.submission_id}:answer:{answer.answer_id}"],
            }],
            "provenance": {"source_ref": event_id,
                           "method": ("Ручная оценка преподавателя по явной ревизии" if manual_confirmed else
                                      "Повторная штатная проверка BooStudy по сохранённому эталону" if confirmed
                                      else "Сохранённая оценка без согласованного подтверждённого источника проверки"),
                           "timestamp_context": _timestamp_context(
                               event_time_source, occurred_at,
                               timestamps={
                                   "assignment_published_at": assignment.created_at,
                                   "student_assigned_at": submission.assigned_at,
                                   "submission_started_at": submission.started_at,
                                   "submission_submitted_at": submission.submitted_at,
                                   "submission_attempt_submitted_at": getattr(latest_attempt, "submitted_at", None),
                                   "answer_submitted_at": answer.submitted_separately_at,
                                   "answer_reviewed_at": answer.reviewed_at,
                                   "evaluation_revision_at": getattr(evaluation, "created_at", None),
                                   "results_published_at": submission.results_published_at,
                               },
                               context_only=("assignment_published_at", "student_assigned_at", "submission_started_at",
                                             "answer_reviewed_at", "evaluation_revision_at", "results_published_at"),
                           ),
                           **({"evaluation_revision": {"id": int(evaluation.revision_id),
                                                       "revision_no": int(evaluation.revision_no),
                                                       "method": evaluation.method,
                                                       "actor_user_id": (int(evaluation.actor_user_id)
                                                                         if evaluation.actor_user_id is not None else None),
                                                       "state": evaluation.state}}
                              if evaluation else {"evaluation_revision": {"status": "legacy_unknown"}}),
                           **({"platform_task_binding": {
                               "knowledge_stable_key": binding["knowledge_stable_key"],
                               "knowledge_version": binding["knowledge_version"],
                               "knowledge_content_sha256": binding["knowledge_content_sha256"],
                               "task_id": binding["task_id"],
                               "content_fingerprint": binding["content_fingerprint"],
                               "source_key": binding["source_key"],
                               "course_id": binding["course_id"],
                               "course_version": binding["course_version"],
                               "lesson_id": binding["lesson_id"],
                               "skill_id": binding["skill_id"],
                           }} if grade_confirmed and binding else {})},
        })
        event_ids.add(event_id)
    return events


def stored_lesson_task_evidence(*, actor_user_id: int | None = None) -> list[dict[str, Any]]:
    """Read exact-answer Lesson Room classwork attempts from the safe synthetic DB only."""
    from app.ai_lab.database_safety import has_verified_safe_ai_lab_db
    from app.ai_lab.provider import is_local_ai_lab_enabled
    from app.models import Lesson, LessonTask, LessonTaskAttempt, Student, User, db

    if not has_verified_safe_ai_lab_db() or not is_local_ai_lab_enabled():
        return []
    query = (
        db.session.query(LessonTaskAttempt, LessonTask, Lesson, Student, User)
        .join(LessonTask, LessonTaskAttempt.lesson_task_id == LessonTask.lesson_task_id)
        .join(Lesson, LessonTask.lesson_id == Lesson.lesson_id)
        .join(Student, Lesson.student_id == Student.student_id)
        .join(User, Student.user_id == User.id)
        .filter(LessonTask.assignment_type == "classwork")
        .filter(User.username.like("demo_%") | User.username.like("synthetic_%"))
    )
    if actor_user_id is not None:
        actor = User.query.filter_by(id=int(actor_user_id)).first()
        role = str(getattr(actor, "role", "") or "").strip().casefold()
        if role not in {"admin", "creator", "superadmin", "super_admin"}:
            query = query.filter(Student.mentor_id == int(actor_user_id))
    rows = query.order_by(LessonTaskAttempt.attempt_id.asc()).limit(5_000).all()
    events = []
    for attempt, lesson_task, lesson, student, user in rows:
        if not attempt.student_submission or str(attempt.status or "").casefold() != "submitted":
            continue
        task = lesson_task.task
        expected = lesson_task.student_answer if lesson_task.student_answer is not None else (getattr(task, "answer", None) if task else None)
        verified = (expected is not None and bool(str(expected).strip())
                    and attempt.submission_correct is not None)
        maximum = getattr(task, "max_score", None) if task else None
        if not isinstance(maximum, (int, float)) or isinstance(maximum, bool) or maximum <= 0:
            maximum = 1
        score = (float(maximum) if bool(attempt.submission_correct) else 0.0) if verified else None
        maximum = float(maximum) if verified else None
        occurred_at = _evidence_timestamp(attempt.submitted_at, naive_timezone=_MOSCOW_TZ)
        if occurred_at is None:
            _logger.warning(
                "Skipping classwork evidence without an actual attempt timestamp: attempt_id=%s",
                attempt.attempt_id,
            )
            continue
        attempt_id = str(attempt.attempt_id)
        synthetic_binding = _synthetic_course_task_binding(
            task, int(lesson.lesson_id), student, int(user.id),
            observed_at=occurred_at,
            assessment_method="exact_answer_check",
            expected_answer=expected,
            max_score=maximum,
        ) if task else None
        criterion_mapping_approved = _synthetic_course_binding_is_approved(synthetic_binding)
        criterion_status = (
            "met" if verified and bool(attempt.submission_correct) else
            "not_met" if verified else "insufficient_data"
        )
        if synthetic_binding and not criterion_mapping_approved:
            criterion_status = "insufficient_data"
        event = {
            "contract_version": EVIDENCE_CONTRACT_VERSION,
            "event_id": f"lesson-classwork-attempt:{attempt_id}",
            "subject_id": f"platform-student:{int(user.id)}",
            "source_module": "ai_classwork",
            "source_record_id": f"lesson-task-attempt:{attempt_id}",
            "occurred_at": occurred_at.isoformat(),
            "evidence_status": "technical_confirmed" if verified else "insufficient_data",
            "assignment": {"id": f"classwork:{int(lesson.lesson_id)}:{int(lesson_task.lesson_task_id)}", "version": 1},
            "topic_ids": ([synthetic_binding["topic_code"]]
                          if synthetic_binding and criterion_mapping_approved else []),
            "skill_ids": ([synthetic_binding["skill_id"]]
                          if verified and synthetic_binding and criterion_mapping_approved else []),
            "error_codes": [],
            "limitations": ([
                "Результат относится к одному критерию синтетического черновика; он не доказывает освоение навыка или корректность на других вариантах.",
                "Характер помощи в Lesson Room не записан; самостоятельность по этой попытке неизвестна.",
                *([] if criterion_mapping_approved else [
                    "Ответ проверен технически, но черновая привязка задания к критерию не утверждена экспертом; событие не подтверждает критерий или навык."
                ]),
            ] if synthetic_binding else [
                "Сохранена только штатная точная проверка ответа; явная связь с предметным навыком не подтверждена.",
                "Характер помощи во время занятия в этой записи не фиксируется.",
            ]),
            "outcome": {"score": score, "maximum": maximum,
                        "status": "exact_answer_check" if verified else "insufficient_data"},
            "criteria": ([{
                "criterion_id": synthetic_binding["criterion_id"],
                "skill_id": synthetic_binding["skill_id"] if verified and criterion_mapping_approved else None,
                "earned": score if criterion_mapping_approved else None,
                "maximum": maximum,
                "status": criterion_status,
                "evidence_status": ("technical_confirmed"
                                    if verified and criterion_mapping_approved else "insufficient_data"),
                "reason": (
                    "Штатная точная проверка Lesson Room сверила ответ с ключом конкретной задачи, но черновая связь с критерием не утверждена; вывод о навыке не делается."
                    if verified and not criterion_mapping_approved else
                    "Штатная точная проверка Lesson Room сверила ответ с ключом конкретной синтетической задачи."
                ),
                "source_refs": [f"lesson-task-attempt:{attempt_id}"],
            }] if synthetic_binding else []),
            "assistance": None,
            "provenance": {
                "source_ref": f"lesson-task-attempt:{attempt_id}",
                "payload_hash": hashlib.sha256(
                    f"{lesson_task.lesson_task_id}:{attempt.student_submission}".encode("utf-8")
                ).hexdigest(),
                "model": "",
                "method": "BooStudy Lesson Room exact-answer check",
                "timestamp_context": _timestamp_context(
                    "lesson_task_attempt.submitted_at", occurred_at,
                    timestamps={
                        "lesson_task_attempt_submitted_at": attempt.submitted_at,
                        "lesson_task_planned_at": lesson_task.date_assigned,
                        "lesson_created_at": lesson.created_at,
                    },
                    context_only=("lesson_task_planned_at", "lesson_created_at"),
                    field_interpretations={
                        "lesson_task_planned_at": _classwork_planned_date_status(
                            lesson_task, lesson, occurred_at,
                        ),
                    },
                ),
                **({"synthetic_course_task_binding": synthetic_binding} if synthetic_binding else {}),
            },
        }
        try:
            events.append(validate_evidence_event(event))
        except EvidenceContractError:
            continue
    return events


def all_analytics_evidence(*, actor_user_id: int | None = None) -> list[dict[str, Any]]:
    """Combine visible evidence and reject conflicting records that reuse an event ID."""
    from app.ai_lab.lesson_intelligence import stored_lesson_evidence
    from app.ai_lab.practice import stored_ai_practice_evidence

    rows = (synthetic_demo_events()
            + stored_homework_evidence(actor_user_id=actor_user_id)
            + stored_platform_homework_evidence(actor_user_id=actor_user_id)
            + stored_lesson_evidence(actor_user_id=actor_user_id)
            + stored_lesson_task_evidence(actor_user_id=actor_user_id)
            + stored_ai_practice_evidence(actor_user_id=actor_user_id))
    return merge_evidence_events([rows])["events"]
