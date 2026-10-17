"""Evidence-labeled local AI Lab quality aggregates."""
from __future__ import annotations

from collections import defaultdict

from app.ai_lab.config import setting
from core.db_models import AiLabExperiment, AiLabRubricVersion, AiLabRubricReview


def _rate(rows: list[bool]) -> dict:
    return {"matched": sum(rows), "sample": len(rows),
            "percent": round(100 * sum(rows) / len(rows), 1) if rows else None}


def _tariff(name: str) -> float | None:
    raw = setting(name)
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if 0 <= value <= 1_000_000 else None


def quality_snapshot() -> dict:
    experiments = AiLabExperiment.query.order_by(AiLabExperiment.id.asc()).all()
    rubrics = AiLabRubricVersion.query.order_by(AiLabRubricVersion.id.asc()).all()
    signals = {key: [] for key in ("score_match", "criteria_alignment", "error_detection")}
    models: dict[str, dict] = defaultdict(lambda: {"runs": 0, "reviewed": 0, "tokens": 0})
    prompts: dict[int, dict] = defaultdict(lambda: {"runs": 0, "score_matches": 0, "score_sample": 0})
    conflicts = 0
    reviews = {"correct": 0, "partially_correct": 0, "incorrect": 0}
    input_tokens = output_tokens = token_sample = 0
    for item in experiments:
        quality = item.quality_json or {}
        for key in signals:
            status = (quality.get(key) or {}).get("status")
            if status in {"pass", "review"}:
                signals[key].append(status == "pass")
        if quality.get("code_judge_conflict") is True:
            conflicts += 1
        if item.manual_rating in reviews:
            reviews[item.manual_rating] += 1
        if item.provider == "gigachat":
            model = models[item.model or "Не указана"]
            model["runs"] += 1
            model["reviewed"] += bool(item.manual_rating)
            model["tokens"] += (item.input_tokens or 0) + (item.output_tokens or 0)
            if item.input_tokens is not None and item.output_tokens is not None:
                input_tokens += item.input_tokens
                output_tokens += item.output_tokens
                token_sample += 1
        if item.prompt_version_no is not None:
            prompt = prompts[item.prompt_version_no]
            prompt["runs"] += 1
            status = (quality.get("score_match") or {}).get("status")
            if status in {"pass", "review"}:
                prompt["score_sample"] += 1
                prompt["score_matches"] += status == "pass"
    rubric_checks = [bool((item.validation_json or {}).get("ok")) for item in rubrics]
    expert_latest = {}
    for review in AiLabRubricReview.query.order_by(AiLabRubricReview.id.asc()).all():
        expert_latest[review.rubric_version_id] = review
    issue_counts: dict[str, int] = defaultdict(int)
    for review in expert_latest.values():
        for issue in review.issues_json or []:
            if isinstance(issue, dict) and issue.get("category"):
                issue_counts[issue["category"]] += 1
    input_rate = _tariff("AI_LAB_GIGACHAT_INPUT_PRICE_PER_MILLION")
    output_rate = _tariff("AI_LAB_GIGACHAT_OUTPUT_PRICE_PER_MILLION")
    return {
        "experiments": len(experiments),
        "signals": {key: _rate(values) for key, values in signals.items()},
        "rubric_structure": _rate(rubric_checks),
        "rubric_expert": _rate([review.verdict == "pass" for review in expert_latest.values()]),
        "rubric_issue_counts": dict(issue_counts),
        "rubric_total": len(rubrics), "conflicts": conflicts,
        "conflict_sample": sum((item.quality_json or {}).get("code_judge_conflict") is not None for item in experiments),
        "reviews": reviews, "review_sample": sum(reviews.values()),
        "models": dict(models), "prompts": dict(prompts),
        "usage": {"input": input_tokens, "output": output_tokens, "sample": token_sample},
        "estimated_cost": round((input_tokens * input_rate + output_tokens * output_rate) / 1_000_000, 4)
        if input_rate is not None and output_rate is not None else None,
        "tariffs": {"input": input_rate, "output": output_rate},
    }
