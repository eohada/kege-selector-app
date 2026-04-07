"""
Единая точка проверки настроек Telegram у профиля перед отправкой.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.models import UserProfile

logger = logging.getLogger(__name__)


def _truthy(v) -> bool:
    return v is None or bool(v)


def user_allows_telegram_notification(
    profile: UserProfile | None,
    kind: Optional[str] = None,
) -> bool:
    """
    kind:
      - None: только глобальный переключатель и наличие chat_id
      - homework_checked, homework_returned, homework_submitted (teacher),
      - lesson_reminder, lesson_scheduled, news, referral_used, system_errors
    """
    if not profile or profile.telegram_chat_id is None:
        return False
    if not _truthy(profile.telegram_notifications_enabled):
        return False
    mapping = {
        'homework_checked': 'tg_notify_homework_checked',
        'homework_returned': 'tg_notify_homework_returned',
        'homework_submitted': 'tg_notify_homework_submitted',
        'lesson_reminder': 'tg_notify_lesson_reminder',
        'lesson_scheduled': 'tg_notify_lesson_scheduled',
        'new_message': 'tg_notify_new_message',
        'news': 'tg_notify_news',
        'referral_used': 'tg_notify_referral_used',
        'system_errors': 'tg_notify_system_errors',
        'low_lessons': 'tg_notify_low_lessons',
    }
    if not kind:
        return True
    attr = mapping.get(kind)
    if not attr:
        return True
    return _truthy(getattr(profile, attr, True))


def notify_user_by_id(
    user_id: int,
    text: str,
    *,
    kind: Optional[str] = None,
    reply_markup: Optional[dict] = None,
) -> bool:
    """Отправить сообщение пользователю платформы по user_id (если разрешено настройками)."""
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


def get_profile_for_user(user_id: int) -> UserProfile | None:
    return UserProfile.query.filter_by(user_id=user_id).first()
