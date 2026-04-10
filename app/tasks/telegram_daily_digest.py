"""Утренний дайджест для учеников (Celery beat, пн–сб 8:00 МСК)."""
from __future__ import annotations

import logging

from celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(name='app.tasks.telegram_daily_digest.telegram_daily_digest_task')
def telegram_daily_digest_task() -> dict:
    """
    Отправить каждому активному ученику с tg_notify_daily_digest=True
    краткий план на сегодня: уроки + кол-во незакрытых заданий.
    """
    from app.models import Student, Lesson, Submission, Assignment, db
    from core.db_models import MOSCOW_TZ, moscow_now
    from app.telegram.user_notify import user_allows_telegram_notification, get_profile_for_user
    from app.telegram.notifications import notify_daily_digest

    now = moscow_now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=0)
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

                # Уроки сегодня
                today_lessons = Lesson.query.filter(
                    Lesson.student_id == student.student_id,
                    Lesson.lesson_date >= today_start.replace(tzinfo=None),
                    Lesson.lesson_date <= today_end.replace(tzinfo=None),
                    Lesson.status == 'planned',
                ).order_by(Lesson.lesson_date).all()

                lessons_data = []
                for l in today_lessons:
                    ld = l.lesson_date
                    if hasattr(ld, 'tzinfo') and ld.tzinfo:
                        ld = ld.astimezone(MOSCOW_TZ)
                    lessons_data.append({
                        'time': ld.strftime('%H:%M') if ld else '—',
                        'topic': l.topic or 'Занятие',
                    })

                # Незакрытые задания
                pending_count = Submission.query.join(
                    Assignment, Assignment.assignment_id == Submission.assignment_id
                ).filter(
                    Submission.student_id == student.student_id,
                    Submission.status.in_(['ASSIGNED', 'IN_PROGRESS', 'RETURNED']),
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
