"""Sprint 9 regressions using synthetic data and no live provider calls."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest


@pytest.fixture()
def sprint9_app():
    from app import create_app, db

    app = create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SECRET_KEY": "sprint9-isolated-test",
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "RUN_ENV": "local",
        "AI_LAB_ENABLED": True,
    })
    with app.app_context():
        db.create_all()
    try:
        yield app
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()


def _homework_response(score: int) -> str:
    return json.dumps({
        "score_awarded": score,
        "max_score": 2,
        "grading_status": "checked",
        "criterion_scores": [{
            "criterion": "2 балла за верный результат.",
            "score_awarded": score,
            "max_score": 2,
            "rationale": "Сверено с эталонным результатом.",
        }],
        "insufficient_data_reason": "",
        "summary": "Проверен результат целочисленного деления.",
        "mistakes": [],
        "student_feedback": "Проверьте вычисление.",
        "teacher_feedback": "Сопоставьте ответ с критерием.",
        "recommended_topics": [],
        "needs_human_review": False,
        "review_reason": "",
        "confidence_level": "medium",
    }, ensure_ascii=False)


class _ReplayProvider:
    name = "synthetic-replay"
    model = "Synthetic-Replay"

    def __init__(self, answers: list[str]):
        self.answers = list(answers)
        self.calls: list[dict] = []

    def list_models(self):
        return [self.model]

    def complete(self, _model, _prompt, _payload, **kwargs):
        self.calls.append(kwargs)
        content = self.answers.pop(0)
        number = len(self.calls)
        return SimpleNamespace(
            content=content,
            model=self.model,
            input_tokens=13 + number,
            output_tokens=7 + number,
            prompt_tokens=11 + number,
            precached_prompt_tokens=2,
            total_tokens=20 + 2 * number,
            payload_id=f"synthetic-{number}",
            payload_sha256=str(number) * 64,
            request_payload={"synthetic": True},
            generation_parameters={"temperature": 0.1, "max_tokens": 32, "top_p": None},
        )


def _stable_limits():
    return {
        "runs_per_admin_per_hour": 120,
        "runs_per_lab_per_hour": 300,
        "max_completion_attempts": 2,
        "auto_retry_enabled": True,
        "max_input_bytes": 128 * 1024,
    }


def test_each_completion_is_durable_and_retry_is_bounded_and_reasoned(sprint9_app, monkeypatch):
    from app import db
    from app.ai_lab import service
    from app.ai_lab.service import ensure_initial_prompt, run_experiment
    from core.db_models import AiLabExperiment, AiLabProviderAttempt

    monkeypatch.setattr(service, "is_local_ai_lab_enabled", lambda: True)
    monkeypatch.setattr(service, "provider_settings", lambda: {"configured": True, "default_model": "Synthetic-Replay"})
    monkeypatch.setattr(service, "ai_lab_limits", _stable_limits)
    provider = _ReplayProvider([_homework_response(1), _homework_response(0)])
    request = {
        "request_key": "1bd24a18-84c5-4e45-9ec6-7ed933761f8a",
        "scenario_id": "py-arithmetic-02",
        "model": provider.model,
        "input": {},
    }
    with sprint9_app.app_context():
        request["prompt_version_id"] = ensure_initial_prompt().id
        record = run_experiment(actor_user_id=9091, payload=request, provider=provider)
        assert record.status == "succeeded"
        assert record.result_json["grading_status"] == "manual_review"
        assert record.result_json["score_awarded"] is None
        assert record.quality_json["technical"]["semantic_validation"]["attempt_count"] == 2
        assert record.quality_json["technical"]["semantic_validation"]["status"] == "manual_review_required_after_retry"
        assert [item["retry_reason"] for item in record.quality_json["technical"]["attempts"]] == [
            "initial", "response_validation",
        ]
        ledger = AiLabProviderAttempt.query.filter_by(experiment_id=record.id).order_by(
            AiLabProviderAttempt.attempt_number.asc()).all()
        assert [item.status for item in ledger] == ["succeeded", "succeeded"]
        assert [item.retry_reason for item in ledger] == ["initial", "response_validation"]
        assert all(item.response_text and item.payload_sha256 for item in ledger)
        assert ledger[0].usage_json["full_input_tokens"] == 14
        assert ledger[1].request_metadata_json["generation_parameters"]["temperature"] == 0.1
        assert provider.calls[1]["repair_issue"]

        duplicate = run_experiment(actor_user_id=9091, payload=request, provider=provider)
        assert duplicate.id == record.id
        assert len(provider.calls) == 2
        changed = {**request, "input": {"student_solution": "изменённый ответ"}}
        from app.ai_lab.service import LabInputError
        with pytest.raises(LabInputError, match="другими входными данными"):
            run_experiment(actor_user_id=9091, payload=changed, provider=provider)
        assert AiLabExperiment.query.filter_by(actor_user_id=9091).count() == 1


def test_auto_retry_can_be_disabled_and_attempt_budget_cannot_exceed_config(sprint9_app, monkeypatch):
    from app import db
    from app.ai_lab import service
    from app.ai_lab.service import LabInputError, ensure_initial_prompt, run_experiment

    monkeypatch.setattr(service, "is_local_ai_lab_enabled", lambda: True)
    monkeypatch.setattr(service, "provider_settings", lambda: {"configured": True, "default_model": "Synthetic-Replay"})
    limits = {**_stable_limits(), "auto_retry_enabled": False}
    monkeypatch.setattr(service, "ai_lab_limits", lambda: limits)
    provider = _ReplayProvider([_homework_response(0)])
    with sprint9_app.app_context():
        prompt = ensure_initial_prompt()
        request = {
            "request_key": "57415130-9d9f-4879-9d6f-91f3a679a52e",
            "scenario_id": "py-arithmetic-02", "model": provider.model,
            "prompt_version_id": prompt.id, "input": {},
        }
        with pytest.raises(LabInputError, match="с учётом настроек"):
            run_experiment(actor_user_id=9092, payload=request, provider=provider, max_completion_attempts=2)
        record = run_experiment(actor_user_id=9092, payload=request, provider=provider)
        assert record.quality_json["technical"]["semantic_validation"]["attempt_count"] == 1
        assert len(provider.calls) == 1


def test_code_judge_points_survive_unresolved_model_conflict():
    from app.ai_lab.service import _apply_code_judge_authority

    result = _apply_code_judge_authority(
        {"score_awarded": None, "grading_status": "manual_review", "needs_human_review": True},
        {"criteria": ["1 балл за корректный ответ."], "max_score": 1},
        {"coverage_note": "Один критерий не покрыт.", "rubric": {
            "max_score": 1, "confirmed_score": 1, "criteria": [{
                "assignment_criterion_id": "answer", "title": "Ответ", "score_awarded": 1,
                "max_score": 1, "status": "fulfilled", "rationale": "Тест пройден.",
            }],
        }, "ai_criteria": [{"criterion": "Ответ"}]},
    )
    assert result["score_awarded"] == 1
    assert result["criterion_scores"][0]["score_awarded"] == 1
    assert result["needs_human_review"] is True


def test_assignment_family_contract_applies_validated_defaults_and_rejects_duplicate_criteria():
    from app.ai_lab.assignment_families import (
        AssignmentFamilyError,
        validate_family_contract,
        validate_variant_parameters,
    )

    contract = validate_family_contract({
        "requirements": [{"id": "answer", "criterion_id": "answer", "description": "Возвращает сумму цифр.", "source_refs": ["task-v1"]}],
        "variant_parameters": [{"name": "n", "type": "integer", "minimum": 0, "maximum": 999, "required": True, "default": 24}],
        "source_refs": [{"source_ref": "task-v1", "version": 1, "sha256": "a" * 64}],
        "compatibility": {"rule": "exact_assignment_contract"},
    })
    assert validate_variant_parameters(contract, {}) == {"n": 24}
    with pytest.raises(AssignmentFamilyError, match="диапазоне"):
        validate_variant_parameters(contract, {"n": 1000})
    duplicate = {
        "requirements": [
            {"id": "first", "criterion_id": "answer", "description": "Первое.", "source_refs": ["task-v1"]},
            {"id": "second", "criterion_id": "answer", "description": "Второе.", "source_refs": ["task-v1"]},
        ],
        "variant_parameters": [],
        "source_refs": [{"source_ref": "task-v1", "version": 1, "sha256": "a" * 64}],
        "compatibility": {"rule": "exact_assignment_contract"},
    }
    with pytest.raises(AssignmentFamilyError, match="ровно одно"):
        validate_family_contract(duplicate)


def test_quality_review_separates_na_skips_and_expert_labels():
    from app.ai_lab.benchmark import summarize_expert_reviews
    from app.ai_lab.quality_review import load_review_bundle

    summary = summarize_expert_reviews([
        {"module": "ai_homework", "split": "dev", "expert_review": {"status": "reviewed", "ratings": {"score": True, "comment": "na"}}},
        {"module": "ai_homework", "split": "dev", "expert_review": {"status": "reviewed", "ratings": {"score": False}}},
        {"module": "ai_homework", "split": "dev", "expert_review": {"status": "pending", "ratings": {}}},
    ])
    metrics = summary["groups"]["ai_homework:dev"]["metrics"]
    assert metrics["score"]["n"] == 2
    assert metrics["score"]["accuracy"] == 0.5
    assert metrics["comment"]["n"] == 0
    assert metrics["comment"]["not_applicable"] == 1
    assert metrics["comment"]["skipped"] == 1

    bundle = load_review_bundle("sprint7")
    assert bundle["summary"]["expert_reviewed_runs"] == 12
    assert bundle["summary"]["aspects_total"] > 0
    assert bundle["summary"]["aspects_unresolved"] < bundle["summary"]["aspects_total"]
    assert all(row["review_priority"]["label"] == "Технический приоритет, не экспертная оценка" for row in bundle["rows"])


def test_assignment_family_has_explicit_approval_and_pins_exact_versions(sprint9_app):
    from app import db
    from app.ai_lab.assignment_families import (
        AssignmentFamilyError,
        approve_family_version,
        create_family_version,
        list_family_versions,
        resolve_family_version,
        verify_family_version,
    )
    from app.ai_lab.code_judge import ensure_seeded_test_sets
    from app.models import User
    from core.db_models import AiLabCodeJudgeRun, AiLabCodeJudgeTestSet, AiLabRubricVersion

    with sprint9_app.app_context():
        admin = User(username="sprint9-family-admin", email="sprint9-family-admin@example.test",
                     role="admin", is_active=True)
        db.session.add(admin)
        db.session.commit()
        suite = next(item for item in ensure_seeded_test_sets()
                     if item["scenario_id"] == "digit-sum-evidence-v1")
        criteria = [{
            "id": item["assignment_criterion_id"], "title": item["title"],
            "max_score": item["max_score"], "description": item["description"],
            "full_credit": "Все связанные проверки пройдены.", "partial_credit": "",
        } for item in suite["rubric_json"]]
        rubric = AiLabRubricVersion(
            rubric_key="sprint9-family-digit-sum", version_no=1,
            assignment_id=suite["assignment_id"], assignment_version=suite["assignment_version"],
            task_json={
                "assignment_id": suite["assignment_id"], "assignment_version": 1,
                "title": "Сумма цифр", "subject": "Информатика", "topic": "Числовые алгоритмы",
                "answer_type": "python", "max_score": sum(item["max_score"] for item in criteria),
                "condition": "Синтетическое задание.",
                "reference_answer": "Любой корректный алгоритм суммирования цифр.",
            },
            criteria_json=criteria, proposed_tests_json=[], edits_json=[],
            validation_json={"ok": True}, status="approved", prompt_version="test-v1",
            generation_json={}, created_by_user_id=admin.id, approved_by_user_id=admin.id,
        )
        db.session.add(rubric)
        db.session.commit()
        reference = AiLabCodeJudgeRun(
            actor_user_id=admin.id, test_set_id=suite["id"], request_key="sprint9-family-reference",
            scenario_id=suite["scenario_id"], run_type="submit", mode="function", status="accepted",
            test_set_version=suite["test_set_version"], code="def digit_sum(n): return 0",
            code_hash="a" * 64, result_json={"test_set_snapshot": suite, "tests": []},
        )
        db.session.add(reference)
        db.session.commit()
        raw = {
            "family_id": "ai-lab.python.digit-sum",
            "title": "Проверенное семейство суммы цифр",
            "assignment_id": suite["assignment_id"],
            "assignment_version": suite["assignment_version"],
            "rubric_version_id": rubric.id,
            "test_set_id": suite["id"],
            "reference_run_id": reference.id,
            "contract": {
                "requirements": [{
                    "id": f"requirement-{item['id']}", "criterion_id": item["id"],
                    "description": item["description"], "source_refs": ["task-v1"],
                } for item in criteria],
                "variant_parameters": [{
                    "name": "max_n", "type": "integer", "minimum": 0, "maximum": 100000,
                    "default": 99999,
                }],
                "source_refs": [{"source_ref": "task-v1", "version": 1, "sha256": "b" * 64}],
                "compatibility": {"rule": "exact_assignment_contract"},
            },
        }
        draft = create_family_version(raw, admin.id)
        assert draft["status"] == "draft"
        with pytest.raises(AssignmentFamilyError, match="Сначала успешно проверьте"):
            approve_family_version(draft["id"], admin.id)

        verified = verify_family_version(draft["id"])
        assert verified["status"] == "verified"
        approved = approve_family_version(draft["id"], admin.id)
        assert approved["status"] == "approved"
        resolved = resolve_family_version(
            family_id=approved["family_id"], version_no=approved["version_no"],
            assignment_id=suite["assignment_id"], assignment_version=suite["assignment_version"],
            variant_parameters={},
        )
        assert resolved["variant_parameters"] == {"max_n": 99999}
        assert {item["criterion_id"] for item in resolved["criteria"]} == {
            item["id"] for item in criteria
        }

        saved_test_set = db.session.get(AiLabCodeJudgeTestSet, suite["id"])
        saved_test_set.test_set_version += 1
        db.session.commit()
        assert list_family_versions(approved_only=True) == []
        with pytest.raises(AssignmentFamilyError, match="больше не совместимо"):
            resolve_family_version(
                family_id=approved["family_id"], version_no=approved["version_no"],
                assignment_id=suite["assignment_id"], assignment_version=suite["assignment_version"],
                variant_parameters={},
            )


def test_unconfirmed_homework_criterion_scores_feed_analytics_evidence():
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from app.ai_lab.analytics import evidence_from_homework_experiment

    experiment = SimpleNamespace(
        id=991, status="succeeded", scenario_id="synthetic.boundary-task",
        scenario_snapshot={
            "assignment_id": "synthetic.boundary-task", "assignment_version": 2,
            "topic": "Границы", "max_score": 1,
            "assignment_criteria": [{"id": "zero-boundary", "skill_id": "python.boundary_cases"}],
        },
        input_snapshot={}, quality_json={},
        result_json={
            "grading_status": "partially_checked", "score_awarded": 0, "max_score": 1,
            "criterion_scores": [{"criterion_id": "zero-boundary", "score_awarded": 0,
                                 "max_score": 1, "rationale": "Ноль классифицирован неверно."}],
        },
        created_at=datetime(2026, 10, 20, 12, tzinfo=timezone.utc), model="Synthetic-Replay",
    )
    event = evidence_from_homework_experiment(experiment, subject_id="synthetic-s9-learner")
    assert event["evidence_status"] == "ai_inference"
    assert event["criteria"] == [{
        "criterion_id": "zero-boundary", "skill_id": "python.boundary_cases", "earned": 0,
        "maximum": 1, "status": "not_met", "evidence_status": "ai_inference",
        "reason": "Ноль классифицирован неверно.", "source_refs": ["ai-lab-experiment:991"],
    }]


def test_platform_homework_does_not_treat_gigachat_completion_as_runner_evidence():
    from app.ai_lab.analytics import _confirmed_code_judge_report

    assert not _confirmed_code_judge_report("completed", {"status": "completed"})[0]

    report = {
        "report_type": "platform_code_judge_evidence_v1", "status": "completed",
        "run_status": "complete", "test_set_id": 8, "test_set_version": 2,
        "rubric_version": 3, "passed": 2, "failed": 0, "total": 2,
        "rubric": {
            "confirmed_score": 3, "confirmed_max_score": 3,
            "unconfirmed_max_score": 0, "max_score": 3,
            "criteria": [{"status": "fulfilled", "score_awarded": 3, "max_score": 3}],
        },
    }
    assert _confirmed_code_judge_report("completed", report)[0]
    assert _confirmed_code_judge_report("unavailable", report)[0]

    report["rubric"]["confirmed_score"] = 2
    assert not _confirmed_code_judge_report("completed", report)[0]


def test_analytics_handles_long_synthetic_history_across_profiles_and_course_versions():
    from datetime import datetime, timedelta, timezone

    from app.ai_lab.analytics import build_analytics_snapshot
    from app.ai_lab.learning_evidence import EVIDENCE_CONTRACT_VERSION, validate_evidence_event

    events = []
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for index in range(180):
        assignment_number = (index // 3) % 3
        failed = index % 4 != 0
        raw = {
            "contract_version": EVIDENCE_CONTRACT_VERSION,
            "event_id": f"sprint9-load-event-{index}",
            "subject_id": f"synthetic-load-learner-{index % 3}",
            "source_module": "ai_homework", "source_record_id": f"sprint9-load-record-{index}",
            "occurred_at": (start + timedelta(minutes=index)).isoformat(),
            "evidence_status": "technical_confirmed",
            "assignment": {"id": f"synthetic.boundary-{assignment_number}", "version": 1 + index % 2},
            "course_context": {"course_id": "synthetic-load-course", "course_version": 1 + index % 2},
            "topic_ids": ["python.boundaries"], "skill_ids": ["python.boundary_cases"],
            "error_codes": ["zero-boundary"] if failed else [],
            "outcome": {"score": 0 if failed else 1, "maximum": 1, "status": "checked"},
            "criteria": [{
                "criterion_id": "zero-boundary", "earned": 0 if failed else 1, "maximum": 1,
                "status": "not_met" if failed else "met", "evidence_status": "technical_confirmed",
                "skill_id": "python.boundary_cases", "reason": "Синтетическое наблюдение.",
                "source_refs": [f"sprint9-load-event-{index}"],
            }],
            "provenance": {"source_ref": f"sprint9-load-event-{index}", "method": "synthetic-load"},
        }
        events.append(validate_evidence_event(raw))

    snapshots = [build_analytics_snapshot(events, f"synthetic-load-learner-{index}") for index in range(3)]
    assert [item["events"] for item in snapshots] == [60, 60, 60]
    assert all(item["uncertainty"]["invalid_events"] == 0 for item in snapshots)
    assert all(item["skills"][0]["confirmed_evidence"] == 60 for item in snapshots)
    assert all(item["skills"][0]["status"] == "needs_support" for item in snapshots)
    assert all(item["trends"][0]["sample"] == 60 for item in snapshots)


def test_quality_review_persists_explicit_not_applicable_without_changing_source(tmp_path, monkeypatch):
    from hashlib import sha256

    from app.ai_lab import quality_review
    from app.ai_lab.benchmark import BenchmarkDataError

    original = quality_review.BENCHMARKS["sprint6"]
    result_copy = tmp_path / "immutable-model-results.jsonl"
    result_copy.write_bytes(original["results"].read_bytes())
    source_hash = sha256(result_copy.read_bytes()).hexdigest()
    monkeypatch.setitem(quality_review.BENCHMARKS, "sprint6", {
        **original, "results": result_copy, "reviews": tmp_path / "expert-reviews.jsonl",
    })
    bundle = quality_review.load_review_bundle("sprint6")
    row = bundle["rows"][0]
    field = quality_review.RATING_FIELDS[row["module"]][0][0]

    quality_review.save_human_review(
        "sprint6", run_id=row["run_id"], case_id=row["case_id"], reviewer_id=991,
        ratings={field: "na"}, comments="Аспект неприменим к этому результату.",
    )
    reopened = quality_review.load_review_bundle("sprint6")
    reviewed = next(item for item in reopened["rows"] if item["case_id"] == row["case_id"])
    assert reviewed["expert_review"]["ratings"] == {field: "na"}
    metric = reopened["summary"]["module_metrics"][row["module"]]["metrics"][field]
    assert metric["n"] == 0
    assert metric["not_applicable"] == 1
    assert result_copy.read_bytes() and sha256(result_copy.read_bytes()).hexdigest() == source_hash
    with pytest.raises(BenchmarkDataError, match="уже оценён"):
        quality_review.save_human_review(
            "sprint6", run_id=row["run_id"], case_id=row["case_id"], reviewer_id=991,
            ratings={field: "na"}, comments="Повтор.",
        )
