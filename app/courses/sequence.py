"""Small, auditable sequence decisions for an individual course."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable


SEQUENCE_CONTRACT = "boostudy.course-sequence-decision.v1"
SEQUENCE_KEY = "_course_sequence"


def course_sequence_state(review_summaries: Any) -> dict[str, Any]:
    summaries = review_summaries if isinstance(review_summaries, dict) else {}
    decision = summaries.get(SEQUENCE_KEY)
    if not isinstance(decision, dict) or decision.get("contract") != SEQUENCE_CONTRACT:
        return {"state": "queued", "history": []}
    history = decision.get("history")
    return {
        "state": "deferred" if decision.get("state") == "deferred" else "queued",
        "reason": str(decision.get("reason") or ""),
        "actor_user_id": decision.get("actor_user_id"),
        "decided_at": decision.get("decided_at"),
        "history": history if isinstance(history, list) else [],
    }


def lesson_is_deferred(lesson: Any) -> bool:
    return course_sequence_state(getattr(lesson, "review_summaries", None))["state"] == "deferred"


def record_course_sequence_decision(
    lesson: Any,
    *,
    action: str,
    reason: str,
    actor_user_id: int,
    effective_course_version: int,
    decided_at: datetime | None = None,
) -> None:
    summaries = dict(getattr(lesson, "review_summaries", None) or {})
    previous = summaries.get(SEQUENCE_KEY)
    history = list(previous.get("history") or []) if isinstance(previous, dict) else []
    timestamp = (decided_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    state = "deferred" if action == "defer" else "queued"
    event = {
        "contract": SEQUENCE_CONTRACT,
        "action": action,
        "source": "teacher_manual",
        "reason": reason.strip(),
        "actor_user_id": int(actor_user_id),
        "decided_at": timestamp,
        "effective_course_version": int(effective_course_version),
    }
    history.append(event)
    summaries[SEQUENCE_KEY] = {
        "contract": SEQUENCE_CONTRACT,
        "state": state,
        "reason": event["reason"],
        "actor_user_id": event["actor_user_id"],
        "decided_at": timestamp,
        "history": history,
    }
    lesson.review_summaries = summaries


def select_course_lesson_target(lessons: Iterable[Any]) -> tuple[Any | None, str | None]:
    ordered = sorted(
        list(lessons or []),
        key=lambda lesson: (
            int(getattr(lesson, "course_order_index", 0) or 0),
            int(getattr(lesson, "lesson_id", 0) or 0),
        ),
    )
    active = [lesson for lesson in ordered if str(getattr(lesson, "status", "")).casefold() == "in_progress"]
    if len(active) > 1:
        return None, "multiple_active_lessons"
    if active:
        return active[0], None

    pending = [
        lesson for lesson in ordered
        if str(getattr(lesson, "status", "")).casefold() in {"planned", "scheduled", "draft"}
        and not lesson_is_deferred(lesson)
    ]
    return (pending[0], None) if pending else (None, None)


def select_next_course_lesson(
    lessons: Iterable[Any],
) -> tuple[Any | None, str | None, list[Any]]:
    """Select an existing upcoming lesson without creating or starting one."""
    ordered = sorted(
        list(lessons or []),
        key=lambda lesson: (
            int(getattr(lesson, "course_order_index", 0) or 0),
            int(getattr(lesson, "lesson_id", 0) or 0),
        ),
    )
    active = [lesson for lesson in ordered if str(getattr(lesson, "status", "")).casefold() == "in_progress"]
    if len(active) > 1:
        return None, "multiple_active_lessons", []

    if active:
        blockers = unresolved_preceding_lessons(ordered, active[0])
        if blockers:
            return None, "unresolved_preceding_lessons", blockers
        active_order = int(getattr(active[0], "course_order_index", 0) or 0)
        candidates = [
            lesson for lesson in ordered
            if int(getattr(lesson, "course_order_index", 0) or 0) > active_order
            and str(getattr(lesson, "status", "")).casefold() in {"planned", "scheduled", "draft"}
            and not lesson_is_deferred(lesson)
        ]
        return (candidates[0], None, []) if candidates else (None, "no_upcoming_lesson", [])

    candidates = [
        lesson for lesson in ordered
        if str(getattr(lesson, "status", "")).casefold() in {"planned", "scheduled", "draft"}
        and not lesson_is_deferred(lesson)
    ]
    return (candidates[0], None, []) if candidates else (None, "no_upcoming_lesson", [])


def unresolved_preceding_lessons(lessons: Iterable[Any], target: Any) -> list[Any]:
    target_order = int(getattr(target, "course_order_index", 0) or 0)
    return [
        lesson for lesson in lessons
        if int(getattr(lesson, "lesson_id", 0) or 0) != int(getattr(target, "lesson_id", 0) or 0)
        and int(getattr(lesson, "course_order_index", 0) or 0) < target_order
        and str(getattr(lesson, "status", "")).casefold() in {"planned", "scheduled", "draft", "in_progress"}
        and not lesson_is_deferred(lesson)
    ]
