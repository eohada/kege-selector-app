"""Run the frozen synthetic Code Judge/GigaChat comparison in the local lab only."""
from __future__ import annotations

import hashlib
import json
import sys
import time
import uuid
from datetime import timezone, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CONTROL_PATH = ROOT / "tests" / "fixtures" / "ai_lab_code_judge_v03_holdout.json"
CONTROL_SHA256 = "28b1dc0a576cf873f8991dec9edaddb514ee85e43c22949e76c61d26ef6b212d"
RESULT_PATH = ROOT / "artifacts" / "ai_lab" / "code_judge_v03_benchmark_results.json"


def _load_control() -> dict[str, Any]:
    raw = CONTROL_PATH.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CONTROL_SHA256:
        raise RuntimeError("Контрольный набор изменён; прогон остановлен до отправки запросов.")
    data = json.loads(raw)
    if len(data.get("cases", [])) != 20:
        raise RuntimeError("Контрольная серия должна содержать ровно 20 синтетических случаев.")
    return data


def _result_summary(experiment: Any) -> dict[str, Any]:
    technical = (experiment.quality_json or {}).get("technical") or {}
    usage = technical.get("usage") or {}
    result = experiment.result_json or {}
    attempts = technical.get("attempts") or []
    model_claim = {}
    if attempts:
        raw = attempts[-1].get("response")
        try:
            model_claim = json.loads(raw) if isinstance(raw, str) else raw or {}
        except json.JSONDecodeError:
            model_claim = {"parse_error": True}
    return {
        "experiment_id": experiment.id,
        "status": experiment.status,
        "validation_status": experiment.validation_status,
        "duration_ms": experiment.duration_ms,
        "usage": usage,
        "attempt_count": len(attempts),
        "model_claim": {
            "score_awarded": model_claim.get("score_awarded"),
            "grading_status": model_claim.get("grading_status"),
            "criterion_scores": model_claim.get("criterion_scores") or [],
            "mistakes": model_claim.get("mistakes") or [],
            "summary": model_claim.get("summary", ""),
            "student_feedback": model_claim.get("student_feedback", ""),
            "teacher_feedback": model_claim.get("teacher_feedback", ""),
            "recommended_topics": model_claim.get("recommended_topics") or [],
        },
        "authoritative_result": {
            "score_awarded": result.get("score_awarded"),
            "grading_status": result.get("grading_status"),
            "criterion_scores": result.get("criterion_scores") or [],
        },
        "quality": {
            "code_judge_conflict": (experiment.quality_json or {}).get("code_judge_conflict"),
            "conflict_detail": (experiment.quality_json or {}).get("code_judge_conflict_detail"),
            "retry_used": (experiment.quality_json or {}).get("code_judge_retry_used"),
        },
    }


def _prediction_metrics(summary: dict[str, Any], case: dict[str, Any], criteria_order: list[str]) -> dict[str, Any]:
    claim = summary.get("model_claim") or {}
    expected_score = case.get("expected_score")
    actual_score = claim.get("score_awarded")
    score_match = actual_score is None if expected_score is None else actual_score is not None and abs(float(actual_score) - float(expected_score)) < 0.001
    expected_criteria = case.get("criterion_scores") or {}
    actual_criteria = claim.get("criterion_scores") or []
    comparisons = []
    for index, criterion_id in enumerate(criteria_order):
        expected = expected_criteria.get(criterion_id)
        if expected is None:
            continue
        actual = actual_criteria[index].get("score_awarded") if index < len(actual_criteria) and isinstance(actual_criteria[index], dict) else None
        comparisons.append({"criterion_id": criterion_id, "expected": expected, "actual": actual, "correct": actual is not None and abs(float(actual) - float(expected)) < 0.001})
    text = " ".join([
        str(claim.get("summary") or ""), str(claim.get("student_feedback") or ""),
        str(claim.get("teacher_feedback") or ""),
        " ".join(str(item.get("description") or "") + " " + str(item.get("explanation") or "") for item in claim.get("mistakes", []) if isinstance(item, dict)),
        " ".join(str(item) for item in claim.get("recommended_topics", [])),
    ]).lower()
    issue_terms = {
        "zero_boundary": ("нол", "0"),
        "off_by_one": ("на 1", "плюс один", "лишн", "дополнительн"),
        "embedded_zero": ("нул", "разряд"),
        "incomplete_digit_traversal": ("цифр", "разряд", "последн", "остат"),
        "return_type": ("тип", "строк", "целочислен", "int"),
        "constant_result": ("всегда", "постоянн", "констант", "вход"),
        "incomplete_return": ("return", "none", "возвращ"),
        "syntax_error": ("синтаксис", "двоеточ", "скобк"),
        "runtime_error": ("ошибк", "исключ", "делен", "выполнен"),
    }
    issue_checks = [{"tag": tag, "detected": any(term in text for term in issue_terms.get(tag, (tag,)))} for tag in case.get("issue_tags", [])]
    recommendation_text = " ".join(str(item) for item in claim.get("recommended_topics", [])).lower()
    recommendation_checks = [{"tag": tag, "detected": any(term in recommendation_text for term in issue_terms.get(tag, (tag,)))} for tag in case.get("recommendation_tags", [])]
    return {
        "score_correct": score_match,
        "criterion_comparisons": comparisons,
        "issue_tag_checks": issue_checks,
        "unexpected_mistake_claim": not case.get("issue_tags") and bool(claim.get("mistakes")),
        "recommendation_tag_checks": recommendation_checks,
    }


def _write_progress(report: dict[str, Any]) -> None:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _aggregate(report: dict[str, Any]) -> dict[str, Any]:
    arms = {}
    expected_judge_scores = 0
    judge_score_correct = 0
    for arm in ("without_code_judge", "with_code_judge"):
        rows = [item[arm] for item in report["cases"]]
        score_metrics = [item["metrics"]["score_correct"] for item in rows]
        criterion_metrics = [check for item in rows for check in item["metrics"]["criterion_comparisons"]]
        issue_checks = [check for item in rows for check in item["metrics"]["issue_tag_checks"]]
        recommendation_checks = [check for item in rows for check in item["metrics"]["recommendation_tag_checks"]]
        arms[arm] = {
            "score_correct": sum(score_metrics), "score_total": len(score_metrics),
            "criterion_correct": sum(check["correct"] for check in criterion_metrics), "criterion_total": len(criterion_metrics),
            "issue_tags_detected": sum(check["detected"] for check in issue_checks), "issue_tag_total": len(issue_checks),
            "recommendation_tags_detected": sum(check["detected"] for check in recommendation_checks), "recommendation_tag_total": len(recommendation_checks),
            "unexpected_mistake_claims": sum(item["metrics"]["unexpected_mistake_claim"] for item in rows),
            "code_judge_conflicts": sum(bool(item["quality"].get("code_judge_conflict")) for item in rows),
            "manual_reviews": sum(item["authoritative_result"].get("grading_status") == "manual_review" for item in rows),
            "total_attempts": sum(item["attempt_count"] for item in rows),
            "retries": sum(max(0, item["attempt_count"] - 1) for item in rows),
            "total_duration_ms": sum(item["duration_ms"] or 0 for item in rows),
            "mean_duration_ms": round(sum(item["duration_ms"] or 0 for item in rows) / max(1, len(rows))),
            "usage": {key: sum((item.get("usage") or {}).get(key) or 0 for item in rows) for key in ("full_input_tokens", "prompt_tokens", "precached_prompt_tokens", "completion_tokens", "total_tokens")},
            "authoritative_score_correct": sum(
                (
                    pair[arm]["authoritative_result"].get("score_awarded") is None
                    if pair["case"].get("expected_score") is None
                    else pair[arm]["authoritative_result"].get("score_awarded") is not None
                    and abs(float(pair[arm]["authoritative_result"]["score_awarded"]) - float(pair["case"]["expected_score"])) < 0.001
                )
                for pair in report["cases"]
            ),
        }
    for item in report["cases"]:
        expected = item["case"].get("expected_score")
        expected_judge_scores += 1
        rubric = item["code_judge"]["rubric"]
        if expected is None:
            judge_score_correct += rubric["unconfirmed_max_score"] > 0 or bool(item["with_code_judge"]["quality"].get("code_judge_conflict"))
        else:
            judge_score_correct += rubric["unconfirmed_max_score"] == 0 and abs(float(rubric["confirmed_score"]) - float(expected)) < 0.001
    return {"model_claims": arms, "code_judge_score_correct": judge_score_correct, "code_judge_score_total": expected_judge_scores}


def main() -> int:
    control = _load_control()
    from app import create_app, db
    from app.ai_lab.code_judge import ensure_seeded_test_sets, run_request
    from app.ai_lab.config import ai_lab_limits
    from app.ai_lab.service import ensure_initial_prompt
    from app.ai_lab.provider import GigaChatProvider, gigachat_request_queue, is_local_ai_lab_enabled, provider_settings
    from app.ai_lab.scenarios import get_scenario
    from app.ai_lab.service import _count_recent_runs, _now_utc, run_experiment
    from core.db_models import User

    application = create_app()
    with application.app_context():
        if db.engine.dialect.name != "sqlite" or not is_local_ai_lab_enabled():
            raise RuntimeError("Контрольная серия разрешена только в локальной AI Lab на SQLite.")
        settings = provider_settings()
        if not settings.get("configured"):
            raise RuntimeError("Локальный GigaChat не настроен.")
        model = control["model"]
        provider = GigaChatProvider(settings)
        with gigachat_request_queue.request("Проверка модели контрольной серии"):
            available_models = provider.list_models()
        if model not in available_models:
            raise RuntimeError(f"Модель {model} отсутствует в фактическом каталоге GigaChat.")
        actor = User.query.filter_by(username="creator").first()
        if actor is None:
            raise RuntimeError("В локальной базе не найдена административная учётная запись AI Lab.")
        per_user, total = _count_recent_runs(actor.id, _now_utc())
        limits = ai_lab_limits()
        if per_user + 40 > limits["runs_per_admin_per_hour"] or total + 40 > limits["runs_per_lab_per_hour"]:
            raise RuntimeError("Текущие локальные лимиты не оставляют квоту для 40 парных запусков.")
        runner_sets = ensure_seeded_test_sets()
        suites = {item["scenario_id"]: item for item in runner_sets}
        scenario = get_scenario("py-digit-sum-16")
        prompt = ensure_initial_prompt()
        diagnostics = __import__("app.ai_lab.code_judge_runner_client", fromlist=["runner_diagnostics"]).runner_diagnostics()
        if not diagnostics.get("ready") or diagnostics.get("secure_profile_verified") is not True:
            raise RuntimeError("Изолированный Runner не прошёл проверку безопасности.")
        report = {
            "name": control["name"], "version": control["version"],
            "fixture_sha256": CONTROL_SHA256, "model": model,
            "prompt_version": prompt.version_no,
            "assignment_id": control["assignment_id"], "assignment_version": control["assignment_version"],
            "started_at": datetime.now(timezone.utc).isoformat(),
            "runner_profile": {"secure_profile_verified": True, "runner_version": diagnostics.get("runner_version"), "network": "disabled", "parallelism": 1},
            "cases": [],
        }
        _write_progress(report)
        for index, case in enumerate(control["cases"], 1):
            suite = suites[case.get("suite", control["suite"])]
            code_run, _ = run_request(actor.id, {
                "request_key": str(uuid.uuid4()), "run_type": "submit",
                "test_set_id": suite["id"], "test_set_version": suite["test_set_version"],
                "test_set": suite, "code": case["code"],
            })
            if not code_run.get("result", {}).get("complete"):
                raise RuntimeError(f"{case['id']}: Code Judge не завершил полный изолированный набор: {code_run.get('technical_error')}")
            judge_rubric = code_run["result"]["rubric"]
            judge_case = {
                "id": case["id"], "status": code_run["status"], "passed": code_run["result"]["passed"],
                "total": code_run["result"]["total"], "duration_ms": code_run.get("duration_ms"),
                "test_set_id": code_run["test_set_id"], "test_set_version": code_run["test_set_version"],
                "rubric_version": suite["rubric_version"], "rubric": judge_rubric,
            }
            pair: dict[str, Any] = {"case": {key: case[key] for key in ("id", "expected_score", "criterion_scores", "issue_tags", "recommendation_tags") if key in case}, "code_judge": judge_case}
            base_input = {
                "condition": scenario["condition"],
                "student_solution": case["code"],
                "reference_answer": "def digit_sum(n):\n    return sum(int(char) for char in str(n))",
                "criteria": scenario["criteria"],
                "max_score": scenario["max_score"],
                "additional_instructions": "",
            }
            for arm in ("without_code_judge", "with_code_judge"):
                experiment = run_experiment(actor_user_id=actor.id, payload={
                    "request_key": str(uuid.uuid4()),
                    "scenario_id": scenario["id"],
                    "model": model,
                    "prompt_version_id": prompt.id,
                    "input": base_input,
                    **({"code_judge_run_id": code_run["id"]} if arm == "with_code_judge" else {}),
                }, provider=provider)
                summary = _result_summary(experiment)
                summary["metrics"] = _prediction_metrics(summary, case, control["criteria"])
                pair[arm] = summary
            report["cases"].append(pair)
            report["completed_pairs"] = index
            _write_progress(report)
            print(f"{index:02d}/20 {case['id']} · Judge {judge_case['passed']}/{judge_case['total']} · AI pairs saved", flush=True)
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        report["metrics"] = _aggregate(report)
        _write_progress(report)
        print(f"REPORT={RESULT_PATH}", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
