"""
Telegram notifications triggered by Flask / Celery events.

These functions are *synchronous* (use urllib) so they can be called from
Flask request handlers, Celery tasks, or background workers without needing
the bot's asyncio event loop.
"""
import json
import logging
import os
import urllib.request
import urllib.error
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Low-level: send a Telegram message via Bot API (sync, no deps)
# ---------------------------------------------------------------------------

def send_telegram_message(
    chat_id: int,
    text_body: str,
    parse_mode: str | None = 'HTML',
    reply_markup: dict | None = None,
    disable_web_page_preview: bool = True,
) -> Optional[dict]:
    """Send a message through the Telegram Bot API (blocking HTTP call)."""
    token = os.environ.get('BOT_TOKEN') or os.environ.get('TELEGRAM_BOT_TOKEN')
    if not token:
        logger.warning('send_telegram_message: no bot token configured')
        return None

    url = f'https://api.telegram.org/bot{token}/sendMessage'
    payload: dict = {
        'chat_id': chat_id,
        'text': text_body,
        'disable_web_page_preview': disable_web_page_preview,
    }
    if parse_mode:
        payload['parse_mode'] = parse_mode
    if reply_markup:
        payload['reply_markup'] = reply_markup

    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url, data=data, headers={'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        logger.error('Telegram API HTTP %s for chat %s: %s', e.code, chat_id, body[:300])
        return None
    except Exception as e:
        logger.error('send_telegram_message to %s failed: %s', chat_id, e)
        return None


def send_telegram_photo(
    chat_id: int,
    photo_url: str,
    caption: str | None = None,
    parse_mode: str | None = 'HTML',
    reply_markup: dict | None = None,
) -> Optional[dict]:
    """Отправить фото по URL (Telegram скачивает сам)."""
    token = os.environ.get('BOT_TOKEN') or os.environ.get('TELEGRAM_BOT_TOKEN')
    if not token:
        logger.warning('send_telegram_photo: no bot token configured')
        return None

    url = f'https://api.telegram.org/bot{token}/sendPhoto'
    payload: dict = {
        'chat_id': chat_id,
        'photo': photo_url,
    }
    if parse_mode:
        payload['parse_mode'] = parse_mode
    if caption:
        payload['caption'] = caption
    if reply_markup:
        payload['reply_markup'] = reply_markup

    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url, data=data, headers={'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        logger.error('Telegram sendPhoto HTTP %s for chat %s: %s', e.code, chat_id, body[:300])
        return None
    except Exception as e:
        logger.error('send_telegram_photo to %s failed: %s', chat_id, e)
        return None


# ---------------------------------------------------------------------------
# High-level notification helpers
# ---------------------------------------------------------------------------

def notify_teacher_manual_review(submission_id: int) -> bool:
    """
    Notify the teacher that a submission needs manual review.

    Looks up the assignment's creator, finds their Telegram chat_id,
    and sends a message with a direct link to the grading page.

    Returns True if the message was sent successfully.
    """
    from urep_bot.db import get_session, close_session
    from urep_bot.config import APP_URL

    session = get_session()
    try:
        row = session.execute(text("""
            SELECT s.submission_id,
                   a.title,
                   a.created_by_id,
                   st.name  AS student_name,
                   up.telegram_chat_id
            FROM "Submissions" s
            JOIN "Assignments" a  ON a.assignment_id = s.assignment_id
            JOIN "Students"    st ON st.student_id   = s.student_id
            JOIN "UserProfiles" up ON up.user_id     = a.created_by_id
            WHERE s.submission_id = :sid
        """), {'sid': submission_id}).fetchone()

        if not row:
            logger.warning('notify_teacher_manual_review: submission %s not found', submission_id)
            return False

        _, title, teacher_uid, student_name, chat_id = row
        if not chat_id:
            logger.info(
                'notify_teacher_manual_review: teacher %s has no telegram_chat_id', teacher_uid,
            )
            return False

        grade_url = f'{APP_URL.rstrip("/")}/submissions/{submission_id}/grade' if APP_URL else ''
        msg = (
            '📝 <b>Работа ожидает проверки</b>\n\n'
            f'📄 {_esc(title or "Без названия")}\n'
            f'👤 {_esc(student_name or "Ученик")}\n'
        )
        if grade_url:
            msg += f'\n🔗 {grade_url}'

        reply_markup = None
        if grade_url:
            reply_markup = {
                'inline_keyboard': [[{
                    'text': '✅ Проверить',
                    'url': grade_url,
                }]],
            }

        from app.telegram.user_notify import user_allows_telegram_notification, get_profile_for_user

        prof = get_profile_for_user(int(teacher_uid))
        if not user_allows_telegram_notification(prof, 'homework_submitted'):
            return False

        result = send_telegram_message(int(chat_id), msg, reply_markup=reply_markup)
        return result is not None and result.get('ok', False)
    except Exception as e:
        logger.error('notify_teacher_manual_review error: %s', e, exc_info=True)
        return False
    finally:
        close_session(session)


def notify_submission_submitted_to_staff(submission_id: int) -> int:
    """
    Учитель (автор работы) и создатели/chief_admin получают уведомление о сдаче (статус SUBMITTED).
    Возвращает число успешных отправок.
    """
    from urep_bot.db import get_session, close_session
    from urep_bot.config import APP_URL
    from app.telegram.user_notify import user_allows_telegram_notification, get_profile_for_user

    session = get_session()
    sent = 0
    try:
        row = session.execute(text("""
            SELECT s.submission_id,
                   a.title,
                   a.created_by_id,
                   st.name AS student_name
            FROM "Submissions" s
            JOIN "Assignments" a ON a.assignment_id = s.assignment_id
            JOIN "Students" st ON st.student_id = s.student_id
            WHERE s.submission_id = :sid
        """), {'sid': submission_id}).fetchone()
        if not row:
            return 0
        _, title, teacher_uid, student_name = row
        admin_rows = session.execute(text("""
            SELECT id FROM "Users" WHERE role IN ('creator', 'chief_admin')
        """)).fetchall()
        admin_ids = [r[0] for r in admin_rows] if admin_rows else []

        base = (APP_URL or '').rstrip('/')
        grade_url = f'{base}/submissions/{submission_id}/grade' if base else ''
        msg = (
            '📤 <b>Работа сдана на проверку</b>\n\n'
            f'📄 {_esc(title or "Без названия")}\n'
            f'👤 {_esc(student_name or "Ученик")}\n'
        )
        if grade_url:
            msg += f'\n🔗 {grade_url}'
        reply_markup = None
        if grade_url:
            reply_markup = {
                'inline_keyboard': [[{'text': '✅ Открыть проверку', 'url': grade_url}]],
            }

        seen_chats: set[int] = set()

        def _send_to_user(uid: int, kind: str | None) -> None:
            nonlocal sent
            if not uid:
                return
            p = get_profile_for_user(int(uid))
            if not p or not p.telegram_chat_id:
                return
            cid = int(p.telegram_chat_id)
            if cid in seen_chats:
                return
            if kind and not user_allows_telegram_notification(p, kind):
                return
            if not kind and not user_allows_telegram_notification(p, None):
                return
            r = send_telegram_message(cid, msg, reply_markup=reply_markup)
            if r and r.get('ok'):
                sent += 1
                seen_chats.add(cid)

        if teacher_uid:
            _send_to_user(int(teacher_uid), 'homework_submitted')

        for aid in admin_ids:
            if teacher_uid and aid == teacher_uid:
                continue
            _send_to_user(int(aid), None)

        return sent
    except Exception as e:
        logger.error('notify_submission_submitted_to_staff error: %s', e, exc_info=True)
        return sent
    finally:
        close_session(session)


def notify_student_graded(submission_id: int) -> bool:
    """Notify a student that their submission has been graded (с учётом настроек профиля)."""
    from urep_bot.db import get_session, close_session
    from urep_bot.config import APP_URL
    from app.telegram.user_notify import notify_user_by_id

    session = get_session()
    try:
        row = session.execute(text("""
            SELECT a.title,
                   st.user_id,
                   s.status
            FROM "Submissions" s
            JOIN "Assignments" a  ON a.assignment_id = s.assignment_id
            JOIN "Students"    st ON st.student_id   = s.student_id
            WHERE s.submission_id = :sid
        """), {'sid': submission_id}).fetchone()

        if not row:
            return False

        title, student_uid, status = row
        if not student_uid:
            return False

        status_text = {
            'GRADED': '✅ Проверено',
            'RETURNED': '↩️ На доработку',
            'AUTO_GRADED': '🤖 Автопроверка завершена',
        }.get(status, f'Статус: {status}')

        view_url = f'{(APP_URL or "").rstrip("/")}/submissions' if APP_URL else ''
        msg = (
            f'📝 <b>{status_text}</b>\n\n'
            f'📄 {_esc(title or "Работа")}\n'
        )
        if view_url:
            msg += f'\n🔗 {view_url}'

        reply_markup = None
        if view_url:
            reply_markup = {
                'inline_keyboard': [[{
                    'text': '📄 Посмотреть',
                    'url': view_url,
                }]],
            }
        kind = 'homework_returned' if status == 'RETURNED' else 'homework_checked'
        return notify_user_by_id(int(student_uid), msg, kind=kind, reply_markup=reply_markup)
    except Exception as e:
        logger.error('notify_student_graded error: %s', e, exc_info=True)
        return False
    finally:
        close_session(session)


def notify_new_gradebook_entry(*, student_user_id: int, student_id: int, entry_title: str, score_text: str) -> bool:
    """Новая запись в журнале оценок — уведомление ученику."""
    from urep_bot.config import APP_URL
    from app.telegram.user_notify import notify_user_by_id

    base = (APP_URL or '').rstrip('/')
    gb_url = f'{base}/student/{student_id}/gradebook' if base else ''
    msg = (
        '📒 <b>Новая запись в журнале</b>\n\n'
        f'{_esc(entry_title or "Оценка")}\n'
        f'{_esc(score_text or "")}\n'
    )
    if gb_url:
        msg += f'\n🔗 {gb_url}'
    reply_markup = None
    if gb_url:
        reply_markup = {'inline_keyboard': [[{'text': '📒 Журнал', 'url': gb_url}]]}
    return notify_user_by_id(
        int(student_user_id), msg, kind='homework_checked', reply_markup=reply_markup,
    )


def notify_lesson_started_for_lesson(lesson_id: int) -> None:
    """Отправить ученику уведомление «урок начался» по id урока (после commit)."""
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
    """Урок переведён в in_progress — ученик."""
    from urep_bot.config import APP_URL
    from app.telegram.user_notify import notify_user_by_id

    base = (APP_URL or '').rstrip('/')
    room_url = f'{base}/lesson/{lesson_id}/classwork-tasks' if base else ''
    msg = (
        '▶️ <b>Урок начался</b>\n\n'
        f'{_esc(topic or "Занятие")}\n'
    )
    if room_url:
        msg += f'\n🔗 {room_url}'
    reply_markup = None
    if room_url:
        reply_markup = {'inline_keyboard': [[{'text': '🚪 В классную комнату', 'url': room_url}]]}
    # kind=None: только глобальный переключатель — старт урока важнее тематических «напоминаний».
    return notify_user_by_id(
        int(student_user_id), msg, kind=None, reply_markup=reply_markup,
    )


# ---------------------------------------------------------------------------
# Event hook — call from Flask route / signal / Celery task
# ---------------------------------------------------------------------------

def on_submission_status_changed(submission) -> None:
    """
    Hook called when a Submission's status changes.

    Dispatches the appropriate Telegram notification.
    Can be invoked from a Flask ``after_commit`` signal or directly.

    ``submission`` can be either a SQLAlchemy model instance (with
    ``.submission_id`` and ``.status``) or a plain dict.
    """
    from app.constants import SubmissionStatus

    sid = getattr(submission, 'submission_id', None) or (submission.get('submission_id') if isinstance(submission, dict) else None)
    status = getattr(submission, 'status', None) or (submission.get('status') if isinstance(submission, dict) else None)

    if not sid or not status:
        return

    if isinstance(status, str):
        status = status.strip().upper()

    if status == SubmissionStatus.NEEDS_MANUAL_REVIEW:
        try:
            notify_teacher_manual_review(sid)
        except Exception:
            logger.exception('on_submission_status_changed: notify_teacher_manual_review failed for %s', sid)

        try:
            from app.tasks.notifications import send_notification_task
            send_notification_task.delay(
                user_id=_get_teacher_user_id(sid),
                message=f'Работа #{sid} ожидает ручной проверки',
                notification_type='submission',
            )
        except Exception:
            pass

    elif status in (SubmissionStatus.SUBMITTED, SubmissionStatus.LATE):
        try:
            notify_submission_submitted_to_staff(sid)
        except Exception:
            logger.exception('on_submission_status_changed: notify_submission_submitted_to_staff failed for %s', sid)

    elif status in (SubmissionStatus.GRADED, SubmissionStatus.RETURNED, SubmissionStatus.AUTO_GRADED):
        try:
            notify_student_graded(sid)
        except Exception:
            logger.exception('on_submission_status_changed: notify_student_graded failed for %s', sid)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _esc(value: str) -> str:
    """HTML-escape for Telegram messages."""
    import html
    return html.escape(str(value)) if value else ''


def _get_teacher_user_id(submission_id: int) -> Optional[int]:
    """Resolve the teacher (Assignment.created_by_id) for a submission."""
    from urep_bot.db import get_session, close_session

    session = get_session()
    try:
        row = session.execute(text("""
            SELECT a.created_by_id
            FROM "Submissions" s
            JOIN "Assignments" a ON a.assignment_id = s.assignment_id
            WHERE s.submission_id = :sid
        """), {'sid': submission_id}).fetchone()
        return row[0] if row else None
    except Exception:
        return None
    finally:
        close_session(session)
