from __future__ import annotations

import html
import logging
from typing import Iterable
from datetime import timedelta

from app.models import db, User, Student, UserNotification, FamilyTie, Tasks, PendingAssignmentNotification, Lesson, moscow_now, BotAdmin

logger = logging.getLogger(__name__)

ASSIGNMENT_NOTIFY_DEBOUNCE_SECONDS = 300


def _get_student_user(student: Student) -> User | None:
    if not student:
        return None
    if getattr(student, 'user_id', None):
        u = User.query.get(student.user_id)
        if u and u.role == 'student':
            return u
    try:
        u = User.query.get(student.student_id)
        if u and u.role == 'student':
            return u
    except Exception:
        pass
    return None


def _get_parent_user_ids_for_student_user(student_user_id: int) -> list[int]:
    try:
        ties = FamilyTie.query.filter_by(student_id=student_user_id, is_confirmed=True).all()
        return [t.parent_id for t in ties if t and t.parent_id]
    except Exception as e:
        logger.warning(f"Failed to load FamilyTies for student_user_id={student_user_id}: {e}")
        return []


def notify_user(user_id: int, *, kind: str, title: str, body: str | None = None, link_url: str | None = None, meta: dict | None = None) -> None:
    n = UserNotification(
        user_id=user_id,
        kind=kind or 'generic',
        title=title,
        body=body,
        link_url=link_url,
        meta=meta,
    )
    db.session.add(n)

    # Mirror important in-app notifications to Telegram when the user has it enabled.
    # This keeps the platform notification model and Telegram delivery in sync.
    try:
        from app.tasks.telegram_dispatch import telegram_notify_user_task

        telegram_lines = [
            f'🔔 <b>{html.escape(str(title or "Уведомление"))}</b>',
        ]
        if body:
            telegram_lines.extend(['', html.escape(str(body))])
        if link_url:
            telegram_lines.extend(['', str(link_url)])
        telegram_text = '\n'.join(telegram_lines)
        telegram_notify_user_task.delay(int(user_id), telegram_text, kind)
    except Exception as e:
        logger.warning('Could not enqueue Telegram mirror for notification user_id=%s kind=%s: %s', user_id, kind, e)


def notify_admins_critical_error(title: str, body: str, meta: dict | None = None) -> None:
    """Создаёт уведомление kind=system_critical_error для всех админов бота (BotAdmin)."""
    try:
        admins = BotAdmin.query.filter_by(is_active=True).all()
        for ba in admins:
            notify_user(ba.user_id, kind='system_critical_error', title=title, body=body, meta=meta)
    except Exception as e:
        logger.warning("Could not notify admins of critical error: %s", e)


def _pluralize_tasks(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return 'задание'
    if 2 <= count % 10 <= 4 and not (12 <= count % 100 <= 14):
        return 'задания'
    return 'заданий'


def build_task_number_summary(task_ids: Iterable[int]) -> str:
    ids = [int(tid) for tid in (task_ids or []) if tid]
    if not ids:
        return 'нет заданий'

    rows = (
        db.session.query(Tasks.task_number, db.func.count(Tasks.task_id))
        .filter(Tasks.task_id.in_(ids))
        .group_by(Tasks.task_number)
        .order_by(Tasks.task_number.asc())
        .all()
    )
    parts = []
    for task_number, count in rows:
        word = _pluralize_tasks(int(count or 0))
        parts.append(f"{int(count)} {word} №{int(task_number)}")
    return ", ".join(parts) if parts else 'нет заданий'


def build_task_number_counts(task_ids: Iterable[int]) -> dict[int, int]:
    ids = [int(tid) for tid in (task_ids or []) if tid]
    if not ids:
        return {}

    rows = (
        db.session.query(Tasks.task_number, db.func.count(Tasks.task_id))
        .filter(Tasks.task_id.in_(ids))
        .group_by(Tasks.task_number)
        .order_by(Tasks.task_number.asc())
        .all()
    )
    return {int(task_number): int(count or 0) for task_number, count in rows}


def notify_student_and_parents(student: Student, *, kind: str, title: str, body: str | None = None, link_url: str | None = None, meta: dict | None = None) -> None:
    st_user = _get_student_user(student)
    if not st_user:
        return

    notify_user(st_user.id, kind=kind, title=title, body=body, link_url=link_url, meta=meta)
    for parent_id in _get_parent_user_ids_for_student_user(st_user.id):
        notify_user(parent_id, kind=kind, title=title, body=body, link_url=link_url, meta=meta)


def _merge_task_ids(existing: list[int] | None, new_ids: list[int]) -> list[int]:
    merged = set(int(x) for x in (existing or []) if x)
    merged.update(int(x) for x in (new_ids or []) if x)
    return sorted(merged)


def enqueue_assignment_notification(*, lesson: Lesson, assignment_type: str, task_ids: list[int], link_url: str | None = None) -> None:
    """Ставит уведомление о заданиях в очередь (дебаунс 5 минут)."""
    if not lesson or not lesson.lesson_id or not lesson.student_id:
        return

    atype = (assignment_type or 'homework').strip().lower()
    if atype not in {'homework', 'classwork', 'exam'}:
        atype = 'homework'

    normalized_ids = [int(tid) for tid in (task_ids or []) if tid]
    if not normalized_ids:
        return

    now = moscow_now()
    pending = PendingAssignmentNotification.query.filter_by(
        lesson_id=lesson.lesson_id,
        assignment_type=atype
    ).first()

    if pending:
        pending.task_ids = _merge_task_ids(pending.task_ids, normalized_ids)
        pending.last_activity_at = now
        if link_url:
            pending.link_url = link_url
    else:
        pending = PendingAssignmentNotification(
            lesson_id=lesson.lesson_id,
            student_id=lesson.student_id,
            assignment_type=atype,
            task_ids=_merge_task_ids([], normalized_ids),
            link_url=link_url,
            created_at=now,
            last_activity_at=now,
        )
        db.session.add(pending)


def process_pending_assignment_notifications(*, debounce_seconds: int | None = None, force: bool = False) -> int:
    """Обрабатывает очередь отложенных уведомлений о заданиях."""
    threshold_seconds = debounce_seconds if debounce_seconds is not None else ASSIGNMENT_NOTIFY_DEBOUNCE_SECONDS
    now = moscow_now()

    query = PendingAssignmentNotification.query
    if not force:
        cutoff = now - timedelta(seconds=threshold_seconds)
        query = query.filter(PendingAssignmentNotification.last_activity_at <= cutoff)

    pending_rows = query.order_by(PendingAssignmentNotification.last_activity_at.asc()).all()
    if not pending_rows:
        return 0

    sent = 0
    for pending in pending_rows:
        try:
            lesson = Lesson.query.get(pending.lesson_id)
            if not lesson or not lesson.student:
                db.session.delete(pending)
                continue

            task_ids = [int(tid) for tid in (pending.task_ids or []) if tid]
            if not task_ids:
                db.session.delete(pending)
                continue

            atype = (pending.assignment_type or 'homework').strip().lower()
            label = {'homework': 'Домашняя работа', 'classwork': 'Классная работа', 'exam': 'Проверочная работа'}.get(atype, 'Задания')
            title = f"Новые задания — {label}"
            summary = build_task_number_summary(task_ids)
            task_numbers = build_task_number_counts(task_ids)
            body = f"{label}: {summary}"
            link_url = pending.link_url

            notify_student_and_parents(
                lesson.student,
                kind='assignment_assigned',
                title=title,
                body=body,
                link_url=link_url,
                meta={'lesson_id': lesson.lesson_id, 'assignment_type': atype, 'tasks_count': len(task_ids), 'task_numbers': task_numbers},
            )

            db.session.delete(pending)
            sent += 1
        except Exception as e:
            logger.warning(f"Failed to process pending assignment notification {pending.pending_id}: {e}")

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.warning(f"Could not commit pending assignment notifications: {e}")

    return sent
