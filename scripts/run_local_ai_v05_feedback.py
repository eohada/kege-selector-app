"""Replay frozen synthetic Code Judge evidence with a new versioned teaching prompt."""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path

from app import create_app, db
from app.ai_lab.service import EDITABLE_INPUT_FIELDS, run_experiment
from core.db_models import AiLabExperiment, AiLabPromptVersion

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifacts/ai_lab/code_judge_v03_benchmark_results.json"
OUTPUT = ROOT / "artifacts/ai_lab/ai_v05_feedback_results.json"


def main() -> None:
    source = SOURCE.read_bytes()
    frozen = json.loads(source)
    digest = hashlib.sha256(source).hexdigest()
    report = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else {
        "source_sha256": digest, "model": frozen["model"], "prompt_version": 6, "cases": [],
    }
    if report["source_sha256"] != digest:
        raise RuntimeError("Frozen source changed after first replay.")
    completed = {row["id"] for row in report["cases"]}
    app = create_app()
    with app.app_context():
        prompt = AiLabPromptVersion.query.filter_by(version_no=6).first()
        if not prompt or "Педагогическая калибровка v0.6" not in prompt.content:
            raise RuntimeError("Version 6 of the pedagogical prompt is missing.")
        for old in frozen["cases"]:
            case_id = old["case"]["id"]
            if case_id in completed:
                continue
            prior = db.session.get(AiLabExperiment, old["with_code_judge"]["experiment_id"])
            judge_id = ((prior.quality_json or {}).get("technical") or {}).get("code_judge", {}).get("run_id")
            payload = {"request_key": str(uuid.uuid4()), "scenario_id": prior.scenario_id,
                       "model": frozen["model"], "prompt_version_id": prompt.id,
                       "input": {key: value for key, value in prior.input_snapshot.items() if key in EDITABLE_INPUT_FIELDS},
                       "code_judge_run_id": judge_id}
            started = time.monotonic()
            experiment = run_experiment(actor_user_id=prior.actor_user_id, payload=payload)
            quality = experiment.quality_json or {}
            technical = quality.get("technical") or {}
            attempts = technical.get("attempts") or []
            try:
                model_claim = json.loads(attempts[-1]["response"]) if attempts else {}
            except (ValueError, TypeError, KeyError):
                model_claim = {}
            report["cases"].append({
                "id": case_id, "experiment_id": experiment.id, "status": experiment.status,
                "validation_status": experiment.validation_status,
                "expected_score": old["case"]["expected_score"],
                "score": (experiment.result_json or {}).get("score_awarded"),
                "model_score": model_claim.get("score_awarded"),
                "model_criterion_scores": model_claim.get("criterion_scores"),
                "score_match": (quality.get("score_match") or {}).get("status"),
                "criteria_alignment": (quality.get("criteria_alignment") or {}).get("status"),
                "error_detection": (quality.get("error_detection") or {}).get("status"),
                "conflict": quality.get("code_judge_conflict"),
                "retry": (technical.get("semantic_validation") or {}).get("retry_used"),
                "usage": technical.get("usage"), "duration_ms": experiment.duration_ms,
                "wall_duration_ms": round((time.monotonic() - started) * 1000),
                "recommended_topics": (experiment.result_json or {}).get("recommended_topics"),
                "student_feedback": (experiment.result_json or {}).get("student_feedback"),
                "teacher_feedback": (experiment.result_json or {}).get("teacher_feedback"),
                "adaptive": ((quality.get("pedagogical_layers") or {}).get("adaptive") or []),
            })
            OUTPUT.parent.mkdir(parents=True, exist_ok=True)
            OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(case_id, experiment.status, "score", (experiment.result_json or {}).get("score_awarded"), flush=True)


if __name__ == "__main__":
    main()
