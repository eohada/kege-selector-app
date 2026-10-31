"""Run the frozen Sprint 6 synthetic benchmark through BooStudy's AI Lab services."""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from app import create_app, db
from app.ai_lab.analytics import build_analytics_snapshot, synthetic_demo_events
from app.ai_lab.benchmark import (
    append_run_records,
    load_frozen_manifest,
    load_run_records,
    run_cases,
)
from app.ai_lab.course import analyze_course, course_analysis_chunks, validate_course_input
from app.ai_lab.lesson_intelligence import analyze_lesson, lesson_analysis_chunks, parse_transcript, validate_lesson_request
from app.ai_lab.practice import recommend_practice
from app.ai_lab.provider import GigaChatProvider, provider_settings
from app.ai_lab.scenarios import list_python_assignments, list_scenarios
from app.ai_lab.service import ensure_initial_prompt, run_experiment
from core.db_models import AiLabPromptVersion


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests/fixtures/ai_lab_sprint6_manifest_v1.json"
LIVE_RUN_LEDGER = ROOT / "docs/modules/artifacts/ai_lab_sprint6_live_run.jsonl"
ACTOR_USER_ID = 987654


class CachedModelCatalogProvider:
    """Share one model-catalog result for the frozen serial benchmark run."""

    name = "gigachat"

    def __init__(self, provider: GigaChatProvider):
        self._provider = provider
        self._models: list[str] | None = None

    def list_models(self) -> list[str]:
        if self._models is None:
            self._models = self._provider.list_models()
        return list(self._models)

    def __getattr__(self, name: str):
        return getattr(self._provider, name)


def _load_live_ledger_records(output_path: Path) -> list[dict[str, Any]]:
    """Load the canonical live ledger even when a caller selects another output path."""
    rows_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for path in {output_path.resolve(), LIVE_RUN_LEDGER.resolve()}:
        if not path.exists():
            continue
        for row in load_run_records(path):
            key = (str(row.get("dataset_id") or ""), str(row.get("run_id") or ""), str(row.get("case_id") or ""))
            rows_by_key[key] = row
    return list(rows_by_key.values())


def _previous_generation_state(records: list[dict[str, Any]], dataset_id: str) -> tuple[set[str], int]:
    attempted_case_ids: set[str] = set()
    used_budget = 0
    for row in records:
        if row.get("dataset_id") != dataset_id:
            continue
        execution = row.get("execution") or {}
        if row.get("module") not in {"ai_homework", "ai_course", "ai_lesson_intelligence"}:
            continue
        attempt_count = int(execution.get("attempt_count") or 0)
        case_id = str(row.get("case_id") or "")
        if case_id and attempt_count > 0:
            attempted_case_ids.add(case_id)
            used_budget += attempt_count
    return attempted_case_ids, used_budget


def _attempts(record: Any) -> list[dict[str, Any]]:
    quality = getattr(record, "quality_json", None) or {}
    technical = quality.get("technical") or {}
    return list(quality.get("generation_attempts") or quality.get("attempts") or technical.get("attempts") or [])


def _serialize_experiment(record: Any, module: str) -> dict[str, Any]:
    quality = getattr(record, "quality_json", None) or {}
    technical = quality.get("technical") or {}
    attempts = _attempts(record)
    prompt = getattr(record, "prompt_snapshot", None) or quality.get("prompt_snapshot")
    prompt_version = quality.get("prompt_version")
    if module == "ai_homework":
        prompt_version = getattr(record, "prompt_version_no", None)
    params = quality.get("generation_parameters") or technical.get("generation_parameters")
    if not params and attempts:
        params = attempts[-1].get("generation_parameters")
    usage = quality.get("usage") or technical.get("usage")
    if not usage and attempts:
        usage = attempts[-1].get("usage")
    provider_payload_hash = technical.get("payload_sha256")
    if not provider_payload_hash and attempts:
        provider_payload_hash = attempts[-1].get("payload_sha256") or attempts[-1].get("request_payload_sha256")
    transport_status = "received" if attempts and getattr(record, "status", "") in {"succeeded", "invalid_response"} else "error"
    return {
        "status": getattr(record, "status", None),
        "model": getattr(record, "model", None) or (attempts[-1].get("model") if attempts else None),
        "model_version": (attempts[-1].get("model_version") or attempts[-1].get("model") if attempts else getattr(record, "model", None)),
        "prompt_version": prompt_version,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest() if isinstance(prompt, str) else quality.get("prompt_sha256"),
        "input_snapshot_sha256": quality.get("input_hash"),
        "payload_sha256": provider_payload_hash,
        "provider_payload_id": (technical.get("payload_id") or attempts[-1].get("payload_id")) if attempts else None,
        "generation_parameters": params,
        "usage": usage or {
            "full_input_tokens": getattr(record, "input_tokens", None),
            "completion_tokens": getattr(record, "output_tokens", None),
        },
        "attempt_count": len(attempts),
        "transport_status": transport_status,
        "structural_validation": getattr(record, "validation_status", None),
        "duration_ms": getattr(record, "duration_ms", None),
        "full_response": getattr(record, "raw_response", None),
        "result": getattr(record, "result_json", None),
        "technical_evidence": quality.get("learning_evidence") or quality.get("structural_findings"),
        "semantic_review": quality.get("semantic_validation") or technical.get("semantic_validation"),
        "error_code": getattr(record, "error_code", None),
        "error_message": getattr(record, "error_message", None),
        "experiment_id": getattr(record, "id", None),
    }


def _provider_execution(record: Any, module: str) -> dict[str, Any]:
    return _serialize_experiment(record, module)


def _build_executors(
    manifest: dict[str, Any], prompt_row: AiLabPromptVersion, provider: Any, run_id: str,
) -> dict[str, Any]:
    model = str(manifest["model_alias"])

    def homework(case: dict[str, Any]) -> dict[str, Any]:
        data = case["input"]
        scenarios = list_scenarios()
        scenario = next((item for item in scenarios if item["id"] == "py-arithmetic-02"), None)
        if scenario is None:
            raise RuntimeError("Синтетический Python-сценарий AI Homework недоступен.")
        criteria = [f"{item['id']}: оценить только указанное поведение, максимум {item['max_points']} балл(а)."
                    for item in data["criteria"]]
        examples = json.dumps(data.get("public_examples", []), ensure_ascii=False)
        payload = {
            "request_key": str(uuid.uuid5(uuid.NAMESPACE_URL, f"boostudy-sprint6:{run_id}:{case['case_id']}")),
            "scenario_id": scenario["id"],
            "model": model,
            "prompt_version_id": prompt_row.id,
            "input": {
                "condition": data["task"],
                "student_solution": data["solution"],
                "reference_answer": "Оцени по условию и публичным примерам; допустимы любые эквивалентные алгоритмы.",
                "criteria": criteria,
                "max_score": sum(float(item["max_points"]) for item in data["criteria"]),
                "additional_instructions": f"Публичные примеры: {examples}",
            },
        }
        record = run_experiment(actor_user_id=ACTOR_USER_ID, payload=payload, provider=provider,
                                max_completion_attempts=1)
        return _provider_execution(record, "ai_homework")

    def course(case: dict[str, Any]) -> dict[str, Any]:
        return _provider_execution(analyze_course(case["input"], actor_user_id=ACTOR_USER_ID, provider=provider), "ai_course")

    def lesson(case: dict[str, Any]) -> dict[str, Any]:
        return _provider_execution(analyze_lesson(case["input"], actor_user_id=ACTOR_USER_ID, provider=provider), "ai_lesson_intelligence")

    def analytics(case: dict[str, Any]) -> dict[str, Any]:
        data = case["input"]
        template = synthetic_demo_events()[0]
        events = []
        for index, raw in enumerate(data["events"]):
            event_id = str(raw.get("event_id") or f"{case['case_id']}:{index}")
            skill_id = str(raw.get("skill_id") or "")
            evidence_status = str(raw.get("evidence_status") or "insufficient_data")
            earned = raw.get("score_awarded")
            maximum = raw.get("maximum_score")
            if earned is None or maximum is None:
                criterion_status, earned = "insufficient_data", None
            else:
                criterion_status = "met" if float(earned) >= float(maximum) else "not_met"
            source_ref = str(raw.get("source_ref") or event_id)
            event = {
                **deepcopy(template),
                "event_id": event_id,
                "subject_id": data["subject_id"],
                "source_module": "ai_homework",
                "source_record_id": event_id,
                "assignment": {"id": str(raw.get("assignment_id") or f"synthetic:{case['case_id']}:{index}"),
                               "version": int(raw.get("assignment_version") or 1)},
                "skill_ids": [skill_id] if skill_id else [],
                "evidence_status": evidence_status,
                "error_codes": [str(raw["error_code"])] if raw.get("error_code") else [],
                "outcome": {"score": earned, "maximum": maximum, "status": "checked" if earned is not None else "unknown"},
                "criteria": ([{
                    "criterion_id": f"{skill_id}.synthetic-result",
                    "skill_id": skill_id,
                    "earned": earned,
                    "maximum": maximum,
                    "status": criterion_status,
                    "evidence_status": evidence_status,
                    "reason": "Результат преобразован из экспертно заданного синтетического примера.",
                    "source_refs": [source_ref],
                }] if skill_id else []),
                "provenance": {"source_ref": source_ref, "method": "synthetic benchmark fixture"},
            }
            events.append(event)
        unique = {event["event_id"]: event for event in events}
        return {"status": "succeeded", "result": build_analytics_snapshot(unique.values(), data["subject_id"]),
                "model": None, "prompt_version": None, "generation_parameters": None,
                "usage": None, "transport_status": "not_applicable", "structural_validation": "deterministic"}

    def practice(case: dict[str, Any]) -> dict[str, Any]:
        data = case["input"]
        subject_id = data["subject_id"]
        template = synthetic_demo_events()[0]
        events = []

        def observation(skill: str, index: int, passed: bool, kind: str) -> dict[str, Any]:
            event_id = f"{case['case_id']}:{skill}:{kind}:{index}"
            assignment_id = f"{case['case_id']}:{skill}:{kind}-assignment:{index}"
            source_ref = f"synthetic-code-judge:{case['case_id']}:{kind}:{index}"
            earned = 1 if passed else 0
            status = "met" if passed else "not_met"
            return {
                **deepcopy(template),
                "event_id": event_id,
                "subject_id": subject_id,
                "source_module": "ai_homework",
                "source_record_id": event_id,
                "assignment": {"id": assignment_id, "version": 1},
                "skill_ids": [skill],
                "topic_ids": [skill],
                "error_codes": [] if passed else ["synthetic.confirmed_failure"],
                "limitations": ["Синтетическое доказательство только для данного набора сценариев."],
                "outcome": {"score": earned, "maximum": 1, "status": "complete" if passed else "partial"},
                "criteria": [{
                    "criterion_id": f"{skill}.synthetic-observation",
                    "skill_id": skill,
                    "earned": earned,
                    "maximum": 1,
                    "status": status,
                    "evidence_status": "technical_confirmed",
                    "reason": "Синтетическая проверка Code Judge прошла." if passed else "Синтетическая проверка Code Judge выявила ошибку.",
                    "source_refs": [source_ref],
                }],
                "provenance": {"source_ref": source_ref, "method": "synthetic Code Judge fixture"},
            }

        for skill in data.get("confirmed_skill_failures", []):
            # Supply the minimum distinct observations Analytics needs before
            # it may set a skill to needs_support; a single fixture flag is not
            # itself a diagnosis or a guessed score.
            for index in range(3):
                events.append(observation(skill, index, False, "failed"))
        for skill in data.get("confirmed_prerequisite_skills", []):
            for index in range(3):
                events.append(observation(skill, index, True, "prerequisite"))
        snapshot = build_analytics_snapshot(events, subject_id)
        prerequisites = data.get("course_prerequisites", {})
        catalog = []
        outline_topics: dict[str, dict[str, Any]] = {}
        for item in data.get("available_assignments", []):
            assignment_id = item["assignment_id"]
            skill_id = item["skill_id"]
            topic = {
                "python.boundary_cases": "Пограничные условия",
                "python.iteration": "Циклы и строки",
                "python.functions": "Функции и аргументы",
            }.get(skill_id, skill_id.replace(".", " ").replace("_", " "))
            catalog.append({"assignment_id": assignment_id, "assignment_version": 1,
                            "title": f"Синтетическое задание {skill_id}", "topic": topic,
                            "difficulty": "synthetic", "type": "python"})
            outline_topics[skill_id] = {"topic_id": skill_id, "skill_id": skill_id,
                                        "assignment_ids": [assignment_id],
                                        "prerequisite_ids": list(prerequisites.get(skill_id, []))}
            for prerequisite_id in item.get("prerequisite_skill_ids", []):
                outline_topics.setdefault(prerequisite_id, {"topic_id": prerequisite_id, "skill_id": prerequisite_id,
                                                             "assignment_ids": [], "prerequisite_ids": []})
        outline = {"course_id": f"synthetic-course:{case['case_id']}", "course_version": 1,
                   "topics": list(outline_topics.values())}
        result = recommend_practice(snapshot, catalog, data.get("completed_assignment_ids", []), outline)
        return {"status": "succeeded", "result": result, "model": None, "prompt_version": None,
                "generation_parameters": None, "usage": None, "transport_status": "not_applicable",
                "structural_validation": "deterministic"}

    return {
        "ai_homework": homework,
        "ai_course": course,
        "ai_lesson_intelligence": lesson,
        "ai_analytics": analytics,
        "ai_practice": practice,
    }


def _planned_generations(case: dict[str, Any]) -> int:
    if case["module"] == "ai_homework":
        return 1
    if case["module"] == "ai_course":
        return len(course_analysis_chunks(validate_course_input(case["input"])))
    if case["module"] == "ai_lesson_intelligence":
        normalized, segments = validate_lesson_request(case["input"])
        return len(lesson_analysis_chunks(segments, normalized["lesson_id"], normalized["lesson_version"]))
    return 0


def _should_stop(execution: dict[str, Any]) -> bool:
    code = str(execution.get("error_code") or "").casefold()
    return any(marker in code for marker in ("auth", "credential", "quota", "rate_limit", "not_configured"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true", help="Print the frozen plan without connecting to GigaChat.")
    mode.add_argument("--run-live", action="store_true", help="Run the frozen synthetic cases once through local GigaChat.")
    mode.add_argument("--run-deterministic", action="store_true", help="Run Analytics and Practice fixture cases without GigaChat.")
    parser.add_argument("--database", default=str(Path(tempfile.gettempdir()) / "boostudy-ai-lab-sprint6.sqlite"))
    parser.add_argument("--output", default=str(ROOT / "docs/modules/artifacts/ai_lab_sprint6_live_run.jsonl"))
    parser.add_argument("--run-id", default=str(uuid.uuid4()), help="Reuse this ID to resume without duplicate generations.")
    args = parser.parse_args()

    manifest, dataset = load_frozen_manifest(MANIFEST)
    case_by_id = {case["case_id"]: case for case in dataset["cases"]}
    plan_rows = [{"case_id": case_id, "module": case_by_id[case_id]["module"],
                  "split": case_by_id[case_id]["split"], "planned_generations": _planned_generations(case_by_id[case_id])}
                 for case_id in manifest["live_case_ids"]]
    if sum(row["planned_generations"] for row in plan_rows) > manifest["maximum_logical_generations"]:
        raise RuntimeError("Зафиксированный план превышает бюджет live-генераций.")
    if args.plan:
        print(json.dumps({"dataset_sha256": dataset["fixture_sha256"], "protocol_sha256": manifest["protocol_sha256"],
                          "model_alias": manifest["model_alias"], "cases": plan_rows,
                          "planned_generations": sum(row["planned_generations"] for row in plan_rows),
                          "maximum_logical_generations": manifest["maximum_logical_generations"]},
                         ensure_ascii=False, indent=2))
        return 0

    if args.run_deterministic:
        case_ids = [case["case_id"] for case in dataset["cases"]
                    if case["module"] in {"ai_analytics", "ai_practice"}]
        database_path = Path(args.database).resolve()
        temp_root = Path(tempfile.gettempdir()).resolve()
        if temp_root not in database_path.parents:
            parser.error("Изолированная БД должна находиться внутри системного временного каталога.")
        app = create_app({
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
            "RUN_ENV": "local",
            "AI_LAB_ENABLED": True,
        })
        with app.app_context():
            db.create_all()
            executors = _build_executors(manifest, None, None, args.run_id)
            rows = run_cases(dataset, executors, case_ids=case_ids, allow_holdout=True, run_id=args.run_id)
        append_run_records(args.output, rows)
        print(json.dumps({"run_id": args.run_id, "case_records": len(rows),
                          "modules": sorted({row["module"] for row in rows}),
                          "generation_attempts": 0, "results_file": str(Path(args.output).resolve()),
                          "database_file": str(database_path)}, ensure_ascii=False, indent=2))
        return 0

    database_path = Path(args.database).resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if temp_root not in database_path.parents:
        parser.error("Изолированная БД должна находиться внутри системного временного каталога.")
    output_path = Path(args.output).resolve()

    existing_records = _load_live_ledger_records(output_path)
    already_called_case_ids, calls = _previous_generation_state(existing_records, dataset["dataset_id"])
    pending_case_ids = [case_id for case_id in manifest["live_case_ids"] if case_id not in already_called_case_ids]
    if not pending_case_ids:
        print(json.dumps({
            "run_id": args.run_id,
            "completed": 0,
            "logical_generation_attempts": 0,
            "budget_used": calls,
            "budget_maximum": manifest["maximum_logical_generations"],
            "reason": "All frozen cases already have recorded generation attempts; no catalogue or completion request was sent.",
            "results_file": str(output_path),
        }, ensure_ascii=False, indent=2))
        return 0
    schedulable_case_ids = [
        case_id for case_id in pending_case_ids
        if calls + _planned_generations(case_by_id[case_id]) <= manifest["maximum_logical_generations"]
    ]
    if not schedulable_case_ids:
        print(json.dumps({
            "run_id": args.run_id,
            "completed": 0,
            "logical_generation_attempts": 0,
            "budget_used": calls,
            "budget_maximum": manifest["maximum_logical_generations"],
            "reason": "No remaining frozen case fits the generation budget; no catalogue or completion request was sent.",
            "results_file": str(output_path),
        }, ensure_ascii=False, indent=2))
        return 0

    app = create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
        "RUN_ENV": "local",
        "AI_LAB_ENABLED": True,
    })

    completed = 0
    stopped_reason = None
    with app.app_context():
        db.create_all()
        prompt_row = AiLabPromptVersion.query.filter_by(version_no=manifest["homework_prompt_version_no"]).first()
        if prompt_row is None:
            prompt_row = ensure_initial_prompt()
        prompt_hash = hashlib.sha256(prompt_row.content.encode("utf-8")).hexdigest()
        if prompt_row.version_no != manifest["homework_prompt_version_no"] or prompt_hash != manifest["homework_prompt_sha256"]:
            raise RuntimeError("Сохранённая инструкция Homework не совпадает с frozen manifest; генерации не запускались.")
        settings = provider_settings()
        if not settings.get("configured"):
            raise RuntimeError("Локальный GigaChat не настроен; генерации не запускались.")
        provider = CachedModelCatalogProvider(GigaChatProvider(settings))
        available_models = provider.list_models()
        if manifest["model_alias"] not in available_models:
            raise RuntimeError("Выбранная модель отсутствует в каталоге GigaChat; генерации не запускались.")
        executors = _build_executors(manifest, prompt_row, provider, args.run_id)
        for case_id in manifest["live_case_ids"]:
            if case_id in already_called_case_ids:
                continue
            case = case_by_id[case_id]
            planned = _planned_generations(case)
            if calls + planned > int(manifest["maximum_logical_generations"]):
                stopped_reason = "live generation budget reached before next case"
                break
            rows = run_cases(dataset, executors, case_ids=[case_id], allow_holdout=True, run_id=args.run_id)
            append_run_records(output_path, rows)
            completed += len(rows)
            if int(rows[0]["execution"].get("attempt_count") or 0) > 0:
                already_called_case_ids.add(case_id)
            attempted = int(rows[0]["execution"].get("attempt_count") or 0)
            if attempted == 0 and case["module"] in {"ai_homework", "ai_course", "ai_lesson_intelligence"}:
                attempted = 1 if rows[0]["execution"].get("transport_status") == "error" else 0
            calls += attempted
            if _should_stop(rows[0]["execution"]):
                stopped_reason = f"provider stop condition: {rows[0]['execution'].get('error_code')}"
                break

    print(json.dumps({"run_id": args.run_id, "completed_case_records": completed,
                      "logical_generation_attempts": calls, "maximum_logical_generations": manifest["maximum_logical_generations"],
                      "results_file": str(output_path), "database_file": str(database_path),
                      "stopped_reason": stopped_reason}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
