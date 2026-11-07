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


def _make_button(text: str, url: str | None = None, callback_data: str | None = None) -> dict:
    btn: dict[str, str] = {'text': text}
    if callback_data:
        btn['callback_data'] = callback_data
    elif url:
        btn['url'] = url
    return {'inline_keyboard': [[btn]]}


def _add_in_bot_action(button: dict | None, text: str, callback_data: str) -> dict:
    in_bot_btn = {'text': text, 'callback_data': callback_data}
    if not button:
        return {'inline_keyboard': [[in_bot_btn]]}
    kb = button.get('inline_keyboard', [])
    for row in kb:
        for b in row:
            if b.get('callback_data') == callback_data:
                return button
    kb.append([in_bot_btn])
    return button



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
    if meta.get('recipient_role'):
        role = str(meta['recipient_role']).lower().strip()
    elif meta.get('role'):
        role = str(meta['role']).lower().strip()
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

        elif kind_norm == 'lesson_batch_scheduled':
            count = meta.get('lessons_count') or len(meta.get('items_preview') or []) or 3
            if role == 'parent':
                card_lines.append(f'🗓️ <b>Назначено {count} занятий у ребёнка</b>')
            else:
                card_lines.append(f'🗓️ <b>Вам назначили {count} занятий</b>')
            card_lines.append('━━━━━━━━━━━━━━━━━━')
            if teacher_name:
                card_lines.append(f'👨‍🏫 <b>Преподаватель:</b> {html.escape(str(teacher_name))}')
            if subject:
                card_lines.append(f'📚 <b>Предмет:</b> {html.escape(str(subject))}')
            card_lines.append('')
            card_lines.append('<b>Ближайшие уроки:</b>')
            preview = meta.get('items_preview') or []
            for itm in preview[:5]:
                card_lines.append(f'• {html.escape(str(itm))}')
            if count > 5:
                card_lines.append(f'<i>... и ещё {count - 5} занятий в расписании</i>')
            card_lines.append('')
            card_lines.append('Все занятия уже добавлены в ваш календарь платформы.')
            button = _make_button('📅 Моё расписание', link_url or 'https://boostudy.ru/schedule')

        elif kind_norm in {'lesson_started', 'lesson_started_student'}:
            card_lines.append('🎬 <b>Урок начинается</b>')
            card_lines.append('━━━━━━━━━━━━━━━━━━')
            if student_name and role in {'parent', 'teacher'}:
                card_lines.append(f'👤 <b>Ученик:</b> {html.escape(str(student_name))}')
            if teacher_name and role != 'teacher':
                card_lines.append(f'👨‍🏫 <b>Преподаватель:</b> {html.escape(str(teacher_name))}')
            if subject:
                card_lines.append(f'📚 <b>Предмет:</b> {html.escape(str(subject))}')
            room_url = meta.get('room_url') or link_url
            if room_url:
                button = _make_button('🚀 Войти в класс', room_url)
            lesson_id = meta.get('lesson_id')
            if lesson_id and role == 'teacher':
                button = _add_in_bot_action(button, '🔗 Запросить ссылку', f'v3:tch:call_link:{lesson_id}')

        elif kind_norm == 'lesson_finished':
            card_lines.append('🏁 <b>Урок завершён</b>')
            card_lines.append('━━━━━━━━━━━━━━━━━━')
            if student_name and role in {'parent', 'teacher'}:
                card_lines.append(f'👤 <b>Ученик:</b> {html.escape(str(student_name))}')
            card_lines.append('Не забудьте сохранить заметку или выдать домашнее задание.')
            lesson_id = meta.get('lesson_id')
            if lesson_id and role == 'teacher':
                button = _make_button('📝 Заметка к уроку', callback_data=f'v3:tch:hw_note:{lesson_id}')

    # -------------------------------------------------------------------------
    # 2. Homework & Assignments Events
    # -------------------------------------------------------------------------
    elif kind_norm in {'assignment_assigned', 'teacher_homework_submitted', 'homework_submitted',
                       'assignment_submitted', 'homework_checked', 'assignment_graded',
                       'homework_returned', 'assignment_returned', 'review_queue', 'assignment_deadline',
                       'teacher_hw_note_reminder', 'lesson_comment'}:
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
            asg_id = meta.get('assignment_id')
            if asg_id and role == 'student':
                button = _add_in_bot_action(button, '📱 Открыть в боте', f'v3:stu:hw_item:{asg_id}')

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
                sub_id = meta.get('submission_id')
                if sub_id:
                    button = _add_in_bot_action(button, '📱 Проверить в боте', f'v3:tch:q_item:{sub_id}')
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
                asg_id = meta.get('assignment_id')
                if asg_id:
                    button = _add_in_bot_action(button, '📱 Открыть в боте', f'v3:stu:hw_item:{asg_id}')

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
            asg_id = meta.get('assignment_id')
            if asg_id and role == 'student':
                button = _add_in_bot_action(button, '📱 Результат в боте', f'v3:stu:hw_item:{asg_id}')

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
            asg_id = meta.get('assignment_id')
            if asg_id and role == 'student':
                button = _add_in_bot_action(button, '📱 Открыть в боте', f'v3:stu:hw_item:{asg_id}')

        elif kind_norm == 'review_queue':
            card_lines.append('📥 <b>Очередь проверки домашних заданий</b>')
            card_lines.append('━━━━━━━━━━━━━━━━━━')
            pending_count = meta.get('pending_count') or 1
            card_lines.append(f'📌 <b>Работ на проверке:</b> {pending_count}')
            if body:
                card_lines.append(html.escape(str(body)))
            if link_url:
                button = _make_button('📝 Перейти к проверке', link_url)
            if role in {'teacher', 'tutor'}:
                button = _add_in_bot_action(button, '📱 Очередь в боте', 'v3:tch:queue')


        elif kind_norm == 'assignment_deadline':
            card_lines.append('⚠️ <b>Скоро истекает срок сдачи задания</b>')
            card_lines.append('━━━━━━━━━━━━━━━━━━')
            if assignment_title:
                card_lines.append(f'📋 <b>Задание:</b> {html.escape(str(assignment_title))}')
            if deadline_str:
                card_lines.append(f'⏳ <b>Дедлайн:</b> {deadline_str}')
            if link_url:
                button = _make_button('📖 Сдать работу', link_url)

        elif kind_norm == 'teacher_hw_note_reminder':
            card_lines.append('⏰ <b>Напоминание о домашнем задании</b>')
            card_lines.append('━━━━━━━━━━━━━━━━━━')
            if student_name:
                card_lines.append(f'👤 <b>Ученик:</b> {html.escape(str(student_name))}')
            card_lines.append('К прошедшему занятию ещё не прикреплено домашнее задание.')
            lesson_id = meta.get('lesson_id')
            if lesson_id and role == 'teacher':
                button = _make_button('📝 Прикрепить ДЗ', callback_data=f'v3:tch:hw_note:{lesson_id}')

        elif kind_norm == 'lesson_comment':
            card_lines.append('💬 <b>Новый комментарий к заданию</b>')
            card_lines.append('━━━━━━━━━━━━━━━━━━')
            if role == 'teacher' and student_name:
                card_lines.append(f'👤 <b>Ученик:</b> {html.escape(str(student_name))}')
            if assignment_title:
                card_lines.append(f'📋 <b>Задание:</b> {html.escape(str(assignment_title))}')
            if body:
                card_lines.append(f'💬 <i>«{html.escape(str(body))}»</i>')
            if link_url:
                button = _make_button('💬 Открыть комментарии', link_url)

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
    # 5. Billing & Balances
    # -------------------------------------------------------------------------
    elif kind_norm in {'lesson_balance_changed', 'low_lessons', 'package_exhausted'}:
        rem = meta.get('lessons_remaining')
        delta = meta.get('delta')
        reason = meta.get('reason')
        if kind_norm == 'lesson_balance_changed':
            card_lines.append('💳 <b>Баланс занятий обновлён</b>')
            card_lines.append('━━━━━━━━━━━━━━━━━━')
            if delta:
                card_lines.append(f'📊 <b>Изменение:</b> {html.escape(str(delta))}')
            if rem is not None:
                card_lines.append(f'💰 <b>Остаток уроков:</b> {rem}')
            if reason:
                card_lines.append(f'💬 <b>Причина:</b> {html.escape(str(reason))}')
            button = _make_button('💳 Баланс и абонементы', link_url or 'https://boostudy.ru/billing')
        elif kind_norm == 'low_lessons':
            card_lines.append('⚠️ <b>Заканчивается оплаченный пакет</b>')
            card_lines.append('━━━━━━━━━━━━━━━━━━')
            if rem is not None:
                card_lines.append(f'💰 <b>Осталось занятий:</b> {rem}')
            card_lines.append('Рекомендуем продлить абонемент, чтобы сохранить удобное время в расписании.')
            button = _make_button('💳 Продлить абонемент', link_url or 'https://boostudy.ru/billing')
        elif kind_norm == 'package_exhausted':
            card_lines.append('🛑 <b>Оплаченные уроки закончились</b>')
            card_lines.append('━━━━━━━━━━━━━━━━━━')
            card_lines.append('Баланс уроков исчерпан. Для продолжения занятий пополните баланс.')
            button = _make_button('💳 Выбрать абонемент', link_url or 'https://boostudy.ru/billing')

    # -------------------------------------------------------------------------
    # 6. Broadcast & Announcements
    # -------------------------------------------------------------------------
    elif kind_norm in {'news', 'announcement', 'broadcast'}:
        sender_name = meta.get('sender_name')
        if kind_norm == 'news':
            card_lines.append('📢 <b>Новости BooStudy</b>')
        elif kind_norm == 'announcement':
            card_lines.append('🔔 <b>Важное объявление</b>')
        else:
            card_lines.append('📢 <b>Сообщение от преподавателя</b>')
        card_lines.append('━━━━━━━━━━━━━━━━━━')
        if sender_name:
            card_lines.append(f'👤 <b>Автор:</b> {html.escape(str(sender_name))}')
        if title and title not in ('news', 'announcement', 'broadcast'):
            card_lines.append(f'📌 <b>{html.escape(str(title))}</b>')
        text_body = body or meta.get('body') or meta.get('text')
        if text_body:
            card_lines.append('')
            card_lines.append(html.escape(str(text_body)))
        if link_url:
            button = _make_button('🔗 Подробнее', link_url)

    elif kind_norm == 'lesson_reminder_response':
        card_lines.append('ℹ️ <b>Отклик на напоминание</b>')
        card_lines.append('━━━━━━━━━━━━━━━━━━')
        st_name = meta.get('student_name')
        resp = meta.get('response')
        if st_name:
            card_lines.append(f'👤 <b>Ученик:</b> {html.escape(str(st_name))}')
        if resp:
            card_lines.append(f'💬 <b>Ответ:</b> {html.escape(str(resp))}')

    elif kind_norm == 'bug_report_reply':
        card_lines.append('🛠 <b>Ответ службы поддержки</b>')
        card_lines.append('━━━━━━━━━━━━━━━━━━')
        ticket = meta.get('ticket_id')
        if ticket:
            card_lines.append(f'🎫 <b>Тикет:</b> #{html.escape(str(ticket))}')
        reply_txt = body or meta.get('reply_text')
        if reply_txt:
            card_lines.append(f'💬 {html.escape(str(reply_txt))}')
        if link_url:
            button = _make_button('💬 Перейти к обращению', link_url)

    elif kind_norm in {'new_gradebook_entry', 'subscription_expiring'}:
        card_lines.append('ℹ️ <b>Уведомление устарело</b>')
        card_lines.append('━━━━━━━━━━━━━━━━━━')
        card_lines.append('Этот тип уведомлений выведен из эксплуатации.')

    # -------------------------------------------------------------------------
    # 7. Achievements, Digests & Generic Fallback
    # -------------------------------------------------------------------------
    elif kind_norm in {'achievement', 'achievement_unlocked'}:
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
