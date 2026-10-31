"""Service layer for explicit lesson ownership, RBAC isolation, and conflict checking.

Sprint 2.2: Multi-Teacher Data Foundation.
Guarantees:
- Explicit teacher ownership for newly created lessons.
- Prevention of cross-teacher mutations (Tutor A cannot mutate Tutor B's lesson).
- Isolated tutor conflict checks (no false-positive blocks from peer teachers).
- Strict query isolation: teachers see only their verified lessons.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple

from app.models import db, Enrollment, Lesson, Student, User
from app.utils.relationship_scope import (
    get_student_user_ids_for_tutor,
    is_creator_or_admin,
)
from app.utils.lesson_time import lesson_storage_to_utc

logger = logging.getLogger(__name__)


class OwnershipValidationError(ValueError):
    """Raised when ownership validation fails due to invalid parameters or relations."""
    pass


class OwnershipSecurityError(PermissionError):
    """Raised when an actor attempts an unauthorized action (e.g. impersonating another tutor)."""
    pass


def resolve_lesson_ownership(
    actor_user: Optional[User],
    student: Student,
    requested_teacher_id: Optional[int] = None,
    requested_subject: Optional[str] = None,
) -> Tuple[Optional[int], Optional[str]]:
    """
    Validates and resolves teacher_id and subject for a new or reassigned lesson.

    Returns:
        (resolved_teacher_id, resolved_subject)
    Raises:
        OwnershipSecurityError: If an actor attempts unauthorized teacher assignment.
        OwnershipValidationError: If student, teacher, or subject contracts are invalid.
    """
    if not student:
        raise OwnershipValidationError("Ученик не указан.")

    # 1. System / unauthenticated execution (CLI, migrations, background workers)
    if not actor_user or not getattr(actor_user, "is_authenticated", False):
        if requested_teacher_id:
            teacher_user = db.session.get(User, int(requested_teacher_id))
            if not teacher_user:
                raise OwnershipValidationError(f"Преподаватель #{requested_teacher_id} не найден.")
            logger.warning(
                f"[TECHNICAL DEBT] Unauthenticated lesson creation assigned to teacher #{teacher_user.id}"
            )
            return teacher_user.id, (requested_subject or "Информатика").strip()
        logger.warning("[TECHNICAL DEBT] Unauthenticated lesson creation without teacher_id (retaining NULL).")
        return None, (requested_subject or "Информатика").strip()

    # 2. Administrator / Platform Creator: Full authority with validation
    if is_creator_or_admin(actor_user):
        target_teacher_id = requested_teacher_id or actor_user.id
        teacher_user = db.session.get(User, int(target_teacher_id))
        if not teacher_user:
            raise OwnershipValidationError(f"Преподаватель #{target_teacher_id} не найден.")

        subject = (requested_subject or "").strip()
        if not subject:
            # Try to resolve from active enrollment between this teacher and student
            if student.user_id:
                enr = (
                    Enrollment.query.filter_by(
                        student_id=student.user_id,
                        tutor_id=teacher_user.id,
                    )
                    .filter(Enrollment.status != "archived")
                    .first()
                )
                if enr and enr.subject:
                    subject = enr.subject.strip()
        return teacher_user.id, subject or "Информатика"

    # 3. Tutor (Regular Teacher): Strict personal ownership
    if getattr(actor_user, "is_tutor", None) and actor_user.is_tutor():
        # Security invariant: Tutor CANNOT assign lessons on behalf of another tutor
        if requested_teacher_id and int(requested_teacher_id) != int(actor_user.id):
            raise OwnershipSecurityError(
                "Преподаватель не может создавать или изменять уроки от имени другого преподавателя."
            )

        # Invariant: Tutor must be authorized to teach this student
        accessible_user_ids = set(get_student_user_ids_for_tutor(actor_user.id))
        is_mentor = bool(student.mentor_id and int(student.mentor_id) == int(actor_user.id))
        student_user_accessible = bool(student.user_id and student.user_id in accessible_user_ids)

        if not is_mentor and not student_user_accessible:
            raise OwnershipSecurityError("У вас нет прав для назначения занятий данному ученику.")

        # Resolve subject from active enrollments
        active_enrollments = []
        if student.user_id:
            active_enrollments = (
                Enrollment.query.filter_by(
                    student_id=student.user_id,
                    tutor_id=actor_user.id,
                )
                .filter(Enrollment.status != "archived")
                .all()
            )

        allowed_subjects = {e.subject.strip() for e in active_enrollments if e.subject}
        cleaned_req_subject = (requested_subject or "").strip()

        if cleaned_req_subject:
            if allowed_subjects and cleaned_req_subject not in allowed_subjects:
                raise OwnershipValidationError(
                    f"Предмет «{cleaned_req_subject}» не соответствует вашему учебному контракту с учеником "
                    f"(доступно: {', '.join(sorted(allowed_subjects))})."
                )
            final_subject = cleaned_req_subject
        elif allowed_subjects:
            final_subject = sorted(allowed_subjects)[0]
        else:
            final_subject = "Информатика"

        return actor_user.id, final_subject

    # 4. Other roles (Students, Parents) cannot create lessons
    raise OwnershipSecurityError("У вас недостаточно прав для создания учебных занятий.")


def get_active_tutor_ids_for_student(student: Optional[Student]) -> set[int]:
    """
    Returns the set of active tutor user IDs associated with the student
    via non-archived enrollments, teacher-student links, or mentor assignment.
    """
    if not student:
        return set()

    active_tutor_ids = set()
    if student.user_id:
        active_tutors = (
            Enrollment.query.filter(
                Enrollment.student_id == student.user_id,
                Enrollment.status != "archived",
            )
            .all()
        )
        active_tutor_ids.update(e.tutor_id for e in active_tutors if e.tutor_id)

    if student.mentor_id:
        active_tutor_ids.add(student.mentor_id)

    return active_tutor_ids


def can_user_view_lesson(actor_user: Optional[User], lesson: Lesson) -> Tuple[bool, Optional[str]]:
    """
    Checks if actor_user has read permission for a lesson.
    Enforces strict zero cross-teacher leakage:
    - Creator / Admin: full visibility.
    - Tutor:
      - Explicit teacher_id: allowed only if teacher_id == actor_user.id.
      - Historical (teacher_id IS NULL): allowed only if tutor was the sole confirmed tutor.
        If multiple candidate tutors exist, access is restricted to Admin to prevent cross-leakage.
    - Student: allowed only for their own lessons.
    - Parent: allowed only for confirmed children.
    """
    if not actor_user or not getattr(actor_user, "is_authenticated", False):
        return False, "Требуется авторизация."

    if is_creator_or_admin(actor_user):
        return True, None

    if getattr(actor_user, "is_tutor", None) and actor_user.is_tutor():
        # Case A: Lesson has explicit teacher_id
        if lesson.teacher_id is not None:
            if int(lesson.teacher_id) == int(actor_user.id):
                return True, None
            return False, "Доступ запрещен: урок назначен другому преподавателю."

        # Case B: Historical lesson without teacher_id (teacher_id IS NULL)
        if not lesson.student_id:
            return False, "Доступ запрещен: урок не привязан к ученику."

        student = db.session.get(Student, lesson.student_id)
        if not student:
            return False, "Доступ запрещен: ученик не найден."

        active_tutor_ids = get_active_tutor_ids_for_student(student)
        if len(active_tutor_ids) > 1:
            return (
                False,
                "Доступ запрещен: исторический урок относится к ученику с несколькими преподавателями. "
                "Просмотр доступен только администратору.",
            )

        if active_tutor_ids == {actor_user.id}:
            return True, None

        return False, "Доступ запрещен: вы не являетесь преподавателем данного урока."

    if getattr(actor_user, "is_student", None) and actor_user.is_student():
        student = Student.query.filter_by(user_id=actor_user.id).first()
        if not student:
            return False, "Учетная запись ученика не найдена."
        if int(lesson.student_id) == int(student.student_id):
            return True, None
        return False, "Доступ запрещен: вы не можете просматривать чужой урок."

    if getattr(actor_user, "is_parent", None) and actor_user.is_parent():
        from app.utils.relationship_scope import get_confirmed_student_user_ids_for_parent
        student = db.session.get(Student, lesson.student_id)
        if student and student.user_id and student.user_id in get_confirmed_student_user_ids_for_parent(actor_user.id):
            return True, None
        return False, "Доступ запрещен: урок не относится к вашим детям."

    return False, "У вас недостаточно прав для просмотра данного урока."


def can_user_modify_lesson(actor_user: Optional[User], lesson: Lesson) -> Tuple[bool, Optional[str]]:
    """
    Checks if actor_user has write permission (edit, reschedule, set-status, delete) on a lesson.
    """
    if not actor_user or not getattr(actor_user, "is_authenticated", False):
        return False, "Требуется авторизация."

    if is_creator_or_admin(actor_user):
        return True, None

    if getattr(actor_user, "is_tutor", None) and actor_user.is_tutor():
        # Case A: Lesson has explicit teacher_id
        if lesson.teacher_id is not None:
            if int(lesson.teacher_id) == int(actor_user.id):
                return True, None
            return False, "Доступ запрещен: урок назначен другому преподавателю."

        # Case B: Historical lesson without teacher_id (teacher_id IS NULL)
        # Only allowed if student belongs exclusively to this tutor and no other tutor is enrolled
        if not lesson.student_id:
            return False, "Доступ запрещен: урок не привязан к ученику."

        student = db.session.get(Student, lesson.student_id)
        if not student:
            return False, "Доступ запрещен: ученик не найден."

        active_tutor_ids = get_active_tutor_ids_for_student(student)

        if len(active_tutor_ids) > 1:
            return (
                False,
                "Доступ запрещен: исторический урок относится к ученику с несколькими преподавателями. "
                "Изменение доступно только администратору.",
            )

        if active_tutor_ids == {actor_user.id}:
            return True, None

        return False, "Доступ запрещен: вы не являетесь преподавателем данного урока."

    return False, "У вас недостаточно прав для изменения урока."


def check_tutor_conflict_isolated(
    tutor_user_id: int,
    start_dt: datetime,
    duration_min: int,
    exclude_lesson_id: Optional[int] = None,
) -> bool:
    """
    Checks time conflict strictly for tutor_user_id's own lessons.
    Never produces false-positive collisions based on other tutors of shared students.
    """
    if not tutor_user_id or not start_dt or not duration_min:
        return False

    start_dt_utc = lesson_storage_to_utc(start_dt)
    end_dt_utc = lesson_storage_to_utc(start_dt + timedelta(minutes=duration_min))
    if not start_dt_utc or not end_dt_utc:
        return False

    # Query only lessons explicitly owned by this tutor
    q = Lesson.query.filter(
        Lesson.teacher_id == tutor_user_id,
        Lesson.status != "cancelled",
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
            return True

    return False


def build_isolated_schedule_query(
    user: User,
    period_start: Optional[datetime] = None,
    period_end: Optional[datetime] = None,
    status_filter: Optional[str] = None,
    student_filter: Optional[int] = None,
    teacher_filter: Optional[int] = None,
    base_query=None,
):
    """
    Builds a secure, isolated SQLAlchemy query for schedule views.
    - Student: sees all own lessons.
    - Tutor: sees only own lessons where teacher_id == user.id.
    - Admin: can see all or filter by teacher / student.
    """
    query = base_query or Lesson.query.order_by(Lesson.lesson_date.desc())

    if is_creator_or_admin(user):
        if teacher_filter:
            query = query.filter(Lesson.teacher_id == teacher_filter)
        if student_filter:
            query = query.filter(Lesson.student_id == student_filter)
    elif getattr(user, "is_tutor", None) and user.is_tutor():
        # Strict isolation: tutor only sees own lessons
        query = query.filter(Lesson.teacher_id == user.id)
        if student_filter:
            query = query.filter(Lesson.student_id == student_filter)
    elif getattr(user, "is_student", None) and user.is_student():
        student = Student.query.filter_by(user_id=user.id).first()
        if not student:
            return query.filter(False)
        query = query.filter(Lesson.student_id == student.student_id)
    else:
        # Default fail-closed
        return query.filter(False)

    if status_filter:
        query = query.filter(Lesson.status == status_filter)

    if period_start and period_end:
        query = query.filter(
            Lesson.lesson_date >= period_start,
            Lesson.lesson_date <= period_end,
        )

    return query


def acquire_scheduling_locks(student_id: int, tutor_user_id: Optional[int] = None) -> Tuple[Optional[Student], Optional[User]]:
    """
    Acquires pessimistic row-level locks on Student and Tutor records
    to serialize concurrent lesson creation and eliminate race conditions.
    Compatible with PostgreSQL (SELECT ... FOR UPDATE) and SQLite.
    """
    locked_student = None
    if student_id:
        locked_student = (
            Student.query.filter(Student.student_id == student_id)
            .with_for_update()
            .first()
        )
    locked_tutor = None
    if tutor_user_id:
        locked_tutor = (
            User.query.filter(User.id == tutor_user_id)
            .with_for_update()
            .first()
        )
    return locked_student, locked_tutor


def get_accessible_students_for_teacher(tutor_user: Optional[User]) -> list[dict]:
    """
    Returns verified students with an active educational relationship with tutor_user.
    Includes student_id, name, school_class, and allowed subjects list.
    Only students with confirmed relations are shown (never platform-wide unlinked students).
    """
    if not tutor_user or not getattr(tutor_user, "is_authenticated", False):
        return []

    if is_creator_or_admin(tutor_user):
        all_students = Student.query.filter_by(is_active=True).order_by(Student.name.asc()).all()
        result = []
        for s in all_students:
            subjects = set()
            if s.user_id:
                enrs = (
                    Enrollment.query.filter(
                        Enrollment.student_id == s.user_id,
                        Enrollment.status != "archived",
                    ).all()
                )
                subjects.update(e.subject.strip() for e in enrs if e.subject)
            if not subjects:
                subjects.add("Информатика")
            result.append({
                "student_id": s.student_id,
                "name": s.name,
                "school_class": s.school_class or "Ученик",
                "allowed_subjects": sorted(subjects),
            })
        return result

    student_user_ids = set(get_student_user_ids_for_tutor(tutor_user.id))
    mentor_students = Student.query.filter(
        Student.mentor_id == tutor_user.id,
        Student.is_active == True,
    ).all()

    students_by_user_id = []
    if student_user_ids:
        students_by_user_id = Student.query.filter(
            Student.user_id.in_(student_user_ids),
            Student.is_active == True,
        ).all()

    seen_ids = set()
    combined_students = []
    for s in (mentor_students + students_by_user_id):
        if s.student_id not in seen_ids:
            seen_ids.add(s.student_id)
            combined_students.append(s)

    combined_students.sort(key=lambda s: s.name or "")

    result = []
    for s in combined_students:
        allowed_subjects = set()
        if s.user_id:
            active_enrs = (
                Enrollment.query.filter(
                    Enrollment.student_id == s.user_id,
                    Enrollment.tutor_id == tutor_user.id,
                    Enrollment.status != "archived",
                ).all()
            )
            allowed_subjects.update(e.subject.strip() for e in active_enrs if e.subject)

        if not allowed_subjects:
            allowed_subjects.add("Информатика")

        result.append({
            "student_id": s.student_id,
            "id": s.student_id,
            "user_id": s.user_id,
            "name": s.name,
            "school_class": s.school_class or "Ученик",
            "allowed_subjects": sorted(allowed_subjects),
            "subjects": sorted(allowed_subjects),
        })

    return result


def resolve_historical_lesson_ownership(
    lesson_id: int,
    target_teacher_id: int,
    actor_user: User,
) -> Lesson:
    """
    Explicit, auditable resolution procedure for historical lessons with teacher_id IS NULL.
    Requires either admin privileges or confirmation that actor_user is the sole tutor.
    """
    lesson = db.session.get(Lesson, lesson_id)
    if not lesson:
        raise OwnershipValidationError(f"Урок #{lesson_id} не найден.")

    if lesson.teacher_id is not None and int(lesson.teacher_id) != int(target_teacher_id):
        if not is_creator_or_admin(actor_user):
            raise OwnershipSecurityError("Только администратор может переназначать преподавателя у распределенного урока.")

    if not is_creator_or_admin(actor_user):
        if int(actor_user.id) != int(target_teacher_id):
            raise OwnershipSecurityError("Вы не можете назначить исторический урок другому преподавателю.")
        student = db.session.get(Student, lesson.student_id) if lesson.student_id else None
        active_tutors = get_active_tutor_ids_for_student(student)
        if active_tutors != {actor_user.id}:
            raise OwnershipSecurityError(
                "Исторический урок относится к ученику с несколькими преподавателями. "
                "Разрешение принадлежности требует проверки администратора."
            )

    target_user = db.session.get(User, target_teacher_id)
    if not target_user:
        raise OwnershipValidationError(f"Преподаватель #{target_teacher_id} не найден.")

    lesson.teacher_id = target_teacher_id
    db.session.commit()
    logger.info(
        f"[HISTORICAL RESOLUTION] Lesson #{lesson_id} assigned to teacher #{target_teacher_id} by actor #{actor_user.id}"
    )
    return lesson
