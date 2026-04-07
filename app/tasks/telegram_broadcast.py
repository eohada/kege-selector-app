"""Пакетная рассылка Telegram с throttling (Celery)."""
from __future__ import annotations

import logging
import time

from celery_app import celery

logger = logging.getLogger(__name__)

_BATCH = 22
_INTER_MESSAGE_SLEEP = 0.06


def _linked_student_chat_targets_after_cursor(cursor_user_id: int | None, limit: int):
    from app.models import User, UserProfile, Student, db

    c = cursor_user_id or 0
    q = (
        db.session.query(User.id, UserProfile.telegram_chat_id)
        .join(UserProfile, UserProfile.user_id == User.id)
        .join(Student, Student.user_id == User.id)
        .filter(
            Student.is_active.is_(True),
            UserProfile.telegram_chat_id.isnot(None),
            User.id > c,
        )
        .order_by(User.id.asc())
        .limit(limit)
    )
    return q.all()


def _count_linked_student_targets() -> int:
    from app.models import User, UserProfile, Student, db

    return (
        db.session.query(db.func.count(User.id))
        .join(UserProfile, UserProfile.user_id == User.id)
        .join(Student, Student.user_id == User.id)
        .filter(
            Student.is_active.is_(True),
            UserProfile.telegram_chat_id.isnot(None),
        )
        .scalar()
        or 0
    )


@celery.task(bind=True, name='app.tasks.telegram_broadcast.process_telegram_broadcast_batch', max_retries=6)
def process_telegram_broadcast_batch(self, broadcast_id: int) -> dict:
    from app.models import TelegramBroadcast, db
    from core.db_models import moscow_now
    from app.telegram.notifications import send_telegram_message, send_telegram_photo

    br = TelegramBroadcast.query.get(broadcast_id)
    if not br:
        return {'ok': False, 'error': 'not_found'}
    if br.status in ('cancelled', 'completed', 'failed'):
        return {'ok': True, 'skipped': br.status}

    try:
        if br.status == 'pending':
            br.status = 'running'
            br.started_at = moscow_now()
            if (br.total_planned or 0) <= 0:
                br.total_planned = _count_linked_student_targets()
            db.session.commit()

        rows = _linked_student_chat_targets_after_cursor(br.cursor_last_user_id, _BATCH)
        if not rows:
            br.status = 'completed'
            br.completed_at = moscow_now()
            db.session.commit()
            return {'ok': True, 'done': True, 'sent_ok': br.sent_ok, 'sent_failed': br.sent_failed}

        for uid, chat_id in rows:
            br.cursor_last_user_id = int(uid)
            try:
                cid = int(chat_id)
            except (TypeError, ValueError):
                br.sent_failed += 1
                br.updated_at = moscow_now()
                db.session.commit()
                continue
            ok = False
            try:
                if (br.photo_url or '').strip():
                    r = send_telegram_photo(
                        cid,
                        br.photo_url.strip(),
                        caption=(br.message_text or '')[:1024] or None,
                        parse_mode=None,
                    )
                else:
                    r = send_telegram_message(cid, br.message_text or '', parse_mode=None)
                ok = bool(r and r.get('ok'))
            except Exception as send_err:
                logger.warning('broadcast %s send to %s failed: %s', broadcast_id, cid, send_err)
            if ok:
                br.sent_ok += 1
            else:
                br.sent_failed += 1
            br.updated_at = moscow_now()
            db.session.commit()
            time.sleep(_INTER_MESSAGE_SLEEP)

        process_telegram_broadcast_batch.delay(broadcast_id)
        return {'ok': True, 'continued': True, 'batch': len(rows)}
    except Exception as e:
        logger.error('process_telegram_broadcast_batch %s: %s', broadcast_id, e, exc_info=True)
        try:
            br = TelegramBroadcast.query.get(broadcast_id)
            if br:
                br.status = 'failed'
                br.error_message = str(e)[:2000]
                br.updated_at = moscow_now()
                db.session.commit()
        except Exception:
            db.session.rollback()
        try:
            self.retry(exc=e, countdown=15)
        except Exception:
            return {'ok': False, 'error': str(e)}
