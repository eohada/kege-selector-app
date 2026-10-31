"""Semantic fingerprints for deciding whether evidence survives course revisions.

Presentation order and lesson timing are intentionally outside the evidence key.
The assessed objective, stable skill, criterion, task and checker are not.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


SEMANTICS_CONTRACT = "boostudy.course-evidence-semantics.v1"


def _hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def course_task_checker_fingerprint(*, answer_spec: Any, answer: Any, expected_answer: Any,
                                    assessment_method: str, max_score: Any,
                                    test_set_id: Any = None, test_set_version: Any = None,
                                    rubric_version: Any = None) -> str:
    """Fingerprint the exact checker inputs used for a course task observation."""
    return _hash({
        "answer_spec": _answer_spec_without_course_link(answer_spec),
        "answer": answer,
        "expected_answer": expected_answer,
        "assessment_method": str(assessment_method or "method_unrecorded"),
        "max_score": max_score,
        "test_set_id": test_set_id,
        "test_set_version": test_set_version,
        "rubric_version": rubric_version,
    })


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value
    return value


def criteria_fingerprint(criteria: Any) -> str:
    parsed = _json_value(criteria)
    if not isinstance(parsed, list):
        parsed = []
    normalized = [item for item in parsed if isinstance(item, dict)]
    normalized.sort(key=lambda item: str(item.get("key") or ""))
    return _hash(normalized)


def _answer_spec_without_course_link(answer_spec: Any) -> Any:
    spec = _json_value(answer_spec)
    if not isinstance(spec, dict):
        return spec
    cleaned = dict(spec)
    cleaned.pop("synthetic_course_skill_binding", None)
    return cleaned


def lesson_objective_fingerprint(lesson: Any, skill: Any) -> str:
    module = getattr(lesson, "course_module", None)
    objective = str(getattr(module, "learning_result", "") or "").strip()
    payload = {
        "topic_code": str(getattr(skill, "topic_code", "") or "").strip(),
        "skill_id": f"exam-skill:{int(getattr(skill, 'skill_id', 0) or 0)}",
        "objective": objective,
        "lesson_content": str(getattr(lesson, "content", "") or "").strip(),
    }
    return _hash(payload)


def task_condition_fingerprint(task: Any) -> str:
    return _hash({
        "content_html": str(getattr(task, "content_html", "") or ""),
        "starter_code": str(getattr(task, "starter_code", "") or ""),
    })


def checker_fingerprint(*, task: Any, grading_method: str, expected_answer: Any = None,
                         max_score: Any = None, test_set_id: Any = None,
                         test_set_version: Any = None, rubric_version: Any = None) -> str:
    return _hash({
        "answer": getattr(task, "answer", None),
        "answer_spec": _answer_spec_without_course_link(getattr(task, "answer_spec", None)),
        "grading_method": str(grading_method or "").strip(),
        "expected_answer": expected_answer,
        "max_score": max_score if max_score is not None else getattr(task, "max_score", None),
        "code_judge_test_set_id": test_set_id,
        "code_judge_test_set_version": test_set_version,
        "rubric_version": rubric_version,
    })


def normalized_assessment_method(value: Any) -> str:
    method = str(value or "").strip().casefold().replace("-", "_")
    if method in {"exact_answer", "exact_answer_check", "boostudy lesson room exact_answer check",
                  "automatic_answer_checker"}:
        return "exact_answer.v1"
    if method in {"python_test_suite", "code_judge", "docker_runner"}:
        return "code_test_suite.v1"
    if method in {"teacher_manual", "teacher_reviewed_without_score", "manual_review"}:
        return "teacher_review.v1"
    return method or "method_unrecorded"


def build_semantic_record(*, course_id: int, course_version: int, lesson: Any, skill: Any,
                          criterion_id: str, task: Any, grading_method: str,
                          expected_answer: Any = None, max_score: Any = None,
                          test_set_id: Any = None, test_set_version: Any = None,
                          rubric_version: Any = None) -> dict[str, Any]:
    skill_id = f"exam-skill:{int(getattr(skill, 'skill_id', 0) or 0)}"
    criteria = criteria_fingerprint(getattr(skill, "mastery_criteria", None))
    return {
        "contract": SEMANTICS_CONTRACT,
        "course_id": int(course_id),
        "course_version": int(course_version),
        "lesson_id": int(getattr(lesson, "lesson_id", 0) or 0),
        "course_skill_id": skill_id,
        "topic_code": str(getattr(skill, "topic_code", "") or "").strip(),
        "criterion_id": str(criterion_id or "").strip(),
        "task_id": int(getattr(task, "task_id", 0) or 0),
        "lesson_objective_fingerprint": lesson_objective_fingerprint(lesson, skill),
        "criteria_fingerprint": criteria,
        "task_condition_fingerprint": task_condition_fingerprint(task),
        "assessment_method": normalized_assessment_method(grading_method),
        "checker_fingerprint": checker_fingerprint(
            task=task, grading_method=normalized_assessment_method(grading_method), expected_answer=expected_answer,
            max_score=max_score, test_set_id=test_set_id,
            test_set_version=test_set_version, rubric_version=rubric_version,
        ),
    }


_SEMANTIC_FIELDS = (
    "course_id", "lesson_id", "course_skill_id", "topic_code", "criterion_id", "task_id",
    "lesson_objective_fingerprint", "criteria_fingerprint", "task_condition_fingerprint",
    "assessment_method", "checker_fingerprint",
)


def compare_semantic_records(event: Any, source: Any, current: Any) -> dict[str, Any]:
    """Return a fully traceable compatibility decision; missing data fails closed."""
    if not all(isinstance(item, dict) for item in (event, source, current)):
        return {"status": "unverified", "matches": [], "mismatches": ["semantic_record_missing"],
                "reason": "Нет полного набора исходного, текущего и сохранённого семантического контекста."}
    matches: list[str] = []
    mismatches: list[str] = []
    for field in _SEMANTIC_FIELDS:
        values = [item.get(field) for item in (event, source, current)]
        if any(value in (None, "") for value in values):
            mismatches.append(f"{field}:missing")
        elif values[0] == values[1] == values[2]:
            matches.append(field)
        else:
            mismatches.append(f"{field}:changed")
    if mismatches:
        return {
            "status": "incompatible" if any(":changed" in item for item in mismatches) else "unverified",
            "matches": matches,
            "mismatches": mismatches,
            "reason": "Семантическая совместимость не подтверждена: " + ", ".join(mismatches),
        }
    return {
        "status": "compatible",
        "matches": matches,
        "mismatches": [],
        "reason": "Навык, цель, критерии, условие и проверяющий совпадают с зафиксированным состоянием исходной версии.",
    }
