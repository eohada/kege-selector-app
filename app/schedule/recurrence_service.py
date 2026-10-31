"""Service layer for recurring lessons, schedule generation, teacher availability, and exceptions.

Sprint 2.4: Recurring Lessons, Teacher Availability & Schedule Exceptions.
Principles:
- RECURRING BY DESIGN. EXCEPTIONS BY CHOICE. HISTORY NEVER REWRITTEN.
- ZERO CROSS-TEACHER LEAKAGE.
- Strict DB-level idempotency via recurrence_key (UNIQUE).
- Non-resurrection of cancelled lessons.
- Pessimistic locking serialized via acquire_scheduling_locks.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional, Tuple

from app.models import (
    Lesson,
    RecurringLessonSlot,
    RecurringSlotException,
    Student,
    TeacherScheduleException,
    TeacherWeeklyAvailability,
    User,
    db,
)
from app.schedule.ownership_service import (
    acquire_scheduling_locks,
    can_user_modify_lesson,
    check_tutor_conflict_isolated,
    resolve_lesson_ownership,
)
from app.utils.lesson_time import (
    lesson_storage_to_local,
    lesson_storage_to_utc,
    parse_local_lesson_datetime,
    timezone_from_name,
    timezone_name,
)
from app.utils.timezone import parse_local_to_utc, to_viewer_tz, utc_now

logger = logging.getLogger(__name__)

DEFAULT_GENERATION_HORIZON_DAYS = 28  # 4 weeks default horizon


class RecurrenceError(Exception):
    """Base error for recurring schedule operations."""
    pass


class RecurrenceConflictError(RecurrenceError):
    """Raised when an occurrence has an unresolvable collision with existing lessons."""
    def __init__(self, message: str, conflict_details: Optional[list[dict]] = None):
        super().__init__(message)
        self.conflict_details = conflict_details or []


class TeacherAvailabilityError(RecurrenceError):
    """Raised when an operation violates teacher working hours or exception rules."""
    def __init__(self, message: str, date_str: Optional[str] = None, reason: Optional[str] = None):
        super().__init__(message)
        self.date_str = date_str
        self.reason = reason


class TeacherExceptionConflictError(RecurrenceError):
    """Raised when a teacher schedule exception collides with existing lessons."""
    def __init__(self, message: str, affected_lessons: Optional[list[dict]] = None):
        super().__init__(message)
        self.affected_lessons = affected_lessons or []


class GeneratedLessonList(list):
    """
    Hybrid return type for generator functions:
    Acts as list of created Lesson objects (iterable, indexable, len()),
    while supporting dict-like access (.get(), ['created_count'], etc.) for backwards compatibility.
    """
    def __init__(self, lessons: list[Any], meta: dict):
        super().__init__(lessons)
        self.meta = meta

    def get(self, key: str, default: Any = None) -> Any:
        return self.meta.get(key, default)

    def __getitem__(self, item: Any) -> Any:
        if isinstance(item, str):
            return self.meta[item]
        return super().__getitem__(item)


def time_str_to_minutes(hhmm: str) -> int:
    """Converts 'HH:MM' string to minutes from start of day."""
    if not hhmm or ':' not in hhmm:
        return 0
    parts = hhmm.strip().split(':')
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except (ValueError, IndexError):
        return 0


def minutes_to_time_str(mins: int) -> str:
    """Converts minutes from start of day to 'HH:MM' string."""
    h = (mins // 60) % 24
    m = mins % 60
    return f"{h:02d}:{m:02d}"


# =========================================================================
# 1. Teacher Availability Management
# =========================================================================

def get_teacher_weekly_availability(teacher_id: int) -> list[dict]:
    """Returns active weekly working hours intervals for a teacher, ordered by weekday and time."""
    records = (
        TeacherWeeklyAvailability.query.filter_by(teacher_id=teacher_id, is_active=True)
        .order_by(TeacherWeeklyAvailability.weekday.asc(), TeacherWeeklyAvailability.start_time.asc())
        .all()
    )
    return [
        {
            'id': r.id,
            'weekday': r.weekday,
            'start_time': r.start_time,
            'end_time': r.end_time,
            'is_active': r.is_active,
        }
        for r in records
    ]


def set_teacher_weekly_availability(teacher_id: int, intervals: list[dict]) -> list[dict]:
    """
    Overwrites the weekly working hours for teacher_id.
    Each item in intervals: {'weekday': 0..6, 'start_time': 'HH:MM', 'end_time': 'HH:MM'}.
    Validates intervals (start < end, weekday in 0..6).
    """
    # Validate all intervals before mutating
    valid_rules = []
    for item in intervals:
        wd = int(item.get('weekday', 0))
        if wd < 0 or wd > 6:
            raise ValueError(f"Недопустимый день недели: {wd} (ожидается 0..6)")
        st = (item.get('start_time') or '').strip()
        et = (item.get('end_time') or '').strip()
        if time_str_to_minutes(st) >= time_str_to_minutes(et):
            raise ValueError(f"Время начала ({st}) должно быть раньше окончания ({et})")
        valid_rules.append((wd, st, et))

    # Remove existing and recreate
    TeacherWeeklyAvailability.query.filter_by(teacher_id=teacher_id).delete(synchronize_session=False)

    for wd, st, et in valid_rules:
        r = TeacherWeeklyAvailability(
            teacher_id=teacher_id,
            weekday=wd,
            start_time=st,
            end_time=et,
            is_active=True,
        )
        db.session.add(r)

    db.session.commit()
    return get_teacher_weekly_availability(teacher_id)


def get_affected_lessons_for_exception(
    teacher_id: int,
    exception_date: date,
    exception_type: str = 'unavailable',
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    tz_name: str = 'Europe/Moscow',
) -> list[dict]:
    """
    Finds active lessons for teacher_id on exception_date that conflict with the exception.
    Returns list of dicts describing each affected lesson.
    """
    candidates = (
        Lesson.query.filter(
            Lesson.teacher_id == teacher_id,
            Lesson.status.in_(['planned', 'in_progress']),
            Lesson.lesson_date.isnot(None),
        )
        .order_by(Lesson.lesson_date.asc())
        .all()
    )

    affected = []
    for l in candidates:
        local_dt = to_viewer_tz(l.lesson_date, tz_name)
        if not local_dt or local_dt.date() != exception_date:
            continue

        is_conflict = False
        l_start_min = local_dt.hour * 60 + local_dt.minute
        l_dur = int(l.duration or 60)
        l_end_min = l_start_min + l_dur

        if exception_type == 'unavailable':
            is_conflict = True
        elif exception_type in ('custom_hours', 'extra_available'):
            exc_start_min = time_str_to_minutes(start_time or '00:00')
            exc_end_min = time_str_to_minutes(end_time or '23:59')
            if l_start_min < exc_start_min or l_end_min > exc_end_min:
                is_conflict = True

        if is_conflict:
            st_name = "Ученик"
            if l.student:
                st_name = getattr(l.student, 'name', None) or f"Ученик #{l.student_id}"
            affected.append({
                'lesson_id': l.lesson_id,
                'student_id': l.student_id,
                'student_name': st_name,
                'subject': l.subject or 'Занятие',
                'lesson_date': l.lesson_date.isoformat() if l.lesson_date else '',
                'time_local': local_dt.strftime('%H:%M'),
                'duration': l_dur,
                'is_recurring': bool(l.recurring_slot_id),
            })
    return affected


def add_teacher_schedule_exception(
    teacher_id: int,
    exception_date: Optional[date] = None,
    exception_type: str = 'unavailable',
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    reason: Optional[str] = None,
    exc_date: Optional[date] = None,
    resolution_action: Optional[str] = None,
    tz_name: str = 'Europe/Moscow',
    actor_user: Optional[User] = None,
) -> TeacherScheduleException:
    """
    Adds or updates a schedule exception (day off or custom hours) for a teacher on a specific date.
    exception_type: 'unavailable' | 'custom_hours' | 'extra_available'.
    resolution_action: 'keep' | 'cancel' | 'reject' | None.
    If existing lessons are affected:
      - None or 'reject': raises TeacherExceptionConflictError.
      - 'cancel': cancels affected lessons with reason.
      - 'keep': preserves affected lessons as agreed exceptions.
    """
    exception_date = exception_date or exc_date
    if not exception_date:
        raise ValueError("Дата исключения обязательна")

    if exception_type not in ('unavailable', 'custom_hours', 'extra_available'):
        raise ValueError(f"Неизвестный тип исключения: {exception_type}")

    if exception_type in ('custom_hours', 'extra_available'):
        if not start_time or not end_time or time_str_to_minutes(start_time) >= time_str_to_minutes(end_time):
            raise ValueError("Для кастомных часов необходимо корректно указать start_time и end_time")

    acquire_scheduling_locks(student_id=None, tutor_user_id=teacher_id)

    affected = get_affected_lessons_for_exception(
        teacher_id=teacher_id,
        exception_date=exception_date,
        exception_type=exception_type,
        start_time=start_time,
        end_time=end_time,
        tz_name=tz_name,
    )

    if affected:
        if resolution_action in (None, 'reject'):
            raise TeacherExceptionConflictError(
                f"На дату {exception_date.isoformat()} уже запланированы уроки ({len(affected)} шт.).",
                affected_lessons=affected,
            )
        elif resolution_action == 'cancel':
            for aff in affected:
                if aff['is_recurring']:
                    cancel_recurring_instance(
                        lesson_id=aff['lesson_id'],
                        reason=f"Отменено: исключение преподавателя ({reason or 'выходной'})",
                        actor_user=actor_user,
                    )
                else:
                    l_obj = db.session.get(Lesson, aff['lesson_id'])
                    if l_obj:
                        l_obj.status = 'cancelled'
                        l_obj.updated_at = utc_now()
        elif resolution_action == 'keep':
            pass
        else:
            raise ValueError(f"Неизвестное действие разрешения конфликта: {resolution_action}")

    existing = TeacherScheduleException.query.filter_by(
        teacher_id=teacher_id,
        exception_date=exception_date,
    ).first()

    if existing:
        existing.exception_type = exception_type
        existing.start_time = start_time
        existing.end_time = end_time
        existing.reason = reason
        exc = existing
    else:
        exc = TeacherScheduleException(
            teacher_id=teacher_id,
            exception_date=exception_date,
            exception_type=exception_type,
            start_time=start_time,
            end_time=end_time,
            reason=reason,
        )
        db.session.add(exc)

    db.session.commit()
    return exc


def delete_teacher_schedule_exception(exception_id: int, teacher_id: int) -> bool:
    """Deletes a schedule exception for the specified teacher."""
    exc = TeacherScheduleException.query.filter_by(id=exception_id, teacher_id=teacher_id).first()
    if not exc:
        return False
    db.session.delete(exc)
    db.session.commit()
    return True


def check_teacher_availability(
    teacher_id: int,
    target_date: Optional[date] = None,
    time_hhmm: Optional[str] = None,
    duration_min: Optional[int] = None,
    tz_name: str = 'Europe/Moscow',
    check_date: Optional[date] = None,
    start_time: Optional[str] = None,
    duration_minutes: Optional[int] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Checks if a teacher is available for a lesson at the specified local date and time.
    Returns: (is_available: bool, reason_if_not: Optional[str]).
    
    Logic:
    1. Check specific TeacherScheduleException for target_date.
       - 'unavailable': False (holiday/day-off).
       - 'custom_hours': lesson interval must fall inside [start_time, end_time].
       - 'extra_available': lesson interval must fall inside [start_time, end_time].
    2. If no date exception:
       - If teacher has configured weekly availability rules:
         - Find rules matching target_date.weekday().
         - If no rules for this weekday: False (day off).
         - If rules exist: lesson interval must fall completely inside at least one rule.
       - If teacher has NO weekly rules configured: default to True (open schedule).
    """
    target_date = target_date or check_date or date.today()
    time_hhmm = time_hhmm or start_time or '18:00'
    duration_min = duration_min or duration_minutes or 60
    lesson_start_min = time_str_to_minutes(time_hhmm)
    lesson_end_min = lesson_start_min + duration_min

    # 1. Date exception
    date_exc = TeacherScheduleException.query.filter_by(
        teacher_id=teacher_id,
        exception_date=target_date,
    ).first()

    if date_exc:
        if date_exc.exception_type == 'unavailable':
            reason_text = date_exc.reason or "Нерабочий день / выходной"
            return False, f"Выходной преподавателя: {reason_text}"

        if date_exc.exception_type in ('custom_hours', 'extra_available'):
            exc_start = time_str_to_minutes(date_exc.start_time or '00:00')
            exc_end = time_str_to_minutes(date_exc.end_time or '23:59')
            if lesson_start_min >= exc_start and lesson_end_min <= exc_end:
                return True, None
            return False, (
                f"Вне индивидуальных часов работы преподавателя на этот день "
                f"({date_exc.start_time}–{date_exc.end_time})"
            )

    # 2. Weekly rules
    teacher_has_rules = (
        TeacherWeeklyAvailability.query.filter_by(teacher_id=teacher_id, is_active=True).first()
        is not None
    )
    if not teacher_has_rules:
        # Teacher has not configured strict working hours; open by default
        return True, None

    day_rules = (
        TeacherWeeklyAvailability.query.filter_by(
            teacher_id=teacher_id,
            weekday=target_date.weekday(),
            is_active=True,
        ).all()
    )

    if not day_rules:
        return False, "нерабочий день / выходной по регулярному графику преподавателя"

    for rule in day_rules:
        r_start = time_str_to_minutes(rule.start_time)
        r_end = time_str_to_minutes(rule.end_time)
        if lesson_start_min >= r_start and lesson_end_min <= r_end:
            return True, None

    intervals_str = ", ".join(f"{r.start_time}–{r.end_time}" for r in day_rules)
    return False, f"вне рабочих часов преподавателя в этот день (доступно: {intervals_str})"


# =========================================================================
# 2. Student Conflict Helper
# =========================================================================

def check_student_conflict(
    student_id: int,
    start_dt_utc: datetime,
    duration_min: int,
    exclude_lesson_id: Optional[int] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Checks if student has an overlapping lesson with ANY teacher.
    Returns: (has_conflict: bool, details: Optional[str]).
    """
    end_dt_utc = start_dt_utc + timedelta(minutes=duration_min)
    q = Lesson.query.filter(
        Lesson.student_id == student_id,
        Lesson.status != 'cancelled',
        Lesson.lesson_date.isnot(None),
    )
    if exclude_lesson_id:
        q = q.filter(Lesson.lesson_id != exclude_lesson_id)

    candidates = q.all()
    for l in candidates:
        if not l.lesson_date:
            continue
        l_start = lesson_storage_to_utc(l.lesson_date)
        l_end = lesson_storage_to_utc(l.lesson_date + timedelta(minutes=int(l.duration or 60)))
        if not l_start or not l_end:
            continue
        if (l_start < end_dt_utc) and (start_dt_utc < l_end):
            subj = l.subject or "Занятие"
            return True, f"Ученик уже занят на уроке «{subj}» ({l_start.strftime('%H:%M')}–{l_end.strftime('%H:%M')} UTC)"

    return False, None


# =========================================================================
# 3. Series Preview and Validation
# =========================================================================

def preview_recurring_slot(
    teacher_id: int,
    student_id: int,
    weekday: int,
    time_hhmm: Optional[str] = None,
    duration: Optional[int] = None,
    tz_name: str = 'Europe/Moscow',
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    horizon_days: int = DEFAULT_GENERATION_HORIZON_DAYS,
    subject: str = 'Информатика',
    ignore_availability: bool = False,
    start_time: Optional[str] = None,
    duration_minutes: Optional[int] = None,
) -> dict:
    """
    Simulates upcoming occurrences of a recurring slot within the horizon.
    Returns preview summary with valid dates, conflict dates, and availability issues.
    Never modifies database state.
    """
    time_hhmm = time_hhmm or start_time or '18:00'
    duration = duration or duration_minutes or 60
    s_date = start_date or date.today()
    from_date = max(s_date, date.today())
    max_horizon_date = from_date + timedelta(days=horizon_days)
    to_date = min(end_date, max_horizon_date) if end_date else max_horizon_date

    occurrences = []
    clean_count = 0
    conflict_count = 0
    unavailable_count = 0

    curr = from_date
    while curr <= to_date:
        if curr.weekday() == weekday:
            dt_utc = parse_local_to_utc(curr.isoformat(), time_hhmm, tz_name)
            occ_item = {
                'date': curr.isoformat(),
                'weekday': weekday,
                'time_local': time_hhmm,
                'start_time': time_hhmm,
                'end_time': minutes_to_time_str(time_str_to_minutes(time_hhmm) + duration),
                'time_utc': dt_utc.isoformat(),
                'status': 'valid',
                'reasons': [],
                'conflict': False,
                'teacher_available': True,
                'conflict_reason': None,
            }

            # Check availability
            if not ignore_availability:
                is_avail, avail_reason = check_teacher_availability(
                    teacher_id, curr, time_hhmm, duration, tz_name
                )
                if not is_avail:
                    occ_item['status'] = 'unavailable'
                    occ_item['teacher_available'] = False
                    occ_item['reasons'].append(avail_reason)
                    unavailable_count += 1

            # Check teacher conflict
            tutor_conflict = check_tutor_conflict_isolated(teacher_id, dt_utc, duration)
            if tutor_conflict:
                occ_item['status'] = 'conflict'
                occ_item['conflict'] = True
                occ_item['reasons'].append("У преподавателя уже назначен другой урок в это время")

            # Check student conflict
            st_conflict, st_msg = check_student_conflict(student_id, dt_utc, duration)
            if st_conflict:
                occ_item['status'] = 'conflict'
                occ_item['conflict'] = True
                occ_item['reasons'].append(st_msg)

            if occ_item['reasons']:
                occ_item['conflict_reason'] = '; '.join(occ_item['reasons'])

            if occ_item['status'] == 'conflict':
                conflict_count += 1
            elif occ_item['status'] == 'valid':
                clean_count += 1

            occurrences.append(occ_item)

        curr += timedelta(days=1)

    return {
        'total_occurrences': len(occurrences),
        'clean_count': clean_count,
        'conflict_count': conflict_count,
        'conflicts_count': conflict_count,
        'unavailable_count': unavailable_count,
        'occurrences': occurrences,
        'can_create_atomic': (conflict_count == 0 and unavailable_count == 0),
    }


# =========================================================================
# 4. Safe Generation Engine (Idempotent, Transactional, Isolated)
# =========================================================================

def generate_lessons_for_slot(
    slot: Any,
    horizon_days: int = DEFAULT_GENERATION_HORIZON_DAYS,
    start_date: Optional[date] = None,
    skip_conflicts: bool = True,
    ignore_availability: bool = False,
    actor_user: Optional[User] = None,
) -> Any:
    """
    Generates concrete Lesson instances for a RecurringLessonSlot up to horizon_days.
    
    Guarantees:
    - Idempotency: Lessons have unique recurrence_key = f"slot_{slot_id}_{YYYYMMDD}".
    - DB-level lock serialization via acquire_scheduling_locks(student_id, teacher_id).
    - Cancelled instances are never resurrected.
    - Exceptions (skip/reschedule) are strictly honored.
    - Zero cross-teacher leakage.
    """
    if isinstance(slot, int):
        slot = db.session.get(RecurringLessonSlot, slot)

    if not slot or not slot.is_active:
        return GeneratedLessonList([], {'slot_id': getattr(slot, 'slot_id', None), 'created_count': 0, 'created': [], 'skipped_conflicts': [], 'skipped_existing': [], 'skipped_exceptions': []})

    from_date = max(slot.start_date or date.today(), start_date or date.today())
    max_horizon_date = from_date + timedelta(days=horizon_days)
    to_date = min(slot.end_date, max_horizon_date) if slot.end_date else max_horizon_date

    # Acquire pessimistic row-level locks on both Student and Teacher
    acquire_scheduling_locks(slot.student_id, slot.owner_user_id)
    try:
        db.session.refresh(slot)
    except Exception:
        pass
    if not slot or not slot.is_active:
        return GeneratedLessonList([], {'slot_id': getattr(slot, 'slot_id', None), 'created_count': 0, 'created': [], 'skipped_conflicts': [], 'skipped_existing': [], 'skipped_exceptions': []})

    created_lessons = []
    created_lesson_objects = []
    skipped_conflicts = []
    skipped_availability = []
    skipped_existing = []
    skipped_exceptions = []
    expected_count = 0

    curr = from_date
    while curr < max_horizon_date and (slot.end_date is None or curr <= slot.end_date):
        if curr.weekday() == slot.weekday:
            expected_count += 1
            origin_date_str = curr.strftime('%Y%m%d')
            rec_key = f"slot_{slot.slot_id}_{origin_date_str}"

            # 1. Check if an explicit exception exists for this slot and date
            exc = RecurringSlotException.query.filter_by(
                slot_id=slot.slot_id,
                exception_date=curr,
            ).first()

            if exc and exc.action in ('skip', 'rescheduled'):
                skipped_exceptions.append({
                    'date': curr.isoformat(),
                    'reason': exc.reason or ('Пропущено по правилу исключения' if exc.action == 'skip' else 'Урок перенесен на другую дату'),
                    'action': exc.action,
                })
                curr += timedelta(days=1)
                continue

            # 2. Check if a lesson already exists for this recurrence key or origin date
            existing_lesson = Lesson.query.filter(
                (Lesson.recurrence_key == rec_key)
                | ((Lesson.recurring_slot_id == slot.slot_id) & (Lesson.slot_origin_date == curr))
            ).first()

            if existing_lesson:
                if existing_lesson.status == 'cancelled':
                    # Non-resurrection guarantee: cancelled lessons remain cancelled!
                    skipped_exceptions.append({
                        'date': curr.isoformat(),
                        'reason': 'Урок был отменен (не воскрешается)',
                    })
                else:
                    skipped_existing.append({
                        'date': curr.isoformat(),
                        'lesson_id': existing_lesson.lesson_id,
                    })
                curr += timedelta(days=1)
                continue

            # 3. Calculate aware UTC instant via local wall time + IANA timezone
            dt_utc = parse_local_to_utc(curr.isoformat(), slot.time_hhmm, slot.timezone)

            # 4. Check Teacher Availability
            if not ignore_availability:
                is_avail, avail_reason = check_teacher_availability(
                    slot.owner_user_id, curr, slot.time_hhmm, slot.duration, slot.timezone
                )
                if not is_avail:
                    if skip_conflicts:
                        skipped_availability.append({'date': curr.isoformat(), 'reason': avail_reason})
                        curr += timedelta(days=1)
                        continue
                    raise TeacherAvailabilityError(
                        f"Преподаватель недоступен на дату {curr.isoformat()}: {avail_reason}",
                        date_str=curr.isoformat(),
                        reason=avail_reason,
                    )

            # 5. Check Conflicts (Teacher & Student)
            tutor_conflict = check_tutor_conflict_isolated(slot.owner_user_id, dt_utc, slot.duration)
            if tutor_conflict:
                if skip_conflicts:
                    skipped_conflicts.append({'date': curr.isoformat(), 'reason': 'Конфликт у преподавателя'})
                    curr += timedelta(days=1)
                    continue
                raise RecurrenceConflictError(
                    f"Конфликт у преподавателя на дату {curr.isoformat()}",
                    conflict_details=[{'date': curr.isoformat(), 'type': 'teacher_conflict'}],
                )

            st_conflict, st_msg = check_student_conflict(slot.student_id, dt_utc, slot.duration)
            if st_conflict:
                if skip_conflicts:
                    skipped_conflicts.append({'date': curr.isoformat(), 'reason': st_msg})
                    curr += timedelta(days=1)
                    continue
                raise RecurrenceConflictError(
                    f"Конфликт у ученика на дату {curr.isoformat()}: {st_msg}",
                    conflict_details=[{'date': curr.isoformat(), 'type': 'student_conflict', 'details': st_msg}],
                )

            # 6. Instantiate Lesson
            new_lesson = Lesson(
                student_id=slot.student_id,
                teacher_id=slot.owner_user_id,
                subject=slot.subject or 'Информатика',
                lesson_date=dt_utc,
                duration=int(slot.duration or 60),
                lesson_type=slot.lesson_type or 'regular',
                status='planned',
                topic=slot.topic or f"Урок [{slot.subject or 'Информатика'}]",
                recurring_slot_id=slot.slot_id,
                recurrence_key=rec_key,
                slot_origin_date=curr,
                is_rescheduled=False,
            )
            db.session.add(new_lesson)
            db.session.flush()

            created_lesson_objects.append(new_lesson)
            created_lessons.append({
                'lesson_id': new_lesson.lesson_id,
                'date': curr.isoformat(),
                'datetime_utc': dt_utc.isoformat(),
                'subject': new_lesson.subject,
            })

        curr += timedelta(days=1)

    db.session.commit()
    ret_meta = {
        'slot_id': slot.slot_id,
        'expected_count': expected_count,
        'created_count': len(created_lessons),
        'created': created_lessons,
        'skipped_conflicts': skipped_conflicts,
        'skipped_availability': skipped_availability,
        'skipped_existing': skipped_existing,
        'skipped_exceptions': skipped_exceptions,
        'has_conflicts': bool(skipped_conflicts or skipped_availability),
        'is_partial': (len(created_lessons) + len(skipped_existing)) < expected_count,
    }
    return GeneratedLessonList(created_lesson_objects, ret_meta)


# =========================================================================
# 5. Recurring Series Management & Exceptions (A, B, C, D, E)
# =========================================================================

def create_recurring_series(
    actor_user: Optional[User] = None,
    student_id: int = 0,
    weekday: int = 0,
    time_hhmm: str = '18:00',
    duration: int = 60,
    subject: Optional[str] = None,
    timezone_str: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    topic: Optional[str] = None,
    skip_conflicts: bool = True,
    horizon_days: int = DEFAULT_GENERATION_HORIZON_DAYS,
    series_id: Optional[str] = None,
    teacher_id: Optional[int] = None,
    start_time: Optional[str] = None,
    duration_minutes: Optional[int] = None,
) -> Tuple[RecurringLessonSlot, Any]:
    """
    Creates a new RecurringLessonSlot and generates initial occurrences within the horizon.
    """
    if actor_user is None and teacher_id is not None:
        actor_user = db.session.get(User, teacher_id)
    if start_time:
        time_hhmm = start_time
    if duration_minutes:
        duration = duration_minutes
    if actor_user is None:
        raise ValueError("actor_user или teacher_id обязателен.")

    student = db.session.get(Student, student_id)
    if not student:
        raise ValueError("Ученик не найден.")

    resolved_teacher_id, resolved_subject = resolve_lesson_ownership(
        actor_user=actor_user,
        student=student,
        requested_teacher_id=actor_user.id if actor_user.is_tutor() else None,
        requested_subject=subject,
    )

    tz = timezone_name(timezone_str or 'Europe/Moscow')
    s_date = start_date or date.today()
    sid = series_id or f"series_{uuid.uuid4()}"

    slot = RecurringLessonSlot(
        owner_user_id=resolved_teacher_id,
        student_id=student.student_id,
        weekday=weekday,
        time_hhmm=time_hhmm,
        duration=duration,
        lesson_type='regular',
        subject=resolved_subject,
        topic=topic,
        start_date=s_date,
        end_date=end_date,
        series_id=sid,
        timezone=tz,
        is_active=True,
    )
    db.session.add(slot)
    db.session.flush()

    gen_result = generate_lessons_for_slot(
        slot=slot,
        horizon_days=horizon_days,
        start_date=s_date,
        skip_conflicts=skip_conflicts,
        actor_user=actor_user,
    )

    return slot, gen_result


# Scenario A: Modify single lesson (Reschedule single occurrence)
def reschedule_recurring_instance(
    lesson_id: int,
    new_date: date,
    new_time_hhmm: Optional[str] = None,
    new_duration: Optional[int] = None,
    actor_user: Optional[User] = None,
    new_time: Optional[str] = None,
    duration_minutes: Optional[int] = None,
    topic: Optional[str] = None,
    status: Optional[str] = None,
    subject: Optional[str] = None,
    notes: Optional[str] = None,
    homework: Optional[str] = None,
    student_notes: Optional[str] = None,
    is_test: Optional[bool] = None,
) -> Lesson:
    """
    Scenario A: Reschedules a single lesson from a recurring series.
    The lesson retains its identity, materials, notes, and slot_origin_date,
    while is_rescheduled is marked True and an exception is recorded so future
    generations don't recreate the original date.
    """
    new_time_hhmm = new_time_hhmm or new_time or '18:00'
    dur = new_duration or duration_minutes

    lesson = db.session.get(Lesson, lesson_id)
    if not lesson:
        raise ValueError(f"Урок #{lesson_id} не найден.")

    if actor_user is None and lesson.teacher_id:
        actor_user = db.session.get(User, lesson.teacher_id)

    can_mod, err_msg = can_user_modify_lesson(actor_user, lesson)
    if not can_mod:
        raise PermissionError(err_msg or "Доступ запрещен.")

    # Acquire locks
    acquire_scheduling_locks(lesson.student_id, lesson.teacher_id)

    # Determine timezone from slot or teacher
    tz_str = 'Europe/Moscow'
    if lesson.recurring_slot:
        tz_str = lesson.recurring_slot.timezone

    new_dt_utc = parse_local_to_utc(new_date.isoformat(), new_time_hhmm, tz_str)
    duration_val = dur or int(lesson.duration or 60)

    # Check conflicts on new datetime
    tutor_conf = check_tutor_conflict_isolated(
        lesson.teacher_id, new_dt_utc, duration_val, exclude_lesson_id=lesson.lesson_id
    )
    if tutor_conf:
        raise RecurrenceConflictError("Конфликт: у преподавателя уже назначен урок на новое время.")

    st_conf, st_msg = check_student_conflict(
        lesson.student_id, new_dt_utc, duration_val, exclude_lesson_id=lesson.lesson_id
    )
    if st_conf:
        raise RecurrenceConflictError(f"Конфликт: {st_msg}")

    # Record exception on original slot date if applicable
    if lesson.recurring_slot_id and lesson.slot_origin_date:
        exc = RecurringSlotException.query.filter_by(
            slot_id=lesson.recurring_slot_id,
            exception_date=lesson.slot_origin_date,
        ).first()
        if not exc:
            exc = RecurringSlotException(
                slot_id=lesson.recurring_slot_id,
                exception_date=lesson.slot_origin_date,
                action='rescheduled',
                rescheduled_to=new_dt_utc,
                reason=f"Перенесен на {new_date.isoformat()} {new_time_hhmm}",
            )
            db.session.add(exc)
        else:
            exc.action = 'rescheduled'
            exc.rescheduled_to = new_dt_utc

    # Update lesson
    lesson.lesson_date = new_dt_utc
    lesson.duration = duration_val
    lesson.is_rescheduled = True
    if topic is not None:
        lesson.topic = topic
    if status is not None:
        lesson.status = status
    if subject is not None:
        lesson.subject = subject
    if notes is not None:
        lesson.notes = notes
        lesson.description = notes
    if homework is not None:
        lesson.homework = homework
    if student_notes is not None:
        lesson.student_notes = student_notes
    if is_test is not None:
        lesson.is_test = is_test
    lesson.updated_at = utc_now()

    db.session.commit()
    return lesson


# Scenario B: Modify this and all future lessons
def update_series_from_date(
    slot_id: Union[int, str] = 0,
    from_date: Optional[date] = None,
    new_weekday: Optional[int] = None,
    new_time_hhmm: Optional[str] = None,
    new_duration: Optional[int] = None,
    actor_user: Optional[User] = None,
    series_id: Optional[str] = None,
    new_start_time: Optional[str] = None,
    new_duration_minutes: Optional[int] = None,
    new_topic: Optional[str] = None,
    new_subject: Optional[str] = None,
) -> Tuple[RecurringLessonSlot, RecurringLessonSlot]:
    """
    Scenario B: Shifts schedule starting from from_date.
    Closes old slot at from_date - 1 day, creates a new slot starting at from_date,
    and removes/regenerates uncompleted future non-exception lessons.
    History before from_date is NEVER rewritten.
    """
    old_slot = None
    if isinstance(slot_id, str) and slot_id.startswith('series_'):
        old_slot = RecurringLessonSlot.query.filter_by(series_id=slot_id, is_active=True).first()
    elif series_id:
        old_slot = RecurringLessonSlot.query.filter_by(series_id=series_id, is_active=True).first()
    elif slot_id:
        old_slot = db.session.get(RecurringLessonSlot, int(slot_id))

    if not old_slot:
        raise ValueError(f"Слот не найден.")

    from_d = from_date or date.today()
    target_weekday = new_weekday if new_weekday is not None else old_slot.weekday
    target_time = new_time_hhmm or new_start_time or old_slot.time_hhmm
    target_duration = new_duration or new_duration_minutes or old_slot.duration
    target_topic = new_topic or old_slot.topic
    target_subject = new_subject or old_slot.subject

    if actor_user and actor_user.is_tutor() and old_slot.owner_user_id != actor_user.id:
        raise PermissionError("Вы не можете изменять серию другого преподавателя.")

    acquire_scheduling_locks(old_slot.student_id, old_slot.owner_user_id)

    # 1. Terminate old slot
    old_slot.end_date = from_d - timedelta(days=1)
    old_slot.updated_at = utc_now()

    # 2. Delete future planned lessons of old slot that are on or after from_date and NOT custom exceptions
    future_lessons = Lesson.query.filter(
        Lesson.recurring_slot_id == old_slot.slot_id,
        Lesson.slot_origin_date >= from_d,
        Lesson.status == 'planned',
        Lesson.is_rescheduled.is_(False),
    ).all()

    for fl in future_lessons:
        db.session.delete(fl)

    # 3. Create new slot
    new_slot = RecurringLessonSlot(
        owner_user_id=old_slot.owner_user_id,
        student_id=old_slot.student_id,
        weekday=target_weekday,
        time_hhmm=target_time,
        duration=target_duration,
        lesson_type=old_slot.lesson_type,
        subject=target_subject,
        topic=target_topic,
        start_date=from_d,
        end_date=None,
        series_id=old_slot.series_id or f"series_{uuid.uuid4()}",
        timezone=old_slot.timezone,
        is_active=True,
    )
    db.session.add(new_slot)
    db.session.flush()

    # 4. Generate lessons for the new slot
    rem_days = DEFAULT_GENERATION_HORIZON_DAYS
    if old_slot.start_date:
        rem_days = max(7, (old_slot.start_date + timedelta(days=DEFAULT_GENERATION_HORIZON_DAYS) - from_d).days)
    generate_lessons_for_slot(
        slot=new_slot,
        horizon_days=rem_days,
        start_date=from_d,
        skip_conflicts=True,
        actor_user=actor_user,
    )

    db.session.commit()
    return old_slot, new_slot


# Scenario C: Modify whole series
def update_whole_series(
    slot_id: int,
    new_time_hhmm: Optional[str] = None,
    new_duration: Optional[int] = None,
    new_subject: Optional[str] = None,
    actor_user: Optional[User] = None,
    start_time: Optional[str] = None,
    duration_minutes: Optional[int] = None,
    topic: Optional[str] = None,
    subject: Optional[str] = None,
) -> RecurringLessonSlot:
    """
    Scenario C: Updates entire recurring series parameters for future uncompleted lessons.
    Past and completed lessons are strictly preserved without modification.
    Individually rescheduled instances (is_rescheduled=True) are strictly preserved at their custom date/time.
    Pre-checks conflicts on new times for all future dates to prevent blind collisions.
    Preserves homework, notes, and custom topics unless explicitly overridden.
    """
    target_time = new_time_hhmm or start_time
    target_dur = new_duration or duration_minutes
    target_subj = new_subject or subject

    slot = db.session.get(RecurringLessonSlot, slot_id)
    if not slot:
        raise ValueError(f"Слот #{slot_id} не найден.")

    if actor_user and actor_user.is_tutor() and slot.owner_user_id != actor_user.id:
        raise PermissionError("Вы не можете изменять серию другого преподавателя.")

    acquire_scheduling_locks(slot.student_id, slot.owner_user_id)

    proposed_time = target_time or slot.time_hhmm
    proposed_duration = target_dur or slot.duration

    today = date.today()

    # Find future planned lessons that are not rescheduled exceptions
    future_lessons = Lesson.query.filter(
        Lesson.recurring_slot_id == slot.slot_id,
        Lesson.slot_origin_date >= today,
        Lesson.status == 'planned',
        Lesson.is_rescheduled.is_(False),
    ).order_by(Lesson.slot_origin_date.asc()).all()

    # Pre-check conflicts on new times for all future dates before mutating anything
    conflicts_found = []
    lesson_datetimes = []
    for fl in future_lessons:
        if fl.slot_origin_date:
            new_dt_utc = parse_local_to_utc(fl.slot_origin_date.isoformat(), proposed_time, slot.timezone)
            tutor_conf = check_tutor_conflict_isolated(
                slot.owner_user_id, new_dt_utc, proposed_duration, exclude_lesson_id=fl.lesson_id
            )
            if tutor_conf:
                conflicts_found.append({
                    'lesson_id': fl.lesson_id,
                    'date': fl.slot_origin_date.isoformat(),
                    'type': 'teacher_conflict',
                    'reason': f"Преподаватель уже занят на {fl.slot_origin_date.isoformat()} в {proposed_time}",
                })
            st_conf, st_msg = check_student_conflict(
                slot.student_id, new_dt_utc, proposed_duration, exclude_lesson_id=fl.lesson_id
            )
            if st_conf:
                conflicts_found.append({
                    'lesson_id': fl.lesson_id,
                    'date': fl.slot_origin_date.isoformat(),
                    'type': 'student_conflict',
                    'reason': st_msg,
                })
            lesson_datetimes.append((fl, new_dt_utc))

    if conflicts_found:
        raise RecurrenceConflictError(
            f"Невозможно обновить серию: обнаружено конфликтов: {len(conflicts_found)}",
            conflict_details=conflicts_found,
        )

    # Safe to apply mutations
    if target_time:
        slot.time_hhmm = target_time
    if target_dur:
        slot.duration = target_dur
    if target_subj:
        slot.subject = target_subj
    if topic:
        slot.topic = topic
    slot.updated_at = utc_now()

    for fl, new_dt_utc in lesson_datetimes:
        fl.lesson_date = new_dt_utc
        fl.duration = proposed_duration
        if target_subj:
            fl.subject = target_subj
        if topic:
            fl.topic = topic
        fl.updated_at = utc_now()

    db.session.commit()
    return slot


# Scenario D: Cancel single lesson
def cancel_recurring_instance(
    lesson_id: int,
    reason: Optional[str] = None,
    actor_user: Optional[User] = None,
) -> Lesson:
    """
    Scenario D: Cancels a single lesson instance.
    Sets status='cancelled' and adds a skip exception for slot_origin_date,
    guaranteeing that subsequent generations will not resurrect this lesson.
    """
    lesson = db.session.get(Lesson, lesson_id)
    if not lesson:
        raise ValueError(f"Урок #{lesson_id} не найден.")

    if actor_user is None and lesson.teacher_id:
        actor_user = db.session.get(User, lesson.teacher_id)

    can_mod, err_msg = can_user_modify_lesson(actor_user, lesson)
    if not can_mod:
        raise PermissionError(err_msg or "Доступ запрещен.")

    lesson.status = 'cancelled'
    lesson.updated_at = utc_now()

    if lesson.recurring_slot_id and lesson.slot_origin_date:
        exc = RecurringSlotException.query.filter_by(
            slot_id=lesson.recurring_slot_id,
            exception_date=lesson.slot_origin_date,
        ).first()
        if not exc:
            exc = RecurringSlotException(
                slot_id=lesson.recurring_slot_id,
                exception_date=lesson.slot_origin_date,
                action='skip',
                reason=reason or "Отменено пользователем",
            )
            db.session.add(exc)
        else:
            exc.action = 'skip'
            exc.reason = reason or exc.reason

    # Attach convenience attributes
    lesson.slot_id = lesson.recurring_slot_id
    lesson.action = 'skip'

    # Invalidate pending telegram delivery if active
    try:
        from app.telegram.delivery import invalidate_pending_lesson_deliveries
        invalidate_pending_lesson_deliveries(lesson.lesson_id, reason='lesson_cancelled')
    except Exception as e:
        logger.warning(f"Could not invalidate telegram delivery for cancelled lesson {lesson_id}: {e}")

    db.session.commit()
    return lesson


# Scenario E: Pause / Resume series
def pause_recurring_series(
    slot_id: int,
    actor_user: Optional[User] = None,
    mode: str = 'stop_generation_only',
    reason: Optional[str] = None,
) -> RecurringLessonSlot:
    """
    Scenario E: Pauses a recurring series.
    Mode A ('stop_generation_only'): Future lessons will not be generated; existing planned lessons remain.
    Mode B ('cancel_future_lessons'): Pauses series AND cancels future planned lessons with skip exceptions.
    Completed history is never mutated!
    """
    if mode not in ('stop_generation_only', 'cancel_future_lessons'):
        raise ValueError(f"Неизвестный режим приостановки: {mode}")

    slot = db.session.get(RecurringLessonSlot, slot_id)
    if not slot:
        raise ValueError(f"Слот #{slot_id} не найден.")
    if actor_user and actor_user.is_tutor() and slot.owner_user_id != actor_user.id:
        raise PermissionError("Вы не можете приостановить серию другого преподавателя.")

    acquire_scheduling_locks(slot.student_id, slot.owner_user_id)
    slot.is_active = False
    slot.updated_at = utc_now()

    if mode == 'cancel_future_lessons':
        today = date.today()
        future_lessons = Lesson.query.filter(
            Lesson.recurring_slot_id == slot.slot_id,
            Lesson.slot_origin_date >= today,
            Lesson.status == 'planned',
        ).all()
        for fl in future_lessons:
            cancel_recurring_instance(
                fl.lesson_id,
                reason=reason or "Серия приостановлена (отмена будущих уроков)",
                actor_user=actor_user,
            )

    db.session.commit()
    return slot


def resume_recurring_series(
    slot_id: int,
    actor_user: Optional[User] = None,
    generate_horizon_days: Optional[int] = None,
) -> RecurringLessonSlot:
    """
    Scenario E: Resumes a paused recurring series.
    Guarantees: Cancelled lessons (whether cancelled individually or via Mode B)
    are NEVER resurrected!
    """
    slot = db.session.get(RecurringLessonSlot, slot_id)
    if not slot:
        raise ValueError(f"Слот #{slot_id} не найден.")
    if actor_user and actor_user.is_tutor() and slot.owner_user_id != actor_user.id:
        raise PermissionError("Вы не можете возобновить серию другого преподавателя.")

    acquire_scheduling_locks(slot.student_id, slot.owner_user_id)
    slot.is_active = True
    slot.updated_at = utc_now()

    if generate_horizon_days:
        generate_lessons_for_slot(slot=slot, horizon_days=generate_horizon_days, actor_user=actor_user)

    db.session.commit()
    return slot
