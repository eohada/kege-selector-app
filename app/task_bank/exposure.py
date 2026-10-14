"""Global per-student task reuse guard shared by assignments, lessons and trainer."""
from __future__ import annotations

import calendar
from datetime import datetime, timezone

from sqlalchemy import event, inspect, text
from sqlalchemy.orm import Session

from core.db_models import (
    Assignment,
    AssignmentTask,
    Lesson,
    LessonTask,
    StudentTaskSeen,
    Submission,
    moscow_now,
)


class TaskExposureConflict(ValueError):
    """Raised when a task is assigned while the student's reuse window is active."""


def _as_moscow_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).astimezone(moscow_now().tzinfo)
        return value.replace(tzinfo=None)
    return value


def add_calendar_months(value: datetime, months: int = 2) -> datetime:
    value = _as_moscow_naive(value)
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _now(now: datetime | None = None) -> datetime:
    return _as_moscow_naive(now or moscow_now())


def exposure_state_for_row(row: StudentTaskSeen | None, now: datetime | None = None) -> dict:
    now = _now(now)
    expires_at = _as_moscow_naive(row.expires_at) if row else None
    if row and expires_at is None and row.normal_use_count:
        expires_at = add_calendar_months(row.last_seen_at or row.created_at)
    previously_used = bool(row and (row.normal_use_count or row.error_review_count))
    blocked = bool(expires_at and expires_at > now)
    return {
        'seen_before': previously_used,
        'blocked': blocked,
        'active_until': expires_at if blocked else None,
        'expired': bool(previously_used and expires_at and expires_at <= now),
        'expired_reuse_count': int(row.expired_reuse_count or 0) if row else 0,
        'error_review_count': int(row.error_review_count or 0) if row else 0,
    }


def exposure_state(session, student_id: int, task_id: int, now: datetime | None = None) -> dict:
    row = session.query(StudentTaskSeen).filter_by(student_id=student_id, task_id=task_id).first()
    return exposure_state_for_row(row, now)


def assert_tasks_available(session, student_ids, task_ids, *, error_review: bool = False) -> None:
    if error_review:
        return
    student_ids = {int(value) for value in student_ids if value is not None}
    task_ids = {int(value) for value in task_ids if value is not None}
    if not student_ids or not task_ids:
        return
    now = _now()
    rows = session.query(StudentTaskSeen).filter(
        StudentTaskSeen.student_id.in_(student_ids),
        StudentTaskSeen.task_id.in_(task_ids),
    ).all()
    by_pair = {(row.student_id, row.task_id): row for row in rows}
    for student_id in student_ids:
        for task_id in task_ids:
            state = exposure_state_for_row(by_pair.get((student_id, task_id)), now)
            if state['blocked']:
                until = state['active_until'].strftime('%d.%m.%Y %H:%M')
                raise TaskExposureConflict(
                    f'Задание {task_id} уже выдавалось ученику (ID {student_id}). '
                    f'Его можно будет выдать повторно после {until} по московскому времени.'
                )


def _lock_student_task(session, student_id: int, task_id: int) -> None:
    """Serialize first-time inserts as well as updates for a student/task pair."""
    if session.get_bind().dialect.name == 'postgresql':
        session.execute(
            text('SELECT pg_advisory_xact_lock(:student_id, :task_id)'),
            {'student_id': int(student_id), 'task_id': int(task_id)},
        )


def record_task_exposure(
    session,
    student_id: int,
    task_id: int,
    *,
    context_type: str,
    context_id: int | str | None = None,
    error_review: bool = False,
    now: datetime | None = None,
) -> StudentTaskSeen:
    """Record a visible task, permitting reuse only after two calendar months."""
    now = _now(now)
    context_id_text = str(context_id)[:96] if context_id is not None else None
    context_type = (context_type or 'other')[:40]

    _lock_student_task(session, student_id, task_id)
    row = (
        session.query(StudentTaskSeen)
        .filter_by(student_id=student_id, task_id=task_id)
        .with_for_update()
        .first()
    )
    if row is None:
        row = next((item for item in session.new if isinstance(item, StudentTaskSeen)
                    and item.student_id == student_id and item.task_id == task_id), None)

    if row is None:
        row = StudentTaskSeen(
            student_id=student_id,
            task_id=task_id,
            source=context_type,
            created_at=now,
            last_seen_at=now,
            expires_at=None if error_review else add_calendar_months(now),
            normal_use_count=0 if error_review else 1,
            expired_reuse_count=0,
            error_review_count=1 if error_review else 0,
            last_error_review_at=now if error_review else None,
            context_id=context_id_text,
        )
        session.add(row)
        return row

    same_context = (
        context_id_text is not None
        and row.context_id == context_id_text
        and row.source in (context_type, f'{context_type}:{context_id_text}')
    )
    if error_review:
        if not same_context:
            row.error_review_count = int(row.error_review_count or 0) + 1
            row.last_error_review_at = now
            row.source = context_type
            row.context_id = context_id_text
        return row

    expires_at = _as_moscow_naive(row.expires_at)
    if expires_at is None and row.normal_use_count:
        expires_at = add_calendar_months(row.last_seen_at or row.created_at)
    if expires_at and expires_at > now:
        if same_context:
            return row
        until = expires_at.strftime('%d.%m.%Y %H:%M')
        raise TaskExposureConflict(
            f'Задание {task_id} уже выдавалось этому ученику. '
            f'Повтор станет доступен после {until} по московскому времени.'
        )

    if row.normal_use_count:
        row.expired_reuse_count = int(row.expired_reuse_count or 0) + 1
    else:
        row.created_at = now
    row.normal_use_count = int(row.normal_use_count or 0) + 1
    row.last_seen_at = now
    row.expires_at = add_calendar_months(now)
    row.source = context_type
    row.context_id = context_id_text
    return row


_LISTENERS_REGISTERED = False
_PENDING_KEY = 'boostudy_task_exposure_pending'


def _stage(session, key: str, value) -> None:
    session.info.setdefault(_PENDING_KEY, {}).setdefault(key, set()).add(value)


def _before_flush(session, _flush_context, _instances) -> None:
    for obj in session.new:
        if isinstance(obj, AssignmentTask):
            _stage(session, 'assignment_tasks', obj)
        elif isinstance(obj, Submission):
            _stage(session, 'submissions', obj)
        elif isinstance(obj, LessonTask):
            _stage(session, 'lesson_tasks', obj)

    for obj in session.dirty:
        state = inspect(obj)
        if isinstance(obj, LessonTask):
            if any(state.attrs[name].history.has_changes() for name in (
                'is_visible_to_student', 'task_id', 'lesson_id', 'is_error_review', 'assignment_type'
            )):
                _stage(session, 'lesson_tasks', obj)
        elif isinstance(obj, AssignmentTask):
            if any(state.attrs[name].history.has_changes() for name in ('task_id', 'assignment_id', 'is_error_review')):
                _stage(session, 'assignment_tasks', obj)


def _assignment_recipients(session, assignment_id: int) -> tuple[Assignment | None, set[int]]:
    assignment = session.get(Assignment, assignment_id)
    if not assignment:
        return None, set()
    recipients = {
        int(student_id)
        for (student_id,) in session.query(Submission.student_id).filter_by(assignment_id=assignment_id).all()
        if student_id is not None
    }
    if assignment.lesson_id:
        lesson = session.get(Lesson, assignment.lesson_id)
        if lesson and lesson.student_id:
            recipients.add(int(lesson.student_id))
    return assignment, recipients


def _after_flush_postexec(session, _flush_context) -> None:
    pending = session.info.pop(_PENDING_KEY, {})
    if not pending:
        return

    assignment_ids = {
        int(task.assignment_id)
        for task in pending.get('assignment_tasks', set())
        if getattr(task, 'assignment_id', None) is not None
    }
    assignment_ids.update(
        int(submission.assignment_id)
        for submission in pending.get('submissions', set())
        if getattr(submission, 'assignment_id', None) is not None
    )

    new_tasks_by_assignment: dict[int, list[int]] = {}
    for task in pending.get('assignment_tasks', set()):
        assignment_id = getattr(task, 'assignment_id', None)
        task_id = getattr(task, 'task_id', None)
        if assignment_id is not None and task_id is not None:
            new_tasks_by_assignment.setdefault(int(assignment_id), []).append(int(task_id))
    for assignment_id, task_ids in new_tasks_by_assignment.items():
        if len(task_ids) != len(set(task_ids)):
            raise TaskExposureConflict(f'В работе {assignment_id} одно и то же задание добавлено несколько раз.')

    for assignment_id in assignment_ids:
        assignment, student_ids = _assignment_recipients(session, assignment_id)
        if not assignment or not student_ids:
            continue
        assignment_tasks = session.query(AssignmentTask).filter_by(assignment_id=assignment_id).all()
        assignment_task_ids = [int(item.task_id) for item in assignment_tasks if item.task_id is not None]
        if len(assignment_task_ids) != len(set(assignment_task_ids)):
            raise TaskExposureConflict(f'В работе {assignment_id} одно и то же задание добавлено несколько раз.')
        mirrored_lesson_task_ids = set()
        if assignment.lesson_id:
            mirrored_lesson_task_ids = {
                int(task_id)
                for (task_id,) in session.query(LessonTask.task_id).filter_by(
                    lesson_id=assignment.lesson_id,
                    is_visible_to_student=True,
                ).all()
            }
        for student_id in student_ids:
            for assignment_task in assignment_tasks:
                if int(assignment_task.task_id) in mirrored_lesson_task_ids:
                    continue
                record_task_exposure(
                    session,
                    student_id,
                    int(assignment_task.task_id),
                    context_type='assignment',
                    context_id=assignment_id,
                    error_review=bool(assignment_task.is_error_review),
                )

    lesson_task_ids = {
        int(task.lesson_task_id)
        for task in pending.get('lesson_tasks', set())
        if getattr(task, 'lesson_task_id', None) is not None
    }
    if not lesson_task_ids:
        return
    lesson_tasks = session.query(LessonTask).filter(LessonTask.lesson_task_id.in_(lesson_task_ids)).all()
    for lesson_task in lesson_tasks:
        if not lesson_task.is_visible_to_student:
            continue
        lesson = session.get(Lesson, lesson_task.lesson_id)
        if not lesson or not lesson.student_id:
            continue
        record_task_exposure(
            session,
            int(lesson.student_id),
            int(lesson_task.task_id),
            context_type='lesson',
            context_id=lesson_task.lesson_task_id,
            error_review=bool(lesson_task.is_error_review),
        )


def register_task_exposure_listeners() -> None:
    global _LISTENERS_REGISTERED
    if _LISTENERS_REGISTERED:
        return
    event.listen(Session, 'before_flush', _before_flush)
    event.listen(Session, 'after_flush_postexec', _after_flush_postexec)
    _LISTENERS_REGISTERED = True
