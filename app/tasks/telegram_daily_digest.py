"""Утренний дайджест для учеников (Celery beat, пн–сб 8:00 МСК)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(name='app.tasks.telegram_daily_digest.telegram_daily_digest_task')
def telegram_daily_digest_task() -> dict:
    """
    Отправить каждому активному ученику с tg_notify_daily_digest=True
    краткий план на сегодня: уроки + кол-во незакрытых заданий.
    """
    from app.models import Student, Lesson, Submission, Assignment, db
    from app.telegram.user_notify import user_allows_telegram_notification, get_profile_for_user
    from app.telegram.notifications import notify_daily_digest
    from app.utils.datetime_utc import effective_timezone_name
    from app.utils.lesson_time import lesson_storage_to_local, timezone_from_name
    sent = 0

    try:
        students = Student.query.filter(
            Student.is_active == True,
            Student.user_id.isnot(None),
        ).all()

        for student in students:
            try:
                profile = get_profile_for_user(int(student.user_id))
                if not user_allows_telegram_notification(profile, 'daily_digest'):
                    continue

                tz_name = effective_timezone_name(student.user) if getattr(student, 'user', None) else 'Europe/Moscow'
                today = datetime.now(timezone.utc).astimezone(timezone_from_name(tz_name)).date()

                # Уроки сегодня
                candidate_lessons = Lesson.query.filter(
                    Lesson.student_id == student.student_id,
                    Lesson.status == 'planned',
                ).order_by(Lesson.lesson_date).all()
                today_lessons = [
                    lesson for lesson in candidate_lessons
                    if (lesson_storage_to_local(lesson.lesson_date, tz_name) is not None
                        and lesson_storage_to_local(lesson.lesson_date, tz_name).date() == today)
                ]

                lessons_data = []
                for l in today_lessons:
                    ld = lesson_storage_to_local(l.lesson_date, tz_name)
                    lessons_data.append({
                        'time': ld.strftime('%H:%M') if ld else '—',
                        'topic': l.topic or 'Занятие',
                    })

                # Незакрытые задания (только активные, не архивированные)
                pending_count = Submission.query.join(
                    Assignment, Assignment.assignment_id == Submission.assignment_id
                ).filter(
                    Submission.student_id == student.student_id,
                    Submission.status.in_(['ASSIGNED', 'IN_PROGRESS', 'RETURNED']),
                    Assignment.is_active == True,  # noqa: E712  не считаем архивные
                ).count()

                if notify_daily_digest(
                    student_user_id=int(student.user_id),
                    lessons_today=lessons_data,
                    pending_count=pending_count,
                ):
                    sent += 1

            except Exception as loop_err:
                logger.warning('daily_digest skip student %s: %s', getattr(student, 'student_id', None), loop_err)

    except Exception as e:
        logger.error('telegram_daily_digest_task: %s', e, exc_info=True)
        return {'ok': False, 'error': str(e), 'sent': sent}

    return {'ok': True, 'sent': sent}
