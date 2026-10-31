"""Run the frozen Sprint 7 synthetic paired benchmark once, with a durable call ledger."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from app import create_app, db
from app.ai_lab.benchmark import append_run_records, load_frozen_manifest, load_run_records, run_cases
from app.ai_lab.code_judge import ensure_seeded_test_sets, run_request
from app.ai_lab.code_judge_runner_client import runner_diagnostics
from app.ai_lab.course import COURSE_ANALYSIS_PROMPT, COURSE_ANALYSIS_PROMPT_VERSION, analyze_course, course_analysis_chunks, validate_course_input
from app.ai_lab.lesson_intelligence import LESSON_PROMPT, LESSON_PROMPT_VERSION, analyze_lesson, lesson_analysis_chunks, validate_lesson_request
from app.ai_lab.prompts import SEMANTIC_RELIABILITY_PROMPT_TEXT
from app.ai_lab.provider import GigaChatProvider, provider_settings
from app.ai_lab.scenarios import get_scenario
from app.ai_lab.service import create_prompt_version, ensure_initial_prompt, run_experiment
from core.db_models import AiLabPromptVersion
from scripts.run_ai_lab_sprint6_benchmark import CachedModelCatalogProvider, _serialize_experiment


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests/fixtures/ai_lab_sprint7_manifest_v1.json"
PREVIOUS = ROOT / "tests/fixtures/ai_lab_sprint6_manifest_v1.json"
RESULTS = ROOT / "docs/modules/artifacts/ai_lab_sprint7_live_run.jsonl"
RESERVATIONS = ROOT / "docs/modules/artifacts/ai_lab_sprint7_requests.jsonl"
ACTOR = 987655


def _sha(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _resolved_cases(dataset: dict, previous: dict) -> dict[str, dict]:
    previous_cases = {item["case_id"]: item for item in previous["cases"]}
    resolved = {}
    for item in dataset["cases"]:
        case = dict(item)
        source_id = case["input"].get("frozen_sprint6_case_id")
        if source_id:
            source = previous_cases.get(source_id)
            if source is None or source["module"] != case["module"] or source["split"] == "holdout":
                raise RuntimeError(f"Invalid frozen source for {case['case_id']}")
            case["input"] = source["input"]
        resolved[case["case_id"]] = case
    return resolved


def _assert_frozen(manifest: dict, cases: dict[str, dict]) -> None:
    expected = {
        "homework_prompt_sha256": _sha(SEMANTIC_RELIABILITY_PROMPT_TEXT),
        "course_prompt_sha256": _sha(COURSE_ANALYSIS_PROMPT),
        "lesson_prompt_sha256": _sha(LESSON_PROMPT),
        "course_prompt_version": COURSE_ANALYSIS_PROMPT_VERSION,
        "lesson_prompt_version": LESSON_PROMPT_VERSION,
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise RuntimeError("Frozen instruction version/hash drift; no request allowed.")
    ids = manifest["live_case_ids"]
    if len(ids) != 12 or len(ids) > manifest["maximum_logical_generations"] or set(ids) != set(cases):
        raise RuntimeError("Frozen case/budget drift; no request allowed.")
    if any(case["split"] == "holdout" for case in cases.values()):
        raise RuntimeError("Sprint 7 live plan must not include holdout cases.")
    for case in cases.values():
        if case["module"] == "ai_course" and len(course_analysis_chunks(validate_course_input(case["input"]))) != 1:
            raise RuntimeError("Course case exceeds one planned generation.")
        if case["module"] == "ai_lesson_intelligence":
            normalized, segments = validate_lesson_request(case["input"])
            if len(lesson_analysis_chunks(segments, normalized["lesson_id"], normalized["lesson_version"])) != 1:
                raise RuntimeError("Lesson case exceeds one planned generation.")


def _judge_runs(cases: dict[str, dict]) -> tuple[dict[str, dict], dict]:
    diagnostics = runner_diagnostics()
    if diagnostics.get("ready") is not True or diagnostics.get("secure_profile_verified") is not True:
        raise RuntimeError("Secure Code Judge is unavailable; no model request allowed.")
    saved = next((item for item in ensure_seeded_test_sets() if item["scenario_id"] == "classify-logic-errors"), None)
    if saved is None:
        raise RuntimeError("Frozen Code Judge test set is missing.")
    runs = {}
    for case in cases.values():
        if case["module"] != "ai_homework":
            continue
        pair_id = case["input"]["pair_id"]
        if pair_id in runs:
            continue
        run, _ = run_request(ACTOR, {
            "request_key": str(uuid.uuid5(uuid.NAMESPACE_URL, f"boostudy-sprint7-judge:{pair_id}")),
            "run_type": "submit", "test_set_id": saved["id"],
            "test_set_version": saved["test_set_version"], "test_set": saved,
            "code": case["input"]["solution"],
        })
        if run["status"] not in {"accepted", "wrong_answer"} or not (run.get("result") or {}).get("complete"):
            raise RuntimeError(f"Code Judge incomplete for {pair_id}: {run['status']}")
        expected = case["expert_expectation"]
        rubric = run["result"]["rubric"]
        scores = {item["assignment_criterion_id"]: item["score_awarded"] for item in rubric["criteria"]}
        if rubric["confirmed_score"] != expected["score"] or scores != expected["criterion_scores"]:
            raise RuntimeError(f"Judge result differs from frozen expert expectation for {pair_id}: {scores}")
        runs[pair_id] = run
    return runs, diagnostics


def _reserve(case_id: str, manifest: dict) -> None:
    RESERVATIONS.parent.mkdir(parents=True, exist_ok=True)
    with _reservation_lock():
        existing = []
        if RESERVATIONS.exists():
            existing = [json.loads(line) for line in RESERVATIONS.read_text(encoding="utf-8").splitlines() if line.strip()]
        if case_id in {row["case_id"] for row in existing}:
            raise RuntimeError(f"Case {case_id} already reserved; refusing duplicate generation.")
        if len(existing) >= manifest["maximum_logical_generations"]:
            raise RuntimeError("Sprint 7 generation budget exhausted.")
        with RESERVATIONS.open("a", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps({"case_id": case_id, "dataset_sha256": manifest["dataset_sha256"],
                                     "reservation_id": str(uuid.uuid4())}, ensure_ascii=False) + "\n")
            output.flush()
            os.fsync(output.fileno())


@contextmanager
def _reservation_lock():
    lock_path = RESERVATIONS.with_suffix(".lock")
    with lock_path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + 5
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    raise RuntimeError("Sprint 7 request ledger is busy; no request was sent.")
                time.sleep(0.05)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--verify-judge", action="store_true")
    mode.add_argument("--run-live", action="store_true")
    parser.add_argument("--database", default=str(Path(tempfile.gettempdir()) / "boostudy-ai-lab-sprint7.sqlite"))
    args = parser.parse_args()

    manifest, dataset = load_frozen_manifest(MANIFEST)
    _, previous = load_frozen_manifest(PREVIOUS)
    cases = _resolved_cases(dataset, previous)
    _assert_frozen(manifest, cases)
    if args.plan:
        print(json.dumps({"dataset_sha256": dataset["fixture_sha256"], "protocol_sha256": manifest["protocol_sha256"],
                          "case_ids": manifest["live_case_ids"], "maximum_generations": manifest["maximum_logical_generations"]}, indent=2))
        return 0

    database = Path(args.database).resolve()
    if Path(tempfile.gettempdir()).resolve() not in database.parents:
        parser.error("Isolated benchmark DB must be in the system temp directory.")
    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False,
                      "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database.as_posix()}",
                      "RUN_ENV": "local", "AI_LAB_ENABLED": True})
    with app.app_context():
        db.create_all()
        judge_runs, diagnostics = _judge_runs(cases)
        if args.verify_judge:
            print(json.dumps({"secure_profile_verified": diagnostics["secure_profile_verified"],
                              "judge": {pair: {"run_id": run["id"], "status": run["status"],
                                               "rubric": run["result"]["rubric"]} for pair, run in judge_runs.items()}},
                             ensure_ascii=False, indent=2))
            return 0

        prompt = AiLabPromptVersion.query.filter_by(version_no=manifest["homework_prompt_version_no"]).first()
        if prompt is None:
            latest = ensure_initial_prompt()
            if latest.version_no != 1:
                raise RuntimeError("Unexpected saved prompt history.")
            prompt = create_prompt_version(SEMANTIC_RELIABILITY_PROMPT_TEXT, ACTOR)
        if prompt.version_no != manifest["homework_prompt_version_no"] or _sha(prompt.content) != manifest["homework_prompt_sha256"]:
            raise RuntimeError("Saved Homework prompt differs from frozen manifest.")
        settings = provider_settings()
        if not settings.get("configured") or not settings.get("ca_bundle_file_exists"):
            raise RuntimeError("GigaChat or trusted CA bundle is unavailable.")
        provider = CachedModelCatalogProvider(GigaChatProvider(settings))
        if manifest["model_alias"] not in provider.list_models():
            raise RuntimeError("Frozen model is not available in live catalogue.")

        prior = load_run_records(RESULTS) if RESULTS.exists() else []
        recorded = {row["case_id"] for row in prior}
        reserved = {json.loads(line)["case_id"] for line in RESERVATIONS.read_text(encoding="utf-8").splitlines() if line.strip()} if RESERVATIONS.exists() else set()
        if recorded - reserved:
            raise RuntimeError("Result ledger contains unreserved calls; stop for manual audit.")
        for case_id in manifest["live_case_ids"]:
            if case_id in reserved:
                continue
            case = cases[case_id]
            _reserve(case_id, manifest)

            def execute(_case: dict) -> dict:
                data = case["input"]
                if case["module"] == "ai_homework":
                    scenario = get_scenario(data["scenario_id"])
                    payload = {
                        "request_key": str(uuid.uuid5(uuid.NAMESPACE_URL, f"boostudy-sprint7-ai:{case_id}")),
                        "scenario_id": scenario["id"], "model": manifest["model_alias"],
                        "prompt_version_id": prompt.id,
                        "input": {"condition": scenario["condition"], "student_solution": data["solution"],
                                  "reference_answer": scenario["reference_answer"], "criteria": scenario["criteria"],
                                  "max_score": scenario["max_score"]},
                    }
                    if data["mode"] == "hybrid":
                        payload["code_judge_run_id"] = judge_runs[data["pair_id"]]["id"]
                    record = run_experiment(actor_user_id=ACTOR, payload=payload, provider=provider,
                                            max_completion_attempts=1)
                elif case["module"] == "ai_course":
                    record = analyze_course(data, actor_user_id=ACTOR, provider=provider)
                else:
                    record = analyze_lesson(data, actor_user_id=ACTOR, provider=provider)
                result = _serialize_experiment(record, case["module"])
                if case["module"] == "ai_homework":
                    judge = judge_runs[data["pair_id"]]
                    result["comparison_mode"] = data["mode"]
                    result["judge_run_id"] = judge["id"]
                    result["judge_score"] = judge["result"]["rubric"]["confirmed_score"]
                    result["judge_criteria"] = judge["result"]["rubric"]["criteria"]
                return result

            rows = run_cases(dataset, {case["module"]: execute}, case_ids=[case_id], run_id="sprint7-frozen-v1")
            append_run_records(RESULTS, rows)
            execution = rows[0]["execution"]
            print(json.dumps({"case_id": case_id, "status": execution.get("status"),
                              "attempt_count": execution.get("attempt_count"),
                              "error_code": execution.get("error_code"),
                              "execution_error": rows[0].get("execution_error")}, ensure_ascii=False), flush=True)
            if rows[0].get("execution_error") or execution.get("transport_status") != "received":
                break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
