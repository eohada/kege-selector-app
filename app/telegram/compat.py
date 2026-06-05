"""Compatibility helpers replacing the old `urep_bot.bot` layer."""
from __future__ import annotations

import html
from typing import Optional

from sqlalchemy import text

from app.models import Lesson, Student, User

WELCOME_MESSAGE = """
👋 <b>Привет! Я бот платформы BooStudy.</b>
"""

HELP_MESSAGE = """
📚 <b>Команды бота:</b>

• /menu — открыть главное меню
• /status — краткая сводка
• /settings — настройки уведомлений
• /start — приветствие и привязка
"""


def build_help_message(role: str | None = None) -> str:
    role = (role or '').strip()
    lines = [HELP_MESSAGE.strip(), '']

    if role == 'student':
        lines += [
            '👤 <b>Для ученика:</b>',
            '• /findstudent — недоступно, это для админов',
            '• Кнопки в меню: расписание, долги, тариф, Mini App',
        ]
    elif role == 'parent':
        lines += [
            '👪 <b>Для родителя:</b>',
            '• Кнопки в меню: дети, расписание, долги, тарифы',
        ]
    elif role in {'creator', 'chief_admin', 'admin'}:
        lines += [
            '🧩 <b>Для админа:</b>',
            '• /findstudent запрос — быстрый поиск ученика',
            '• Кнопки в меню: сводка, ученики, роли, рассылка',
        ]
    else:
        lines += [
            'ℹ️ <b>Подсказка:</b>',
            '• Сначала привяжи аккаунт через /start или /link',
        ]

    lines += [
        '',
        'Если что-то не нашлось, жми /menu — там самый короткий путь.',
    ]
    return '\n'.join(lines)

PROFILE_NOT_LINKED = """
❌ <b>Telegram не привязан к аккаунту</b>
"""

ERROR_MESSAGE = "❌ Произошла ошибка. Попробуй ещё раз или обратись к преподавателю."


def esc(value) -> str:
    return html.escape(str(value)) if value is not None else ''


def get_user_by_chat_id(session, chat_id: int) -> dict | None:
    row = session.execute(text("""
        SELECT u.id, u.username, u.email, u.role, up.first_name, up.last_name
        FROM "Users" u
        JOIN "UserProfiles" up ON up.user_id = u.id
        WHERE up.telegram_chat_id = :cid
        LIMIT 1
    """), {'cid': chat_id}).fetchone()
    if not row:
        return None
    uid, username, email, role, first_name, last_name = row
    return {
        'id': uid,
        'username': username,
        'email': email,
        'role': role,
        'first_name': first_name,
        'last_name': last_name,
    }


def get_student_by_email(session, email, user_id):
    student = Student.query.filter_by(user_id=user_id).first()
    if student:
        return {'student_id': student.student_id, 'name': student.name, 'category': getattr(student, 'category', None)}
    if email:
        student = Student.query.filter_by(email=email).first()
        if student:
            return {'student_id': student.student_id, 'name': student.name, 'category': getattr(student, 'category', None)}
    return None


def get_lessons(session, student_id: int, upcoming=True, limit=7):
    q = Lesson.query.filter_by(student_id=student_id)
    if upcoming:
        q = q.filter(Lesson.status == 'planned').order_by(Lesson.lesson_date.asc())
    else:
        q = q.order_by(Lesson.lesson_date.desc())
    lessons = q.limit(limit).all()
    return [
        {'lesson_date': l.lesson_date, 'topic': l.topic, 'lesson_id': l.lesson_id, 'status': l.status}
        for l in lessons
    ]


def build_lessons_text(lessons, upcoming=True):
    lines = ['📅 <b>Расписание</b>']
    if not lessons:
        lines.append('Уроков пока нет.')
    for lesson in lessons:
        dt = lesson.get('lesson_date')
        topic = lesson.get('topic') or 'Урок'
        lines.append(f'• {dt.strftime("%d.%m %H:%M") if dt else "—"} — {esc(topic)}')
    return '\n'.join(lines)


async def build_stats_text(session, user):
    return '📊 <b>Статистика</b>'
