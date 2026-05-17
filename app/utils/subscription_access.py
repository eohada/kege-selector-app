from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from flask import g, has_request_context
from sqlalchemy.orm import joinedload

from app.models import TariffPlan, UserSubscription, db


@dataclass(frozen=True)
class EffectiveAccess:
    """
    Effective access for paywalled modules.

    Notes:
    - We only *enforce* access when the active subscription has a plan AND that plan explicitly sets
      allow_lessons/allow_trainer (see hooks.py). For display, we still return best-effort info.
    - All timestamps in subscriptions are stored as naive UTC in this project (datetime.utcnow()).
    """

    subscription: Optional[UserSubscription]
    plan: Optional[TariffPlan]

    allow_lessons: Optional[bool]  # None => unknown / not defined by plan
    allow_trainer: Optional[bool]  # None => unknown / not defined by plan

    status: str  # none|active|expired|cancelled|paused
    ends_at_utc: Optional[datetime]
    seconds_left: Optional[int]

    lessons_remaining: Optional[int]  # оставшееся количество уроков

    label: str


def _now_utc_naive() -> datetime:
    return datetime.utcnow().replace(tzinfo=None)


def _compute_label(allow_lessons: Optional[bool], allow_trainer: Optional[bool]) -> str:
    if allow_lessons is True and allow_trainer is True:
        return "Уроки + тренажёр"
    if allow_lessons is True and allow_trainer is False:
        return "Только уроки"
    if allow_lessons is False and allow_trainer is True:
        return "Только тренажёр"
    if allow_lessons is False and allow_trainer is False:
        return "Нет доступа"
    return "Не задано / без ограничений"


def _load_effective_access_for_user(user_id: int) -> EffectiveAccess:
    """Load subscription access (no request-level cache)."""
    now = _now_utc_naive()
    sub = (
        UserSubscription.query.options(joinedload(UserSubscription.plan))
        .filter_by(user_id=user_id, status="active")
        .order_by(UserSubscription.ends_at.desc().nullslast(), UserSubscription.subscription_id.desc())
        .first()
    )
    if not sub:
        return EffectiveAccess(
            subscription=None,
            plan=None,
            allow_lessons=None,
            allow_trainer=None,
            status="none",
            ends_at_utc=None,
            seconds_left=None,
            lessons_remaining=None,
            label=_compute_label(None, None),
        )

    ends_at = sub.ends_at
    lessons_remaining = getattr(sub, 'lessons_remaining', None)
    
    time_expired = ends_at and ends_at < now
    lessons_expired = lessons_remaining is not None and lessons_remaining <= 0
    
    if time_expired or lessons_expired:
        return EffectiveAccess(
            subscription=sub,
            plan=sub.plan if sub.plan_id else None,
            allow_lessons=None,
            allow_trainer=None,
            status="expired",
            ends_at_utc=ends_at,
            seconds_left=0,
            lessons_remaining=lessons_remaining,
            label="Уроки закончились" if lessons_expired else "Подписка истекла",
        )

    plan = sub.plan if sub.plan_id else None
    allow_lessons = None
    allow_trainer = None
    if plan:
        allow_lessons = None if plan.allow_lessons is None else bool(plan.allow_lessons)
        allow_trainer = None if plan.allow_trainer is None else bool(plan.allow_trainer)

    seconds_left = None
    if ends_at:
        seconds_left = max(0, int((ends_at - now).total_seconds()))

    return EffectiveAccess(
        subscription=sub,
        plan=plan,
        allow_lessons=allow_lessons,
        allow_trainer=allow_trainer,
        status=(sub.status or "active"),
        ends_at_utc=ends_at,
        seconds_left=seconds_left,
        lessons_remaining=lessons_remaining,
        label=_compute_label(allow_lessons, allow_trainer),
    )


def get_effective_access_for_user(user_id: int) -> EffectiveAccess:
    """
    Returns best-effort effective access for a user based on latest active subscription.
    Cached for the lifetime of the current HTTP request (hooks + context_processor).
    """
    if has_request_context():
        cache = getattr(g, '_effective_access_by_user', None)
        if cache is None:
            cache = {}
            g._effective_access_by_user = cache
        cached = cache.get(user_id)
        if cached is not None:
            return cached
        eff = _load_effective_access_for_user(user_id)
        cache[user_id] = eff
        return eff
    return _load_effective_access_for_user(user_id)


def mark_subscription_expired_if_needed(sub: UserSubscription) -> None:
    """
    Best-effort helper: if ends_at passed, mark subscription as expired.
    Never raises.
    """
    try:
        now = _now_utc_naive()
        if sub and sub.status == "active" and sub.ends_at and sub.ends_at < now:
            sub.status = "expired"
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass

