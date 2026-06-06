"""
Единая точка проверки настроек Telegram перед отправкой.
Поддерживает quiet hours (тихие часы) по МСК.
"""
from __future__ import annotations

import logging
from datetime import timezone
from typing import Optional

from app.models import UserProfile

logger = logging.getLogger(__name__)

# Mapping kind → UserProfile attribute
_KIND_TO_ATTR: dict[str, str] = {
    'homework_checked':          'tg_notify_homework_checked',
    'homework_returned':         'tg_notify_homework_returned',
    'homework_submitted':        'tg_notify_homework_submitted',
    'lesson_reminder':           'tg_notify_lesson_reminder',
    'lesson_scheduled':          'tg_notify_lesson_scheduled',
    'new_message':               'tg_notify_new_message',
    'news':                      'tg_notify_news',
    'referral_used':             'tg_notify_referral_used',
    'system_errors':             'tg_notify_system_errors',
    'low_lessons':               'tg_notify_low_lessons',
    'subscription_expiring':     'tg_notify_subscription_expiring',
    'bug_report_reply':          'tg_notify_bug_report_reply',
    'daily_digest':              'tg_notify_daily_digest',
}

# Kinds that bypass quiet hours (urgent or time-sensitive)
_QUIET_HOURS_BYPASS = {'system_errors', 'bug_report_reply', 'lesson_scheduled', 'lesson_reminder'}


def _truthy(v) -> bool:
    return v is None or bool(v)


def _in_quiet_hours(profile: UserProfile) -> bool:
    """Возвращает True, если сейчас тихое время (МСК)."""
    try:
        start = getattr(profile, 'tg_quiet_hours_start', None)
        end = getattr(profile, 'tg_quiet_hours_end', None)
        if start is None or end is None:
            return False
        from core.db_models import MOSCOW_TZ, moscow_now
        now_hour = moscow_now().hour
        if start <= end:
            return start <= now_hour < end
        else:
            # Ночной диапазон, например 23-7
            return now_hour >= start or now_hour < end
    except Exception:
        return False


def user_allows_telegram_notification(
    profile: UserProfile | None,
    kind: Optional[str] = None,
) -> bool:
    """
    Проверяет: можно ли отправить уведомление данного типа профилю.

    kind=None — только глобальный переключатель.
    """
    if not profile or profile.telegram_chat_id is None:
        return False
    if not _truthy(profile.telegram_notifications_enabled):
        return False

    attr = _KIND_TO_ATTR.get(kind) if kind else None
    if attr and kind not in {'lesson_scheduled', 'lesson_reminder'}:
        if not _truthy(getattr(profile, attr, True)):
            return False

    # Тихие часы (кроме bypass-типов)
    if kind not in _QUIET_HOURS_BYPASS and _in_quiet_hours(profile):
        return False

    return True


def notify_user_by_id(
    user_id: int,
    text: str,
    *,
    kind: Optional[str] = None,
    reply_markup: Optional[dict] = None,
) -> bool:
    """Отправить сообщение пользователю платформы по user_id."""
    from app.telegram.notifications import send_telegram_message

    try:
        profile = UserProfile.query.filter_by(user_id=user_id).first()
        if not user_allows_telegram_notification(profile, kind):
            return False
        cid = int(profile.telegram_chat_id)
        result = send_telegram_message(cid, text, reply_markup=reply_markup)
        return bool(result and result.get('ok'))
    except Exception as e:
        logger.warning('notify_user_by_id failed user_id=%s: %s', user_id, e, exc_info=True)
        return False


def notify_user_by_chat_id(
    chat_id: int,
    text: str,
    *,
    kind: Optional[str] = None,
    reply_markup: Optional[dict] = None,
) -> bool:
    """Отправить сообщение по telegram_chat_id с проверкой настроек."""
    from app.telegram.notifications import send_telegram_message

    try:
        profile = UserProfile.query.filter_by(telegram_chat_id=chat_id).first()
        if not user_allows_telegram_notification(profile, kind):
            return False
        result = send_telegram_message(int(chat_id), text, reply_markup=reply_markup)
        return bool(result and result.get('ok'))
    except Exception as e:
        logger.warning('notify_user_by_chat_id failed chat_id=%s: %s', chat_id, e, exc_info=True)
        return False


def get_profile_for_user(user_id: int) -> UserProfile | None:
    return UserProfile.query.filter_by(user_id=user_id).first()
