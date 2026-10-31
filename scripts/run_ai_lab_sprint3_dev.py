"""Run only the frozen Sprint 3 synthetic development set against local AI Lab."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DISABLE_BACKGROUND_WORKERS", "1")

FIXTURE = ROOT / "tests" / "fixtures" / "ai_lab_sprint3_dev_cases.json"
FIXTURE_SHA256 = "e30dd3ebf7a985794f6bacd9a852478bdfda696c4be4b0a5e7bba565ef4a0038"
REPORT = ROOT / "artifacts" / "ai_lab" / "sprint3_dev_validation.json"


def _load_cases() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw = FIXTURE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != FIXTURE_SHA256:
        raise RuntimeError("Development fixture hash mismatch; stopped before any runner or model call.")
    dataset = json.loads(raw)
    if dataset.get("split") != "development" or len(dataset.get("cases", [])) != 3:
        raise RuntimeError("Only the three-case development split is allowed by this runner.")
    if sum(len(case.get("solutions", [])) for case in dataset["cases"]) != 12:
        raise RuntimeError("The expected 12 synthetic solutions are not present.")
    return dataset, dataset["cases"]


def _task_from_case(case: dict[str, Any]) -> dict[str, Any]:
    prompt = str(case["prompt"])
    prompt = re.split(r"\s+Предложение по диапазону|\s+Предлагаемый предел|\s+Предлагаемая версия", prompt, maxsplit=1)[0].strip()
    return {
        "subject": "Информатика",
        "topic": str(case["assignment"].get("title") or case["assignment"]["id"]),
        "answer_type": "python",
        "condition": prompt,
        "reference_answer": str(case["solutions"][0]["source"]),
        "teacher_requirements": "",
        "title": str(case["assignment"].get("title") or case["assignment"]["id"]),
        "max_score": float(case["rubric"]["max_score"]),
    }


def _create_approved_rubric(case: dict[str, Any], task: dict[str, Any], actor_id: int):
    from app import db
    from app.ai_lab.rubric_builder import validate_criteria, validate_task
    from core.db_models import AiLabRubricVersion

    criteria = [{
        "id": item["id"],
        "title": item["name"],
        "description": item["description"],
        "max_score": item["max_score"],
        "full_credit": item["award_rule"],
        "partial_credit": "",
        "typical_errors": [],
        "automatable": True,
        "evidence": "Подтверждается перечисленными синтетическими проверками Code Judge.",
        "manual_reason": "",
        "policy": "all_or_nothing",
    } for item in case["criteria"]]
    checked_task = validate_task(task)
    checked_criteria, validation = validate_criteria(criteria, checked_task)
    if not validation["ok"]:
        raise RuntimeError(f"Expert rubric failed structural validation: {validation['errors']}")
    rubric_key = str(uuid.uuid5(uuid.NAMESPACE_URL, str(case["rubric"]["id"])))
    item = AiLabRubricVersion(
        rubric_key=rubric_key,
        version_no=int(case["rubric"]["version"]),
        assignment_id=str(case["assignment"]["id"]),
        assignment_version=int(case["assignment"]["version"]),
        task_json=checked_task,
        criteria_json=checked_criteria,
        proposed_tests_json=[],
        raw_proposal_json={"source": "frozen_synthetic_development_fixture", "expert_prepared": True},
        edits_json=[],
        validation_json={**validation, "test_verification": "actual_runner_validation_pending"},
        status="approved",
        model="expert-prepared-synthetic-rubric",
        prompt_version="sprint-3-dev-oracle-v2",
        generation_json={"provider_calls": 0},
        created_by_user_id=actor_id,
        approved_by_user_id=actor_id,
        approved_at=datetime.now(timezone.utc),
    )
    db.session.add(item)
    db.session.commit()
    return item


def _test_set_from_case(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": str(case["assignment"].get("title") or case["assignment"]["id"]),
        "description": "Изолированный Sprint 3 development test set v2.",
        "mode": "function",
        "function_name": case["contract"]["function_name"],
        "comparator": "exact",
        "tolerance": 1e-6,
        "starter_code": str(case["solutions"][0]["source"]),
        "test_cases": [{
            "id": test["id"],
            "name": test["id"],
            "visibility": test["visibility"],
            "args": test["args"],
            "expected": test["expected"],
        } for test in case["tests"]],
        "rubric_json": [{
            "id": criterion["id"],
            "assignment_criterion_id": criterion["id"],
            "title": criterion["name"],
            "description": criterion["description"],
            "max_score": criterion["max_score"],
            "policy": "all_or_nothing",
            "checks": [{"case_id": test_id, "projection": "whole"} for test_id in criterion["test_ids"]],
        } for criterion in case["criteria"]],
        "assignment_id": case["assignment"]["id"],
        "assignment_version": case["assignment"]["version"],
    }


def _criterion_scores(rubric: dict[str, Any] | None) -> dict[str, float | None]:
    return {
        str(item.get("assignment_criterion_id") or item.get("id")): item.get("score_awarded")
        for item in (rubric or {}).get("criteria", [])
    }


def _response_claim(experiment) -> dict[str, Any]:
    technical = (experiment.quality_json or {}).get("technical") or {}
    attempts = technical.get("attempts") or []
    if not attempts:
        return {}
    raw = attempts[-1].get("response")
    try:
        claim = json.loads(raw) if isinstance(raw, str) else raw or {}
    except json.JSONDecodeError:
        return {"parse_error": True}
    if not isinstance(claim, dict):
        return {}
    return {key: claim.get(key) for key in ("score_awarded", "max_score", "grading_status", "criterion_scores", "summary", "student_feedback") if key in claim}


def run(*, with_gigachat: bool) -> dict[str, Any]:
    dataset, cases = _load_cases()
    from app import create_app, db
    from app.ai_lab.code_judge import run_request, save_test_set
    from app.ai_lab.code_judge_runner_client import runner_diagnostics
    from app.ai_lab.provider import GigaChatProvider, ProviderError, provider_settings
    from app.ai_lab.rubric_builder import validate_criteria, validate_task
    from app.ai_lab.scenarios import list_scenarios
    from app.ai_lab.service import ensure_initial_prompt, run_experiment
    from core.db_models import AiLabCodeJudgeTestSet, User

    app = create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "ENVIRONMENT": "local",
        "AI_LAB_ENABLED": True,
    })
    report: dict[str, Any] = {
        "dataset_id": dataset.get("dataset_id"),
        "dataset_version": dataset.get("dataset_version"),
        "dataset_sha256": FIXTURE_SHA256,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "database": "sqlite:///:memory:",
        "runner": {},
        "model_calls_authorized": 3 if with_gigachat else 0,
        "model_generation_calls": 0,
        "cases": [],
    }
    with app.app_context():
        db.create_all()
        diagnostics = runner_diagnostics()
        report["runner"] = {
            "ready": diagnostics.get("ready"),
            "secure_profile_verified": diagnostics.get("secure_profile_verified"),
            "runner_version": diagnostics.get("runner_version"),
            "queue": diagnostics.get("queue"),
            "limits": diagnostics.get("limits"),
            "security_profile": diagnostics.get("security_profile"),
        }
        if not diagnostics.get("ready") or diagnostics.get("secure_profile_verified") is not True:
            report["stopped_reason"] = "Runner missing or failed its security profile; no code was executed."
            return report

        actor = User.query.filter_by(username="creator").first()
        if not actor:
            report["stopped_reason"] = "Isolated app did not seed its local creator test user."
            return report

        rubrics = {}
        suites = {}
        for case in cases:
            task = _task_from_case(case)
            rubric = _create_approved_rubric(case, task, actor.id)
            rubrics[case["assignment"]["id"]] = rubric
            suite_data = save_test_set(_test_set_from_case(case), actor.id)
            test_set = db.session.get(AiLabCodeJudgeTestSet, suite_data["id"])
            test_set.test_set_version = int(case["test_set"]["version"])
            test_set.rubric_version = int(case["rubric"]["version"])
            db.session.commit()
            suite_data["test_set_version"] = test_set.test_set_version
            suite_data["rubric_version"] = test_set.rubric_version
            suites[case["assignment"]["id"]] = suite_data

        scenarios = {item.get("assignment_id"): item for item in list_scenarios() if item.get("assignment_id")}
        run_by_solution: dict[str, dict[str, Any]] = {}
        for case in cases:
            case_summary = {
                "case_id": case["case_id"],
                "assignment_id": case["assignment"]["id"],
                "assignment_version": case["assignment"]["version"],
                "test_set_version": case["test_set"]["version"],
                "rubric_version": case["rubric"]["version"],
                "solutions": [],
            }
            suite = suites[case["assignment"]["id"]]
            for solution in case["solutions"]:
                run_data, _created = run_request(actor.id, {
                    "request_key": str(uuid.uuid4()),
                    "run_type": "submit",
                    "test_set_id": suite["id"],
                    "test_set_version": suite["test_set_version"],
                    "test_set": suite,
                    "code": solution["source"],
                })
                result = run_data.get("result") or {}
                if result.get("complete") is not True:
                    raise RuntimeError(f"{solution['id']}: Code Judge did not complete the frozen suite.")
                actual = _criterion_scores(result.get("rubric"))
                expected = solution.get("criterion_results") or {}
                case_summary["solutions"].append({
                    "solution_id": solution["id"],
                    "variant": solution["label"],
                    "expert_score": solution.get("expected_score"),
                    "code_judge_score": (result.get("rubric") or {}).get("confirmed_score"),
                    "score_match": (result.get("rubric") or {}).get("confirmed_score") == solution.get("expected_score"),
                    "expert_criteria": expected,
                    "code_judge_criteria": actual,
                    "criteria_match": {key: actual.get(key) == value for key, value in expected.items()},
                    "passed": result.get("passed"),
                    "total": result.get("total"),
                    "status": run_data.get("status"),
                    "duration_ms": run_data.get("duration_ms"),
                })
                run_by_solution[solution["id"]] = run_data
            report["cases"].append(case_summary)

        if with_gigachat:
            settings = provider_settings()
            if not settings.get("configured"):
                report["model_error"] = "Локальный ключ GigaChat не настроен; генерация пропущена."
            else:
                provider = GigaChatProvider(settings)
                models = provider.list_models()
                model = next((item for item in models if item.casefold() == "gigachat-3-pro".casefold()), None)
                if not model:
                    report["model_error"] = "GigaChat-3-Pro отсутствует в фактически полученном каталоге."
                else:
                    class CappedProvider:
                        def __init__(self, delegate):
                            self.delegate = delegate
                            self.name = getattr(delegate, "name", "gigachat")
                            self.calls = 0

                        def list_models(self):
                            return self.delegate.list_models()

                        def complete(self, *args, **kwargs):
                            if self.calls >= 3:
                                raise ProviderError("sprint3_call_budget_exhausted", "Лимит Sprint 3: не более трёх запросов генерации.")
                            self.calls += 1
                            return self.delegate.complete(*args, **kwargs)

                    capped = CappedProvider(provider)
                    prompt = ensure_initial_prompt()
                    for case in cases:
                        alternative = next(item for item in case["solutions"] if item["label"] == "alternative_correct")
                        code_run = run_by_solution[alternative["id"]]
                        scenario = scenarios.get(case["assignment"]["id"])
                        if not scenario:
                            raise RuntimeError(f"Approved rubric scenario missing for {case['assignment']['id']}.")
                        experiment = run_experiment(
                            actor_user_id=actor.id,
                            payload={
                                "request_key": str(uuid.uuid4()),
                                "scenario_id": scenario["id"],
                                "model": model,
                                "prompt_version_id": prompt.id,
                                "input": {
                                    "condition": scenario["condition"],
                                    "student_solution": alternative["source"],
                                    "reference_answer": task["reference_answer"] if (task := _task_from_case(case)) else "",
                                    "criteria": scenario["criteria"],
                                    "max_score": scenario["max_score"],
                                    "additional_instructions": "",
                                },
                                "code_judge_run_id": code_run["id"],
                            },
                            provider=capped,
                        )
                        technical = (experiment.quality_json or {}).get("technical") or {}
                        case_summary = next(item for item in report["cases"] if item["case_id"] == case["case_id"])
                        code_judge_score = (code_run.get("result", {}).get("rubric") or {}).get("confirmed_score")
                        case_summary["ai_homework"] = {
                            "experiment_id": experiment.id,
                            "status": experiment.status,
                            "model": experiment.model,
                            "prompt_version": prompt.version_no,
                            "code_judge_run_id": code_run["id"],
                            "code_judge_score": code_judge_score,
                            "expert_score": alternative["expected_score"],
                            "initial_model_claim": _response_claim(experiment),
                            "final_after_evidence": experiment.result_json,
                            "semantic_validation": technical.get("semantic_validation"),
                            "usage": technical.get("usage"),
                            "duration_ms": experiment.duration_ms,
                        }
                        report["model_generation_calls"] = capped.calls
                        if experiment.status != "succeeded":
                            case_summary["ai_homework"]["technical_error"] = {
                                "code": experiment.error_code,
                                "message": experiment.error_message,
                            }
                            break

    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    flat = [solution for case in report["cases"] for solution in case["solutions"]]
    total_criteria = [match for solution in flat for match in solution["criteria_match"].values()]
    report["metrics"] = {
        "solutions": len(flat),
        "score_matches": sum(bool(item["score_match"]) for item in flat),
        "score_match_rate": round(sum(bool(item["score_match"]) for item in flat) / len(flat), 4) if flat else None,
        "criterion_matches": sum(bool(item) for item in total_criteria),
        "criterion_total": len(total_criteria),
        "criterion_match_rate": round(sum(bool(item) for item in total_criteria) / len(total_criteria), 4) if total_criteria else None,
        "model_generation_calls": report["model_generation_calls"],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-gigachat", action="store_true", help="Use at most one completion per task (3 total).")
    args = parser.parse_args()
    try:
        result = run(with_gigachat=args.with_gigachat)
    except Exception as exc:
        print(f"Sprint 3 dev validation failed: {type(exc).__name__}: {str(exc)[:400]}", file=sys.stderr)
        return 1
    print(json.dumps({
        "report": str(REPORT),
        "runner": {key: result.get("runner", {}).get(key) for key in ("ready", "secure_profile_verified", "runner_version", "limits")},
        "metrics": result.get("metrics"),
        "model_error": result.get("model_error"),
        "stopped_reason": result.get("stopped_reason"),
    }, ensure_ascii=False, indent=2))
    return 0 if result.get("runner", {}).get("secure_profile_verified") else 2


if __name__ == "__main__":
    raise SystemExit(main())
