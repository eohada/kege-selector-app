"""
Маршруты расписания
"""
import logging
import os
import re
from datetime import datetime, timedelta, time, date, timezone as dt_timezone
from flask import render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_required, current_user

from app.schedule import schedule_bp
from app.lessons.lifecycle import LessonLifecycleError, transition_lesson_status
from app.models import (
    Lesson, Student, User, RecurringLessonSlot, db, moscow_now, MOSCOW_TZ, TOMSK_TZ,
    LessonTask, LessonTaskTeacherComment, LessonTaskAttempt,
    LessonWhiteboard, LessonOutcome, LessonMaterialLink,
    PendingAssignmentNotification, LessonMessage, LessonTeacherHomeworkNote,
    LearningError, LearningItem, Assignment, GradebookEntry
)
from app.auth.rbac_utils import get_user_scope, has_permission
from app.notifications.service import notify_student_and_parents
from app.telegram.user_notify import notify_user_by_id
from app.utils.relationship_scope import get_parent_user_ids_for_student
from app.utils.datetime_utc import effective_timezone_name
from app.utils.lesson_time import parse_local_lesson_datetime, lesson_storage_to_local, lesson_storage_to_utc, timezone_from_name, timezone_name, lesson_display_time
from app.utils.timezone import to_utc_instant, format_utc_iso_z, parse_local_to_utc, canonical_timezone_name
from core.audit_logger import audit_logger
import secrets

logger = logging.getLogger(__name__)

RU_MONTHS_GEN = [
    'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
    'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'
]
RU_MONTHS_NOM = [
    'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
    'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'
]


def _add_months(src: date, months: int) -> date:
    month_idx = src.month - 1 + months
    year = src.year + month_idx // 12
    month = month_idx % 12 + 1
    return date(year, month, 1)


def _schedule_timezone_from_user() -> str:
    try:
        return timezone_name(effective_timezone_name(current_user))
    except Exception:
        return 'Europe/Moscow'

def _resolve_accessible_student_ids_for_current_user() -> list[int] | None:
    """
    Lessons.student_id хранит Student.student_id.
    get_user_scope() возвращает список User.id учеников.
    Маппим User.id -> Student.student_id по user_id и fallback student_id==user.id.
    """
    if not current_user.is_authenticated:
        return []
    if current_user.is_creator() or current_user.is_admin() or current_user.is_chief_tester():
        return None

    scope = get_user_scope(current_user)
    if scope.get('can_see_all'):
        return None

    user_ids = scope.get('student_ids') or []
    if current_user.is_student() and current_user.id not in user_ids:
        user_ids = [current_user.id]

    if not user_ids:
        return []

    student_ids: list[int] = []
    try:
        # Прямой поиск всех привязанных к преподавателю/тьютору учеников (mentor_id / enrollments)
        if current_user and current_user.is_authenticated:
            if current_user.is_tutor():
                from app.schedule.ownership_service import get_accessible_students_for_teacher
                tutor_students = get_accessible_students_for_teacher(current_user)
                student_ids.extend([s['student_id'] for s in tutor_students if s.get('student_id')])
            else:
                my_students = Student.query.filter(
                    (Student.mentor_id == current_user.id) | (Student.user_id == current_user.id)
                ).all()
                student_ids.extend([s.student_id for s in my_students if s])

        by_user_id = Student.query.filter(Student.user_id.in_(user_ids)).all() if user_ids else []
        student_ids.extend([s.student_id for s in by_user_id if s])
        usernames = list(dict.fromkeys([(u.username or '').strip() for u in User.query.filter(User.id.in_(user_ids)).all() if (u.username or '').strip()])) if user_ids else []
        if usernames:
            by_platform = Student.query.filter(Student.platform_id.in_(usernames)).all()
            student_ids.extend([s.student_id for s in by_platform if s])
        if user_ids:
            by_legacy = Student.query.filter(Student.student_id.in_(user_ids)).all()
            student_ids.extend([s.student_id for s in by_legacy if s])
    except Exception as e:
        logger.warning(f"Schedule: failed map scope user_ids->student_ids: {e}")

    seen = set()
    out: list[int] = []
    for sid in student_ids:
        if sid not in seen:
            seen.add(sid)
            out.append(sid)
    return out


def _resolve_accessible_student_ids_for_user(user: User) -> list[int] | None:
    """То же, что scope для current_user, но для token-based export."""
    if not user:
        return []
    if user.is_creator() or user.is_admin() or user.is_chief_tester():
        return None

    scope = get_user_scope(user)
    if scope.get('can_see_all'):
        return None

    user_ids = scope.get('student_ids') or []
    if user.is_student() and user.id not in user_ids:
        user_ids = [user.id]
    if not user_ids:
        return []

    student_ids: list[int] = []
    if getattr(user, 'is_tutor', None) and user.is_tutor():
        from app.schedule.ownership_service import get_accessible_students_for_teacher
        tutor_students = get_accessible_students_for_teacher(user)
        student_ids.extend([s['student_id'] for s in tutor_students if s.get('student_id')])
    try:
        by_user_id = Student.query.filter(Student.user_id.in_(user_ids)).all()
        student_ids.extend([s.student_id for s in by_user_id if s])
    except Exception:
        pass
    try:
        students_by_id = Student.query.filter(Student.student_id.in_(user_ids)).all()
        student_ids.extend([s.student_id for s in students_by_id if s])
    except Exception:
        pass

    seen = set()
    out: list[int] = []
    for sid in student_ids:
        if sid not in seen:
            seen.add(sid)
            out.append(sid)
    return out


def _can_manage_schedule() -> bool:
    if not current_user.is_authenticated:
        return False
    if current_user.is_creator() or current_user.is_admin():
        return True
    if current_user.is_student() or current_user.is_parent():
        return False
    if getattr(current_user, 'is_tutor', None) and current_user.is_tutor():
        return True
    return bool(
        has_permission(current_user, 'tools.schedule')
        or has_permission(current_user, 'lesson.create')
        or has_permission(current_user, 'lesson.edit')
    )


def _require_lesson_in_scope(lesson: Lesson, require_write: bool = False) -> bool:
    """Проверка, что урок в области видимости пользователя с изоляцией прав."""
    if not current_user.is_authenticated:
        return False
    user_role = getattr(current_user, 'role', '')
    sb_role = session.get('sandbox_role', '')
    if user_role in ['creator', 'admin', 'chief_admin'] or sb_role in ['creator', 'admin'] or current_user.is_creator() or current_user.is_admin():
        return True

    from app.schedule.ownership_service import can_user_modify_lesson, can_user_view_lesson

    # Серверная изоляция для преподавателей (чтение и запись)
    if current_user.is_tutor():
        if getattr(lesson, 'lesson_id', None) is None and getattr(lesson, 'teacher_id', None) is None:
            from app.schedule.ownership_service import get_active_tutor_ids_for_student
            student = db.session.get(Student, lesson.student_id) if lesson.student_id else None
            return bool(student and current_user.id in get_active_tutor_ids_for_student(student))

        if require_write:
            allowed_write, _ = can_user_modify_lesson(current_user, lesson)
            return allowed_write
        else:
            allowed_read, _ = can_user_view_lesson(current_user, lesson)
            return allowed_read

    # Серверная изоляция для учеников
    if current_user.is_student():
        student = Student.query.filter_by(user_id=current_user.id).first()
        if not student:
            return False
        if require_write:
            return False  # Ученик не имеет прав на редактирование/удаление уроков
        return int(lesson.student_id) == int(student.student_id)

    # Родители и общие роли
    allowed = _resolve_accessible_student_ids_for_current_user()
    if allowed is None:
        return True
    return bool(allowed and lesson.student_id in allowed)


def _purge_lessons_dependencies(lesson_ids: list[int]) -> None:
    """
    Очищает и отвязывает все зависимые сущности перед удалением записей уроков.
    Предотвращает ошибки нарушения внешних ключей (ForeignKeyViolation) в PostgreSQL.
    """
    if not lesson_ids:
        return

    # 1. Задания к уроку и их вложенные сущности (комментарии, попытки)
    lt_rows = db.session.query(LessonTask.lesson_task_id).filter(LessonTask.lesson_id.in_(lesson_ids)).all()
    lt_ids = [r[0] for r in lt_rows if r and r[0]]
    if lt_ids:
        LessonTaskTeacherComment.query.filter(LessonTaskTeacherComment.lesson_task_id.in_(lt_ids)).delete(synchronize_session=False)
        LessonTaskAttempt.query.filter(LessonTaskAttempt.lesson_task_id.in_(lt_ids)).delete(synchronize_session=False)
        LessonTask.query.filter(LessonTask.lesson_task_id.in_(lt_ids)).delete(synchronize_session=False)

    # 2. Доски Miro, итоги занятий, материалы, уведомления, сообщения и заметки
    LessonWhiteboard.query.filter(LessonWhiteboard.lesson_id.in_(lesson_ids)).delete(synchronize_session=False)
    LessonOutcome.query.filter(LessonOutcome.lesson_id.in_(lesson_ids)).delete(synchronize_session=False)
    LessonMaterialLink.query.filter(LessonMaterialLink.lesson_id.in_(lesson_ids)).delete(synchronize_session=False)
    PendingAssignmentNotification.query.filter(PendingAssignmentNotification.lesson_id.in_(lesson_ids)).delete(synchronize_session=False)
    LessonMessage.query.filter(LessonMessage.lesson_id.in_(lesson_ids)).delete(synchronize_session=False)
    LessonTeacherHomeworkNote.query.filter(LessonTeacherHomeworkNote.lesson_id.in_(lesson_ids)).delete(synchronize_session=False)

    # 3. Обнуление nullable-ссылок на уроки
    LearningError.query.filter(LearningError.lesson_id.in_(lesson_ids)).update({'lesson_id': None}, synchronize_session=False)
    LearningItem.query.filter(LearningItem.lesson_id.in_(lesson_ids)).update({'lesson_id': None}, synchronize_session=False)
    Assignment.query.filter(Assignment.lesson_id.in_(lesson_ids)).update({'lesson_id': None}, synchronize_session=False)
    GradebookEntry.query.filter(GradebookEntry.lesson_id.in_(lesson_ids)).update({'lesson_id': None}, synchronize_session=False)

def _parse_date(value: str | None):
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except Exception:
        return None

def _dt_to_ics_utc(value: datetime) -> str:
    """Сериализация момента урока в обязательный UTC-формат iCalendar."""
    dt = lesson_storage_to_utc(value) or datetime.now(dt_timezone.utc)
    return dt.strftime('%Y%m%dT%H%M%SZ')


def _dt_to_ics_local(value: datetime, timezone: str) -> str:
    """
    Возвращаем datetime в локальной таймзоне (без 'Z'), чтобы импорт в Google Calendar
    совпадал с отображением в UI (wall time).
    """
    local = lesson_storage_to_local(value, timezone)
    return local.strftime('%Y%m%dT%H%M%S') if local else ''


def _lessons_in_local_window(query, timezone: str, start_day: date, end_day: date):
    """Фильтрует уроки по датам зрителя без небезопасного смешения aware/naive SQL."""
    result = []
    for lesson in query.all():
        local = lesson_storage_to_local(lesson.lesson_date, timezone)
        if local and start_day <= local.date() <= end_day:
            result.append(lesson)
    return result


def _is_lesson_test(lesson) -> bool:
    """Определить, относится ли урок к тестовому слою."""
    if not lesson:
        return False
    notes = str(getattr(lesson, 'notes', '') or '')
    if '__NOT_TEST__' in notes:
        return False
    if getattr(lesson, 'lesson_type', None) and str(lesson.lesson_type).strip().lower() == 'test':
        return True
    if '__TEST__' in notes:
        return True
    topic = str(getattr(lesson, 'topic', '') or '')
    if re.search(r'(?i)(тест|test|проверк|poyasa)', topic):
        return True
    return False


def _extract_clean_lesson_datetime(raw_date: str, raw_time: str, tz_name: str | None, start_time_utc: str | None = None) -> datetime:
    """Извлечь дату и время без поломки часовых поясов и вернуть UTC aware datetime."""
    # 1. Если клиент явно прислал start_time_utc в ISO формате с Z или offset
    if start_time_utc and isinstance(start_time_utc, str):
        parsed = to_utc_instant(start_time_utc.strip())
        if parsed:
            return parsed

    raw_date_str = str(raw_date or '').strip()
    raw_time_str = str(raw_time or '').strip()

    # 2. Если raw_date_str сам по себе является ISO строкой с Z или смещением (+/-)
    if 'Z' in raw_date_str or 'z' in raw_date_str or ('+' in raw_date_str and 'T' in raw_date_str):
        parsed = to_utc_instant(raw_date_str)
        if parsed:
            return parsed

    # 3. Если передан локальный ввод (дата + время + таймзона)
    tz_canonical = canonical_timezone_name(tz_name or 'Europe/Moscow')

    if 'T' in raw_date_str:
        parts = raw_date_str.split('T')
        date_part = parts[0].strip()
        time_part = raw_time_str or parts[1][:5].strip()
    elif ' ' in raw_date_str:
        parts = raw_date_str.split(' ', 1)
        date_part = parts[0].strip()
        time_part = raw_time_str or parts[1][:5].strip()
    else:
        date_part = raw_date_str
        time_part = raw_time_str or '12:00'

    if not time_part:
        time_part = '12:00'
    elif len(time_part) > 5 and ':' in time_part[:5]:
        time_part = time_part[:5]

    return parse_local_to_utc(date_part, time_part, tz_canonical)


def _parse_local_datetime(date_str: str, time_str: str, timezone: str, start_time_utc: str | None = None):
    return _extract_clean_lesson_datetime(date_str, time_str, timezone, start_time_utc=start_time_utc)


def _student_has_overlap(student_id: int, start_dt: datetime, duration_min: int, exclude_lesson_id: int | None = None) -> bool:
    if not student_id or not start_dt or not duration_min:
        return False
    start_dt_utc = lesson_storage_to_utc(start_dt)
    end_dt_utc = lesson_storage_to_utc(start_dt + timedelta(minutes=duration_min))
    if not start_dt_utc or not end_dt_utc:
        return False

    # Lesson.lesson_date is stored as naive Moscow wall time, while the
    # comparison below is UTC-aware. Filtering by UTC values in SQL would
    # silently miss the same lesson in Tomsk and other user time zones.
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
        if _is_lesson_test(l):
            continue
        l_start = lesson_storage_to_utc(l.lesson_date)
        l_end = lesson_storage_to_utc(l.lesson_date + timedelta(minutes=int(l.duration or 60)))
        if not l_start or not l_end:
            continue
        if (l_start < end_dt_utc) and (start_dt_utc < l_end):
            return True

    return False


def _student_parent_user_ids(student_id: int | None) -> list[int]:
    if not student_id:
        return []
    try:
        student = Student.query.get(student_id)
        if not student or not student.user_id:
            return []
        return [int(pid) for pid in get_parent_user_ids_for_student(int(student.user_id))]
    except Exception:
        return []


def _lesson_local_time_for_user(lesson: Lesson, user_id: int | None) -> str:
    if not lesson or not lesson.lesson_date:
        return '—'
    try:
        recipient = User.query.filter_by(id=user_id).first() if user_id else None
        tz_name = effective_timezone_name(recipient) if recipient else 'Europe/Moscow'
        dt = lesson_storage_to_local(lesson.lesson_date, tz_name)
        return dt.strftime('%d.%m.%Y %H:%M') if dt else (lesson.lesson_date.strftime('%d.%m.%Y %H:%M') if lesson.lesson_date else '—')
    except Exception:
        return lesson.lesson_date.strftime('%d.%m.%Y %H:%M')


def _absolute_app_url(path: str) -> str:
    base = (os.environ.get('APP_URL') or '').rstrip('/')
    if base:
        return f'{base}{path}'
    return path


def _notify_lesson_scheduled(lesson: Lesson, student: Student, headline: str, actor_user_id: int | None = None, old_dt: datetime | None = None) -> None:
    """Direct Telegram delivery for lesson creation/reschedule with rich notification format."""
    try:
        from app.telegram.delivery import invalidate_pending_lesson_deliveries
        is_reschedule = 'перенес' in (headline or '').lower()
        if is_reschedule:
            invalidate_pending_lesson_deliveries(lesson.lesson_id, reason='lesson_rescheduled')

        topic = (lesson.topic or '').strip() or 'Занятие по расписанию'
        lesson_url = _absolute_app_url(url_for('lessons.lesson_view', lesson_id=lesson.lesson_id))

        from app.models import User
        tutor_user = User.query.get(actor_user_id) if actor_user_id else None
        tutor_name = tutor_user.username if tutor_user else 'Преподаватель'
        student_name = getattr(student, 'name', None) or 'Ученик'

        kind = 'lesson_rescheduled' if is_reschedule else 'lesson_scheduled'
        from app.notifications.service import notify_user

        meta = {
            'lesson_id': lesson.lesson_id,
            'topic': topic,
            'subject': getattr(lesson, 'subject', 'Информатика') or 'Информатика',
            'start_time': lesson.lesson_date,
            'teacher_name': tutor_name,
            'student_name': student_name,
            'student_id': getattr(student, 'student_id', None),
            'student_user_id': getattr(student, 'user_id', None),
            'actor_user_id': actor_user_id,
            'actor_role': getattr(tutor_user, 'role', 'teacher') if tutor_user else 'teacher',
        }
        if old_dt:
            meta['old_start_time'] = old_dt

        lesson_teacher_id = lesson.teacher_id or (actor_user_id if tutor_user and tutor_user.is_tutor() else None)

        # Notify tutor (suppressed if tutor is actor)
        if lesson_teacher_id:
            teacher_meta = dict(meta)
            teacher_meta['recipient_role'] = 'teacher'
            notify_user(int(lesson_teacher_id), kind=kind, title=headline, link_url=lesson_url, meta=teacher_meta)

        # Notify student
        if student and getattr(student, 'user_id', None):
            student_meta = dict(meta)
            student_meta['recipient_role'] = 'student'
            notify_user(int(student.user_id), kind=kind, title=headline, link_url=lesson_url, meta=student_meta)

        # Notify parents
        for parent_id in _student_parent_user_ids(student.student_id if student else None):
            parent_meta = dict(meta)
            parent_meta['parent_id'] = int(parent_id)
            parent_meta['recipient_role'] = 'parent'
            notify_user(int(parent_id), kind=kind, title=headline, link_url=lesson_url, meta=parent_meta)

        try:
            db.session.commit()
        except Exception as commit_err:
            db.session.rollback()
            logger.warning('Could not commit lesson_scheduled notifications: %s', commit_err)
    except Exception as e:
        logger.warning('Direct lesson_scheduled notify failed: %s', e)


def _notify_lesson_cancelled(lesson: Lesson, student: Student, reason: str = 'Урок отменён', actor_user_id: int | None = None) -> None:
    """Notify student, teacher, and parents about a cancelled lesson, invalidating stale reminders."""
    try:
        from app.telegram.delivery import invalidate_pending_lesson_deliveries
        invalidate_pending_lesson_deliveries(lesson.lesson_id, reason='lesson_cancelled')

        topic = (lesson.topic or '').strip() or 'Занятие по расписанию'
        from app.models import User
        actor_user = User.query.get(actor_user_id) if actor_user_id else None
        teacher_name = 'Преподаватель'
        if lesson.teacher_id:
            tch = User.query.get(lesson.teacher_id)
            if tch:
                teacher_name = tch.username or 'Преподаватель'

        student_name = getattr(student, 'name', None) or 'Ученик'
        meta = {
            'lesson_id': lesson.lesson_id,
            'topic': topic,
            'subject': getattr(lesson, 'subject', 'Информатика') or 'Информатика',
            'start_time': lesson.lesson_date,
            'teacher_name': teacher_name,
            'student_name': student_name,
            'reason': reason,
            'student_id': getattr(student, 'student_id', None),
            'student_user_id': getattr(student, 'user_id', None),
            'actor_user_id': actor_user_id,
            'actor_role': getattr(actor_user, 'role', 'teacher') if actor_user else 'teacher',
        }

        from app.notifications.service import notify_user
        headline = 'Урок отменён'

        # Notify teacher
        if lesson.teacher_id:
            teacher_meta = dict(meta)
            teacher_meta['recipient_role'] = 'teacher'
            notify_user(int(lesson.teacher_id), kind='lesson_cancelled', title=headline, meta=teacher_meta)

        # Notify student
        if student and getattr(student, 'user_id', None):
            student_meta = dict(meta)
            student_meta['recipient_role'] = 'student'
            notify_user(int(student.user_id), kind='lesson_cancelled', title=headline, meta=student_meta)

        # Notify parents
        for parent_id in _student_parent_user_ids(student.student_id if student else None):
            parent_meta = dict(meta)
            parent_meta['parent_id'] = int(parent_id)
            parent_meta['recipient_role'] = 'parent'
            notify_user(int(parent_id), kind='lesson_cancelled', title=headline, meta=parent_meta)

        try:
            db.session.commit()
        except Exception as commit_err:
            db.session.rollback()
            logger.warning('Could not commit lesson_cancelled notifications: %s', commit_err)
    except Exception as e:
        logger.warning('Direct lesson_cancelled notify failed: %s', e)


def notify_scheduled_lessons_batch(
    lessons: list[Lesson],
    student: Student,
    actor_user_id: int | None = None,
    headline: str = 'Новый урок запланирован',
) -> None:
    """Grouped notification dispatch for batch lesson creation.
    
    If >= 3 planned lessons are scheduled at once, emits a single grouped
    card (lesson_batch_scheduled) and suppresses individual cards.
    If < 3 lessons, emits individual cards.
    In-app UserNotification is preserved for both.
    """
    if not lessons or not student:
        return

    planned = [l for l in lessons if getattr(l, 'status', None) == 'planned']
    if not planned:
        return

    from app.telegram.batching import BATCH_THRESHOLD, process_scheduled_lessons_batch
    from app.telegram.delivery import enqueue_delivery
    from app.telegram.user_notify import is_notification_enabled_for_user
    from app.models import UserNotification
    import uuid

    if len(planned) < BATCH_THRESHOLD:
        for l in planned:
            _notify_lesson_scheduled(l, student, headline, actor_user_id=actor_user_id)
        return

    batch_id = f"batch_{uuid.uuid4().hex[:12]}"
    from app.models import User
    actor_user = User.query.get(actor_user_id) if actor_user_id else None
    teacher_name = 'Преподаватель'
    if planned[0].teacher_id:
        tch = User.query.get(planned[0].teacher_id)
        if tch:
            teacher_name = tch.username or 'Преподаватель'
    elif actor_user:
        teacher_name = actor_user.username or 'Преподаватель'

    schedule_url = _absolute_app_url(url_for('schedule.schedule'))
    lessons_data = [
        {
            'lesson_id': l.lesson_id,
            'topic': l.topic or l.subject or 'Занятие',
            'start_time': l.lesson_date,
            'lesson_date': l.lesson_date,
        }
        for l in planned
    ]

    # 1. Student Delivery
    if getattr(student, 'user_id', None):
        st_uid = int(student.user_id)
        st_notif = UserNotification(
            user_id=st_uid,
            kind='lesson_batch_scheduled',
            title=f'Запланировано {len(planned)} занятий',
            body=f'Преподаватель {teacher_name} запланировал {len(planned)} уроков в расписании.',
            link_url=schedule_url,
            meta={'batch_id': batch_id, 'lessons_count': len(planned), 'teacher_name': teacher_name},
        )
        db.session.add(st_notif)
        db.session.flush()

        if st_uid != actor_user_id:
            if is_notification_enabled_for_user(st_uid, role='student', kind='lesson_batch_scheduled'):
                cards = process_scheduled_lessons_batch(
                    recipient_user_id=st_uid,
                    teacher_name=teacher_name,
                    lessons_data=lessons_data,
                    batch_id=batch_id,
                    recipient_role='student',
                    schedule_url=schedule_url,
                )
                for item in cards:
                    enqueue_delivery(
                        st_uid,
                        item['text'],
                        kind='lesson_batch_scheduled',
                        notification_id=st_notif.notification_id,
                        reply_markup=item['reply_markup'],
                        meta=item.get('meta'),
                        dedupe_key=item.get('dedupe_key'),
                        priority='normal',
                    )

    # 2. Parent Delivery
    for parent_id in _student_parent_user_ids(student.student_id if student else None):
        p_uid = int(parent_id)
        p_notif = UserNotification(
            user_id=p_uid,
            kind='lesson_batch_scheduled',
            title=f'Назначено {len(planned)} занятий у ребёнка',
            body=f'Преподаватель {teacher_name} запланировал {len(planned)} уроков.',
            link_url=schedule_url,
            meta={'batch_id': batch_id, 'lessons_count': len(planned), 'teacher_name': teacher_name, 'student_id': student.student_id},
        )
        db.session.add(p_notif)
        db.session.flush()

        if p_uid != actor_user_id:
            if is_notification_enabled_for_user(p_uid, role='parent', kind='lesson_batch_scheduled'):
                p_cards = process_scheduled_lessons_batch(
                    recipient_user_id=p_uid,
                    teacher_name=teacher_name,
                    lessons_data=lessons_data,
                    batch_id=batch_id,
                    recipient_role='parent',
                    schedule_url=schedule_url,
                    student_name=student.name if student else None,
                )
                for item in p_cards:
                    enqueue_delivery(
                        p_uid,
                        item['text'],
                        kind='lesson_batch_scheduled',
                        notification_id=p_notif.notification_id,
                        reply_markup=item['reply_markup'],
                        meta=item.get('meta'),
                        dedupe_key=item.get('dedupe_key'),
                        priority='normal',
                    )

    try:
        db.session.commit()
    except Exception as commit_err:
        db.session.rollback()
        logger.warning('Could not commit batch lesson notifications: %s', commit_err)



def _tutor_has_overlap(tutor_user_id: int, start_dt: datetime, duration_min: int, exclude_lesson_id: int | None = None) -> bool:
    """
    Проверка пересечения по преподавателю (чтобы не поставить 2 урока одновременно).
    Использует строгую изоляцию уроков конкретного преподавателя (без ложных блокировок от чужих уроков общих учеников).
    """
    from app.schedule.ownership_service import check_tutor_conflict_isolated
    return check_tutor_conflict_isolated(tutor_user_id, start_dt, duration_min, exclude_lesson_id)


def _is_technical_teacher_login(name: str) -> bool:
    if not name:
        return True
    lower = name.strip().lower()
    if any(prefix in lower for prefix in ['qa_pool', 'pool_teacher', 'test_evo', 'synth_', 'mock_']):
        return True
    if lower.startswith(('user_', 'student_', 'teacher_')) and any(c.isdigit() for c in lower):
        return True
    if '_' in name and ' ' not in name:
        return True
    return False


def _resolve_human_teacher_name(user_obj) -> str:
    if not user_obj:
        return 'Преподаватель курса'
    if hasattr(user_obj, 'id'):
        from core.db_models import UserProfile
        prof = UserProfile.query.filter_by(user_id=user_obj.id).first()
        if prof:
            first = (prof.first_name or '').strip()
            last = (prof.last_name or '').strip()
            cand_full = f"{first} {last}".strip()
            if cand_full and not _is_technical_teacher_login(cand_full):
                return cand_full
            if first and not _is_technical_teacher_login(first):
                return first
            disp = (getattr(prof, 'display_name', None) or '').strip()
            if disp and not _is_technical_teacher_login(disp):
                return disp
    fn = (getattr(user_obj, 'full_name', None) or '').strip()
    if fn and not _is_technical_teacher_login(fn):
        return fn
    uname = (getattr(user_obj, 'username', None) or '').strip()
    if uname and not _is_technical_teacher_login(uname):
        return uname
    return 'Преподаватель курса'


@schedule_bp.route('/schedule/preview/temporal-canvas')
@login_required
def schedule_preview_temporal_canvas():
    """Sprint 2.7 Temporal Canvas Preview (Zero production risk, read-only isolated preview)"""
    return schedule(preview_template='sandbox/teacher_schedule_temporal_canvas.html')


@schedule_bp.route('/schedule')
@login_required
def schedule(preview_template=None):
    """Расписание уроков"""
    user_role = (getattr(current_user, 'role', '') or '').lower()
    sb_role = (session.get('sandbox_role', '') or '').lower()
    allowed_roles = {'teacher', 'tutor', 'creator', 'admin', 'chief_admin', 'student', 'parent'}
    
    if not (user_role in allowed_roles or sb_role in allowed_roles or (current_user and current_user.is_authenticated and (current_user.is_creator() or current_user.is_admin()))):
        if not has_permission(current_user, 'schedule.view') and not has_permission(current_user, 'tools.schedule'):
            flash('У вас недостаточно прав для просмотра расписания.', 'danger')
            return redirect(url_for('main.dashboard'))

    try:
        week_offset = int(request.args.get('week', 0))
    except (ValueError, TypeError):
        week_offset = 0
    # Enforce safe navigation boundaries (+/- 2 years = 104 weeks) to prevent date overflow / excessive load
    week_offset = max(-104, min(104, week_offset))
    view_mode = (request.args.get('view') or 'week').strip().lower()
    if view_mode not in ('week', 'agenda', 'day', 'month'):
        view_mode = 'week'
    status_filter = request.args.get('status', '')
    category_filter = request.args.get('category', '')
    # Время зрителя: query-параметр имеет приоритет (для быстрого переключения в шапке), иначе профиль
    timezone = (request.args.get('timezone') or _schedule_timezone_from_user()).strip()
    student_filter = request.args.get('student_id', type=int)

    timezone = timezone_name(timezone)
    display_tz = timezone_from_name(timezone)

    today = datetime.now(dt_timezone.utc).astimezone(display_tz).date()
    month_weeks = []
    month_start = None
    month_end = None
    day_names = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

    if view_mode in ('week', 'agenda'):
        week_start = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
        week_days = [week_start + timedelta(days=i) for i in range(7)]
        week_end = week_days[-1]
        period_start = week_start
        period_end = week_end
        if week_days[0].month == week_days[-1].month and week_days[0].year == week_days[-1].year:
            week_label = f"{week_days[0].day} — {week_days[-1].day} {RU_MONTHS_GEN[week_days[-1].month - 1]} {week_days[-1].year}"
        elif week_days[0].year == week_days[-1].year:
            week_label = f"{week_days[0].day} {RU_MONTHS_GEN[week_days[0].month - 1]} — {week_days[-1].day} {RU_MONTHS_GEN[week_days[-1].month - 1]} {week_days[-1].year}"
        else:
            week_label = f"{week_days[0].day} {RU_MONTHS_GEN[week_days[0].month - 1]} {week_days[0].year} — {week_days[-1].day} {RU_MONTHS_GEN[week_days[-1].month - 1]} {week_days[-1].year}"
    elif view_mode == 'day':
        day_date = today + timedelta(days=week_offset)
        week_start = day_date
        week_days = [day_date]
        week_end = day_date
        period_start = day_date
        period_end = day_date
        week_label = f"{day_date.day:02d} {RU_MONTHS_GEN[day_date.month - 1]} {day_date.year}"
    else:
        month_start = _add_months(today.replace(day=1), week_offset)
        month_end = _add_months(month_start, 1) - timedelta(days=1)
        week_start = month_start
        week_end = month_end
        week_days = []
        period_start = month_start
        period_end = month_end
        week_label = f"{RU_MONTHS_NOM[month_start.month - 1]} {month_start.year}"

    slot_minutes = request.args.get('slot', 30, type=int)
    slot_minutes = slot_minutes if slot_minutes in (15, 30, 60) else 30
    day_start_hour = request.args.get('start', 0, type=int)
    day_end_hour = request.args.get('end', 23, type=int)
    if day_start_hour < 0:
        day_start_hour = 0
    if day_end_hour > 23:
        day_end_hour = 23
    if day_end_hour < day_start_hour:
        day_start_hour, day_end_hour = 7, 22
    total_minutes = (day_end_hour - day_start_hour + 1) * 60
    total_slots = int(total_minutes / slot_minutes)
    time_labels = [f"{hour:02d}:00" for hour in range(day_start_hour, day_end_hour + 1)]

    user_role = getattr(current_user, 'role', '') if current_user and current_user.is_authenticated else ''
    sb_role = session.get('sandbox_role', '')
    is_creator = (user_role in ['creator', 'admin', 'chief_admin'] or sb_role in ['creator', 'admin'] or (current_user and current_user.is_authenticated and current_user.is_creator()))

    allowed_student_ids = _resolve_accessible_student_ids_for_current_user()
    if is_creator:
        query = Lesson.query.order_by(Lesson.lesson_date.desc())
    elif current_user.is_tutor():
        # Строгая изоляция: преподаватель видит только свои уроки
        query = Lesson.query.filter(Lesson.teacher_id == current_user.id).order_by(Lesson.lesson_date.desc())
    elif current_user.is_student():
        st_user = Student.query.filter_by(user_id=current_user.id).first()
        if st_user:
            query = Lesson.query.filter(Lesson.student_id == st_user.student_id).order_by(Lesson.lesson_date.desc())
        else:
            query = Lesson.query.filter(False)
    else:
        query = Lesson.query.order_by(Lesson.lesson_date.desc())
        if allowed_student_ids is not None:
            if not allowed_student_ids:
                query = query.filter(False)
            else:
                query = query.filter(Lesson.student_id.in_(allowed_student_ids))

    if status_filter:
        query = query.filter_by(status=status_filter)

    if category_filter:
        query = query.join(Student).filter(Student.category == category_filter)

    if student_filter:
        if allowed_student_ids is not None and student_filter not in allowed_student_ids:
            flash('Доступ запрещен.', 'danger')
            return redirect(url_for('schedule.schedule', week=week_offset, timezone=timezone))
        query = query.filter(Lesson.student_id == student_filter)

    # SQL-level half-open intervals to prevent unbounded full-table scans.
    # Buffer +/- 2 days around period_start/period_end covers all possible viewer timezones (UTC-12 to UTC+14)
    sql_window_start = datetime.combine(period_start - timedelta(days=2), time.min)
    sql_window_end = datetime.combine(period_end + timedelta(days=2), time.max)
    query = query.filter(
        Lesson.lesson_date >= sql_window_start,
        Lesson.lesson_date <= sql_window_end
    )

    lessons = query.options(db.joinedload(Lesson.student)).all()

    real_events = []
    for lesson in lessons:
        if not lesson.lesson_date:
            continue
        lesson_date_display = lesson_storage_to_local(lesson.lesson_date, timezone)
        lesson_date_local = lesson_date_display.date()
        day_index = (lesson_date_local - week_start).days
        
        if day_index < 0 or day_index >= 7:
            logger.debug(f"Урок {lesson.lesson_id} вне недели: lesson_date={lesson.lesson_date}, "
                        f"lesson_date_local={lesson_date_local}, week_start={week_start}, day_index={day_index}")
            continue
        
        if 0 <= day_index < 7:
            start_time = lesson_date_display.time()
            end_datetime = lesson_date_display + timedelta(minutes=lesson.duration)
            end_time = end_datetime.time()
            status_text = {'planned': 'Запланирован', 'in_progress': 'Идет сейчас', 'completed': 'Проведен', 'cancelled': 'Отменен'}.get(lesson.status, lesson.status)
            if not lesson.student:
                continue  # Пропускаем уроки без студента
            profile_url = url_for('students.student_profile', student_id=lesson.student.student_id)
            real_events.append({
                'lesson_id': lesson.lesson_id,
                'student': lesson.student.name,
                'student_id': lesson.student.student_id,
                'subject': lesson.subject or 'Информатика',
                'grade': f"{lesson.student.school_class} класс" if lesson.student.school_class else (lesson.student.category or 'Не указано'),
                'status': status_text,
                'status_code': lesson.status,
                'day_index': day_index,
                'start': start_time,
                'end': end_time,
                'start_time': start_time.strftime('%H:%M'),
                'profile_url': profile_url,
                'topic': lesson.topic,
                'lesson_type': lesson.lesson_type,
                'duration_minutes': int(lesson.duration or 60)  # Сохраняем исходную длительность из БД
            })

    day_columns_count = len(week_days) if view_mode in ('week', 'day') else 0
    day_events = {i: [] for i in range(day_columns_count)}
    day_start_minutes = day_start_hour * 60

    for event in real_events:
        duration_minutes = event.get('duration_minutes', 60)
        duration_minutes = max(duration_minutes, slot_minutes)
        event['start_total'] = event['start'].hour * 60 + event['start'].minute
        end_hour = event['end'].hour
        end_minute = event['end'].minute
        if end_hour * 60 + end_minute < event['start_total']:
            event['end_total'] = 1440
        else:
            event['end_total'] = end_hour * 60 + end_minute
        event['duration_minutes'] = duration_minutes
        if day_columns_count and event['day_index'] in day_events:
            day_events[event['day_index']].append(event)

    for day_index, events in day_events.items():
        events.sort(key=lambda e: (e['start_total'], e['end_total']))
        active = []
        max_columns = 1
        for event in events:
            current_start = event['start_total']
            active = [a for a in active if a['end_total'] > current_start]
            used_columns = {a['column_index'] for a in active}
            column_index = 0
            while column_index in used_columns:
                column_index += 1
            event['column_index'] = column_index
            active.append(event)
            max_columns = max(max_columns, len(active))
        for event in events:
            event['columns_total'] = max_columns
            column_width = 100 / max_columns
            event['left_percent'] = column_width * event['column_index']
            event['width_percent'] = max(column_width - 1.5, 8)

    day_events_json = {i: [] for i in range(day_columns_count)}
    for day_index, events in day_events.items():
        for event in events:
            json_event = {
                'lesson_id': event['lesson_id'],
                'student': event['student'],
                'student_id': event['student_id'],
                'subject': event['subject'],
                'grade': event['grade'],
                'status': event['status'],
                'status_code': event['status_code'],
                'lesson_type': event.get('lesson_type'),
                'topic': event.get('topic'),
                'start_time': event['start_time'],
                'profile_url': event['profile_url'],
                'lesson_url': url_for('lessons.lesson_view', lesson_id=event['lesson_id']),
                'start_total': event['start_total'],
                'duration_minutes': event.get('duration_minutes') or 60,
                'left_percent': event['left_percent'],
                'width_percent': event['width_percent']
            }
            json_event['is_conflict'] = bool((event.get('columns_total') or 1) > 1)
            day_events_json[day_index].append(json_event)

    month_lessons_map = {}
    if view_mode == 'month' and month_start and month_end:
        for l in lessons:
            if not l.student:
                continue
            dt = lesson_storage_to_local(l.lesson_date, timezone)
            day_key = dt.date().isoformat()
            month_lessons_map.setdefault(day_key, []).append({
                'time': dt.strftime('%H:%M'),
                'student_name': l.student.name,
                'status': l.status,
                'lesson_url': url_for('lessons.lesson_view', lesson_id=l.lesson_id),
            })

        grid_start = month_start - timedelta(days=month_start.weekday())
        grid_end = month_end + timedelta(days=(6 - month_end.weekday()))
        cursor = grid_start
        while cursor <= grid_end:
            week_cells = []
            for _ in range(7):
                iso = cursor.isoformat()
                items = month_lessons_map.get(iso, [])
                week_cells.append({
                    'date': cursor,
                    'iso': iso,
                    'in_month': cursor.month == month_start.month,
                    'is_today': cursor == today,
                    'day_name': day_names[cursor.weekday()],
                    'events': items[:3],
                    'events_count': len(items),
                })
                cursor += timedelta(days=1)
            month_weeks.append(week_cells)

    # Ученики для модалки создания урока и селектов расписания
    from app.schedule.ownership_service import get_accessible_students_for_teacher
    accessible_students_data = get_accessible_students_for_teacher(current_user)
    accessible_sids = [s['student_id'] for s in accessible_students_data]
    if current_user.is_tutor():
        students = Student.query.filter(Student.student_id.in_(accessible_sids)).order_by(Student.name.asc()).all() if accessible_sids else []
    elif is_creator and request.args.get('view') == 'all':
        students = Student.query.filter_by(is_active=True).order_by(Student.name.asc()).all()
    else:
        students = Student.query.filter(Student.student_id.in_(accessible_sids)).order_by(Student.name.asc()).all() if accessible_sids else []
    statuses = ['planned', 'in_progress', 'completed', 'cancelled']
    categories = ['ЕГЭ', 'ОГЭ', 'ЛЕВЕЛАП', 'ПРОГРАММИРОВАНИЕ']

    agenda = []
    try:
        for l in lessons:
            if not l.student or not l.lesson_date:
                continue
            dt_display = lesson_storage_to_local(l.lesson_date, timezone)
            agenda.append({
                'lesson_id': l.lesson_id,
                'date': dt_display.strftime('%Y-%m-%d'),
                'time': dt_display.strftime('%H:%M'),
                'date_human': dt_display.strftime('%d.%m.%Y'),
                'student_name': l.student.name,
                'student_id': l.student.student_id,
                'status': l.status,
                'topic': l.topic,
                'duration': int(l.duration or 60),
                'lesson_url': url_for('lessons.lesson_view', lesson_id=l.lesson_id),
                'profile_url': url_for('students.student_profile', student_id=l.student.student_id),
            })
    except Exception:
        agenda = []

    agenda_week_sidebar = agenda
    try:
        if view_mode == 'week' and (not status_filter) and (current_user.is_student() or current_user.is_tutor()):
            agenda_week_sidebar = [a for a in (agenda or []) if (a.get('status') or '').lower() != 'planned']
    except Exception:
        agenda_week_sidebar = agenda

    today_display_date = moscow_now().astimezone(display_tz).date()

    if preview_template:
        tpl_name = preview_template
    elif request.args.get('legacy') == '1':
        tpl_name = 'sandbox/student_schedule.html' if current_user.is_student() else 'sandbox/teacher_schedule.html'
    else:
        tpl_name = 'sandbox/student_schedule.html' if current_user.is_student() else 'sandbox/teacher_schedule_temporal_canvas.html'
    
    raw_lessons_payload = []
    for l in lessons:
        if not l.lesson_date:
            continue
        local_start = lesson_storage_to_local(l.lesson_date, timezone)
        utc_instant = lesson_storage_to_utc(l.lesson_date)
        duration_minutes = int(l.duration or 60)
        local_end = local_start + timedelta(minutes=duration_minutes)
        raw_lessons_payload.append({
            'lesson_id': l.lesson_id,
            'student_name': l.student.name if l.student else 'Ученик',
            'student_id': l.student_id,
            'lesson_date': format_utc_iso_z(utc_instant),
            'start_iso': format_utc_iso_z(utc_instant),
            'start_date': local_start.date().isoformat(),
            'start_time': local_start.strftime('%H:%M'),
            'end_time': local_end.strftime('%H:%M'),
            'grid_top': local_start.hour * 60 + local_start.minute,
            'topic': l.topic or 'Занятие',
            'notes': l.notes or '',
            'student_notes': l.student_notes or '',
            'homework': l.homework or '',
            'materials': l.materials if l.materials else [],
            'description': l.notes or (f'Урок по теме «{l.topic}». Разбор теории и типовых заданий ЕГЭ.' if l.topic else 'Занятие по расписанию.'),
            'duration_minutes': duration_minutes,
            'status': l.status or 'planned',
            'lesson_type': l.lesson_type or 'individual',
            'is_test': _is_lesson_test(l),
            'room_url': url_for('lessons.lesson_interactive_room', lesson_id=l.lesson_id),
            'teacher_id': l.teacher_id,
            'subject': l.subject or 'Информатика',
            'recurring_slot_id': l.recurring_slot_id,
            'is_recurring': bool(l.recurring_slot_id),
            'is_rescheduled': bool(l.is_rescheduled),
            'slot_origin_date': l.slot_origin_date.isoformat() if l.slot_origin_date else None,
        })

    active_homework = []
    useful_materials = []
    seen_material_titles = set()
    student_notes_text = ''
    teacher_name = None
    teacher_avatar = None
    student_tutors_map = {}

    if current_user.is_authenticated and current_user.is_student():
        from app.models import Submission, Assignment
        st_obj = Student.query.filter_by(user_id=current_user.id).first()
        if not st_obj:
            cand = Student.query.get(current_user.id)
            if cand and cand.user_id is None:
                st_obj = cand
        if st_obj:
            try:
                from core.db_models import Enrollment
                user_id_val = getattr(st_obj, 'user_id', None) or current_user.id
                student_id_val = getattr(st_obj, 'student_id', None)
                enr_conditions = [Enrollment.student_id == user_id_val]
                if student_id_val and student_id_val != user_id_val:
                    enr_conditions.append(Enrollment.student_id == student_id_val)
                enrollments = Enrollment.query.filter(db.or_(*enr_conditions)).all()
                for enr in enrollments:
                    if getattr(enr, 'tutor_id', None):
                        t_user = User.query.get(enr.tutor_id)
                        if t_user:
                            student_tutors_map[enr.tutor_id] = t_user
            except Exception:
                pass

            if getattr(st_obj, 'mentor_id', None) and st_obj.mentor_id not in student_tutors_map:
                m_user = User.query.get(st_obj.mentor_id)
                if m_user:
                    student_tutors_map[st_obj.mentor_id] = m_user

            if len(student_tutors_map) == 1:
                sole_teacher = next(iter(student_tutors_map.values()))
                teacher_name = _resolve_human_teacher_name(sole_teacher)
                teacher_avatar = getattr(sole_teacher, 'avatar_url', None) or '/static/images/default-avatar.svg'
            elif len(student_tutors_map) > 1:
                # Multi-teacher scenario: prevent false attribution of an arbitrary teacher
                teacher_name = None
                teacher_avatar = None
            else:
                teacher_name = None
                teacher_avatar = None

            # Homework fetching with deduplication, timezone-aware deadlines and status support
            seen_assignment_ids = set()
            try:
                subs = (
                    Submission.query.join(Assignment, Submission.assignment_id == Assignment.assignment_id)
                    .filter(
                        Submission.student_id == st_obj.student_id,
                        Submission.status.in_(['ASSIGNED', 'IN_PROGRESS', 'RETURNED', 'SUBMITTED', 'GRADED', 'ACCEPTED']),
                        Assignment.is_active == True,
                    )
                    .options(db.contains_eager(Submission.assignment))
                    .order_by(Assignment.deadline.asc().nullslast())
                    .all()
                )
                for sub in subs:
                    if not sub.assignment or sub.assignment_id in seen_assignment_ids:
                        continue
                    seen_assignment_ids.add(sub.assignment_id)

                    deadline_iso = None
                    deadline_date_str = None
                    deadline_time_str = '23:59'
                    if sub.assignment.deadline:
                        dl = sub.assignment.deadline
                        if dl.tzinfo is None:
                            dl = dl.replace(tzinfo=dt_timezone.utc)
                        dl_local = dl.astimezone(display_tz)
                        deadline_iso = dl_local.isoformat()
                        deadline_date_str = dl_local.date().isoformat()
                        deadline_time_str = dl_local.strftime('%H:%M')

                    active_homework.append({
                        'id': sub.assignment_id,
                        'submission_id': sub.submission_id,
                        'title': sub.assignment.title,
                        'deadline': deadline_iso,
                        'deadline_date': deadline_date_str,
                        'deadline_time': deadline_time_str,
                        'url': url_for('assignments.submission_view', submission_id=sub.submission_id),
                        'status': sub.status,
                        'tasks_count': len(sub.assignment.tasks) if sub.assignment.tasks else 0,
                    })
                    if len(active_homework) >= 10:
                        break
            except Exception as e:
                logger.warning(f"Error fetching active homework for schedule: {e}")

            for l in sorted(lessons, key=lambda x: x.lesson_date or datetime.min, reverse=True):
                if getattr(l, 'status', None) in ('cancelled', 'canceled'):
                    continue
                if l.student_notes and l.student_notes.strip():
                    student_notes_text = l.student_notes.strip()
                    break
                elif l.notes and l.notes.strip():
                    student_notes_text = l.notes.strip()
                    break

            if not student_notes_text:
                student_notes_text = "«Обрати особое внимание на ключевые темы недели и не забывай вовремя сдавать домашние задания!»"

            for l in lessons:
                if l.materials and isinstance(l.materials, list):
                    for m in l.materials:
                        m_title = m.get('title') or m.get('name')
                        if m_title and m_title not in seen_material_titles:
                            seen_material_titles.add(m_title)
                            useful_materials.append({
                                'title': m_title,
                                'url': m.get('url') or '#',
                                'type': 'material',
                                'pages': m.get('pages', 'Материал к уроку')
                            })
                if l.topic and l.topic.strip():
                    topic_title = f"{l.topic.strip()} — теория"
                    if topic_title not in seen_material_titles:
                        seen_material_titles.add(topic_title)
                        useful_materials.append({
                            'title': topic_title,
                            'url': url_for('theory.theory_index'),
                            'type': 'theory',
                            'pages': 'Конспект'
                        })
                if len(useful_materials) >= 4:
                    break

            if not useful_materials:
                useful_materials = [
                    {
                        'title': 'Линейные алгоритмы и логика',
                        'url': url_for('theory.theory_index'),
                        'type': 'theory',
                        'pages': 'Конспект • Базовая теория'
                    },
                    {
                        'title': 'Циклы for и while в Python',
                        'url': url_for('theory.theory_index'),
                        'type': 'theory',
                        'pages': 'Конспект • Синтаксис и практика'
                    },
                    {
                        'title': 'Обработка строк и списков',
                        'url': url_for('theory.theory_index'),
                        'type': 'theory',
                        'pages': 'Конспект • Типовые задачи ЕГЭ'
                    }
                ]

    teacher_homework_items = []
    teacher_attention_items = []
    recurring_series_payload = []
    avail_intervals_payload = []
    avail_exceptions_payload = []

    if current_user.is_authenticated and not current_user.is_student():
        from app.models import Submission, Assignment, TeacherScheduleException, RecurringLessonSlot
        from app.schedule.recurrence_service import get_teacher_weekly_availability

        # 1. Homework deadlines & submissions
        try:
            if accessible_sids:
                subs_q = (
                    Submission.query.join(Assignment, Submission.assignment_id == Assignment.assignment_id)
                    .filter(
                        Submission.student_id.in_(accessible_sids),
                        Assignment.is_active == True,
                    )
                    .options(db.contains_eager(Submission.assignment))
                    .order_by(Assignment.deadline.asc().nullslast())
                    .limit(50)
                    .all()
                )
                seen_assign = set()
                for sub in subs_q:
                    if not sub.assignment:
                        continue
                    deadline_iso = None
                    deadline_date_str = None
                    deadline_time_str = '23:59'
                    if sub.assignment.deadline:
                        dl = sub.assignment.deadline
                        if dl.tzinfo is None:
                            dl = dl.replace(tzinfo=dt_timezone.utc)
                        dl_local = dl.astimezone(display_tz)
                        deadline_iso = dl_local.isoformat()
                        deadline_date_str = dl_local.date().isoformat()
                        deadline_time_str = dl_local.strftime('%H:%M')
                    st_name = sub.student.name if sub.student else f'Ученик #{sub.student_id}'
                    h_item = {
                        'id': sub.assignment_id,
                        'submission_id': sub.submission_id,
                        'student_id': sub.student_id,
                        'student_name': st_name,
                        'title': sub.assignment.title,
                        'deadline': deadline_iso,
                        'deadline_date': deadline_date_str,
                        'deadline_time': deadline_time_str,
                        'url': url_for('assignments.submission_view', submission_id=sub.submission_id) if sub.submission_id else url_for('assignments.assignment_view', assignment_id=sub.assignment_id),
                        'status': sub.status,
                        'tasks_count': len(sub.assignment.tasks) if sub.assignment.tasks else 0,
                    }
                    teacher_homework_items.append(h_item)

                    if sub.status in ('SUBMITTED', 'NEEDS_MANUAL_REVIEW'):
                        teacher_attention_items.append({
                            'id': f'attn_sub_{sub.submission_id}',
                            'type': 'homework_review',
                            'severity': 'high',
                            'title': f'Проверить ДЗ: {st_name}',
                            'subtitle': sub.assignment.title,
                            'url': url_for('assignments.submission_view', submission_id=sub.submission_id),
                            'badge': 'На проверке',
                            'color': 'amber',
                            'icon': 'ph-pencil-simple-line'
                        })
        except Exception as e:
            logger.warning(f"Error fetching teacher homework items: {e}")

        # 2. Upcoming / Live lessons for attention
        try:
            now_local = datetime.now(dt_timezone.utc).astimezone(display_tz)
            for l_item in raw_lessons_payload:
                st_code = l_item.get('status')
                if st_code == 'in_progress':
                    teacher_attention_items.insert(0, {
                        'id': f'attn_live_{l_item["lesson_id"]}',
                        'type': 'lesson_live',
                        'severity': 'urgent',
                        'title': f'Идёт урок: {l_item.get("student_name")}',
                        'subtitle': f'{l_item.get("subject")} • {l_item.get("topic")}',
                        'url': l_item.get('room_url'),
                        'badge': 'Прямо сейчас',
                        'color': 'rose',
                        'icon': 'ph-broadcast',
                        'lesson_id': l_item['lesson_id']
                    })
                elif st_code == 'planned' and l_item.get('start_date') == today_display_date.isoformat():
                    try:
                        l_hour, l_min = map(int, l_item.get('start_time', '00:00').split(':'))
                        l_dt = now_local.replace(hour=l_hour, minute=l_min, second=0, microsecond=0)
                        diff_sec = (l_dt - now_local).total_seconds()
                        if 0 <= diff_sec <= 7200:
                            mins_left = int(diff_sec // 60)
                            badge_txt = f'Через {mins_left} мин' if mins_left > 0 else 'Менее минуты'
                            teacher_attention_items.append({
                                'id': f'attn_up_{l_item["lesson_id"]}',
                                'type': 'lesson_upcoming',
                                'severity': 'high' if mins_left <= 30 else 'medium',
                                'title': f'Урок: {l_item.get("student_name")}',
                                'subtitle': f'{l_item.get("start_time")} • {l_item.get("subject")}',
                                'url': l_item.get('room_url'),
                                'badge': badge_txt,
                                'color': 'indigo',
                                'icon': 'ph-clock-countdown',
                                'lesson_id': l_item['lesson_id']
                            })
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"Error building teacher attention items: {e}")

        # 3. Recurring series
        try:
            r_query = RecurringLessonSlot.query.filter_by(is_active=True)
            if current_user.is_tutor():
                r_query = r_query.filter_by(owner_user_id=current_user.id)
            r_slots = r_query.order_by(RecurringLessonSlot.weekday.asc(), RecurringLessonSlot.time_hhmm.asc()).all()
            for rs in r_slots:
                st_name = rs.student.name if rs.student else f"Ученик #{rs.student_id}"
                recurring_series_payload.append({
                    'slot_id': rs.slot_id,
                    'teacher_id': rs.owner_user_id,
                    'student_id': rs.student_id,
                    'student_name': st_name,
                    'subject': rs.subject or 'Информатика',
                    'weekday': rs.weekday,
                    'time_hhmm': rs.time_hhmm,
                    'duration': rs.duration,
                    'timezone': rs.timezone,
                    'start_date': rs.start_date.isoformat() if rs.start_date else None,
                    'end_date': rs.end_date.isoformat() if rs.end_date else None,
                    'is_active': rs.is_active,
                    'topic': rs.topic,
                })
        except Exception as e:
            logger.warning(f"Error fetching recurring series: {e}")

        # 4. Teacher availability
        try:
            avail_intervals_payload = get_teacher_weekly_availability(current_user.id)
            excs = TeacherScheduleException.query.filter_by(teacher_id=current_user.id).order_by(TeacherScheduleException.exception_date.asc()).all()
            avail_exceptions_payload = [
                {
                    'id': e.id,
                    'exception_date': e.exception_date.isoformat(),
                    'exception_type': e.exception_type,
                    'start_time': e.start_time,
                    'end_time': e.end_time,
                    'reason': e.reason,
                }
                for e in excs
            ]
        except Exception as e:
            logger.warning(f"Error fetching availability for schedule data: {e}")

    # Calculate weekly metrics for student view
    week_start_date = week_days[0] if week_days else period_start
    week_end_date = week_days[-1] if week_days else period_end
    week_lessons = []
    for l_data in raw_lessons_payload:
        s_date_str = l_data.get('start_date')
        if s_date_str:
            try:
                s_date = datetime.strptime(s_date_str, '%Y-%m-%d').date()
                if week_start_date <= s_date <= week_end_date:
                    week_lessons.append(l_data)
            except Exception:
                pass

    conducted_count = sum(1 for l in week_lessons if l.get('status') in ('completed', 'done'))
    planned_count = sum(1 for l in week_lessons if l.get('status') == 'planned')
    cancelled_count = sum(1 for l in week_lessons if l.get('status') in ('cancelled', 'canceled'))
    test_count = sum(1 for l in week_lessons if l.get('is_test') or l.get('lesson_type') == 'test')
    week_hw = [h for h in active_homework if (h.get('deadline_date') and week_start_date.isoformat() <= h['deadline_date'] <= week_end_date.isoformat())]
    hw_count = len(week_hw)
    total_activities = conducted_count + planned_count + hw_count + test_count
    completion_base = conducted_count + planned_count
    progress_percent = int(round((conducted_count / completion_base) * 100)) if completion_base > 0 else 0

    real_streak = 0
    if current_user.is_authenticated and current_user.is_student():
        st_candidate = Student.query.filter_by(user_id=current_user.id).first()
        if not st_candidate:
            cand = Student.query.get(current_user.id)
            if cand and cand.user_id is None:
                st_candidate = cand
        if st_candidate:
            try:
                from app.utils.streak_service import get_effective_streak
                real_streak = get_effective_streak(st_candidate, today_date=today_display_date)
            except Exception:
                real_streak = int(getattr(st_candidate, 'streak_days', 0) or 0)

    weekly_stats = {
        'conducted': conducted_count,
        'planned': planned_count,
        'cancelled': cancelled_count,
        'homework': hw_count,
        'total_active_homework': len(active_homework),
        'tests': test_count,
        'total': total_activities,
        'conducted_and_planned': completion_base,
        'percent': progress_percent,
        'streak_days': real_streak,
    }

    weekly_bars = []
    for day in week_days:
        day_iso = day.isoformat()
        d_lessons = [l for l in week_lessons if l.get('start_date') == day_iso]
        d_hw = [h for h in active_homework if (h.get('deadline_date') == day_iso or (h.get('deadline') and h['deadline'].startswith(day_iso)))]
        total_day = len(d_lessons) + len(d_hw)
        intensity = min(100, max(22, total_day * 40)) if total_day > 0 else 22
        weekly_bars.append({
            'date': day.day,
            'iso': day_iso,
            'is_today': day == today_display_date,
            'count': total_day,
            'intensity_pct': intensity,
        })

    weekly_goals = []
    for hw in active_homework[:2]:
        is_done = hw.get('status') in ('SUBMITTED', 'GRADED', 'ACCEPTED')
        weekly_goals.append({
            'id': f"hw_{hw['id']}",
            'title': f"Сдать домашнее задание: {hw['title']}",
            'completed': is_done,
            'url': hw.get('url') or '/submissions',
            'type': 'homework',
        })
    for l in week_lessons[:3]:
        is_done = l.get('status') in ('completed', 'done')
        action_prefix = "Разобрать тему" if not is_done else "Пройдена тема"
        weekly_goals.append({
            'id': f"lesson_{l['lesson_id']}",
            'title': f"{action_prefix} «{l.get('topic', 'Занятие')}»",
            'completed': is_done,
            'url': l.get('room_url') or '#',
            'type': 'lesson',
        })
    if len(weekly_goals) > 4:
        weekly_goals = weekly_goals[:4]

    RU_WEEKDAY_NAMES_FULL = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']

    weekdays_payload = []
    for index, day in enumerate(week_days):
        day_iso = day.isoformat()
        day_l = sorted([l for l in week_lessons if l.get('start_date') == day_iso], key=lambda x: x.get('start_time') or '00:00')
        day_hw = [h for h in active_homework if (h.get('deadline_date') == day_iso or (h.get('deadline') and h['deadline'].startswith(day_iso)))]
        
        events = []
        # 1. Lessons on this day
        for l in day_l:
            is_test = l.get('is_test') or l.get('lesson_type') == 'test'
            is_webinar = l.get('lesson_type') == 'webinar'
            is_done = l.get('status') in ('completed', 'done')
            is_cancelled = l.get('status') in ('cancelled', 'canceled')
            is_in_progress = l.get('status') == 'in_progress'

            if is_cancelled:
                color = 'slate'
                icon = 'ph-x-circle'
                badge = 'Отменено'
            elif is_done:
                color = 'emerald'
                icon = 'ph-check-circle'
                badge = 'Проведено'
            elif is_in_progress:
                color = 'amber'
                icon = 'ph-broadcast'
                badge = 'Идёт урок'
            elif is_test:
                color = 'rose'
                icon = 'ph-check-square-offset'
                badge = 'Контрольная работа'
            elif is_webinar:
                color = 'violet'
                icon = 'ph-video-camera'
                badge = 'Вебинар'
            else:
                color = 'indigo'
                icon = 'ph-laptop'
                badge = 'Занятие'

            action_label = 'Материалы урока →' if is_done else 'Перейти к занятию →'
            room_link = l.get('room_url') or url_for('lessons.lesson_interactive_room', lesson_id=l['lesson_id'])

            # Multi-teacher aware teacher resolution for this specific lesson
            lesson_tutor_name = None
            lesson_tutor_avatar = None
            explicit_tutor_id = getattr(l, 'teacher_id', None) or getattr(l, 'tutor_id', None) or (l.get('teacher_id') if isinstance(l, dict) else None)
            if explicit_tutor_id:
                t_obj = student_tutors_map.get(explicit_tutor_id) or User.query.get(explicit_tutor_id)
                if t_obj:
                    lesson_tutor_name = _resolve_human_teacher_name(t_obj)
                    lesson_tutor_avatar = getattr(t_obj, 'avatar_url', None) or '/static/images/default-avatar.svg'
            if not lesson_tutor_name or lesson_tutor_name == 'Преподаватель курса':
                if teacher_name and teacher_name != 'Преподаватель курса':
                    lesson_tutor_name = teacher_name
                    lesson_tutor_avatar = teacher_avatar or lesson_tutor_avatar or '/static/images/default-avatar.svg'
                else:
                    lesson_tutor_name = lesson_tutor_name or 'Преподаватель курса'
                    lesson_tutor_avatar = lesson_tutor_avatar or teacher_avatar or '/static/images/default-avatar.svg'

            # Extract materials strictly belonging to THIS lesson (no cross-lesson leakage!)
            raw_lesson_materials = l.get('materials') if isinstance(l, dict) else getattr(l, 'materials', None)
            lesson_materials = []
            if raw_lesson_materials and isinstance(raw_lesson_materials, list):
                for m in raw_lesson_materials:
                    if isinstance(m, dict) and (m.get('title') or m.get('name')):
                        lesson_materials.append({
                            'title': m.get('title') or m.get('name'),
                            'url': m.get('url') or '#',
                            'type': m.get('type') or 'material',
                            'pages': m.get('pages', 'Материал к уроку')
                        })

            lesson_note = (l.get('student_notes') or l.get('notes') or '').strip()
            lesson_topic = (l.get('topic') or '').strip()
            lesson_desc = (
                f"Урок по теме «{lesson_topic}». Разбор теории и типовых заданий ЕГЭ."
                if lesson_topic else "Индивидуальное занятие с преподавателем."
            )
            lesson_subject = (l.get('subject') if isinstance(l, dict) else getattr(l, 'subject', None)) or 'Информатика'

            events.append({
                'id': f"lesson_{l['lesson_id']}",
                'type': 'lesson',
                'lesson_id': l['lesson_id'],
                'subject': lesson_subject,
                'title': lesson_topic or 'Индивидуальное занятие',
                'subtitle': f"{l.get('start_time', '18:00')} – {l.get('end_time', '19:00')}",
                'time_str': f"{l.get('start_time', '18:00')} – {l.get('end_time', '19:00')}",
                'description': lesson_desc,
                'notes': lesson_note,
                'student_notes': lesson_note,
                'teacher': {
                    'name': lesson_tutor_name or 'Преподаватель курса',
                    'full_name': lesson_tutor_name or 'Преподаватель курса',
                    'role': 'Преподаватель курса',
                    'avatar': lesson_tutor_avatar or '/static/images/default-avatar.svg'
                },
                'materials': lesson_materials,
                'badge': badge,
                'color': color,
                'icon': icon,
                'status': l.get('status'),
                'is_recurring': bool(l.get('is_recurring')),
                'is_rescheduled': bool(l.get('is_rescheduled')),
                'recurring_slot_id': l.get('recurring_slot_id'),
                'action_label': action_label,
                'action_url': room_link,
                'secondary_label': 'Открыть теорию',
                'secondary_url': url_for('theory.theory_index'),
            })

        # 2. Homework submissions due on this day
        for h in day_hw:
            d_time = h.get('deadline_time') or '23:59'
            hw_status = (h.get('status') or '').upper()
            is_hw_done = hw_status in ('SUBMITTED', 'GRADED', 'ACCEPTED')
            is_hw_returned = hw_status == 'RETURNED'
            is_hw_in_progress = hw_status == 'IN_PROGRESS'

            if is_hw_done:
                badge = 'ДЗ сдано'
                color = 'emerald'
                subtitle = 'Выполнено и отправлено'
                action_label = 'Посмотреть решение →'
            elif is_hw_returned:
                badge = 'На доработке'
                color = 'rose'
                subtitle = f"Доработать до {d_time}"
                action_label = 'Доработать задание →'
            elif is_hw_in_progress:
                badge = 'В процессе'
                color = 'amber'
                subtitle = f"Сдать до {d_time}"
                action_label = 'Продолжить выполнение →'
            else:
                badge = 'Домашнее задание'
                color = 'amber'
                subtitle = f"Сдать до {d_time}"
                action_label = 'Перейти к заданию →'

            events.append({
                'id': f"hw_{h['id']}",
                'type': 'homework',
                'assignment_id': h['id'],
                'subject': 'Информатика',
                'title': h.get('title') or 'Домашнее задание',
                'subtitle': subtitle,
                'time_str': f"До {d_time}",
                'description': f"Количество заданий: {h.get('tasks_count', 0)}. Реши задания и отправь на проверку преподавателю.",
                'homework_desc': f"Количество заданий: {h.get('tasks_count', 0)}. Реши задания и отправь на проверку преподавателю.",
                'badge': badge,
                'color': color,
                'icon': 'ph-file-text',
                'status': h.get('status'),
                'action_label': action_label,
                'action_url': h.get('url') or '/submissions',
                'secondary_label': 'Открыть теорию',
                'secondary_url': url_for('theory.theory_index'),
            })

        # 3. Free day / Self-study if no events
        if not events:
            is_weekend = (index >= 5)
            events.append({
                'id': f"free_{index}",
                'type': 'free',
                'title': 'Выходной • Время для себя' if is_weekend else 'Самостоятельное закрепление',
                'subtitle': 'Отдых и восстановление' if is_weekend else 'Повторение пройденного материала',
                'time_str': 'Весь день' if is_weekend else 'Самостоятельно',
                'description': (
                    'Сегодня нет обязательных занятий. Отличный день, чтобы погулять, выспаться и набраться сил на следующую неделю!'
                    if is_weekend else
                    'На сегодня занятий не запланировано. Рекомендуем заглянуть в теорию или порешать задания из банка.'
                ),
                'badge': 'Отдых' if is_weekend else 'Практика',
                'color': 'amber' if is_weekend else 'slate',
                'icon': 'ph-sun' if is_weekend else 'ph-sparkle',
                'status': 'free',
                'action_label': 'Открыть теорию →',
                'action_url': url_for('theory.theory_index'),
                'secondary_label': 'Банк заданий',
                'secondary_url': '/tasks',
            })

        main_event = events[0]
        actual_events_count = len([e for e in events if e['type'] != 'free'])
        is_today = (day == today_display_date)
        is_past = (day < today_display_date)
        is_future = (day > today_display_date)

        # Check completion status for the day
        has_actual = (actual_events_count > 0)
        day_actual_events = [e for e in events if e['type'] != 'free']
        all_lessons_done = all(e.get('status') in ('completed', 'done') for e in day_actual_events if e['type'] == 'lesson')
        all_hw_done = all((e.get('status') or '').upper() in ('SUBMITTED', 'GRADED', 'ACCEPTED') for e in day_actual_events if e['type'] == 'homework')
        is_completed = has_actual and all_lessons_done and all_hw_done
        has_uncompleted_past = is_past and has_actual and not is_completed

        weekdays_payload.append({
            'name': day_names[index],
            'short_name': day_names[index],
            'full_name': RU_WEEKDAY_NAMES_FULL[index],
            'day_name': RU_WEEKDAY_NAMES_FULL[index],
            'date': day.day,
            'month_name': RU_MONTHS_GEN[day.month - 1],
            'short_date_label': f"{day_names[index]}, {day.day} {RU_MONTHS_GEN[day.month - 1][:3]}",
            'date_badge': f"Сегодня, {day.day} {RU_MONTHS_GEN[day.month - 1]}" if is_today else f"{day.day} {RU_MONTHS_GEN[day.month - 1]}",
            'iso': day_iso,
            'is_today': is_today,
            'is_past': is_past,
            'is_future': is_future,
            'is_completed': is_completed,
            'has_uncompleted_past': has_uncompleted_past,
            'day_index': index,
            'events': events,
            'main_event': main_event,
            'events_count': actual_events_count,
        })

    # Pick default selected day
    default_selected_day_index = 0
    today_matches = [i for i, d in enumerate(weekdays_payload) if d['is_today']]
    if today_matches:
        default_selected_day_index = today_matches[0]
    else:
        with_events = [i for i, d in enumerate(weekdays_payload) if d['events_count'] > 0]
        if with_events:
            default_selected_day_index = with_events[0]

    if 'streak_days' not in weekly_stats:
        weekly_stats['streak_days'] = real_streak

    return render_template(
        tpl_name,
        schedule_page_data={
            'active_user': {'id': current_user.id, 'name': getattr(current_user, 'full_name', None) or current_user.username, 'role': current_user.role},
            'is_admin': current_user.is_admin() or current_user.is_creator(),
            'lessons': raw_lessons_payload,
            'weekdays': weekdays_payload,
            'default_selected_day_index': default_selected_day_index,
            'selected_day': weekdays_payload[default_selected_day_index] if weekdays_payload else None,
            'today_iso': today_display_date.isoformat(),
            'active_homework': active_homework,
            'useful_materials': useful_materials,
            'student_notes_general': student_notes_text,
            'teacher_name': teacher_name or 'Преподаватель курса',
            'teacher_avatar': teacher_avatar or '/static/images/schedule/mock_teacher_avatar.png',
            'weekly_stats': weekly_stats,
            'stats': weekly_stats,
            'weekly_bars': weekly_bars,
            'weekly_goals': weekly_goals,
            'week_offset': week_offset,
            'week_label': week_label,
            'timezone': timezone,
            'tz_name': timezone,
            'base_url': url_for('schedule.schedule'),
            'can_manage': _can_manage_schedule(),
            'accessible_students': accessible_students_data,
            'teacher_homework_items': teacher_homework_items,
            'attention_items': teacher_attention_items,
            'recurring_series': recurring_series_payload,
            'availability_intervals': avail_intervals_payload,
            'availability_exceptions': avail_exceptions_payload,
            'is_temporal_canvas_preview': bool(preview_template),
        },
        week_days=week_days,
        week_label=week_label,
        time_labels=time_labels,
        day_events=day_events_json,
        slot_minutes=slot_minutes,
        total_slots=total_slots,
        day_start_hour=day_start_hour,
        day_end_hour=day_end_hour,
        week_offset=week_offset,
        status_filter=status_filter,
        category_filter=category_filter,
        timezone=timezone,
        student_filter=student_filter,
        students=students,
        statuses=statuses,
        categories=categories,
        can_manage_schedule=_can_manage_schedule(),
        is_student_view=current_user.is_student(),
        is_parent_view=current_user.is_parent(),
        agenda=agenda,
        agenda_week_sidebar=agenda_week_sidebar,
        view_mode=view_mode,
        today_display_date=today_display_date,
        day_names=day_names,
        day_columns_count=day_columns_count,
        month_weeks=month_weeks,
    )

@schedule_bp.route('/schedule/create-lesson', methods=['POST'])
@login_required
def schedule_create_lesson():
    """Создание урока из расписания"""
    if not _can_manage_schedule() or (not has_permission(current_user, 'lesson.create') and not current_user.is_tutor()):
        flash('У вас недостаточно прав для создания уроков.', 'danger')
        return redirect(url_for('schedule.schedule'))
        
    try:
        student_id = request.form.get('student_id', type=int)
        start_time_utc = request.form.get('start_time_utc')
        lesson_date_str = request.form.get('lesson_date')
        lesson_time_str = request.form.get('lesson_time') or request.form.get('start_time')
        duration = request.form.get('duration', 60, type=int)
        is_test_form = request.form.get('is_test') in ('true', '1', 'on', True)
        lesson_type = 'test' if is_test_form else (request.form.get('lesson_type') or 'regular').strip().lower()
        timezone = (request.form.get('timezone') or _schedule_timezone_from_user()).strip()
        lesson_mode = request.form.get('lesson_mode', 'single')
        repeat_count = request.form.get('repeat_count', type=int)

        if not student_id or (not lesson_date_str and not start_time_utc):
            error_message = 'Заполните все обязательные поля'
            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            if is_ajax:
                return jsonify({
                    'success': False,
                    'error': error_message
                }), 400
            flash(error_message, 'error')
            return redirect(url_for('schedule.schedule'))

        base_lesson_datetime = _extract_clean_lesson_datetime(lesson_date_str, lesson_time_str, timezone, start_time_utc=start_time_utc)

        student = Student.query.get_or_404(student_id)
        allowed_student_ids = _resolve_accessible_student_ids_for_current_user()
        if allowed_student_ids is not None and student.student_id not in allowed_student_ids:
            error_message = 'Доступ запрещен'
            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            if is_ajax:
                return jsonify({'success': False, 'error': error_message}), 403
            flash(error_message, 'danger')
            return redirect(url_for('schedule.schedule'))

        # Явное разрешение преподавателя и предмета через ownership_service
        from app.schedule.ownership_service import (
            resolve_lesson_ownership,
            OwnershipValidationError,
            OwnershipSecurityError,
        )
        req_teacher_id = request.form.get('teacher_id', type=int)
        req_subject = request.form.get('subject')
        try:
            resolved_teacher_id, resolved_subject = resolve_lesson_ownership(
                actor_user=current_user,
                student=student,
                requested_teacher_id=req_teacher_id,
                requested_subject=req_subject,
            )
        except (OwnershipValidationError, OwnershipSecurityError) as own_err:
            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            if is_ajax:
                return jsonify({'success': False, 'error': str(own_err)}), 403
            flash(str(own_err), 'danger')
            return redirect(url_for('schedule.schedule'))

        if lesson_mode == 'recurring' and repeat_count and repeat_count > 1:
            lessons_to_create = repeat_count
        else:
            lessons_to_create = 1

        effective_tutor_id = resolved_teacher_id or (current_user.id if current_user.is_tutor() else None)

        from app.schedule.ownership_service import acquire_scheduling_locks
        acquire_scheduling_locks(student_id, effective_tutor_id)

        created_lessons = []
        for week_offset in range(lessons_to_create):
            lesson_datetime = base_lesson_datetime + timedelta(weeks=week_offset)
            
            if _student_has_overlap(student_id, lesson_datetime, duration):
                if lessons_to_create == 1:
                    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
                    if is_ajax:
                        return jsonify({'success': False, 'error': 'В это время ученик занят на другом уроке'}), 409
                    flash('В это время ученик занят на другом уроке', 'danger')
                    return redirect(url_for('schedule.schedule'))
                logger.warning(
                    f"Пересечение уроков: student_id={student_id}, "
                    f"start={lesson_datetime}, duration={duration}. Пропускаем."
                )
                continue

            if effective_tutor_id and _tutor_has_overlap(effective_tutor_id, lesson_datetime, duration):
                if lessons_to_create == 1:
                    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
                    if is_ajax:
                        return jsonify({'success': False, 'error': 'В это время у вас уже есть занятие'}), 409
                    flash('В это время у вас уже есть занятие', 'danger')
                    return redirect(url_for('schedule.schedule'))
                logger.warning(
                    f"Пересечение уроков у преподавателя: tutor_id={effective_tutor_id}, "
                    f"start={lesson_datetime}, duration={duration}. Пропускаем."
                )
                continue
            
            new_lesson = Lesson(
                student_id=student_id,
                teacher_id=resolved_teacher_id,
                subject=resolved_subject,
                lesson_date=lesson_datetime,
                duration=duration,
                lesson_type=lesson_type,
                status='planned'
            )
            db.session.add(new_lesson)
            created_lessons.append(new_lesson)

        if not created_lessons:
            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            if is_ajax:
                return jsonify({'success': False, 'error': 'Не удалось создать уроки из-за конфликтов расписания'}), 409
            flash('Не удалось создать уроки из-за конфликтов расписания', 'danger')
            return redirect(url_for('schedule.schedule'))

        # 1. ЖЕСТКИЙ ИЗОЛИРОВАННЫЙ КОММИТ УРОКОВ В БД
        try:
            db.session.commit()
            for created_lesson in created_lessons:
                print(f"[LESSON PERSIST SUCCESS] Lesson ID={created_lesson.lesson_id}, Date={created_lesson.lesson_date}, Student={created_lesson.student_id}")
        except Exception as e:
            db.session.rollback()
            print(f"[CREATE_LESSON ERROR] Failed to commit lessons to DB: {e}")
            raise

        # 2. НЕЗАВИСИМЫЙ БЛОК ОТПРАВКИ УВЕДОМЛЕНИЙ (Ошибки отправки НЕ отменяют уроки!)
        try:
            notify_scheduled_lessons_batch(
                created_lessons,
                student,
                actor_user_id=current_user.id,
                headline='Новый урок запланирован',
            )
        except Exception as notify_err:
            print(f"[CREATE_LESSON NOTIFY WARNING] TG notification failed: {notify_err}")
        
        for created_lesson in created_lessons:
            audit_logger.log(
                action='create_lesson_from_schedule',
                entity='Lesson',
                entity_id=created_lesson.lesson_id,
                status='success',
                metadata={
                    'student_id': student_id,
                    'student_name': student.name,
                    'lesson_mode': lesson_mode,
                    'repeat_count': lessons_to_create,
                    'lesson_date': str(created_lesson.lesson_date),
                    'duration': duration,
                    'lesson_type': lesson_type
                }
            )

        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

        if lessons_to_create > 1:
            success_message = f'Создано {lessons_to_create} уроков с {student.name} (на {lessons_to_create} недель)'
            logger.info(f'Created {lessons_to_create} lessons for student {student_id} starting from {base_lesson_datetime}')
        else:
            success_message = f'Урок с {student.name} успешно создан'
            logger.info(f'Created lesson {created_lessons[0].lesson_id} for student {student_id} at {base_lesson_datetime}')

        if is_ajax:
            created_payload = []
            for l in created_lessons:
                dt_display = lesson_storage_to_local(l.lesson_date, timezone)
                created_payload.append({
                    'lesson_id': l.lesson_id,
                    'student': student.name,
                    'student_id': student.student_id,
                    'status': 'Запланирован',
                    'status_code': l.status,
                    'lesson_type': l.lesson_type,
                    'topic': l.topic,
                    'start_time': dt_display.strftime('%H:%M'),
                    'start_total': dt_display.hour * 60 + dt_display.minute,
                    'duration_minutes': int(l.duration or 60),
                    'profile_url': url_for('students.student_profile', student_id=student.student_id),
                    'lesson_url': url_for('lessons.lesson_view', lesson_id=l.lesson_id),
                })
            return jsonify({
                'success': True,
                'message': success_message,
                'created_lessons': created_payload,
            }), 200

        flash(success_message, 'success')
    except Exception as e:
        db.session.rollback()
        error_details = str(e)
        logger.error(f'Error creating lesson: {error_details}', exc_info=True)

        if 'time' in error_details.lower() or 'date' in error_details.lower() or 'strptime' in error_details.lower():
            error_message = f'Ошибка в формате даты или времени: {error_details}'
        elif 'not found' in error_details.lower() or '404' in error_details.lower():
            error_message = 'Ученик не найден'
        else:
            error_message = f'Ошибка при создании урока: {error_details}'

        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

        if is_ajax:
            return jsonify({
                'success': False,
                'error': error_message
            }), 500

        flash(error_message, 'error')

    week_offset = request.form.get('week_offset', 0, type=int)
    status_filter = request.form.get('status_filter', '')
    category_filter = request.form.get('category_filter', '')
    timezone = request.form.get('timezone') or _schedule_timezone_from_user()

    params = {'week': week_offset, 'timezone': timezone}
    if status_filter:
        params['status'] = status_filter
    if category_filter:
        params['category'] = category_filter

    return redirect(url_for('schedule.schedule', **params))


@schedule_bp.route('/schedule/api/lesson/<int:lesson_id>/reschedule', methods=['POST'])
@schedule_bp.route('/schedule/reschedule/<int:lesson_id>', methods=['POST'])
@schedule_bp.route('/api/schedule/lesson/<int:lesson_id>/reschedule', methods=['POST'])
@schedule_bp.route('/api/schedule/reschedule/<int:lesson_id>', methods=['POST'])
@login_required
def schedule_reschedule_lesson(lesson_id: int):
    """Перенос урока на другое время (AJAX и Form)."""
    if not _can_manage_schedule() or (not has_permission(current_user, 'lesson.edit') and not current_user.is_tutor()):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'Некорректный формат запроса'}), 400

    lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)
    if not _require_lesson_in_scope(lesson, require_write=True):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    start_time_utc = data.get('start_time_utc')
    date_str = (data.get('lesson_date') or data.get('new_date') or data.get('date') or '').strip()
    time_str = (data.get('lesson_time') or data.get('new_time') or data.get('time') or '').strip()
    timezone = (data.get('timezone') or _schedule_timezone_from_user()).strip()

    if not start_time_utc and (not date_str or not time_str):
        return jsonify({'success': False, 'error': 'lesson_date и lesson_time обязательны'}), 400

    try:
        new_dt = _parse_local_datetime(date_str, time_str, timezone, start_time_utc=start_time_utc)
    except Exception as e:
        return jsonify({'success': False, 'error': f'Ошибка формата даты/времени: {e}'}), 400

    duration = int(lesson.duration or 60)
    effective_tutor_id = lesson.teacher_id or (current_user.id if current_user.is_tutor() else None)
    from app.schedule.ownership_service import acquire_scheduling_locks, check_tutor_conflict_isolated
    acquire_scheduling_locks(lesson.student_id, effective_tutor_id)

    if _student_has_overlap(lesson.student_id, new_dt, duration, exclude_lesson_id=lesson.lesson_id):
        return jsonify({'success': False, 'error': 'В это время ученик занят на другом уроке'}), 409
    if effective_tutor_id and check_tutor_conflict_isolated(effective_tutor_id, new_dt, duration, exclude_lesson_id=lesson.lesson_id):
        return jsonify({'success': False, 'error': 'В это время у вас уже есть занятие'}), 409

    try:
        old_dt = lesson.lesson_date
        lesson.lesson_date = new_dt
        lesson.tg_reminder_30min_sent = False
        db.session.commit()

        try:
            if lesson.status == 'planned' and lesson.student:
                _notify_lesson_scheduled(
                    lesson,
                    lesson.student,
                    'Урок перенесён',
                    actor_user_id=current_user.id,
                    old_dt=old_dt,
                )
                try:
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    logger.warning(f"Could not commit lesson reschedule notification: {e}")
        except Exception as e:
            logger.warning(f"Failed to notify about lesson reschedule: {e}")

        audit_logger.log(
            action='reschedule_lesson',
            entity='Lesson',
            entity_id=lesson.lesson_id,
            status='success'
        )
        return jsonify({'success': True}), 200
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='reschedule_lesson', entity='Lesson', error=str(e))
        return jsonify({'success': False, 'error': str(e)}), 500


@schedule_bp.route('/api/schedule/create_lesson', methods=['POST'])
@schedule_bp.route('/sandbox/api/schedule/create', methods=['POST'])
@schedule_bp.route('/api/schedule/create', methods=['POST'])
@login_required
def create_schedule_lesson_api():
    """API создания урока с гарантией коммита в БД."""
    if not _can_manage_schedule() or (not has_permission(current_user, 'lesson.create') and not current_user.is_tutor()):
        return jsonify({'status': 'error', 'message': 'Доступ запрещен'}), 403
    data = request.get_json(force=True, silent=True) or (request.form.to_dict() if request.form else {})

    try:
        raw_student_id = data.get('student_id') or data.get('student')
        start_time_utc = data.get('start_time_utc')
        raw_date = data.get('lesson_date') or data.get('start_time') or data.get('date')
        raw_time = data.get('time') or data.get('lesson_time') or ''
        topic = data.get('topic') or data.get('notes') or 'Занятие по расписанию'
        req_tz = (data.get('timezone') or _schedule_timezone_from_user()).strip()

        if not raw_student_id or (not raw_date and not start_time_utc):
            return jsonify({'status': 'error', 'message': 'Укажите ученика и дату урока'}), 400

        clean_date = _extract_clean_lesson_datetime(str(raw_date or ''), str(raw_time or ''), req_tz, start_time_utc=start_time_utc)

        student = Student.query.filter(
            (Student.student_id == raw_student_id) | (Student.user_id == raw_student_id)
        ).first()

        if not student:
            return jsonify({'status': 'error', 'message': f'Ученик #{raw_student_id} не найден в БД'}), 404
        if not _require_lesson_in_scope(Lesson(student_id=student.student_id)):
            return jsonify({'status': 'error', 'message': 'Ученик вне области доступа'}), 403

        try:
            duration = int(data.get('duration') or 60)
        except (TypeError, ValueError):
            duration = 60
        if duration < 15 or duration > 360:
            return jsonify({'status': 'error', 'message': 'Некорректная длительность урока'}), 400

        is_test_req = data.get('is_test') in (True, 'true', '1', 1) or str(data.get('lesson_type', '')).strip().lower() == 'test'
        lesson_type_val = 'test' if is_test_req else (data.get('lesson_type') or 'individual').strip().lower()

        # Явное разрешение преподавателя и предмета через ownership_service
        from app.schedule.ownership_service import (
            resolve_lesson_ownership,
            check_tutor_conflict_isolated,
            acquire_scheduling_locks,
            OwnershipValidationError,
            OwnershipSecurityError,
        )
        req_teacher_id = data.get('teacher_id')
        req_subject = data.get('subject')
        try:
            resolved_teacher_id, resolved_subject = resolve_lesson_ownership(
                actor_user=current_user,
                student=student,
                requested_teacher_id=int(req_teacher_id) if req_teacher_id else None,
                requested_subject=str(req_subject) if req_subject else None,
            )
        except (OwnershipValidationError, OwnershipSecurityError) as own_err:
            return jsonify({'status': 'error', 'message': str(own_err)}), 403

        effective_tutor_id = resolved_teacher_id or (current_user.id if current_user.is_tutor() else None)

        # Конкурентная сериализация через блокировку строк БД
        acquire_scheduling_locks(student.student_id, effective_tutor_id)

        # Проверка доступности преподавателя (Sprint 2.4)
        if effective_tutor_id and not is_test_req and not data.get('ignore_availability'):
            from app.schedule.recurrence_service import check_teacher_availability
            local_dt = lesson_storage_to_local(clean_date, req_tz)
            if local_dt:
                is_avail, avail_reason = check_teacher_availability(
                    effective_tutor_id,
                    local_dt.date(),
                    local_dt.strftime('%H:%M'),
                    duration,
                    req_tz,
                )
                if not is_avail:
                    return jsonify({
                        'status': 'error',
                        'message': f'Преподаватель недоступен: {avail_reason}',
                        'availability_conflict': True,
                    }), 409

        # Ветка создания повторяющейся серии (Sprint 2.4)
        if data.get('is_recurring'):
            from app.schedule.recurrence_service import create_recurring_series
            local_dt = lesson_storage_to_local(clean_date, req_tz)
            end_date_str = data.get('recurrence_end_date') or data.get('end_date')
            end_date_val = None
            if end_date_str:
                try:
                    end_date_val = datetime.strptime(str(end_date_str).strip(), '%Y-%m-%d').date()
                except Exception:
                    pass
            slot, gen_res = create_recurring_series(
                actor_user=current_user,
                student_id=student.student_id,
                weekday=local_dt.weekday(),
                time_hhmm=local_dt.strftime('%H:%M'),
                duration=duration,
                subject=resolved_subject,
                timezone_str=req_tz,
                start_date=local_dt.date(),
                end_date=end_date_val,
                topic=topic,
                skip_conflicts=bool(data.get('skip_conflicts', True)),
            )
            if gen_res:
                try:
                    notify_scheduled_lessons_batch(
                        list(gen_res),
                        student,
                        actor_user_id=current_user.id,
                        headline='Новая серия уроков запланирована',
                    )
                except Exception as batch_err:
                    logger.warning("Failed to notify recurring batch: %s", batch_err)

            return jsonify({
                'status': 'success',
                'success': True,
                'message': f'Регулярное расписание создано! Сформировано уроков: {gen_res.get("created_count", 0)}',
                'slot_id': slot.slot_id,
                'created_count': gen_res.get('created_count', 0),
                'created': gen_res.get('created', []),
                'skipped_conflicts': gen_res.get('skipped_conflicts', []),
            }), 201

        if not is_test_req and _student_has_overlap(student.student_id, clean_date, duration):
            return jsonify({'status': 'error', 'message': 'В это время ученик занят на другом уроке'}), 409

        if effective_tutor_id and not is_test_req and check_tutor_conflict_isolated(effective_tutor_id, clean_date, duration):
            return jsonify({'status': 'error', 'message': 'В это время у вас уже есть занятие'}), 409

        notes = data.get('notes') or data.get('description') or ''
        notes_val = str(notes).strip() if notes else None
        if is_test_req and (not notes_val or '__TEST__' not in notes_val):
            notes_val = ((notes_val or '') + ' __TEST__').strip()

        homework = data.get('homework') or ''
        student_notes = data.get('student_notes') or data.get('teacher_notes') or ''
        materials_raw = data.get('materials')
        materials = []
        if isinstance(materials_raw, list):
            materials = [m for m in materials_raw if isinstance(m, dict) and m.get('name')]
        elif isinstance(materials_raw, str) and materials_raw.strip():
            try:
                import json
                parsed = json.loads(materials_raw)
                if isinstance(parsed, list):
                    materials = [m for m in parsed if isinstance(m, dict) and m.get('name')]
            except Exception:
                materials = [{'name': materials_raw.strip(), 'url': ''}]

        new_lesson = Lesson(
            student_id=student.student_id,
            teacher_id=resolved_teacher_id,
            subject=resolved_subject,
            lesson_date=clean_date,
            topic=topic,
            notes=notes_val,
            homework=str(homework).strip() if homework else None,
            student_notes=str(student_notes).strip() if student_notes else None,
            materials=materials if materials else None,
            status=(data.get('status') or 'planned').strip().lower(),
            duration=duration,
            lesson_type=lesson_type_val,
        )

        db.session.add(new_lesson)
        db.session.commit()

        # 📲 ОТДЕЛЬНЫЙ ИЗОЛИРОВАННЫЙ БЛОК ТЕЛЕГРАМ-УВЕДОМЛЕНИЙ (Ошибки сети НЕ отменяют урок!)
        try:
            if new_lesson.status == 'planned':
                _notify_lesson_scheduled(
                    new_lesson,
                    student,
                    'Новый урок запланирован',
                    actor_user_id=current_user.id,
                )
        except Exception:
            logger.exception('Schedule API: lesson %s was created, but notification failed', new_lesson.lesson_id)

        return jsonify({
            'status': 'success',
            'success': True,
            'message': 'Урок успешно сохранен!',
            'lesson_id': new_lesson.lesson_id
        }), 200

    except Exception as err:
        db.session.rollback()
        import traceback
        logger.exception('Schedule API: failed to create lesson')
        return jsonify({'status': 'error', 'message': f'Ошибка БД: {str(err)}'}), 500


@schedule_bp.route('/api/schedule/update_lesson/<int:lesson_id>', methods=['POST', 'PUT'])
@schedule_bp.route('/sandbox/api/schedule/update/<int:lesson_id>', methods=['POST', 'PUT'])
@schedule_bp.route('/api/schedule/update/<int:lesson_id>', methods=['POST', 'PUT'])
@login_required
def update_schedule_lesson_api(lesson_id: int):
    """API обновления урока с поддержкой всех расширенных полей."""
    if not _can_manage_schedule() or (not has_permission(current_user, 'lesson.edit') and not current_user.is_tutor()):
        return jsonify({'status': 'error', 'message': 'Доступ запрещен'}), 403
    try:
        lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)
        if not _require_lesson_in_scope(lesson, require_write=True):
            return jsonify({'status': 'error', 'message': 'Доступ запрещен'}), 403
        data = request.get_json(force=True, silent=True) or request.form or {}

        if 'topic' in data:
            lesson.topic = str(data['topic']).strip() or lesson.topic
        if 'start_time_utc' in data or 'lesson_date' in data or 'start_time' in data or 'time' in data:
            start_time_utc = data.get('start_time_utc')
            raw_date = data.get('lesson_date') or data.get('start_time')
            raw_time = data.get('time') or data.get('lesson_time') or ''
            req_tz = (data.get('timezone') or _schedule_timezone_from_user()).strip()
            new_date = _extract_clean_lesson_datetime(str(raw_date or ''), str(raw_time or ''), req_tz, start_time_utc=start_time_utc)
        else:
            new_date = lesson.lesson_date

        new_student_id = lesson.student_id
        if 'student_id' in data:
            target_student = Student.query.filter(
                (Student.student_id == int(data['student_id'])) | (Student.user_id == int(data['student_id']))
            ).first()
            if not target_student:
                return jsonify({'status': 'error', 'message': 'Ученик не найден'}), 404
            probe = Lesson(student_id=target_student.student_id)
            if not _require_lesson_in_scope(probe):
                return jsonify({'status': 'error', 'message': 'Ученик вне области доступа'}), 403
            new_student_id = target_student.student_id

        try:
            new_duration = int(data.get('duration', lesson.duration or 60))
        except (TypeError, ValueError):
            new_duration = 60
        if new_duration < 15 or new_duration > 360:
            return jsonify({'status': 'error', 'message': 'Некорректная длительность'}), 400

        is_test_val = None
        if 'is_test' in data:
            is_test_val = data.get('is_test') in (True, 'true', '1', 1)
        elif str(data.get('lesson_type', '')).strip().lower() == 'test':
            is_test_val = True
        else:
            is_test_val = _is_lesson_test(lesson)

        from app.schedule.ownership_service import acquire_scheduling_locks, check_tutor_conflict_isolated
        effective_tutor_id = lesson.teacher_id or (current_user.id if current_user.is_tutor() else None)
        acquire_scheduling_locks(new_student_id, effective_tutor_id)

        if not is_test_val and _student_has_overlap(new_student_id, new_date, new_duration, exclude_lesson_id=lesson.lesson_id):
            return jsonify({'status': 'error', 'message': 'В это время ученик занят на другом уроке'}), 409

        if effective_tutor_id and not is_test_val and check_tutor_conflict_isolated(effective_tutor_id, new_date, new_duration, exclude_lesson_id=lesson.lesson_id):
            return jsonify({'status': 'error', 'message': 'В это время у вас уже есть занятие'}), 409

        # Защита от несанкционированного изменения teacher_id
        if 'teacher_id' in data and data['teacher_id'] is not None:
            if not (current_user.is_creator() or current_user.is_admin()):
                return jsonify({'status': 'error', 'message': 'Преподаватель не может изменять привязку урока к другому учителю'}), 403
            lesson.teacher_id = int(data['teacher_id'])

        if 'subject' in data and data['subject']:
            lesson.subject = str(data['subject']).strip()

        lesson.lesson_date = new_date
        lesson.student_id = new_student_id
        lesson.duration = new_duration
        if 'status' in data:
            if data['status'] not in ('planned', 'in_progress', 'completed', 'cancelled'):
                return jsonify({'status': 'error', 'message': 'Некорректный статус'}), 400
            try:
                transition_lesson_status(
                    lesson, data['status'],
                    source="schedule_lesson_update_api",
                    reason="teacher_updated_schedule_lesson_status",
                    actor_user_id=getattr(current_user, "id", None),
                )
            except LessonLifecycleError as exc:
                db.session.rollback()
                return jsonify({'status': 'error', 'message': str(exc)}), 409

        if 'notes' in data or 'description' in data:
            val = data.get('notes') if 'notes' in data else data.get('description')
            lesson.notes = str(val).strip() if val else None
        if 'homework' in data:
            val = data.get('homework')
            lesson.homework = str(val).strip() if val else None
        if 'student_notes' in data or 'teacher_notes' in data:
            val = data.get('student_notes') if 'student_notes' in data else data.get('teacher_notes')
            lesson.student_notes = str(val).strip() if val else None
        if 'materials' in data:
            materials_raw = data.get('materials')
            if isinstance(materials_raw, list):
                lesson.materials = [m for m in materials_raw if isinstance(m, dict) and m.get('name')]
            elif isinstance(materials_raw, str):
                try:
                    import json
                    parsed = json.loads(materials_raw)
                    if isinstance(parsed, list):
                        lesson.materials = [m for m in parsed if isinstance(m, dict) and m.get('name')]
                    else:
                        lesson.materials = None
                except Exception:
                    lesson.materials = [{'name': materials_raw.strip(), 'url': ''}] if materials_raw.strip() else None
            elif materials_raw is None:
                lesson.materials = None

        if 'is_test' in data:
            if is_test_val:
                lesson.lesson_type = 'test'
                if lesson.notes and '__NOT_TEST__' in lesson.notes:
                    lesson.notes = lesson.notes.replace('__NOT_TEST__', '').strip() or None
                if not lesson.notes or '__TEST__' not in lesson.notes:
                    lesson.notes = ((lesson.notes or '') + ' __TEST__').strip()
            else:
                if lesson.lesson_type == 'test':
                    lesson.lesson_type = 'individual'
                if lesson.notes and '__TEST__' in lesson.notes:
                    lesson.notes = lesson.notes.replace('__TEST__', '').strip() or None
                topic = str(getattr(lesson, 'topic', '') or '')
                if re.search(r'(?i)(тест|test|проверк|poyasa)', topic):
                    lesson.notes = ((lesson.notes or '') + ' __NOT_TEST__').strip()
        elif 'lesson_type' in data:
            lt = str(data['lesson_type']).strip().lower()
            if lt in ('regular', 'individual', 'test', 'exam', 'introductory', 'group', 'webinar'):
                lesson.lesson_type = lt

        db.session.commit()

        # Формируем полные данные обновлённого урока для мгновенной отрисовки без перезагрузки страницы
        req_tz = (data.get('timezone') or _schedule_timezone_from_user()).strip()
        local_start = lesson_storage_to_local(lesson.lesson_date, req_tz) if lesson.lesson_date else None
        duration_min = int(lesson.duration or 60)
        local_end = (local_start + timedelta(minutes=duration_min)) if local_start else None

        updated_payload = {
            'lesson_id': lesson.lesson_id,
            'id': lesson.lesson_id,
            'student_id': lesson.student_id,
            'student_name': lesson.student.name if lesson.student else 'Ученик',
            'subject': lesson.subject or 'Информатика',
            'teacher_id': lesson.teacher_id,
            'topic': lesson.topic,
            'status': lesson.status,
            'start_date': local_start.strftime('%Y-%m-%d') if local_start else '',
            'start_time': local_start.strftime('%H:%M') if local_start else '',
            'end_time': local_end.strftime('%H:%M') if local_end else '',
            'duration_minutes': duration_min,
            'duration': duration_min,
            'lesson_type': lesson.lesson_type,
            'is_test': _is_lesson_test(lesson),
            'notes': lesson.notes,
            'description': lesson.notes,
            'homework': lesson.homework,
            'student_notes': lesson.student_notes,
            'materials': lesson.materials or [],
        }

        return jsonify({
            'status': 'success',
            'success': True,
            'message': 'Урок обновлен!',
            'lesson': updated_payload
        }), 200

    except Exception as err:
        db.session.rollback()
        logger.exception('Schedule API: failed to update lesson %s', lesson_id)
        return jsonify({'status': 'error', 'message': str(err)}), 500


@schedule_bp.route('/api/schedule/lesson/<int:lesson_id>/details', methods=['GET'])
@schedule_bp.route('/schedule/api/lesson/<int:lesson_id>/details', methods=['GET'])
@login_required
def get_lesson_details_api(lesson_id: int):
    """Детальная информация об уроке для модального окна просмотра/редактирования."""
    lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)
    if not _require_lesson_in_scope(lesson):
        return jsonify({'status': 'error', 'message': 'Доступ запрещен'}), 403

    tz = _schedule_timezone_from_user()
    local_start = lesson_storage_to_local(lesson.lesson_date, tz) if lesson.lesson_date else None
    duration_min = int(lesson.duration or 60)
    local_end = (local_start + timedelta(minutes=duration_min)) if local_start else None

    return jsonify({
        'status': 'success',
        'lesson': {
            'lesson_id': lesson.lesson_id,
            'student_id': lesson.student_id,
            'student_name': lesson.student.name if lesson.student else 'Ученик',
            'subject': lesson.subject or 'Информатика',
            'teacher_id': lesson.teacher_id,
            'topic': lesson.topic or '',
            'notes': lesson.notes or '',
            'description': lesson.notes or '',
            'homework': lesson.homework or '',
            'student_notes': lesson.student_notes or '',
            'teacher_notes': lesson.student_notes or '',
            'materials': lesson.materials or [],
            'status': lesson.status or 'planned',
            'duration_minutes': duration_min,
            'lesson_type': lesson.lesson_type or 'individual',
            'date': local_start.strftime('%Y-%m-%d') if local_start else '',
            'start_time': local_start.strftime('%H:%M') if local_start else '',
            'end_time': local_end.strftime('%H:%M') if local_end else '',
            'room_url': url_for('lessons.lesson_interactive_room', lesson_id=lesson.lesson_id),
        }
    })


@schedule_bp.route('/schedule/api/lesson/<int:lesson_id>/set-status', methods=['POST'])
@login_required
def schedule_set_status(lesson_id: int):
    """Быстрое изменение статуса урока (AJAX)."""
    if not _can_manage_schedule() or (not has_permission(current_user, 'lesson.edit') and not current_user.is_tutor()):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'Некорректный формат запроса'}), 400

    status = (data.get('status') or '').strip()
    if status not in ('planned', 'in_progress', 'completed', 'cancelled'):
        return jsonify({'success': False, 'error': 'Некорректный status'}), 400

    lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)
    if not _require_lesson_in_scope(lesson, require_write=True):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    if lesson.status == "completed" and status != "completed":
        return jsonify({
            'success': False,
            'error': 'Проведённый урок нельзя вернуть в запланированные без отдельной корректировки баланса.',
        }), 409
    try:
        old_status = lesson.status
        _transitioned, balance_notice = transition_lesson_status(
            lesson, status,
            source="schedule_set_status_api",
            reason="teacher_changed_lesson_status",
            actor_user_id=getattr(current_user, "id", None),
        )
        db.session.commit()

        try:
            if status == 'planned' and old_status != 'planned' and lesson.student:
                _notify_lesson_scheduled(
                    lesson,
                    lesson.student,
                    'Новый урок запланирован',
                    actor_user_id=current_user.id,
                )
                try:
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    logger.warning(f"Could not commit lesson_scheduled notification (set_status): {e}")
            elif status == 'cancelled' and old_status != 'cancelled' and lesson.student:
                _notify_lesson_cancelled(
                    lesson,
                    lesson.student,
                    reason='Урок отменён в расписании',
                    actor_user_id=current_user.id,
                )
                try:
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    logger.warning(f"Could not commit lesson_cancelled notification (set_status): {e}")
        except Exception as e:
            logger.warning(f"Failed to notify about lesson status change: {e}")

        audit_logger.log(
            action='set_lesson_status',
            entity='Lesson',
            entity_id=lesson.lesson_id,
            status='success',
            metadata={
                'student_id': lesson.student_id,
                'student_name': lesson.student.name if lesson.student else None,
                'old_status': old_status,
                'new_status': status,
            }
        )
        return jsonify({'success': True}), 200
    except LessonLifecycleError as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 409
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='set_lesson_status', entity='Lesson', error=str(e))
        return jsonify({'success': False, 'error': str(e)}), 500


@schedule_bp.route('/schedule/api/lesson/<int:lesson_id>/update', methods=['POST'])
@login_required
def schedule_update_lesson(lesson_id: int):
    """Инлайн-редактирование ключевых полей урока (AJAX)."""
    if not _can_manage_schedule() or (not has_permission(current_user, 'lesson.edit') and not current_user.is_tutor()):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'Некорректный формат запроса'}), 400

    lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)
    if not _require_lesson_in_scope(lesson, require_write=True):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    duration = data.get('duration')
    lesson_type = data.get('lesson_type')
    topic = data.get('topic')
    start_time_utc = data.get('start_time_utc')
    lesson_date = data.get('lesson_date')
    lesson_time = data.get('lesson_time')
    timezone = (data.get('timezone') or _schedule_timezone_from_user()).strip()

    new_lesson_date = None
    if start_time_utc or (lesson_date is not None and lesson_time is not None):
        date_str = str(lesson_date or '').strip()
        time_str = str(lesson_time or '').strip()
        if start_time_utc or (date_str and time_str):
            try:
                new_lesson_date = _parse_local_datetime(date_str, time_str, timezone, start_time_utc=start_time_utc)
            except Exception as e:
                return jsonify({'success': False, 'error': f'Ошибка формата даты/времени: {e}'}), 400

    if duration is not None:
        try:
            duration = int(duration)
        except Exception:
            return jsonify({'success': False, 'error': 'duration должен быть числом'}), 400
        if duration < 30 or duration > 240 or (duration % 30) != 0:
            return jsonify({'success': False, 'error': 'duration: 30..240 с шагом 30'}), 400

    if lesson_type is not None:
        lesson_type = str(lesson_type).strip().lower()
        if lesson_type not in ('regular', 'individual', 'test', 'exam', 'introductory', 'group', 'webinar'):
            return jsonify({'success': False, 'error': 'Некорректный lesson_type'}), 400

    if topic is not None:
        topic = str(topic).strip()
        if len(topic) > 300:
            return jsonify({'success': False, 'error': 'topic слишком длинная'}), 400

    check_date = new_lesson_date if new_lesson_date is not None else lesson.lesson_date
    check_duration = duration if duration is not None else (lesson.duration or 60)
    
    if new_lesson_date is not None or duration is not None:
        effective_tutor_id = lesson.teacher_id or (current_user.id if current_user.is_tutor() else None)
        from app.schedule.ownership_service import acquire_scheduling_locks, check_tutor_conflict_isolated
        acquire_scheduling_locks(lesson.student_id, effective_tutor_id)
        if _student_has_overlap(lesson.student_id, check_date, check_duration, exclude_lesson_id=lesson.lesson_id):
            return jsonify({'success': False, 'error': 'В это время ученик занят на другом уроке'}), 409
        if effective_tutor_id and check_tutor_conflict_isolated(effective_tutor_id, check_date, check_duration, exclude_lesson_id=lesson.lesson_id):
            return jsonify({'success': False, 'error': 'В это время у вас уже есть занятие'}), 409

    if 'subject' in data and data['subject']:
        lesson.subject = str(data['subject']).strip()

    try:
        old_dt = lesson.lesson_date
        old = {
            'duration': lesson.duration,
            'lesson_type': lesson.lesson_type,
            'topic': lesson.topic,
            'lesson_date': str(lesson.lesson_date) if lesson.lesson_date else None,
        }

        if new_lesson_date is not None:
            lesson.lesson_date = new_lesson_date
        if duration is not None:
            lesson.duration = duration
        if lesson_type is not None:
            lesson.lesson_type = lesson_type
        if topic is not None:
            lesson.topic = topic

        db.session.commit()

        try:
            if new_lesson_date is not None and lesson.status == 'planned' and lesson.student:
                from app.telegram.delivery import invalidate_pending_lesson_deliveries
                invalidate_pending_lesson_deliveries(lesson.lesson_id, reason='lesson_rescheduled')
                _notify_lesson_scheduled(
                    lesson,
                    lesson.student,
                    'Урок перенесён',
                    actor_user_id=current_user.id,
                    old_dt=old_dt,
                )
                try:
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    logger.warning(f"Could not commit lesson update reschedule notification: {e}")
        except Exception as e:
            logger.warning(f"Failed to notify about lesson update reschedule: {e}")

        audit_logger.log(
            action='update_lesson_inline',
            entity='Lesson',
            entity_id=lesson.lesson_id,
            status='success',
            metadata={
                'student_id': lesson.student_id,
                'student_name': lesson.student.name if lesson.student else None,
                'old': old,
                'new': {
                    'duration': lesson.duration,
                    'lesson_type': lesson.lesson_type,
                    'topic': lesson.topic,
                }
            }
        )

        response_data = {
            'lesson_id': lesson.lesson_id,
            'duration_minutes': int(lesson.duration or 60),
            'lesson_type': lesson.lesson_type,
            'topic': lesson.topic,
        }
        
        if new_lesson_date is not None:
            response_data['lesson_date'] = str(lesson.lesson_date)
        
        return jsonify({
            'success': True,
            'lesson': response_data
        }), 200
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='update_lesson_inline', entity='Lesson', error=str(e))
        return jsonify({'success': False, 'error': str(e)}), 500


@schedule_bp.route('/schedule/api/events')
@schedule_bp.route('/api/schedule/events')
@login_required
def schedule_api_events():
    """
    JSON события для синхронизации внутри интерфейса.
    Права/видимость строго как у расписания.
    """
    if not has_permission(current_user, 'schedule.view') and not has_permission(current_user, 'tools.schedule'):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    start_str = request.args.get('start')
    end_str = request.args.get('end')
    start_date = _parse_date(start_str) if start_str else None
    end_date = _parse_date(end_str) if end_str else None
    timezone = request.args.get('timezone') or _schedule_timezone_from_user()
    timezone = timezone_name(timezone)
    display_tz = timezone_from_name(timezone)

    if current_user.is_authenticated and (current_user.is_admin() or current_user.is_creator()):
        q = Lesson.query.options(db.joinedload(Lesson.student)).order_by(Lesson.lesson_date.asc())
    elif current_user.is_tutor():
        q = Lesson.query.filter(Lesson.teacher_id == current_user.id).options(db.joinedload(Lesson.student)).order_by(Lesson.lesson_date.asc())
    elif current_user.is_student():
        student = Student.query.filter_by(user_id=current_user.id).first()
        if not student:
            return jsonify({'success': True, 'events': []})
        q = Lesson.query.filter(Lesson.student_id == student.student_id).options(db.joinedload(Lesson.student)).order_by(Lesson.lesson_date.asc())
    else:
        allowed = _resolve_accessible_student_ids_for_current_user()
        q = Lesson.query.options(db.joinedload(Lesson.student)).order_by(Lesson.lesson_date.asc())
        if allowed is not None:
            if not allowed:
                q = q.filter(False)
            else:
                q = q.filter(Lesson.student_id.in_(allowed))

    lessons = q.all()
    out = []
    for l in lessons:
        if not l.student or not l.lesson_date:
            continue
        dt_display = lesson_storage_to_local(l.lesson_date, timezone)
        if not dt_display:
            continue
        if start_date and dt_display.date() < start_date:
            continue
        if end_date and dt_display.date() > end_date:
            continue

        start_time_str = dt_display.strftime('%H:%M')
        out.append({
            'id': l.lesson_id,
            'lesson_id': l.lesson_id,
            'title': l.topic or (l.subject or 'Занятие'),
            'student_id': l.student.student_id,
            'student': l.student.name,
            'subject': l.subject or 'Информатика',
            'status_code': l.status,
            'lesson_type': l.lesson_type,
            'topic': l.topic,
            'duration_minutes': int(l.duration or 60),
            'start': dt_display.isoformat(),
            'start_iso': format_utc_iso_z(lesson_storage_to_utc(l.lesson_date)),
            'date': dt_display.strftime('%Y-%m-%d'),
            'start_time': start_time_str,
            'time_str': start_time_str,
            'start_total': dt_display.hour * 60 + dt_display.minute,
            'profile_url': url_for('students.student_profile', student_id=l.student.student_id),
            'lesson_url': url_for('lessons.lesson_view', lesson_id=l.lesson_id),
        })
    return jsonify({'success': True, 'events': out})


@schedule_bp.route('/schedule/api/lesson/<int:lesson_id>/delete', methods=['POST'])
@schedule_bp.route('/api/schedule/delete_lesson/<int:lesson_id>', methods=['POST', 'DELETE'])
@login_required
def schedule_delete_lesson(lesson_id: int):
    if not _can_manage_schedule():
        return jsonify({'status': 'error', 'success': False, 'error': 'Доступ запрещен'}), 403

    lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)
    if not _require_lesson_in_scope(lesson, require_write=True):
        return jsonify({'status': 'error', 'success': False, 'error': 'Доступ запрещен'}), 403

    try:
        meta = {
            'student_id': lesson.student_id,
            'student_name': lesson.student.name if lesson.student else None,
            'lesson_date': str(lesson.lesson_date),
            'duration': int(lesson.duration or 60),
            'lesson_type': lesson.lesson_type,
            'status': lesson.status,
        }
        if lesson.status == 'planned' and lesson.student:
            try:
                _notify_lesson_cancelled(
                    lesson,
                    lesson.student,
                    reason='Урок отменён и удалён из расписания',
                    actor_user_id=current_user.id,
                )
            except Exception as notify_err:
                logger.warning("Could not dispatch lesson cancellation on delete: %s", notify_err)

        from app.telegram.delivery import invalidate_pending_lesson_deliveries
        invalidate_pending_lesson_deliveries(lesson_id, reason='lesson_deleted')
        _purge_lessons_dependencies([lesson_id])
        db.session.delete(lesson)
        db.session.commit()
        db.session.expire_all()
        try:
            audit_logger.log(action='delete_lesson_from_schedule', entity='Lesson', entity_id=lesson_id, status='success', metadata=meta)
        except Exception:
            pass
        return jsonify({'status': 'success', 'success': True, 'lesson_id': lesson_id, 'message': 'Урок успешно удалён'}), 200
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='delete_lesson_from_schedule', entity='Lesson', entity_id=lesson_id, error=str(e))
        return jsonify({'status': 'error', 'success': False, 'error': str(e)}), 500


@schedule_bp.route('/api/schedule/bulk_delete_lessons', methods=['POST'])
@login_required
def schedule_bulk_delete_lessons():
    """Массовое удаление уроков: по списку ID или полная очистка тестовых занятий."""
    if not _can_manage_schedule():
        return jsonify({'status': 'error', 'success': False, 'error': 'Доступ запрещен'}), 403

    data = request.get_json(silent=True) or {}
    lesson_ids = data.get('lesson_ids') or []
    delete_all_test = data.get('delete_all_test') in (True, 'true', '1', 1)

    try:
        deleted_ids = []
        if delete_all_test:
            q = Lesson.query.options(db.joinedload(Lesson.student))
            if current_user.is_tutor():
                q = q.filter(Lesson.teacher_id == current_user.id)
            else:
                allowed = _resolve_accessible_student_ids_for_current_user()
                if allowed is not None:
                    q = q.filter(Lesson.student_id.in_(allowed))
            candidates = q.all()
            for l in candidates:
                if _is_lesson_test(l):
                    deleted_ids.append(l.lesson_id)
        elif lesson_ids and isinstance(lesson_ids, list):
            clean_ids = list(dict.fromkeys([int(x) for x in lesson_ids if str(x).strip().isdigit()]))
            if clean_ids:
                q = Lesson.query.options(db.joinedload(Lesson.student)).filter(Lesson.lesson_id.in_(clean_ids))
                lessons_to_del = q.all()
                for l in lessons_to_del:
                    if _require_lesson_in_scope(l, require_write=True):
                        deleted_ids.append(l.lesson_id)

        if deleted_ids:
            from app.telegram.delivery import invalidate_pending_lesson_deliveries
            for dlid in deleted_ids:
                invalidate_pending_lesson_deliveries(int(dlid), reason='bulk_lesson_deleted')
            _purge_lessons_dependencies(deleted_ids)
            Lesson.query.filter(Lesson.lesson_id.in_(deleted_ids)).delete(synchronize_session=False)
            db.session.commit()
            db.session.expire_all()
        else:
            db.session.commit()

        try:
            audit_logger.log(
                action='bulk_delete_lessons',
                entity='Lesson',
                status='success',
                metadata={'deleted_count': len(deleted_ids), 'deleted_ids': deleted_ids, 'delete_all_test': delete_all_test}
            )
        except Exception:
            pass

        return jsonify({
            'status': 'success',
            'success': True,
            'deleted_count': len(deleted_ids),
            'deleted_ids': deleted_ids,
            'message': f'Успешно удалено {len(deleted_ids)} уроков'
        }), 200
    except Exception as e:
        db.session.rollback()
        logger.exception("Failed bulk delete lessons: %s", e)
        return jsonify({'status': 'error', 'success': False, 'error': str(e)}), 500


@schedule_bp.route('/api/schedule/lesson/<int:lesson_id>/toggle_test', methods=['POST'])
@login_required
def schedule_toggle_test_lesson(lesson_id: int):
    """Быстрое переключение тестового статуса урока."""
    if not _can_manage_schedule() or (not has_permission(current_user, 'lesson.edit') and not current_user.is_tutor()):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    try:
        lesson = Lesson.query.get_or_404(lesson_id)
        if not _require_lesson_in_scope(lesson):
            return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

        currently_test = _is_lesson_test(lesson)
        if currently_test:
            lesson.lesson_type = 'individual'
            if lesson.notes and '__TEST__' in lesson.notes:
                lesson.notes = lesson.notes.replace('__TEST__', '').strip() or None
            topic = str(getattr(lesson, 'topic', '') or '')
            if re.search(r'(?i)(тест|test|проверк|poyasa)', topic):
                lesson.notes = ((lesson.notes or '') + ' __NOT_TEST__').strip()
            new_is_test = False
        else:
            lesson.lesson_type = 'test'
            if lesson.notes and '__NOT_TEST__' in lesson.notes:
                lesson.notes = lesson.notes.replace('__NOT_TEST__', '').strip() or None
            lesson.notes = ((lesson.notes or '') + ' __TEST__').strip()
            new_is_test = True

        db.session.commit()
        return jsonify({
            'status': 'success',
            'success': True,
            'is_test': new_is_test,
            'lesson_id': lesson_id,
            'lesson_type': lesson.lesson_type,
            'message': 'Урок перемещён в тестовый подслой' if new_is_test else 'Урок сделан обычным'
        }), 200
    except Exception as e:
        db.session.rollback()
        logger.exception("Failed to toggle test lesson %s: %s", lesson_id, e)
        return jsonify({'success': False, 'error': str(e)}), 500


@schedule_bp.route('/schedule/export.ics')
@schedule_bp.route('/schedule/export_ics')
@schedule_bp.route('/api/schedule/export_ics')
@login_required
def schedule_export_ics():
    """Экспорт видимого расписания в iCalendar (.ics) для синхронизации."""
    if not has_permission(current_user, 'schedule.view') and not has_permission(current_user, 'tools.schedule'):
        flash('У вас недостаточно прав для экспорта расписания.', 'danger')
        return redirect(url_for('schedule.schedule'))

    export_tzid = _schedule_timezone_from_user()
    today = datetime.now(dt_timezone.utc).astimezone(timezone_from_name(export_tzid)).date()

    if current_user.is_authenticated and (current_user.is_admin() or current_user.is_creator()):
        q = Lesson.query.options(db.joinedload(Lesson.student)).order_by(Lesson.lesson_date.asc())
    elif current_user.is_tutor():
        q = Lesson.query.filter(Lesson.teacher_id == current_user.id).options(db.joinedload(Lesson.student)).order_by(Lesson.lesson_date.asc())
    elif current_user.is_student():
        student = Student.query.filter_by(user_id=current_user.id).first()
        if not student:
            return Response("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n", mimetype="text/calendar; charset=utf-8")
        q = Lesson.query.filter(Lesson.student_id == student.student_id).options(db.joinedload(Lesson.student)).order_by(Lesson.lesson_date.asc())
    else:
        allowed = _resolve_accessible_student_ids_for_current_user()
        q = Lesson.query.options(db.joinedload(Lesson.student)).order_by(Lesson.lesson_date.asc())
        if allowed is not None:
            if not allowed:
                q = q.filter(False)
            else:
                q = q.filter(Lesson.student_id.in_(allowed))

    lessons = _lessons_in_local_window(q, export_tzid, today - timedelta(days=14), today + timedelta(days=60))
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//BlackNeon//Schedule//RU",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-TIMEZONE:{export_tzid}",
    ]
    for l in lessons:
        if not l.student or not l.lesson_date:
            continue
        dt_start_local = _dt_to_ics_local(l.lesson_date, export_tzid)
        dt_end_local = _dt_to_ics_local(l.lesson_date + timedelta(minutes=int(l.duration or 60)), export_tzid)
        summary = f"Урок [{l.subject or 'Информатика'}]: {l.student.name}"
        if l.topic:
            summary = f"{summary} · {l.topic}"
        uid = f"lesson-{l.lesson_id}@black-neon"
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{_dt_to_ics_utc(datetime.now(dt_timezone.utc))}",
            f"DTSTART;TZID={export_tzid}:{dt_start_local}",
            f"DTEND;TZID={export_tzid}:{dt_end_local}",
            f"SUMMARY:{summary}",
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    ics = "\r\n".join(lines) + "\r\n"

    from flask import Response
    return Response(
        ics,
        mimetype="text/calendar; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=\"schedule.ics\""},
    )


@schedule_bp.route('/schedule/ics/<string:token>')
def schedule_export_ics_by_token(token: str):
    """Приватный экспорт .ics по токену (для внешней синхронизации без логина)."""
    token = (token or '').strip()
    if not token or len(token) < 16:
        from flask import abort
        abort(404)

    user = User.query.filter_by(schedule_ics_token=token).first()
    if not user or not user.is_active:
        from flask import abort
        abort(404)

    export_tzid = timezone_name(effective_timezone_name(user))
    today = datetime.now(dt_timezone.utc).astimezone(timezone_from_name(export_tzid)).date()

    if is_creator_or_admin(user):
        q = Lesson.query.options(db.joinedload(Lesson.student)).order_by(Lesson.lesson_date.asc())
    elif user.is_tutor():
        q = Lesson.query.filter(Lesson.teacher_id == user.id).options(db.joinedload(Lesson.student)).order_by(Lesson.lesson_date.asc())
    elif user.is_student():
        student = Student.query.filter_by(user_id=user.id).first()
        if not student:
            return Response("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n", mimetype="text/calendar; charset=utf-8")
        q = Lesson.query.filter(Lesson.student_id == student.student_id).options(db.joinedload(Lesson.student)).order_by(Lesson.lesson_date.asc())
    else:
        allowed = _resolve_accessible_student_ids_for_user(user)
        q = Lesson.query.options(db.joinedload(Lesson.student)).order_by(Lesson.lesson_date.asc())
        if allowed is not None:
            if not allowed:
                q = q.filter(False)
            else:
                q = q.filter(Lesson.student_id.in_(allowed))

    lessons = _lessons_in_local_window(q, export_tzid, today - timedelta(days=14), today + timedelta(days=60))
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//BlackNeon//Schedule//RU",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-TIMEZONE:{export_tzid}",
    ]
    for l in lessons:
        if not l.student or not l.lesson_date:
            continue
        dt_start_local = _dt_to_ics_local(l.lesson_date, export_tzid)
        dt_end_local = _dt_to_ics_local(l.lesson_date + timedelta(minutes=int(l.duration or 60)), export_tzid)
        summary = f"Урок [{l.subject or 'Информатика'}]: {l.student.name}"
        if l.topic:
            summary = f"{summary} · {l.topic}"
        uid = f"lesson-{l.lesson_id}@black-neon"
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{_dt_to_ics_utc(datetime.now(dt_timezone.utc))}",
            f"DTSTART;TZID={export_tzid}:{dt_start_local}",
            f"DTEND;TZID={export_tzid}:{dt_end_local}",
            f"SUMMARY:{summary}",
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    ics = "\r\n".join(lines) + "\r\n"

    from flask import Response
    return Response(ics, mimetype="text/calendar; charset=utf-8")


@schedule_bp.route('/schedule/ics-token/regenerate', methods=['POST'])
@login_required
def schedule_regenerate_ics_token():
    """Ротация приватного токена календаря."""
    if not has_permission(current_user, 'schedule.view') and not has_permission(current_user, 'tools.schedule'):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    try:
        for _ in range(5):
            token = secrets.token_urlsafe(24)
            exists = User.query.filter(User.schedule_ics_token == token).first()
            if not exists:
                current_user.schedule_ics_token = token
                db.session.commit()
                return jsonify({'success': True, 'token': token}), 200
        return jsonify({'success': False, 'error': 'Не удалось сгенерировать токен'}), 500
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@schedule_bp.route('/schedule/templates/api/list')
@login_required
def schedule_templates_list():
    if not _can_manage_schedule():
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    allowed = _resolve_accessible_student_ids_for_current_user()
    q = RecurringLessonSlot.query.filter(RecurringLessonSlot.is_active.is_(True)).options(db.joinedload(RecurringLessonSlot.student))
    if allowed is not None:
        if not allowed:
            q = q.filter(False)
        else:
            q = q.filter(RecurringLessonSlot.student_id.in_(allowed))
    if not (current_user.is_admin() or current_user.is_creator()):
        q = q.filter((RecurringLessonSlot.owner_user_id == current_user.id) | (RecurringLessonSlot.owner_user_id.is_(None)))

    items = q.order_by(RecurringLessonSlot.student_id.asc(), RecurringLessonSlot.weekday.asc(), RecurringLessonSlot.time_hhmm.asc()).limit(500).all()
    out = []
    for t in items:
        out.append({
            'slot_id': t.slot_id,
            'student_id': t.student_id,
            'student_name': t.student.name if t.student else f"Student #{t.student_id}",
            'weekday': int(t.weekday),
            'time_hhmm': t.time_hhmm,
            'duration': int(t.duration or 60),
            'lesson_type': t.lesson_type,
            'timezone': t.timezone,
        })
    return jsonify({'success': True, 'templates': out})


@schedule_bp.route('/schedule/templates/api/create', methods=['POST'])
@login_required
def schedule_templates_create():
    if not _can_manage_schedule() or (not has_permission(current_user, 'lesson.create') and not current_user.is_tutor()):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    data = request.get_json(silent=True) or {}
    try:
        student_id = int(data.get('student_id'))
    except Exception:
        return jsonify({'success': False, 'error': 'student_id обязателен'}), 400

    try:
        weekday = int(data.get('weekday'))
    except Exception:
        return jsonify({'success': False, 'error': 'weekday обязателен'}), 400
    if weekday < 0 or weekday > 6:
        return jsonify({'success': False, 'error': 'weekday 0..6'}), 400

    time_hhmm = (data.get('time_hhmm') or '').strip()
    if not time_hhmm or len(time_hhmm) != 5 or time_hhmm[2] != ':':
        return jsonify({'success': False, 'error': 'time_hhmm формат HH:MM'}), 400

    duration = data.get('duration', 60)
    try:
        duration = int(duration)
    except Exception:
        return jsonify({'success': False, 'error': 'duration должен быть числом'}), 400
    if duration < 30 or duration > 240 or (duration % 30) != 0:
        return jsonify({'success': False, 'error': 'duration: 30..240 с шагом 30'}), 400

    lesson_type = (data.get('lesson_type') or 'regular').strip()
    if lesson_type not in ('regular', 'exam', 'introductory'):
        lesson_type = 'regular'

    timezone = timezone_name(data.get('timezone') or _schedule_timezone_from_user())

    allowed = _resolve_accessible_student_ids_for_current_user()
    if allowed is not None and student_id not in allowed:
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    exists = RecurringLessonSlot.query.filter_by(student_id=student_id, weekday=weekday, time_hhmm=time_hhmm, is_active=True).first()
    if exists:
        return jsonify({'success': True, 'slot_id': exists.slot_id}), 200

    tpl = RecurringLessonSlot(
        owner_user_id=current_user.id,
        student_id=student_id,
        weekday=weekday,
        time_hhmm=time_hhmm,
        duration=duration,
        lesson_type=lesson_type,
        timezone=timezone,
        is_active=True,
    )
    db.session.add(tpl)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify({'success': True, 'slot_id': tpl.slot_id}), 201


@schedule_bp.route('/schedule/templates/api/delete/<int:slot_id>', methods=['POST'])
@login_required
def schedule_templates_delete(slot_id: int):
    if not _can_manage_schedule():
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    tpl = RecurringLessonSlot.query.get_or_404(slot_id)
    allowed = _resolve_accessible_student_ids_for_current_user()
    if allowed is not None and tpl.student_id not in allowed:
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    if not (current_user.is_admin() or current_user.is_creator()) and tpl.owner_user_id != current_user.id:
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    tpl.is_active = False
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify({'success': True}), 200


@schedule_bp.route('/schedule/templates/api/from-lesson/<int:lesson_id>', methods=['POST'])
@login_required
def schedule_templates_create_from_lesson(lesson_id: int):
    if not _can_manage_schedule() or (not has_permission(current_user, 'lesson.create') and not current_user.is_tutor()):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    data = request.get_json(silent=True) or {}
    timezone = timezone_name(data.get('timezone') or _schedule_timezone_from_user())

    lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)
    if not _require_lesson_in_scope(lesson):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    dt_local = lesson_storage_to_local(lesson.lesson_date, timezone)

    weekday = int(dt_local.weekday())
    time_hhmm = dt_local.strftime('%H:%M')
    duration = int(lesson.duration or 60)
    lesson_type = lesson.lesson_type or 'regular'
    if lesson_type not in ('regular', 'exam', 'introductory'):
        lesson_type = 'regular'

    exists = RecurringLessonSlot.query.filter_by(student_id=lesson.student_id, weekday=weekday, time_hhmm=time_hhmm, is_active=True).first()
    if exists:
        return jsonify({'success': True, 'slot_id': exists.slot_id}), 200

    tpl = RecurringLessonSlot(
        owner_user_id=current_user.id,
        student_id=lesson.student_id,
        weekday=weekday,
        time_hhmm=time_hhmm,
        duration=duration,
        lesson_type=lesson_type,
        timezone=timezone,
        is_active=True,
    )
    db.session.add(tpl)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify({'success': True, 'slot_id': tpl.slot_id}), 201


@schedule_bp.route('/schedule/templates/api/apply-week', methods=['POST'])
@login_required
def schedule_templates_apply_week():
    """Сгенерировать уроки на текущую неделю по шаблонам."""
    if not _can_manage_schedule() or (not has_permission(current_user, 'lesson.create') and not current_user.is_tutor()):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    data = request.get_json(silent=True) or {}
    try:
        week_offset = int(data.get('week_offset', 0))
    except Exception:
        week_offset = 0

    viewer_timezone = _schedule_timezone_from_user()
    today = datetime.now(dt_timezone.utc).astimezone(timezone_from_name(viewer_timezone)).date()
    week_start = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    week_end = week_start + timedelta(days=6)

    allowed = _resolve_accessible_student_ids_for_current_user()
    q = RecurringLessonSlot.query.filter(RecurringLessonSlot.is_active.is_(True))
    if allowed is not None:
        if not allowed:
            q = q.filter(False)
        else:
            q = q.filter(RecurringLessonSlot.student_id.in_(allowed))
    if not (current_user.is_admin() or current_user.is_creator()):
        q = q.filter(RecurringLessonSlot.owner_user_id == current_user.id)
    templates = q.all()

    created_payload = []
    created_pairs = []
    for t in templates:
        day = week_start + timedelta(days=int(t.weekday))
        dt = _parse_local_datetime(day.strftime('%Y-%m-%d'), t.time_hhmm, t.timezone)

        target_utc = lesson_storage_to_utc(dt)
        exists = next((
            lesson for lesson in Lesson.query.filter_by(student_id=t.student_id).all()
            if lesson_storage_to_utc(lesson.lesson_date)
            and abs((lesson_storage_to_utc(lesson.lesson_date) - target_utc).total_seconds()) <= 60
        ), None)
        if exists:
            continue

        if _student_has_overlap(t.student_id, dt, int(t.duration or 60)):
            continue
        if current_user.is_tutor() and _tutor_has_overlap(current_user.id, dt, int(t.duration or 60)):
            continue

        l = Lesson(
            student_id=t.student_id,
            lesson_date=dt,
            duration=int(t.duration or 60),
            lesson_type=t.lesson_type,
            status='planned'
        )
        db.session.add(l)
        try:
            db.session.flush()
        except Exception:
            db.session.rollback()
            continue

        dt_display = lesson_storage_to_local(l.lesson_date, viewer_timezone)
        st = Student.query.get(t.student_id)
        if not st:
            continue
        created_pairs.append((l, st))
        created_payload.append({
            'lesson_id': l.lesson_id,
            'student': st.name,
            'student_id': st.student_id,
            'status': 'Запланирован',
            'status_code': l.status,
            'lesson_type': l.lesson_type,
            'topic': l.topic,
            'start_time': dt_display.strftime('%H:%M'),
            'start_total': dt_display.hour * 60 + dt_display.minute,
            'duration_minutes': int(l.duration or 60),
            'profile_url': url_for('students.student_profile', student_id=st.student_id),
            'lesson_url': url_for('lessons.lesson_view', lesson_id=l.lesson_id),
            'is_conflict': False,
        })

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

    try:
        lessons_by_student = {}
        for lesson, st in created_pairs:
            if lesson.status == 'planned':
                lessons_by_student.setdefault(st, []).append(lesson)
        for st, st_lessons in lessons_by_student.items():
            notify_scheduled_lessons_batch(
                st_lessons,
                st,
                actor_user_id=current_user.id,
                headline='Новый урок запланирован',
            )
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.warning(f"Could not commit lesson_scheduled notifications (recurring slots): {e}")
    except Exception as e:
        logger.warning(f"Failed to notify about lesson_scheduled (recurring slots): {e}")

    return jsonify({'success': True, 'created_lessons': created_payload}), 200


# =========================================================================
# SPRINT 2.4: RECURRING LESSONS & TEACHER AVAILABILITY API
# =========================================================================

@schedule_bp.route('/api/schedule/recurring/preview', methods=['POST'])
@login_required
def api_schedule_recurring_preview():
    """Preview simulation of upcoming recurring occurrences and conflict detection."""
    if not _can_manage_schedule():
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    data = request.get_json(silent=True) or {}
    try:
        student_id = int(data.get('student_id'))
        weekday = int(data.get('weekday'))
        time_hhmm = str(data.get('time_hhmm') or '').strip()
        duration = int(data.get('duration') or 60)
        timezone_str = (data.get('timezone') or _schedule_timezone_from_user()).strip()
        start_date_str = (data.get('start_date') or '').strip()
        end_date_str = (data.get('end_date') or '').strip()
        subject = (data.get('subject') or 'Информатика').strip()
        ignore_avail = bool(data.get('ignore_availability'))
    except Exception as e:
        return jsonify({'success': False, 'error': f'Некорректные параметры: {e}'}), 400

    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else date.today()
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None

    from app.schedule.recurrence_service import preview_recurring_slot
    preview = preview_recurring_slot(
        teacher_id=current_user.id,
        student_id=student_id,
        weekday=weekday,
        time_hhmm=time_hhmm,
        duration=duration,
        tz_name=timezone_str,
        start_date=start_date,
        end_date=end_date,
        subject=subject,
        ignore_availability=ignore_avail,
    )
    return jsonify({'success': True, 'preview': preview}), 200


@schedule_bp.route('/api/schedule/recurring/create', methods=['POST'])
@login_required
def api_schedule_recurring_create():
    """Create a recurring series and generate occurrences within horizon."""
    if not _can_manage_schedule():
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    data = request.get_json(silent=True) or {}
    try:
        student_id = int(data.get('student_id'))
        weekday = int(data.get('weekday'))
        time_hhmm = str(data.get('time_hhmm') or '').strip()
        duration = int(data.get('duration') or 60)
        timezone_str = (data.get('timezone') or _schedule_timezone_from_user()).strip()
        start_date_str = (data.get('start_date') or '').strip()
        end_date_str = (data.get('end_date') or '').strip()
        subject = (data.get('subject') or '').strip()
        topic = (data.get('topic') or '').strip()
        skip_conflicts = bool(data.get('skip_conflicts', True))
    except Exception as e:
        return jsonify({'success': False, 'error': f'Некорректные параметры: {e}'}), 400

    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else date.today()
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None

    from app.schedule.recurrence_service import create_recurring_series, RecurrenceConflictError, TeacherAvailabilityError
    try:
        slot, gen_res = create_recurring_series(
            actor_user=current_user,
            student_id=student_id,
            weekday=weekday,
            time_hhmm=time_hhmm,
            duration=duration,
            subject=subject,
            timezone_str=timezone_str,
            start_date=start_date,
            end_date=end_date,
            topic=topic,
            skip_conflicts=skip_conflicts,
        )
        return jsonify({
            'success': True,
            'slot_id': slot.slot_id,
            'created_count': gen_res.get('created_count', 0),
            'created': gen_res.get('created', []),
            'skipped_conflicts': gen_res.get('skipped_conflicts', []),
            'skipped_exceptions': gen_res.get('skipped_exceptions', []),
        }), 201
    except (RecurrenceConflictError, TeacherAvailabilityError) as err:
        return jsonify({'success': False, 'error': str(err)}), 409
    except Exception as e:
        logger.error(f"Error creating recurring series: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@schedule_bp.route('/api/schedule/recurring/list', methods=['GET'])
@login_required
def api_schedule_recurring_list():
    """List all recurring series belonging to current user."""
    if not _can_manage_schedule():
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    q = RecurringLessonSlot.query.options(db.joinedload(RecurringLessonSlot.student))
    if current_user.is_tutor():
        q = q.filter(RecurringLessonSlot.owner_user_id == current_user.id)

    slots = q.order_by(RecurringLessonSlot.weekday.asc(), RecurringLessonSlot.time_hhmm.asc()).all()
    out = []
    for s in slots:
        out.append({
            'slot_id': s.slot_id,
            'teacher_id': s.owner_user_id,
            'student_id': s.student_id,
            'student_name': s.student.name if s.student else f"Ученик #{s.student_id}",
            'subject': s.subject or 'Информатика',
            'weekday': s.weekday,
            'time_hhmm': s.time_hhmm,
            'duration': s.duration,
            'timezone': s.timezone,
            'start_date': s.start_date.isoformat() if s.start_date else None,
            'end_date': s.end_date.isoformat() if s.end_date else None,
            'is_active': s.is_active,
            'topic': s.topic,
        })
    return jsonify({'success': True, 'series': out}), 200


@schedule_bp.route('/api/schedule/recurring/reschedule-instance', methods=['POST'])
@login_required
def api_schedule_recurring_reschedule_instance():
    """Scenario A: Reschedule a single instance of a recurring series."""
    if not _can_manage_schedule():
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    data = request.get_json(silent=True) or {}
    lesson_id = data.get('lesson_id')
    new_date_str = data.get('new_date')
    new_time_hhmm = data.get('new_time')
    new_duration = data.get('duration')

    if not lesson_id or not new_date_str or not new_time_hhmm:
        return jsonify({'success': False, 'error': 'lesson_id, new_date, new_time обязательны'}), 400

    try:
        new_date = datetime.strptime(new_date_str, '%Y-%m-%d').date()
    except Exception:
        return jsonify({'success': False, 'error': 'Некорректная дата'}), 400

    from app.schedule.recurrence_service import reschedule_recurring_instance, RecurrenceConflictError
    try:
        lesson = reschedule_recurring_instance(
            lesson_id=int(lesson_id),
            new_date=new_date,
            new_time_hhmm=new_time_hhmm,
            new_duration=int(new_duration) if new_duration else None,
            actor_user=current_user,
        )
        return jsonify({'success': True, 'lesson_id': lesson.lesson_id, 'new_date': new_date_str, 'new_time': new_time_hhmm}), 200
    except RecurrenceConflictError as ce:
        return jsonify({'success': False, 'error': str(ce)}), 409
    except PermissionError as pe:
        return jsonify({'success': False, 'error': str(pe)}), 403
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@schedule_bp.route('/api/schedule/recurring/cancel-instance', methods=['POST'])
@login_required
def api_schedule_recurring_cancel_instance():
    """Scenario D: Cancel a single instance of a recurring series."""
    if not _can_manage_schedule():
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    data = request.get_json(silent=True) or {}
    lesson_id = data.get('lesson_id')
    reason = data.get('reason')
    if not lesson_id:
        return jsonify({'success': False, 'error': 'lesson_id обязателен'}), 400

    from app.schedule.recurrence_service import cancel_recurring_instance
    try:
        lesson = cancel_recurring_instance(lesson_id=int(lesson_id), reason=reason, actor_user=current_user)
        return jsonify({'success': True, 'lesson_id': lesson.lesson_id, 'status': lesson.status}), 200
    except PermissionError as pe:
        return jsonify({'success': False, 'error': str(pe)}), 403
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@schedule_bp.route('/api/schedule/recurring/update-future', methods=['POST'])
@login_required
def api_schedule_recurring_update_future():
    """Scenario B: Modify this and all future lessons of a recurring series."""
    if not _can_manage_schedule():
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    data = request.get_json(silent=True) or {}
    slot_id = data.get('slot_id')
    from_date_str = data.get('from_date')
    new_weekday = data.get('new_weekday')
    new_time_hhmm = data.get('new_time')
    new_duration = data.get('duration') or 60

    if not slot_id or not from_date_str or new_weekday is None or not new_time_hhmm:
        return jsonify({'success': False, 'error': 'Все поля обязательны'}), 400

    try:
        from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
    except Exception:
        return jsonify({'success': False, 'error': 'Некорректная дата'}), 400

    from app.schedule.recurrence_service import update_series_from_date
    try:
        old_s, new_s = update_series_from_date(
            slot_id=int(slot_id),
            from_date=from_date,
            new_weekday=int(new_weekday),
            new_time_hhmm=str(new_time_hhmm).strip(),
            new_duration=int(new_duration),
            actor_user=current_user,
        )
        return jsonify({'success': True, 'old_slot_id': old_s.slot_id, 'new_slot_id': new_s.slot_id}), 200
    except PermissionError as pe:
        return jsonify({'success': False, 'error': str(pe)}), 403
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@schedule_bp.route('/api/schedule/recurring/update-series', methods=['POST'])
@login_required
def api_schedule_recurring_update_series():
    """Scenario C: Modify whole series parameters for future uncompleted lessons."""
    if not _can_manage_schedule():
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    data = request.get_json(silent=True) or {}
    slot_id = data.get('slot_id')
    new_time_hhmm = data.get('new_time')
    new_duration = data.get('duration') or 60
    new_subject = data.get('subject')
    topic = data.get('topic')

    if not slot_id or not new_time_hhmm:
        return jsonify({'success': False, 'error': 'slot_id и new_time обязательны'}), 400

    from app.schedule.recurrence_service import update_whole_series, RecurrenceConflictError
    try:
        slot = update_whole_series(
            slot_id=int(slot_id),
            new_time_hhmm=str(new_time_hhmm).strip(),
            new_duration=int(new_duration),
            new_subject=str(new_subject).strip() if new_subject else None,
            topic=str(topic).strip() if topic else None,
            actor_user=current_user,
        )
        return jsonify({'success': True, 'slot_id': slot.slot_id}), 200
    except RecurrenceConflictError as rce:
        return jsonify({
            'success': False,
            'error': str(rce),
            'conflict': True,
            'conflict_details': getattr(rce, 'conflict_details', []),
        }), 409
    except PermissionError as pe:
        return jsonify({'success': False, 'error': str(pe)}), 403
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@schedule_bp.route('/api/schedule/recurring/pause', methods=['POST'])
@login_required
def api_schedule_recurring_pause():
    """Scenario E: Pause a recurring series."""
    if not _can_manage_schedule():
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    data = request.get_json(silent=True) or {}
    slot_id = data.get('slot_id')
    mode = data.get('mode', 'stop_generation_only')
    reason = data.get('reason')
    if not slot_id:
        return jsonify({'success': False, 'error': 'slot_id обязателен'}), 400

    from app.schedule.recurrence_service import pause_recurring_series
    try:
        slot = pause_recurring_series(
            slot_id=int(slot_id),
            actor_user=current_user,
            mode=mode,
            reason=reason,
        )
        return jsonify({'success': True, 'slot_id': slot.slot_id, 'is_active': slot.is_active, 'mode': mode}), 200
    except PermissionError as pe:
        return jsonify({'success': False, 'error': str(pe)}), 403
    except ValueError as ve:
        return jsonify({'success': False, 'error': str(ve)}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@schedule_bp.route('/api/schedule/recurring/resume', methods=['POST'])
@login_required
def api_schedule_recurring_resume():
    """Scenario E: Resume a recurring series."""
    if not _can_manage_schedule():
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    data = request.get_json(silent=True) or {}
    slot_id = data.get('slot_id')
    if not slot_id:
        return jsonify({'success': False, 'error': 'slot_id обязателен'}), 400

    from app.schedule.recurrence_service import resume_recurring_series, generate_lessons_for_slot
    try:
        slot = resume_recurring_series(slot_id=int(slot_id), actor_user=current_user)
        gen_res = generate_lessons_for_slot(slot=slot, horizon_days=28, actor_user=current_user)
        return jsonify({'success': True, 'slot_id': slot.slot_id, 'is_active': slot.is_active, 'created_count': gen_res.get('created_count', 0)}), 200
    except PermissionError as pe:
        return jsonify({'success': False, 'error': str(pe)}), 403
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@schedule_bp.route('/api/student/schedule', methods=['GET'])
@login_required
def api_student_schedule_concept_d():
    """Returns JSON schedule for current student user (Concept D)."""
    student = None
    if current_user.is_student():
        student = Student.query.filter_by(user_id=current_user.id).first()
    elif current_user.is_creator() or current_user.is_admin():
        st_id = request.args.get('student_id')
        if st_id:
            student = db.session.get(Student, int(st_id))
    if not student:
        student = Student.query.filter_by(user_id=current_user.id).first()

    if not student:
        return jsonify({'status': 'success', 'lessons': []}), 200

    lessons = Lesson.query.filter_by(student_id=student.student_id).order_by(Lesson.lesson_date.asc()).all()
    res = []
    for l in lessons:
        res.append({
            'lesson_id': l.lesson_id,
            'subject': l.subject,
            'topic': l.topic,
            'status': l.status,
            'start_time': l.start_time.isoformat() if l.start_time else None,
            'duration': l.duration,
            'is_recurring': bool(l.recurring_slot_id),
            'recurring_slot_id': l.recurring_slot_id,
            'is_rescheduled': bool(l.is_rescheduled),
            'slot_origin_date': l.slot_origin_date.isoformat() if l.slot_origin_date else None,
        })
    return jsonify({'status': 'success', 'lessons': res}), 200


# =========================================================================
# AVAILABILITY ENDPOINTS
# =========================================================================

@schedule_bp.route('/api/schedule/availability/weekly', methods=['GET', 'POST'])
@login_required
def api_schedule_availability_weekly():
    """Manage weekly working hours intervals for teacher."""
    if not _can_manage_schedule() or not current_user.is_tutor():
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    from app.schedule.recurrence_service import get_teacher_weekly_availability, set_teacher_weekly_availability
    if request.method == 'GET':
        intervals = get_teacher_weekly_availability(current_user.id)
        return jsonify({'success': True, 'intervals': intervals}), 200

    data = request.get_json(silent=True) or {}
    intervals_in = data.get('intervals', [])
    try:
        saved = set_teacher_weekly_availability(current_user.id, intervals_in)
        return jsonify({'success': True, 'intervals': saved}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@schedule_bp.route('/api/schedule/availability/exceptions', methods=['GET'])
@login_required
def api_schedule_availability_exceptions_list():
    """List date exceptions for teacher."""
    if not _can_manage_schedule() or not current_user.is_tutor():
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    from app.models import TeacherScheduleException
    excs = TeacherScheduleException.query.filter_by(teacher_id=current_user.id).order_by(TeacherScheduleException.exception_date.asc()).all()
    out = [
        {
            'id': e.id,
            'exception_date': e.exception_date.isoformat(),
            'exception_type': e.exception_type,
            'start_time': e.start_time,
            'end_time': e.end_time,
            'reason': e.reason,
        }
        for e in excs
    ]
    return jsonify({'success': True, 'exceptions': out}), 200


@schedule_bp.route('/api/schedule/availability/exceptions/add', methods=['POST'])
@login_required
def api_schedule_availability_exceptions_add():
    """Add or update date exception for teacher."""
    if not _can_manage_schedule() or not current_user.is_tutor():
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    data = request.get_json(silent=True) or {}
    exc_date_str = data.get('exception_date') or data.get('date')
    exc_type = data.get('exception_type') or 'unavailable'
    start_time = data.get('start_time')
    end_time = data.get('end_time')
    reason = data.get('reason')
    resolution_action = data.get('resolution_action')

    if not exc_date_str:
        return jsonify({'success': False, 'error': 'exception_date обязательна'}), 400

    try:
        exc_date = datetime.strptime(str(exc_date_str).strip(), '%Y-%m-%d').date()
    except Exception:
        return jsonify({'success': False, 'error': 'Некорректная дата'}), 400

    from app.schedule.recurrence_service import add_teacher_schedule_exception, TeacherExceptionConflictError
    try:
        exc = add_teacher_schedule_exception(
            teacher_id=current_user.id,
            exception_date=exc_date,
            exception_type=exc_type,
            start_time=start_time,
            end_time=end_time,
            reason=reason,
            resolution_action=resolution_action,
            tz_name=getattr(current_user, 'timezone', 'Europe/Moscow') or 'Europe/Moscow',
            actor_user=current_user,
        )
        return jsonify({'success': True, 'exception_id': exc.id}), 201
    except TeacherExceptionConflictError as tece:
        return jsonify({
            'success': False,
            'error': str(tece),
            'conflict': True,
            'affected_lessons': tece.affected_lessons,
        }), 409
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@schedule_bp.route('/api/schedule/availability/exceptions/delete/<int:exception_id>', methods=['POST'])
@login_required
def api_schedule_availability_exceptions_delete(exception_id: int):
    """Delete date exception."""
    if not _can_manage_schedule() or not current_user.is_tutor():
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    from app.schedule.recurrence_service import delete_teacher_schedule_exception
    success = delete_teacher_schedule_exception(exception_id, current_user.id)
    return jsonify({'success': success}), 200 if success else 404


@schedule_bp.route('/api/schedule/find-free-slots', methods=['GET', 'POST'])
@login_required
def api_schedule_find_free_slots():
    """Smart time finder: recommend non-conflicting slots within teacher working hours."""
    if not _can_manage_schedule():
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    from app.schedule.recurrence_service import get_teacher_weekly_availability
    from app.models import TeacherScheduleException, Lesson

    req_data = request.get_json(silent=True) or request.args
    duration = int(req_data.get('duration') or 60)
    student_id = req_data.get('student_id', type=int) if hasattr(req_data, 'get') else None
    days_ahead = int(req_data.get('days_ahead') or 7)

    teacher_id = current_user.id
    tz_str = (getattr(current_user, 'timezone', None) or 'Europe/Moscow').strip()
    tz = timezone_from_name(tz_str)

    today = datetime.now(dt_timezone.utc).astimezone(tz).date()

    # 1. Weekly availability map
    weekly = get_teacher_weekly_availability(teacher_id)
    avail_map = {item['weekday']: item for item in weekly}

    # 2. Exceptions
    exceptions = TeacherScheduleException.query.filter_by(teacher_id=teacher_id).filter(
        TeacherScheduleException.exception_date >= today,
        TeacherScheduleException.exception_date <= today + timedelta(days=days_ahead)
    ).all()
    exc_map = {e.exception_date.isoformat(): e for e in exceptions}

    # 3. Existing lessons
    window_start = datetime.combine(today, datetime.min.time(), tzinfo=tz).astimezone(dt_timezone.utc)
    window_end = datetime.combine(today + timedelta(days=days_ahead), datetime.max.time(), tzinfo=tz).astimezone(dt_timezone.utc)

    teacher_lessons = Lesson.query.filter(
        Lesson.teacher_id == teacher_id,
        Lesson.status.in_(['planned', 'in_progress']),
        Lesson.lesson_date >= window_start.replace(tzinfo=None),
        Lesson.lesson_date <= window_end.replace(tzinfo=None)
    ).all()

    student_lessons = []
    if student_id:
        student_lessons = Lesson.query.filter(
            Lesson.student_id == student_id,
            Lesson.status.in_(['planned', 'in_progress']),
            Lesson.lesson_date >= window_start.replace(tzinfo=None),
            Lesson.lesson_date <= window_end.replace(tzinfo=None)
        ).all()

    busy_intervals = []
    for l in teacher_lessons + student_lessons:
        if not l.lesson_date:
            continue
        l_utc = l.lesson_date.replace(tzinfo=dt_timezone.utc)
        l_loc = l_utc.astimezone(tz)
        dur = int(l.duration or 60)
        busy_intervals.append((l_loc, l_loc + timedelta(minutes=dur)))

    recommended_slots = []
    RU_WD_NAMES = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

    for day_idx in range(days_ahead):
        cur_date = today + timedelta(days=day_idx)
        wd = cur_date.weekday()
        iso_date = cur_date.isoformat()

        inv = avail_map.get(wd)
        is_active = inv.get('is_active', True) if inv else True
        start_str = inv.get('start_time', '09:00') if inv else '09:00'
        end_str = inv.get('end_time', '21:00') if inv else '21:00'

        exc = exc_map.get(iso_date)
        if exc:
            if exc.exception_type == 'unavailable':
                continue
            elif exc.exception_type == 'custom_hours' and exc.start_time and exc.end_time:
                start_str = exc.start_time
                end_str = exc.end_time
            elif exc.exception_type == 'extra_available':
                is_active = True

        if not is_active:
            continue

        try:
            sh, sm = map(int, start_str.split(':'))
            eh, em = map(int, end_str.split(':'))
        except Exception:
            sh, sm = 9, 0
            eh, em = 21, 0

        day_start_dt = datetime.combine(cur_date, datetime.min.time(), tzinfo=tz) + timedelta(hours=sh, minutes=sm)
        day_end_dt = datetime.combine(cur_date, datetime.min.time(), tzinfo=tz) + timedelta(hours=eh, minutes=em)

        cand_start = day_start_dt
        now_dt = datetime.now(dt_timezone.utc).astimezone(tz)

        while cand_start + timedelta(minutes=duration) <= day_end_dt:
            cand_end = cand_start + timedelta(minutes=duration)

            if cand_start > now_dt:
                has_collision = False
                for b_start, b_end in busy_intervals:
                    if max(cand_start, b_start) < min(cand_end, b_end):
                        has_collision = True
                        break

                if not has_collision:
                    recommended_slots.append({
                        'date': iso_date,
                        'weekday': wd,
                        'weekday_name': RU_WD_NAMES[wd],
                        'date_label': f"{RU_WD_NAMES[wd]}, {cur_date.day} {RU_MONTHS_GEN[cur_date.month - 1]}",
                        'start_time': cand_start.strftime('%H:%M'),
                        'end_time': cand_end.strftime('%H:%M'),
                        'duration': duration,
                        'is_today': cur_date == today,
                    })
                    if len(recommended_slots) >= 12:
                        break
            cand_start += timedelta(minutes=30)
        if len(recommended_slots) >= 12:
            break

    return jsonify({'success': True, 'slots': recommended_slots}), 200


