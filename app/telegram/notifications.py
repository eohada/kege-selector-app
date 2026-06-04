"""
Telegram notifications triggered by Flask / Celery events.

All send_* functions are synchronous (urllib) — safe to call from Flask
request handlers, Celery tasks, or background threads without the bot's asyncio loop.
"""
from __future__ import annotations

import html
import json
import logging
import os
import urllib.request
import urllib.error
from typing import Optional

from sqlalchemy import text
from app.telegram.config import APP_URL, BOT_TOKEN
from app.telegram.db import get_session, close_session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Low-level senders
# ---------------------------------------------------------------------------

def _bot_token() -> str | None:
    return BOT_TOKEN or None


def _tg_post(method: str, payload: dict, timeout: int = 10) -> Optional[dict]:
    """Generic Telegram Bot API POST."""
    token = _bot_token()
    if not token:
        logger.warning('_tg_post: no bot token configured')
        return None
    url = f'https://api.telegram.org/bot{token}/{method}'
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        logger.error('Telegram %s HTTP %s for payload chat=%s: %s', method, e.code, payload.get('chat_id'), body[:300])
        return None
    except Exception as e:
        logger.error('Telegram %s failed: %s', method, e)
        return None


def send_telegram_message(
    chat_id: int,
    text_body: str,
    parse_mode: str | None = 'HTML',
    reply_markup: dict | None = None,
    disable_web_page_preview: bool = True,
) -> Optional[dict]:
    """Send a text message."""
    payload: dict = {
        'chat_id': chat_id,
        'text': text_body,
        'disable_web_page_preview': disable_web_page_preview,
    }
    if parse_mode:
        payload['parse_mode'] = parse_mode
    if reply_markup:
        payload['reply_markup'] = reply_markup
    return _tg_post('sendMessage', payload)


def send_telegram_photo(
    chat_id: int,
    photo_url: str | None = None,
    file_id: str | None = None,
    caption: str | None = None,
    parse_mode: str | None = 'HTML',
    reply_markup: dict | None = None,
) -> Optional[dict]:
    """Send a photo by URL or file_id."""
    photo = file_id or photo_url
    if not photo:
        logger.warning('send_telegram_photo: no photo_url or file_id provided')
        return None
    payload: dict = {'chat_id': chat_id, 'photo': photo}
    if caption:
        payload['caption'] = caption
    if parse_mode:
        payload['parse_mode'] = parse_mode
    if reply_markup:
        payload['reply_markup'] = reply_markup
    return _tg_post('sendPhoto', payload, timeout=20)


# ---------------------------------------------------------------------------
# Submission notifications
# ---------------------------------------------------------------------------

def notify_teacher_manual_review(submission_id: int) -> bool:
    """Уведомить автора задания о поступлении работы на ручную проверку."""
    from app.telegram.user_notify import user_allows_telegram_notification, get_profile_for_user

    session = get_session()
    try:
        row = session.execute(text("""
            SELECT s.submission_id, a.title, a.created_by_id,
                   st.name AS student_name, up.telegram_chat_id
            FROM "Submissions" s
            JOIN "Assignments" a  ON a.assignment_id = s.assignment_id
            JOIN "Students"    st ON st.student_id   = s.student_id
            JOIN "UserProfiles" up ON up.user_id     = a.created_by_id
            WHERE s.submission_id = :sid
        """), {'sid': submission_id}).fetchone()

        if not row:
            return False

        _, title, teacher_uid, student_name, chat_id = row
        if not chat_id:
            return False

        prof = get_profile_for_user(int(teacher_uid))
        if not user_allows_telegram_notification(prof, 'homework_submitted'):
            return False

        grade_url = f'{(APP_URL or "").rstrip("/")}/submissions/{submission_id}/grade'
        msg = (
            '📝 <b>Работа ожидает проверки</b>\n\n'
            f'📄 {_esc(title or "Без названия")}\n'
            f'👤 {_esc(student_name or "Ученик")}\n'
            f'\n🔗 {grade_url}'
        )
        markup = {'inline_keyboard': [[{'text': '✅ Проверить', 'url': grade_url}]]}
        result = send_telegram_message(int(chat_id), msg, reply_markup=markup)
        return bool(result and result.get('ok'))
    except Exception as e:
        logger.error('notify_teacher_manual_review error: %s', e, exc_info=True)
        return False
    finally:
        close_session(session)


def notify_submission_submitted_to_staff(submission_id: int) -> int:
    """Уведомить учителя и всех создателей о сдаче работы. Возвращает кол-во отправок."""
    from app.telegram.user_notify import user_allows_telegram_notification, get_profile_for_user

    session = get_session()
    sent = 0
    try:
        row = session.execute(text("""
            SELECT s.submission_id, a.title, a.created_by_id, st.name
            FROM "Submissions" s
            JOIN "Assignments" a ON a.assignment_id = s.assignment_id
            JOIN "Students"    st ON st.student_id   = s.student_id
            WHERE s.submission_id = :sid
        """), {'sid': submission_id}).fetchone()
        if not row:
            return 0
        _, title, teacher_uid, student_name = row

        admin_rows = session.execute(text(
            "SELECT id FROM \"Users\" WHERE role IN ('creator','chief_admin')"
        )).fetchall()
        admin_ids = [r[0] for r in admin_rows]

        base = (APP_URL or '').rstrip('/')
        grade_url = f'{base}/submissions/{submission_id}/grade' if base else ''
        msg = (
            '📤 <b>Работа сдана на проверку</b>\n\n'
            f'📄 {_esc(title or "Без названия")}\n'
            f'👤 {_esc(student_name or "Ученик")}\n'
        )
        if grade_url:
            msg += f'\n🔗 {grade_url}'
        markup = None
        if grade_url:
            markup = {'inline_keyboard': [[{'text': '✅ Открыть проверку', 'url': grade_url}]]}

        seen: set[int] = set()

        def _send(uid: int, kind: str | None) -> None:
            nonlocal sent
            p = get_profile_for_user(int(uid))
            if not p or not p.telegram_chat_id:
                return
            cid = int(p.telegram_chat_id)
            if cid in seen:
                return
            if not user_allows_telegram_notification(p, kind):
                return
            r = send_telegram_message(cid, msg, reply_markup=markup)
            if r and r.get('ok'):
                sent += 1
                seen.add(cid)

        if teacher_uid:
            _send(int(teacher_uid), 'homework_submitted')
        for aid in admin_ids:
            if teacher_uid and aid == int(teacher_uid):
                continue
            _send(int(aid), None)
        return sent
    except Exception as e:
        logger.error('notify_submission_submitted_to_staff: %s', e, exc_info=True)
        return sent
    finally:
        close_session(session)


def notify_student_graded(submission_id: int) -> bool:
    """Уведомить ученика о проверке/возврате работы."""
    from app.telegram.user_notify import notify_user_by_id

    session = get_session()
    try:
        row = session.execute(text("""
            SELECT a.title, st.user_id, s.status
            FROM "Submissions" s
            JOIN "Assignments" a ON a.assignment_id = s.assignment_id
            JOIN "Students"    st ON st.student_id   = s.student_id
            WHERE s.submission_id = :sid
        """), {'sid': submission_id}).fetchone()
        if not row:
            return False

        title, student_uid, status = row
        if not student_uid:
            return False

        status_map = {
            'GRADED':       '✅ Проверено',
            'RETURNED':     '↩️ На доработку',
        }
        status_text = status_map.get(status, f'Статус: {status}')
        view_url = f'{(APP_URL or "").rstrip("/")}/submissions/{submission_id}' if APP_URL else ''
        msg = f'📝 <b>{status_text}</b>\n\n📄 {_esc(title or "Работа")}\n'
        if view_url:
            msg += f'\n🔗 {view_url}'
        markup = None
        if view_url:
            markup = {'inline_keyboard': [[{'text': '📄 Посмотреть', 'url': view_url}]]}
        kind = 'homework_returned' if status == 'RETURNED' else 'homework_checked'
        return notify_user_by_id(int(student_uid), msg, kind=kind, reply_markup=markup)
    except Exception as e:
        logger.error('notify_student_graded: %s', e, exc_info=True)
        return False
    finally:
        close_session(session)


# ---------------------------------------------------------------------------
# Gradebook notification
# ---------------------------------------------------------------------------

def notify_new_gradebook_entry(
    *, student_user_id: int, student_id: int, entry_title: str, score_text: str,
) -> bool:
    """Новая запись в журнале оценок — уведомление ученику."""
    from app.telegram.user_notify import notify_user_by_id

    base = (APP_URL or '').rstrip('/')
    gb_url = f'{base}/student/{student_id}/gradebook' if base else ''
    msg = f'📒 <b>Новая запись в журнале</b>\n\n{_esc(entry_title or "Оценка")}\n{_esc(score_text or "")}\n'
    if gb_url:
        msg += f'\n🔗 {gb_url}'
    markup = None
    if gb_url:
        markup = {'inline_keyboard': [[{'text': '📒 Журнал', 'url': gb_url}]]}
    return notify_user_by_id(int(student_user_id), msg, kind='homework_checked', reply_markup=markup)


# ---------------------------------------------------------------------------
# Lesson notifications
# ---------------------------------------------------------------------------

def notify_lesson_started_for_lesson(lesson_id: int) -> None:
    """Уведомить ученика «урок начался» по lesson_id (вызывается после commit)."""
    try:
        from app.models import Lesson
        lesson = Lesson.query.get(lesson_id)
        if not lesson:
            return
        st = lesson.student
        if not st or not st.user_id:
            return
        notify_lesson_started_to_student(
            student_user_id=int(st.user_id),
            lesson_id=int(lesson.lesson_id),
            topic=lesson.topic or 'Занятие',
        )
    except Exception as e:
        logger.warning('notify_lesson_started_for_lesson %s: %s', lesson_id, e, exc_info=True)


def notify_lesson_started_to_student(*, student_user_id: int, lesson_id: int, topic: str) -> bool:
    """Урок переведён в статус in_progress — уведомление ученику."""
    from app.telegram.user_notify import notify_user_by_id

    base = (APP_URL or '').rstrip('/')
    room_url = f'{base}/lesson/{lesson_id}/classwork-tasks' if base else ''
    msg = f'▶️ <b>Урок начался</b>\n\n{_esc(topic or "Занятие")}\n'
    if room_url:
        msg += f'\n🔗 {room_url}'
    markup = None
    if room_url:
        markup = {'inline_keyboard': [[{'text': '🚪 В классную комнату', 'url': room_url}]]}
    return notify_user_by_id(int(student_user_id), msg, kind=None, reply_markup=markup)


# ---------------------------------------------------------------------------
# Subscription expiry notification
# ---------------------------------------------------------------------------

def notify_subscription_expiring(
    *, student_user_id: int, days_left: int, subscription_end: str,
) -> bool:
    """Подписка истекает — предупреждение ученику."""
    from app.telegram.user_notify import notify_user_by_id

    base = (APP_URL or '').rstrip('/')
    billing_url = f'{base}/billing' if base else ''

    if days_left == 0:
        head = '⚠️ <b>Подписка истекает сегодня!</b>'
    elif days_left == 1:
        head = '⚠️ <b>Подписка истекает завтра</b>'
    else:
        head = f'ℹ️ <b>Подписка истекает через {days_left} дн.</b>'

    msg = f'{head}\n\nДата окончания: {subscription_end}\n'
    if billing_url:
        msg += f'\n🔗 {billing_url}'
    markup = None
    if billing_url:
        markup = {'inline_keyboard': [[{'text': '💳 Продлить подписку', 'url': billing_url}]]}
    return notify_user_by_id(
        int(student_user_id), msg, kind='subscription_expiring', reply_markup=markup,
    )


# ---------------------------------------------------------------------------
# Bug report reply notification
# ---------------------------------------------------------------------------

def notify_bug_report_reply(*, student_chat_id: int, report_id: int, reply_text: str) -> bool:
    """Отправить ученику ответ на баг-репорт (прямой send, не через user_notify)."""
    msg = (
        f'💬 <b>Ответ от команды BooStudy</b>\n\n'
        f'📌 По репорту <b>#{report_id}</b>:\n\n'
        f'{_esc(reply_text)}'
    )
    result = send_telegram_message(int(student_chat_id), msg)
    return bool(result and result.get('ok'))


# ---------------------------------------------------------------------------
# Daily digest notification
# ---------------------------------------------------------------------------

def notify_daily_digest(*, student_user_id: int, lessons_today: list, pending_count: int) -> bool:
    """Утренний дайджест для ученика."""
    from app.telegram.user_notify import notify_user_by_id

    lines = ['☀️ <b>Доброе утро! Твой план на сегодня:</b>', '']

    if lessons_today:
        lines.append('<b>📅 Уроки:</b>')
        for lesson in lessons_today:
            time_str = lesson.get('time', '—')
            topic = _esc((lesson.get('topic') or 'Занятие')[:50])
            lines.append(f'  • {time_str} — {topic}')
        lines.append('')
    else:
        lines.append('📅 Уроков сегодня нет\n')

    if pending_count > 0:
        lines.append(f'📋 Незавершённых заданий: <b>{pending_count}</b>')
    else:
        lines.append('✅ Все задания выполнены!')

    base = (APP_URL or '').rstrip('/')
    if base:
        lines.append(f'\n🔗 {base}')

    msg = '\n'.join(lines)
    return notify_user_by_id(int(student_user_id), msg, kind='daily_digest')


# ---------------------------------------------------------------------------
# Submission status hook
# ---------------------------------------------------------------------------

def on_submission_status_changed(submission) -> None:
    """
    Hook вызывается при смене статуса Submission.
    Диспетчеризует нужное Telegram-уведомление.
    """
    from app.constants import SubmissionStatus

    sid = (
        getattr(submission, 'submission_id', None)
        or (submission.get('submission_id') if isinstance(submission, dict) else None)
    )
    status = (
        getattr(submission, 'status', None)
        or (submission.get('status') if isinstance(submission, dict) else None)
    )

    if not sid or not status:
        return
    if isinstance(status, str):
        status = status.strip().upper()

    if status == SubmissionStatus.NEEDS_MANUAL_REVIEW:
        try:
            notify_teacher_manual_review(sid)
        except Exception:
            logger.exception('on_submission_status_changed: notify_teacher_manual_review failed for %s', sid)

    elif status in (SubmissionStatus.SUBMITTED, SubmissionStatus.NEEDS_MANUAL_REVIEW):
        try:
            notify_submission_submitted_to_staff(sid)
        except Exception:
            logger.exception('on_submission_status_changed: notify_submission_submitted_to_staff failed for %s', sid)

    elif status in (SubmissionStatus.GRADED, SubmissionStatus.RETURNED):
        try:
            notify_student_graded(sid)
        except Exception:
            logger.exception('on_submission_status_changed: notify_student_graded failed for %s', sid)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _esc(value: str) -> str:
    return html.escape(str(value)) if value else ''


def _get_teacher_user_id(submission_id: int) -> Optional[int]:
    session = get_session()
    try:
        row = session.execute(text("""
            SELECT a.created_by_id FROM "Submissions" s
            JOIN "Assignments" a ON a.assignment_id = s.assignment_id
            WHERE s.submission_id = :sid
        """), {'sid': submission_id}).fetchone()
        return row[0] if row else None
    except Exception:
        return None
    finally:
        close_session(session)
