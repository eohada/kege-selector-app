"""
Единая точка проверки настроек Telegram перед отправкой.
Поддерживает quiet hours (тихие часы) по МСК.
"""
from __future__ import annotations

import html
import logging
from datetime import timezone
from typing import Optional

from app.models import User, UserProfile

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
_STUDENT_ACK_PROMPT = 'Уведомление пришло?(уведомления тестируются, это - временная мера)'
_STUDENT_ACK_BUTTON = '✅ Пришло'
_STUDENT_ACK_CALLBACK_PREFIX = 'notif_ack'
_STUDENT_FEEDBACK_CALLBACK_PREFIX = 'notif_fb'
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
    """Сообщить создателям, что ученик дал обратную связь по тестовому уведомлению."""
    from app.telegram.notifications import send_telegram_message
    from core.db_models import moscow_now

    username = (student_username or '').strip().lstrip('@')
    full_name = ' '.join(part for part in [student_first_name, student_last_name] if part).strip()
    if username:
        student_tag = f'@{username}'
    elif full_name:
        student_tag = f'{full_name} (chat_id {student_chat_id})'
    else:
        student_tag = f'chat_id {student_chat_id}'

    confirmed_at = moscow_now().strftime('%d.%m.%Y %H:%M:%S')
    text_plain = (notification_text or '').strip() or 'Текст уведомления недоступен'
    if len(text_plain) > 2600:
        text_plain = f'{text_plain[:2600].rstrip()}\n...'

    header = '✅ <b>Ученик подтвердил получение уведомления</b>'
    if feedback_title:
        header = '⚠️ <b>Ученик отметил проблему с уведомлением</b>'

    feedback_block = ''
    if feedback_title:
        feedback_block = f'🧪 Обратная связь: <b>{html.escape(feedback_title)}</b>\n'
        if feedback_details:
            feedback_block += f'📝 Детали: <b>{html.escape(feedback_details)}</b>\n'

    report = (
        f'{header}\n\n'
        f'👤 Telegram ученика: <b>{html.escape(student_tag)}</b>\n'
        f'🆔 Chat ID: <code>{int(student_chat_id)}</code>\n'
        f'🔔 Тип: <code>{html.escape(kind or "generic")}</code>\n'
        f'{feedback_block}'
        f'🕒 Подтверждено: <b>{html.escape(confirmed_at)} МСК</b>\n\n'
        '<b>Текст уведомления:</b>\n'
        f'<pre>{html.escape(text_plain)}</pre>'
    )

    recipients = (
        User.query
        .join(UserProfile, UserProfile.user_id == User.id)
        .filter(UserProfile.telegram_chat_id.isnot(None))
        .filter(User.role.in_(('creator', 'chief_admin')))
        .all()
    )

    sent = 0
    for creator in recipients:
        profile = UserProfile.query.filter_by(user_id=creator.id).first()
        chat_id = getattr(profile, 'telegram_chat_id', None)
        if not chat_id:
            continue
        try:
            result = send_telegram_message(int(chat_id), report)
            if result and result.get('ok'):
                sent += 1
        except Exception:
            logger.warning('notification ack report failed creator_id=%s', creator.id, exc_info=True)
    return sent


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
        text, reply_markup = _with_student_ack_controls(profile, text, kind, reply_markup)
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
        text, reply_markup = _with_student_ack_controls(profile, text, kind, reply_markup)
        result = send_telegram_message(int(chat_id), text, reply_markup=reply_markup)
        return bool(result and result.get('ok'))
    except Exception as e:
        logger.warning('notify_user_by_chat_id failed chat_id=%s: %s', chat_id, e, exc_info=True)
        return False


def get_profile_for_user(user_id: int) -> UserProfile | None:
    return UserProfile.query.filter_by(user_id=user_id).first()
