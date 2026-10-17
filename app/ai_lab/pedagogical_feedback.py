"""Separate model prose from Code Judge evidence and cautious course advice."""
from __future__ import annotations

from typing import Any


def build_feedback_layers(result: dict[str, Any], judge_report: dict[str, Any] | None) -> dict[str, Any]:
    criteria = ((judge_report or {}).get("rubric") or {}).get("criteria") or []
    confirmed = [item for item in criteria if item.get("status") == "fulfilled"]
    failed = [item for item in criteria if item.get("status") == "not_fulfilled"]
    uncertain = [item for item in criteria if item.get("status") == "insufficient_data"]
    mistakes = result.get("mistakes") or []
    model_advice = [item.get("correction_recommendation", "") for item in mistakes
                    if isinstance(item, dict) and item.get("correction_recommendation")]
    topics = result.get("recommended_topics") or []
    adaptive = []
    for item in failed:
        failed_cases = [e.get("case_id") for e in item.get("evidence") or [] if e.get("status") == "failed"]
        if not failed_cases:
            continue
        matching = [topic for topic in topics if isinstance(topic, str) and topic.strip()
                    and (topic.casefold() in (item.get("title") or "").casefold()
                         or topic.casefold() in (item.get("description") or "").casefold())]
        adaptive.append({
            "skill": item.get("title"), "confirmed_error": item.get("rationale"),
            "confidence": "execution_evidence", "evidence": failed_cases,
            "suggested_review": matching[0] if matching else item.get("title"),
            "review_source": "model_topic_matching_criterion" if matching else "failed_existing_criterion",
            "note": "Повторить подтверждённый критерий; новую тему курса автоматически не создавать. Решение за преподавателем.",
        })
    return {
        "student": {
            "correct": [item.get("title") for item in confirmed],
            "error": [item.get("rationale") for item in failed],
            "why": [item.get("explanation") for item in mistakes if isinstance(item, dict) and item.get("explanation")],
            "how_to_fix_draft": model_advice,
            "review_topics_draft": [item["suggested_review"] for item in adaptive if item["suggested_review"]],
            "model_comment_draft": result.get("student_feedback") or "",
        },
        "teacher": {
            "fulfilled": [item.get("title") for item in confirmed],
            "difficulty": [item.get("title") for item in failed],
            "judge_confirmed": bool(judge_report),
            "manual_check": [item.get("title") for item in uncertain],
            "action_draft": result.get("teacher_feedback") or "",
        },
        "adaptive": adaptive,
        "model_confidence_note": "Самооценка модели не является вероятностью правильности.",
    }
