"""Reproducible, review-separated storage for synthetic AI Lab evaluations."""
from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


ALLOWED_SPLITS = frozenset({"development", "regression", "holdout"})
REQUIRED_DATASET_FIELDS = frozenset({
    "dataset_id", "dataset_version", "synthetic_only", "real_student_data", "cases",
})


class BenchmarkDataError(ValueError):
    """Raised when benchmark input is not frozen, synthetic, or reproducible."""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_dataset(path: str | Path, expected_sha256: str) -> dict[str, Any]:
    """Load a frozen JSON fixture and reject hash/scope/split drift."""
    fixture_path = Path(path)
    actual_sha256 = sha256_file(fixture_path)
    if not expected_sha256 or actual_sha256.lower() != expected_sha256.lower():
        raise BenchmarkDataError("SHA-256 набора не совпадает с frozen manifest.")
    try:
        dataset = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkDataError("Не удалось прочитать JSON-набор испытаний.") from exc
    missing = REQUIRED_DATASET_FIELDS - dataset.keys()
    if missing:
        raise BenchmarkDataError(f"В наборе отсутствуют обязательные поля: {', '.join(sorted(missing))}.")
    if dataset["synthetic_only"] is not True or dataset["real_student_data"] is not False:
        raise BenchmarkDataError("Benchmark принимает только синтетические данные.")
    if dataset.get("frozen_before_live_model_runs") is not True:
        raise BenchmarkDataError("Набор должен быть frozen до live запусков.")
    cases = dataset["cases"]
    if not isinstance(cases, list) or not cases:
        raise BenchmarkDataError("В наборе нет испытаний.")
    seen: set[str] = set()
    for case in cases:
        case_id = case.get("case_id") if isinstance(case, dict) else None
        if not case_id or case_id in seen:
            raise BenchmarkDataError("Идентификаторы испытаний должны быть непустыми и уникальными.")
        seen.add(case_id)
        if case.get("split") not in ALLOWED_SPLITS:
            raise BenchmarkDataError(f"Испытание {case_id} не относится к разрешённой выборке.")
        if "input" not in case or "expert_expectation" not in case:
            raise BenchmarkDataError(f"В испытании {case_id} нет входа или зафиксированного эталона.")
    return {**dataset, "fixture_sha256": actual_sha256}


def load_frozen_manifest(path: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest_path = Path(path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkDataError("Не удалось прочитать manifest набора.") from exc
    root = manifest_path.parents[2]
    protocol_path = root / manifest.get("protocol_path", "")
    if not manifest.get("protocol_sha256") or sha256_file(protocol_path).lower() != manifest["protocol_sha256"].lower():
        raise BenchmarkDataError("SHA-256 протокола не совпадает с frozen manifest.")
    dataset = load_dataset(root / manifest["dataset_path"], manifest["dataset_sha256"])
    if dataset["dataset_id"] != manifest.get("dataset_id") or dataset.get("dataset_version") != manifest.get("dataset_version"):
        raise BenchmarkDataError("ID или версия набора не совпадают с frozen manifest.")
    for relative_path, expected in (manifest.get("preserved_existing_fixture_hashes") or {}).items():
        if sha256_file(root / relative_path).lower() != expected.lower():
            raise BenchmarkDataError(f"Ранее зафиксированный набор изменён: {relative_path}.")
    live_case_ids = manifest.get("live_case_ids") or []
    all_case_ids = {case["case_id"] for case in dataset["cases"]}
    if len(live_case_ids) > 30 or len(live_case_ids) != len(set(live_case_ids)) or not set(live_case_ids) <= all_case_ids:
        raise BenchmarkDataError("Живой бюджет или список case ID некорректен.")
    return manifest, dataset


def run_cases(
    dataset: dict[str, Any],
    executors: dict[str, Callable[[dict[str, Any]], dict[str, Any]]],
    *,
    case_ids: Iterable[str] | None = None,
    allow_holdout: bool = False,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    """Run selected cases through module adapters and retain unscored outputs.

    Holdout runs require explicit opt-in. The runner never derives an expert score
    from model output; expert review is a separate, later field in the stored row.
    """
    selected = set(case_ids) if case_ids is not None else None
    records: list[dict[str, Any]] = []
    run_id = str(run_id or uuid.uuid4())
    for case in dataset["cases"]:
        if selected is not None and case["case_id"] not in selected:
            continue
        if case["split"] == "holdout" and not allow_holdout:
            continue
        executor = executors.get(case["module"])
        if executor is None:
            continue
        started = datetime.now(timezone.utc)
        try:
            execution = executor(case)
            if not isinstance(execution, dict):
                raise TypeError("Benchmark executor must return a dictionary.")
            execution_error = None
        except Exception as exc:  # retain failed experiments instead of skipping them
            execution = {}
            execution_error = {"type": type(exc).__name__, "message": str(exc)}
        finished = datetime.now(timezone.utc)
        records.append({
            "run_id": run_id,
            "dataset_id": dataset["dataset_id"],
            "dataset_version": dataset.get("dataset_version"),
            "fixture_sha256": dataset["fixture_sha256"],
            "case_id": case["case_id"],
            "module": case["module"],
            "split": case["split"],
            "input_sha256": hashlib.sha256(
                json.dumps(case["input"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "duration_ms": max(0, int((finished - started).total_seconds() * 1000)),
            "execution": execution,
            "execution_error": execution_error,
            "expert_review": {"status": "pending", "ratings": {}, "reviewer": None, "reviewed_at": None},
        })
    unknown = selected - {record["case_id"] for record in records} if selected is not None else set()
    if unknown:
        raise BenchmarkDataError(f"Не выполнены выбранные испытания: {', '.join(sorted(unknown))}.")
    return records


def append_run_records(path: str | Path, records: Iterable[dict[str, Any]]) -> int:
    """Append immutable JSONL records; return the number of rows written."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with target.open("a", encoding="utf-8", newline="\n") as output:
        for record in records:
            output.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def summarize_expert_reviews(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate only explicit reviewed boolean ratings; pending items are excluded."""
    rows = list(records)
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(str(row.get("module", "unknown")), str(row.get("split", "unknown")))].append(row)
    result: dict[str, Any] = {
        "method": "Reviewed boolean ratings only; null, missing, and pending ratings are excluded from each denominator.",
        "total_runs": len(rows),
        "expert_reviewed_runs": sum(row.get("expert_review", {}).get("status") == "reviewed" for row in rows),
        "pending_runs": sum(row.get("expert_review", {}).get("status") != "reviewed" for row in rows),
        "groups": {},
    }
    for (module, split), group in sorted(groups.items()):
        metrics: dict[str, dict[str, int | float]] = {}
        names = {
            name
            for row in group
            if row.get("expert_review", {}).get("status") == "reviewed"
            for name in row.get("expert_review", {}).get("ratings", {})
        }
        for name in sorted(names):
            values = [
                row["expert_review"]["ratings"].get(name)
                for row in group
                if row.get("expert_review", {}).get("status") == "reviewed"
            ]
            labeled = [value for value in values if type(value) is bool]
            not_applicable = sum(value == "na" for value in values)
            skipped = sum(value is None for value in values)
            if labeled:
                correct = sum(labeled)
                metrics[name] = {"correct": correct, "n": len(labeled), "accuracy": correct / len(labeled),
                                 "not_applicable": not_applicable, "skipped": skipped}
            elif values:
                metrics[name] = {"correct": 0, "n": 0, "accuracy": None,
                                 "not_applicable": not_applicable, "skipped": skipped}
        result["groups"][f"{module}:{split}"] = {
            "runs": len(group),
            "reviewed": sum(row.get("expert_review", {}).get("status") == "reviewed" for row in group),
            "metrics": metrics,
        }
    return result


def attach_expert_reviews(
    records: Iterable[dict[str, Any]], reviews: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Join separately appended expert labels to immutable execution rows."""
    review_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for review in reviews:
        key = (str(review.get("run_id") or ""), str(review.get("case_id") or ""))
        if not all(key) or not str(review.get("reviewer") or "").strip():
            raise BenchmarkDataError("Экспертная разметка должна содержать run_id, case_id и reviewer.")
        if key in review_by_key:
            raise BenchmarkDataError("Для одного результата найдена повторная экспертная разметка.")
        ratings = review.get("ratings")
        if not isinstance(ratings, dict) or not ratings:
            raise BenchmarkDataError("Экспертная разметка должна содержать ratings.")
        review_by_key[key] = {"status": "reviewed", "ratings": ratings,
                              "reviewer": review["reviewer"], "reviewed_at": review.get("reviewed_at"),
                              "comments": review.get("comments", "")}
    attached = []
    target_keys = {
        (str(row.get("run_id") or ""), str(row.get("case_id") or ""))
        for row in records
    }
    orphaned = set(review_by_key) - target_keys
    if orphaned:
        raise BenchmarkDataError("Экспертная разметка ссылается на отсутствующий запуск или case ID.")
    for record in records:
        row = dict(record)
        key = (str(row.get("run_id") or ""), str(row.get("case_id") or ""))
        if key in review_by_key:
            row["expert_review"] = review_by_key[key]
        attached.append(row)
    return attached


def append_expert_review(
    path: str | Path, *, run_id: str, case_id: str, reviewer: str,
    ratings: dict[str, Any], comments: str = "",
) -> None:
    """Append a separate human review; never rewrite the model execution record."""
    reviewer = str(reviewer or "").strip()
    if not run_id or not case_id or not reviewer or not isinstance(ratings, dict) or not ratings:
        raise BenchmarkDataError("Укажите run_id, case_id, reviewer и хотя бы одну оценку.")
    row = {"run_id": run_id, "case_id": case_id, "reviewer": reviewer,
           "ratings": ratings, "comments": str(comments or ""),
           "reviewed_at": datetime.now(timezone.utc).isoformat()}
    append_run_records(path, [row])


def load_expert_reviews(path: str | Path) -> list[dict[str, Any]]:
    reviews = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            review = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BenchmarkDataError(f"Повреждена экспертная разметка в строке {line_number}.") from exc
        reviews.extend([review])
    return reviews


def load_run_records(path: str | Path) -> list[dict[str, Any]]:
    records = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BenchmarkDataError(f"Повреждена запись результата в строке {line_number}.") from exc
        if not isinstance(record, dict) or "expert_review" not in record:
            raise BenchmarkDataError(f"В строке {line_number} нет записи независимой экспертизы.")
        records.append(record)
    return records
