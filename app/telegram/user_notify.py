"""
Единая точка проверки настроек Telegram перед отправкой.
Поддерживает quiet hours (тихие часы) по МСК.
"""
from __future__ import annotations

import html
import hashlib
import logging
from datetime import timezone
from typing import Optional
from sqlalchemy import or_

from app.models import User, UserProfile
from core.db_models import UserNotificationPreference, db, moscow_now
from app.runtime_state import get_json, set_json
from app.telegram.registry import NotificationTypeRegistry

logger = logging.getLogger(__name__)

# Mapping kind → UserProfile attribute
_KIND_TO_ATTR: dict[str, str] = {
    'homework_checked':          'tg_notify_homework_checked',
    'assignment_graded':         'tg_notify_homework_checked',
    'homework_returned':         'tg_notify_homework_returned',
    'assignment_returned':       'tg_notify_homework_returned',
    'homework_submitted':        'tg_notify_homework_submitted',
    'assignment_submitted':      'tg_notify_homework_submitted',
    'teacher_homework_submitted':'tg_notify_homework_submitted',
    'assignment_assigned':       'tg_notify_homework_submitted',
    'assignment_deadline':       'tg_notify_homework_submitted',
    'lesson_comment':            'tg_notify_homework_submitted',
    'review_queue':              'tg_notify_homework_submitted',
    'lesson_reminder':           'tg_notify_lesson_reminder',
    'lesson_scheduled':          'tg_notify_lesson_scheduled',
    'lesson_batch_scheduled':    'tg_notify_lesson_scheduled',
    'lesson_rescheduled':        'tg_notify_lesson_scheduled',
    'lesson_cancelled':          'tg_notify_lesson_scheduled',
    'lesson_started':            'tg_notify_lesson_scheduled',
    'lesson_started_student':    'tg_notify_lesson_scheduled',
    'lesson_finished':           'tg_notify_lesson_scheduled',
    'teacher_hw_note_reminder':  'tg_notify_homework_submitted',
    'new_message':               'tg_notify_new_message',
    'news':                      'tg_notify_news',
    'announcement':              'tg_notify_news',
    'broadcast':                 'tg_notify_news',
    'achievement':               'tg_notify_news',
    'achievement_unlocked':      'tg_notify_news',
    'family_link_created':       'tg_notify_news',
    'family_link_confirmed':     'tg_notify_news',
    'family_link_updated':       'tg_notify_news',
    'family_link_removed':       'tg_notify_news',
    'family_link_revoked':       'tg_notify_news',
    'referral_used':             'tg_notify_referral_used',
    'system_errors':             'tg_notify_system_errors',
    'system_critical_error':     'tg_notify_system_errors',
    'operational_alert':         'tg_notify_system_errors',
    'lesson_balance_changed':    'tg_notify_low_lessons',
    'low_lessons':               'tg_notify_low_lessons',
    'package_exhausted':         'tg_notify_low_lessons',
    'subscription_expiring':     'tg_notify_subscription_expiring',
    'bug_report_reply':          'tg_notify_bug_report_reply',
    'daily_digest':              'tg_notify_daily_digest',
    'child_digest':              'tg_notify_daily_digest',
}

# Public taxonomy for new application services.
TELEGRAM_NOTIFICATION_KINDS = frozenset({
    *_KIND_TO_ATTR.keys(),
    'generic',
    'lesson_batch_scheduled',
    'announcement',
    'broadcast',
    'package_exhausted',
    'lesson_started',
    'lesson_started_student',
    'lesson_finished',
    'teacher_hw_note_reminder',
})

# Kinds that bypass quiet hours (urgent or time-sensitive)
_QUIET_HOURS_BYPASS = {
    'system_errors',
    'system_critical_error',
    'operational_alert',
    'bug_report_reply',
    'lesson_scheduled',
    'lesson_rescheduled',
    'lesson_cancelled',
    'lesson_reminder',
    'lesson_started_student',
}
_TELEGRAM_DEDUPE_SECONDS = 120
_STUDENT_ACK_PROMPT = 'Уведомление пришло?(уведомления тестируются, это - временная мера)'
_STUDENT_ACK_BUTTON = '✅ Пришло'
_STUDENT_ACK_CALLBACK_PREFIX = 'notif_ack'
_STUDENT_FEEDBACK_CALLBACK_PREFIX = 'notif_fb'


def normalize_notification_kind(kind: Optional[str]) -> Optional[str]:
    """Keep notification policy keys stable across producers."""
    if kind is None:
        return None
    value = str(kind).strip().lower()
    if value == 'achievement_unlocked':
        return 'achievement'
    return value if value in TELEGRAM_NOTIFICATION_KINDS else 'generic'


STUDENT_NOTIFICATION_FEEDBACK_OPTIONS: dict[str, str] = {
    'dup': 'Это уведомление продублировалось',
    'late': 'Это уведомление пришло с опозданием',
    'bad': 'Этого уведомления не должно быть',
    'link': 'Это уведомление содержит некорректную ссылку',
}
STUDENT_NOTIFICATION_FEEDBACK_NUMBER_TO_CODE: dict[str, str] = {
    '1': 'dup',
    '2': 'late',
    '3': 'bad',
    '4': 'link',
}


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


def is_notification_enabled_for_user(
    user_id: int,
    role: str | None = None,
    kind: str | None = None,
) -> bool:
    """Check if notification kind is enabled for a given user and role.

    Resolution hierarchy:
    1. Check UserProfile.telegram_notifications_enabled (global killswitch)
    2. Check UserNotificationPreference (user_id, role, kind) explicit record
    3. Check legacy UserProfile.tg_notify_* attribute fallback (honor opt-outs)
    4. Fall back to NotificationTypeRegistry default for the role
    """
    if not user_id:
        return False
    user_id = int(user_id)

    profile = UserProfile.query.filter_by(user_id=user_id).first()
    if not profile or not profile.telegram_chat_id:
        return False
    if not _truthy(profile.telegram_notifications_enabled):
        return False

    if not kind:
        return True

    kind = normalize_notification_kind(kind) or kind

    if not role:
        user = User.query.get(user_id)
        role = getattr(user, 'role', 'student') or 'student'
    role = str(role).lower().strip()

    # 1. UserNotificationPreference table
    pref = UserNotificationPreference.query.filter_by(
        user_id=user_id,
        role=role,
        event_kind=kind,
    ).first()
    if pref is not None:
        return bool(pref.is_enabled)

    # 2. Legacy UserProfile fallback (honor explicit opt-outs)
    attr = _KIND_TO_ATTR.get(kind)
    if attr and hasattr(profile, attr):
        legacy_val = getattr(profile, attr)
        if legacy_val is False:
            return False

    # 3. Registry default
    return NotificationTypeRegistry.is_default_enabled(kind, role)


def get_user_notification_preference(
    user_id: int,
    role: str,
    kind: str,
) -> tuple[bool, str]:
    """Return (is_enabled, provenance) where provenance is 'user', 'legacy', or 'default'."""
    user_id = int(user_id)
    role = str(role).lower().strip()
    kind = normalize_notification_kind(kind) or kind

    pref = UserNotificationPreference.query.filter_by(
        user_id=user_id,
        role=role,
        event_kind=kind,
    ).first()
    if pref is not None:
        return bool(pref.is_enabled), "user"

    profile = UserProfile.query.filter_by(user_id=user_id).first()
    attr = _KIND_TO_ATTR.get(kind)
    if profile and attr and hasattr(profile, attr):
        legacy_val = getattr(profile, attr)
        if legacy_val is False:
            return False, "legacy"

    return NotificationTypeRegistry.is_default_enabled(kind, role), "default"


def set_user_notification_preference(
    user_id: int,
    role: str,
    kind: str,
    is_enabled: bool,
) -> UserNotificationPreference:
    """Upsert user's explicit preference."""
    user_id = int(user_id)
    role = str(role).lower().strip()
    kind = normalize_notification_kind(kind) or kind

    pref = UserNotificationPreference.query.filter_by(
        user_id=user_id,
        role=role,
        event_kind=kind,
    ).first()
    if pref:
        pref.is_enabled = bool(is_enabled)
        pref.updated_at = moscow_now()
    else:
        pref = UserNotificationPreference(
            user_id=user_id,
            role=role,
            event_kind=kind,
            is_enabled=bool(is_enabled),
        )
        db.session.add(pref)
    db.session.commit()
    return pref


def reset_user_notification_preferences_to_defaults(
    user_id: int,
    role: str,
) -> int:
    """Delete explicit preferences for user and role, reverting to defaults."""
    user_id = int(user_id)
    role = str(role).lower().strip()
    count = UserNotificationPreference.query.filter_by(
        user_id=user_id,
        role=role,
    ).delete()
    db.session.commit()
    return count


def user_allows_telegram_notification(
    profile: UserProfile | None,
    kind: Optional[str] = None,
    role: Optional[str] = None,
) -> bool:
    """
    Проверяет: можно ли отправить уведомление данного типа профилю.

    kind=None — только глобальный переключатель.
    """
    kind = normalize_notification_kind(kind)
    if not profile or profile.telegram_chat_id is None:
        return False
    if not _truthy(profile.telegram_notifications_enabled):
        return False

    if not is_notification_enabled_for_user(profile.user_id, role=role, kind=kind):
        return False

    # Тихие часы (кроме bypass-типов)
    if kind not in _QUIET_HOURS_BYPASS and _in_quiet_hours(profile):
        return False

    return True


def _is_student_profile(profile: UserProfile | None) -> bool:
    if not profile:
        return False
    user = User.query.get(profile.user_id)
    if not user:
        return False
    try:
        if hasattr(user, 'is_student') and user.is_student():
            return True
    except Exception:
        pass
    return getattr(user, 'role', None) == 'student'


def _telegram_dedupe_key(profile: UserProfile | None, text: str, kind: Optional[str]) -> str | None:
    if not profile or not getattr(profile, 'telegram_chat_id', None):
        return None
    raw = f'{int(profile.telegram_chat_id)}|{kind or "generic"}|{text or ""}'
    digest = hashlib.sha1(raw.encode('utf-8')).hexdigest()
    return f'telegram:dedupe:{digest}'


def _telegram_dedupe_hit(profile: UserProfile | None, text: str, kind: Optional[str]) -> bool:
    key = _telegram_dedupe_key(profile, text, kind)
    if not key:
        return False
    try:
        if get_json(key):
            return True
    except Exception:
        return False
    return False


def _mark_telegram_dedupe(profile: UserProfile | None, text: str, kind: Optional[str]) -> None:
    key = _telegram_dedupe_key(profile, text, kind)
    if not key:
        return
    try:
        set_json(key, {'seen': True}, ttl_seconds=_TELEGRAM_DEDUPE_SECONDS)
    except Exception:
        return


def _copy_inline_keyboard(reply_markup: Optional[dict]) -> list[list[dict]]:
    if not isinstance(reply_markup, dict):
        return []
    keyboard = reply_markup.get('inline_keyboard')
    if not isinstance(keyboard, list):
        return []
    copied: list[list[dict]] = []
    for row in keyboard:
        if not isinstance(row, list):
            continue
        copied.append([dict(button) for button in row if isinstance(button, dict)])
    return copied


def _with_student_ack_controls(
    profile: UserProfile | None,
    text: str,
    kind: Optional[str],
    reply_markup: Optional[dict],
) -> tuple[str, Optional[dict]]:
    if not _is_student_profile(profile):
        return text, reply_markup

    text_with_prompt = text if _STUDENT_ACK_PROMPT in text else f'{text}\n\n{_STUDENT_ACK_PROMPT}'
    keyboard = _copy_inline_keyboard(reply_markup)
    callback_kind = (kind or 'generic')[:24]
    callback_data = f'{_STUDENT_ACK_CALLBACK_PREFIX}:{profile.user_id}:{callback_kind}'
    feedback_rows = [
        [
            {
                'text': '🔁 Продублировалось',
                'callback_data': f'{_STUDENT_FEEDBACK_CALLBACK_PREFIX}:{profile.user_id}:dup:{callback_kind}',
            },
            {
                'text': '⏰ С опозданием',
                'callback_data': f'{_STUDENT_FEEDBACK_CALLBACK_PREFIX}:{profile.user_id}:late:{callback_kind}',
            },
        ],
        [
            {
                'text': '🚫 Не должно быть',
                'callback_data': f'{_STUDENT_FEEDBACK_CALLBACK_PREFIX}:{profile.user_id}:bad:{callback_kind}',
            },
            {
                'text': '🔗 Некорректная ссылка',
                'callback_data': f'{_STUDENT_FEEDBACK_CALLBACK_PREFIX}:{profile.user_id}:link:{callback_kind}',
            },
        ],
        [
            {
                'text': '🧩 Несколько вариантов',
                'callback_data': f'{_STUDENT_FEEDBACK_CALLBACK_PREFIX}:{profile.user_id}:multi:{callback_kind}',
            },
        ],
    ]

    has_ack = any(
        str(button.get('callback_data') or '').startswith(f'{_STUDENT_ACK_CALLBACK_PREFIX}:')
        for row in keyboard
        for button in row
    )
    if not has_ack:
        keyboard.append([{'text': _STUDENT_ACK_BUTTON, 'callback_data': callback_data}])
    has_feedback = any(
        str(button.get('callback_data') or '').startswith(f'{_STUDENT_FEEDBACK_CALLBACK_PREFIX}:')
        for row in keyboard
        for button in row
    )
    if not has_feedback:
        keyboard.extend(feedback_rows)

    return text_with_prompt, {'inline_keyboard': keyboard}


def send_student_notification_ack_report(
    *,
    student_chat_id: int,
    student_username: str | None,
    student_first_name: str | None,
    student_last_name: str | None,
    notification_text: str,
    kind: str | None = None,
    feedback_title: str | None = None,
    feedback_details: str | None = None,
) -> int:
    """Deprecated test reporting hook: neutralized to prevent noisy developer alerts."""
    logger.debug('student_notification_ack received for chat_id=%s kind=%s (suppressed)', student_chat_id, kind)
    return 0


def notify_user_by_id(
    user_id: int,
    text: str,
    *,
    kind: Optional[str] = None,
    reply_markup: Optional[dict] = None,
) -> bool:
    """Отправить сообщение пользователю платформы по user_id."""
    from app.telegram.delivery import enqueue_delivery
    from app.models import db
    kind = normalize_notification_kind(kind)

    try:
        profile = get_profile_for_user(int(user_id))
        if not user_allows_telegram_notification(profile, kind):
            return False
        dedupe_text = text
        if _telegram_dedupe_hit(profile, dedupe_text, kind):
            logger.info('Skipped duplicate Telegram notification user_id=%s kind=%s', user_id, kind)
            return True
        row = enqueue_delivery(
            int(user_id),
            text,
            kind=kind,
            reply_markup=reply_markup,
        )
        db.session.flush()
        queued = row.status in {'pending', 'processing', 'retry', 'sent'}
        if queued:
            _mark_telegram_dedupe(profile, dedupe_text, kind)
        return queued
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
    from app.telegram.delivery import enqueue_delivery
    from app.models import db
    kind = normalize_notification_kind(kind)

    try:
        profile = UserProfile.query.filter_by(telegram_chat_id=chat_id).first()
        if not profile:
            user = User.query.filter(or_(
                User.telegram_chat_id == int(chat_id),
                User.tg_id == int(chat_id),
                User.telegram_id == int(chat_id),
            )).first()
            profile = get_profile_for_user(user.id) if user else None
        if not user_allows_telegram_notification(profile, kind):
            return False
        dedupe_text = text
        if _telegram_dedupe_hit(profile, dedupe_text, kind):
            logger.info('Skipped duplicate Telegram notification chat_id=%s kind=%s', chat_id, kind)
            return True
        row = enqueue_delivery(
            int(profile.user_id),
            text,
            kind=kind,
            reply_markup=reply_markup,
        )
        db.session.flush()
        queued = row.status in {'pending', 'processing', 'retry', 'sent'}
        if queued:
            _mark_telegram_dedupe(profile, dedupe_text, kind)
        return queued
    except Exception as e:

        logger.warning('notify_user_by_chat_id failed chat_id=%s: %s', chat_id, e, exc_info=True)
        return False


def get_profile_for_user(user_id: int) -> UserProfile | None:
    profile = UserProfile.query.filter_by(user_id=user_id).first()
    if not profile:
        return None
    if profile.telegram_chat_id is None:
        user = User.query.get(int(user_id))
        legacy_chat_id = (
            getattr(user, 'telegram_chat_id', None)
            or getattr(user, 'tg_id', None)
        ) if user else None
        if legacy_chat_id is not None:
            try:
                profile.telegram_chat_id = int(legacy_chat_id)
                if not profile.telegram_id:
                    profile.telegram_id = str(getattr(user, 'telegram_id', None) or legacy_chat_id)
            except (TypeError, ValueError):
                logger.warning('Could not reconcile legacy Telegram identity user_id=%s', user_id)
    return profile
