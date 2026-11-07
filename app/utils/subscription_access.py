from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from flask import g, has_request_context, request
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
            allow_lessons=False,
            allow_trainer=False,
            status="none",
            ends_at_utc=None,
            seconds_left=None,
            lessons_remaining=None,
            label=_compute_label(False, False),
        )

    ends_at = sub.ends_at
    lessons_remaining = getattr(sub, 'lessons_remaining', None)
    
    time_expired = ends_at and ends_at < now
    lessons_expired = lessons_remaining is not None and lessons_remaining <= 0
    
    if time_expired or lessons_expired:
        return EffectiveAccess(
            subscription=sub,
            plan=sub.plan if sub.plan_id else None,
            allow_lessons=False,
            allow_trainer=False,
            status="expired",
            ends_at_utc=ends_at,
            seconds_left=0,
            lessons_remaining=lessons_remaining,
            label="Уроки закончились" if lessons_expired else "Подписка истекла",
        )

    plan = sub.plan if sub.plan_id else None
    allow_lessons = False
    allow_trainer = False
    if plan:
        allow_lessons = bool(plan.allow_lessons) if plan.allow_lessons is not None else False
        allow_trainer = bool(plan.allow_trainer) if plan.allow_trainer is not None else False

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
        cache = getattr(request, '_effective_access_by_user', None)
        if cache is None:
            cache = {}
            try:
                request._effective_access_by_user = cache
            except Exception:
                pass
        cached = cache.get(user_id)
        if cached is not None:
            return cached
        eff = _load_effective_access_for_user(user_id)
        cache[user_id] = eff
        return eff
    return _load_effective_access_for_user(user_id)


def get_course_lesson_balance_summary(user_id: int) -> dict:
    """Return active lesson balances grouped by exam, subject and level."""
    now = _now_utc_naive()
    subscriptions = (
        UserSubscription.query
        .options(joinedload(UserSubscription.plan))
        .filter_by(user_id=user_id, status='active')
        .order_by(UserSubscription.ends_at.desc().nullslast(), UserSubscription.subscription_id.desc())
        .all()
    )

    grouped = {}
    for subscription in subscriptions:
        if subscription.ends_at and subscription.ends_at < now:
            continue

        plan = subscription.plan if subscription.plan_id else None
        exam = (subscription.exam or (plan.exam if plan else '') or '').strip().lower()
        subject = (subscription.subject or (plan.subject if plan else '') or '').strip().lower()
        level = (subscription.level or (plan.level if plan else '') or '').strip().lower()
        key = (exam, subject, level)
        course = grouped.setdefault(key, {
            'exam': exam,
            'subject': subject,
            'level': level,
            'lessons_remaining': 0,
            'is_unlimited': False,
            'ends_at': None,
        })

        if subscription.lessons_remaining is None:
            course['is_unlimited'] = True
        else:
            course['lessons_remaining'] += max(0, int(subscription.lessons_remaining))

        if subscription.ends_at and (course['ends_at'] is None or subscription.ends_at > course['ends_at']):
            course['ends_at'] = subscription.ends_at

    exam_labels = {'ege': 'ЕГЭ', 'oge': 'ОГЭ'}
    subject_labels = {'inf': 'Информатика', 'math': 'Математика'}
    level_labels = {'prof': 'Профиль', 'base': 'База'}
    courses = []
    for course in grouped.values():
        course['key'] = '|'.join((course['exam'], course['subject'], course['level']))
        parts = []
        if course['exam']:
            parts.append(exam_labels.get(course['exam'], course['exam'].upper()))
        if course['subject']:
            parts.append(subject_labels.get(course['subject'], course['subject'].capitalize()))
        if course['level']:
            parts.append(level_labels.get(course['level'], course['level'].capitalize()))
        course['label'] = ' · '.join(parts) or 'Общий баланс без предмета'
        courses.append(course)

    courses.sort(key=lambda course: (
        {'math': 0, 'inf': 1}.get(course['subject'], 2),
        course['exam'],
        course['level'],
    ))
    total_lessons = None if any(course['is_unlimited'] for course in courses) else sum(
        course['lessons_remaining'] for course in courses
    )
    return {
        'courses': courses,
        'total_lessons': total_lessons,
        'has_active_subscriptions': bool(courses),
    }


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

