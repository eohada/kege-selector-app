"""Периодические напоминания о дедлайнах сдачи работ (Telegram, антиспам через БД)."""
from __future__ import annotations

import logging
import os
from datetime import timedelta, timezone

from celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(name='app.tasks.telegram_deadlines.telegram_deadline_reminders_task')
def telegram_deadline_reminders_task() -> dict:
    from app.models import Submission, Assignment, Student, db
    from core.db_models import SubmissionTelegramDeadlineSent, utc_now, MOSCOW_TZ
    from app.telegram.notifications import _esc
    from app.telegram.user_notify import notify_user_by_id

    now = utc_now()
    sent = 0
    try:
        q = (
            Submission.query.join(Assignment, Assignment.assignment_id == Submission.assignment_id)
            .join(Student, Student.student_id == Submission.student_id)
            .filter(
                Submission.status.in_(['ASSIGNED', 'IN_PROGRESS', 'RETURNED']),
                Assignment.deadline.isnot(None),
                Assignment.is_active == True,  # noqa: E712  не уведомляем по архивным
                Student.user_id.isnot(None),
            )
        )
        # Materialize rows before entering the loop.
        # Committing inside the loop closes the transaction, so a live server-side
        # cursor would become invalid mid-iteration.
        for sub in q.all():
            try:
                assignment = sub.assignment
                if not assignment or not assignment.deadline or not sub.student or not sub.student.user_id:
                    continue
                dl = assignment.deadline
                if getattr(dl, 'tzinfo', None) is None:
                    dl_utc = dl.replace(tzinfo=MOSCOW_TZ).astimezone(timezone.utc)
                else:
                    dl_utc = dl.astimezone(timezone.utc)
                delta = dl_utc - now
                if delta.total_seconds() <= 0:
                    continue
                window_key = None
                if timedelta(hours=22) <= delta <= timedelta(hours=26):
                    window_key = '24h'
                elif timedelta(minutes=40) <= delta <= timedelta(minutes=80):
                    window_key = '1h'
                if not window_key:
                    continue
                if SubmissionTelegramDeadlineSent.query.filter_by(
                    submission_id=sub.submission_id,
                    window_key=window_key,
                ).first():
                    continue

                title = (assignment.title or 'Работа').strip()
                base = (os.environ.get('APP_URL') or '').strip().rstrip('/')
                link = f'{base}/submissions/{sub.submission_id}' if base else ''
                if window_key == '24h':
                    head = 'Дедлайн через ~24 ч'
                else:
                    head = 'Дедлайн примерно через час'
                msg = (
                    f'⏰ <b>{_esc(head)}</b>\n\n'
                    f'📄 {_esc(title)}\n'
                )
                if link:
                    msg += f'\n🔗 {link}'
                reply_markup = None
                if link:
                    reply_markup = {'inline_keyboard': [[{'text': '📄 К работе', 'url': link}]]}

                uid = int(sub.student.user_id)
                if notify_user_by_id(int(uid), msg, kind='lesson_reminder', reply_markup=reply_markup):
                    db.session.add(
                        SubmissionTelegramDeadlineSent(
                            submission_id=sub.submission_id,
                            window_key=window_key,
                        )
                    )
                    db.session.commit()
                    sent += 1
            except Exception as loop_err:
                db.session.rollback()
                logger.warning('deadline reminder skip submission %s: %s', getattr(sub, 'submission_id', None), loop_err)
                continue
    except Exception as e:
        logger.error('telegram_deadline_reminders_task: %s', e, exc_info=True)
        return {'ok': False, 'error': str(e), 'sent': sent}
    return {'ok': True, 'sent': sent}
