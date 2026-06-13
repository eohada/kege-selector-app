"""Отложенные напоминания преподавателю по итогам урока."""
from __future__ import annotations

import logging
from datetime import timedelta

from celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(name='app.tasks.telegram_homework_notes.telegram_homework_notes_task')
def telegram_homework_notes_task() -> dict:
    from app.models import LessonTeacherHomeworkNote, db
    from core.db_models import moscow_now
    from app.telegram.notifications import notify_teacher_homework_note_reminder

    now = moscow_now()
    sent = 0
    try:
        notes = (
            LessonTeacherHomeworkNote.query
            .filter(LessonTeacherHomeworkNote.is_sent == False)  # noqa: E712
            .filter(LessonTeacherHomeworkNote.remind_at.isnot(None))
            .filter(LessonTeacherHomeworkNote.remind_at <= now)
            .order_by(LessonTeacherHomeworkNote.remind_at.asc())
            .limit(100)
            .all()
        )
        for note in notes:
            try:
                if notify_teacher_homework_note_reminder(note.note_id):
                    db.session.commit()
                    sent += 1
            except Exception as loop_err:
                db.session.rollback()
                logger.warning('homework note reminder skipped note=%s: %s', getattr(note, 'note_id', None), loop_err)
    except Exception as e:
        logger.error('telegram_homework_notes_task: %s', e, exc_info=True)
        return {'ok': False, 'error': str(e), 'sent': sent}
    return {'ok': True, 'sent': sent}
