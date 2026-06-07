"""Напоминания за 30 минут до урока (Celery beat, каждые 5 мин)."""
from __future__ import annotations

import logging
import os
from datetime import timedelta

from celery_app import celery

logger = logging.getLogger(__name__)


def send_lesson_30min_reminder(lesson, *, force: bool = False) -> bool:
    """Send the same 30-minute lesson reminder used by the periodic task."""
    from app.models import Student, db
    from app.telegram.user_notify import notify_user_by_id
    from app.telegram.notifications import _esc
    from app.utils.datetime_utc import effective_timezone_name
    from app.utils.lesson_time import lesson_storage_to_local

    if not lesson or not getattr(lesson, 'lesson_id', None):
        return False
    if not force and getattr(lesson, 'tg_reminder_30min_sent', False):
        return False

    student = getattr(lesson, 'student', None)
    if not student and getattr(lesson, 'student_id', None):
        student = Student.query.get(lesson.student_id)
    if not student or not student.user_id:
        logger.info('lesson_reminder skipped lesson=%s: no linked student user', getattr(lesson, 'lesson_id', None))
        return False

    topic = _esc((lesson.topic or 'Занятие')[:60])
    base = (os.environ.get('APP_URL') or '').rstrip('/')
    room_url = f'{base}/lesson/{lesson.lesson_id}/classwork-tasks' if base else ''

    tz_name = 'Europe/Moscow'
    try:
        if getattr(student, 'user', None):
            tz_name = effective_timezone_name(student.user)
    except Exception:
        tz_name = 'Europe/Moscow'
    lesson_dt = lesson_storage_to_local(lesson.lesson_date, tz_name)
    time_str = lesson_dt.strftime('%H:%M') if lesson_dt else '—'

    msg = (
        f'⏰ <b>Урок через 30 минут!</b>\n\n'
        f'📚 {topic}\n'
        f'🕐 Начало: {time_str}\n'
    )
    if room_url:
        msg += f'\n🔗 {room_url}'
    markup = None
    if room_url:
        markup = {'inline_keyboard': [[{'text': '🚪 Войти в класс', 'url': room_url}]]}

    ok = notify_user_by_id(int(student.user_id), msg, kind='lesson_reminder', reply_markup=markup)
    if ok and not force:
        lesson.tg_reminder_30min_sent = True
        db.session.commit()
    return bool(ok)


@celery.task(name='app.tasks.telegram_lesson_reminders.telegram_lesson_reminders_task')
def telegram_lesson_reminders_task() -> dict:
    """
    Проверяет все запланированные уроки в окне [25 мин, 35 мин] от начала.
    Если напоминание ещё не отправлено — отправляет и ставит флаг.
    """
    from app.models import Lesson, Student, db
    from core.db_models import moscow_now

    now = moscow_now()
    window_start = (now + timedelta(minutes=25)).replace(tzinfo=None)
    window_end = (now + timedelta(minutes=35)).replace(tzinfo=None)
    sent = 0

    try:
        lessons = (
            Lesson.query
            .join(Student, Student.student_id == Lesson.student_id)
            .filter(
                Lesson.status == 'planned',
                Lesson.lesson_date >= window_start,
                Lesson.lesson_date <= window_end,
                Lesson.tg_reminder_30min_sent == False,
                Student.user_id.isnot(None),
            )
            .all()
        )
        logger.info(
            'lesson_reminder scan window=%s..%s candidates=%s',
            window_start,
            window_end,
            len(lessons),
        )

        for lesson in lessons:
            try:
                if send_lesson_30min_reminder(lesson):
                    sent += 1
            except Exception as loop_err:
                db.session.rollback()
                logger.warning('lesson_reminder skip lesson %s: %s', getattr(lesson, 'lesson_id', None), loop_err)

    except Exception as e:
        logger.error('telegram_lesson_reminders_task: %s', e, exc_info=True)
        return {'ok': False, 'error': str(e), 'sent': sent}

    return {'ok': True, 'sent': sent}
