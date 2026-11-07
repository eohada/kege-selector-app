"""Explicit lesson lifecycle transitions and auditable non-transition signals."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from math import ceil
from typing import Any

from core.db_models import AuditLog, LearningItem, Lesson, MOSCOW_TZ, db, moscow_now


VALID_LESSON_STATUSES = {"planned", "in_progress", "completed", "cancelled"}


class LessonLifecycleError(ValueError):
    """Raised when a requested transition would make billing/history ambiguous."""


def _moscow_naive(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(MOSCOW_TZ).replace(tzinfo=None)
    return value


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    aware_value = (value.astimezone(MOSCOW_TZ) if value.tzinfo is not None
                   else value.replace(tzinfo=MOSCOW_TZ))
    return aware_value.isoformat(timespec="microseconds")


def record_lesson_event(
    lesson: Lesson,
    *,
    action: str,
    source: str,
    reason: str,
    actor_user_id: int | None = None,
    metadata: dict[str, Any] | None = None,
    event_key: str | None = None,
) -> bool:
    """Write structured lifecycle provenance in the same transaction as the change."""
    if not lesson or not lesson.lesson_id:
        return False
    if event_key:
        candidates = AuditLog.query.filter_by(
            action=action, entity="Lesson", entity_id=int(lesson.lesson_id)
        ).order_by(AuditLog.id.desc()).all()
        for candidate in candidates:
            try:
                saved = json.loads(candidate.meta_data or "{}")
            except (TypeError, ValueError):
                continue
            if isinstance(saved, dict) and saved.get("event_key") == event_key:
                return False

    now = moscow_now()
    payload = {
        "source": str(source)[:80],
        "reason": str(reason)[:240],
        "occurred_at": _iso(now),
        "timezone": "Europe/Moscow",
    }
    if event_key:
        payload["event_key"] = event_key[:240]
    if metadata:
        payload.update(metadata)
    db.session.add(AuditLog(
        timestamp=now,
        user_id=int(actor_user_id) if actor_user_id else None,
        action=str(action)[:50],
        entity="Lesson",
        entity_id=int(lesson.lesson_id),
        status="success",
        meta_data=json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str),
    ))
    return True


def sync_learning_item_status(lesson: Lesson) -> int:
    """Keep course progress aligned with explicit lesson state, never with timer expiry."""
    if not lesson or not lesson.lesson_id:
        return 0
    item_status = {
        "planned": "planned",
        "in_progress": "in_progress",
        "completed": "done",
        # A cancelled meeting leaves the curriculum item uncompleted and schedulable.
        "cancelled": "planned",
    }.get(str(lesson.status or "").lower())
    if item_status is None:
        return 0
    items = LearningItem.query.filter_by(lesson_id=lesson.lesson_id, item_type="lesson").all()
    for item in items:
        item.status = item_status
    return len(items)


def deduct_lesson_balance(
    lesson: Lesson,
    *,
    source: str,
    actor_user_id: int | None = None,
) -> tuple[int, int, str] | None:
    """Deduct once, only on an explicit completion transition; audit exact amounts."""
    if not lesson or not lesson.lesson_id or not lesson.student:
        return None
    claimed = Lesson.query.filter(
        Lesson.lesson_id == int(lesson.lesson_id),
        Lesson.balance_deducted.is_not(True),
    ).update({Lesson.balance_deducted: True}, synchronize_session=False)
    if claimed != 1:
        db.session.refresh(lesson, attribute_names=["balance_deducted"])
        return None

    lesson.balance_deducted = True
    student = lesson.student
    try:
        duration = int(lesson.duration or 60)
    except (TypeError, ValueError):
        duration = 60
    units = max(1, ceil(duration / 60))
    before = int(student.lessons_balance or 0)
    after = before - units
    student.lessons_balance = after

    subscription_before = subscription_after = None
    if student.user_id:
        from app.models import UserSubscription

        active_subscriptions = UserSubscription.query.filter_by(
            user_id=student.user_id, status="active"
        ).order_by(
            UserSubscription.ends_at.desc().nullslast(),
            UserSubscription.subscription_id.desc(),
        ).all()

        def course_key(value):
            normalized = (value or '').strip().lower().replace('ё', 'е')
            if normalized in {'inf', 'informatics'} or 'информат' in normalized:
                return 'inf'
            if normalized in {'math', 'mathematics'} or 'математ' in normalized:
                return 'math'
            return None

        lesson_course = course_key(lesson.subject) or 'inf'
        matching_subscription = None
        general_subscription = None
        for candidate in active_subscriptions:
            subscription_course = course_key(
                candidate.subject or (candidate.plan.subject if candidate.plan else None)
            )
            if subscription_course == lesson_course:
                matching_subscription = candidate
                break
            if subscription_course is None and general_subscription is None:
                general_subscription = candidate
        active_subscription = matching_subscription or general_subscription
        if active_subscription and active_subscription.lessons_remaining is not None:
            subscription_before = int(active_subscription.lessons_remaining)
            subscription_after = max(0, subscription_before - units)
            active_subscription.lessons_remaining = subscription_after

    reason = f"Списание после явного подтверждения проведённого урока #{lesson.lesson_id}"
    record_lesson_event(
        lesson,
        action="lesson.balance_deducted",
        source=source,
        reason=reason,
        actor_user_id=actor_user_id,
        metadata={
            "units": units,
            "duration_minutes": duration,
            "student_balance_before": before,
            "student_balance_after": after,
            "subscription_balance_before": subscription_before,
            "subscription_balance_after": subscription_after,
        },
    )
    return before, after, reason


def transition_lesson_status(
    lesson: Lesson,
    target_status: str,
    *,
    source: str,
    reason: str,
    actor_user_id: int | None = None,
    started_at: datetime | None = None,
    conducted_confirmation_reason: str | None = None,
) -> tuple[bool, tuple[int, int, str] | None]:
    """Apply one explicit transition with provenance, curriculum sync, and one-time billing.

    Completion is reserved for the teacher confirmation route; all other callers may
    start/cancel lessons but cannot assert that a session was conducted.
    """
    target = str(target_status or "").strip().lower()
    if target not in VALID_LESSON_STATUSES:
        raise LessonLifecycleError("Недопустимый статус урока.")
    previous = str(lesson.status or "planned").strip().lower()
    if previous == target:
        return False, None
    confirmation = str(conducted_confirmation_reason or "").strip()
    if target == "completed" and len(confirmation) < 8:
        raise LessonLifecycleError(
            "Завершить урок можно только после отдельного подтверждения преподавателя о проведённом занятии."
        )
    if previous == "completed":
        raise LessonLifecycleError(
            "Проведённый урок нельзя вернуть в запланированные без отдельной корректировки баланса."
        )

    old_started_at = lesson.started_at
    lesson.status = target
    if target == "in_progress":
        lesson.started_at = _moscow_naive(started_at or moscow_now())
    elif target in {"planned", "cancelled"} and previous == "in_progress":
        lesson.started_at = None

    synced_items = sync_learning_item_status(lesson)
    record_lesson_event(
        lesson,
        action="lesson.status_transition",
        source=source,
        reason=reason,
        actor_user_id=actor_user_id,
        metadata={
            "from_status": previous,
            "to_status": target,
            "started_at_before": _iso(old_started_at),
            "started_at_after": _iso(lesson.started_at),
            "learning_items_synced": synced_items,
            "pedagogical_outcome_recorded": False,
            "conducted_confirmation_reason": confirmation if target == "completed" else None,
        },
    )
    balance_notice = None
    if target == "completed":
        balance_notice = deduct_lesson_balance(
            lesson, source=source, actor_user_id=actor_user_id,
        )
    return True, balance_notice


def record_lesson_timer_elapsed(lesson: Lesson, *, now: datetime | None = None) -> bool:
    """Record that allotted time elapsed; this is not proof of a conducted lesson."""
    if not lesson or str(lesson.status or "").lower() != "in_progress" or not lesson.started_at:
        return False
    try:
        duration = max(1, int(lesson.duration or 60))
    except (TypeError, ValueError):
        duration = 60
    started_at = _moscow_naive(lesson.started_at)
    observed_at = _moscow_naive(now or moscow_now())
    threshold = started_at + timedelta(minutes=duration)
    if observed_at < threshold:
        return False
    event_key = f"timer_elapsed:{lesson.lesson_id}:{started_at.isoformat()}:{duration}"
    return record_lesson_event(
        lesson,
        action="lesson.timer_elapsed",
        source="lesson_duration_timer",
        reason="Время по расписанию истекло; факт проведения и педагогический итог не подтверждены.",
        metadata={
            "status_at_signal": str(lesson.status),
            "started_at": started_at.isoformat(timespec="microseconds"),
            "elapsed_threshold_at": _iso(threshold),
            "duration_minutes": duration,
            "balance_deducted": bool(lesson.balance_deducted),
        },
        event_key=event_key,
    )


def record_lesson_outcome_saved(
    lesson: Lesson,
    outcome_id: int | None,
    *,
    actor_user_id: int | None,
    covered_count: int,
    repeat_count: int,
) -> None:
    record_lesson_event(
        lesson,
        action="lesson.pedagogical_outcome_saved",
        source="lesson_room_reflection",
        reason="Преподаватель сохранил структурированный итог занятия.",
        actor_user_id=actor_user_id,
        metadata={
            "outcome_id": outcome_id,
            "covered_count": int(covered_count),
            "repeat_count": int(repeat_count),
        },
    )
