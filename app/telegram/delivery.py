"""Durable Telegram outbox: idempotent enqueue, retry and recovery."""
from datetime import timedelta
import hashlib
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from core.db_models import TelegramDelivery, UserNotification, UserProfile, db, utc_now
from app.telegram.notifications import send_telegram_message, send_telegram_photo
from app.telegram.user_notify import (
    _KIND_TO_ATTR, _QUIET_HOURS_BYPASS, _in_quiet_hours,
    normalize_notification_kind,
)

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5
RETRY_DELAYS = (60, 300, 900, 3600, 21600)


def make_dedupe_key(user_id, text, kind=None, notification_id=None):
    raw = json.dumps([int(user_id), normalize_notification_kind(kind), text or '', notification_id], ensure_ascii=False, separators=(',', ':'))
    return 'telegram:%s' % hashlib.sha256(raw.encode()).hexdigest()


def enqueue_delivery(user_id, text, *, kind=None, notification_id=None, priority='normal', dedupe_key=None, reply_markup=None, photo_url=None, caption=None):
    kind = normalize_notification_kind(kind) or 'generic'
    dedupe_key = dedupe_key or make_dedupe_key(user_id, text, kind, notification_id)
    existing = TelegramDelivery.query.filter_by(dedupe_key=dedupe_key).first()
    if existing:
        return existing
    profile = UserProfile.query.filter_by(user_id=int(user_id)).first()
    payload = {'text': text}
    if reply_markup:
        payload['reply_markup'] = reply_markup
    if photo_url:
        payload['photo_url'] = photo_url
        payload['caption'] = caption if caption is not None else text
    row = TelegramDelivery(user_id=int(user_id), notification_id=notification_id,
                           telegram_chat_id=getattr(profile, 'telegram_chat_id', None),
                           kind=kind, payload=payload, priority=priority,
                           dedupe_key=dedupe_key)
    try:
        with db.session.begin_nested():
            db.session.add(row)
            db.session.flush()
        return row
    except IntegrityError:
        # Another producer won the unique dedupe race. The savepoint keeps the
        # caller's outer transaction usable; return the canonical row.
        existing = TelegramDelivery.query.filter_by(dedupe_key=dedupe_key).first()
        if existing:
            return existing
        raise


def enqueue_direct_delivery(user_id, chat_id, text, *, kind='demo_lead', dedupe_key=None, reply_markup=None):
    """Queue a message to an explicit operational chat without using user preferences.

    This is used for server-owned destinations such as the demo lead inbox.
    The lead is already persisted before this function is called; a Telegram
    outage therefore cannot roll back or hide the lead.
    """
    dedupe_key = dedupe_key or make_dedupe_key(user_id, text, kind)
    row = enqueue_delivery(user_id, text, kind=kind, priority='high', dedupe_key=dedupe_key)
    row.telegram_chat_id = int(chat_id)
    row.payload = {
        'text': text,
        'direct_chat_id': int(chat_id),
        **({'reply_markup': reply_markup} if reply_markup else {}),
    }
    db.session.commit()
    return row


def claim_due_deliveries(limit=50):
    now = utc_now()
    rows = (TelegramDelivery.query
            .filter(TelegramDelivery.status.in_(['pending', 'retry']), TelegramDelivery.next_attempt_at <= now)
            .order_by(TelegramDelivery.priority.desc(), TelegramDelivery.created_at.asc())
            .with_for_update(skip_locked=True).limit(int(limit)).all())
    for row in rows:
        row.status = 'processing'
        row.processing_started_at = now
        row.last_attempt_at = now
        row.attempt_count = int(row.attempt_count or 0) + 1
    db.session.commit()
    logger.info('telegram_delivery_claimed count=%s limit=%s', len(rows), limit)
    return [row.delivery_id for row in rows]


def _quiet_release(profile):
    now = datetime.now(timezone.utc)
    start = getattr(profile, 'tg_quiet_hours_start', None)
    end = getattr(profile, 'tg_quiet_hours_end', None)
    if start is None or end is None:
        return now + timedelta(hours=1)
    release = now.replace(minute=0, second=0, microsecond=0)
    for _ in range(25):
        release += timedelta(hours=1)
        hour = release.hour
        quiet = (start <= hour < end) if start <= end else (hour >= start or hour < end)
        if not quiet:
            return release
    return now + timedelta(hours=1)


def _finish(row, status, error=None, next_attempt_at=None):
    row.status = status
    row.last_error = (str(error)[:1000] if error else None)
    if next_attempt_at:
        row.next_attempt_at = next_attempt_at
    if status == 'sent':
        row.sent_at = utc_now()
        if row.notification_id:
            n = db.session.get(UserNotification, row.notification_id)
            if n:
                n.telegram_sent = True
    db.session.commit()
    logger.info('telegram_delivery_finished delivery_id=%s status=%s attempts=%s', row.delivery_id, status, row.attempt_count)


def deliver_one(delivery_id):
    row = db.session.get(TelegramDelivery, delivery_id)
    if not row or row.status != 'processing':
        return {'ok': False, 'status': 'skipped'}
    direct_chat_id = (row.payload or {}).get('direct_chat_id')
    profile = UserProfile.query.filter_by(user_id=row.user_id).first()
    chat_id = int(direct_chat_id) if direct_chat_id else (getattr(profile, 'telegram_chat_id', None) or row.telegram_chat_id)
    if not chat_id:
        _finish(row, 'cancelled', 'telegram chat is not linked')
        return {'ok': False, 'status': 'cancelled'}
    if not direct_chat_id and not getattr(profile, 'telegram_notifications_enabled', False):
        _finish(row, 'cancelled', 'telegram notifications disabled')
        return {'ok': False, 'status': 'cancelled'}
    attr = _KIND_TO_ATTR.get(row.kind)
    if not direct_chat_id and attr and row.kind not in {'lesson_scheduled', 'lesson_reminder'} and not getattr(profile, attr, True):
        _finish(row, 'cancelled', 'notification kind disabled')
        return {'ok': False, 'status': 'cancelled'}
    if not direct_chat_id and row.kind not in _QUIET_HOURS_BYPASS and _in_quiet_hours(profile):
        row.status = 'retry'
        row.next_attempt_at = _quiet_release(profile)
        db.session.commit()
        return {'ok': False, 'status': 'deferred_quiet_hours'}
    try:
        if row.payload.get('photo_url'):
            result = send_telegram_photo(
                int(chat_id),
                row.payload.get('photo_url'),
                caption=row.payload.get('caption'),
                parse_mode='HTML',
            )
        else:
            result = send_telegram_message(
                int(chat_id),
                row.payload.get('text', ''),
                reply_markup=row.payload.get('reply_markup'),
            )
        if result and result.get('ok'):
            _finish(row, 'sent')
            return {'ok': True, 'status': 'sent'}
        code = (result or {}).get('error_code')
        description = (result or {}).get('description', 'telegram rejected message')
        retryable = code == 429 or (isinstance(code, int) and code >= 500)
        if not retryable:
            _finish(row, 'failed', description)
            return {'ok': False, 'status': 'failed'}
        raise RuntimeError(description)
    except Exception as exc:
        if row.attempt_count >= MAX_ATTEMPTS:
            _finish(row, 'failed', exc)
            return {'ok': False, 'status': 'failed'}
        delay = RETRY_DELAYS[min(row.attempt_count - 1, len(RETRY_DELAYS) - 1)]
        _finish(row, 'retry', exc, utc_now() + timedelta(seconds=delay))
        return {'ok': False, 'status': 'retry'}


def recover_stale_processing(timeout_minutes=10):
    cutoff = utc_now() - timedelta(minutes=timeout_minutes)
    rows = TelegramDelivery.query.filter_by(status='processing').filter(TelegramDelivery.processing_started_at < cutoff).all()
    for row in rows:
        row.status = 'retry'
        row.next_attempt_at = utc_now()
        row.last_error = 'recovered stale processing claim'
    db.session.commit()
    return len(rows)
