"""Human review of immutable, synthetic AI Lab benchmark outputs."""
from __future__ import annotations

import os
import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.ai_lab.benchmark import (
    BenchmarkDataError,
    append_expert_review,
    attach_expert_reviews,
    load_expert_reviews,
    load_frozen_manifest,
    load_run_records,
    summarize_expert_reviews,
)
from app.ai_lab.scenarios import get_scenario


ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS = {
    "sprint6": {
        "label": "Sprint 6 · исходная серия",
        "manifest": ROOT / "tests/fixtures/ai_lab_sprint6_manifest_v1.json",
        "results": ROOT / "docs/modules/artifacts/ai_lab_sprint6_live_run.jsonl",
        "reviews": ROOT / "docs/modules/artifacts/ai_lab_sprint6_expert_reviews.jsonl",
    },
    "sprint7": {
        "label": "Sprint 7 · парная серия",
        "manifest": ROOT / "tests/fixtures/ai_lab_sprint7_manifest_v1.json",
        "results": ROOT / "docs/modules/artifacts/ai_lab_sprint7_live_run.jsonl",
        "reviews": ROOT / "docs/modules/artifacts/ai_lab_sprint7_expert_reviews.jsonl",
    },
}

RATING_FIELDS: dict[str, tuple[tuple[str, str], ...]] = {
    "ai_homework": (
        ("final_score_correct", "Итоговый балл обоснован"),
        ("criterion_scores_correct", "Баллы по критериям верны"),
        ("explanation_correct", "Педагогическое объяснение верно"),
        ("no_invented_errors", "Нет выдуманных ошибок"),
        ("alternative_solution_handled", "Допустимый альтернативный способ принят"),
        ("insufficient_evidence_handled", "Недостаток данных обработан корректно"),
        ("hidden_tests_protected", "Скрытые тесты не раскрыты"),
        ("recommendations_supported", "Советы по исправлению подтверждены"),
    ),
    "ai_course": (
        ("findings_correct", "Проблемы определены верно"),
        ("findings_complete", "Существенные проблемы не пропущены"),
        ("source_references_correct", "Ссылки на материал точны"),
        ("pedagogically_justified", "Предложение педагогически обосновано"),
        ("proposal_factually_correct", "Исправление фактически верно"),
        ("no_unsupported_claims", "Нет неподтверждённых утверждений"),
        ("source_meaning_preserved", "Смысл исходного материала сохранён"),
    ),
    "ai_lesson_intelligence": (
        ("summary_factual", "Конспект соответствует стенограмме"),
        ("topics_supported", "Темы подтверждены репликами"),
        ("source_references_correct", "Ссылки на реплики точны"),
        ("important_observations_present", "Важные наблюдения не пропущены"),
        ("no_false_observations", "Нет ложных затруднений"),
        ("learner_resolution_handled", "Позднее исправление ошибки учтено"),
        ("question_not_overcalled_as_difficulty", "Вопрос не принят за доказанную ошибку"),
        ("uncertainty_handled", "Неопределённость обозначена"),
    ),
}


def _json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def _review_presentation(row: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    execution = row.get("execution") or {}
    result = execution.get("result") or {}
    raw_model = _json_object(execution.get("full_response"))
    expectation = case.get("expert_expectation") or {}
    source = case.get("input") or {}

    if row.get("module") == "ai_homework":
        judge_criteria = execution.get("judge_criteria") or []
        model_criteria = raw_model.get("criterion_scores") or []
        expected_scores = expectation.get("criterion_scores") or {}
        criteria = []
        for index, item in enumerate(judge_criteria):
            criterion_id = str(item.get("assignment_criterion_id") or item.get("id") or index)
            model_item = model_criteria[index] if index < len(model_criteria) else {}
            expected_score = expected_scores.get(criterion_id)
            judge_score = item.get("score_awarded")
            model_score = model_item.get("score_awarded") if isinstance(model_item, dict) else None
            criteria.append({
                "id": criterion_id,
                "title": item.get("title") or item.get("description") or criterion_id,
                "maximum": item.get("max_score"),
                "expected": expected_score,
                "judge": judge_score,
                "model": model_score,
                "judge_status": item.get("status"),
                "evidence": item.get("evidence") or [],
                "rationale": item.get("rationale") or "",
                "model_differs": (model_score is not None and judge_score is not None
                                  and abs(float(model_score) - float(judge_score)) > 0.001),
            })
        return {
            "task": source.get("task") or source.get("condition") or "",
            "solution": source.get("solution") or source.get("student_solution") or "",
            "criteria": source.get("criteria") or [],
            "expected_score": expectation.get("score"),
            "judge_score": execution.get("judge_score"),
            "model_score": raw_model.get("score_awarded"),
            "final_score": result.get("score_awarded"),
            "max_score": expectation.get("max_score") or raw_model.get("max_score") or result.get("max_score"),
            "criteria_comparison": criteria,
            "student_feedback": raw_model.get("student_feedback") or result.get("student_feedback") or "",
            "teacher_feedback": raw_model.get("teacher_feedback") or result.get("teacher_feedback") or "",
            "mistakes": raw_model.get("mistakes") or result.get("mistakes") or [],
            "automatic_note": "Сопоставлены замороженный эталон, ответ модели и снимок Code Judge. Это машинная сверка, не экспертная метка.",
        }

    if row.get("module") == "ai_course":
        materials = source.get("materials") or []
        material_by_id = {item.get("material_id"): item for item in materials if isinstance(item, dict)}
        proposals = result.get("material_proposals") or []
        normalized_proposals = []
        for proposal in proposals:
            material = material_by_id.get(proposal.get("material_id"), {})
            refs = proposal.get("source_refs") or []
            locations = [location for location in proposal.get("source_locations", []) if isinstance(location, dict)]
            normalized_proposals.append({
                **proposal,
                "source_content": material.get("content") or "",
                "source_locations": locations,
                "pedagogical_basis": proposal.get("observation") or "",
            })
        return {
            "materials": materials,
            "proposals": normalized_proposals,
            "summary": result.get("summary") or "",
            "structural_findings": result.get("structural_findings") or [],
            "automatic_note": "Проверена привязка source_refs. Фактическую и педагогическую правильность правки подтверждает преподаватель.",
        }

    transcript = source.get("transcript") or []
    utterances = []
    if isinstance(transcript, list):
        for index, item in enumerate(transcript, 1):
            if isinstance(item, dict):
                utterances.append({
                    "id": item.get("segment_id") or f"фрагмент {index}",
                    "speaker": item.get("speaker") or item.get("speaker_role") or "Роль не указана",
                    "text": item.get("text") or "",
                })
    elif isinstance(transcript, str):
        for index, line in enumerate(transcript.splitlines(), 1):
            text = line.strip()
            if not text:
                continue
            parts = text.split(":", 1)
            utterances.append({"id": f"строка {index}",
                               "speaker": parts[0] if len(parts) == 2 else "Роль не указана",
                               "text": parts[1].strip() if len(parts) == 2 else text})
    return {
        "utterances": utterances,
        "summary": result.get("summary") or "",
        "topics": result.get("topics") or [],
        "observations": result.get("observed_difficulties") or [],
        "unsubstantiated": result.get("unsubstantiated_observations") or [],
        "automatic_note": "Ссылки сверены с исходными фрагментами. Содержательные выводы остаются AI inference до решения преподавателя.",
    }


def _is_model_output(row: dict[str, Any]) -> bool:
    execution = row.get("execution") or {}
    return (
        isinstance(execution, dict)
        and int(execution.get("attempt_count") or 0) > 0
        and execution.get("transport_status") == "received"
    )


def _review_priority(row: dict[str, Any]) -> dict[str, Any]:
    """Order technically informative cases first; this never assigns a human label."""
    execution = row.get("execution") or {}
    result = execution.get("result") or {}
    presentation = row.get("review_presentation") or {}
    reasons: list[str] = []
    priority = 0
    if result.get("grading_status") in {"manual_review", "manual_review_required"}:
        priority += 100
        reasons.append("результат уже отправлен на ручную проверку")
    if result.get("needs_human_review"):
        priority += 30
        reasons.append("технический результат требует решения преподавателя")
    judge_score = presentation.get("judge_score")
    model_score = presentation.get("model_score")
    if judge_score is not None and model_score is not None:
        try:
            if abs(float(judge_score) - float(model_score)) > 0.001:
                priority += 80
                reasons.append("балл GigaChat расходится с Code Judge")
        except (TypeError, ValueError, OverflowError):
            priority += 50
            reasons.append("баллы нельзя однозначно сопоставить")
    if any(item.get("model_differs") for item in presentation.get("criteria_comparison", [])):
        priority += 70
        reasons.append("есть расхождение по критерию")
    quality = execution.get("quality") or {}
    if quality.get("pedagogical_validation", {}).get("status") == "conflict_detected":
        priority += 60
        reasons.append("обнаружено противоречие комментария")
    return {"score": priority, "reasons": reasons,
            "label": "Технический приоритет, не экспертная оценка"}


def load_review_bundle(benchmark_id: str) -> dict[str, Any]:
    definition = BENCHMARKS.get(benchmark_id)
    if definition is None:
        raise BenchmarkDataError("Неизвестная контрольная серия.")
    manifest, dataset = load_frozen_manifest(definition["manifest"])
    raw_rows = load_run_records(definition["results"])
    model_rows = [row for row in raw_rows if _is_model_output(row)]
    reviews = load_expert_reviews(definition["reviews"]) if definition["reviews"].exists() else []
    rows = attach_expert_reviews(model_rows, reviews)
    cases = {case["case_id"]: case for case in dataset["cases"]}
    if benchmark_id == "sprint7":
        _, previous_dataset = load_frozen_manifest(
            BENCHMARKS["sprint6"]["manifest"]
        )
        previous_cases = {case["case_id"]: case for case in previous_dataset["cases"]}
        for case_id, case in cases.items():
            source_id = case["input"].get("frozen_sprint6_case_id")
            if source_id:
                source = previous_cases.get(source_id)
                if source is None or source["module"] != case["module"] or source["split"] == "holdout":
                    raise BenchmarkDataError(f"Недопустимый источник для {case_id}.")
                cases[case_id] = {**case, "input": source["input"], "frozen_source_case_id": source_id}
            elif case["module"] == "ai_homework":
                scenario = get_scenario(str(case["input"].get("scenario_id") or ""))
                if scenario is None or scenario.get("type") != "python":
                    raise BenchmarkDataError(f"Неизвестное Python-задание для {case_id}.")
                cases[case_id] = {**case, "input": {**case["input"], "task": scenario["condition"],
                                                   "criteria": scenario["criteria"],
                                                   "public_examples": [item for item in scenario.get("test_cases", [])
                                                                       if item.get("visibility") != "hidden"]}}
    for row in rows:
        if row.get("case_id") not in cases or row.get("dataset_id") != dataset["dataset_id"]:
            raise BenchmarkDataError("Результат не соответствует замороженному набору.")
        row["review_presentation"] = _review_presentation(row, cases[row["case_id"]])
        row["review_priority"] = _review_priority(row)
    rows.sort(key=lambda row: (-row["review_priority"]["score"], row.get("case_id", "")))
    summary = summarize_expert_reviews(rows)
    summary["excluded_before_model_or_transport"] = len(raw_rows) - len(model_rows)
    summary["manual_escalations"] = sum(
        ((row.get("execution") or {}).get("result") or {}).get("grading_status") == "manual_review"
        for row in rows
    )
    summary["manual_escalation_n"] = len(rows)
    total_aspects = sum(len(RATING_FIELDS.get(row.get("module"), ())) for row in rows)
    explicit_aspects = sum(
        1 for row in rows
        for value in (row.get("expert_review", {}).get("ratings") or {}).values()
        if type(value) is bool or value == "na"
    )
    summary["aspects_total"] = total_aspects
    summary["aspects_unresolved"] = max(0, total_aspects - explicit_aspects)
    summary["aspects_not_applicable"] = sum(
        value == "na" for row in rows
        for value in (row.get("expert_review", {}).get("ratings") or {}).values()
    )
    module_metrics: dict[str, dict[str, Any]] = {}
    for module, fields in RATING_FIELDS.items():
        module_rows = [row for row in rows if row.get("module") == module]
        reviewed = [row for row in module_rows if row["expert_review"]["status"] == "reviewed"]
        metrics = {}
        for key, _ in fields:
            values = [row["expert_review"]["ratings"].get(key) for row in reviewed]
            rated = [value for value in values if type(value) is bool]
            metrics[key] = {
                "correct": sum(rated),
                "n": len(rated),
                "accuracy": sum(rated) / len(rated) if rated else None,
                "not_applicable": sum(value == "na" for value in values),
                "skipped": sum(value is None for value in values),
                "pending": len(module_rows) - len(reviewed),
            }
        module_metrics[module] = {"model_outputs": len(module_rows), "reviewed": len(reviewed), "metrics": metrics}
    summary["module_metrics"] = module_metrics
    return {"id": benchmark_id, "definition": definition, "manifest": manifest,
            "dataset": dataset, "cases": cases, "rows": rows, "summary": summary}


@contextmanager
def _review_file_lock(path: Path):
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
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
                    raise BenchmarkDataError("Журнал экспертных оценок занят. Повторите сохранение.")
                time.sleep(0.05)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def save_human_review(
    benchmark_id: str, *, run_id: str, case_id: str, reviewer_id: int,
    ratings: dict[str, Any], comments: str,
) -> None:
    bundle = load_review_bundle(benchmark_id)
    row = next((item for item in bundle["rows"] if item["run_id"] == run_id and item["case_id"] == case_id), None)
    if row is None:
        raise BenchmarkDataError("Этот результат не является ответом модели из выбранной серии.")
    allowed = {key for key, _ in RATING_FIELDS.get(row["module"], ())}
    if not ratings or not set(ratings) <= allowed or any(type(value) is not bool and value != "na" for value in ratings.values()):
        raise BenchmarkDataError("Отметьте хотя бы один аспект как верный, неверный или неприменимый.")
    if not isinstance(comments, str) or len(comments) > 4000:
        raise BenchmarkDataError("Комментарий не должен превышать 4000 символов.")
    review_path = bundle["definition"]["reviews"]
    with _review_file_lock(review_path):
        current = load_expert_reviews(review_path) if review_path.exists() else []
        if any(item.get("run_id") == run_id and item.get("case_id") == case_id for item in current):
            raise BenchmarkDataError("Этот результат уже оценён. Обновите страницу.")
        append_expert_review(review_path, run_id=run_id, case_id=case_id,
                             reviewer=f"user:{reviewer_id}", ratings=ratings,
                             comments=comments.strip())
