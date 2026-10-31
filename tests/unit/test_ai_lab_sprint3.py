from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ai_lab.analytics import (
    COURSE_ANALYSIS_CONTRACT_VERSION,
    build_analytics_snapshot,
    course_analysis_input,
    evidence_from_homework_experiment,
    synthetic_demo_events,
)
from app.ai_lab.learning_evidence import (
    EVIDENCE_CONTRACT_VERSION,
    EvidenceContractError,
    LESSON_INTELLIGENCE_CONTRACT_VERSION,
    validate_evidence_event,
    validate_lesson_intelligence_output,
)
from app.ai_lab.practice import recommend_practice
from app.ai_lab.rubric_builder import validate_criteria, validate_task
from app.ai_lab.service import _public_code_judge_report, _user_payload


@pytest.fixture()
def isolated_app():
    from app import create_app, db

    test_app = create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "RUN_ENV": "local",
        "AI_LAB_ENABLED": True,
    })
    with test_app.app_context():
        db.create_all()
    try:
        yield test_app
    finally:
        with test_app.app_context():
            db.session.remove()
            db.drop_all()


def test_evidence_contract_rejects_invalid_criterion_provenance():
    event = synthetic_demo_events()[0]
    event["criteria"][0]["evidence_status"] = "maybe"
    with pytest.raises(EvidenceContractError, match="статус доказательства"):
        validate_evidence_event(event)


def test_analytics_and_practice_require_repeated_confirmed_failures():
    events = synthetic_demo_events()
    edge = build_analytics_snapshot(events, "edge-case-learner")
    boundary = next(item for item in edge["skills"] if item["skill_id"] == "python.boundary_cases")
    assert boundary["status"] == "needs_support"
    assert len(edge["recurring_errors"]) == 1

    catalog = [
        {"assignment_id": "new-boundary-task", "assignment_version": 1, "title": "Проверка условий", "topic": "Условия и границы", "type": "python"},
    ]
    practice = recommend_practice(edge, catalog)
    assert [item["assignment_id"] for item in practice["recommendations"]] == ["new-boundary-task"]

    one_error = build_analytics_snapshot([events[0]], "edge-case-learner")
    single_skill = one_error["skills"][0]
    assert single_skill["status"] == "insufficient_data"
    single_practice = recommend_practice(one_error, catalog)
    assert single_practice["recommendations"] == []
    assert single_practice["suppressed"]


def test_course_input_is_versioned_and_read_only():
    events = synthetic_demo_events()
    contract = course_analysis_input(events, "edge-case-learner")
    assert contract["contract_version"] == COURSE_ANALYSIS_CONTRACT_VERSION
    assert contract["mode"] == "read_only"
    assert all(event["subject_id"] == "edge-case-learner" for event in contract["evidence"])
    assert any("не разрешает" in message for message in contract["limitations"])


def test_lesson_intelligence_contract_accepts_synthetic_text_and_rejects_audio():
    contract = {
        "contract_version": LESSON_INTELLIGENCE_CONTRACT_VERSION,
        "lesson_id": "synthetic.lesson.conditions",
        "lesson_version": 1,
        "topics": [{"topic_id": "python.conditions", "title": "Условия", "evidence_status": "expert_confirmed", "source_ref": "text:segment-1"}],
        "content_segments": [{"segment_id": "segment-1", "summary": "Сравнение границ", "evidence_status": "expert_confirmed", "source_ref": "text:segment-1"}],
        "observed_difficulties": [],
        "summary": "Синтетический фрагмент про условия.",
        "source": {"kind": "synthetic_text", "ref": "synthetic-lesson-text-v1"},
        "verification_status": "expert_confirmed",
        "limitations": [],
    }
    assert validate_lesson_intelligence_output(contract)["lesson_id"] == "synthetic.lesson.conditions"
    contract["source"] = {"kind": "livekit_audio", "ref": "room-1"}
    with pytest.raises(EvidenceContractError, match="только синтетический текст"):
        validate_lesson_intelligence_output(contract)


def test_saved_homework_evidence_stays_typed_and_does_not_expose_code():
    experiment = SimpleNamespace(
        id=71,
        status="succeeded",
        scenario_id="synthetic.sum-multiples-of-three",
        scenario_snapshot={
            "assignment_id": "synthetic.sum-multiples-of-three",
            "assignment_version": 2,
            "topic": "Условия и границы",
            "assignment_criteria": [{"id": "logic.boundary", "max_score": 3}],
        },
        input_snapshot={"student_solution": "def solve(n): return n"},
        quality_json={"technical": {"code_judge": {
            "score_awarded": 3,
            "max_score": 3,
            "criteria": [{"assignment_criterion_id": "logic.boundary", "score_awarded": 3,
                          "max_score": 3, "status": "met", "rationale": "Связанные тесты пройдены."}],
        }}},
        result_json={"grading_status": "checked", "score_awarded": 3, "max_score": 3},
        created_at=datetime.now(timezone.utc),
        model="GigaChat-3-Pro",
    )
    event = evidence_from_homework_experiment(experiment)
    assert event["contract_version"] == EVIDENCE_CONTRACT_VERSION
    assert event["evidence_status"] == "technical_confirmed"
    assert event["outcome"]["score"] == 3
    assert "student_solution" not in event
    assert event["criteria"][0]["status"] == "met"


def test_homework_to_analytics_to_practice_uses_explicit_skill_mapping():
    events = []
    for index, assignment_id in enumerate(("synthetic.task-a", "synthetic.task-b", "synthetic.task-c"), 1):
        experiment = SimpleNamespace(
            id=100 + index,
            status="succeeded",
            scenario_id=assignment_id,
            scenario_snapshot={
                "assignment_id": assignment_id,
                "assignment_version": 1,
                "topic": "Условия и границы",
                "assignment_criteria": [{"id": "boundary", "skill_id": "python.boundary_cases", "max_score": 1}],
            },
            input_snapshot={"student_solution": f"synthetic answer {index}"},
            quality_json={"technical": {"code_judge": {
                "score_awarded": 0,
                "max_score": 1,
                "criteria": [{"assignment_criterion_id": "boundary", "score_awarded": 0,
                              "max_score": 1, "status": "not_fulfilled", "rationale": "Пограничная проверка не пройдена."}],
            }}},
            result_json={"grading_status": "partially_checked", "score_awarded": 0, "max_score": 1},
            created_at=datetime(2026, 10, index, 12, tzinfo=timezone.utc),
            model="GigaChat-3-Pro",
        )
        events.append(evidence_from_homework_experiment(experiment, subject_id="synthetic-pipeline-learner"))

    snapshot = build_analytics_snapshot(events, "synthetic-pipeline-learner")
    skill = snapshot["skills"][0]
    assert skill["status"] == "needs_support"
    assert snapshot["recurring_errors"][0]["code"] == "boundary"
    practice = recommend_practice(snapshot, [{
        "assignment_id": "synthetic.next-boundary",
        "assignment_version": 1,
        "title": "Следующее задание на границы",
        "topic": "Условия и границы",
        "type": "python",
    }], [event["assignment"]["id"] for event in events])
    assert practice["recommendations"][0]["assignment_id"] == "synthetic.next-boundary"


def test_analytics_and_practice_admin_routes_use_synthetic_evidence(isolated_app, monkeypatch):
    from app.ai_lab import routes
    from app.models import db, User

    with isolated_app.app_context():
        admin = User(username="sprint3_admin", email="sprint3-admin@example.test", role="admin")
        admin.set_password("local-test-password")
        db.session.add(admin)
        db.session.commit()

    client = isolated_app.test_client()
    assert client.get("/admin/ai-lab/analytics").status_code == 302
    login = client.post("/login", data={"username": "sprint3_admin", "password": "local-test-password"})
    assert login.status_code == 302

    monkeypatch.setattr(routes, "list_python_assignments", lambda: [{
        "assignment_id": "synthetic.next-boundary",
        "assignment_version": 1,
        "title": "Следующее задание на границы",
        "topic": "Условия и границы",
        "type": "python",
    }])
    analytics = client.get("/admin/ai-lab/api/analytics?subject_id=edge-case-learner")
    practice = client.get("/admin/ai-lab/api/practice/recommendations?subject_id=edge-case-learner")

    assert analytics.status_code == 200
    assert analytics.json["snapshot"]["skills"]
    assert practice.status_code == 200
    assert practice.json["recommendations"][0]["assignment_id"] == "synthetic.next-boundary"
    assert practice.json["recommendations"][0]["basis"]["source_refs"]

    student = User(username="sprint3_student", email="sprint3-student@example.test", role="student")
    student.set_password("local-test-password")
    with isolated_app.app_context():
        db.session.add(student)
        db.session.commit()
    student_client = isolated_app.test_client()
    student_login = student_client.post("/login", data={"username": "sprint3_student", "password": "local-test-password"})
    assert student_login.status_code == 302
    assert student_client.get("/admin/ai-lab/analytics").status_code == 403


def test_ai_payload_never_contains_test_cases():
    payload = _user_payload(
        {"student_solution": "print(1)", "test_cases": [{"input": "secret"}]},
        None,
        {"status": "completed", "passed": 1},
        {"test_cases": [{"visibility": "hidden", "input": "secret"}]},
    )
    assert "test_cases" not in payload["task"]
    assert "synthetic_test_cases_for_static_reasoning" not in payload
    assert "secret" not in str(payload)
    assert "скрытые проверки" in payload["feedback_constraints"][0]


def test_ai_code_judge_report_redacts_hidden_cases_and_outcomes():
    report = {
        "passed": 2,
        "total": 3,
        "tests": [
            {"id": "public-1", "visibility": "public", "status": "passed", "expected": 4, "actual": 4},
            {"id": "hidden-1", "visibility": "hidden", "status": "failed", "expected": 999, "actual": 1},
        ],
        "rubric": {
            "criteria": [{
                "id": "boundary",
                "score_awarded": 0,
                "evidence": [
                    {"case_id": "public-1", "status": "passed"},
                    {"case_id": "hidden-1", "status": "failed"},
                ],
            }],
        },
    }
    sanitized = _public_code_judge_report(report)
    assert sanitized["passed"] == 1 and sanitized["total"] == 1
    assert [item["id"] for item in sanitized["tests"]] == ["public-1"]
    assert sanitized["rubric"]["criteria"][0]["evidence"] == [{"case_id": "public-1", "status": "passed"}]
    assert "hidden-1" not in str(sanitized)
    assert "999" not in str(sanitized)


def test_frozen_sprint3_dev_fixture_is_unmodified_and_never_uses_holdout():
    fixture_path = Path(__file__).parents[1] / "fixtures" / "ai_lab_sprint3_dev_cases.json"
    raw = fixture_path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "e30dd3ebf7a985794f6bacd9a852478bdfda696c4be4b0a5e7bba565ef4a0038"
    dataset = json.loads(raw)
    assert dataset["split"] == "development"
    assert len(dataset["cases"]) == 3
    assert sum(len(case["solutions"]) for case in dataset["cases"]) == 12


def test_rubric_validator_reports_unapproved_partial_credit_and_separates_quality_dimensions():
    task = validate_task({
        "subject": "Информатика", "topic": "Условия", "answer_type": "text",
        "condition": "Определи результат сравнения чисел.", "max_score": 2,
        "teacher_requirements": "",
    })
    criteria = [{
        "id": "compare.result", "title": "Результат сравнения", "description": "Назван результат.",
        "max_score": 2, "full_credit": "Результат указан верно.", "partial_credit": "Одна часть ответа верна.",
        "typical_errors": [], "automatable": False, "evidence": "Содержательный ответ",
        "manual_reason": "Нужна проверка объяснения.", "policy": "proportional",
    }]
    _, validation = validate_criteria(criteria, task)
    assert validation["structural_status"] == "invalid"
    assert any("частичное начисление не разрешено" in error for error in validation["errors"])
    assert validation["content_correctness"] == "not_assessed_requires_expert_review"


def test_truncated_rubric_generation_is_saved_as_a_technical_error(isolated_app, monkeypatch):
    from app.ai_lab import rubric_builder
    from app.ai_lab.provider import CompletionResult
    from core.db_models import AiLabRubricVersion

    class FakeProvider:
        def __init__(self, _settings):
            pass

        def list_models(self):
            return ["GigaChat-3-Pro"]

        def complete_structured(self, *_args, **_kwargs):
            return CompletionResult(
                content='{"criteria":[', model="GigaChat-3-Pro", input_tokens=100,
                output_tokens=3200, prompt_tokens=100, precached_prompt_tokens=0,
                total_tokens=3300, payload_id="synthetic-payload", payload_sha256="a" * 64,
                generation_parameters={"max_tokens": 3200}, finish_reason="length",
            )

    monkeypatch.setattr(rubric_builder, "provider_settings", lambda: {"configured": True})
    monkeypatch.setattr(rubric_builder, "GigaChatProvider", FakeProvider)
    task = {
        "subject": "Информатика", "topic": "Условия", "answer_type": "text",
        "condition": "Определи результат сравнения чисел.", "max_score": 2,
    }
    with isolated_app.app_context():
        result = rubric_builder.generate_rubric(task, "GigaChat-3-Pro", None)
        saved = AiLabRubricVersion.query.filter_by(status="generation_error").one()
        assert result["status"] == "generation_error"
        assert result["generation"]["technical_error"]["code"] == "generation_truncated"
        assert result["generation"]["usage"]["completion_tokens"] == 3200
        assert saved.raw_proposal_json["truncated_completion"] == '{"criteria":['


def test_rubric_generation_reuses_stable_assignment_version_and_rejects_changed_content(isolated_app, monkeypatch):
    from app.ai_lab import rubric_builder
    from app.models import db
    from core.db_models import AiLabRubricVersion

    task = rubric_builder.validate_task({
        "assignment_id": "course.python.sum.v1", "assignment_version": 3,
        "title": "Сумма чисел", "subject": "Информатика", "topic": "Циклы",
        "answer_type": "python", "max_score": 3, "condition": "Сложить числа по условию.",
    })
    key = rubric_builder._stable_rubric_key(task)
    saved = AiLabRubricVersion(
        rubric_key=key, version_no=2, assignment_id=task["assignment_id"],
        assignment_version=task["assignment_version"], task_json=task,
        criteria_json=[{"id": "logic.sum", "title": "Сумма", "max_score": 3}],
        proposed_tests_json=[], edits_json=[], validation_json={"ok": True},
        status="approved", prompt_version=rubric_builder.PROMPT_VERSION,
        generation_json={},
    )
    with isolated_app.app_context():
        db.session.add(saved)
        db.session.commit()
        monkeypatch.setattr(rubric_builder, "provider_settings", lambda: pytest.fail("A compatible rubric must not call GigaChat"))
        reused = rubric_builder.generate_rubric(task, "GigaChat-3-Pro", 12)
        assert reused["reused"] is True
        assert reused["id"] == saved.id
        assert reused["version_no"] == 2

        revised = rubric_builder.revise_rubric(saved.id, {"task": task, "criteria": [{
            "id": "logic.sum", "title": "Сумма", "description": "Сумма вычислена правильно.",
            "max_score": 3, "full_credit": "Все значения суммы совпали.",
            "partial_credit": "", "typical_errors": [], "automatable": False,
            "evidence": "Сверка с эталонным решением.",
            "manual_reason": "Нужно экспертно проверить ход решения.", "policy": "all_or_nothing",
        }]}, 12)
        assert revised["version_no"] == 3
        assert revised["assignment_version"] == 3
        assert revised["status"] == "draft"

        changed_task = {**task, "condition": "Сложить только чётные числа."}
        with pytest.raises(rubric_builder.RubricError, match="другая формулировка") as error:
            rubric_builder.generate_rubric(changed_task, "GigaChat-3-Pro", 12)
        assert error.value.status == 409
