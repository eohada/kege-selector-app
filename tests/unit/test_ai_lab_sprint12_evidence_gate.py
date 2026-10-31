"""Synthetic Sprint 12 evidence-gate regressions; no GigaChat or learner data."""
from __future__ import annotations

import pytest

from app.ai_lab.feedback_validation import (
    apply_feedback_evidence_gate,
    audit_feedback_claims,
    build_feedback_evidence_gate,
    suppress_conflicting_comment,
)


def _report(*, criterion_status: str = "not_fulfilled", criterion_evidence=None, tests=None) -> dict:
    return {
        "status": "wrong_answer",
        "rubric": {
            "criteria": [{
                "id": "criterion-parity",
                "assignment_criterion_id": "criterion-parity",
                "title": "Чётность для отрицательных чисел",
                "status": criterion_status,
                "evidence": criterion_evidence or [],
            }],
        },
        "tests": tests or [],
    }


def _result(recommendation: str) -> dict:
    return {
        "score_awarded": 1,
        "max_score": 3,
        "summary": "Критерий чётности требует проверки.",
        "student_feedback": "Проверь обработку отрицательных значений.",
        "teacher_feedback": "Проверить предложенный вариант.",
        "mistakes": [{
            "criterion_id": "criterion-parity",
            "evidence_refs": ["negative-two"],
            "description": "Ошибка в проверке чётности",
            "explanation": "Условие не учитывает отрицательные числа.",
            "correction_recommendation": recommendation,
        }],
    }


def _failed_test_report() -> dict:
    return _report(
        criterion_evidence=[{"case_id": "negative-two", "status": "failed"}],
        tests=[{
            "id": "negative-two", "visibility": "public", "status": "wrong_answer",
            "expected": True, "actual": False,
        }],
    )


def test_failed_repair_is_contradicted_hidden_and_keeps_code_judge_score():
    result = _result("```python\ndef is_even(n):\n    return n % 2 == 1\n``` ")
    report = _failed_test_report()
    audit = audit_feedback_claims(result, report)
    check = {
        "status": "fails_saved_tests",
        "passed": 0,
        "total": 1,
        "candidate_sha256": "synthetic-hash",
        "counterexample": {"id": "negative-two", "visibility": "public", "expected": True, "actual": False},
        "test_evidence": [{"id": "negative-two", "visibility": "public", "status": "failed"}],
    }
    gate = build_feedback_evidence_gate(result, report, check, audit)
    safe = apply_feedback_evidence_gate(result, gate, check)

    recommendation = next(item for item in gate["claims"] if item["claim_type"] == "code_recommendation")
    assert recommendation["status"] == "contradicted"
    assert recommendation["counterexample"]["id"] == "negative-two"
    assert audit["status"] != "conflict_detected"
    assert safe["score_awarded"] == 1
    assert safe["mistakes"][0]["correction_recommendation"] == ""
    assert safe["mistakes"][0]["evidence_gate"]["status"] == "contradicted"
    assert safe["mistakes"][0]["evidence_gate"]["message"]


def test_alternative_fix_passes_bounded_tests_even_when_freeform_claims_are_unverified():
    result = _result("```python\ndef is_even(n):\n    return (n & 1) == 0\n```")
    report = _failed_test_report()
    audit = audit_feedback_claims(result, report)
    check = {
        "status": "passes_saved_tests",
        "passed": 4,
        "total": 4,
        "test_evidence": [{"id": "negative-two", "visibility": "public", "status": "passed"}],
    }
    gate = build_feedback_evidence_gate(result, report, check, audit)
    safe = apply_feedback_evidence_gate(result, gate, check)

    recommendation = next(item for item in gate["claims"] if item["claim_type"] == "code_recommendation")
    prose = next(item for item in gate["claims"] if item["claim_type"] == "pedagogical_narrative")
    assert recommendation["status"] == "verified"
    assert "не доказывает корректность для всех входов" in recommendation["note"]
    assert prose["status"] == "unverified"
    assert "```python" in safe["mistakes"][0]["correction_recommendation"]
    assert safe["mistakes"][0]["evidence_gate"]["status"] == "verified"


def test_runner_unavailable_marks_suggestion_unverified_without_claiming_it_passed():
    result = _result("```python\ndef is_even(n):\n    return n % 2 == 0\n```")
    report = _failed_test_report()
    audit = audit_feedback_claims(result, report)
    check = {"status": "runner_unavailable", "message": "Runner недоступен."}
    gate = build_feedback_evidence_gate(result, report, check, audit)
    safe = apply_feedback_evidence_gate(result, gate, check)

    recommendation = next(item for item in gate["claims"] if item["claim_type"] == "code_recommendation")
    assert recommendation["status"] == "unverified"
    assert "проверен" not in recommendation["note"].lower()
    assert safe["mistakes"][0]["correction_recommendation"]
    assert safe["mistakes"][0]["evidence_gate"]["status"] == "unverified"


def test_model_cannot_cite_a_public_test_that_code_judge_passed_as_error_evidence():
    result = _result("Используйте побитовую проверку.")
    report = _report(
        criterion_status="not_fulfilled",
        criterion_evidence=[{"case_id": "negative-two", "status": "failed"}],
        tests=[{"id": "negative-two", "visibility": "public", "status": "passed"}],
    )

    audit = audit_feedback_claims(result, report)

    assert audit["status"] == "conflict_detected"
    assert "не подтверждает ошибку" in " ".join(audit["issues"])


def test_insufficient_criterion_does_not_turn_a_passing_fix_into_a_conflict():
    result = _result("```python\ndef is_even(n):\n    return n % 2 == 0\n```")
    report = _report(
        criterion_status="insufficient_data",
        criterion_evidence=[{"case_id": "negative-two", "status": "unconfirmed"}],
        tests=[{"id": "negative-two", "visibility": "public", "status": "passed"}],
    )
    result["mistakes"][0]["evidence_refs"] = []
    audit = audit_feedback_claims(result, report)
    check = {"status": "passes_saved_tests", "passed": 3, "total": 3, "test_evidence": []}
    gate = build_feedback_evidence_gate(result, report, check, audit)
    safe = apply_feedback_evidence_gate(result, gate, check)

    recommendation = next(item for item in gate["claims"] if item["claim_type"] == "code_recommendation")
    assert audit["status"] != "conflict_detected"
    assert recommendation["status"] == "verified"
    assert safe["mistakes"][0]["correction_recommendation"]
    assert safe["score_awarded"] == 1


def test_duplicate_model_mistakes_do_not_change_deterministic_code_judge_score():
    from app.ai_lab.service import _apply_code_judge_authority

    result = {
        "score_awarded": 0,
        "mistakes": [{"criterion_id": "criterion-parity"}, {"criterion_id": "criterion-parity"}],
    }
    run_input = {"max_score": 3, "criteria": [{"criterion": "Чётность", "max_score": 3}]}
    report = {"rubric": {
        "max_score": 3,
        "confirmed_score": 2,
        "unconfirmed_max_score": 0,
        "criteria": [{
            "assignment_criterion_id": "criterion-parity",
            "title": "Чётность",
            "max_score": 3,
            "score_awarded": 2,
            "rationale": "Подтверждённый частичный результат.",
            "status": "not_fulfilled",
        }],
    }, "coverage_note": "Сохранённые тесты."}

    scored = _apply_code_judge_authority(result, run_input, report)

    assert scored["score_awarded"] == 2
    assert len(scored["mistakes"]) == 2
    assert scored["criterion_scores"][0]["score_awarded"] == 2


def test_code_candidate_returns_public_counterexample_without_hidden_values(monkeypatch):
    from types import SimpleNamespace
    from app import create_app, db
    from app.ai_lab import code_judge, code_judge_runner_client
    from app.ai_lab import config as ai_config
    from app.ai_lab.feedback_validation import verify_code_candidate

    app = create_app({"TESTING": True, "SECRET_KEY": "s12-counterexample", "SQLALCHEMY_DATABASE_URI": "sqlite://"})
    cases = [
        {"id": "public-zero", "visibility": "public", "args": [0], "expected": False},
        {"id": "private-case", "visibility": "hidden", "args": [99], "expected": "secret-expected"},
    ]
    snapshot = {
        "assignment_id": "synthetic-boundary", "assignment_version": 1,
        "mode": "function", "function_name": "check", "comparator": "exact", "tolerance": 0,
        "test_cases": cases,
    }
    original = SimpleNamespace(
        actor_user_id=31, run_type="submit", test_set_id=4, test_set_version=2, status="wrong_answer",
        result_json={"test_set_snapshot": snapshot},
    )
    normalized = {
        "status": "completed", "complete": True, "passed": 0, "failed": 2, "total": 2,
        "tests": [
            {"id": "public-zero", "status": "wrong_answer", "expected": False, "actual": True},
            {"id": "private-case", "status": "wrong_answer", "expected": "secret-expected", "actual": "secret-actual"},
        ],
    }

    with app.app_context():
        monkeypatch.setattr(db.session, "get", lambda model, row_id: original)
        monkeypatch.setattr(code_judge, "validate_test_set", lambda raw: snapshot)
        monkeypatch.setattr(code_judge_runner_client, "runner_diagnostics", lambda: {"ready": True, "secure_profile_verified": True})
        monkeypatch.setattr(code_judge_runner_client, "run_isolated", lambda payload: {"synthetic": True})
        monkeypatch.setattr(code_judge, "_normalize_result", lambda raw, expected_count: normalized)
        monkeypatch.setattr(ai_config, "code_judge_limits", lambda: {"test_timeout_seconds": 2})
        check = verify_code_candidate({"mistakes": [{
            "correction_recommendation": "```python\ndef check(n):\n    return n >= 0\n```",
        }]}, actor_user_id=31, judge_report={
            "run_id": 8, "test_set_id": 4, "test_set_version": 2,
            "assignment_id": "synthetic-boundary", "assignment_version": 1,
        })

    assert check["status"] == "fails_saved_tests"
    assert check["counterexample"] == {
        "id": "public-zero", "visibility": "public", "status": "wrong_answer",
        "expected": False, "actual": True,
    }
    assert "private-case" not in str(check)
    assert "secret-expected" not in str(check)
    assert "secret-actual" not in str(check)


def test_score_disagreement_with_code_judge_is_detected():
    from app.ai_lab.service import _judge_conflict

    report = {"rubric": {
        "max_score": 3,
        "confirmed_score": 2,
        "unconfirmed_max_score": 0,
        "criteria": [{"title": "Чётность", "score_awarded": 2, "status": "not_fulfilled"}],
    }}
    result = {"score_awarded": 1, "criterion_scores": [{"score_awarded": 1}]}

    assert _judge_conflict(result, report) == "Итоговый балл модели противоречит подтверждённой оценке Code Judge."


def test_existing_isolated_runner_checks_python_boundary_and_alternative_algorithms():
    from app import create_app
    from app.ai_lab.code_judge_runner_client import runner_diagnostics, run_isolated
    from app.ai_lab.config import code_judge_limits

    app = create_app({"TESTING": True, "SECRET_KEY": "s12-runner-check", "SQLALCHEMY_DATABASE_URI": "sqlite://"})
    cases = [
        ("bitwise-even-negative", "def check(n):\n    return (n & 1) == 0", [([-4], True), ([-3], False), ([0], True)]),
        ("modulo-odd-negative", "def check(n):\n    return n % 2 == 1", [([-3], True), ([-2], False), ([0], False)]),
        ("positive-strict-boundary", "def check(n):\n    return n > 0", [([0], False), ([1], True), ([-1], False)]),
        ("positive-inclusive-error", "def check(n):\n    return n >= 0", [([0], False), ([1], True), ([-1], False)]),
        ("multiples-counts-zero", "def check(n, k):\n    return sum(1 for value in range(n + 1) if value % k == 0)", [([4, 2], 3), ([0, 3], 1), ([5, 2], 3)]),
        ("even-modulo-alternative", "def check(n):\n    return n % 2 == 0", [([-4], True), ([-3], False), ([0], True)]),
        ("wrong-even-comparison", "def check(n):\n    return n % 2 == 1", [([-4], True), ([-3], False), ([0], True)]),
    ]

    with app.app_context():
        diagnostics = runner_diagnostics()
        if diagnostics.get("ready") is not True or diagnostics.get("secure_profile_verified") is not True:
            pytest.skip("Изолированный Runner не подтвердил полный профиль безопасности.")
        assert diagnostics.get("limits", {}).get("concurrency") == 1
        results = {}
        for name, code, inputs in cases:
            payload = {
                "code": code,
                "mode": "function",
                "function_name": "check",
                "comparator": "exact",
                "tolerance": 0,
                "test_cases": [
                    {"id": f"case-{index}", "visibility": "public", "args": args, "expected": expected}
                    for index, (args, expected) in enumerate(inputs, 1)
                ],
                "limits": code_judge_limits(),
            }
            results[name] = run_isolated(payload).get("tests", [])

    assert all(item.get("status") == "passed" for item in results["bitwise-even-negative"])
    assert all(item.get("status") == "passed" for item in results["modulo-odd-negative"])
    assert all(item.get("status") == "passed" for item in results["positive-strict-boundary"])
    assert results["positive-inclusive-error"][0].get("status") == "wrong_answer"
    assert results["positive-inclusive-error"][0].get("actual") is True
    assert all(item.get("status") == "passed" for item in results["multiples-counts-zero"])
    assert all(item.get("status") == "passed" for item in results["even-modulo-alternative"])
    assert all(item.get("status") == "wrong_answer" for item in results["wrong-even-comparison"])


def test_runner_confirmation_without_a_run_is_conflict_and_comment_is_withheld():
    result = {
        "score_awarded": 3,
        "max_score": 4,
        "summary": "Ответ неполный.",
        "student_feedback": "Добавьте четвёртое значение.",
        "teacher_feedback": "Code Judge подтверждает наличие трёх чисел.",
        "mistakes": [],
    }
    report = {
        "status": "not_run",
        "runner_status": "not_run",
        "rubric": {"criteria": []},
        "tests": [],
    }
    check = {"status": "not_checked_without_linked_runner"}

    audit = audit_feedback_claims(result, report)
    gate = build_feedback_evidence_gate(result, report, check, audit)
    safe = apply_feedback_evidence_gate(suppress_conflicting_comment(result, audit), gate, check)

    execution_claim = next(item for item in gate["claims"] if item["claim_type"] == "execution_result")
    assert audit["status"] == "conflict_detected"
    assert execution_claim["status"] == "contradicted"
    assert safe["score_awarded"] == 3
    assert "Code Judge подтверждает" not in safe["teacher_feedback"]
    assert "скрыт" in safe["summary"].lower()


def test_no_runner_statement_is_not_misclassified_as_confirmation():
    result = {
        "summary": "Code Judge не запускался и результат не подтверждён.",
        "student_feedback": "Требуется проверка преподавателя.",
        "teacher_feedback": "Нет данных исполнения.",
        "mistakes": [],
    }
    report = {
        "status": "not_run",
        "runner_status": "not_run",
        "rubric": {"criteria": []},
        "tests": [],
    }

    audit = audit_feedback_claims(result, report)

    assert audit["status"] != "conflict_detected"
