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
    parse_mode: str = 'HTML',
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
        'parse_mode': parse_mode,
        'disable_web_page_preview': disable_web_page_preview,
    }
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

        grade_url = f'{APP_URL}/submission/{submission_id}/grade' if APP_URL else ''
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

        result = send_telegram_message(int(chat_id), msg, reply_markup=reply_markup)
        return result is not None and result.get('ok', False)
    except Exception as e:
        logger.error('notify_teacher_manual_review error: %s', e, exc_info=True)
        return False
    finally:
        close_session(session)


def notify_student_graded(submission_id: int) -> bool:
    """Notify a student that their submission has been graded."""
    from urep_bot.db import get_session, close_session
    from urep_bot.config import APP_URL

    session = get_session()
    try:
        row = session.execute(text("""
            SELECT a.title,
                   st.name,
                   st.user_id,
                   up.telegram_chat_id,
                   s.status
            FROM "Submissions" s
            JOIN "Assignments" a  ON a.assignment_id = s.assignment_id
            JOIN "Students"    st ON st.student_id   = s.student_id
            JOIN "UserProfiles" up ON up.user_id     = st.user_id
            WHERE s.submission_id = :sid
        """), {'sid': submission_id}).fetchone()

        if not row:
            return False

        title, student_name, student_uid, chat_id, status = row
        if not chat_id:
            return False

        status_text = {
            'GRADED': '✅ Проверено',
            'RETURNED': '↩️ На доработку',
            'AUTO_GRADED': '🤖 Автопроверка завершена',
        }.get(status, f'Статус: {status}')

        view_url = f'{APP_URL}/submissions' if APP_URL else ''
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

        result = send_telegram_message(int(chat_id), msg, reply_markup=reply_markup)
        return result is not None and result.get('ok', False)
    except Exception as e:
        logger.error('notify_student_graded error: %s', e, exc_info=True)
        return False
    finally:
        close_session(session)


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
