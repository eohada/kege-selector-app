"""Run the frozen synthetic rubric cases with the local GigaChat configuration."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from app import create_app
from app.ai_lab.rubric_builder import generate_rubric, get_rubric
from core.db_models import AiLabExperiment

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/ai_lab_rubric_builder_v04_cases.json"
OUTPUT = ROOT / "artifacts/ai_lab/rubric_builder_v04_benchmark_results.json"
MODEL = "GigaChat-3-Pro"


def write_report(report: dict) -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    fixture_bytes = FIXTURE.read_bytes()
    fixture = json.loads(fixture_bytes)
    report = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else {
        "name": "AI Rubric Builder v0.4 synthetic benchmark",
        "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
        "prompt_version": fixture["prompt_version"], "model": MODEL, "cases": [],
    }
    if report["fixture_sha256"] != hashlib.sha256(fixture_bytes).hexdigest():
        raise RuntimeError("Frozen benchmark fixture changed; keep previous results separate.")
    completed = {row["id"] for row in report["cases"]}
    app = create_app()
    with app.app_context():
        previous = AiLabExperiment.query.order_by(AiLabExperiment.id.desc()).first()
        if previous is None or previous.actor_user_id is None:
            raise RuntimeError("Local admin experiment is required to attribute benchmark runs.")
        actor = previous.actor_user_id
        for partition in ("development", "control"):
            for case in fixture[partition]:
                if case["id"] in completed:
                    continue
                start = time.monotonic()
                if case.get("existing_rubric_id"):
                    rubric = get_rubric(case["existing_rubric_id"])
                    if rubric is None:
                        raise RuntimeError(f"Existing rubric {case['existing_rubric_id']} is missing")
                else:
                    rubric = generate_rubric(case["task"], MODEL, actor)
                row = {
                    "id": case["id"], "partition": partition,
                    "expert_expectation": case["expert_expectation"],
                    "duration_ms": round((time.monotonic() - start) * 1000),
                    "rubric_id": rubric["id"], "status": rubric["status"],
                    "validation": rubric["validation"],
                    "criteria": rubric["criteria"],
                    "warnings_from_model": (rubric["raw_proposal"] or {}).get("warnings") or [],
                    "suggested_test_count": len(rubric["proposed_tests"]),
                    "usage": rubric["generation"]["usage"],
                }
                report["cases"].append(row)
                write_report(report)
                print(case["id"], "rubric", rubric["id"], "valid", rubric["validation"]["ok"],
                      "criteria", [(item["title"], item["max_score"]) for item in rubric["criteria"]],
                      "warnings", len(row["warnings_from_model"]), flush=True)
    print("RESULT", OUTPUT)


if __name__ == "__main__":
    main()
