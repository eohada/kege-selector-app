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
from telegram.ext import ContextTypes, ConversationHandler
from sqlalchemy import text

from app.telegram.db import get_session, close_session
from app.telegram.compat import (
    get_user_by_chat_id,
    get_student_by_email,
    get_lessons,
    build_lessons_text,
    build_stats_text,
    esc,
    WELCOME_MESSAGE,
    HELP_MESSAGE,
    PROFILE_NOT_LINKED,
    ERROR_MESSAGE,
)
from app.telegram.config import APP_URL, APP_OPEN_URL

from app.telegram.link_api import call_link_bot_api
from app.telegram.role_management import (
    MAIN_BOT_ROLES,
    actor_can_assign_role,
    notify_role_changed,
    relation_summary,
    role_label,
    set_single_role,
    subscription_summary_for_user,
    user_display_name,
)

logger = logging.getLogger(__name__)

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

def _mini_app_url() -> str:
    base = (APP_URL or os.environ.get('APP_URL') or '').strip().rstrip('/')
    return f'{base}/tg-app/' if base else ''


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


def _get_linked_user(chat_id: int) -> Optional[dict]:
    session = get_session()
    try:
        return get_user_by_chat_id(session, chat_id)
    finally:
        close_session(session)


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

    if _is_student(role):
        rows = [
            [
                InlineKeyboardButton('📋 Мои долги', callback_data='my_debts'),
                InlineKeyboardButton('📅 Расписание', callback_data='schedule'),
            ],
            [
                InlineKeyboardButton('🎲 Случайная задача', callback_data='random_task'),
                InlineKeyboardButton('📊 Статистика', callback_data='stats'),
            ],
            [
                InlineKeyboardButton('💳 Мой тариф', callback_data='subscription'),
                InlineKeyboardButton('📱 Mini App', web_app=WebAppInfo(url=_mini_app_url())) if _mini_app_url() else InlineKeyboardButton('🌐 Открыть сайт', url=APP_OPEN_URL),
            ],
            [
                InlineKeyboardButton('⚙️ Уведомления', callback_data='settings'),
                InlineKeyboardButton('🐛 Баг-репорт', callback_data='bug_report_start'),
            ],
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
                InlineKeyboardButton('📝 Непроверенные', callback_data='ungraded'),
                InlineKeyboardButton('🔗 Инвайт', callback_data='gen_invite'),
            ],
            [
                InlineKeyboardButton('📢 Рассылка', callback_data='broadcast_prompt'),
                InlineKeyboardButton('🐛 Баг-репорты', callback_data='view_bug_reports'),
            ],
            [InlineKeyboardButton('🌐 Панель управления', url=f'{APP_URL}/admin' if APP_URL else APP_OPEN_URL)],
        ]
    elif _is_senior_admin(role):
        rows = [
            [
                InlineKeyboardButton('📊 Сводка', callback_data='admin_stats'),
                InlineKeyboardButton('🧩 Роли и связи', callback_data='roles_panel'),
            ],
            [
                InlineKeyboardButton('👥 Пользователи', callback_data='admin_users'),
                InlineKeyboardButton('📝 Непроверенные', callback_data='ungraded'),
            ],
            [
                InlineKeyboardButton('📢 Рассылка', callback_data='broadcast_prompt'),
                InlineKeyboardButton('🐛 Баг-репорты', callback_data='view_bug_reports'),
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
                InlineKeyboardButton('📝 Непроверенные', callback_data='ungraded'),
            ],
            [
                InlineKeyboardButton('🐛 Баг-репорты', callback_data='view_bug_reports'),
                InlineKeyboardButton('⚙️ Уведомления', callback_data='settings'),
            ],
            [InlineKeyboardButton('🌐 Панель управления', url=f'{APP_URL}/admin/users' if APP_URL else APP_OPEN_URL)],
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
        [_btn('Новости и рассылки', 'tg_notify_news', 'news')],
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

    user = _get_linked_user(chat_id)
    mini_kb = _reply_keyboard_with_mini_app(user)

    if user:
        name = user.get('first_name') or user.get('username') or 'пользователь'
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


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/menu — ролевое меню."""
    chat_id = update.effective_chat.id
    touch_telegram_activity(chat_id)
    user = _get_linked_user(chat_id)

    if not user:
        await update.message.reply_text(
            '🔗 Сначала привяжи аккаунт командой /start или /link КОД',
        )
        return

    mini_kb = _reply_keyboard_with_mini_app(user)
    if mini_kb:
        await update.message.reply_text('👇 Mini App', reply_markup=mini_kb)
    await update.message.reply_text(
        '📋 <b>Меню BooStudy</b>',
        parse_mode='HTML',
        reply_markup=_menu_keyboard(user),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    touch_telegram_activity(update.effective_chat.id)
    await update.message.reply_text(HELP_MESSAGE, parse_mode='HTML')


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
            await update.message.reply_text('ℹ️ Нет связанного профиля ученика.')
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

        parts = []
        if next_lesson:
            d = next_lesson[0].strftime('%d.%m в %H:%M') if next_lesson[0] else '—'
            t = esc((next_lesson[1] or 'Урок')[:40])
            parts.append(f'📅 Ближайший урок: <b>{d}</b> — {t}')
        else:
            parts.append('📅 Ближайших уроков нет')

        parts.append(f'📋 Долгов: <b>{debts}</b>')

        await update.message.reply_text('\n'.join(parts), parse_mode='HTML')
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
    user = _get_linked_user(chat_id)
    if not user:
        await update.message.reply_text('🔗 Привяжи аккаунт командой /start')
        return
    await _send_settings(update.message.reply_text, chat_id)


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
    touch_telegram_activity(update.effective_chat.id)
    user = _get_linked_user(update.effective_chat.id)
    if not user:
        if update.message:
            await update.message.reply_text('🔗 Сначала привяжи аккаунт: /start')
        else:
            await update.callback_query.edit_message_text('🔗 Сначала привяжи аккаунт: /start')
        return ConversationHandler.END

    if update.callback_query:
        await update.callback_query.answer()
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
    await query.answer()

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
    await query.answer()

    data = query.data or ''
    chat_id = update.effective_chat.id
    touch_telegram_activity(chat_id)

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
            'my_debts':           _cb_my_debts,
            'random_task':        _cb_random_task,
            'schedule':           _cb_schedule,
            'stats':              _cb_student_stats,
            'subscription':        _cb_subscription,
            'parent_children':     _cb_parent_children,
            'parent_schedule':     _cb_parent_schedule,
            'parent_debts':        _cb_parent_debts,
            'parent_subscription': _cb_parent_subscription,
            'ungraded':           _cb_ungraded,
            'admin_stats':        _cb_admin_stats,
            'gen_invite':         _cb_gen_invite,
            'admin_users':        _cb_admin_users,
            'admin_students':      _cb_admin_students,
            'roles_panel':        _cb_roles_panel,
            'teacher_stats':      _cb_teacher_stats,
            'teacher_students':    _cb_teacher_students,
            'teacher_schedule':    _cb_teacher_schedule,
            'back_menu':          _cb_back_menu,
            'settings':           _cb_settings,
            'view_bug_reports':   _cb_view_bug_reports,
            'broadcast_prompt':   _cb_broadcast_prompt,
            'bug_report_start':   _cb_bug_report_start_inline,
        }

        if data.startswith('toggle_'):
            await _cb_toggle_notification(query, data, chat_id)
            return

        if data.startswith('role_user_'):
            await _cb_role_user(query, session, user, data)
            return

        if data.startswith('role_set_'):
            await _cb_role_set(query, session, user, data)
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
    await query.edit_message_text(
        '📋 <b>Меню BooStudy</b>', parse_mode='HTML', reply_markup=_menu_keyboard(user),
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
            'news':              'tg_notify_news',
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
    if mini_url:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton('📱 Открыть рассылку в Mini App', web_app=WebAppInfo(url=mini_url))],
            _BACK_ROW,
        ])
        await query.edit_message_text(
            '📢 <b>Рассылка</b>\n\nОткрой Mini App для создания рассылки.',
            parse_mode='HTML',
            reply_markup=kb,
        )
    else:
        await query.edit_message_text(
            '📢 Рассылка доступна через Mini App. Настрой APP_URL в переменных окружения.',
            reply_markup=_back_keyboard(),
        )


# ---------------------------------------------------------------------------
# Role management
# ---------------------------------------------------------------------------

async def _cb_roles_panel(query, session, user):
    if not user or not _can_manage_roles(user.get('role', '')):
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return

    rows = session.execute(text("""
        SELECT u.id, u.username, u.role, up.first_name, up.last_name, up.telegram_chat_id
        FROM "Users" u
        LEFT JOIN "UserProfiles" up ON up.user_id = u.id
        WHERE u.is_active = TRUE
          AND up.telegram_chat_id IS NOT NULL
        ORDER BY up.telegram_last_interaction_at DESC NULLS LAST, u.created_at DESC
        LIMIT 12
    """)).fetchall()

    lines = ['🧩 <b>Роли и связи</b>', '']
    lines.append('Выбери подключенного Telegram-пользователя:')
    buttons = []
    for uid, username, role, first_name, last_name, chat_id in rows:
        name = (f'{first_name or ""} {last_name or ""}'.strip() or username or f'ID {uid}')[:32]
        lines.append(f'• {esc(name)} — {esc(role_label(role))}')
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

    lines = [
        '👤 <b>Пользователь</b>',
        '',
        f'Имя: <b>{esc(user_display_name(target))}</b>',
        f'Текущая роль: <b>{esc(role_label(target.role))}</b>',
        esc(relation_summary(target)),
        '',
        'Выбери новую роль:',
    ]

    buttons = []
    for role in MAIN_BOT_ROLES:
        ok, _ = actor_can_assign_role(actor, target, role)
        if ok and role != target.role:
            buttons.append([InlineKeyboardButton(role_label(role), callback_data=f'role_set_{target.id}_{role}')])
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
    return session.execute(text("""
        SELECT su.id AS student_user_id, st.student_id, st.name, su.username
        FROM "FamilyTies" ft
        JOIN "Users" su ON su.id = ft.student_id
        LEFT JOIN "Students" st ON st.user_id = su.id
        WHERE ft.parent_id = :uid
        ORDER BY st.name ASC NULLS LAST, su.username ASC
    """), {'uid': parent_user_id}).fetchall()


async def _cb_parent_children(query, session, user):
    if not user:
        await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode='HTML', reply_markup=_back_keyboard())
        return
    rows = _parent_children_rows(session, int(user['id']))
    lines = ['👤 <b>Мои дети</b>', '']
    if not rows:
        lines.append('Пока не прикреплен ни один ученик.')
    else:
        for student_user_id, student_id, name, username in rows:
            lines.append(f'• <b>{esc(name or username or "Ученик")}</b>')
    await query.edit_message_text('\n'.join(lines), parse_mode='HTML', reply_markup=_back_keyboard())


async def _cb_parent_schedule(query, session, user):
    if not user:
        await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode='HTML', reply_markup=_back_keyboard())
        return
    children = _parent_children_rows(session, int(user['id']))
    lines = ['📅 <b>Расписание детей</b>', '']
    found = False
    for _student_user_id, student_id, name, username in children[:4]:
        if not student_id:
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
    await query.edit_message_text('\n'.join(lines), parse_mode='HTML', reply_markup=_back_keyboard())


async def _cb_parent_debts(query, session, user):
    if not user:
        await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode='HTML', reply_markup=_back_keyboard())
        return
    children = _parent_children_rows(session, int(user['id']))
    lines = ['📝 <b>Домашки и долги детей</b>', '']
    if not children:
        lines.append('Пока не прикреплен ни один ученик.')
    for _student_user_id, student_id, name, username in children[:5]:
        if not student_id:
            continue
        count = session.execute(text("""
            SELECT COUNT(*)
            FROM "Submissions" s
            WHERE s.student_id = :sid
              AND s.status IN ('ASSIGNED', 'IN_PROGRESS', 'RETURNED')
        """), {'sid': int(student_id)}).scalar() or 0
        lines.append(f'• <b>{esc(name or username or "Ученик")}</b>: {count} активных работ')
    await query.edit_message_text('\n'.join(lines), parse_mode='HTML', reply_markup=_back_keyboard())


async def _cb_parent_subscription(query, session, user):
    if not user:
        await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode='HTML', reply_markup=_back_keyboard())
        return
    children = _parent_children_rows(session, int(user['id']))
    lines = ['💳 <b>Тарифы детей</b>', '']
    if not children:
        lines.append('Пока не прикреплен ни один ученик.')
    for student_user_id, _student_id, name, username in children[:5]:
        summary = subscription_summary_for_user(int(student_user_id))
        lines.append(f'<b>{esc(name or username or "Ученик")}</b>')
        lines.append(f'  Тариф: {esc(summary.plan_title)}')
        lines.append(f'  Осталось уроков: {esc(summary.lessons_remaining)}')
        lines.append('')
    await query.edit_message_text('\n'.join(lines), parse_mode='HTML', reply_markup=_back_keyboard())


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
        SELECT st.name, u.username, up.telegram_chat_id IS NOT NULL AS has_tg
        FROM "Students" st
        LEFT JOIN "Users" u ON u.id = st.user_id
        LEFT JOIN "UserProfiles" up ON up.user_id = u.id
        WHERE st.is_active = TRUE
        ORDER BY st.student_id DESC
        LIMIT 20
    """)).fetchall()
    lines = ['🎓 <b>Ученики</b>', '']
    if not rows:
        lines.append('Активных учеников пока нет.')
    else:
        for name, username, has_tg in rows:
            tg_badge = ' 📱' if has_tg else ''
            lines.append(f'• <b>{esc(name or username or "Ученик")}</b>{tg_badge}')
    await query.edit_message_text('\n'.join(lines), parse_mode='HTML', reply_markup=_back_keyboard())


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
    await update.message.reply_text(
        'Используй /menu для навигации или /help для справки.\n'
        'Для баг-репорта: /report или кнопка в меню.',
    )
