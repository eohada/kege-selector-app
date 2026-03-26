"""
Telegram Bot 2.0 — command handlers, role-based menus, callback handlers.

All DB access goes through ``urep_bot.db`` (raw SQLAlchemy sessions) so that
handlers work inside the dedicated bot event-loop thread without needing
Flask's application context.
"""
import html
import logging
import random
from datetime import datetime, timezone
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import text

from urep_bot.db import get_session, close_session
from urep_bot.bot import (
    get_user_by_chat_id,
    get_student_by_email,
    get_lessons,
    get_detailed_stats,
    get_subscription_info,
    build_lessons_text,
    build_profile_text,
    build_stats_text,
    esc,
    WELCOME_MESSAGE,
    HELP_MESSAGE,
    PROFILE_NOT_LINKED,
    ERROR_MESSAGE,
)
from urep_bot.config import APP_URL, APP_OPEN_URL

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keyboard builders
# ---------------------------------------------------------------------------

_BACK_ROW = [InlineKeyboardButton('« Меню', callback_data='back_menu')]


def _menu_keyboard(user: dict | None) -> InlineKeyboardMarkup:
    """Build a role-aware inline keyboard for /menu."""
    role = (user or {}).get('role', '')

    if role in ('student', 'parent'):
        rows = [
            [InlineKeyboardButton('📋 Мои долги', callback_data='my_debts')],
            [InlineKeyboardButton('🎲 Случайная задача', callback_data='random_task')],
            [InlineKeyboardButton('📅 Расписание', callback_data='schedule')],
            [InlineKeyboardButton('📊 Статистика', callback_data='stats')],
            [InlineKeyboardButton('🌐 Открыть сайт', url=APP_OPEN_URL)],
        ]
    elif role in ('admin', 'creator', 'chief_admin'):
        rows = [
            [InlineKeyboardButton('📊 Статистика платформы', callback_data='admin_stats')],
            [InlineKeyboardButton('🔗 Генерация инвайта', callback_data='gen_invite')],
            [InlineKeyboardButton('📝 Непроверенные работы', callback_data='ungraded')],
            [InlineKeyboardButton('👥 Пользователи', callback_data='admin_users')],
            [InlineKeyboardButton('🌐 Админ-панель', url=f'{APP_URL}/admin' if APP_URL else APP_OPEN_URL)],
        ]
    else:  # tutor / teacher / content_maker / designer / tester …
        rows = [
            [InlineKeyboardButton('📝 Непроверенные работы', callback_data='ungraded')],
            [InlineKeyboardButton('📊 Статистика', callback_data='teacher_stats')],
            [InlineKeyboardButton('📅 Расписание', callback_data='schedule')],
            [InlineKeyboardButton('🌐 Открыть сайт', url=APP_OPEN_URL)],
        ]
    return InlineKeyboardMarkup(rows)


def _back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([_BACK_ROW])


# ---------------------------------------------------------------------------
# Helper: resolve linked user
# ---------------------------------------------------------------------------

def _get_linked_user(chat_id) -> Optional[dict]:
    session = get_session()
    try:
        return get_user_by_chat_id(session, chat_id)
    finally:
        close_session(session)


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Greet the user; show different text if already linked."""
    chat_id = update.effective_chat.id
    user = _get_linked_user(chat_id)

    if user:
        name = user.get('first_name') or user.get('username') or 'пользователь'
        msg = (
            f'👋 <b>Привет, {esc(name)}!</b>\n\n'
            f'Ты привязан к BooStudy как <b>{esc(user.get("username", ""))}</b>.\n'
            'Нажми /menu для навигации.'
        )
        await update.message.reply_text(msg, parse_mode='HTML', reply_markup=_menu_keyboard(user))
    else:
        msg = (
            WELCOME_MESSAGE
            + f'\n\n🔢 <b>Твой chat_id:</b> <code>{chat_id}</code>'
        )
        await update.message.reply_text(msg, parse_mode='HTML')


# ---------------------------------------------------------------------------
# /menu
# ---------------------------------------------------------------------------

async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show role-based inline menu."""
    chat_id = update.effective_chat.id
    user = _get_linked_user(chat_id)

    if not user:
        await update.message.reply_text(
            '🔗 Сначала привяжи аккаунт — /start\nЗатем отправь /link КОД',
            parse_mode='HTML',
        )
        return

    await update.message.reply_text(
        '📋 <b>Меню BooStudy</b>',
        parse_mode='HTML',
        reply_markup=_menu_keyboard(user),
    )


# ---------------------------------------------------------------------------
# /help
# ---------------------------------------------------------------------------

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_MESSAGE, parse_mode='HTML')


# ---------------------------------------------------------------------------
# Catch-all for plain text (forward to polling bot's handler if needed)
# ---------------------------------------------------------------------------

async def handle_private_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Placeholder for private text messages (link codes, error reports, etc.)."""
    if not update.message or update.message.chat.type != 'private':
        return
    msg = (update.message.text or '').strip()
    if not msg:
        return
    await update.message.reply_text(
        'Используй /menu для навигации или /help для справки.',
    )


# ===================================================================
# Callback query dispatcher
# ===================================================================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    chat_id = update.effective_chat.id

    session = get_session()
    try:
        user = get_user_by_chat_id(session, chat_id)

        dispatch = {
            'my_debts':      _cb_my_debts,
            'random_task':   _cb_random_task,
            'schedule':      _cb_schedule,
            'stats':         _cb_student_stats,
            'ungraded':      _cb_ungraded,
            'admin_stats':   _cb_admin_stats,
            'gen_invite':    _cb_gen_invite,
            'admin_users':   _cb_admin_users,
            'teacher_stats': _cb_teacher_stats,
            'back_menu':     _cb_back_menu,
        }

        handler = dispatch.get(data)
        if handler:
            await handler(query, session, user)
        else:
            await query.edit_message_text(
                '⚠️ Неизвестная команда.',
                reply_markup=_back_keyboard(),
            )
    except Exception as e:
        logger.error('Callback %s error: %s', data, e, exc_info=True)
        try:
            await query.edit_message_text(ERROR_MESSAGE, parse_mode='HTML', reply_markup=_back_keyboard())
        except Exception:
            pass
    finally:
        close_session(session)


# ---------------------------------------------------------------------------
# « Меню (back)
# ---------------------------------------------------------------------------

async def _cb_back_menu(query, session, user):
    if not user:
        await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode='HTML')
        return
    await query.edit_message_text(
        '📋 <b>Меню BooStudy</b>',
        parse_mode='HTML',
        reply_markup=_menu_keyboard(user),
    )


# ---------------------------------------------------------------------------
# 📋 Мои долги  (student / parent)
# ---------------------------------------------------------------------------

async def _cb_my_debts(query, session, user):
    if not user:
        await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode='HTML', reply_markup=_back_keyboard())
        return

    student = get_student_by_email(session, user.get('email'), user.get('id'))
    if not student:
        await query.edit_message_text(
            '📚 Профиль ученика не найден. Обратись к преподавателю.',
            parse_mode='HTML',
            reply_markup=_back_keyboard(),
        )
        return

    sid = student['student_id']

    # Overdue / pending homework from LessonTasks
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

    # Pending / returned Submissions
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
                s_map = {'ASSIGNED': '📝', 'IN_PROGRESS': '🔄', 'RETURNED': '↩️'}
                emoji = s_map.get(status, '❓')
                dl = f' (до {deadline.strftime("%d.%m %H:%M")})' if deadline else ''
                lines.append(f'  {emoji} {t}{dl}')
            lines.append('')

    await query.edit_message_text('\n'.join(lines), parse_mode='HTML', reply_markup=_back_keyboard())


# ---------------------------------------------------------------------------
# 🎲 Случайная задача
# ---------------------------------------------------------------------------

async def _cb_random_task(query, session, user):
    if not user:
        await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode='HTML', reply_markup=_back_keyboard())
        return

    student = get_student_by_email(session, user.get('email'), user.get('id'))
    category = (student or {}).get('category', 'ege')

    task_number = random.randint(1, 27)
    trainer_url = f'{APP_URL}/trainer' if APP_URL else '#'

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f'🎯 Открыть задание №{task_number}',
            url=f'{trainer_url}?task_number={task_number}',
        )],
        _BACK_ROW,
    ])

    await query.edit_message_text(
        f'🎲 <b>Случайная задача</b>\n\n'
        f'Тебе выпало задание <b>№{task_number}</b> ({esc(category.upper())}).\n'
        f'Нажми кнопку ниже, чтобы решить его в тренажёре.',
        parse_mode='HTML',
        reply_markup=keyboard,
    )


# ---------------------------------------------------------------------------
# 📅 Расписание
# ---------------------------------------------------------------------------

async def _cb_schedule(query, session, user):
    if not user:
        await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode='HTML', reply_markup=_back_keyboard())
        return

    student = get_student_by_email(session, user.get('email'), user.get('id'))
    if not student:
        await query.edit_message_text(
            '📅 Профиль ученика не найден.',
            parse_mode='HTML',
            reply_markup=_back_keyboard(),
        )
        return

    lessons = get_lessons(session, student['student_id'], upcoming=True, limit=7)
    if not lessons:
        await query.edit_message_text(
            '📅 <b>Расписание</b>\n\nБлижайших уроков пока нет.',
            parse_mode='HTML',
            reply_markup=_back_keyboard(),
        )
        return

    text_msg = build_lessons_text(lessons, upcoming=True)
    await query.edit_message_text(text_msg, parse_mode='HTML', reply_markup=_back_keyboard())


# ---------------------------------------------------------------------------
# 📊 Статистика (student)
# ---------------------------------------------------------------------------

async def _cb_student_stats(query, session, user):
    if not user:
        await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode='HTML', reply_markup=_back_keyboard())
        return

    stats_text = await build_stats_text(session, user)
    await query.edit_message_text(stats_text, parse_mode='HTML', reply_markup=_back_keyboard())


# ---------------------------------------------------------------------------
# 📝 Непроверенные работы  (teacher / admin)
# ---------------------------------------------------------------------------

async def _cb_ungraded(query, session, user):
    if not user:
        await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode='HTML', reply_markup=_back_keyboard())
        return

    role = user.get('role', '')
    if role not in ('admin', 'creator', 'chief_admin', 'tutor', 'content_maker'):
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return

    user_id = user['id']

    # Submissions awaiting manual review (teacher sees only own assignments;
    # admins see all).
    if role in ('admin', 'creator', 'chief_admin'):
        rows = session.execute(text("""
            SELECT s.submission_id, a.title, st.name, s.submitted_at, s.status
            FROM "Submissions" s
            JOIN "Assignments" a ON a.assignment_id = s.assignment_id
            JOIN "Students" st ON st.student_id = s.student_id
            WHERE s.status IN ('SUBMITTED', 'NEEDS_MANUAL_REVIEW')
            ORDER BY s.submitted_at ASC NULLS LAST
            LIMIT 15
        """)).fetchall()
    else:
        rows = session.execute(text("""
            SELECT s.submission_id, a.title, st.name, s.submitted_at, s.status
            FROM "Submissions" s
            JOIN "Assignments" a ON a.assignment_id = s.assignment_id
            JOIN "Students" st ON st.student_id = s.student_id
            WHERE a.created_by_id = :uid
              AND s.status IN ('SUBMITTED', 'NEEDS_MANUAL_REVIEW')
            ORDER BY s.submitted_at ASC NULLS LAST
            LIMIT 15
        """), {'uid': user_id}).fetchall()

    lines = ['📝 <b>Непроверенные работы</b>', '']
    if not rows:
        lines.append('✅ Все работы проверены!')
    else:
        for sid, title, student_name, submitted_at, status in rows:
            t = esc((title or '—')[:50])
            n = esc((student_name or '—')[:30])
            d = submitted_at.strftime('%d.%m %H:%M') if submitted_at else '—'
            emoji = '🔍' if status == 'NEEDS_MANUAL_REVIEW' else '📤'
            link = f'{APP_URL}/submission/{sid}/grade' if APP_URL else ''
            line = f'{emoji} <b>{t}</b>\n   {n} — {d}'
            if link:
                line += f'\n   🔗 {link}'
            lines.append(line)
            lines.append('')

    await query.edit_message_text('\n'.join(lines), parse_mode='HTML', reply_markup=_back_keyboard())


# ---------------------------------------------------------------------------
# 📊 Статистика платформы  (admin)
# ---------------------------------------------------------------------------

async def _cb_admin_stats(query, session, user):
    if not user or user.get('role') not in ('admin', 'creator', 'chief_admin'):
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return

    total_users = session.execute(text('SELECT COUNT(*) FROM "Users"')).scalar() or 0
    active_students = session.execute(text(
        'SELECT COUNT(*) FROM "Students" WHERE is_active = TRUE'
    )).scalar() or 0
    lessons_today = session.execute(text(
        "SELECT COUNT(*) FROM \"Lessons\" WHERE lesson_date::date = CURRENT_DATE"
    )).scalar() or 0
    pending_submissions = session.execute(text(
        "SELECT COUNT(*) FROM \"Submissions\" WHERE status IN ('SUBMITTED','NEEDS_MANUAL_REVIEW')"
    )).scalar() or 0
    active_subs = session.execute(text(
        "SELECT COUNT(*) FROM \"UserSubscriptions\" WHERE status = 'active'"
    )).scalar() or 0

    msg = (
        '📊 <b>Статистика платформы</b>\n\n'
        f'👤 Пользователей: {total_users}\n'
        f'🎓 Активных учеников: {active_students}\n'
        f'📅 Уроков сегодня: {lessons_today}\n'
        f'📝 Ожидают проверки: {pending_submissions}\n'
        f'💳 Активных подписок: {active_subs}'
    )
    await query.edit_message_text(msg, parse_mode='HTML', reply_markup=_back_keyboard())


# ---------------------------------------------------------------------------
# 🔗 Генерация инвайта  (admin)
# ---------------------------------------------------------------------------

async def _cb_gen_invite(query, session, user):
    if not user or user.get('role') not in ('admin', 'creator', 'chief_admin'):
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return

    import secrets
    code = secrets.token_urlsafe(6).upper()[:8]
    invite_url = f'{APP_URL}/invite/{code}' if APP_URL else code

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton('📋 Скопировать ссылку', url=invite_url)],
        _BACK_ROW,
    ])

    await query.edit_message_text(
        f'🔗 <b>Пригласительная ссылка</b>\n\n'
        f'Код: <code>{code}</code>\n'
        f'Ссылка: {invite_url}\n\n'
        f'Отправь эту ссылку ученику или родителю.',
        parse_mode='HTML',
        reply_markup=keyboard,
    )


# ---------------------------------------------------------------------------
# 👥 Пользователи  (admin)
# ---------------------------------------------------------------------------

async def _cb_admin_users(query, session, user):
    if not user or user.get('role') not in ('admin', 'creator', 'chief_admin'):
        await query.edit_message_text('⛔ Доступ запрещён.', reply_markup=_back_keyboard())
        return

    rows = session.execute(text("""
        SELECT u.username, u.role, up.telegram_chat_id IS NOT NULL AS has_tg
        FROM "Users" u
        LEFT JOIN "UserProfiles" up ON up.user_id = u.id
        WHERE u.is_active = TRUE
        ORDER BY u.created_at DESC
        LIMIT 20
    """)).fetchall()

    lines = ['👥 <b>Последние пользователи</b>', '']
    for username, role, has_tg in rows:
        tg_badge = ' 📱' if has_tg else ''
        lines.append(f'• <b>{esc(username or "—")}</b> — {esc(role or "—")}{tg_badge}')
    if not rows:
        lines.append('Нет активных пользователей.')

    await query.edit_message_text('\n'.join(lines), parse_mode='HTML', reply_markup=_back_keyboard())


# ---------------------------------------------------------------------------
# 📊 Статистика преподавателя  (tutor)
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

    pending = row[0] if row else 0
    graded = row[1] if row else 0
    total = row[2] if row else 0

    lessons_row = session.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE status = 'completed') AS done,
            COUNT(*) FILTER (WHERE status = 'planned' AND lesson_date >= NOW()) AS upcoming
        FROM "Lessons"
        WHERE student_id IN (
            SELECT student_id FROM "Students" WHERE user_id = :uid
        )
    """), {'uid': uid}).fetchone()

    lessons_done = lessons_row[0] if lessons_row else 0
    lessons_upcoming = lessons_row[1] if lessons_row else 0

    msg = (
        '📊 <b>Статистика преподавателя</b>\n\n'
        f'📝 Работ на проверку: {pending}\n'
        f'✅ Проверено: {graded} / {total}\n\n'
        f'📅 Проведённых уроков: {lessons_done}\n'
        f'🗓 Ближайших уроков: {lessons_upcoming}'
    )
    await query.edit_message_text(msg, parse_mode='HTML', reply_markup=_back_keyboard())
