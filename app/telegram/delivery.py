"""Durable Telegram outbox: idempotent enqueue, retry and recovery."""
from datetime import timedelta
import hashlib
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from core.db_models import TelegramDelivery, UserNotification, UserProfile, db, utc_now
from app.telegram.config import is_delivery_permitted
from app.telegram.notifications import send_telegram_message, send_telegram_photo
from app.telegram.user_notify import (
    _KIND_TO_ATTR, _QUIET_HOURS_BYPASS, _in_quiet_hours,
    normalize_notification_kind, is_notification_enabled_for_user,
)

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5
RETRY_DELAYS = (60, 300, 900, 3600, 21600)


def make_dedupe_key(user_id, text, kind=None, notification_id=None):
    raw = json.dumps([int(user_id), normalize_notification_kind(kind), text or '', notification_id], ensure_ascii=False, separators=(',', ':'))
    return 'telegram:%s' % hashlib.sha256(raw.encode()).hexdigest()


def enqueue_delivery(
    user_id,
    text,
    *,
    kind=None,
    notification_id=None,
    priority='normal',
    dedupe_key=None,
    reply_markup=None,
    photo_url=None,
    caption=None,
    meta=None,
    lesson_id=None,
    student_id=None,
):
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
    if meta:
        payload['meta'] = meta
    if lesson_id is not None:
        payload['lesson_id'] = int(lesson_id)
    if student_id is not None:
        payload['student_id'] = int(student_id)

    row = TelegramDelivery(
        user_id=int(user_id),
        notification_id=notification_id,
        telegram_chat_id=getattr(profile, 'telegram_chat_id', None),
        kind=kind,
        payload=payload,
        priority=priority,
        dedupe_key=dedupe_key,
    )
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
    from app.telegram.config import is_kill_switch_active
    if is_kill_switch_active():
        logger.info('telegram_delivery_claim_suppressed_by_emergency_kill_switch')
        return []

    now = utc_now()
    query = (
        TelegramDelivery.query
        .filter(TelegramDelivery.status.in_(['pending', 'retry']), TelegramDelivery.next_attempt_at <= now)
        .order_by(TelegramDelivery.priority.desc(), TelegramDelivery.created_at.asc())
    )
    # SQLite does not support FOR UPDATE SKIP LOCKED
    if db.engine.dialect.name != 'sqlite':
        query = query.with_for_update(skip_locked=True)

    rows = query.limit(int(limit)).all()
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
    elif status == 'simulated':
        row.sent_at = utc_now()
        if row.notification_id:
            n = db.session.get(UserNotification, row.notification_id)
            if n:
                n.telegram_sent = False
    db.session.commit()
    logger.info('telegram_delivery_finished delivery_id=%s status=%s attempts=%s', row.delivery_id, status, row.attempt_count)


def validate_delivery_freshness(row: TelegramDelivery) -> tuple[bool, str | None]:
    """Verify event validity and pre-send object state before dispatching.

    Enforces managed event validity policies:
    1. Check expires_at (if explicitly provided in payload or payload['meta']).
    2. Check lesson state (if lesson_id present: lesson exists, not cancelled, reminder not in past).
    3. Check submission state (if submission_id present: submission exists, not already graded for review alerts).
    4. Check family tie state (if student-specific notification to parent: tie exists and is confirmed).
    """
    now = utc_now()
    payload = row.payload or {}
    meta = payload.get('meta') or {}

    # 1. Check explicit expiration timestamp
    expires_at_raw = payload.get('expires_at') or meta.get('expires_at')
    if expires_at_raw:
        try:
            if isinstance(expires_at_raw, (int, float)):
                exp_dt = datetime.fromtimestamp(expires_at_raw, tz=timezone.utc)
            elif isinstance(expires_at_raw, str):
                from app.utils.datetime_utc import coerce_to_utc
                exp_dt = coerce_to_utc(expires_at_raw)
            else:
                exp_dt = expires_at_raw
            if exp_dt and now > exp_dt:
                return False, 'expired_by_policy'
        except Exception:
            pass

    # 2. Re-validate Lesson object state
    lesson_id = payload.get('lesson_id') or meta.get('lesson_id')
    if lesson_id is not None:
        try:
            from core.db_models import Lesson
            lesson = db.session.get(Lesson, int(lesson_id))
            if not lesson:
                return False, 'lesson_not_found'
            if getattr(lesson, 'status', None) == 'cancelled' and row.kind in ('lesson_reminder', 'lesson_scheduled', 'lesson_rescheduled'):
                return False, 'lesson_cancelled'
            if row.kind in ('lesson_reminder', 'lesson_scheduled', 'lesson_rescheduled'):
                l_date = getattr(lesson, 'lesson_date', None)
                if l_date is not None:
                    from app.utils.datetime_utc import coerce_to_utc
                    l_dt = coerce_to_utc(l_date)
                    if l_dt and now > l_dt:
                        return False, 'lesson_already_started'
        except Exception as e:
            logger.debug('Error checking lesson state for delivery %s: %s', row.delivery_id, e)

    # 3. Re-validate Submission object state
    submission_id = payload.get('submission_id') or meta.get('submission_id')
    if submission_id is not None:
        try:
            from core.db_models import Submission
            sub = db.session.get(Submission, int(submission_id))
            if not sub:
                return False, 'submission_not_found'
            if row.kind in ('teacher_homework_submitted', 'homework_submitted', 'review_queue'):
                sub_status = str(getattr(sub, 'status', '')).upper()
                if sub_status in ('CHECKED', 'GRADED', 'COMPLETED') or getattr(sub, 'graded_at', None) is not None:
                    return False, 'submission_already_graded'
        except Exception as e:
            logger.debug('Error checking submission state for delivery %s: %s', row.delivery_id, e)

    # 4. Re-validate FamilyTie state
    student_id = payload.get('student_id') or meta.get('student_id')
    if student_id and row.user_id != int(student_id):
        try:
            from app.models import FamilyTie
            tie = FamilyTie.query.filter_by(parent_id=row.user_id, student_id=int(student_id), is_confirmed=True).first()
            if not tie:
                return False, 'family tie unconfirmed or revoked'
        except Exception as e:
            logger.debug('Error checking family tie for delivery %s: %s', row.delivery_id, e)

    # 5. Validity policies: deferred deliveries (quiet hours, scheduled retry) must never expire prematurely
    if row.next_attempt_at:
        from app.utils.datetime_utc import coerce_to_utc
        next_att = coerce_to_utc(row.next_attempt_at)
        if next_att and next_att > now:
            return True, None

    # Transient reminders without a lesson object expire after 24h
    if row.kind == 'lesson_reminder' and lesson_id is None and row.created_at:
        try:
            from app.utils.datetime_utc import coerce_to_utc
            c_dt = coerce_to_utc(row.created_at)
            if c_dt and (now - c_dt).total_seconds() > 24 * 3600:
                return False, 'expired_by_policy'
        except Exception:
            pass

    return True, None


def deliver_one(delivery_id):
    row = db.session.get(TelegramDelivery, delivery_id)
    if not row or row.status != 'processing':
        return {'ok': False, 'status': 'skipped'}
    direct_chat_id = (row.payload or {}).get('direct_chat_id')
    profile = UserProfile.query.filter_by(user_id=row.user_id).first()
    if not direct_chat_id:
        chat_id = getattr(profile, 'telegram_chat_id', None)
        if not chat_id:
            _finish(row, 'cancelled', 'telegram chat is not linked')
            return {'ok': False, 'status': 'cancelled'}
    else:
        chat_id = int(direct_chat_id)

    if not direct_chat_id and not getattr(profile, 'telegram_notifications_enabled', False):
        _finish(row, 'cancelled', 'telegram notifications disabled')
        return {'ok': False, 'status': 'cancelled'}

    # Check if the user previously blocked the bot and hasn't unblocked (/start) yet
    if not direct_chat_id and getattr(profile, 'telegram_blocked_at', None) is not None:
        _finish(row, 'failed', 'bot blocked by user (awaiting user unblock /start)')
        return {'ok': False, 'status': 'failed', 'reason': 'bot_blocked'}

    # Verify event validity and pre-send object state (lesson cancelled, tie revoked, etc.)
    is_valid, cancel_reason = validate_delivery_freshness(row)
    if not is_valid:
        logger.info('telegram_delivery_invalidated delivery_id=%s reason=%s', row.delivery_id, cancel_reason)
        _finish(row, 'cancelled', f'invalidated: {cancel_reason}')
        return {'ok': False, 'status': 'cancelled', 'reason': cancel_reason}

    # Respect granular user preferences and role-based opt-outs
    meta = (row.payload or {}).get('meta') or {}
    role = meta.get('recipient_role') or meta.get('role')
    if not direct_chat_id and not is_notification_enabled_for_user(row.user_id, role=role, kind=row.kind):
        _finish(row, 'cancelled', f'notification kind disabled by user preference: {row.kind} (role: {role})')
        return {'ok': False, 'status': 'cancelled', 'reason': 'disabled_by_preference'}

    if not direct_chat_id and row.kind not in _QUIET_HOURS_BYPASS and _in_quiet_hours(profile):
        row.status = 'retry'
        row.next_attempt_at = _quiet_release(profile)
        db.session.commit()
        return {'ok': False, 'status': 'deferred_quiet_hours'}

    # Emergency Kill Switch guard: safely pause delivery and keep in queue without finishing
    from app.telegram.config import is_kill_switch_active
    if is_kill_switch_active():
        logger.warning('telegram_delivery_paused_by_emergency_kill_switch delivery_id=%s', row.delivery_id)
        row.status = 'retry'
        row.next_attempt_at = utc_now() + timedelta(seconds=60)
        row.last_error = 'paused: emergency kill switch active'
        db.session.commit()
        return {'ok': False, 'status': 'paused', 'paused': True}

    # Safety guard: Dev allowlist enforcement
    if not is_delivery_permitted(chat_id, user_id=row.user_id):
        logger.info('telegram_delivery_dev_dry_run delivery_id=%s user_id=%s chat_id=%s (simulated mode)', row.delivery_id, row.user_id, chat_id)
        _finish(row, 'simulated', error='[dev_dry_run] delivered simulated (dry-run mode active)')
        return {'ok': True, 'status': 'simulated', 'dry_run': True}

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
            if code == 403 or (isinstance(description, str) and 'blocked' in description.lower()):
                logger.warning('telegram_user_blocked_bot user_id=%s chat_id=%s: %s', row.user_id, chat_id, description)
                if profile:
                    profile.telegram_blocked_at = utc_now()
                    db.session.commit()
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


def invalidate_pending_lesson_deliveries(lesson_id: int, reason: str = 'lesson_rescheduled') -> int:
    """Cancels any pending or retrying deliveries for a given lesson (e.g. after reschedule or cancellation)."""
    deliveries = TelegramDelivery.query.filter(
        TelegramDelivery.status.in_(['pending', 'retry']),
        TelegramDelivery.kind.in_(['lesson_reminder', 'lesson_scheduled', 'lesson_rescheduled'])
    ).all()
    count = 0
    lid_str = str(lesson_id)
    for d in deliveries:
        payload = d.payload or {}
        p_lid = payload.get('lesson_id') or (payload.get('meta') or {}).get('lesson_id')
        if p_lid == lesson_id or (p_lid is None and lid_str in json.dumps(payload)):
            d.status = 'cancelled'
            d.last_error = f'invalidated: {reason}'
            count += 1
    if count:
        db.session.commit()
        logger.info('invalidated_lesson_deliveries lesson_id=%s count=%s reason=%s', lesson_id, count, reason)
    return count
