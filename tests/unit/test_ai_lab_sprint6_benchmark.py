from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.ai_lab.benchmark import (
    BenchmarkDataError,
    append_run_records,
    attach_expert_reviews,
    load_frozen_manifest,
    load_run_records,
    run_cases,
    summarize_expert_reviews,
)


ROOT = Path(__file__).parents[2]
MANIFEST_PATH = ROOT / "tests/fixtures/ai_lab_sprint6_manifest_v1.json"


def _frozen_dataset():
    _, dataset = load_frozen_manifest(MANIFEST_PATH)
    return dataset


def test_sprint6_dataset_is_hash_checked_synthetic_and_partitioned():
    dataset = _frozen_dataset()
    assert dataset["dataset_id"] == "boostudy-ai-lab-sprint6-synthetic-v1"
    assert {case["module"] for case in dataset["cases"]} == {
        "ai_homework", "ai_course", "ai_lesson_intelligence", "ai_analytics", "ai_practice",
    }
    assert {case["split"] for case in dataset["cases"]} == {"development", "regression", "holdout"}
    assert all(case["expert_review_status"] == "pending" for case in dataset["cases"])


def test_sprint6_benchmark_records_failures_and_excludes_holdout_by_default(tmp_path):
    dataset = _frozen_dataset()

    def executor(case):
        if case["case_id"] == "hw-dev-correct-return":
            raise RuntimeError("synthetic transport failure")
        return {"full_response": "synthetic output", "usage": {"input_tokens": 10, "output_tokens": 4}}

    records = run_cases(dataset, {module: executor for module in {case["module"] for case in dataset["cases"]}})
    assert records
    assert all(record["split"] != "holdout" for record in records)
    failed = next(record for record in records if record["case_id"] == "hw-dev-correct-return")
    assert failed["execution_error"]["type"] == "RuntimeError"
    assert failed["expert_review"]["status"] == "pending"

    path = tmp_path / "run.jsonl"
    assert append_run_records(path, records) == len(records)
    assert len(load_run_records(path)) == len(records)


def test_sprint6_holdout_requires_explicit_opt_in_and_review_metrics_exclude_unlabeled():
    dataset = _frozen_dataset()
    holdout_id = next(case["case_id"] for case in dataset["cases"] if case["split"] == "holdout")
    with pytest.raises(BenchmarkDataError, match="Не выполнены выбранные испытания"):
        run_cases(dataset, {"ai_homework": lambda case: {}}, case_ids=[holdout_id])

    summary = summarize_expert_reviews([
        {"module": "ai_homework", "split": "holdout", "expert_review": {"status": "reviewed", "ratings": {"score_correct": True, "reasoning": False}}},
        {"module": "ai_homework", "split": "holdout", "expert_review": {"status": "reviewed", "ratings": {"score_correct": None, "reasoning": True}}},
        {"module": "ai_homework", "split": "holdout", "expert_review": {"status": "pending", "ratings": {"score_correct": True, "reasoning": True}}},
    ])
    metrics = summary["groups"]["ai_homework:holdout"]["metrics"]
    assert metrics["score_correct"] == {
        "correct": 1, "n": 1, "accuracy": 1.0, "not_applicable": 0, "skipped": 1,
    }
    assert metrics["reasoning"] == {
        "correct": 1, "n": 2, "accuracy": 0.5, "not_applicable": 0, "skipped": 0,
    }
    assert summary["pending_runs"] == 1


def test_expert_reviews_are_stored_separately_and_joined_by_run_and_case():
    run = {"run_id": "run-1", "case_id": "case-1", "module": "ai_lesson_intelligence",
           "split": "holdout", "execution": {"full_response": "model output"},
           "expert_review": {"status": "pending", "ratings": {}}}
    reviewed = attach_expert_reviews([run], [{
        "run_id": "run-1", "case_id": "case-1", "reviewer": "reviewer-1",
        "ratings": {"factual": True, "unsupported_claim": False}, "reviewed_at": "2026-10-20T00:00:00Z",
    }])
    assert run["expert_review"]["status"] == "pending"
    assert reviewed[0]["expert_review"]["status"] == "reviewed"
    assert summarize_expert_reviews(reviewed)["expert_reviewed_runs"] == 1


def test_sprint6_fixture_hash_drift_is_rejected(tmp_path):
    from app.ai_lab.benchmark import load_dataset

    fixture = tmp_path / "fixture.json"
    fixture.write_text('{"dataset_id":"x"}', encoding="utf-8")
    with pytest.raises(BenchmarkDataError, match="SHA-256"):
        load_dataset(fixture, "0" * 64)


def test_sprint6_deterministic_adapters_use_typed_evidence_and_course_links():
    from scripts.run_ai_lab_sprint6_benchmark import _build_executors

    manifest, dataset = load_frozen_manifest(MANIFEST_PATH)
    executors = _build_executors(manifest, None, None, "adapter-test")
    cases = {case["case_id"]: case for case in dataset["cases"]}

    analytics = executors["ai_analytics"](cases["analytics-dev-two-confirmed-failures"])["result"]
    boundary_skill = next(item for item in analytics["skills"] if item["skill_id"] == "python.boundary_cases")
    assert boundary_skill["confirmed_evidence"] == 2
    assert boundary_skill["assignment_count"] == 2
    assert boundary_skill["status"] == "insufficient_data"

    recommendation = executors["ai_practice"](cases["practice-dev-prerequisites-satisfied"])["result"]
    assert [item["assignment_id"] for item in recommendation["recommendations"]] == ["s6-practice-boundary"]

    missing_prerequisite = executors["ai_practice"](cases["practice-holdout-prerequisite-missing"])["result"]
    assert missing_prerequisite["recommendations"] == []
    assert "python.conditions" in missing_prerequisite["suppressed"][0]["reason"]

    completed = executors["ai_practice"](cases["practice-holdout-already-completed"])["result"]
    assert completed["recommendations"] == []


def test_sprint6_live_budget_ledger_prevents_duplicate_calls_across_output_paths(tmp_path, monkeypatch):
    import scripts.run_ai_lab_sprint6_benchmark as runner

    canonical = tmp_path / "canonical-live.jsonl"
    alternate = tmp_path / "alternate-output.jsonl"
    monkeypatch.setattr(runner, "LIVE_RUN_LEDGER", canonical)
    recorded_attempt = {
        "dataset_id": "frozen-synthetic-v1",
        "run_id": "run-1",
        "case_id": "hw-dev-correct-return",
        "module": "ai_homework",
        "execution": {"attempt_count": 1},
        "expert_review": {"status": "pending", "ratings": {}},
    }
    append_run_records(canonical, [recorded_attempt])
    append_run_records(alternate, [recorded_attempt, {
        **recorded_attempt,
        "run_id": "run-2",
        "execution": {"attempt_count": 1},
    }])

    rows = runner._load_live_ledger_records(alternate)
    attempted_case_ids, used_budget = runner._previous_generation_state(rows, "frozen-synthetic-v1")
    assert attempted_case_ids == {"hw-dev-correct-return"}
    assert used_budget == 2
