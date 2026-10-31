"""Deterministic Sprint 8 regressions; no live model calls and no fixture edits."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ai_lab.feedback_validation import (
    audit_feedback_claims,
    suppress_conflicting_comment,
    verify_code_candidate,
)
from app.ai_lab.quality_review import load_review_bundle
from app.ai_lab.schemas import ResponseValidationError, validate_response


ROOT = Path(__file__).parents[2]


def _sprint7_case(case_id: str) -> dict:
    for line in (ROOT / "docs/modules/artifacts/ai_lab_sprint7_live_run.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["case_id"] == case_id:
            return row
    raise AssertionError(f"Не найден замороженный случай {case_id}")


def test_saved_alternative_feedback_conflict_is_blocked_while_code_judge_score_survives():
    row = _sprint7_case("s7-classify-alternative-hybrid")
    execution = row["execution"]
    raw = json.loads(execution["full_response"])
    report = {
        "rubric": {"criteria": execution["judge_criteria"]},
        "tests": [], "passed": 0, "total": 0,
    }
    audit = audit_feedback_claims(raw, report)
    assert audit["status"] == "conflict_detected"
    gated = suppress_conflicting_comment({**raw, "score_awarded": execution["judge_score"]}, audit)
    assert gated["score_awarded"] == 4
    assert gated["student_feedback"].startswith("Комментарий модели требует проверки")
    assert gated["mistakes"] == []
    assert "н & 1" not in gated["student_feedback"]


def test_saved_boundary_explanation_accepts_strict_positive_correction():
    row = _sprint7_case("s7-classify-boundary-hybrid")
    raw = json.loads(row["execution"]["full_response"])
    report = {"rubric": {"criteria": row["execution"]["judge_criteria"]}, "tests": [], "passed": 0, "total": 0}
    audit = audit_feedback_claims(raw, report)
    assert audit["status"] != "conflict_detected"
    assert any("n > 0" in item["correction_recommendation"] for item in raw["mistakes"])


def test_saved_score_sum_diagnostic_precedes_unknown_status_and_unknown_status_stays_rejected():
    row = _sprint7_case("s7-classify-wrong-hybrid")
    raw = json.loads(row["execution"]["full_response"])
    with pytest.raises(ResponseValidationError, match="суммой баллов по критериям"):
        validate_response(raw, 4, [
            {"criterion": item["criterion"], "max_score": item["max_score"]}
            for item in raw["criterion_scores"]
        ], require_criteria=True)

    raw["score_awarded"] = sum(item["score_awarded"] for item in raw["criterion_scores"])
    with pytest.raises(ResponseValidationError, match="Неизвестный grading_status"):
        validate_response(raw, 4, [
            {"criterion": item["criterion"], "max_score": item["max_score"]}
            for item in raw["criterion_scores"]
        ], require_criteria=True)


def test_code_candidate_uses_only_secure_runner_and_reports_aggregate_result(monkeypatch):
    from app import create_app, db
    from app.ai_lab import code_judge, code_judge_runner_client
    from app.ai_lab import config as ai_config

    app = create_app({"TESTING": True, "SECRET_KEY": "sprint8-check", "SQLALCHEMY_DATABASE_URI": "sqlite://"})
    original = SimpleNamespace(
        id=7, actor_user_id=19, test_set_id=2, test_set_version=3, run_type="submit", status="wrong_answer",
        result_json={"test_set_snapshot": {
            "title": "Synthetic classify", "assignment_id": "synthetic-classify", "assignment_version": 1,
            "test_cases": [{"id": "private-case", "visibility": "hidden"}],
        }},
    )
    snapshot = {
        "title": "Synthetic classify", "assignment_id": "synthetic-classify", "assignment_version": 1,
        "mode": "function", "function_name": "classify", "comparator": "exact", "tolerance": 0.0,
        "test_cases": [{"id": "private-case", "visibility": "hidden", "args": [0], "expected": [False, True]}],
    }
    runner_payloads = []
    with app.app_context():
        monkeypatch.setattr(db.session, "get", lambda model, row_id: original)
        monkeypatch.setattr(code_judge, "validate_test_set", lambda raw: snapshot)
        monkeypatch.setattr(code_judge_runner_client, "runner_diagnostics", lambda: {
            "ready": True, "secure_profile_verified": True,
        })
        monkeypatch.setattr(code_judge_runner_client, "run_isolated", lambda payload: runner_payloads.append(payload) or {"runner": "ok"})
        monkeypatch.setattr(code_judge, "_normalize_result", lambda raw, expected: {
            "status": "completed", "complete": True, "passed": 0, "failed": 1, "total": 1,
        })
        monkeypatch.setattr(ai_config, "code_judge_limits", lambda: {"test_timeout_seconds": 2})
        result = verify_code_candidate({"mistakes": [{
            "correction_recommendation": "Полная версия:\n```python\ndef classify(n):\n    return (n >= 0, n % 2 == 0)\n```",
        }]}, actor_user_id=19, judge_report={
            "run_id": 7, "test_set_id": 2, "test_set_version": 3,
            "assignment_id": "synthetic-classify", "assignment_version": 1,
        })
    assert result["status"] == "fails_saved_tests"
    assert result["passed"] == 0 and result["total"] == 1
    assert len(runner_payloads) == 1
    assert "private-case" in runner_payloads[0]["test_cases"][0]["id"]
    assert "private-case" not in json.dumps(result)

    from app.ai_lab.code_judge_runner_client import RunnerUnavailable
    monkeypatch.setattr(
        code_judge_runner_client, "run_isolated",
        lambda payload: (_ for _ in ()).throw(RunnerUnavailable("private-case hidden expected value")),
    )
    with app.app_context():
        unavailable = verify_code_candidate({"mistakes": [{
            "correction_recommendation": "```python\ndef classify(n):\n    return n\n```",
        }]}, actor_user_id=19, judge_report={
            "run_id": 7, "test_set_id": 2, "test_set_version": 3,
            "assignment_id": "synthetic-classify", "assignment_version": 1,
        })
    assert unavailable["status"] == "runner_unavailable"
    assert "private-case" not in json.dumps(unavailable)


def test_quality_review_builds_teacher_views_without_human_labels_or_fixture_changes():
    bundle = load_review_bundle("sprint7")
    assert bundle["summary"]["expert_reviewed_runs"] == 12
    homework = next(row for row in bundle["rows"] if row["case_id"] == "s7-classify-alternative-hybrid")
    assert homework["review_presentation"]["task"]
    assert homework["review_presentation"]["solution"].startswith("def classify")
    assert homework["review_presentation"]["expected_score"] == 4
    assert homework["review_presentation"]["judge_score"] == 4
    course = next(row for row in bundle["rows"] if row["module"] == "ai_course")
    assert "proposals" in course["review_presentation"]
    lesson = next(row for row in bundle["rows"] if row["module"] == "ai_lesson_intelligence")
    assert lesson["review_presentation"]["utterances"]


def test_lesson_questions_are_not_difficulty_and_later_resolution_survives_chunk_merge():
    from app.ai_lab.lesson_intelligence import (
        LESSON_PROMPT,
        _merge_lesson_chunk_results,
        _validate_ai_result,
        parse_transcript,
    )

    question = parse_transcript("Ученик: Почему цикл начинается с нуля?")
    question_result = _validate_ai_result({
        "summary": "Ученик задал вопрос о начале цикла.", "topics": [], "content_segments": [],
        "observed_difficulties": [{"skill_id": "python.iteration", "description": "Не понимает индексирование.",
                                   "source_refs": [question[0]["segment_id"]]}], "limitations": [],
    }, {"lesson_id": "synthetic-s8-question", "lesson_version": 1, "source_ref": "synthetic-source", "segments": question})
    assert question_result["observed_difficulties"] == []
    assert len(question_result["unsubstantiated_observations"]) == 1

    segments = parse_transcript(
        "Ученик: Я не понимаю, почему range не включает верхнюю границу.\n"
        "Преподаватель: Последняя граница не входит в диапазон.\n"
        "Ученик: Теперь понятно: передам верхнюю границу плюс один."
    )
    first = _validate_ai_result({
        "summary": "Ученик обозначил затруднение с границей.", "topics": [], "content_segments": [],
        "observed_difficulties": [{"skill_id": "python.boundary_cases", "description": "Не понял исключённую границу.",
                                   "source_refs": [segments[0]["segment_id"]]}], "limitations": [],
    }, {"lesson_id": "synthetic-s8-resolution", "lesson_version": 1, "source_ref": "synthetic-source", "segments": segments[:2]})
    merged = _merge_lesson_chunk_results({"lesson_id": "synthetic-s8-resolution", "lesson_version": 1,
                                          "source_ref": "synthetic-source", "segments": segments},
                                         [{"result": first}, {"result": {"summary": "Позднее исправление отмечено.",
                                                                             "topics": [], "content_segments": [],
                                                                             "observed_difficulties": [], "limitations": []}}])
    observation = merged["observed_difficulties"][0]
    assert observation["resolution_status"] == "unresolved_or_unknown"
    assert observation["review_status"] == "pending"
    assert observation["resolution_source_refs"] == []
    assert "недоверенные" in LESSON_PROMPT


def test_course_mistaken_factual_proposal_stays_unapproved_and_requires_human_decision():
    from app.ai_lab.course import CourseAnalysisError, _validate_model_output, course_analysis_chunks, validate_course_input

    source = validate_course_input({
        "course_id": "synthetic-s8-course", "course_version": 1, "title": "Остаток от деления",
        "topics": [{"topic_id": "python.arithmetic", "title": "Арифметика", "order": 1, "prerequisite_ids": []}],
        "learning_goals": [], "assignments": [],
        "materials": [{"material_id": "synthetic-material-s8", "title": "Оператор %",
                       "topic_id": "python.arithmetic", "content": "Оператор % возвращает остаток от деления."}],
    })
    chunk = course_analysis_chunks(source)[0]
    ref = chunk["materials"][0]["source_fragments"][0]["source_ref"]
    output = _validate_model_output({"summary": "Требуется проверить точность формулировки.",
                                     "material_proposals": [{"proposal_id": "p1", "material_id": "synthetic-material-s8",
                                                              "observation": "Текст неверно называет результат частным.",
                                                              "proposed_text": "Оператор % возвращает частное от деления.",
                                                              "source_refs": [ref]}]}, chunk)
    assert output["summary_status"] == "unverified"
    assert output["material_proposals"][0]["status"] == "draft"
    assert output["material_proposals"][0]["source_refs"] == [ref]
    with pytest.raises(CourseAnalysisError, match="фактические источники"):
        _validate_model_output({"summary": "Есть замечание.", "material_proposals": [{
            "proposal_id": "p2", "material_id": "synthetic-material-s8", "observation": "Неподтверждённый вывод.",
            "proposed_text": "Изменить определение.", "source_refs": ["foreign-source"],
        }]}, chunk)
