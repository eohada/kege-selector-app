from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

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

    # subscription / plan
    subscription: Optional[UserSubscription]
    plan: Optional[TariffPlan]

    # effective module flags
    allow_lessons: Optional[bool]  # None => unknown / not defined by plan
    allow_trainer: Optional[bool]  # None => unknown / not defined by plan

    # timing
    status: str  # none|active|expired|cancelled|paused
    ends_at_utc: Optional[datetime]
    seconds_left: Optional[int]

    # display
    label: str


def _now_utc_naive() -> datetime:
    # Always compare naive UTC datetimes (matches datetime.utcnow() usage across codebase).
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


def get_effective_access_for_user(user_id: int) -> EffectiveAccess:
    """
    Returns best-effort effective access for a user based on latest active subscription.
    """
    now = _now_utc_naive()
    sub = (
        UserSubscription.query.filter_by(user_id=user_id, status="active")
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
            label=_compute_label(None, None),
        )

    ends_at = sub.ends_at
    if ends_at and ends_at < now:
        # subscription is logically expired (even if status field wasn't updated yet)
        return EffectiveAccess(
            subscription=sub,
            plan=TariffPlan.query.get(sub.plan_id) if sub.plan_id else None,
            allow_lessons=None,
            allow_trainer=None,
            status="expired",
            ends_at_utc=ends_at,
            seconds_left=0,
            label="Подписка истекла",
        )

    plan = TariffPlan.query.get(sub.plan_id) if sub.plan_id else None
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
        label=_compute_label(allow_lessons, allow_trainer),
    )


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

