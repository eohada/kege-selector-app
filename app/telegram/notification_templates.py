"""Centralized template builder for BooStudy Telegram notifications.

Renders high-quality, role-tailored visual cards with emoji, HTML formatting,
Russian date/time localization, and actionable inline buttons.
"""
from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.utils.timezone import to_viewer_tz, format_viewer_dt


RU_MONTHS = (
    'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
    'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
)
RU_WEEKDAYS = ('пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс')


def format_russian_dt(dt: datetime | str | None, viewer_tz: str | None = None) -> str:
    """Format UTC datetime into Russian localized string in viewer's timezone.

    Example: "24 октября (сб) в 18:00 МСК"
    """
    if dt is None:
        return ''
    local = to_viewer_tz(dt, viewer_tz or 'Europe/Moscow')
    if local is None:
        return str(dt)
    month_name = RU_MONTHS[local.month - 1]
    weekday_name = RU_WEEKDAYS[local.weekday()]
    time_str = local.strftime('%H:%M')
    tz_suffix = ' МСК' if (viewer_tz or 'Europe/Moscow') in {'Europe/Moscow', 'MSK'} else f' ({local.tzname() or viewer_tz})'
    return f"{local.day} {month_name} ({weekday_name}) в {time_str}{tz_suffix}"


def _get_user_role_and_tz(user_id: int) -> tuple[str, str]:
    """Retrieve user role and timezone with safe fallback."""
    from app.models import User, UserProfile
    try:
        user = User.query.get(user_id)
        role = getattr(user, 'role', 'student') or 'student'
        tz = getattr(user, 'timezone_iana', None)
        if not tz:
            prof = UserProfile.query.filter_by(user_id=user_id).first()
            tz = getattr(prof, 'timezone', None) or getattr(prof, 'timezone_iana', None)
        return str(role).lower(), str(tz or 'Europe/Moscow')
    except Exception:
        return 'student', 'Europe/Moscow'


def _make_button(text: str, url: str) -> dict:
    return {'inline_keyboard': [[{'text': text, 'url': url}]]}


def _is_local_url(url: str | None) -> bool:
    if not url:
        return False
    return '127.0.0.1' in url or 'localhost' in url


def render_telegram_notification(
    user_id: int,
    kind: str,
    title: str,
    body: str | None = None,
    link_url: str | None = None,
    meta: dict[str, Any] | None = None,
) -> tuple[str, dict | None]:
    """Central entrypoint for rendering notification cards.

    Returns:
        (html_text, reply_markup_dict_or_None)
    """
    meta = meta or {}
    role, user_tz = _get_user_role_and_tz(user_id)
    kind_norm = (kind or 'generic').lower().strip()

    card_lines: list[str] = []
    button: dict | None = None

    # Helper for formatting timestamps in meta
    def _meta_time(key: str) -> str:
        val = meta.get(key)
        if val:
            return format_russian_dt(val, user_tz)
        return ''

    # -------------------------------------------------------------------------
    # 1. Lesson & Schedule Events
    # -------------------------------------------------------------------------
    if kind_norm in {'lesson_scheduled', 'lesson_rescheduled', 'lesson_cancelled', 'lesson_reminder'}:
        dt_str = _meta_time('start_time') or _meta_time('lesson_date') or _meta_time('scheduled_time')
        student_name = meta.get('student_name')
        teacher_name = meta.get('teacher_name')
        subject = meta.get('subject') or meta.get('topic') or meta.get('lesson_title')

        if kind_norm == 'lesson_scheduled':
            if role == 'parent':
                header = '📅 <b>Новый урок у ребёнка</b>'
            elif role == 'teacher':
                header = '📅 <b>Новое занятие в расписании</b>'
            else:
                header = '📅 <b>Новый урок в расписании</b>'
            card_lines.append(header)
            card_lines.append('━━━━━━━━━━━━━━━━━━')
            if role == 'parent' and student_name:
                card_lines.append(f'👤 <b>Ученик:</b> {html.escape(str(student_name))}')
            if role != 'teacher' and teacher_name:
                card_lines.append(f'👨‍🏫 <b>Преподаватель:</b> {html.escape(str(teacher_name))}')
            if role == 'teacher' and student_name:
                card_lines.append(f'👤 <b>Ученик:</b> {html.escape(str(student_name))}')
            if subject:
                card_lines.append(f'📚 <b>Предмет / Тема:</b> {html.escape(str(subject))}')
            if dt_str:
                card_lines.append(f'⏰ <b>Начало:</b> {dt_str}')
            elif body:
                card_lines.append(html.escape(str(body)))

            if link_url:
                button = _make_button('📅 Открыть расписание', link_url)

        elif kind_norm == 'lesson_rescheduled':
            card_lines.append('🔄 <b>Урок перенесён</b>')
            card_lines.append('━━━━━━━━━━━━━━━━━━')
            if student_name and role in {'parent', 'teacher'}:
                card_lines.append(f'👤 <b>Ученик:</b> {html.escape(str(student_name))}')
            if subject:
                card_lines.append(f'📚 <b>Предмет:</b> {html.escape(str(subject))}')
            if dt_str:
                card_lines.append(f'⏰ <b>Новое время:</b> {dt_str}')
            old_dt = _meta_time('old_start_time')
            if old_dt:
                card_lines.append(f'⏳ <i>Старое время: {old_dt}</i>')
            if body and not dt_str:
                card_lines.append(html.escape(str(body)))

            if link_url:
                button = _make_button('📅 Расписание', link_url)

        elif kind_norm == 'lesson_cancelled':
            card_lines.append('❌ <b>Урок отменён</b>')
            card_lines.append('━━━━━━━━━━━━━━━━━━')
            if student_name and role in {'parent', 'teacher'}:
                card_lines.append(f'👤 <b>Ученик:</b> {html.escape(str(student_name))}')
            if subject:
                card_lines.append(f'📚 <b>Предмет:</b> {html.escape(str(subject))}')
            if dt_str:
                card_lines.append(f'⏰ <b>Было запланировано:</b> {dt_str}')
            reason = meta.get('reason')
            if reason:
                card_lines.append(f'💬 <b>Причина:</b> {html.escape(str(reason))}')
            elif body:
                card_lines.append(html.escape(str(body)))

            if link_url:
                button = _make_button('📅 Расписание', link_url)

        elif kind_norm == 'lesson_reminder':
            minutes_left = meta.get('minutes_left')
            time_phrase = f'через {minutes_left} мин.' if minutes_left else 'скоро'
            if role == 'parent':
                card_lines.append(f'⏰ <b>Напоминание: урок у ребёнка {time_phrase}</b>')
            else:
                card_lines.append(f'⏰ <b>Напоминание: урок начнётся {time_phrase}</b>')
            card_lines.append('━━━━━━━━━━━━━━━━━━')
            if student_name and role in {'parent', 'teacher'}:
                card_lines.append(f'👤 <b>Ученик:</b> {html.escape(str(student_name))}')
            if teacher_name and role != 'teacher':
                card_lines.append(f'👨‍🏫 <b>Преподаватель:</b> {html.escape(str(teacher_name))}')
            if subject:
                card_lines.append(f'📚 <b>Урок:</b> {html.escape(str(subject))}')
            if dt_str:
                card_lines.append(f'⏰ <b>Время:</b> {dt_str}')
            if body and not dt_str:
                card_lines.append(html.escape(str(body)))

            join_url = meta.get('room_url') or link_url
            if join_url:
                button = _make_button('🚀 Войти в класс', join_url)

    # -------------------------------------------------------------------------
    # 2. Homework & Assignments Events
    # -------------------------------------------------------------------------
    elif kind_norm in {'assignment_assigned', 'teacher_homework_submitted', 'homework_submitted',
                       'assignment_submitted', 'homework_checked', 'assignment_graded',
                       'homework_returned', 'assignment_returned', 'review_queue', 'assignment_deadline'}:
        assignment_title = meta.get('assignment_title') or meta.get('title') or title
        student_name = meta.get('student_name')
        deadline_str = _meta_time('deadline')
        score = meta.get('score')
        max_score = meta.get('max_score')
        comment = meta.get('teacher_comment') or meta.get('comment')

        if kind_norm == 'assignment_assigned':
            if role == 'parent':
                card_lines.append('📝 <b>Новое задание у ребёнка</b>')
            else:
                card_lines.append('📝 <b>Новое домашнее задание</b>')
            card_lines.append('━━━━━━━━━━━━━━━━━━')
            if role == 'parent' and student_name:
                card_lines.append(f'👤 <b>Ученик:</b> {html.escape(str(student_name))}')
            if assignment_title:
                card_lines.append(f'📋 <b>Задание:</b> {html.escape(str(assignment_title))}')
            if deadline_str:
                card_lines.append(f'⏳ <b>Срок сдачи:</b> {deadline_str}')
            if body and not assignment_title:
                card_lines.append(html.escape(str(body)))

            if link_url:
                btn_txt = '📖 Посмотреть задание' if role == 'parent' else '📖 Перейти к заданию'
                button = _make_button(btn_txt, link_url)

        elif kind_norm in {'teacher_homework_submitted', 'homework_submitted', 'assignment_submitted'}:
            if role == 'teacher':
                card_lines.append('📥 <b>Сдана домашняя работа</b>')
                card_lines.append('━━━━━━━━━━━━━━━━━━')
                if student_name:
                    card_lines.append(f'👤 <b>Ученик:</b> {html.escape(str(student_name))}')
                if assignment_title:
                    card_lines.append(f'📋 <b>Работа:</b> {html.escape(str(assignment_title))}')
                submitted_at = _meta_time('submitted_at')
                if submitted_at:
                    card_lines.append(f'⏱ <b>Сдано:</b> {submitted_at}')
                if body and not assignment_title:
                    card_lines.append(html.escape(str(body)))
                if link_url:
                    button = _make_button('📝 Проверить работу', link_url)
            elif role == 'parent':
                card_lines.append('📤 <b>Ребёнок сдал домашнюю работу</b>')
                card_lines.append('━━━━━━━━━━━━━━━━━━')
                if student_name:
                    card_lines.append(f'👤 <b>Ученик:</b> {html.escape(str(student_name))}')
                if assignment_title:
                    card_lines.append(f'📋 <b>Работа:</b> {html.escape(str(assignment_title))}')
                card_lines.append('<i>Работа ожидает проверки преподавателем.</i>')
                if link_url:
                    button = _make_button('📖 Посмотреть', link_url)
            else:
                card_lines.append('📤 <b>Домашняя работа успешно отправлена</b>')
                card_lines.append('━━━━━━━━━━━━━━━━━━')
                if assignment_title:
                    card_lines.append(f'📋 <b>Задание:</b> {html.escape(str(assignment_title))}')
                card_lines.append('<i>Работа отправлена преподавателю на проверку.</i>')
                if link_url:
                    button = _make_button('📋 Моя работа', link_url)

        elif kind_norm in {'homework_checked', 'assignment_graded'}:
            if role == 'parent':
                card_lines.append('✅ <b>Проверена домашняя работа ребёнка</b>')
            else:
                card_lines.append('✅ <b>Домашнее задание проверено</b>')
            card_lines.append('━━━━━━━━━━━━━━━━━━')
            if role == 'parent' and student_name:
                card_lines.append(f'👤 <b>Ученик:</b> {html.escape(str(student_name))}')
            if assignment_title:
                card_lines.append(f'📋 <b>Задание:</b> {html.escape(str(assignment_title))}')
            if score is not None:
                max_str = f' / {max_score}' if max_score is not None else ''
                card_lines.append(f'⭐️ <b>Оценка:</b> {score}{max_str}')
            if comment:
                card_lines.append(f'💬 <b>Комментарий:</b> <i>«{html.escape(str(comment))}»</i>')
            elif body and score is None:
                card_lines.append(html.escape(str(body)))

            if link_url:
                button = _make_button('📊 Посмотреть результат', link_url)

        elif kind_norm in {'homework_returned', 'assignment_returned'}:
            if role == 'parent':
                card_lines.append('🔄 <b>Работа ребёнка возвращена на доработку</b>')
            else:
                card_lines.append('🔄 <b>Работа возвращена на доработку</b>')
            card_lines.append('━━━━━━━━━━━━━━━━━━')
            if role == 'parent' and student_name:
                card_lines.append(f'👤 <b>Ученик:</b> {html.escape(str(student_name))}')
            if assignment_title:
                card_lines.append(f'📋 <b>Задание:</b> {html.escape(str(assignment_title))}')
            if comment:
                card_lines.append(f'💬 <b>Замечания учителя:</b> <i>«{html.escape(str(comment))}»</i>')
            elif body:
                card_lines.append(html.escape(str(body)))

            if link_url:
                btn_txt = '✏️ Исправить работу' if role != 'parent' else '📖 Посмотреть замечания'
                button = _make_button(btn_txt, link_url)

        elif kind_norm == 'review_queue':
            card_lines.append('📥 <b>Очередь проверки домашних заданий</b>')
            card_lines.append('━━━━━━━━━━━━━━━━━━')
            pending_count = meta.get('pending_count') or 1
            card_lines.append(f'📌 <b>Работ на проверке:</b> {pending_count}')
            if body:
                card_lines.append(html.escape(str(body)))
            if link_url:
                button = _make_button('📝 Перейти к проверке', link_url)

        elif kind_norm == 'assignment_deadline':
            card_lines.append('⚠️ <b>Скоро истекает срок сдачи задания</b>')
            card_lines.append('━━━━━━━━━━━━━━━━━━')
            if assignment_title:
                card_lines.append(f'📋 <b>Задание:</b> {html.escape(str(assignment_title))}')
            if deadline_str:
                card_lines.append(f'⏳ <b>Дедлайн:</b> {deadline_str}')
            if link_url:
                button = _make_button('📖 Сдать работу', link_url)

    # -------------------------------------------------------------------------
    # 3. Family Ties & Relations
    # -------------------------------------------------------------------------
    elif kind_norm in {'family_link_created', 'family_link_confirmed', 'family_link_revoked', 'family_link_removed'}:
        other_name = meta.get('relative_name') or meta.get('student_name') or meta.get('parent_name')
        if kind_norm == 'family_link_created':
            card_lines.append('👨‍👩‍👧 <b>Запрос на семейную привязку</b>')
            card_lines.append('━━━━━━━━━━━━━━━━━━')
            if other_name:
                card_lines.append(f'👤 <b>Пользователь:</b> {html.escape(str(other_name))}')
            if body:
                card_lines.append(html.escape(str(body)))
        elif kind_norm == 'family_link_confirmed':
            card_lines.append('👨‍👩‍👧 <b>Семейная связь подтверждена</b>')
            card_lines.append('━━━━━━━━━━━━━━━━━━')
            if other_name:
                card_lines.append(f'👤 <b>Связанный аккаунт:</b> {html.escape(str(other_name))}')
            if body:
                card_lines.append(html.escape(str(body)))
        else:
            card_lines.append('👨‍👩‍👧 <b>Семейная связь отключена</b>')
            card_lines.append('━━━━━━━━━━━━━━━━━━')
            if body:
                card_lines.append(html.escape(str(body)))

        if link_url:
            button = _make_button('👨‍👩‍👧 Семейный профиль', link_url)

    # -------------------------------------------------------------------------
    # 4. System & Operational Alerts
    # -------------------------------------------------------------------------
    elif kind_norm in {'system_critical_error', 'system_errors', 'operational_alert'}:
        if kind_norm == 'system_critical_error':
            card_lines.append('🚨 <b>Критический сбой системы</b>')
        else:
            card_lines.append('⚠️ <b>Системное оповещение</b>')
        card_lines.append('━━━━━━━━━━━━━━━━━━')
        if title:
            card_lines.append(f'<b>Тема:</b> {html.escape(str(title))}')
        if body:
            card_lines.append(f'<pre>{html.escape(str(body)[:800])}</pre>')
        service = meta.get('service')
        if service:
            card_lines.append(f'⚙️ <b>Сервис:</b> {html.escape(str(service))}')

    # -------------------------------------------------------------------------
    # 5. Achievements, Digests & Generic Fallback
    # -------------------------------------------------------------------------
    elif kind_norm == 'achievement':
        card_lines.append('🏆 <b>Новое достижение разблокировано!</b>')
        card_lines.append('━━━━━━━━━━━━━━━━━━')
        ach_title = meta.get('achievement_title') or title
        if ach_title:
            card_lines.append(f'⭐️ <b>«{html.escape(str(ach_title))}»</b>')
        if body:
            card_lines.append(html.escape(str(body)))
        if link_url:
            button = _make_button('🏆 Мои достижения', link_url)

    elif kind_norm in {'child_digest', 'daily_digest'}:
        card_lines.append('📊 <b>Дайджест успеваемости BooStudy</b>')
        card_lines.append('━━━━━━━━━━━━━━━━━━')
        if body:
            card_lines.append(html.escape(str(body)))
        if link_url:
            button = _make_button('📊 Полная статистика', link_url)

    else:
        # Default fallback
        icon = '🔔'
        clean_title = html.escape(str(title or 'Уведомление'))
        card_lines.append(f'{icon} <b>{clean_title}</b>')
        if body:
            card_lines.append('━━━━━━━━━━━━━━━━━━')
            card_lines.append(html.escape(str(body)))
        if link_url:
            button = _make_button('🔗 Перейти на платформу', link_url)

    # Dev link note if pointing to localhost
    if link_url and _is_local_url(link_url):
        card_lines.append('')
        card_lines.append('<i>ℹ️ Локальная ссылка (dev)</i>')

    text = '\n'.join(card_lines)
    return text, button
