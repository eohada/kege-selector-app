"""Frozen 30-case local synthetic rubric series; never reads student submissions."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from app import create_app
from app.ai_lab.rubric_builder import PROMPT_VERSION, generate_rubric
from app.ai_lab.rubric_builder import RubricError
from app.ai_lab.provider import ProviderError
from core.db_models import AiLabExperiment

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/ai_lab_v05_cases.json"
OUTPUT = ROOT / f"artifacts/ai_lab/ai_v05_rubric_results_{PROMPT_VERSION.rsplit('-', 1)[-1].replace('.', '')}.json"


def main() -> None:
    source = FIXTURE.read_bytes()
    fixture = json.loads(source)
    digest = hashlib.sha256(source).hexdigest()
    if len(fixture["development"]) + len(fixture["control"]) < 30:
        raise RuntimeError("The frozen synthetic suite must contain at least 30 tasks.")
    report = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else {
        "fixture_sha256": digest, "model": fixture["model"], "prompt_version": PROMPT_VERSION,
        "cases": [],
    }
    if report["fixture_sha256"] != digest:
        raise RuntimeError("Fixture changed after the first run; preserve the old report.")
    completed = {row["id"] for row in report["cases"]}
    app = create_app()
    with app.app_context():
        previous = AiLabExperiment.query.order_by(AiLabExperiment.id.desc()).first()
        if not previous or previous.actor_user_id is None:
            raise RuntimeError("A local administrator experiment is needed to attribute calls.")
        for partition in ("development", "control"):
            for case in fixture[partition]:
                if case["id"] in completed:
                    continue
                task = {
                    "title": case["title"], "subject": "Информатика", "topic": case["title"],
                    "answer_type": "python", "condition": case["condition"],
                    "reference_answer": case["reference"], "teacher_requirements": case["requirements"],
                    "max_score": sum(weight for _, weight in case["criteria"]),
                }
                started = time.monotonic()
                try:
                    rubric = generate_rubric(task, fixture["model"], previous.actor_user_id)
                except (RubricError, ProviderError) as exc:
                    report["cases"].append({
                        "id": case["id"], "partition": partition, "status": "failed",
                        "error_code": getattr(exc, "code", type(exc).__name__),
                        "error": str(exc), "expected_criteria": case["criteria"],
                        "expected_score": case["expected_score"], "expected_errors": case["errors"],
                        "duration_ms": round((time.monotonic() - started) * 1000),
                        "usage": None,
                    })
                    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
                    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                    print(case["id"], "failed", getattr(exc, "code", type(exc).__name__), flush=True)
                    continue
                report["cases"].append({
                    "id": case["id"], "partition": partition, "rubric_id": rubric["id"],
                    "expected_criteria": case["criteria"], "expected_score": case["expected_score"],
                    "expected_errors": case["errors"], "generated_criteria": rubric["criteria"],
                    "validation": rubric["validation"], "warnings": (rubric["raw_proposal"] or {}).get("warnings", []),
                    "usage": rubric["generation"].get("usage"), "duration_ms": round((time.monotonic() - started) * 1000),
                })
                OUTPUT.parent.mkdir(parents=True, exist_ok=True)
                OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print(case["id"], "saved", rubric["id"], "valid", rubric["validation"]["ok"], flush=True)


if __name__ == "__main__":
    main()
