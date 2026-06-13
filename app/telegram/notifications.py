"""
Telegram notifications triggered by Flask / Celery events.

All send_* functions are synchronous (urllib) — safe to call from Flask
request handlers, Celery tasks, or background threads without the bot's asyncio loop.
"""
from __future__ import annotations

import html
import json
import logging
import urllib.request
import urllib.error
from typing import Optional

from sqlalchemy import text
from app.telegram.config import APP_URL, BOT_TOKEN, telegram_proxy_parts
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
    opener = urllib.request.build_opener()
    proxy = telegram_proxy_parts()
    if proxy:
        opener.add_handler(urllib.request.ProxyHandler({'http': proxy['url'], 'https': proxy['url']}))
    try:
        with opener.open(req, timeout=timeout) as resp:
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

def notify_lesson_started_for_lesson(lesson_id: int, *, actor_user_id: int | None = None) -> None:
    """Уведомить ученика и, если есть, преподавателя о старте урока."""
    try:
        from app.models import Lesson, UserProfile
        lesson = Lesson.query.get(lesson_id)
        if not lesson:
            return
        st = lesson.student
        if actor_user_id:
            prof = UserProfile.query.filter_by(user_id=int(actor_user_id)).first()
            if prof and prof.telegram_chat_id:
                teacher_name = ' '.join(part for part in [
                    getattr(st.user, 'first_name', None) if getattr(st, 'user', None) else None,
                    getattr(st.user, 'last_name', None) if getattr(st, 'user', None) else None,
                ] if part).strip() or getattr(st, 'name', None) or 'Ученик'
                lesson_topic = lesson.topic or 'Занятие'
                duration = f'{int(lesson.duration or 60)} мин'
                msg = (
                    '▶️ <b>Урок начался</b>\n\n'
                    f'👤 Ученик: {_esc(teacher_name)}\n'
                    f'📚 Тема: {_esc(lesson_topic)}\n'
                    f'⏱ Длительность: {duration}\n\n'
                    'Пришли ссылку на видеосозвон одним сообщением.\n'
                    'После этого я отправлю её ученику вместе с сообщением о начале урока.'
                )
                markup = {'inline_keyboard': [[{'text': '📎 Отправить ссылку', 'callback_data': f'lesson_call_link:{lesson.lesson_id}'}]]}
                send_telegram_message(int(prof.telegram_chat_id), msg, reply_markup=markup)
    except Exception as e:
        logger.warning('notify_lesson_started_for_lesson %s: %s', lesson_id, e, exc_info=True)


def notify_lesson_started_to_student(*, student_user_id: int, lesson_id: int, topic: str, room_url: str | None = None) -> bool:
    """Урок переведён в статус in_progress — уведомление ученику."""
    from app.telegram.user_notify import notify_user_by_id

    if room_url is None:
        base = (APP_URL or '').rstrip('/')
        room_url = f'{base}/lesson/{lesson_id}/classwork-tasks' if base else ''
    msg = f'▶️ <b>Урок начался</b>\n\n{_esc(topic or "Занятие")}\n'
    if room_url:
        msg += f'\n🔗 {room_url}'
    markup = None
    if room_url:
        markup = {'inline_keyboard': [[{'text': '🚪 В классную комнату', 'url': room_url}]]}
    return notify_user_by_id(int(student_user_id), msg, kind=None, reply_markup=markup)


def notify_lesson_finished_for_teacher(
    *,
    lesson_id: int,
    teacher_user_id: int | None = None,
    actor_chat_id: int | None = None,
) -> bool:
    """Попросить преподавателя оставить ДЗ после завершения урока."""
    from app.telegram.user_notify import user_allows_telegram_notification, get_profile_for_user
    from app.models import Lesson, UserProfile

    lesson = Lesson.query.get(int(lesson_id))
    if not lesson:
        return False

    st = lesson.student
    student_name = (
        getattr(st, 'name', None)
        or (
            f"{getattr(getattr(st, 'user', None), 'first_name', '')} {getattr(getattr(st, 'user', None), 'last_name', '')}".strip()
            if st and getattr(st, 'user', None) else None
        )
        or 'Ученик'
    )
    msg = (
        '✅ <b>Урок завершен</b>\n\n'
        f'👤 Ученик: <b>{_esc(student_name)}</b>\n'
        f'📚 Урок: <b>{_esc(lesson.topic or "Занятие")}</b>\n'
        f'⏱ Длительность: <b>{int(lesson.duration or 60)} мин</b>\n\n'
        'Напиши следующим сообщением, какое ДЗ нужно оставить ученику.\n'
        'Потом я спрошу, когда напомнить об этом.'
    )
    markup = {'inline_keyboard': [[{'text': '📝 Оставить ДЗ', 'callback_data': f'lesson_hw_note:{lesson.lesson_id}'}]]}

    targets: list[int] = []
    if teacher_user_id:
        profile = UserProfile.query.filter_by(user_id=int(teacher_user_id)).first()
        if profile and profile.telegram_chat_id:
            targets.append(int(profile.telegram_chat_id))
    elif actor_chat_id:
        targets.append(int(actor_chat_id))

    if not targets:
        # Фолбэк: всем создателям/админам с Telegram, если урок завершился автоматом.
        from app.models import User, UserProfile
        creator_rows = (
            User.query
            .join(UserProfile, UserProfile.user_id == User.id)
            .filter(UserProfile.telegram_chat_id.isnot(None))
            .filter(User.role.in_(('creator', 'chief_admin', 'tutor')))
            .all()
        )
        for creator in creator_rows:
            profile = get_profile_for_user(int(creator.id))
            if not profile or not user_allows_telegram_notification(profile, None):
                continue
            chat_id = getattr(profile, 'telegram_chat_id', None)
            if chat_id:
                targets.append(int(chat_id))

    sent = False
    for chat_id in dict.fromkeys(targets):
        result = send_telegram_message(int(chat_id), msg, reply_markup=markup)
        sent = bool(result and result.get('ok')) or sent
    return sent


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


def notify_lesson_reminder_response_to_creators(
    *,
    student_user_id: int,
    student_chat_id: int,
    student_username: str | None,
    student_first_name: str | None,
    student_last_name: str | None,
    lesson_id: int | None,
    lesson_topic: str | None,
    lesson_time: str | None,
    response_kind: str,
    response_label: str,
    original_text: str,
) -> int:
    """Сообщить создателям, как ученик ответил на напоминание."""
    from app.telegram.notifications import send_telegram_message
    from app.models import User, UserProfile

    username = (student_username or '').strip().lstrip('@')
    full_name = ' '.join(part for part in [student_first_name, student_last_name] if part).strip()
    if username:
        student_tag = f'@{username}'
    elif full_name:
        student_tag = full_name
    else:
        student_tag = f'chat_id {student_chat_id}'

    lesson_ref = f'#{lesson_id}' if lesson_id else '—'
    topic = (lesson_topic or 'Занятие').strip()
    time_line = f'🕐 Начало: <b>{_esc(lesson_time or "—")}</b>\n' if lesson_time else ''

    report = (
        '⏰ <b>Ответ на напоминание об уроке</b>\n\n'
        f'👤 Ученик: <b>{_esc(student_tag)}</b>\n'
        f'🆔 Платформа: <code>{int(student_user_id)}</code>\n'
        f'📚 Урок: <b>{_esc(lesson_ref)}</b>\n'
        f'📄 Тема: <b>{_esc(topic)}</b>\n'
        f'{time_line}'
        f'✅ Ответ: <b>{_esc(response_label)}</b>\n\n'
        '<b>Текст уведомления:</b>\n'
        f'<pre>{html.escape((original_text or "").strip())}</pre>'
    )

    recipients = (
        User.query
        .join(UserProfile, UserProfile.user_id == User.id)
        .filter(UserProfile.telegram_chat_id.isnot(None))
        .filter(User.role.in_(('creator', 'chief_admin')))
        .all()
    )

    sent = 0
    for creator in recipients:
        profile = UserProfile.query.filter_by(user_id=creator.id).first()
        chat_id = getattr(profile, 'telegram_chat_id', None)
        if not chat_id:
            continue
        try:
            result = send_telegram_message(int(chat_id), report)
            if result and result.get('ok'):
                sent += 1
        except Exception:
            logger.warning('lesson reminder response report failed creator_id=%s', creator.id, exc_info=True)
    return sent


def notify_lesson_balance_changed(
    *,
    student_user_id: int,
    before: int | None,
    after: int | None,
    reason: str | None = None,
    source: str = 'manual',
) -> bool:
    """
    Сообщить ученику об изменении баланса уроков и при необходимости о низком остатке.

    source:
      - manual: ручное изменение админом/создателем
      - lesson: списание после урока
      - tariff: назначение/продление тарифа
    """
    from app.telegram.user_notify import notify_user_by_id

    if after is None:
        return False

    before_val = int(before) if before is not None else None
    after_val = int(after)
    reason_text = (reason or '').strip()

    lines = ['📚 <b>Изменение количества уроков</b>', '']
    if before_val is None:
        lines.append(f'Было: <b>—</b>')
    else:
        lines.append(f'Было: <b>{before_val}</b>')
    lines.append(f'Стало: <b>{after_val}</b>')
    if reason_text:
        lines.append(f'Причина: {_esc(reason_text)}')
    if source == 'manual':
        lines.append('')
        lines.append('Это ручное изменение баланса.')

    extra_kind: str | None = None
    extra_text: str | None = None
    if after_val == 5:
        extra_kind = 'low_lessons'
        extra_text = '⚠️ <b>Внимание, на балансе осталось пять уроков.</b>'
    elif after_val == 1:
        extra_kind = 'low_lessons'
        extra_text = '⚠️ <b>На балансе остался один урок.</b>'
    elif after_val == 0:
        extra_kind = 'low_lessons'
        extra_text = '🚫 <b>Уроки на балансе закончились.</b>'
    elif before_val is not None and before_val >= 3 and after_val < 3:
        extra_kind = 'low_lessons'
        extra_text = '⚠️ <b>На балансе осталось меньше трех уроков.</b>'

    msg = '\n'.join(lines)
    ok = notify_user_by_id(int(student_user_id), msg, kind=None)
    if not ok:
        return False

    if extra_text:
        return notify_user_by_id(int(student_user_id), extra_text, kind=extra_kind)
    return True


def notify_teacher_homework_note_reminder(note_id: int) -> bool:
    """Напоминание преподавателю о сохраненной заметке по ДЗ."""
    from app.models import LessonTeacherHomeworkNote, UserProfile
    from app.telegram.user_notify import user_allows_telegram_notification

    note = LessonTeacherHomeworkNote.query.get(int(note_id))
    if not note or note.is_sent:
        return False

    profile = UserProfile.query.filter_by(user_id=int(note.teacher_user_id)).first()
    if not profile or not profile.telegram_chat_id or not user_allows_telegram_notification(profile, None):
        return False

    lesson = note.lesson
    student_name = getattr(lesson.student, 'name', None) if lesson and lesson.student else 'Ученик'
    msg = (
        '⏰ <b>Напоминание по ДЗ после урока</b>\n\n'
        f'👤 Ученик: <b>{_esc(student_name or "Ученик")}</b>\n'
        f'📚 Урок: <b>{_esc(lesson.topic or "Занятие" if lesson else "Занятие")}</b>\n\n'
        '<b>Что нужно скинуть:</b>\n'
        f'<pre>{html.escape((note.homework_text or "").strip())}</pre>'
    )
    if lesson:
        try:
            from app.utils.lesson_time import lesson_storage_to_local
            from app.utils.datetime_utc import effective_timezone_name
            tz_name = effective_timezone_name(getattr(lesson.student, 'user', None)) if getattr(lesson.student, 'user', None) else 'Europe/Moscow'
            dt_local = lesson_storage_to_local(lesson.lesson_date, tz_name)
            if dt_local:
                msg += f'\n🕐 Урок: {dt_local.strftime("%d.%m.%Y %H:%M")}'
        except Exception:
            pass

    result = send_telegram_message(int(profile.telegram_chat_id), msg)
    if result and result.get('ok'):
        note.is_sent = True
        from core.db_models import moscow_now
        note.reminder_sent_at = moscow_now()
        return True
    return False


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
