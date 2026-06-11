"""
Telegram Bot — command handlers, role-based menus, FSM conversations.

Roles:
  student / parent      → student menu
  creator / chief_admin → creator menu
  tutor / content_maker → teacher menu

FSM states:
  BUG_REPORT_TEXT   — ожидаем описание + опц. скриншот от ученика
  CREATOR_REPLY_TEXT — ожидаем текст ответа от создателя
"""
from __future__ import annotations

import html
import logging
import os
import random
import secrets
from datetime import datetime, timezone
from typing import Optional

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
)
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes, ConversationHandler
from sqlalchemy import text, func
from werkzeug.security import generate_password_hash

from app.telegram.db import get_session, close_session
from app.telegram.compat import (
    get_user_by_chat_id,
    get_student_by_email,
    get_lessons,
    build_lessons_text,
    build_stats_text,
    build_help_message,
    esc,
    WELCOME_MESSAGE,
    HELP_MESSAGE,
    PROFILE_NOT_LINKED,
    ERROR_MESSAGE,
)
from app.utils.release_notes import build_release_notes_text
from app.telegram.config import (
    APP_URL,
    APP_OPEN_URL,
    BOOTSTRAP_CREATOR_CHAT_ID,
    BOOTSTRAP_CREATOR_DISPLAY_NAME,
    BOOTSTRAP_CREATOR_USERNAME,
)

from app.telegram.link_api import call_link_bot_api
from app.utils.relationship_scope import get_family_tie_by_id, get_family_ties_for_parent, get_family_ties_for_student
from app.telegram.role_management import (
    MAIN_BOT_ROLES,
    actor_can_assign_role,
    actor_can_clear_role,
    clear_all_roles,
    notify_role_changed,
    relation_summary,
    role_label,
    set_single_role,
    subscription_summary_for_user,
    user_display_name,
)

logger = logging.getLogger(__name__)

UNAUTHORIZED_ROLE_OPTIONS = ('student', 'parent', 'tutor', 'designer', 'admin')

# ---------------------------------------------------------------------------
# FSM state constants
# ---------------------------------------------------------------------------
BUG_REPORT_TEXT = 1
CREATOR_REPLY_TEXT = 2

# context.user_data key for storing report_id while creator types reply
_CTX_REPLY_REPORT_ID = 'bug_reply_report_id'
_CTX_REPLY_STUDENT_CHAT_ID = 'bug_reply_student_chat_id'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _answer_callback_query(query, *args, **kwargs) -> bool:
    """Acknowledge callback quickly without making old callbacks retry forever."""
    if not query:
        return False
    try:
        await query.answer(*args, **kwargs)
        return True
    except BadRequest as exc:
        message = str(exc).lower()
        if 'query is too old' in message or 'query id is invalid' in message:
            logger.warning('Telegram callback answer skipped: %s', exc)
            return False
        raise
    except TelegramError as exc:
        logger.warning('Telegram callback answer failed: %s', exc)
        return False

def _mini_app_url() -> str:
    base = (APP_URL or os.environ.get('APP_URL') or '').strip().rstrip('/')
    return f'{base}/tg-app/' if base else ''


def _normalize_tg_username(value: str | None) -> str:
    return (value or '').strip().lstrip('@').lower()


def _clear_stale_tg_link(profile) -> bool:
    """
    Освобождает Telegram-связь у старой записи, если владелец уже неактивен
    или запись осиротела.
    """
    if not profile:
        return False
    try:
        user = getattr(profile, 'user', None)
        if user and getattr(user, 'is_active', True):
            return False
    except Exception:
        return False

    changed = False
    for attr in (
        'telegram_chat_id',
        'telegram_id',
        'telegram_link_code',
        'telegram_link_code_expires',
        'telegram_link_token',
        'telegram_link_token_expires',
    ):
        if getattr(profile, attr, None) is not None:
            setattr(profile, attr, None)
            changed = True
    return changed


def _creator_identity_matches(chat_id: int, tg_username: str | None = None) -> bool:
    username = _normalize_tg_username(tg_username)
    if chat_id == BOOTSTRAP_CREATOR_CHAT_ID:
        return True
    return bool(username and username == BOOTSTRAP_CREATOR_USERNAME)


def _ensure_bootstrap_creator_link(
    chat_id: int,
    *,
    tg_username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> Optional[dict]:
    if not _creator_identity_matches(chat_id, tg_username):
        return None

    from app.models import db, User, UserProfile, UserRole

    username_norm = _normalize_tg_username(tg_username) or BOOTSTRAP_CREATOR_USERNAME
    telegram_id = f'@{username_norm}' if username_norm else None

    profile = UserProfile.query.filter_by(telegram_chat_id=chat_id).first()
    user = profile.user if profile and profile.user else None

    if not user and telegram_id:
        profile = UserProfile.query.filter_by(telegram_id=telegram_id).first()
        user = profile.user if profile and profile.user else None

    if not user and username_norm:
        user = User.query.filter_by(username=username_norm).first()

    if not user:
        user = User.query.filter_by(role='creator').order_by(User.id.asc()).first()

    created = False
    if not user:
        user = User(
            username=username_norm or 'creator',
            email=None,
            password_hash=generate_password_hash(secrets.token_urlsafe(24)),
            role='creator',
            is_active=True,
            telegram_link=telegram_id,
            custom_status='автопривязка Telegram для создателя',
        )
        db.session.add(user)
        db.session.flush()
        created = True

    user.is_active = True
    user.role = 'creator'
    if telegram_id:
        user.telegram_link = telegram_id

    if not any((ur.role == 'creator') for ur in (user.user_roles or [])):
        db.session.add(UserRole(user_id=user.id, role='creator'))

    profile = profile or getattr(user, 'profile', None)
    if not profile:
        profile = UserProfile(user_id=user.id)
        db.session.add(profile)

    profile.telegram_chat_id = chat_id
    if telegram_id:
        profile.telegram_id = telegram_id
    if first_name and not profile.first_name:
        profile.first_name = first_name
    if last_name and not profile.last_name:
        profile.last_name = last_name
    if not profile.first_name:
        profile.first_name = BOOTSTRAP_CREATOR_DISPLAY_NAME
    profile.telegram_notifications_enabled = True

    db.session.commit()
    _track_start_lead(
        chat_id,
        tg_username=tg_username,
        first_name=first_name,
        last_name=last_name,
        assigned_user_id=user.id,
        is_authorized=True,
    )
    logger.info(
        'Bootstrap creator Telegram link ensured for chat_id=%s username=%s user_id=%s created=%s',
        chat_id, username_norm, user.id, created,
    )

    session = get_session()
    try:
        return get_user_by_chat_id(session, chat_id)
    finally:
        close_session(session)


def touch_telegram_activity(chat_id: int) -> None:
    """Обновить время последней активности пользователя в боте."""
    try:
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        session = get_session()
        try:
            session.execute(
                text('''
                    UPDATE "UserProfiles"
                    SET telegram_last_interaction_at = :ts, updated_at = :ts
                    WHERE telegram_chat_id = :cid
                '''),
                {'ts': now_naive, 'cid': chat_id},
            )
            session.commit()
        except Exception:
            session.rollback()
        finally:
            close_session(session)
    except Exception:
        logger.debug('touch_telegram_activity failed for chat_id=%s', chat_id, exc_info=True)


def _track_start_lead(
    chat_id: int,
    *,
    tg_username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    assigned_user_id: int | None = None,
    is_authorized: bool = False,
) -> None:
    """Запомнить Telegram-пользователя, который написал боту."""
    try:
        from app.models import db, TelegramStartLead

        db.create_all()

        username = _normalize_tg_username(tg_username) or None
        lead = TelegramStartLead.query.filter_by(telegram_chat_id=chat_id).first()
        if not lead:
            lead = TelegramStartLead(telegram_chat_id=chat_id)
            db.session.add(lead)

        lead.telegram_username = username
        lead.first_name = first_name or lead.first_name
        lead.last_name = last_name or lead.last_name
        lead.last_seen_at = datetime.now(timezone.utc).replace(tzinfo=None)
        if assigned_user_id is not None:
            lead.assigned_user_id = assigned_user_id
        if is_authorized:
            lead.is_authorized = True
        elif lead.is_authorized is None:
            lead.is_authorized = False
        db.session.commit()
    except Exception:
        logger.debug('track_start_lead failed for chat_id=%s', chat_id, exc_info=True)
        try:
            from app.models import db
            db.session.rollback()
        except Exception:
            pass


def _build_student_profile_url(student_id: int | None) -> str:
    if not APP_URL or not student_id:
        return ''
    return f'{APP_URL.rstrip("/")}/student/{int(student_id)}'


def _telegram_public_link(username: str | None) -> str:
    username = _normalize_tg_username(username)
    return f'https://t.me/{username}' if username else ''


def _pick_lead_display_name(lead) -> str:
    full_name = f'{getattr(lead, "first_name", "") or ""} {getattr(lead, "last_name", "") or ""}'.strip()
    username = getattr(lead, 'telegram_username', None)
    if full_name:
        return full_name
    if username:
        return f'@{username}'
    return f'chat {getattr(lead, "telegram_chat_id", "—")}'


def _get_linked_user(
    chat_id: int,
    *,
    tg_username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> Optional[dict]:
    session = get_session()
    try:
        linked = get_user_by_chat_id(session, chat_id)
    finally:
        close_session(session)
    if linked:
        return linked
    return _ensure_bootstrap_creator_link(
        chat_id,
        tg_username=tg_username,
        first_name=first_name,
        last_name=last_name,
    )


def _is_creator(role: str) -> bool:
    return role == 'creator'


def _is_senior_admin(role: str) -> bool:
    return role == 'chief_admin'


def _is_admin(role: str) -> bool:
    return role in ('creator', 'chief_admin', 'admin')


def _can_manage_roles(role: str) -> bool:
    return role in ('creator', 'chief_admin', 'admin')


def _is_teacher(role: str) -> bool:
    return role in ('creator', 'chief_admin', 'admin', 'tutor', 'content_maker')


def _is_student(role: str) -> bool:
    return role == 'student'


def _is_parent(role: str) -> bool:
    return role == 'parent'


def _has_access_role(role: str) -> bool:
    return role in {'creator', 'chief_admin', 'admin', 'tutor', 'content_maker', 'parent', 'student', 'designer'}


# ---------------------------------------------------------------------------
# Keyboard builders
# ---------------------------------------------------------------------------

_BACK_ROW = [InlineKeyboardButton('« Меню', callback_data='back_menu')]


def _reply_keyboard_with_mini_app(user: dict | None) -> ReplyKeyboardMarkup | None:
    url = _mini_app_url()
    if not url or not user:
        return None
    return ReplyKeyboardMarkup(
        [[KeyboardButton(text='📱 Открыть BooStudy', web_app=WebAppInfo(url=url))]],
        resize_keyboard=True,
    )


def _menu_keyboard(user: dict | None) -> InlineKeyboardMarkup:
    """Role-aware inline keyboard for /menu."""
    role = (user or {}).get('role', '')

    if not _has_access_role(role):
        return InlineKeyboardMarkup([
            [InlineKeyboardButton('⚙️ Уведомления', callback_data='settings')],
            [InlineKeyboardButton('🌐 Открыть сайт', url=APP_OPEN_URL)],
        ])

    if _is_student(role):
        rows = [
            [
                InlineKeyboardButton('🏠 Мой кабинет', callback_data='student_home'),
                InlineKeyboardButton('📅 Расписание', callback_data='schedule'),
            ],
            [
                InlineKeyboardButton('📋 Мои долги', callback_data='my_debts'),
                InlineKeyboardButton('🎲 Случайная задача', callback_data='random_task'),
            ],
            [
                InlineKeyboardButton('📊 Статистика', callback_data='stats'),
                InlineKeyboardButton('💳 Мой тариф', callback_data='subscription'),
            ],
            [
                InlineKeyboardButton('📱 Mini App', web_app=WebAppInfo(url=_mini_app_url())) if _mini_app_url() else InlineKeyboardButton('🌐 Открыть сайт', url=APP_OPEN_URL),
                InlineKeyboardButton('⚙️ Уведомления', callback_data='settings'),
            ],
            [InlineKeyboardButton('🐛 Баг-репорт', callback_data='bug_report_start')],
            [InlineKeyboardButton('🌐 Открыть сайт', url=APP_OPEN_URL)],
        ]
    elif _is_parent(role):
        rows = [
            [
                InlineKeyboardButton('👤 Мой ребенок', callback_data='parent_children'),
                InlineKeyboardButton('📅 Расписание', callback_data='parent_schedule'),
            ],
            [
                InlineKeyboardButton('📝 Домашки', callback_data='parent_debts'),
                InlineKeyboardButton('💳 Тарифы детей', callback_data='parent_subscription'),
            ],
            [
                InlineKeyboardButton('⚙️ Уведомления', callback_data='settings'),
                InlineKeyboardButton('🌐 Открыть сайт', url=APP_OPEN_URL),
            ],
        ]
    elif _is_creator(role):
        rows = [
            [
                InlineKeyboardButton('📊 Статистика', callback_data='admin_stats'),
                InlineKeyboardButton('🧩 Роли и связи', callback_data='roles_panel'),
            ],
            [
                InlineKeyboardButton('👥 Пользователи', callback_data='admin_users'),
                InlineKeyboardButton('🎓 Ученики', callback_data='admin_students'),
            ],
            [
                InlineKeyboardButton('👪 Родители', callback_data='admin_parents'),
                InlineKeyboardButton('👨‍🏫 Преподаватели', callback_data='admin_tutors'),
            ],
            [
                InlineKeyboardButton('🆕 Неавторизованные', callback_data='unauth_users'),
                InlineKeyboardButton('🔗 Инвайт', callback_data='gen_invite'),
            ],
            [
                InlineKeyboardButton('📝 Непроверенные', callback_data='ungraded'),
                InlineKeyboardButton('🐛 Баг-репорты', callback_data='view_bug_reports'),
            ],
            [
                InlineKeyboardButton('📢 Рассылка', callback_data='broadcast_prompt'),
                InlineKeyboardButton('📨 Тест-рассылка', callback_data='test_broadcast_send'),
            ],
            [
                InlineKeyboardButton('⚙️ Уведомления', callback_data='settings'),
                InlineKeyboardButton('🌐 Панель управления', url=f'{APP_URL}/admin' if APP_URL else APP_OPEN_URL),
            ],
        ]
    elif _is_senior_admin(role):
        rows = [
            [
                InlineKeyboardButton('📊 Сводка', callback_data='admin_stats'),
                InlineKeyboardButton('🧩 Роли и связи', callback_data='roles_panel'),
            ],
            [
                InlineKeyboardButton('👥 Пользователи', callback_data='admin_users'),
                InlineKeyboardButton('🆕 Неавторизованные', callback_data='unauth_users'),
            ],
            [
                InlineKeyboardButton('🎓 Ученики', callback_data='admin_students'),
                InlineKeyboardButton('👪 Родители', callback_data='admin_parents'),
            ],
            [
                InlineKeyboardButton('👨‍🏫 Преподаватели', callback_data='admin_tutors'),
                InlineKeyboardButton('📝 Непроверенные', callback_data='ungraded'),
            ],
            [
                InlineKeyboardButton('📢 Рассылка', callback_data='broadcast_prompt'),
                InlineKeyboardButton('📨 Тест-рассылка', callback_data='test_broadcast_send'),
            ],
            [
                InlineKeyboardButton('🐛 Баг-репорты', callback_data='view_bug_reports'),
                InlineKeyboardButton('⚙️ Уведомления', callback_data='settings'),
            ],
            [InlineKeyboardButton('🌐 Панель управления', url=f'{APP_URL}/admin/users' if APP_URL else APP_OPEN_URL)],
        ]
    elif role == 'admin':
        rows = [
            [
                InlineKeyboardButton('📊 Сводка', callback_data='admin_stats'),
                InlineKeyboardButton('👥 Пользователи', callback_data='admin_users'),
            ],
            [
                InlineKeyboardButton('🧩 Роли без админов', callback_data='roles_panel'),
                InlineKeyboardButton('🆕 Неавторизованные', callback_data='unauth_users'),
            ],
            [
                InlineKeyboardButton('🎓 Ученики', callback_data='admin_students'),
                InlineKeyboardButton('👪 Родители', callback_data='admin_parents'),
            ],
            [
                InlineKeyboardButton('👨‍🏫 Преподаватели', callback_data='admin_tutors'),
                InlineKeyboardButton('🐛 Баг-репорты', callback_data='view_bug_reports'),
            ],
            [
                InlineKeyboardButton('📝 Непроверенные', callback_data='ungraded'),
                InlineKeyboardButton('⚙️ Уведомления', callback_data='settings'),
            ],
            [InlineKeyboardButton('🌐 Панель управления', url=f'{APP_URL}/admin/users' if APP_URL else APP_OPEN_URL)],
        ]
    elif role == 'designer':
        rows = [
            [InlineKeyboardButton('✨ Мой статус', callback_data='designer_status')],
            [
                InlineKeyboardButton('⚙️ Уведомления', callback_data='settings'),
                InlineKeyboardButton('🌐 Открыть сайт', url=APP_OPEN_URL),
            ],
        ]
    else:
        rows = [
            [
                InlineKeyboardButton('📝 Непроверенные', callback_data='ungraded'),
                InlineKeyboardButton('📊 Статистика', callback_data='teacher_stats'),
            ],
            [
                InlineKeyboardButton('🎓 Мои ученики', callback_data='teacher_students'),
                InlineKeyboardButton('📅 Расписание', callback_data='teacher_schedule'),
            ],
            [
                InlineKeyboardButton('⚙️ Уведомления', callback_data='settings'),
                InlineKeyboardButton('🌐 Открыть сайт', url=APP_OPEN_URL),
            ],
        ]
    return InlineKeyboardMarkup(rows)


def _back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([_BACK_ROW])


def _student_dashboard_keyboard() -> InlineKeyboardMarkup:
    mini_app_url = _mini_app_url()
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton('📅 Расписание', callback_data='schedule'),
            InlineKeyboardButton('📋 Долги', callback_data='my_debts'),
        ],
        [
            InlineKeyboardButton('🎲 Задача', callback_data='random_task'),
            InlineKeyboardButton('📊 Статистика', callback_data='stats'),
        ],
        [
            InlineKeyboardButton('💳 Тариф', callback_data='subscription'),
            InlineKeyboardButton('⚙️ Уведомления', callback_data='settings'),
        ],
        [
            InlineKeyboardButton('📱 Mini App', web_app=WebAppInfo(url=mini_app_url)) if mini_app_url else InlineKeyboardButton('🌐 Открыть сайт', url=APP_OPEN_URL),
        ],
        _BACK_ROW,
    ])


def _student_admin_summary(session, student_user_id: int, student_id: int | None, name: str | None = None) -> str:
    student_label = name or f'ID {student_user_id}'
    next_lesson = None
    if student_id:
        next_lesson = session.execute(text("""
            SELECT lesson_date, topic
            FROM "Lessons"
            WHERE student_id = :sid AND status = 'planned' AND lesson_date >= NOW()
            ORDER BY lesson_date ASC
            LIMIT 1
        """), {'sid': student_id}).fetchone()

    active_debts = 0
    if student_id:
        active_debts = session.execute(text("""
            SELECT COUNT(*)
            FROM "Submissions" s
            WHERE s.student_id = :sid
              AND s.status IN ('ASSIGNED', 'IN_PROGRESS', 'RETURNED')
        """), {'sid': student_id}).scalar() or 0

    summary = subscription_summary_for_user(int(student_user_id))
    tg_row = session.execute(text("""
        SELECT telegram_chat_id, telegram_id
        FROM "UserProfiles"
        WHERE user_id = :uid
        LIMIT 1
    """), {'uid': int(student_user_id)}).fetchone()
    tg_chat_id = tg_row[0] if tg_row else None
    tg_id = tg_row[1] if tg_row else None
    if tg_chat_id:
        tg_status = f'✅ бот привязан{f" · {tg_id}" if tg_id else ""}'
    elif tg_id:
        tg_status = f'⚠️ указан {tg_id}, бот не подтвержден'
    else:
        tg_status = '❌ не привязан'
    parts = [
        '🎓 <b>Карточка ученика</b>',
        '',
        f'Имя: <b>{esc(student_label)}</b>',
        f'ID пользователя: <code>{student_user_id}</code>',
    ]
    if student_id:
        parts.append(f'ID ученика: <code>{student_id}</code>')
    parts.append(f'Telegram: <b>{esc(tg_status)}</b>')
    parts.append(f'Тариф: <b>{esc(summary.plan_title)}</b>')
    parts.append(f'Осталось уроков: <b>{esc(summary.lessons_remaining)}</b>')
    parts.append(f'Активных работ: <b>{active_debts}</b>')
    if next_lesson:
        lesson_date, topic = next_lesson
        when = lesson_date.strftime('%d.%m в %H:%M') if lesson_date else '—'
        parts.append(f'Ближайший урок: <b>{when}</b> — {esc((topic or "Урок")[:60])}')
    else:
        parts.append('Ближайших уроков пока нет')
    parts.append('')
    parts.append('Здесь можно быстро проверить профиль и связи.')
    return '\n'.join(parts)


def _student_dashboard_text(session, user: dict) -> str:
    student = get_student_by_email(session, user.get('email'), user.get('id'))
    if not student:
        return (
            '🏠 <b>Мой кабинет</b>\n\n'
            'Профиль ученика пока не найден. Обратись к преподавателю.'
        )

    sid = student['student_id']
    next_lesson = session.execute(text("""
        SELECT lesson_date, topic
        FROM "Lessons"
        WHERE student_id = :sid AND status = 'planned' AND lesson_date >= NOW()
        ORDER BY lesson_date ASC
        LIMIT 1
    """), {'sid': sid}).fetchone()

    debts = session.execute(text("""
        SELECT COUNT(*)
        FROM "Submissions" s
        JOIN "Assignments" a ON a.assignment_id = s.assignment_id
        WHERE s.student_id = :sid
          AND s.status IN ('ASSIGNED', 'IN_PROGRESS', 'RETURNED')
    """), {'sid': sid}).scalar() or 0

    plan_summary = subscription_summary_for_user(int(user['id']))
    parts = ['🏠 <b>Мой кабинет</b>', '']
    parts.append(f'👤 <b>{esc(user.get("first_name") or user.get("username") or "Ученик")}</b>')
    parts.append(f'📋 Долгов: <b>{debts}</b>')
    parts.append(f'💳 Тариф: <b>{esc(plan_summary.plan_title)}</b>')

    if next_lesson:
        lesson_date, topic = next_lesson
        when = lesson_date.strftime('%d.%m в %H:%M') if lesson_date else '—'
        parts.append(f'📅 Ближайший урок: <b>{when}</b> — {esc((topic or "Урок")[:60])}')
    else:
        parts.append('📅 Ближайших уроков пока нет')

    parts.append('')
    parts.append('Выбери, что сделать дальше:')
    return '\n'.join(parts)


def _admin_dashboard_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton('📊 Сводка', callback_data='admin_home'),
            InlineKeyboardButton('👥 Пользователи', callback_data='admin_users'),
        ],
        [
            InlineKeyboardButton('🎓 Ученики', callback_data='admin_students'),
            InlineKeyboardButton('🔎 Поиск ученика', callback_data='admin_student_search_help'),
            InlineKeyboardButton('👪 Родители', callback_data='admin_parents'),
        ],
        [
            InlineKeyboardButton('👨‍🏫 Преподаватели', callback_data='admin_tutors'),
            InlineKeyboardButton('🧩 Роли и связи', callback_data='roles_panel'),
        ],
        [
            InlineKeyboardButton('🆕 Неавторизованные', callback_data='unauth_users'),
            InlineKeyboardButton('🐛 Баг-репорты', callback_data='view_bug_reports'),
        ],
        [
            InlineKeyboardButton('📢 Рассылка', callback_data='broadcast_prompt'),
            InlineKeyboardButton('📨 Тест-рассылка', callback_data='test_broadcast_send'),
        ],
        _BACK_ROW,
    ])


def _admin_dashboard_text(session) -> str:
    active_users = session.execute(text("""
        SELECT COUNT(*) FROM "Users" WHERE is_active = TRUE
    """)).scalar() or 0
    students = session.execute(text("""
        SELECT COUNT(*) FROM "Users"
        WHERE is_active = TRUE AND role = 'student' AND COALESCE(is_demo_user, FALSE) = FALSE
    """)).scalar() or 0
    parents = session.execute(text("""
        SELECT COUNT(*) FROM "Users"
        WHERE is_active = TRUE AND role = 'parent' AND COALESCE(is_demo_user, FALSE) = FALSE
    """)).scalar() or 0
    tutors = session.execute(text("""
        SELECT COUNT(*) FROM "Users"
        WHERE is_active = TRUE AND role = 'tutor' AND COALESCE(is_demo_user, FALSE) = FALSE
    """)).scalar() or 0
    demo_students = session.execute(text("""
        SELECT COUNT(*) FROM "Users"
        WHERE is_active = TRUE AND role = 'student' AND COALESCE(is_demo_user, FALSE) = TRUE
    """)).scalar() or 0
    test_accounts = session.execute(text("""
        SELECT COUNT(*) FROM "Users"
        WHERE is_active = TRUE AND role IN ('tester', 'chief_tester')
    """)).scalar() or 0
    pending_leads = session.execute(text("""
        SELECT COUNT(*) FROM "TelegramStartLeads"
        WHERE COALESCE(is_authorized, FALSE) = FALSE
    """)).scalar() or 0
    bug_reports = session.execute(text("""
        SELECT COUNT(*) FROM "BotErrorReports"
        WHERE COALESCE(status, 'new') IN ('new', 'open')
    """)).scalar() or 0
    return (
        '📊 <b>Админ-сводка</b>\n\n'
        f'👥 Активных пользователей: <b>{active_users}</b>\n'
        f'🎓 Ученики: <b>{students}</b>\n'
        f'👪 Родители: <b>{parents}</b>\n'
        f'👨‍🏫 Преподаватели: <b>{tutors}</b>\n'
        f'🧪 Демо-ученики: <b>{demo_students}</b>\n'
        f'🧫 Тестовые аккаунты: <b>{test_accounts}</b>\n'
        f'🆕 Неавторизованные лиды: <b>{pending_leads}</b>\n'
        f'🐛 Открытые баг-репорты: <b>{bug_reports}</b>\n\n'
        'Выбери раздел для управления.'
    )


def _admin_student_search_help_text() -> str:
    return (
        '🔎 <b>Поиск ученика</b>\n\n'
        'Используй команду:\n'
        '<code>/findstudent часть_имени</code>\n\n'
        'Или ищи по username, Telegram-id и ID пользователя.'
    )


def _settings_keyboard(profile) -> InlineKeyboardMarkup:
    """Inline toggles for notification settings."""
    def _btn(label: str, attr: str, cb_prefix: str) -> InlineKeyboardButton:
        enabled = getattr(profile, attr, True)
        icon = '✅' if enabled else '❌'
        return InlineKeyboardButton(f'{icon} {label}', callback_data=f'toggle_{cb_prefix}')

    rows = [
        [_btn('Проверка ДЗ', 'tg_notify_homework_checked', 'homework_checked')],
        [_btn('ДЗ на доработку', 'tg_notify_homework_returned', 'homework_returned')],
        [_btn('Расписание уроков', 'tg_notify_lesson_scheduled', 'lesson_scheduled')],
        [_btn('Напоминания о дедлайнах', 'tg_notify_lesson_reminder', 'lesson_reminder')],
        [_btn('Мало уроков', 'tg_notify_low_lessons', 'low_lessons')],
        [_btn('Новости и рассылки', 'tg_notify_news', 'news')],
        [_btn('Проверка ДЗ от ученика', 'tg_notify_homework_submitted', 'homework_submitted')],
        [_btn('Новый реферал', 'tg_notify_referral_used', 'referral_used')],
        [_btn('Системные ошибки', 'tg_notify_system_errors', 'system_errors')],
        [_btn('Подписка заканчивается', 'tg_notify_subscription_expiring', 'subscription_expiring')],
        [_btn('Утренний дайджест (8:00)', 'tg_notify_daily_digest', 'daily_digest')],
        [_btn('Ответы на баг-репорты', 'tg_notify_bug_report_reply', 'bug_report_reply')],
        [
            InlineKeyboardButton('🔕 Выключить всё', callback_data='toggle_all_off'),
            InlineKeyboardButton('🔔 Включить всё', callback_data='toggle_all_on'),
        ],
        _BACK_ROW,
    ]
    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------------------
# Link result helper
# ---------------------------------------------------------------------------

async def _apply_link_result(update: Update, *, chat_id: int, result: dict | None) -> bool:
    if not result:
        await update.message.reply_text(
            '❌ Не удалось связаться с сервером BooStudy. Попробуй позже.',
            parse_mode='HTML',
        )
        return False
    data = result.get('data') or {}
    err = data.get('error')
    if result.get('status') == 200 and data.get('success'):
        user = _get_linked_user(chat_id)
        if user:
            _track_start_lead(chat_id, assigned_user_id=int(user['id']), is_authorized=True)
        name = (user or {}).get('first_name') or (user or {}).get('username') or 'пользователь'
        mini_kb = _reply_keyboard_with_mini_app(user)
        await update.message.reply_text(
            f'✅ <b>Аккаунт привязан!</b>\n\nПривет, {esc(name)}!\n'
            'Открой Mini App кнопкой ниже или /menu.',
            parse_mode='HTML',
            reply_markup=mini_kb,
        )
        await update.message.reply_text(
            '📋 <b>Меню BooStudy</b>',
            parse_mode='HTML',
            reply_markup=_menu_keyboard(user),
        )
        return True
    if err == 'already_linked':
        await update.message.reply_text(
            'ℹ️ Этот Telegram уже привязан. Используй /unlink в профиле или напиши администратору.',
        )
    elif err == 'expired_code':
        await update.message.reply_text('⌛ Код или ссылка устарели. Сгенерируй новые в профиле на сайте.')
    elif err == 'invalid_code':
        await update.message.reply_text('❌ Неверный код. Проверь данные в профиле BooStudy.')
    else:
        await update.message.reply_text(f'❌ Не удалось привязать: {esc(str(err or "ошибка"))}')
    return False


# ===========================================================================
# Command handlers
# ===========================================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Приветствие; /start TOKEN — привязывает аккаунт по deep link."""
    chat_id = update.effective_chat.id
    touch_telegram_activity(chat_id)
    _track_start_lead(
        chat_id,
        tg_username=update.effective_user.username,
        first_name=update.effective_user.first_name,
        last_name=update.effective_user.last_name,
    )

    if update.message and context.args:
        token = (context.args[0] or '').strip()
        if token and len(token) >= 16:
            uname = (update.effective_user.username or '').strip()
            result = call_link_bot_api(
                chat_id=chat_id,
                telegram_id=f'@{uname}' if uname else None,
                link_token=token,
                app_url=APP_URL,
            )
            await _apply_link_result(update, chat_id=chat_id, result=result)
            return

    user = _get_linked_user(
        chat_id,
        tg_username=update.effective_user.username,
        first_name=update.effective_user.first_name,
        last_name=update.effective_user.last_name,
    )
    mini_kb = _reply_keyboard_with_mini_app(user)

    if user:
        _track_start_lead(chat_id, assigned_user_id=int(user['id']), is_authorized=True)
        name = user.get('first_name') or user.get('username') or 'пользователь'
        if _is_student(user.get('role', '')):
            session = get_session()
            try:
                await update.message.reply_text(
                    _student_dashboard_text(session, user),
                    parse_mode='HTML',
                    reply_markup=_student_dashboard_keyboard(),
                )
            finally:
                close_session(session)
        elif _is_admin(user.get('role', '')):
            session = get_session()
            try:
                await update.message.reply_text(
                    _admin_dashboard_text(session),
                    parse_mode='HTML',
                    reply_markup=_admin_dashboard_keyboard(),
                )
            finally:
                close_session(session)
        else:
            await update.message.reply_text(
                f'👋 <b>Привет, {esc(name)}!</b>\n\n'
                f'Ты привязан к BooStudy как <b>{esc(user.get("username", ""))}</b>.\n'
                'Нажми /menu для навигации или открой Mini App кнопкой ниже.',
                parse_mode='HTML',
                reply_markup=mini_kb,
            )
            await update.message.reply_text(
                '📋 <b>Меню BooStudy</b>',
                parse_mode='HTML',
                reply_markup=_menu_keyboard(user),
            )
    else:
        await update.message.reply_text(
            WELCOME_MESSAGE + f'\n\n🔢 <b>Твой chat_id:</b> <code>{chat_id}</code>',
            parse_mode='HTML',
        )


async def cmd_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/link КОД — привязка аккаунта вручную."""
    chat_id = update.effective_chat.id
    touch_telegram_activity(chat_id)
    if not context.args:
        await update.message.reply_text(
            'ℹ️ Укажи код: <code>/link ABCDEF</code>\nКод — в профиле на сайте BooStudy.',
            parse_mode='HTML',
        )
        return
    code = context.args[0].strip().upper()
    uname = (update.effective_user.username or '').strip()
    result = call_link_bot_api(
        chat_id=chat_id,
        telegram_id=f'@{uname}' if uname else None,
        code=code,
        app_url=APP_URL,
    )
    await _apply_link_result(update, chat_id=chat_id, result=result)


async def cmd_linkforce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/linkforce КОД — принудительная привязка аккаунта."""
    chat_id = update.effective_chat.id
    touch_telegram_activity(chat_id)
    if not context.args:
        await update.message.reply_text(
            'ℹ️ Укажи код: <code>/linkforce ABCDEF</code>\n'
            'Команда принудительно отвяжет старый аккаунт Telegram и привяжет новый.',
            parse_mode='HTML',
        )
        return
    code = context.args[0].strip().upper()
    uname = (update.effective_user.username or '').strip()
    result = call_link_bot_api(
        chat_id=chat_id,
        telegram_id=f'@{uname}' if uname else None,
        code=code,
        force=True,
        app_url=APP_URL,
    )
    await _apply_link_result(update, chat_id=chat_id, result=result)


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/menu — ролевое меню."""
    chat_id = update.effective_chat.id
    touch_telegram_activity(chat_id)
    user = _get_linked_user(
        chat_id,
        tg_username=update.effective_user.username,
        first_name=update.effective_user.first_name,
        last_name=update.effective_user.last_name,
    )

    if not user:
        await update.message.reply_text(
            '🔗 Сначала привяжи аккаунт командой /start или /link КОД',
        )
        return

    _track_start_lead(chat_id, assigned_user_id=int(user['id']), is_authorized=True)

    mini_kb = _reply_keyboard_with_mini_app(user)
    if mini_kb:
        await update.message.reply_text('👇 Mini App', reply_markup=mini_kb)
    if _is_student(user.get('role', '')):
        session = get_session()
        try:
            await update.message.reply_text(
                _student_dashboard_text(session, user),
                parse_mode='HTML',
                reply_markup=_student_dashboard_keyboard(),
            )
        finally:
            close_session(session)
        return
    if _is_admin(user.get('role', '')):
        session = get_session()
        try:
            await update.message.reply_text(
                _admin_dashboard_text(session),
                parse_mode='HTML',
                reply_markup=_admin_dashboard_keyboard(),
            )
        finally:
            close_session(session)
        return
    await update.message.reply_text(
        '📋 <b>Меню BooStudy</b>',
        parse_mode='HTML',
        reply_markup=_menu_keyboard(user),
    )


async def cmd_findstudent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    touch_telegram_activity(chat_id)
    user = _get_linked_user(
        chat_id,
        tg_username=update.effective_user.username,
        first_name=update.effective_user.first_name,
        last_name=update.effective_user.last_name,
    )
    if not user or not _is_admin(user.get('role', '')):
        await update.message.reply_text('⛔ Команда доступна только админам и создателю.')
        return
    query_text = ' '.join(context.args).strip() if context.args else ''
    if not query_text:
        await update.message.reply_text(_admin_student_search_help_text(), parse_mode='HTML')
        return

    pattern = f'%{query_text.lower()}%'
    session = get_session()
    try:
        rows = session.execute(text("""
            SELECT u.id AS student_user_id,
                   st.student_id,
                   COALESCE(NULLIF(st.name, ''), up.first_name, u.username) AS display_name,
                   u.username,
                   up.telegram_id,
                   up.telegram_chat_id IS NOT NULL AS has_tg
            FROM "Users" u
            LEFT JOIN "Students" st ON st.user_id = u.id
            LEFT JOIN "UserProfiles" up ON up.user_id = u.id
            WHERE u.is_active = TRUE
              AND u.role = 'student'
              AND COALESCE(u.is_demo_user, FALSE) = FALSE
              AND (
                    LOWER(COALESCE(st.name, '')) LIKE :pattern
                 OR LOWER(COALESCE(up.first_name, '')) LIKE :pattern
                 OR LOWER(COALESCE(up.last_name, '')) LIKE :pattern
                 OR LOWER(COALESCE(u.username, '')) LIKE :pattern
                 OR LOWER(COALESCE(up.telegram_id, '')) LIKE :pattern
                 OR CAST(u.id AS TEXT) LIKE :plain_pattern
                 OR CAST(COALESCE(st.student_id, 0) AS TEXT) LIKE :plain_pattern
                 OR CAST(COALESCE(up.telegram_chat_id, 0) AS TEXT) LIKE :plain_pattern
              )
            ORDER BY up.telegram_last_interaction_at DESC NULLS LAST, u.created_at DESC
            LIMIT 12
        """), {'pattern': pattern, 'plain_pattern': f'%{query_text}%'}).fetchall()
    finally:
        close_session(session)

    if not rows:
        await update.message.reply_text(
            f'🔎 По запросу <b>{esc(query_text)}</b> ничего не найдено.',
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('↩️ К сводке', callback_data='admin_home')]]),
        )
        return

    lines = [f'🔎 <b>Результаты поиска: {esc(query_text)}</b>', '']
    buttons = []
    for student_user_id, student_id, display_name, username, telegram_id, has_tg in rows:
        tg_badge = ' 📱' if has_tg else ''
        lines.append(f'• <b>{esc(display_name or username or "Ученик")}</b>{tg_badge} · user_id: <code>{student_user_id}</code>')
        row_buttons = [InlineKeyboardButton((display_name or username or 'Ученик')[:24], callback_data=f'student_manage_{student_user_id}_{student_id}') if student_id else InlineKeyboardButton((display_name or username or 'Ученик')[:24], callback_data=f'role_user_{student_user_id}')]
        if telegram_id:
            row_buttons.append(InlineKeyboardButton('Telegram', url=_telegram_public_link(telegram_id)))
        buttons.append(row_buttons)
    buttons.append([InlineKeyboardButton('↩️ К сводке', callback_data='admin_home')])
    await update.message.reply_text('\n'.join(lines), parse_mode='HTML', reply_markup=InlineKeyboardMarkup(buttons))


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    touch_telegram_activity(update.effective_chat.id)
    user = _get_linked_user(
        update.effective_chat.id,
        tg_username=update.effective_user.username,
        first_name=update.effective_user.first_name,
        last_name=update.effective_user.last_name,
    )
    role = (user or {}).get('role')
    await update.message.reply_text(
        build_help_message(role),
        parse_mode='HTML',
        reply_markup=_menu_keyboard(user) if user else None,
    )


async def cmd_whatsnew(update: Update, context: ContextTypes.DEFAULT_TYPE):
    touch_telegram_activity(update.effective_chat.id)
    user = _get_linked_user(
        update.effective_chat.id,
        tg_username=update.effective_user.username,
        first_name=update.effective_user.first_name,
        last_name=update.effective_user.last_name,
    )
    buttons = [[InlineKeyboardButton('🌐 Открыть платформу', url=APP_URL or APP_OPEN_URL)]]
    if user:
        buttons.insert(0, [InlineKeyboardButton('📋 Открыть меню', callback_data='back_menu')])
    await update.message.reply_text(
        build_release_notes_text(),
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/status — краткая сводка одной строкой."""
    chat_id = update.effective_chat.id
    touch_telegram_activity(chat_id)
    user = _get_linked_user(chat_id)
    if not user:
        await update.message.reply_text('🔗 Привяжи аккаунт командой /start')
        return

    session = get_session()
    try:
        student = get_student_by_email(session, user.get('email'), user.get('id'))
        if not student:
            await update.message.reply_text(
                'ℹ️ Нет связанного профиля ученика.',
                reply_markup=_menu_keyboard(user),
            )
            return
        sid = student['student_id']

        # Ближайший урок
        next_lesson = session.execute(text("""
            SELECT lesson_date, topic FROM "Lessons"
            WHERE student_id = :sid AND status = 'planned'
              AND lesson_date >= NOW()
            ORDER BY lesson_date ASC LIMIT 1
        """), {'sid': sid}).fetchone()

        # Кол-во долгов
        debts = session.execute(text("""
            SELECT COUNT(*) FROM "Submissions" s
            JOIN "Assignments" a ON a.assignment_id = s.assignment_id
            WHERE s.student_id = :sid
              AND s.status IN ('ASSIGNED','IN_PROGRESS','RETURNED')
        """), {'sid': sid}).scalar() or 0

        parts = ['📌 <b>Коротко по делу</b>', '']
        if next_lesson:
            d = next_lesson[0].strftime('%d.%m в %H:%M') if next_lesson[0] else '—'
            t = esc((next_lesson[1] or 'Урок')[:40])
            parts.append(f'📅 Ближайший урок: <b>{d}</b> — {t}')
        else:
            parts.append('📅 Ближайших уроков нет')

        parts.append(f'📋 Долгов: <b>{debts}</b>')

        summary_buttons = [
            [
                InlineKeyboardButton('📅 Расписание', callback_data='schedule'),
                InlineKeyboardButton('📋 Долги', callback_data='my_debts'),
            ],
            [
                InlineKeyboardButton('⚙️ Уведомления', callback_data='settings'),
                InlineKeyboardButton('📋 Меню', callback_data='back_menu'),
            ],
        ]
        if _is_student(user.get('role', '')):
            summary_buttons.insert(1, [
                InlineKeyboardButton('🎲 Задача', callback_data='random_task'),
                InlineKeyboardButton('💳 Тариф', callback_data='subscription'),
            ])
        await update.message.reply_text('\n'.join(parts), parse_mode='HTML', reply_markup=InlineKeyboardMarkup(summary_buttons))
    except Exception as e:
        logger.error('cmd_status error: %s', e)
        await update.message.reply_text('⚠️ Не удалось получить статус.')
    finally:
        close_session(session)


async def cmd_random(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/random — случайная задача в тренажёре."""
    chat_id = update.effective_chat.id
    touch_telegram_activity(chat_id)
    user = _get_linked_user(chat_id)
    if not user:
        await update.message.reply_text('🔗 Привяжи аккаунт командой /start')
        return
    task_number = random.randint(1, 27)
    trainer_url = f'{APP_URL}/trainer?task_number={task_number}' if APP_URL else '#'
    await update.message.reply_text(
        f'🎲 <b>Случайная задача №{task_number}</b>\n\nНажми кнопку, чтобы открыть тренажёр.',
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(f'🎯 Задание №{task_number}', url=trainer_url),
        ]]),
    )


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/settings — настройки уведомлений."""
    chat_id = update.effective_chat.id
    touch_telegram_activity(chat_id)
    user = _get_linked_user(
        chat_id,
        tg_username=update.effective_user.username,
        first_name=update.effective_user.first_name,
        last_name=update.effective_user.last_name,
    )
    if not user:
        await update.message.reply_text('🔗 Привяжи аккаунт командой /start')
        return
    await _send_settings(update.message.reply_text, chat_id)


async def cmd_claim_creator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принудительно активировать автономную creator-привязку."""
    chat_id = update.effective_chat.id
    touch_telegram_activity(chat_id)
    user = _ensure_bootstrap_creator_link(
        chat_id,
        tg_username=update.effective_user.username,
        first_name=update.effective_user.first_name,
        last_name=update.effective_user.last_name,
    )
    if not user:
        await update.message.reply_text(
            '⛔ Эта команда доступна только для резервного аккаунта создателя.',
        )
        return
    await update.message.reply_text(
        '✅ Creator-доступ активирован для этого Telegram.\n\nИспользуй /menu для панели управления.',
    )
    await update.message.reply_text(
        '📋 <b>Меню BooStudy</b>',
        parse_mode='HTML',
        reply_markup=_menu_keyboard(user),
    )


async def cmd_testnotify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/testnotify — отправить себе тестовое уведомление."""
    chat_id = update.effective_chat.id
    touch_telegram_activity(chat_id)
    user = _get_linked_user(
        chat_id,
        tg_username=update.effective_user.username,
        first_name=update.effective_user.first_name,
        last_name=update.effective_user.last_name,
    )
    if not user or not _is_admin(user.get('role', '')):
        await update.message.reply_text('⛔ Эта команда доступна только создателю или администратору.')
        return

    from app.telegram.notifications import send_telegram_message

    result = send_telegram_message(
        chat_id,
        'Тестовое уведомление BooStudy.\n\nЭто автономная проверка Telegram-контура без платформы.',
        parse_mode=None,
    )
    if result and result.get('ok'):
        await update.message.reply_text('✅ Тестовое уведомление отправлено в этот чат.')
    else:
        await update.message.reply_text('⚠️ Не удалось отправить тестовое уведомление.')


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/broadcast текст — быстрая Telegram-рассылка по привязанным пользователям."""
    chat_id = update.effective_chat.id
    touch_telegram_activity(chat_id)
    user = _get_linked_user(
        chat_id,
        tg_username=update.effective_user.username,
        first_name=update.effective_user.first_name,
        last_name=update.effective_user.last_name,
    )
    if not user or not _is_admin(user.get('role', '')):
        await update.message.reply_text('⛔ Эта команда доступна только создателю или администратору.')
        return
    if not context.args:
        await update.message.reply_text('ℹ️ Используй: <code>/broadcast Текст рассылки</code>', parse_mode='HTML')
        return

    from app.telegram.notifications import send_telegram_message

    text_body = '📢 BooStudy\n\n' + ' '.join(context.args).strip()
    session = get_session()
    sent = 0
    failed = 0
    try:
        rows = session.execute(text("""
            SELECT up.telegram_chat_id
            FROM "UserProfiles" up
            JOIN "Users" u ON u.id = up.user_id
            WHERE up.telegram_chat_id IS NOT NULL
              AND u.is_active = TRUE
            ORDER BY u.id ASC
        """)).fetchall()
        for (recipient_chat_id,) in rows:
            try:
                result = send_telegram_message(int(recipient_chat_id), text_body, parse_mode=None)
                if result and result.get('ok'):
                    sent += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
    finally:
        close_session(session)

    await update.message.reply_text(
        f'✅ Рассылка завершена.\n\nУспешно: {sent}\nС ошибкой: {failed}',
        parse_mode=None,
    )


async def _send_settings(send_fn, chat_id: int) -> None:
    """Отправить/обновить сообщение с настройками."""
    from app.models import UserProfile
    try:
        profile = UserProfile.query.filter_by(telegram_chat_id=chat_id).first()
    except Exception:
        profile = None

    if not profile:
        await send_fn('⚠️ Профиль не найден. Привяжи аккаунт: /start')
        return

    global_on = bool(profile.telegram_notifications_enabled)
    status_line = '🔔 Уведомления <b>включены</b>' if global_on else '🔕 Уведомления <b>выключены</b>'
    await send_fn(
        f'⚙️ <b>Настройки уведомлений</b>\n\n{status_line}\n\nНажми на пункт чтобы переключить:',
        parse_mode='HTML',
        reply_markup=_settings_keyboard(profile),
    )


# ===========================================================================
# Bug report FSM (ConversationHandler)
# ===========================================================================

async def bug_report_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало: отправляем приглашение описать проблему."""
    if update.callback_query:
        await _answer_callback_query(update.callback_query)

    touch_telegram_activity(update.effective_chat.id)
    user = _get_linked_user(update.effective_chat.id)
    if not user:
        if update.message:
            await update.message.reply_text('🔗 Сначала привяжи аккаунт: /start')
        else:
            await update.callback_query.edit_message_text('🔗 Сначала привяжи аккаунт: /start')
        return ConversationHandler.END

    if update.callback_query:
        await update.callback_query.message.reply_text(
            '🐛 <b>Баг-репорт</b>\n\n'
            'Опиши проблему подробно. Можно приложить скриншот.\n\n'
            '❌ Для отмены напиши /cancel',
            parse_mode='HTML',
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        await update.message.reply_text(
            '🐛 <b>Баг-репорт</b>\n\n'
            'Опиши проблему подробно. Можно приложить скриншот.\n\n'
            '❌ Для отмены напиши /cancel',
            parse_mode='HTML',
            reply_markup=ReplyKeyboardRemove(),
        )
    return BUG_REPORT_TEXT


async def bug_report_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получить текст + опц. фото, сохранить в БД, отправить создателям."""
    chat_id = update.effective_chat.id
    msg = update.message

    text_content = msg.text or msg.caption or ''
    photo_file_id = None

    if msg.photo:
        photo_file_id = msg.photo[-1].file_id
    elif msg.document and msg.document.mime_type and msg.document.mime_type.startswith('image/'):
        photo_file_id = msg.document.file_id

    if not text_content and not photo_file_id:
        await msg.reply_text('⚠️ Пожалуйста, напиши описание проблемы (или прикрепи скриншот с описанием).')
        return BUG_REPORT_TEXT

    user = _get_linked_user(chat_id)
    user_id = (user or {}).get('id')
    user_name = (user or {}).get('first_name') or (user or {}).get('username') or 'Аноним'
    tg_username = update.effective_user.username or ''
    user_display = f'{esc(user_name)} (@{esc(tg_username)})' if tg_username else esc(user_name)

    # Сохранить в БД
    report_id = None
    try:
        from app.models import db
        from core.db_models import BotErrorReport, moscow_now
        report = BotErrorReport(
            user_id=user_id,
            telegram_chat_id=chat_id,
            message=text_content or '[только скриншот]',
            screenshot_file_id=photo_file_id,
            status='new',
        )
        db.session.add(report)
        db.session.commit()
        report_id = report.report_id
    except Exception as e:
        logger.error('bug_report_receive: DB error: %s', e, exc_info=True)
        await msg.reply_text('⚠️ Ошибка при сохранении репорта. Попробуй позже.')
        return ConversationHandler.END

    # Форвардим создателям
    now_str = datetime.now().strftime('%H:%M %d.%m.%Y')
    forward_text = (
        f'🐛 <b>Баг-репорт #{report_id}</b>\n\n'
        f'👤 {user_display}\n'
        f'🕐 {now_str}\n\n'
        f'{esc(text_content) if text_content else "<i>[без текста]</i>"}'
    )
    forward_markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton('💬 Ответить', callback_data=f'bug_reply_{report_id}_{chat_id}'),
            InlineKeyboardButton('✅ Закрыть', callback_data=f'bug_close_{report_id}'),
        ],
    ])

    await _notify_creators_bug_report(report_id, forward_text, forward_markup, photo_file_id)

    await msg.reply_text(
        f'✅ <b>Репорт #{report_id} принят!</b>\n\n'
        'Мы разберёмся и ответим в этом чате. Спасибо!',
        parse_mode='HTML',
        reply_markup=_reply_keyboard_with_mini_app(user),
    )
    return ConversationHandler.END


async def _notify_creators_bug_report(
    report_id: int,
    text_body: str,
    markup: InlineKeyboardMarkup,
    photo_file_id: Optional[str],
) -> None:
    """Разослать баг-репорт всем создателям с привязанным TG."""
    from app.telegram.notifications import send_telegram_message, send_telegram_photo
    session = get_session()
    try:
        rows = session.execute(text("""
            SELECT up.telegram_chat_id
            FROM "Users" u
            JOIN "UserProfiles" up ON up.user_id = u.id
            WHERE u.role IN ('creator','chief_admin')
              AND up.telegram_chat_id IS NOT NULL
              AND u.is_active = TRUE
        """)).fetchall()

        markup_dict = markup.to_dict()

        for (creator_chat_id,) in rows:
            try:
                if photo_file_id:
                    send_telegram_photo(
                        int(creator_chat_id),
                        photo_url=None,
                        file_id=photo_file_id,
                        caption=text_body,
                        reply_markup=markup_dict,
                    )
                else:
                    send_telegram_message(int(creator_chat_id), text_body, reply_markup=markup_dict)
            except Exception as e:
                logger.warning('bug report forward to creator %s failed: %s', creator_chat_id, e)
    except Exception as e:
        logger.error('_notify_creators_bug_report: %s', e, exc_info=True)
    finally:
        close_session(session)


async def bug_report_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text('❌ Баг-репорт отменён.', reply_markup=ReplyKeyboardRemove())
    user = _get_linked_user(update.effective_chat.id)
    if user:
        await update.message.reply_text(
            '📋 <b>Меню</b>', parse_mode='HTML', reply_markup=_menu_keyboard(user),
        )
    return ConversationHandler.END


# ===========================================================================
# Creator reply FSM
# ===========================================================================

async def creator_reply_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Создатель нажал «Ответить» на баг-репорте."""
    query = update.callback_query
    await _answer_callback_query(query)

    _, _, report_id_str, student_chat_str = query.data.split('_', 3)
    context.user_data[_CTX_REPLY_REPORT_ID] = int(report_id_str)
    context.user_data[_CTX_REPLY_STUDENT_CHAT_ID] = int(student_chat_str)

    await query.message.reply_text(
        f'💬 Введи ответ на баг-репорт <b>#{report_id_str}</b>:\n\n'
        '❌ /cancel — отмена',
        parse_mode='HTML',
    )
    return CREATOR_REPLY_TEXT


async def creator_reply_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получить текст ответа, отправить ученику, обновить БД."""
    reply_text = (update.message.text or '').strip()
    if not reply_text:
        await update.message.reply_text('⚠️ Ответ не может быть пустым. Введи текст или /cancel')
        return CREATOR_REPLY_TEXT

    report_id = context.user_data.get(_CTX_REPLY_REPORT_ID)
    student_chat_id = context.user_data.get(_CTX_REPLY_STUDENT_CHAT_ID)
    creator_name = (
        (update.effective_user.first_name or '') + ' ' +
        (update.effective_user.last_name or '')
    ).strip() or 'Команда BooStudy'

    # Обновить в БД
    try:
        from app.models import db
        from core.db_models import BotErrorReport, moscow_now
        report = BotErrorReport.query.get(report_id)
        if report:
            from app.models import User
            creator_user = User.query.filter_by(
                telegram_chat_id=update.effective_chat.id
            ).first() if hasattr(User, 'telegram_chat_id') else None
            report.admin_reply = reply_text
            report.status = 'answered'
            report.replied_at = moscow_now()
            report.reply_sent_at = moscow_now()
            db.session.commit()
    except Exception as e:
        logger.error('creator_reply_receive: DB error: %s', e, exc_info=True)

    # Отправить ученику
    from app.telegram.notifications import send_telegram_message
    student_msg = (
        f'💬 <b>Ответ от команды BooStudy</b>\n\n'
        f'📌 По репорту <b>#{report_id}</b>:\n\n'
        f'{esc(reply_text)}'
    )
    try:
        send_telegram_message(student_chat_id, student_msg)
    except Exception as e:
        logger.error('creator_reply: send to student %s failed: %s', student_chat_id, e)
        await update.message.reply_text('⚠️ Не удалось доставить ответ ученику.')
        return ConversationHandler.END

    await update.message.reply_text(
        f'✅ Ответ отправлен ученику (репорт #{report_id} закрыт).',
    )
    return ConversationHandler.END


async def creator_reply_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text('❌ Ответ отменён.')
    return ConversationHandler.END


# ===========================================================================
# Callback query dispatcher
# ===========================================================================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await _answer_callback_query(query)

    data = query.data or ''
    chat_id = update.effective_chat.id
    touch_telegram_activity(chat_id)

    # Student confirms that a test notification arrived
    if data.startswith('notif_ack:'):
        await _cb_notification_ack(query, data)
        return

    if data.startswith('lesson_rsvp:'):
        await _cb_lesson_rsvp(query, data)
        return

    if data.startswith('admin_link_confirm:'):
        await _cb_admin_link_confirm(query, data)
        return

    if data == 'noop':
        return

    # Creator closes a bug report
    if data.startswith('bug_close_'):
        await _cb_bug_close(query, data)
        return

    # Creator reply — handled by ConversationHandler, but extra safeguard
    if data.startswith('bug_reply_'):
        await query.message.reply_text(
            '💬 Нажми кнопку «Ответить» — в контексте разговора. Или используй /cancel и нажми снова.',
        )
        return

    session = get_session()
    try:
        user = get_user_by_chat_id(session, chat_id)

        dispatch = {
            'admin_home':        _cb_admin_home,
            'admin_student_search_help': _cb_admin_student_search_help,
            'student_home':      _cb_student_home,
            'my_debts':           _cb_my_debts,
            'random_task':        _cb_random_task,
            'schedule':           _cb_schedule,
            'stats':              _cb_student_stats,
            'subscription':        _cb_subscription,
            'parent_children':     _cb_parent_children,
            'parent_child':        _cb_parent_child_detail,
            'parent_schedule':     _cb_parent_schedule,
            'parent_debts':        _cb_parent_debts,
            'parent_subscription': _cb_parent_subscription,
            'ungraded':           _cb_ungraded,
            'admin_stats':        _cb_admin_stats,
            'gen_invite':         _cb_gen_invite,
            'admin_users':        _cb_admin_users,
            'admin_students':      _cb_admin_students,
            'admin_parents':      _cb_admin_parents,
            'admin_tutors':       _cb_admin_tutors,
            'unauth_users':       _cb_unauth_users,
            'roles_panel':        _cb_roles_panel,
            'teacher_stats':      _cb_teacher_stats,
            'teacher_students':    _cb_teacher_students,
            'teacher_schedule':    _cb_teacher_schedule,
            'designer_status':    _cb_designer_status,
            'back_menu':          _cb_back_menu,
            'settings':           _cb_settings,
            'view_bug_reports':   _cb_view_bug_reports,
            'broadcast_prompt':   _cb_broadcast_prompt,
            'test_broadcast_send': _cb_test_broadcast_send,
            'bug_report_start':   _cb_bug_report_start_inline,
        }

        if data.startswith('toggle_'):
            await _cb_toggle_notification(query, data, chat_id)
            return

        if data.startswith('role_user_'):
            await _cb_role_user(query, session, user, data)
            return

        if data.startswith('parent_child_'):
            await _cb_parent_child_detail(query, session, user, data)
            return

        if data.startswith('role_set_'):
            await _cb_role_set(query, session, user, data)
            return

        if data.startswith('role_clear_'):
            await _cb_role_clear(query, session, user, data)
            return

        if data.startswith('lead_user_'):
            await _cb_lead_user(query, session, user, data)
            return

        if data.startswith('lead_set_'):
            await _cb_lead_set(query, session, user, data)
            return

        if data.startswith('student_manage_'):
            await _cb_student_manage(query, session, user, data)
            return

        if data.startswith('student_tg_link_'):
            await _cb_student_tg_link(query, session, user, data, context)
            return

        if data.startswith('student_tg_unlink_'):
            await _cb_student_tg_unlink(query, session, user, data)
            return

        if data.startswith('student_stub_parent_'):
            await _cb_student_stub_parent(query, session, user, data)
            return

        if data.startswith('student_parents_'):
            await _cb_student_parents(query, session, user, data)
            return

        if data.startswith('student_tutors_'):
            await _cb_student_tutors(query, session, user, data)
            return

        if data.startswith('student_remove_parent_'):
            await _cb_student_remove_parent(query, session, user, data)
            return

        if data.startswith('student_remove_tutor_'):
            await _cb_student_remove_tutor(query, session, user, data)
            return

        if data.startswith('test_feedback_'):
            await _cb_test_feedback(query, session, user, data)
            return

        handler_fn = dispatch.get(data)
        if handler_fn:
            await handler_fn(query, session, user)
        else:
            await query.edit_message_text('⚠️ Неизвестная команда.', reply_markup=_back_keyboard())
    except Exception as e:
        logger.error('Callback %s error: %s', data, e, exc_info=True)
        try:
            await query.edit_message_text(ERROR_MESSAGE, parse_mode='HTML', reply_markup=_back_keyboard())
        except Exception:
            pass
    finally:
        close_session(session)


# ---------------------------------------------------------------------------
# Back to menu
# ---------------------------------------------------------------------------

async def _cb_back_menu(query, session, user):
    if not user:
        await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode='HTML')
        return
    if _is_student(user.get('role', '')):
        await _cb_student_home(query, session, user)
        return
    if _is_admin(user.get('role', '')):
        await _cb_admin_home(query, session, user)
        return
    await query.edit_message_text(
        '📋 <b>Меню BooStudy</b>', parse_mode='HTML', reply_markup=_menu_keyboard(user),
    )


async def _cb_admin_home(query, session, user):
    if not user or not _is_admin(user.get('role', '')):
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return
    await query.edit_message_text(
        _admin_dashboard_text(session),
        parse_mode='HTML',
        reply_markup=_admin_dashboard_keyboard(),
    )


async def _cb_admin_student_search_help(query, session, user):
    if not user or not _is_admin(user.get('role', '')):
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return
    await query.edit_message_text(
        _admin_student_search_help_text(),
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('🔎 К поиску', callback_data='admin_home')],
            _BACK_ROW,
        ]),
    )


async def _cb_student_home(query, session, user):
    if not user:
        await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode='HTML', reply_markup=_back_keyboard())
        return
    await query.edit_message_text(
        _student_dashboard_text(session, user),
        parse_mode='HTML',
        reply_markup=_student_dashboard_keyboard(),
    )


# ---------------------------------------------------------------------------
# Settings from inline button
# ---------------------------------------------------------------------------

async def _cb_settings(query, session, user):
    if not user:
        await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode='HTML')
        return
    chat_id = query.from_user.id
    from app.models import UserProfile
    try:
        profile = UserProfile.query.filter_by(telegram_chat_id=chat_id).first()
    except Exception:
        profile = None
    if not profile:
        await query.edit_message_text('⚠️ Профиль не найден.')
        return
    global_on = bool(profile.telegram_notifications_enabled)
    status_line = '🔔 Уведомления <b>включены</b>' if global_on else '🔕 Уведомления <b>выключены</b>'
    await query.edit_message_text(
        f'⚙️ <b>Настройки уведомлений</b>\n\n{status_line}\n\nНажми на пункт чтобы переключить:',
        parse_mode='HTML',
        reply_markup=_settings_keyboard(profile),
    )


async def _cb_toggle_notification(query, data: str, chat_id: int) -> None:
    """Переключить флаг уведомления в профиле и обновить клавиатуру."""
    kind = data[len('toggle_'):]  # e.g. 'homework_checked' or 'all_off'

    from app.models import UserProfile, db

    try:
        profile = UserProfile.query.filter_by(telegram_chat_id=chat_id).first()
        if not profile:
            await query.answer('Профиль не найден', show_alert=True)
            return

        _MAP = {
            'homework_checked':  'tg_notify_homework_checked',
            'homework_returned': 'tg_notify_homework_returned',
            'lesson_scheduled':  'tg_notify_lesson_scheduled',
            'lesson_reminder':   'tg_notify_lesson_reminder',
            'low_lessons':       'tg_notify_low_lessons',
            'news':              'tg_notify_news',
            'homework_submitted':'tg_notify_homework_submitted',
            'referral_used':     'tg_notify_referral_used',
            'system_errors':     'tg_notify_system_errors',
            'subscription_expiring': 'tg_notify_subscription_expiring',
            'daily_digest':      'tg_notify_daily_digest',
            'bug_report_reply':  'tg_notify_bug_report_reply',
        }

        if kind == 'all_off':
            profile.telegram_notifications_enabled = False
        elif kind == 'all_on':
            profile.telegram_notifications_enabled = True
            for attr in _MAP.values():
                setattr(profile, attr, True)
        elif kind in _MAP:
            attr = _MAP[kind]
            setattr(profile, attr, not getattr(profile, attr, True))
        else:
            await query.answer('Неизвестная настройка', show_alert=True)
            return

        db.session.commit()

        global_on = bool(profile.telegram_notifications_enabled)
        status_line = '🔔 Уведомления <b>включены</b>' if global_on else '🔕 Уведомления <b>выключены</b>'
        await query.edit_message_text(
            f'⚙️ <b>Настройки уведомлений</b>\n\n{status_line}\n\nНажми на пункт чтобы переключить:',
            parse_mode='HTML',
            reply_markup=_settings_keyboard(profile),
        )
    except Exception as e:
        logger.error('_cb_toggle_notification error: %s', e, exc_info=True)
        await query.answer('Ошибка при сохранении', show_alert=True)


# ---------------------------------------------------------------------------
# Bug report — close button (creator)
# ---------------------------------------------------------------------------

async def _cb_bug_close(query, data: str) -> None:
    report_id_str = data[len('bug_close_'):]
    try:
        from app.models import db
        from core.db_models import BotErrorReport, moscow_now
        report = BotErrorReport.query.get(int(report_id_str))
        if report and report.status not in ('answered', 'closed'):
            report.status = 'closed'
            db.session.commit()
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(f'✅ Закрыт #{report_id_str}', callback_data='noop'),
            ]])
        )
    except Exception as e:
        logger.error('_cb_bug_close: %s', e)
        await query.answer('Ошибка', show_alert=True)


async def _cb_notification_ack(query, data: str) -> None:
    parts = data.split(':', 2)
    kind = parts[2] if len(parts) >= 3 else 'generic'
    from_user = query.from_user
    message = query.message
    notification_text = ''
    if message:
        notification_text = getattr(message, 'text', None) or getattr(message, 'caption', None) or ''

    try:
        from app.telegram.user_notify import send_student_notification_ack_report

        sent = send_student_notification_ack_report(
            student_chat_id=int(from_user.id),
            student_username=getattr(from_user, 'username', None),
            student_first_name=getattr(from_user, 'first_name', None),
            student_last_name=getattr(from_user, 'last_name', None),
            notification_text=notification_text,
            kind=kind,
        )
        if not sent:
            logger.warning('notification ack report had no creator recipients chat_id=%s kind=%s', from_user.id, kind)
    except Exception as e:
        logger.error('_cb_notification_ack error: %s', e, exc_info=True)
        return

    try:
        markup = getattr(message, 'reply_markup', None) if message else None
        rows = getattr(markup, 'inline_keyboard', None) or []
        new_rows = []
        for row in rows:
            new_row = []
            for button in row:
                callback_data = getattr(button, 'callback_data', None) or ''
                if callback_data.startswith('notif_ack:'):
                    new_row.append(InlineKeyboardButton('✅ Подтверждено', callback_data='noop'))
                else:
                    new_row.append(button)
            if new_row:
                new_rows.append(new_row)
        if message and new_rows:
            await message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(new_rows))
    except Exception:
        logger.debug('notification ack markup update skipped', exc_info=True)


async def _cb_lesson_rsvp(query, data: str) -> None:
    parts = data.split(':', 2)
    response_kind = parts[1] if len(parts) >= 2 else 'ontime'
    lesson_id = None
    try:
        lesson_id = int(parts[2]) if len(parts) >= 3 else None
    except Exception:
        lesson_id = None

    response_map = {
        'ontime': 'Приду вовремя',
        'late': 'Опаздываю',
        'skip': 'Не приду',
    }
    response_label = response_map.get(response_kind, 'Ответ получен')
    from_user = query.from_user
    message = query.message
    original_text = ''
    if message:
        original_text = getattr(message, 'text', None) or getattr(message, 'caption', None) or ''

    try:
        from app.models import Lesson, Student
        from app.telegram.notifications import notify_lesson_reminder_response_to_creators

        lesson = Lesson.query.get(lesson_id) if lesson_id else None
        student = None
        if lesson and lesson.student:
            student = lesson.student
        elif lesson and lesson.student_id:
            student = Student.query.get(lesson.student_id)

        if not student or not student.user_id:
            await query.answer('Не удалось найти ученика', show_alert=True)
            return

        sent = notify_lesson_reminder_response_to_creators(
            student_user_id=int(student.user_id),
            student_chat_id=int(from_user.id),
            student_username=getattr(from_user, 'username', None),
            student_first_name=getattr(from_user, 'first_name', None),
            student_last_name=getattr(from_user, 'last_name', None),
            lesson_id=lesson_id,
            lesson_topic=getattr(lesson, 'topic', None),
            lesson_time=(lesson.lesson_date.strftime('%d.%m.%Y %H:%M') if lesson and getattr(lesson, 'lesson_date', None) else None),
            response_kind=response_kind,
            response_label=response_label,
            original_text=original_text,
        )
        if not sent:
            logger.warning('lesson reminder response report had no recipients lesson_id=%s kind=%s', lesson_id, response_kind)
    except Exception as e:
        logger.error('_cb_lesson_rsvp error: %s', e, exc_info=True)
        return

    try:
        if message:
            base_rows = getattr(getattr(message, 'reply_markup', None), 'inline_keyboard', None) or []
            new_rows = []
            for row in base_rows:
                new_row = []
                for button in row:
                    callback_data = getattr(button, 'callback_data', None) or ''
                    if callback_data.startswith('lesson_rsvp:'):
                        new_row.append(InlineKeyboardButton('✅ Ответ отправлен', callback_data='noop'))
                    else:
                        new_row.append(button)
                if new_row:
                    new_rows.append(new_row)
            if new_rows:
                await message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(new_rows))
    except Exception:
        logger.debug('lesson rsvp markup update skipped', exc_info=True)


async def _cb_admin_link_confirm(query, data: str) -> None:
    try:
        _, profile_id_str, admin_id_str = data.split(':', 2)
        profile_id = int(profile_id_str)
        admin_id = int(admin_id_str)
    except Exception:
        logger.warning('bad admin link callback data=%s', data)
        return

    from_user = query.from_user
    try:
        from app.models import db, Student, User, UserProfile
        from app.telegram.notifications import send_telegram_message

        profile = UserProfile.query.get(profile_id)
        if not profile:
            await query.message.reply_text('⚠️ Профиль для привязки не найден.')
            return

        existing = UserProfile.query.filter(
            UserProfile.telegram_chat_id == int(from_user.id),
            UserProfile.profile_id != profile.profile_id,
        ).first()
        if existing:
            if _clear_stale_tg_link(existing):
                db.session.flush()
            else:
                await query.message.reply_text('⚠️ Этот Telegram уже привязан к другому активному аккаунту BooStudy.')
                return

        username = (getattr(from_user, 'username', None) or '').strip()
        profile.telegram_chat_id = int(from_user.id)
        if username:
            profile.telegram_id = f'@{username}'
        profile.telegram_notifications_enabled = True
        profile.telegram_link_code = None
        profile.telegram_link_code_expires = None
        profile.telegram_link_token = None
        profile.telegram_link_token_expires = None
        db.session.commit()

        student = Student.query.filter_by(user_id=profile.user_id).first()
        if student and username:
            student.telegram = f'@{username}'
            student.telegram_username = username
        student_user = User.query.get(profile.user_id)
        student_name = getattr(student, 'name', None) or getattr(student_user, 'username', None) or f'user_id {profile.user_id}'
        student_tg = f'@{username}' if username else f'chat_id {from_user.id}'

        await query.message.edit_text(
            '✅ Telegram привязан к аккаунту BooStudy.\n\n'
            f'Профиль: {student_name}',
        )

        admin_profile = UserProfile.query.filter_by(user_id=admin_id).first()
        admin_chat_id = getattr(admin_profile, 'telegram_chat_id', None)
        if admin_chat_id:
            send_telegram_message(
                int(admin_chat_id),
                '✅ <b>Ученик подтвердил ручную привязку Telegram</b>\n\n'
                f'👤 Ученик: <b>{esc(student_name)}</b>\n'
                f'💬 Telegram: <b>{esc(student_tg)}</b>\n'
                f'🆔 Профиль платформы: <code>{profile.user_id}</code>',
            )
    except Exception as e:
        try:
            from app.models import db
            db.session.rollback()
        except Exception:
            pass
        logger.error('_cb_admin_link_confirm error: %s', e, exc_info=True)
        try:
            await query.message.reply_text('⚠️ Не удалось привязать Telegram. Попробуй позже.')
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Bug report from inline button (starts FSM — only via reply)
# ---------------------------------------------------------------------------

async def _cb_bug_report_start_inline(query, session, user):
    if not user:
        await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode='HTML')
        return
    await query.edit_message_text(
        '🐛 <b>Баг-репорт</b>\n\nОтправь описание проблемы следующим сообщением. '
        'Можно приложить скриншот.\n\n❌ /cancel — отмена',
        parse_mode='HTML',
    )


# ---------------------------------------------------------------------------
# View bug reports (creator)
# ---------------------------------------------------------------------------

async def _cb_view_bug_reports(query, session, user):
    if not user or not _is_admin(user.get('role', '')):
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return

    rows = session.execute(text("""
        SELECT ber.report_id, ber.message, ber.status, ber.created_at,
               u.username, up.first_name
        FROM "BotErrorReports" ber
        LEFT JOIN "Users" u ON u.id = ber.user_id
        LEFT JOIN "UserProfiles" up ON up.user_id = ber.user_id
        WHERE ber.status IN ('new', 'in_progress')
        ORDER BY ber.created_at DESC
        LIMIT 10
    """)).fetchall()

    lines = ['🐛 <b>Новые баг-репорты</b>', '']
    if not rows:
        lines.append('✅ Новых репортов нет!')
    else:
        for rid, msg, status, created_at, username, first_name in rows:
            name = esc((first_name or username or 'Аноним')[:20])
            preview = esc((msg or '')[:80])
            d = created_at.strftime('%d.%m %H:%M') if created_at else '—'
            s_icon = '🆕' if status == 'new' else '🔄'
            lines.append(f'{s_icon} <b>#{rid}</b> {name} — {d}')
            lines.append(f'   {preview}')
            lines.append('')

    lines.append('📱 Полный список — в Mini App')
    await query.edit_message_text('\n'.join(lines), parse_mode='HTML', reply_markup=_back_keyboard())


# ---------------------------------------------------------------------------
# Broadcast prompt (creator)
# ---------------------------------------------------------------------------

async def _cb_broadcast_prompt(query, session, user):
    if not user or not _is_admin(user.get('role', '')):
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return

    mini_url = _mini_app_url()
    rows = []
    if mini_url:
        rows.append([InlineKeyboardButton('📱 Открыть рассылку в Mini App', web_app=WebAppInfo(url=mini_url))])
    rows.append(_BACK_ROW)
    await query.edit_message_text(
        '📢 <b>Рассылка</b>\n\n'
        'Автономный режим уже доступен прямо в боте.\n'
        'Используй команду:\n'
        '<code>/broadcast Текст рассылки</code>\n\n'
        'Для проверки доставки есть отдельная кнопка тестовой рассылки в меню.\n\n'
        'Mini App можно использовать позже, когда платформа вернется.',
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def _cb_test_broadcast_send(query, session, user):
    if not user or not _is_admin(user.get('role', '')):
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return

    from app.telegram.notifications import send_telegram_message

    rows = session.execute(text("""
        SELECT u.id, COALESCE(NULLIF(st.name, ''), up.first_name, u.username) AS display_name, up.telegram_chat_id
        FROM "Users" u
        LEFT JOIN "Students" st ON st.user_id = u.id
        LEFT JOIN "UserProfiles" up ON up.user_id = u.id
        WHERE u.role = 'student'
          AND u.is_active = TRUE
          AND COALESCE(u.is_demo_user, FALSE) = FALSE
          AND up.telegram_chat_id IS NOT NULL
        ORDER BY up.telegram_last_interaction_at DESC NULLS LAST, u.created_at DESC
    """)).fetchall()

    sent = 0
    failed = 0
    for student_user_id, display_name, chat_id in rows:
        markup = {
            'inline_keyboard': [[
                {'text': '✅ Пришло корректно', 'callback_data': f'test_feedback_ok_{student_user_id}'},
                {'text': '❌ Есть проблема', 'callback_data': f'test_feedback_fail_{student_user_id}'},
            ]]
        }
        result = send_telegram_message(
            int(chat_id),
            'Тестовое уведомление.\n\nНажмите галочку, если оно пришло корректно, или крестик, если есть проблема.',
            parse_mode=None,
            reply_markup=markup,
        )
        if result and result.get('ok'):
            sent += 1
        else:
            failed += 1

    await query.edit_message_text(
        '📨 <b>Тестовая рассылка отправлена</b>\n\n'
        f'Успешно: <b>{sent}</b>\n'
        f'С ошибкой: <b>{failed}</b>\n\n'
        'Ответы учеников будут прилетать создателю отдельными сообщениями.',
        parse_mode='HTML',
        reply_markup=_back_keyboard(),
    )


async def _cb_test_feedback(query, session, user, data: str):
    raw = data[len('test_feedback_'):]
    try:
        answer, student_user_id_str = raw.split('_', 1)
        student_user_id = int(student_user_id_str)
    except ValueError:
        await query.answer('Не удалось обработать ответ', show_alert=True)
        return

    from app.telegram.notifications import send_telegram_message

    student_name = None
    if user:
        student_name = user.get('first_name') or user.get('username')
    if not student_name:
        row = session.execute(text("""
            SELECT COALESCE(NULLIF(st.name, ''), up.first_name, u.username)
            FROM "Users" u
            LEFT JOIN "Students" st ON st.user_id = u.id
            LEFT JOIN "UserProfiles" up ON up.user_id = u.id
            WHERE u.id = :uid
            LIMIT 1
        """), {'uid': student_user_id}).fetchone()
        student_name = row[0] if row else f'ID {student_user_id}'

    answer_label = '✅ пришло корректно' if answer == 'ok' else '❌ есть проблема'
    creator_chat_id = _creator_feedback_chat_id()
    send_telegram_message(
        creator_chat_id,
        f'{student_name} — {answer_label}',
        parse_mode=None,
    )
    await query.edit_message_text(
        f'Спасибо! Ответ записан: {answer_label}',
        reply_markup=None,
    )


# ---------------------------------------------------------------------------
# Role management
# ---------------------------------------------------------------------------

async def _cb_roles_panel(query, session, user):
    if not user or not _can_manage_roles(user.get('role', '')):
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return

    rows = session.execute(text("""
        SELECT u.id, u.username, u.role, up.first_name, up.last_name, up.telegram_chat_id, up.telegram_id
        FROM "Users" u
        LEFT JOIN "UserProfiles" up ON up.user_id = u.id
        WHERE u.is_active = TRUE
          AND up.telegram_chat_id IS NOT NULL
          AND COALESCE(u.is_demo_user, FALSE) = FALSE
        ORDER BY up.telegram_last_interaction_at DESC NULLS LAST, u.created_at DESC
        LIMIT 12
    """)).fetchall()

    lines = ['🧩 <b>Роли и связи</b>', '']
    lines.append('Выбери подключенного Telegram-пользователя:')
    buttons = []
    for uid, username, role, first_name, last_name, chat_id, telegram_id in rows:
        name = (f'{first_name or ""} {last_name or ""}'.strip() or username or f'ID {uid}')[:32]
        tg_line = telegram_id or f'chat {chat_id}'
        lines.append(f'• {esc(name)} — {esc(role_label(role))} · {esc(tg_line)}')
        buttons.append([InlineKeyboardButton(f'{name} · {role_label(role)}', callback_data=f'role_user_{uid}')])
    if not rows:
        lines.append('Пока нет подключенных Telegram-пользователей.')
    buttons.append(_BACK_ROW)
    await query.edit_message_text('\n'.join(lines), parse_mode='HTML', reply_markup=InlineKeyboardMarkup(buttons))


async def _cb_role_user(query, session, user, data: str):
    if not user or not _can_manage_roles(user.get('role', '')):
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return
    try:
        target_id = int(data[len('role_user_'):])
    except ValueError:
        await query.edit_message_text('⚠️ Пользователь не найден.', reply_markup=_back_keyboard())
        return

    from app.models import User
    actor = User.query.get(int(user['id']))
    target = User.query.get(target_id)
    if not actor or not target:
        await query.edit_message_text('⚠️ Пользователь не найден.', reply_markup=_back_keyboard())
        return

    profile = getattr(target, 'profile', None)
    telegram_id = getattr(profile, 'telegram_id', None)
    telegram_chat_id = getattr(profile, 'telegram_chat_id', None)
    telegram_line = telegram_id or (f'chat_id {telegram_chat_id}' if telegram_chat_id else 'не привязан')

    lines = [
        '👤 <b>Пользователь</b>',
        '',
        f'Имя: <b>{esc(user_display_name(target))}</b>',
        f'Текущая роль: <b>{esc(role_label(target.role))}</b>',
        f'Telegram: {esc(telegram_line)}',
        esc(relation_summary(target)),
        '',
        'Выбери новую роль:',
    ]

    buttons = []
    for role in MAIN_BOT_ROLES:
        ok, _ = actor_can_assign_role(actor, target, role)
        if ok and role != target.role:
            buttons.append([InlineKeyboardButton(role_label(role), callback_data=f'role_set_{target.id}_{role}')])
    clear_ok, _ = actor_can_clear_role(actor, target)
    if clear_ok and target.role and target.role != 'tester':
        buttons.append([InlineKeyboardButton('Снять роль', callback_data=f'role_clear_{target.id}')])
    tg_link = _telegram_public_link(telegram_id)
    if tg_link:
        buttons.append([InlineKeyboardButton('Открыть Telegram', url=tg_link)])
    if target.role == 'student':
        from app.models import Student
        student_profile = Student.query.filter_by(user_id=target.id).first()
        if student_profile:
            buttons.append([
                InlineKeyboardButton('👪 Родители', callback_data=f'student_parents_{target.id}_{student_profile.student_id}'),
                InlineKeyboardButton('👨‍🏫 Преподаватели', callback_data=f'student_tutors_{target.id}_{student_profile.student_id}'),
            ])
    if not buttons:
        lines.append('Нет доступных изменений для твоей роли.')
    buttons.append([InlineKeyboardButton('↩️ К списку', callback_data='roles_panel')])
    buttons.append(_BACK_ROW)
    await query.edit_message_text('\n'.join(lines), parse_mode='HTML', reply_markup=InlineKeyboardMarkup(buttons))


async def _cb_role_set(query, session, user, data: str):
    if not user or not _can_manage_roles(user.get('role', '')):
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return

    raw = data[len('role_set_'):]
    try:
        target_id_str, new_role = raw.split('_', 1)
        target_id = int(target_id_str)
    except ValueError:
        await query.edit_message_text('⚠️ Не удалось понять роль.', reply_markup=_back_keyboard())
        return

    from app.models import User, db
    actor = User.query.get(int(user['id']))
    target = User.query.get(target_id)
    if not actor or not target:
        await query.edit_message_text('⚠️ Пользователь не найден.', reply_markup=_back_keyboard())
        return

    ok, reason = actor_can_assign_role(actor, target, new_role)
    if not ok:
        await query.edit_message_text(f'⛔ {esc(reason)}', parse_mode='HTML', reply_markup=_back_keyboard())
        return

    old_role = set_single_role(target, new_role)
    db.session.commit()
    notified = notify_role_changed(target, old_role, new_role, actor=actor)

    msg = (
        '✅ <b>Роль изменена</b>\n\n'
        f'Пользователь: <b>{esc(user_display_name(target))}</b>\n'
        f'Старая роль: {esc(role_label(old_role))}\n'
        f'Новая роль: {esc(role_label(new_role))}\n'
        f'{esc(relation_summary(target))}\n\n'
        f'Уведомление пользователю: {"отправлено" if notified else "не отправлено, Telegram не привязан"}'
    )
    await query.edit_message_text(
        msg,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('↩️ К пользователю', callback_data=f'role_user_{target.id}')],
            [InlineKeyboardButton('👥 К списку', callback_data='roles_panel')],
        ]),
    )


async def _cb_role_clear(query, session, user, data: str):
    if not user or not _can_manage_roles(user.get('role', '')):
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return
    try:
        target_id = int(data[len('role_clear_'):])
    except ValueError:
        await query.edit_message_text('⚠️ Пользователь не найден.', reply_markup=_back_keyboard())
        return

    from app.models import User, db

    actor = User.query.get(int(user['id']))
    target = User.query.get(target_id)
    if not actor or not target:
        await query.edit_message_text('⚠️ Пользователь не найден.', reply_markup=_back_keyboard())
        return

    ok, reason = actor_can_clear_role(actor, target)
    if not ok:
        await query.edit_message_text(f'⛔ {esc(reason)}', parse_mode='HTML', reply_markup=_back_keyboard())
        return

    old_role = clear_all_roles(target)
    db.session.commit()
    notified = notify_role_changed(target, old_role, None, actor=actor)

    msg = (
        '✅ <b>Роль снята</b>\n\n'
        f'Пользователь: <b>{esc(user_display_name(target))}</b>\n'
        f'Старая роль: {esc(role_label(old_role))}\n'
        'Новая роль: <b>Без роли</b>\n\n'
        f'Уведомление пользователю: {"отправлено" if notified else "не отправлено, Telegram не привязан"}'
    )
    await query.edit_message_text(
        msg,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('↩️ К пользователю', callback_data=f'role_user_{target.id}')],
            [InlineKeyboardButton('👥 К списку', callback_data='roles_panel')],
        ]),
    )


async def _cb_unauth_users(query, session, user):
    if not user or not _can_manage_roles(user.get('role', '')):
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return

    from app.models import db
    db.create_all()

    rows = session.execute(text("""
        SELECT lead_id, telegram_chat_id, telegram_username, first_name, last_name, last_seen_at
        FROM "TelegramStartLeads"
        WHERE COALESCE(is_authorized, FALSE) = FALSE
        ORDER BY last_seen_at DESC NULLS LAST, lead_id DESC
        LIMIT 20
    """)).fetchall()

    lines = ['🆕 <b>Неавторизованные пользователи</b>', '']
    buttons = []
    if not rows:
        lines.append('Пока пусто. Здесь появятся люди, которые нажали /start, но еще не получили роль.')
    else:
        lines.append('Выбери человека и сразу выдай ему роль:')
        for lead_id, chat_id, username, first_name, last_name, last_seen_at in rows:
            name = (f'{first_name or ""} {last_name or ""}'.strip() or (f'@{username}' if username else f'chat {chat_id}'))[:32]
            last_seen = f' · {last_seen_at.strftime("%d.%m %H:%M")}' if last_seen_at else ''
            lines.append(f'• <b>{esc(name)}</b>{esc(last_seen)}')
            buttons.append([InlineKeyboardButton(name, callback_data=f'lead_user_{lead_id}')])
    buttons.append(_BACK_ROW)
    await query.edit_message_text('\n'.join(lines), parse_mode='HTML', reply_markup=InlineKeyboardMarkup(buttons))


async def _cb_lead_user(query, session, user, data: str):
    if not user or not _can_manage_roles(user.get('role', '')):
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return

    try:
        lead_id = int(data[len('lead_user_'):])
    except ValueError:
        await query.edit_message_text('⚠️ Пользователь не найден.', reply_markup=_back_keyboard())
        return

    from app.models import db, TelegramStartLead, User

    db.create_all()

    lead = TelegramStartLead.query.get(lead_id)
    actor = User.query.get(int(user['id']))
    if not lead or not actor:
        await query.edit_message_text('⚠️ Пользователь не найден.', reply_markup=_back_keyboard())
        return

    lines = [
        '🆕 <b>Пользователь из Telegram</b>',
        '',
        f'Имя: <b>{esc(_pick_lead_display_name(lead))}</b>',
        f'chat_id: <code>{lead.telegram_chat_id}</code>',
        f'username: {esc("@" + lead.telegram_username if lead.telegram_username else "не указан")}',
        '',
        'Выбери роль, которую нужно выдать:',
    ]

    buttons = []
    for role in UNAUTHORIZED_ROLE_OPTIONS:
        shadow_target = User(username='shadow', password_hash='shadow', role='student', is_active=True)
        ok, _ = actor_can_assign_role(actor, shadow_target, role)
        if ok:
            buttons.append([InlineKeyboardButton(role_label(role), callback_data=f'lead_set_{lead.lead_id}_{role}')])

    buttons.append([InlineKeyboardButton('↩️ К списку', callback_data='unauth_users')])
    buttons.append(_BACK_ROW)
    await query.edit_message_text('\n'.join(lines), parse_mode='HTML', reply_markup=InlineKeyboardMarkup(buttons))


def _make_safe_username(base: str) -> str:
    cleaned = ''.join(ch for ch in (base or '').lower() if ch.isalnum() or ch == '_').strip('_')
    return cleaned or 'user'


def _ensure_unique_username(base: str) -> str:
    from app.models import User

    candidate = _make_safe_username(base)
    if not User.query.filter_by(username=candidate).first():
        return candidate

    for _ in range(50):
        alt = f'{candidate}_{secrets.token_hex(2)}'
        if not User.query.filter_by(username=alt).first():
            return alt
    return f'{candidate}_{int(datetime.now(timezone.utc).timestamp())}'


def _ensure_user_student_record(user_obj, display_name: str, tg_username: str | None = None):
    from app.models import db, Student

    student = Student.query.filter_by(user_id=user_obj.id).first()
    if student:
        return student

    student = Student(
        user_id=user_obj.id,
        name=display_name or user_obj.username or f'Ученик {user_obj.id}',
        telegram=f'@{tg_username}' if tg_username else None,
        telegram_username=tg_username,
        is_active=True,
    )
    db.session.add(student)
    db.session.flush()
    return student


def _creator_feedback_chat_id() -> int:
    return int(BOOTSTRAP_CREATOR_CHAT_ID)


async def _cb_lead_set(query, session, user, data: str):
    if not user or not _can_manage_roles(user.get('role', '')):
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return

    raw = data[len('lead_set_'):]
    try:
        lead_id_str, new_role = raw.split('_', 1)
        lead_id = int(lead_id_str)
    except ValueError:
        await query.edit_message_text('⚠️ Не удалось понять роль.', reply_markup=_back_keyboard())
        return

    from app.models import db, TelegramStartLead, User, UserProfile

    db.create_all()

    lead = TelegramStartLead.query.get(lead_id)
    actor = User.query.get(int(user['id']))
    if not lead or not actor:
        await query.edit_message_text('⚠️ Пользователь не найден.', reply_markup=_back_keyboard())
        return

    shadow_target = User(username='shadow', password_hash='shadow', role='student', is_active=True)
    ok, reason = actor_can_assign_role(actor, shadow_target, new_role)
    if not ok:
        await query.edit_message_text(f'⛔ {esc(reason)}', parse_mode='HTML', reply_markup=_back_keyboard())
        return

    user_obj = lead.assigned_user
    created = False
    if not user_obj:
        username_seed = lead.telegram_username or f'tg_{lead.telegram_chat_id}'
        user_obj = User(
            username=_ensure_unique_username(username_seed),
            email=None,
            password_hash=generate_password_hash(secrets.token_urlsafe(24)),
            role=new_role,
            is_active=True,
            telegram_link=f'@{lead.telegram_username}' if lead.telegram_username else None,
            custom_status='создано из Telegram-бота',
        )
        db.session.add(user_obj)
        db.session.flush()
        created = True

    old_role = user_obj.role
    if created:
        old_role = 'Без роли'
    set_single_role(user_obj, new_role)

    profile = getattr(user_obj, 'profile', None)
    if not profile:
        profile = UserProfile(user_id=user_obj.id)
        db.session.add(profile)
    profile.telegram_chat_id = lead.telegram_chat_id
    if lead.telegram_username:
        profile.telegram_id = f'@{lead.telegram_username}'
    if lead.first_name and not profile.first_name:
        profile.first_name = lead.first_name
    if lead.last_name and not profile.last_name:
        profile.last_name = lead.last_name
    profile.telegram_notifications_enabled = True

    if new_role == 'student':
        _ensure_user_student_record(user_obj, _pick_lead_display_name(lead), lead.telegram_username)

    lead.assigned_user_id = user_obj.id
    lead.is_authorized = True
    lead.last_seen_at = datetime.now(timezone.utc).replace(tzinfo=None)

    db.session.commit()
    notified = notify_role_changed(user_obj, old_role, new_role, actor=actor)

    msg = (
        '✅ <b>Роль выдана прямо из бота</b>\n\n'
        f'Кому: <b>{esc(_pick_lead_display_name(lead))}</b>\n'
        f'Новая роль: <b>{esc(role_label(new_role))}</b>\n'
        f'Профиль: <b>{esc(user_display_name(user_obj))}</b>\n\n'
        f'Уведомление: {"отправлено" if notified else "не отправлено"}'
    )
    await query.edit_message_text(
        msg,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('🧩 Открыть роли пользователя', callback_data=f'role_user_{user_obj.id}')],
            [InlineKeyboardButton('↩️ К неавторизованным', callback_data='unauth_users')],
            _BACK_ROW,
        ]),
    )


async def _cb_student_manage(query, session, user, data: str):
    if not user or not _is_admin(user.get('role', '')):
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return

    raw = data[len('student_manage_'):]
    try:
        student_user_id_str, student_id_str = raw.split('_', 1)
        student_user_id = int(student_user_id_str)
        student_id = int(student_id_str)
    except ValueError:
        await query.edit_message_text('⚠️ Ученик не найден.', reply_markup=_back_keyboard())
        return

    row = session.execute(text("""
        SELECT st.name, u.username,
               (SELECT COUNT(*) FROM "FamilyTies" ft WHERE ft.student_id = :student_user_id) AS parent_count,
               (SELECT COUNT(*) FROM "Enrollments" e WHERE e.student_id = :student_user_id AND e.status = 'active') AS tutor_count
        FROM "Students" st
        LEFT JOIN "Users" u ON u.id = st.user_id
        WHERE st.student_id = :student_id
        LIMIT 1
    """), {'student_user_id': student_user_id, 'student_id': student_id}).fetchone()

    if not row:
        await query.edit_message_text('⚠️ Ученик не найден.', reply_markup=_back_keyboard())
        return

    name, username, parent_count, tutor_count = row
    profile_url = _build_student_profile_url(student_id)
    lines = [_student_admin_summary(session, student_user_id, student_id, name or username)]
    buttons = []
    if profile_url:
        buttons.append([InlineKeyboardButton('🔗 Открыть профиль ученика', url=profile_url)])
    buttons.append([
        InlineKeyboardButton('🔗 Запросить привязку TG', callback_data=f'student_tg_link_{student_user_id}_{student_id}'),
        InlineKeyboardButton('⛔ Отвязать TG', callback_data=f'student_tg_unlink_{student_user_id}_{student_id}'),
    ])
    buttons.append([
        InlineKeyboardButton('👪 Родители', callback_data=f'student_parents_{student_user_id}_{student_id}'),
        InlineKeyboardButton('👨‍🏫 Преподаватели', callback_data=f'student_tutors_{student_user_id}_{student_id}'),
    ])
    buttons.append([InlineKeyboardButton('👪 Родитель вне платформы', callback_data=f'student_stub_parent_{student_user_id}_{student_id}')])
    buttons.append([
        InlineKeyboardButton('↩️ К ученикам', callback_data='admin_students'),
        InlineKeyboardButton('📊 К сводке', callback_data='admin_home'),
    ])
    buttons.append(_BACK_ROW)
    await query.edit_message_text('\n'.join(lines), parse_mode='HTML', reply_markup=InlineKeyboardMarkup(buttons))


async def _cb_student_tg_link(query, session, user, data: str, context: ContextTypes.DEFAULT_TYPE):
    if not user or not _is_admin(user.get('role', '')):
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return
    try:
        raw = data[len('student_tg_link_'):]
        student_user_id_str, student_id_str = raw.split('_', 1)
        student_user_id = int(student_user_id_str)
        student_id = int(student_id_str)
    except ValueError:
        await query.edit_message_text('⚠️ Ученик не найден.', reply_markup=_back_keyboard())
        return

    row = session.execute(text("""
        SELECT COALESCE(NULLIF(st.name, ''), u.username)
        FROM "Users" u
        LEFT JOIN "Students" st ON st.user_id = u.id
        WHERE u.id = :uid AND st.student_id = :sid
        LIMIT 1
    """), {'uid': student_user_id, 'sid': student_id}).fetchone()
    student_name = row[0] if row else f'ID {student_user_id}'
    context.user_data['admin_tg_link_target'] = {
        'student_user_id': student_user_id,
        'student_id': student_id,
        'student_name': student_name,
        'admin_user_id': int(user['id']),
    }
    await query.edit_message_text(
        '🔗 <b>Ручная привязка Telegram</b>\n\n'
        f'Ученик: <b>{esc(student_name)}</b>\n\n'
        'Отправь следующим сообщением Telegram-тег ученика, например:\n'
        '<code>@username</code>\n\n'
        'Важно: ученик должен хотя бы раз открыть бота BooStudy и нажать /start, иначе бот не сможет отправить ему запрос.',
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('↩️ К карточке ученика', callback_data=f'student_manage_{student_user_id}_{student_id}')],
            _BACK_ROW,
        ]),
    )


async def _cb_student_tg_unlink(query, session, user, data: str):
    if not user or not _is_admin(user.get('role', '')):
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return
    try:
        raw = data[len('student_tg_unlink_'):]
        student_user_id_str, student_id_str = raw.split('_', 1)
        student_user_id = int(student_user_id_str)
        student_id = int(student_id_str)
    except ValueError:
        await query.edit_message_text('⚠️ Ученик не найден.', reply_markup=_back_keyboard())
        return

    try:
        from app.models import db, Student, UserProfile
        profile = UserProfile.query.filter_by(user_id=student_user_id).first()
        student = Student.query.get(student_id)
        if not profile or (not profile.telegram_chat_id and not profile.telegram_id):
            await query.edit_message_text(
                'ℹ️ Telegram у ученика уже не привязан.',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('↩️ К карточке ученика', callback_data=f'student_manage_{student_user_id}_{student_id}')],
                    _BACK_ROW,
                ]),
            )
            return
        profile.telegram_chat_id = None
        profile.telegram_id = None
        profile.telegram_link_code = None
        profile.telegram_link_code_expires = None
        profile.telegram_link_token = None
        profile.telegram_link_token_expires = None
        if student:
            student.telegram = None
            student.telegram_username = None
        db.session.commit()
        await query.edit_message_text(
            '✅ Telegram отвязан от аккаунта ученика.',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('↩️ К карточке ученика', callback_data=f'student_manage_{student_user_id}_{student_id}')],
                _BACK_ROW,
            ]),
        )
    except Exception as e:
        try:
            from app.models import db
            db.session.rollback()
        except Exception:
            pass
        logger.error('_cb_student_tg_unlink error: %s', e, exc_info=True)
        await query.edit_message_text('⚠️ Не удалось отвязать Telegram.', reply_markup=_back_keyboard())


async def _cb_student_parents(query, session, user, data: str):
    if not user or not _is_admin(user.get('role', '')):
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return
    raw = data[len('student_parents_'):]
    try:
        student_user_id_str, student_id_str = raw.split('_', 1)
        student_user_id = int(student_user_id_str)
        student_id = int(student_id_str)
    except ValueError:
        await query.edit_message_text('⚠️ Ученик не найден.', reply_markup=_back_keyboard())
        return

    from app.models import User, UserProfile

    rows = []
    family_ties = get_family_ties_for_student(student_user_id, include_pending=False)
    for tie in family_ties:
        parent = User.query.get(tie.parent_id)
        if not parent:
            continue
        profile = UserProfile.query.filter_by(user_id=parent.id).first()
        rows.append((
            tie.tie_id,
            parent.id,
            parent.username,
            getattr(profile, 'first_name', None),
            getattr(profile, 'last_name', None),
            getattr(profile, 'telegram_id', None),
        ))
    rows.sort(key=lambda row: ((row[3] or '').lower(), (row[2] or '').lower()))

    lines = ['👪 <b>Родители ученика</b>', '']
    buttons = []
    if not rows:
        lines.append('Пока никто не прикреплен.')
    else:
        for tie_id, parent_id, username, first_name, last_name, telegram_id in rows:
            display = (f'{first_name or ""} {last_name or ""}'.strip() or username or f'ID {parent_id}')[:32]
            tg = f' · {telegram_id}' if telegram_id else ''
            lines.append(f'• <b>{esc(display)}</b>{esc(tg)}')
            buttons.append([
                InlineKeyboardButton(display, callback_data=f'role_user_{parent_id}'),
                InlineKeyboardButton('Удалить', callback_data=f'student_remove_parent_{tie_id}_{student_user_id}_{student_id}'),
            ])
    buttons.append([InlineKeyboardButton('↩️ К ученику', callback_data=f'student_manage_{student_user_id}_{student_id}')])
    buttons.append(_BACK_ROW)
    await query.edit_message_text('\n'.join(lines), parse_mode='HTML', reply_markup=InlineKeyboardMarkup(buttons))


async def _cb_student_tutors(query, session, user, data: str):
    if not user or not _is_admin(user.get('role', '')):
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return
    raw = data[len('student_tutors_'):]
    try:
        student_user_id_str, student_id_str = raw.split('_', 1)
        student_user_id = int(student_user_id_str)
        student_id = int(student_id_str)
    except ValueError:
        await query.edit_message_text('⚠️ Ученик не найден.', reply_markup=_back_keyboard())
        return

    rows = session.execute(text("""
        SELECT e.enrollment_id, t.id, t.username, up.first_name, up.last_name, up.telegram_id, e.subject
        FROM "Enrollments" e
        JOIN "Users" t ON t.id = e.tutor_id
        LEFT JOIN "UserProfiles" up ON up.user_id = t.id
        WHERE e.student_id = :student_user_id
          AND e.status = 'active'
        ORDER BY up.first_name ASC NULLS LAST, t.username ASC
    """), {'student_user_id': student_user_id}).fetchall()

    lines = ['👨‍🏫 <b>Преподаватели ученика</b>', '']
    buttons = []
    if not rows:
        lines.append('Пока никто не прикреплен.')
    else:
        for enrollment_id, tutor_id, username, first_name, last_name, telegram_id, subject in rows:
            display = (f'{first_name or ""} {last_name or ""}'.strip() or username or f'ID {tutor_id}')[:32]
            suffix = f' · {subject}' if subject else ''
            tg = f' · {telegram_id}' if telegram_id else ''
            lines.append(f'• <b>{esc(display)}</b>{esc(suffix)}{esc(tg)}')
            buttons.append([
                InlineKeyboardButton(display, callback_data=f'role_user_{tutor_id}'),
                InlineKeyboardButton('Удалить', callback_data=f'student_remove_tutor_{enrollment_id}_{student_user_id}_{student_id}'),
            ])
    buttons.append([InlineKeyboardButton('↩️ К ученику', callback_data=f'student_manage_{student_user_id}_{student_id}')])
    buttons.append(_BACK_ROW)
    await query.edit_message_text('\n'.join(lines), parse_mode='HTML', reply_markup=InlineKeyboardMarkup(buttons))


async def _cb_student_remove_parent(query, session, user, data: str):
    if not user or not _is_admin(user.get('role', '')):
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return
    raw = data[len('student_remove_parent_'):]
    try:
        tie_id_str, student_user_id_str, student_id_str = raw.split('_', 2)
        tie_id = int(tie_id_str)
        student_user_id = int(student_user_id_str)
        student_id = int(student_id_str)
    except ValueError:
        await query.edit_message_text('⚠️ Не удалось понять связь.', reply_markup=_back_keyboard())
        return

    from app.models import db, FamilyTie

    tie = get_family_tie_by_id(tie_id)
    if not tie:
        await query.edit_message_text('⚠️ Связь уже удалена.', reply_markup=_back_keyboard())
        return

    db.session.delete(tie)
    db.session.commit()
    await query.edit_message_text(
        '✅ Родитель отвязан от ученика.',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('↩️ К родителям ученика', callback_data=f'student_parents_{student_user_id}_{student_id}')],
            [InlineKeyboardButton('↩️ К карточке ученика', callback_data=f'student_manage_{student_user_id}_{student_id}')],
            _BACK_ROW,
        ]),
    )


async def _cb_student_remove_tutor(query, session, user, data: str):
    if not user or not _is_admin(user.get('role', '')):
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return
    raw = data[len('student_remove_tutor_'):]
    try:
        enrollment_id_str, student_user_id_str, student_id_str = raw.split('_', 2)
        enrollment_id = int(enrollment_id_str)
        student_user_id = int(student_user_id_str)
        student_id = int(student_id_str)
    except ValueError:
        await query.edit_message_text('⚠️ Не удалось понять связь.', reply_markup=_back_keyboard())
        return

    from app.models import db, Enrollment

    enrollment = Enrollment.query.get(enrollment_id)
    if not enrollment:
        await query.edit_message_text('⚠️ Связь уже удалена.', reply_markup=_back_keyboard())
        return

    db.session.delete(enrollment)
    db.session.commit()
    await query.edit_message_text(
        '✅ Преподаватель отвязан от ученика.',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('↩️ К преподавателям ученика', callback_data=f'student_tutors_{student_user_id}_{student_id}')],
            [InlineKeyboardButton('↩️ К карточке ученика', callback_data=f'student_manage_{student_user_id}_{student_id}')],
            _BACK_ROW,
        ]),
    )


async def _cb_student_stub_parent(query, session, user, data: str):
    if not user or not _is_admin(user.get('role', '')):
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return

    raw = data[len('student_stub_parent_'):]
    try:
        student_user_id_str, student_id_str = raw.split('_', 1)
        student_user_id = int(student_user_id_str)
        student_id = int(student_id_str)
    except ValueError:
        await query.edit_message_text('⚠️ Не удалось определить ученика.', reply_markup=_back_keyboard())
        return

    from app.models import db, User, UserProfile, UserRole, FamilyTie, Student

    student = Student.query.get(student_id)
    if not student:
        await query.edit_message_text('⚠️ Ученик не найден.', reply_markup=_back_keyboard())
        return

    student_name = student.name or f'Ученик {student_id}'
    existing_tie = (
        FamilyTie.query
        .join(User, User.id == FamilyTie.parent_id)
        .filter(
            FamilyTie.student_id == student_user_id,
            User.role == 'parent',
            User.is_active.is_(False),
            User.custom_status == 'родитель отсутствует на платформе',
        )
        .first()
    )
    if existing_tie:
        await query.edit_message_text(
            'ℹ️ Для этого ученика уже есть пометка, что родитель отсутствует на платформе.',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('↩️ К карточке ученика', callback_data=f'student_manage_{student_user_id}_{student_id}')],
                _BACK_ROW,
            ]),
        )
        return

    parent_user = User(
        username=_ensure_unique_username(f'offline_parent_{student_user_id}'),
        email=None,
        password_hash=generate_password_hash(secrets.token_urlsafe(24)),
        role='parent',
        is_active=False,
        custom_status='родитель отсутствует на платформе',
    )
    db.session.add(parent_user)
    db.session.flush()
    db.session.add(UserRole(user_id=parent_user.id, role='parent'))
    db.session.add(UserProfile(
        user_id=parent_user.id,
        first_name='Родитель',
        last_name='вне платформы',
        internal_notes=f'Создано из Telegram-бота для ученика {student_name}',
        telegram_notifications_enabled=False,
    ))
    db.session.add(FamilyTie(
        parent_id=parent_user.id,
        student_id=student_user_id,
        access_level='full',
        is_confirmed=True,
    ))
    db.session.commit()

    await query.edit_message_text(
        '✅ <b>Готово</b>\n\n'
        f'Для ученика <b>{esc(student_name)}</b> создана заглушка:\n'
        '«родитель отсутствует на платформе / не пользуется платформой».\n\n'
        'Теперь в связях ученика будет видно, что родитель учтен.',
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('↩️ К карточке ученика', callback_data=f'student_manage_{student_user_id}_{student_id}')],
            [InlineKeyboardButton('🧩 К ролям и связям', callback_data='roles_panel')],
            _BACK_ROW,
        ]),
    )


async def _cb_designer_status(query, session, user):
    if not user or user.get('role') != 'designer':
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return
    await query.edit_message_text(
        '✨ <b>Графический дизайнер</b>\n\n'
        'Пока это роль-заглушка.\n'
        'Эта роль - пустышка(пока что), просто наслаждайся своим новым статусом.',
        parse_mode='HTML',
        reply_markup=_back_keyboard(),
    )


# ---------------------------------------------------------------------------
# Мои долги (student)
# ---------------------------------------------------------------------------

async def _cb_my_debts(query, session, user):
    if not user:
        await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode='HTML', reply_markup=_back_keyboard())
        return

    student = get_student_by_email(session, user.get('email'), user.get('id'))
    if not student:
        await query.edit_message_text(
            '📚 Профиль ученика не найден. Обратись к преподавателю.',
            parse_mode='HTML', reply_markup=_back_keyboard(),
        )
        return

    sid = student['student_id']

    hw_rows = session.execute(text("""
        SELECT l.lesson_date, l.topic, lt.status
        FROM "LessonTasks" lt
        JOIN "Lessons" l ON l.lesson_id = lt.lesson_id
        WHERE l.student_id = :sid
          AND lt.assignment_type = 'homework'
          AND lt.status NOT IN ('graded', 'checked')
        ORDER BY l.lesson_date DESC
        LIMIT 10
    """), {'sid': sid}).fetchall()

    sub_rows = session.execute(text("""
        SELECT a.title, s.status, a.deadline
        FROM "Submissions" s
        JOIN "Assignments" a ON a.assignment_id = s.assignment_id
        WHERE s.student_id = :sid
          AND s.status IN ('ASSIGNED', 'IN_PROGRESS', 'RETURNED')
        ORDER BY a.deadline ASC NULLS LAST
        LIMIT 10
    """), {'sid': sid}).fetchall()

    lines = ['📋 <b>Мои долги</b>', '']
    if not hw_rows and not sub_rows:
        lines.append('✅ У тебя нет невыполненных заданий! 🎉')
    else:
        if hw_rows:
            lines.append('<b>📝 ДЗ с уроков:</b>')
            for date_val, topic, status in hw_rows:
                d = date_val.strftime('%d.%m') if date_val else '—'
                t = esc((topic or 'Без темы')[:60])
                s = {'assigned': '📝 назначено', 'submitted': '⏳ на проверке', 'returned': '↩️ доработка'}.get(status, status)
                lines.append(f'  • {d} — {t} ({s})')
            lines.append('')
        if sub_rows:
            lines.append('<b>📄 Работы:</b>')
            for title, status, deadline in sub_rows:
                t = esc((title or 'Без названия')[:60])
                emoji = {'ASSIGNED': '📝', 'IN_PROGRESS': '🔄', 'RETURNED': '↩️'}.get(status, '❓')
                dl = f' (до {deadline.strftime("%d.%m %H:%M")})' if deadline else ''
                lines.append(f'  {emoji} {t}{dl}')

    await query.edit_message_text('\n'.join(lines), parse_mode='HTML', reply_markup=_back_keyboard())


# ---------------------------------------------------------------------------
# Случайная задача (student)
# ---------------------------------------------------------------------------

async def _cb_random_task(query, session, user):
    if not user:
        await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode='HTML', reply_markup=_back_keyboard())
        return
    student = get_student_by_email(session, user.get('email'), user.get('id'))
    category = (student or {}).get('category', 'ege')
    task_number = random.randint(1, 27)
    trainer_url = f'{APP_URL}/trainer?task_number={task_number}' if APP_URL else '#'
    await query.edit_message_text(
        f'🎲 <b>Случайная задача</b>\n\nТебе выпало задание <b>№{task_number}</b> ({esc(category.upper())}).',
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f'🎯 Открыть задание №{task_number}', url=trainer_url)],
            _BACK_ROW,
        ]),
    )


# ---------------------------------------------------------------------------
# Расписание
# ---------------------------------------------------------------------------

async def _cb_schedule(query, session, user):
    if not user:
        await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode='HTML', reply_markup=_back_keyboard())
        return
    student = get_student_by_email(session, user.get('email'), user.get('id'))
    if not student:
        await query.edit_message_text('📅 Профиль ученика не найден.', reply_markup=_back_keyboard())
        return
    lessons = get_lessons(session, student['student_id'], upcoming=True, limit=7)
    if not lessons:
        await query.edit_message_text(
            '📅 <b>Расписание</b>\n\nБлижайших уроков пока нет.',
            parse_mode='HTML', reply_markup=_back_keyboard(),
        )
        return
    await query.edit_message_text(build_lessons_text(lessons, upcoming=True), parse_mode='HTML', reply_markup=_back_keyboard())


# ---------------------------------------------------------------------------
# Статистика (student)
# ---------------------------------------------------------------------------

async def _cb_student_stats(query, session, user):
    if not user:
        await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode='HTML', reply_markup=_back_keyboard())
        return
    stats_text = await build_stats_text(session, user)
    await query.edit_message_text(stats_text, parse_mode='HTML', reply_markup=_back_keyboard())


# ---------------------------------------------------------------------------
# Тариф ученика
# ---------------------------------------------------------------------------

async def _cb_subscription(query, session, user):
    if not user:
        await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode='HTML', reply_markup=_back_keyboard())
        return
    summary = subscription_summary_for_user(int(user['id']))
    msg = (
        '💳 <b>Мой тариф</b>\n\n'
        f'Тариф: <b>{esc(summary.plan_title)}</b>\n'
        f'Статус: {esc(summary.status)}\n'
        f'Осталось уроков: <b>{esc(summary.lessons_remaining)}</b>\n'
        f'Действует до: {esc(summary.ends_at)}'
    )
    await query.edit_message_text(msg, parse_mode='HTML', reply_markup=_back_keyboard())


# ---------------------------------------------------------------------------
# Родитель
# ---------------------------------------------------------------------------

def _parent_children_rows(session, parent_user_id: int):
    from app.models import Student, User
    ties = get_family_ties_for_parent(int(parent_user_id), include_pending=True)
    rows = []
    for tie in ties:
        su = User.query.get(tie.student_id)
        if not su:
            continue
        st = Student.query.filter_by(user_id=su.id).first()
        rows.append((su.id, getattr(st, 'student_id', None), getattr(st, 'name', None), su.username, bool(tie.is_confirmed)))
    rows.sort(key=lambda row: ((row[2] or row[3] or '').lower(), (row[3] or '').lower()))
    return rows


def _parent_children_keyboard(rows):
    buttons = []
    for student_user_id, student_id, name, username, confirmed in rows[:8]:
        label = (name or username or 'Ученик')[:24]
        buttons.append([InlineKeyboardButton(f'👤 {label}', callback_data=f'parent_child_{student_user_id}_{student_id or 0}')])
    buttons.append([InlineKeyboardButton('↩️ Назад', callback_data='back_menu')])
    return InlineKeyboardMarkup(buttons)


async def _cb_parent_children(query, session, user):
    if not user:
        await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode='HTML', reply_markup=_back_keyboard())
        return
    rows = _parent_children_rows(session, int(user['id']))
    lines = ['👤 <b>Мои дети</b>', '']
    if not rows:
        lines.append('Пока не прикреплен ни один ученик.')
    else:
        for student_user_id, student_id, name, username, confirmed in rows:
            status = 'подтверждено' if confirmed else 'ожидает подтверждения'
            lines.append(f'• <b>{esc(name or username or "Ученик")}</b> — {status}')
    await query.edit_message_text('\n'.join(lines), parse_mode='HTML', reply_markup=_parent_children_keyboard(rows))


async def _cb_parent_child_detail(query, session, user, data: str):
    if not user:
        await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode='HTML', reply_markup=_back_keyboard())
        return
    raw = data[len('parent_child_'):]
    try:
        student_user_id_str, student_id_str = raw.split('_', 1)
        student_user_id = int(student_user_id_str)
        student_id = int(student_id_str)
    except ValueError:
        await query.edit_message_text('⚠️ Ученик не найден.', reply_markup=_back_keyboard())
        return

    from app.models import Student, User, UserProfile, UserSubscription

    tie = get_family_tie_between(int(user['id']), student_user_id, include_pending=True)
    if not tie:
        await query.edit_message_text('⚠️ Связь с учеником не найдена.', reply_markup=_back_keyboard())
        return

    su = User.query.get(student_user_id)
    st = Student.query.filter_by(user_id=student_user_id).first()
    profile = UserProfile.query.filter_by(user_id=student_user_id).first()
    sub = (
        UserSubscription.query.filter_by(user_id=student_user_id, status='active')
        .order_by(UserSubscription.ends_at.desc().nullslast(), UserSubscription.subscription_id.desc())
        .first()
    )
    status_label = 'Подтверждена' if tie.is_confirmed else 'Ожидает подтверждения'
    lesson_count = 'не указано'
    if sub:
        lesson_count = 'без лимита' if sub.lessons_remaining is None else str(sub.lessons_remaining)
    name = getattr(st, 'name', None) or (su.username if su else 'Ученик')
    lines = [
        '👤 <b>Карточка ребенка</b>',
        '',
        f'• <b>{esc(name)}</b>',
        f'• Связь: {esc(status_label)}',
        f'• Telegram: {esc((profile.telegram_id if profile else None) or "не привязан")}',
        f'• Баланс уроков: {esc(lesson_count)}',
    ]
    if student_id:
        lines.append(f'• Профиль на платформе: #{student_id}')
    buttons = []
    if student_id:
        buttons.append([InlineKeyboardButton('🔗 Открыть профиль на сайте', url=f'{(APP_URL or APP_OPEN_URL).rstrip("/")}/student/{student_id}')])
    buttons.append([
        InlineKeyboardButton('📅 Расписание', callback_data='parent_schedule'),
        InlineKeyboardButton('📝 Домашки', callback_data='parent_debts'),
    ])
    buttons.append([
        InlineKeyboardButton('💳 Тарифы', callback_data='parent_subscription'),
        InlineKeyboardButton('👤 К списку детей', callback_data='parent_children'),
    ])
    buttons.append(_BACK_ROW)
    await query.edit_message_text('\n'.join(lines), parse_mode='HTML', reply_markup=InlineKeyboardMarkup(buttons))


async def _cb_parent_schedule(query, session, user):
    if not user:
        await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode='HTML', reply_markup=_back_keyboard())
        return
    children = _parent_children_rows(session, int(user['id']))
    lines = ['📅 <b>Расписание детей</b>', '']
    found = False
    for _student_user_id, student_id, name, username, confirmed in children[:4]:
        if not student_id:
            continue
        if not confirmed:
            lines.append(f'<b>{esc(name or username or "Ученик")}</b> — связь ожидает подтверждения')
            lines.append('')
            continue
        lessons = get_lessons(session, int(student_id), upcoming=True, limit=3)
        lines.append(f'<b>{esc(name or username or "Ученик")}</b>')
        if not lessons:
            lines.append('  Ближайших уроков нет.')
        else:
            found = True
            for lesson in lessons:
                date_val = lesson.get('lesson_date') if isinstance(lesson, dict) else getattr(lesson, 'lesson_date', None)
                topic = lesson.get('topic') if isinstance(lesson, dict) else getattr(lesson, 'topic', None)
                d = date_val.strftime('%d.%m %H:%M') if date_val else '—'
                lines.append(f'  • {d} — {esc(topic or "урок")}')
        lines.append('')
    if not children:
        lines.append('Пока не прикреплен ни один ученик.')
    elif not found and len(lines) <= 3:
        lines.append('Ближайших уроков пока нет.')
    await query.edit_message_text('\n'.join(lines), parse_mode='HTML', reply_markup=_parent_children_keyboard(children))


async def _cb_parent_debts(query, session, user):
    if not user:
        await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode='HTML', reply_markup=_back_keyboard())
        return
    children = _parent_children_rows(session, int(user['id']))
    lines = ['📝 <b>Домашки и долги детей</b>', '']
    if not children:
        lines.append('Пока не прикреплен ни один ученик.')
    for student_user_id, student_id, name, username, confirmed in children[:5]:
        if not student_id:
            continue
        count = session.execute(text("""
            SELECT COUNT(*)
            FROM "Submissions" s
            WHERE s.student_id = :sid
              AND s.status IN ('ASSIGNED', 'IN_PROGRESS', 'RETURNED')
        """), {'sid': int(student_id)}).scalar() or 0
        lines.append(f'• <b>{esc(name or username or "Ученик")}</b>: {count} активных работ · {"подтверждено" if confirmed else "ожидает подтверждения"}')
    await query.edit_message_text('\n'.join(lines), parse_mode='HTML', reply_markup=_parent_children_keyboard(children))


async def _cb_parent_subscription(query, session, user):
    if not user:
        await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode='HTML', reply_markup=_back_keyboard())
        return
    children = _parent_children_rows(session, int(user['id']))
    lines = ['💳 <b>Тарифы детей</b>', '']
    if not children:
        lines.append('Пока не прикреплен ни один ученик.')
    for student_user_id, _student_id, name, username, confirmed in children[:5]:
        summary = subscription_summary_for_user(int(student_user_id))
        lines.append(f'<b>{esc(name or username or "Ученик")}</b>')
        lines.append(f'  Тариф: {esc(summary.plan_title)}')
        lines.append(f'  Осталось уроков: {esc(summary.lessons_remaining)}')
        lines.append(f'  Связь: {"подтверждена" if confirmed else "ожидает подтверждения"}')
        lines.append('')
    await query.edit_message_text('\n'.join(lines), parse_mode='HTML', reply_markup=_parent_children_keyboard(children))


# ---------------------------------------------------------------------------
# Преподаватель
# ---------------------------------------------------------------------------

async def _cb_teacher_students(query, session, user):
    if not user:
        await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode='HTML', reply_markup=_back_keyboard())
        return
    rows = session.execute(text("""
        SELECT DISTINCT su.id, st.student_id, st.name, su.username, e.subject
        FROM "Enrollments" e
        JOIN "Users" su ON su.id = e.student_id
        LEFT JOIN "Students" st ON st.user_id = su.id
        WHERE e.tutor_id = :uid AND e.status != 'archived'
        ORDER BY st.name ASC NULLS LAST, su.username ASC
        LIMIT 20
    """), {'uid': int(user['id'])}).fetchall()
    lines = ['🎓 <b>Мои ученики</b>', '']
    if not rows:
        lines.append('Пока нет прикрепленных учеников.')
    else:
        for _uid, _sid, name, username, subject in rows:
            subj = f' · {subject}' if subject else ''
            lines.append(f'• <b>{esc(name or username or "Ученик")}</b>{esc(subj)}')
    await query.edit_message_text('\n'.join(lines), parse_mode='HTML', reply_markup=_back_keyboard())


async def _cb_teacher_schedule(query, session, user):
    if not user:
        await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode='HTML', reply_markup=_back_keyboard())
        return
    rows = session.execute(text("""
        SELECT l.lesson_date, l.topic, st.name
        FROM "Lessons" l
        JOIN "Students" st ON st.student_id = l.student_id
        JOIN "Enrollments" e ON e.student_id = st.user_id
        WHERE e.tutor_id = :uid
          AND e.status != 'archived'
          AND l.lesson_date >= NOW()
        ORDER BY l.lesson_date ASC
        LIMIT 10
    """), {'uid': int(user['id'])}).fetchall()
    lines = ['📅 <b>Расписание преподавателя</b>', '']
    if not rows:
        lines.append('Ближайших уроков пока нет.')
    else:
        for date_val, topic, student_name in rows:
            d = date_val.strftime('%d.%m %H:%M') if date_val else '—'
            lines.append(f'• {d} — <b>{esc(student_name or "Ученик")}</b>, {esc(topic or "урок")}')
    await query.edit_message_text('\n'.join(lines), parse_mode='HTML', reply_markup=_back_keyboard())


# ---------------------------------------------------------------------------
# Непроверенные работы (teacher / admin)
# ---------------------------------------------------------------------------

async def _cb_ungraded(query, session, user):
    if not user:
        await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode='HTML', reply_markup=_back_keyboard())
        return
    role = user.get('role', '')
    if not (_is_creator(role) or _is_teacher(role)):
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return

    if _is_creator(role):
        rows = session.execute(text("""
            SELECT s.submission_id, a.title, st.name, s.submitted_at, s.status
            FROM "Submissions" s
            JOIN "Assignments" a ON a.assignment_id = s.assignment_id
            JOIN "Students" st ON st.student_id = s.student_id
            WHERE s.status IN ('SUBMITTED','NEEDS_MANUAL_REVIEW')
            ORDER BY s.submitted_at ASC NULLS LAST LIMIT 15
        """)).fetchall()
    else:
        rows = session.execute(text("""
            SELECT s.submission_id, a.title, st.name, s.submitted_at, s.status
            FROM "Submissions" s
            JOIN "Assignments" a ON a.assignment_id = s.assignment_id
            JOIN "Students" st ON st.student_id = s.student_id
            WHERE a.created_by_id = :uid
              AND s.status IN ('SUBMITTED','NEEDS_MANUAL_REVIEW')
            ORDER BY s.submitted_at ASC NULLS LAST LIMIT 15
        """), {'uid': user['id']}).fetchall()

    lines = ['📝 <b>Непроверенные работы</b>', '']
    if not rows:
        lines.append('✅ Все работы проверены!')
    else:
        for sid, title, student_name, submitted_at, status in rows:
            t = esc((title or '—')[:50])
            n = esc((student_name or '—')[:30])
            d = submitted_at.strftime('%d.%m %H:%M') if submitted_at else '—'
            emoji = '🔍' if status == 'NEEDS_MANUAL_REVIEW' else '📤'
            link = f'{APP_URL}/submissions/{sid}/grade' if APP_URL else ''
            lines.append(f'{emoji} <b>{t}</b>')
            lines.append(f'   {n} — {d}')
            if link:
                lines.append(f'   🔗 {link}')
            lines.append('')

    await query.edit_message_text('\n'.join(lines), parse_mode='HTML', reply_markup=_back_keyboard())


# ---------------------------------------------------------------------------
# Статистика платформы (creator)
# ---------------------------------------------------------------------------

async def _cb_admin_stats(query, session, user):
    if not user or not _is_admin(user.get('role', '')):
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return

    total_users = session.execute(text('SELECT COUNT(*) FROM "Users"')).scalar() or 0
    active_students = session.execute(text('SELECT COUNT(*) FROM "Students" WHERE is_active = TRUE')).scalar() or 0
    lessons_today = session.execute(text(
        "SELECT COUNT(*) FROM \"Lessons\" WHERE lesson_date::date = CURRENT_DATE"
    )).scalar() or 0
    pending = session.execute(text(
        "SELECT COUNT(*) FROM \"Submissions\" WHERE status IN ('SUBMITTED','NEEDS_MANUAL_REVIEW')"
    )).scalar() or 0
    active_subs = session.execute(text(
        "SELECT COUNT(*) FROM \"UserSubscriptions\" WHERE status = 'active'"
    )).scalar() or 0
    new_bug_reports = session.execute(text(
        "SELECT COUNT(*) FROM \"BotErrorReports\" WHERE status = 'new'"
    )).scalar() or 0

    msg = (
        '📊 <b>Статистика платформы</b>\n\n'
        f'👤 Пользователей: <b>{total_users}</b>\n'
        f'🎓 Активных учеников: <b>{active_students}</b>\n'
        f'📅 Уроков сегодня: <b>{lessons_today}</b>\n'
        f'📝 Ожидают проверки: <b>{pending}</b>\n'
        f'💳 Активных подписок: <b>{active_subs}</b>\n'
        f'🐛 Новых баг-репортов: <b>{new_bug_reports}</b>'
    )
    await query.edit_message_text(msg, parse_mode='HTML', reply_markup=_back_keyboard())


# ---------------------------------------------------------------------------
# Генерация инвайта (creator)
# ---------------------------------------------------------------------------

async def _cb_gen_invite(query, session, user):
    if not user or not _is_admin(user.get('role', '')):
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return

    code = secrets.token_urlsafe(6).upper()[:8]
    invite_url = f'{APP_URL}/invite/{code}' if APP_URL else code
    await query.edit_message_text(
        f'🔗 <b>Пригласительная ссылка</b>\n\n'
        f'Код: <code>{code}</code>\n'
        f'Ссылка: {invite_url}\n\n'
        f'Отправь ученику или родителю.',
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('📋 Открыть ссылку', url=invite_url)],
            _BACK_ROW,
        ]),
    )


# ---------------------------------------------------------------------------
# Список учеников (creator)
# ---------------------------------------------------------------------------

async def _cb_admin_users(query, session, user):
    if not user or not _is_admin(user.get('role', '')):
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return

    rows = session.execute(text("""
        SELECT u.username, u.role, up.telegram_chat_id IS NOT NULL AS has_tg,
               up.telegram_last_interaction_at
        FROM "Users" u
        LEFT JOIN "UserProfiles" up ON up.user_id = u.id
        WHERE u.is_active = TRUE
        ORDER BY u.created_at DESC
        LIMIT 20
    """)).fetchall()

    lines = ['👥 <b>Пользователи</b>', '']
    for username, role, has_tg, last_tg in rows:
        tg_badge = ' 📱' if has_tg else ''
        last_str = ''
        if last_tg:
            last_str = f' (был {last_tg.strftime("%d.%m")})'
        lines.append(f'• <b>{esc(username or "—")}</b>{tg_badge} — {esc(role_label(role))}{last_str}')
    if not rows:
        lines.append('Нет активных пользователей.')

    await query.edit_message_text('\n'.join(lines), parse_mode='HTML', reply_markup=_back_keyboard())


async def _cb_admin_students(query, session, user):
    if not user or not _is_admin(user.get('role', '')):
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return
    rows = session.execute(text("""
        SELECT u.id AS student_user_id,
               st.student_id,
               COALESCE(NULLIF(st.name, ''), up.first_name, u.username) AS display_name,
               u.username,
               up.telegram_chat_id IS NOT NULL AS has_tg,
               up.telegram_id,
               (SELECT COUNT(*) FROM "FamilyTies" ft WHERE ft.student_id = u.id) AS parent_count,
               (SELECT COUNT(*) FROM "Submissions" s WHERE s.student_id = st.student_id AND s.status IN ('ASSIGNED', 'IN_PROGRESS', 'RETURNED')) AS debt_count,
               (SELECT lesson_date FROM "Lessons" l WHERE l.student_id = st.student_id AND l.status = 'planned' AND l.lesson_date >= NOW() ORDER BY l.lesson_date ASC LIMIT 1) AS next_lesson_at
        FROM "Users" u
        LEFT JOIN "Students" st ON st.user_id = u.id
        LEFT JOIN "UserProfiles" up ON up.user_id = u.id
        WHERE u.is_active = TRUE
          AND u.role = 'student'
          AND COALESCE(u.is_demo_user, FALSE) = FALSE
        ORDER BY up.telegram_last_interaction_at DESC NULLS LAST, u.created_at DESC
        LIMIT 12
    """)).fetchall()
    lines = ['🎓 <b>Ученики</b>', '']
    buttons = []
    if not rows:
        lines.append('Активных учеников пока нет.')
    else:
        lines.append('Нажми на ученика, чтобы открыть карточку, Telegram и связи.')
        lines.append('')
        for student_user_id, student_id, display_name, username, has_tg, telegram_id, parent_count, debt_count, next_lesson_at in rows:
            if has_tg:
                tg_caption = f'✅ TG {telegram_id or ""}'.strip()
            elif telegram_id:
                tg_caption = f'⚠️ TG {telegram_id} без бота'
            else:
                tg_caption = '❌ TG нет'
            display_name = display_name or username or 'Ученик'
            next_lesson = f' · след. урок: {next_lesson_at.strftime("%d.%m %H:%M")}' if next_lesson_at else ''
            lines.append(f'• <b>{esc(display_name)}</b> · {esc(tg_caption)} · родители: {parent_count or 0} · долги: {debt_count or 0}{next_lesson}')
            if student_user_id and student_id:
                buttons.append([InlineKeyboardButton(display_name[:34], callback_data=f'student_manage_{student_user_id}_{student_id}')])
    buttons.append(_BACK_ROW)
    await query.edit_message_text('\n'.join(lines), parse_mode='HTML', reply_markup=InlineKeyboardMarkup(buttons))


async def _cb_admin_parents(query, session, user):
    if not user or not _is_admin(user.get('role', '')):
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return
    rows = session.execute(text("""
        SELECT u.id, COALESCE(NULLIF(TRIM(COALESCE(up.first_name, '') || ' ' || COALESCE(up.last_name, '')), ''), u.username) AS display_name,
               up.telegram_id,
               (SELECT COUNT(*) FROM "FamilyTies" ft WHERE ft.parent_id = u.id) AS children_count
        FROM "Users" u
        LEFT JOIN "UserProfiles" up ON up.user_id = u.id
        WHERE u.role = 'parent'
          AND COALESCE(u.is_demo_user, FALSE) = FALSE
        ORDER BY children_count DESC, display_name ASC
        LIMIT 20
    """)).fetchall()
    lines = ['👪 <b>Родители</b>', '']
    buttons = []
    if not rows:
        lines.append('Пока нет родителей.')
    else:
        for uid, display_name, telegram_id, children_count in rows:
            tg = f' · {telegram_id}' if telegram_id else ''
            lines.append(f'• <b>{esc(display_name)}</b> · детей: {children_count or 0}{esc(tg)}')
            buttons.append([InlineKeyboardButton(str(display_name)[:32], callback_data=f'role_user_{uid}')])
    buttons.append(_BACK_ROW)
    await query.edit_message_text('\n'.join(lines), parse_mode='HTML', reply_markup=InlineKeyboardMarkup(buttons))


async def _cb_admin_tutors(query, session, user):
    if not user or not _is_admin(user.get('role', '')):
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return
    rows = session.execute(text("""
        SELECT u.id, COALESCE(NULLIF(TRIM(COALESCE(up.first_name, '') || ' ' || COALESCE(up.last_name, '')), ''), u.username) AS display_name,
               up.telegram_id,
               (SELECT COUNT(DISTINCT e.student_id) FROM "Enrollments" e WHERE e.tutor_id = u.id AND e.status = 'active') AS students_count
        FROM "Users" u
        LEFT JOIN "UserProfiles" up ON up.user_id = u.id
        WHERE u.role = 'tutor'
          AND COALESCE(u.is_demo_user, FALSE) = FALSE
        ORDER BY students_count DESC, display_name ASC
        LIMIT 20
    """)).fetchall()
    lines = ['👨‍🏫 <b>Преподаватели</b>', '']
    buttons = []
    if not rows:
        lines.append('Пока нет преподавателей.')
    else:
        for uid, display_name, telegram_id, students_count in rows:
            tg = f' · {telegram_id}' if telegram_id else ''
            lines.append(f'• <b>{esc(display_name)}</b> · учеников: {students_count or 0}{esc(tg)}')
            buttons.append([InlineKeyboardButton(str(display_name)[:32], callback_data=f'role_user_{uid}')])
    buttons.append(_BACK_ROW)
    await query.edit_message_text('\n'.join(lines), parse_mode='HTML', reply_markup=InlineKeyboardMarkup(buttons))


# ---------------------------------------------------------------------------
# Статистика преподавателя
# ---------------------------------------------------------------------------

async def _cb_teacher_stats(query, session, user):
    if not user:
        await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode='HTML', reply_markup=_back_keyboard())
        return

    uid = user['id']
    row = session.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE s.status IN ('SUBMITTED','NEEDS_MANUAL_REVIEW')) AS pending,
            COUNT(*) FILTER (WHERE s.status = 'GRADED') AS graded,
            COUNT(*) AS total
        FROM "Submissions" s
        JOIN "Assignments" a ON a.assignment_id = s.assignment_id
        WHERE a.created_by_id = :uid
    """), {'uid': uid}).fetchone()

    lessons_row = session.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE status = 'completed') AS done,
            COUNT(*) FILTER (WHERE status = 'planned' AND lesson_date >= NOW()) AS upcoming
        FROM "Lessons"
        WHERE student_id IN (SELECT student_id FROM "Students" WHERE user_id = :uid)
    """), {'uid': uid}).fetchone()

    pending = row[0] if row else 0
    graded = row[1] if row else 0
    total = row[2] if row else 0
    done = lessons_row[0] if lessons_row else 0
    upcoming = lessons_row[1] if lessons_row else 0

    msg = (
        '📊 <b>Статистика преподавателя</b>\n\n'
        f'📝 Работ на проверку: <b>{pending}</b>\n'
        f'✅ Проверено: <b>{graded}</b> / {total}\n\n'
        f'📅 Проведённых уроков: <b>{done}</b>\n'
        f'🗓 Ближайших уроков: <b>{upcoming}</b>'
    )
    await query.edit_message_text(msg, parse_mode='HTML', reply_markup=_back_keyboard())


# ---------------------------------------------------------------------------
# Catch-all text
# ---------------------------------------------------------------------------

async def handle_private_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or update.message.chat.type != 'private':
        return
    touch_telegram_activity(update.effective_chat.id)
    pending_tg_link = context.user_data.get('admin_tg_link_target')
    if pending_tg_link:
        await _handle_admin_tg_link_username(update, context, pending_tg_link)
        return
    await update.message.reply_text(
        'Используй /menu для навигации или /help для справки.\n'
        'Для баг-репорта: /report или кнопка в меню.',
    )


async def _handle_admin_tg_link_username(update: Update, context: ContextTypes.DEFAULT_TYPE, target: dict):
    raw_username = (update.message.text or '').strip()
    username = _normalize_tg_username(raw_username)
    student_user_id = int(target.get('student_user_id') or 0)
    student_id = int(target.get('student_id') or 0)
    student_name = target.get('student_name') or f'ID {student_user_id}'
    admin_user_id = int(target.get('admin_user_id') or 0)

    if not username:
        await update.message.reply_text(
            '⚠️ Не вижу Telegram-тег. Отправь его в формате @username.',
            parse_mode='HTML',
        )
        return

    try:
        from app.models import db, TelegramStartLead, UserProfile
        from app.telegram.notifications import send_telegram_message

        lead = TelegramStartLead.query.filter(func.lower(TelegramStartLead.telegram_username) == username).first()
        target_chat_id = getattr(lead, 'telegram_chat_id', None)
        if not target_chat_id:
            existing_profile = UserProfile.query.filter(
                func.lower(UserProfile.telegram_id).in_((username, f'@{username}')),
                UserProfile.telegram_chat_id.isnot(None),
            ).first()
            if existing_profile and _clear_stale_tg_link(existing_profile):
                db.session.commit()
                existing_profile = None
            target_chat_id = getattr(existing_profile, 'telegram_chat_id', None)

        if not target_chat_id:
            await update.message.reply_text(
                '⚠️ Не нашел этого человека среди тех, кто писал боту.\n\n'
                'Попроси ученика открыть бота BooStudy, нажать /start, потом повтори привязку.',
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('↩️ К карточке ученика', callback_data=f'student_manage_{student_user_id}_{student_id}')],
                    _BACK_ROW,
                ]),
            )
            return

        profile = UserProfile.query.filter_by(user_id=student_user_id).first()
        if not profile:
            profile = UserProfile(user_id=student_user_id)
            db.session.add(profile)
            db.session.flush()
        profile.telegram_id = f'@{username}'
        db.session.commit()

        msg = (
            '🔗 <b>Запрос на привязку Telegram к BooStudy</b>\n\n'
            f'Аккаунт на платформе: <b>{esc(student_name)}</b>\n'
            f'Запросил администратор BooStudy.\n\n'
            'Если это твой аккаунт BooStudy, подтверди связь кнопкой ниже.'
        )
        markup = {'inline_keyboard': [[{
            'text': '✅ Подтвердить привязку',
            'callback_data': f'admin_link_confirm:{profile.profile_id}:{admin_user_id}',
        }]]}
        result = send_telegram_message(int(target_chat_id), msg, reply_markup=markup)
        if result and result.get('ok'):
            context.user_data.pop('admin_tg_link_target', None)
            await update.message.reply_text(
                f'✅ Запрос отправлен @{username}.\n\n'
                'Когда ученик нажмет подтверждение, Telegram привяжется к профилю, а тебе придет сообщение.',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('↩️ К карточке ученика', callback_data=f'student_manage_{student_user_id}_{student_id}')],
                    _BACK_ROW,
                ]),
            )
        else:
            await update.message.reply_text('⚠️ Не удалось отправить запрос ученику в Telegram.')
    except Exception as e:
        try:
            from app.models import db
            db.session.rollback()
        except Exception:
            pass
        logger.error('_handle_admin_tg_link_username error: %s', e, exc_info=True)
        await update.message.reply_text('⚠️ Ошибка при запуске привязки Telegram.')
