"""Application/read-model layer for the official BooStudy Telegram surface.

Telegram handlers should translate updates and render these DTOs.  This module
owns the bounded, permission-aware read queries so handlers do not grow more
role-specific SQL.  It deliberately contains no Telegram SDK types.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, or_

from app.auth.rbac_utils import get_user_scope, has_permission
from app.models import (
    Assignment,
    FamilyTie,
    Lesson,
    Submission,
    Student,
    User,
    db,
)
from core.db_models import BugReport, TelegramDelivery
from app.utils.datetime_utc import coerce_to_utc, effective_timezone_name
from app.telegram import deep_links


ROLE_CONTEXTS = {"student", "teacher", "tutor", "parent", "admin", "creator"}
TEACHER_CONTEXTS = {"teacher", "tutor"}
ADMIN_CONTEXTS = {"admin", "creator"}


@dataclass(frozen=True)
class ActionItem:
    """A curated actionable item, never a raw event."""

    type: str
    priority: str
    title: str
    description: str | None = None
    timestamp: datetime | None = None
    entity_type: str | None = None
    entity_id: int | None = None
    primary_action: str | None = None
    deep_link: str | None = None


@dataclass(frozen=True)
class TodayView:
    context: str
    user_id: int
    display_name: str
    timezone: str
    lessons: tuple[dict[str, Any], ...] = ()
    assignments: tuple[dict[str, Any], ...] = ()
    pending_review_count: int = 0
    overdue_count: int = 0
    actions: tuple[ActionItem, ...] = ()
    urgent_assignments: tuple[dict[str, Any], ...] = ()
    recently_graded: dict[str, Any] | None = None
    teachers: tuple[dict[str, Any], ...] = ()
    oldest_submission: dict[str, Any] | None = None


@dataclass(frozen=True)
class ContextView:
    identity_user_id: int
    active_context: str
    available_contexts: tuple[str, ...]
    timezone: str


@dataclass(frozen=True)
class ReviewQueueItem:
    submission_id: int
    student_id: int
    student_name: str
    assignment_id: int
    assignment_title: str
    submitted_at: datetime | None
    status: str
    deep_link: str | None = None


@dataclass(frozen=True)
class ParentChildSummary:
    student_id: int
    name: str
    next_lesson: dict[str, Any] | None
    active_assignments: int
    overdue_assignments: int
    latest_result_percent: float | None
    category: str | None = None
    overdue_items: tuple[dict[str, Any], ...] = ()
    latest_graded_info: dict[str, Any] | None = None


@dataclass(frozen=True)
class ParentDigest:
    student_id: int
    completed_count: int
    active_count: int
    overdue_count: int
    latest_results: tuple[float, ...] = ()


@dataclass(frozen=True)
class OperationalSummary:
    users: int
    active_students: int
    active_teachers: int
    pending_reviews: int
    open_bug_reports: int
    pending_deliveries: int = 0
    retry_deliveries: int = 0
    failed_deliveries: int = 0
    sent_deliveries: int = 0
    oldest_review_wait_days: int = 0
    critical_bugs_count: int = 0


def _can_view_operations(user: User) -> bool:
    return bool(user.is_admin() or user.is_creator() or user.is_chief_admin())


def build_operational_problems(user: User, *, limit: int = 50) -> tuple[dict[str, Any], ...]:
    if not _can_view_operations(user):
        return ()
    limit = max(1, min(int(limit), 100))
    rows = (db.session.query(BugReport).filter(
        BugReport.status.in_(("NEW", "IN_PROGRESS", "new", "in_progress"))
    ).order_by(BugReport.severity.asc(), BugReport.created_at.asc()).limit(limit).all())
    return tuple({
        "id": int(row.id), "title": row.title, "severity": row.severity,
        "status": row.status, "created_at": coerce_to_utc(row.created_at),
        "deep_link": deep_links.bug_report(row.id),
    } for row in rows)


def search_operational_users(user: User, query: str, *, limit: int = 20) -> tuple[dict[str, Any], ...]:
    if not _can_view_operations(user):
        return ()
    term = (query or '').strip()
    if len(term) < 2:
        return ()
    limit = max(1, min(int(limit), 50))
    pattern = f"%{term}%"
    rows = (db.session.query(User).filter(User.is_active.is_(True), or_(
        User.username.ilike(pattern), User.numeric_id.ilike(pattern)
    )).order_by(User.username.asc()).limit(limit).all())
    return tuple({"user_id": int(row.id), "username": row.username, "role": row.role,
                  "deep_link": deep_links.user(row.id)} for row in rows)


def resolve_active_context(user: User, requested: str | None = None) -> str:
    """Resolve a role context and reject UI-only role escalation.

    ``creator_bot_mode`` is the existing persisted creator/teacher preference;
    it is only honored after the user's actual RBAC roles are checked.
    """
    actual = {str(role).lower() for role in (user.roles() if hasattr(user, "roles") else [user.role])}
    requested = (requested or "").strip().lower()
    if requested == "teacher" and (actual & ({"creator"} | TEACHER_CONTEXTS)):
        return "teacher"
    if requested == "creator" and "creator" in actual:
        return "creator"
    if requested in {"tutor", "teacher"} and requested in actual:
        return requested
    if requested in {"student", "parent", "admin"} and requested in actual:
        return requested

    if "creator" in actual:
        return "teacher" if str(getattr(user, "creator_bot_mode", "")).upper() == "TEACHER" else "creator"
    for preferred in ("admin", "tutor", "teacher", "parent", "student"):
        if preferred in actual:
            return preferred
    return str(getattr(user, "role", "student") or "student").lower()


def available_contexts(user: User) -> tuple[str, ...]:
    actual = {str(role).lower() for role in (user.roles() if hasattr(user, "roles") else [user.role])}
    contexts: list[str] = []
    if "creator" in actual:
        contexts.extend(("teacher", "creator"))
    elif actual & TEACHER_CONTEXTS:
        contexts.append("teacher" if "teacher" in actual else "tutor")
    for role in ("parent", "student", "admin"):
        if role in actual and role not in contexts:
            contexts.append(role)
    return tuple(contexts or (resolve_active_context(user),))


def context_view(user: User, requested: str | None = None) -> ContextView:
    return ContextView(
        identity_user_id=int(user.id),
        active_context=resolve_active_context(user, requested),
        available_contexts=available_contexts(user),
        timezone=effective_timezone_name(user),
    )


def _student_ids_for_context(user: User, context: str) -> list[int]:
    """Return Student primary keys, not User ids, for bounded joins."""
    scope = get_user_scope(user)
    if context in ADMIN_CONTEXTS and scope["can_see_all"]:
        return [row.student_id for row in db.session.query(Student.student_id).filter(Student.is_active.is_(True)).all()]
    if context == "student":
        row = db.session.query(Student.student_id).filter(Student.user_id == user.id, Student.is_active.is_(True)).first()
        return [int(row[0])] if row else []
    if context == "parent":
        rows = db.session.query(FamilyTie.student_id).filter(
            FamilyTie.parent_id == user.id,
            FamilyTie.is_confirmed.is_(True),
        ).all()
        ids = [int(row[0]) for row in rows]
        selected = getattr(getattr(user, 'profile', None), 'telegram_selected_child_id', None)
        if selected is not None and int(selected) in ids:
            return [int(selected)]
        return ids
    if context in TEACHER_CONTEXTS or context == "teacher":
        from app.utils.relationship_scope import get_student_user_ids_for_tutor
        student_uids = get_student_user_ids_for_tutor(user.id)
        conditions = [Student.mentor_id == user.id]
        if student_uids:
            conditions.append(Student.user_id.in_(student_uids))
        rows = db.session.query(Student.student_id).filter(
            or_(*conditions),
            Student.is_active.is_(True),
        ).distinct().all()
        return [int(row[0]) for row in rows]
    return []



def _lesson_dict(lesson: Lesson) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    teacher_name = None
    if lesson.teacher_id:
        tch = db.session.get(User, lesson.teacher_id)
        if tch:
            teacher_name = tch.full_name or tch.username
    starts_at = coerce_to_utc(lesson.lesson_date)
    duration = int(lesson.duration or 60)
    is_live = False
    if starts_at and lesson.status not in ("cancelled", "completed"):
        ends_at = starts_at + timedelta(minutes=duration)
        if starts_at <= now <= ends_at:
            is_live = True
    return {
        "id": int(lesson.lesson_id),
        "student_id": int(lesson.student_id) if lesson.student_id is not None else None,
        "subject": lesson.subject or "Занятие",
        "topic": lesson.topic or "Урок",
        "teacher_name": teacher_name,
        "teacher_id": lesson.teacher_id,
        "starts_at": starts_at,
        "duration": duration,
        "duration_minutes": duration,
        "status": lesson.status or "planned",
        "is_live": is_live,
        "room_available": bool(lesson.lesson_id),
        "lesson_url": deep_links.lesson(lesson.lesson_id),
        "deep_link": deep_links.lesson(lesson.lesson_id),
    }


def _assignment_dict(assignment: Assignment, submission: Submission | None) -> dict[str, Any]:
    status = (submission.status if submission else "ASSIGNED") or "ASSIGNED"
    teacher_name = None
    if assignment.created_by_id:
        tch = db.session.get(User, assignment.created_by_id)
        if tch:
            teacher_name = tch.full_name or tch.username
    return {
        "id": int(assignment.assignment_id),
        "assignment_id": int(assignment.assignment_id),
        "title": assignment.title,
        "type": assignment.assignment_type or "ДЗ",
        "teacher_name": teacher_name,
        "teacher_id": assignment.created_by_id,
        "deadline": coerce_to_utc(assignment.deadline),
        "submission_id": int(submission.submission_id) if submission else None,
        "status": status,
        "percentage": submission.percentage if submission else None,
        "total_score": getattr(submission, "total_score", None) if submission else None,
        "max_score": getattr(submission, "max_score", None) if submission else None,
        "teacher_feedback": getattr(submission, "teacher_feedback", None) if submission else None,
        "graded_at": coerce_to_utc(submission.graded_at) if submission and submission.graded_at else None,
        "submitted_at": coerce_to_utc(submission.submitted_at) if submission and submission.submitted_at else None,
        "deep_link": deep_links.assignment(assignment.assignment_id),
        "url": deep_links.assignment(assignment.assignment_id),
    }


def _student_today(user: User, context: str, student_ids: list[int]) -> TodayView:
    now = datetime.now(timezone.utc)
    lessons_raw = db.session.query(Lesson).filter(
        Lesson.student_id.in_(student_ids),
        Lesson.lesson_date.isnot(None),
        Lesson.lesson_date >= now - timedelta(hours=3),
        Lesson.status.notin_(("cancelled", "completed")),
    ).order_by(Lesson.lesson_date.asc()).limit(12).all() if student_ids else []
    lessons = []
    for l in lessons_raw:
        st_utc = coerce_to_utc(l.lesson_date)
        dur = int(l.duration or 60)
        if st_utc and st_utc + timedelta(minutes=dur) >= now:
            lessons.append(l)
    lessons = lessons[:8]
    submissions = db.session.query(Submission).join(Assignment).filter(
        Submission.student_id.in_(student_ids),
        Assignment.is_active.is_(True),
    ).order_by(Assignment.deadline.asc()).limit(25).all() if student_ids else []
    assignments = [_assignment_dict(sub.assignment, sub) for sub in submissions]

    actions: list[ActionItem] = []
    urgent_assignments = []
    teachers_dict: dict[int, dict[str, Any]] = {}

    for item in assignments:
        deadline = item["deadline"]
        status = str(item["status"]).upper()
        t_name = item.get("teacher_name")
        if t_name and item.get("teacher_id"):
            teachers_dict[item["teacher_id"]] = {
                "id": item["teacher_id"],
                "name": t_name,
                "subject": item.get("type", "Курс"),
            }

        if deadline and status not in {"CHECKED", "GRADED", "COMPLETED"}:
            is_overdue = deadline < now
            is_soon = not is_overdue and (deadline - now).total_seconds() <= 172800  # 48 hours
            if is_overdue:
                actions.append(ActionItem("assignment.overdue", "high", "Просроченное задание", item["title"], deadline, "assignment", item["id"], "open_assignment"))
                urgent_assignments.append({**item, "is_overdue": True})
            elif is_soon:
                actions.append(ActionItem("assignment.deadline", "normal", "Приближается дедлайн", item["title"], deadline, "assignment", item["id"], "open_assignment"))
                urgent_assignments.append({**item, "is_overdue": False})

    # Find teachers from lessons too
    for lesson in lessons:
        if lesson.teacher_id:
            tch = db.session.get(User, lesson.teacher_id)
            if tch:
                teachers_dict[lesson.teacher_id] = {
                    "id": lesson.teacher_id,
                    "name": tch.full_name or tch.username,
                    "subject": lesson.subject or "Информатика",
                }

    # Find recently graded submission
    recently_graded = None
    recent_graded_sub = db.session.query(Submission).join(Assignment).filter(
        Submission.student_id.in_(student_ids),
        Submission.status.in_(("CHECKED", "GRADED", "COMPLETED")),
        Submission.percentage.isnot(None),
    ).order_by(Submission.graded_at.desc().nullslast(), Submission.submission_id.desc()).first() if student_ids else None

    if recent_graded_sub:
        recently_graded = _assignment_dict(recent_graded_sub.assignment, recent_graded_sub)

    return TodayView(
        context=context,
        user_id=int(user.id),
        display_name=getattr(getattr(user, "profile", None), "first_name", None) or user.username,
        timezone=effective_timezone_name(user),
        lessons=tuple(_lesson_dict(lesson) for lesson in lessons),
        assignments=tuple(assignments),
        overdue_count=sum(1 for action in actions if action.type == "assignment.overdue"),
        actions=tuple(actions[:10]),
        urgent_assignments=tuple(urgent_assignments[:3]),
        recently_graded=recently_graded,
        teachers=tuple(teachers_dict.values()),
    )


def _build_teacher_review_query(user: User, student_ids: list[int] | None = None):
    scope = get_user_scope(user)
    if scope.get("can_see_all"):
        return db.session.query(Submission, Student, Assignment).join(
            Student, Submission.student_id == Student.student_id
        ).join(
            Assignment, Submission.assignment_id == Assignment.assignment_id
        ).filter(
            Submission.status.in_(("SUBMITTED", "IN_REVIEW", "RETURNED"))
        )
    if student_ids is None:
        student_ids = _student_ids_for_context(user, "teacher")

    lesson_taught_by_teacher = db.session.query(Lesson.lesson_id).filter(
        Lesson.lesson_id == Assignment.lesson_id,
        Lesson.teacher_id == user.id,
    ).exists()
    teacher_ownership = or_(
        Assignment.created_by_id == user.id,
        lesson_taught_by_teacher,
    )
    conditions = [teacher_ownership]
    if student_ids:
        conditions.append(and_(Student.student_id.in_(student_ids), Student.mentor_id == user.id))

    q = db.session.query(Submission, Student, Assignment).join(
        Student, Submission.student_id == Student.student_id
    ).join(
        Assignment, Submission.assignment_id == Assignment.assignment_id
    ).filter(
        or_(*conditions),
        Submission.status.in_(("SUBMITTED", "IN_REVIEW", "RETURNED")),
    )
    if student_ids:
        q = q.filter(Submission.student_id.in_(student_ids))
    return q


def can_teacher_review_submission(user: User, submission_id: int) -> bool:
    """Verify that user has permission and strictly scoped access to this submission (zero IDOR)."""
    if not (has_permission(user, "assignment.grade") or has_permission(user, "assignment.view")):
        return False
    scope = get_user_scope(user)
    if scope.get("can_see_all"):
        return bool(db.session.get(Submission, int(submission_id)))
    q = _build_teacher_review_query(user).filter(Submission.submission_id == int(submission_id))
    return db.session.query(q.exists()).scalar() is True


def build_today_view(user: User, requested_context: str | None = None) -> TodayView:
    """Build the bounded Home read model for the active role."""
    context = resolve_active_context(user, requested_context)
    student_ids = _student_ids_for_context(user, context)
    if context in {"student", "parent"}:
        return _student_today(user, context, student_ids)

    now = datetime.now(timezone.utc)
    teacher_lesson_cond = or_(
        Lesson.teacher_id == user.id,
        and_(Lesson.student_id.in_(student_ids), Lesson.teacher_id.is_(None)),
    ) if student_ids else (Lesson.teacher_id == user.id)

    lessons_raw = db.session.query(Lesson).filter(
        teacher_lesson_cond,
        Lesson.lesson_date.isnot(None),
        Lesson.lesson_date >= now - timedelta(hours=3),
        Lesson.status.notin_(('cancelled', 'completed')),
    ).order_by(Lesson.lesson_date.asc()).limit(16).all() if context in TEACHER_CONTEXTS or context == "teacher" else []
    lessons = []
    for l in lessons_raw:
        st_utc = coerce_to_utc(l.lesson_date)
        dur = int(l.duration or 60)
        if st_utc and st_utc + timedelta(minutes=dur) >= now:
            lessons.append(l)
    lessons = lessons[:12]

    review_count = _build_teacher_review_query(user, student_ids).count() if (context in TEACHER_CONTEXTS or context == "teacher") else 0
    overdue_count = db.session.query(Submission).join(Student, Submission.student_id == Student.student_id).join(Assignment).filter(
        Submission.student_id.in_(student_ids),
        Assignment.is_active.is_(True),
        Submission.status.notin_(('CHECKED', 'GRADED', 'COMPLETED')),
        Assignment.deadline.isnot(None), Assignment.deadline < now,
    ).count() if (context in TEACHER_CONTEXTS or context == "teacher") and student_ids else 0

    oldest_submission = None
    urgent_teacher_items = []
    if context in TEACHER_CONTEXTS or context == "teacher":
        oldest_row = _build_teacher_review_query(user, student_ids).order_by(
            Submission.submitted_at.asc().nullsfirst(),
            Submission.submission_id.asc(),
        ).first()
        if oldest_row:
            sub_r, st_r, asgn_r = oldest_row
            sub_utc = sub_r.submitted_at if (sub_r.submitted_at and sub_r.submitted_at.tzinfo) else (sub_r.submitted_at.replace(tzinfo=timezone.utc) if sub_r.submitted_at else None)
            wait_days = (now - sub_utc).days if sub_utc else 0
            oldest_submission = {
                "submission_id": int(sub_r.submission_id),
                "student_name": st_r.name,
                "student_id": int(st_r.student_id),
                "assignment_title": asgn_r.title,
                "submitted_at": coerce_to_utc(sub_r.submitted_at),
                "wait_days": max(0, wait_days),
            }

        if student_ids:
            overdue_rows = db.session.query(Submission, Student, Assignment).join(
                Student, Submission.student_id == Student.student_id
            ).join(
                Assignment, Submission.assignment_id == Assignment.assignment_id
            ).filter(
                Submission.student_id.in_(student_ids),
                Assignment.is_active.is_(True),
                Submission.status.notin_(('CHECKED', 'GRADED', 'COMPLETED')),
                Assignment.deadline.isnot(None), Assignment.deadline < now,
            ).order_by(Assignment.deadline.asc()).limit(3).all()

            for o_sub, o_st, o_asgn in overdue_rows:
                urgent_teacher_items.append({
                    "student_id": int(o_st.student_id),
                    "student_name": o_st.name,
                    "assignment_id": int(o_asgn.assignment_id),
                    "assignment_title": o_asgn.title,
                    "deadline": coerce_to_utc(o_asgn.deadline),
                })

    actions = ()
    teacher_actions = []
    if review_count:
        teacher_actions.append(ActionItem("submission.review", "high", "Работы ждут проверки", str(review_count), entity_type="submission", primary_action="open_review_queue"))
    if overdue_count:
        teacher_actions.append(ActionItem("assignment.overdue", "normal", "Просроченные задания учеников", str(overdue_count), entity_type="assignment", primary_action="open_students"))
    actions = tuple(teacher_actions)
    return TodayView(
        context=context,
        user_id=int(user.id),
        display_name=getattr(getattr(user, "profile", None), "first_name", None) or user.username,
        timezone=effective_timezone_name(user),
        lessons=tuple(_lesson_dict(lesson) for lesson in lessons),
        pending_review_count=int(review_count),
        overdue_count=int(overdue_count),
        actions=actions,
        urgent_assignments=tuple(urgent_teacher_items),
        oldest_submission=oldest_submission,
    )


def build_teacher_review_queue(user: User, *, limit: int = 50) -> tuple[ReviewQueueItem, ...]:
    """Return only submissions belonging to the teacher's current scope."""
    if not (has_permission(user, "assignment.grade") or has_permission(user, "assignment.view")):
        return ()
    limit = max(1, min(int(limit), 100))
    q = _build_teacher_review_query(user)
    rows = q.order_by(
        Submission.submitted_at.asc().nullsfirst(),
        Submission.submission_id.asc(),
    ).limit(limit).all()
    return tuple(
        ReviewQueueItem(
            submission_id=int(submission.submission_id),
            student_id=int(student.student_id),
            student_name=student.name,
            assignment_id=int(assignment.assignment_id),
            assignment_title=assignment.title,
            submitted_at=coerce_to_utc(submission.submitted_at),
            status=submission.status,
            deep_link=deep_links.submission(submission.submission_id) or deep_links.assignment(assignment.assignment_id),
        )
        for submission, student, assignment in rows
    )


def build_teacher_students(user: User, *, query: str = '', limit: int = 50) -> tuple[dict[str, Any], ...]:
    """Bounded teacher-scoped student cards, aggregated without per-student queries."""
    if not (user.is_tutor() or user.is_creator()) or not has_permission(user, 'assignment.view'):
        return ()
    student_ids = _student_ids_for_context(user, 'teacher')
    if not student_ids:
        return ()
    limit = max(1, min(int(limit), 100))
    rows = db.session.query(Student).filter(Student.student_id.in_(student_ids), Student.is_active.is_(True))
    term = (query or '').strip()
    if term:
        rows = rows.filter(Student.name.ilike(f'%{term}%'))
    students = rows.order_by(Student.name.asc()).limit(limit).all()
    ids = [int(item.student_id) for item in students]
    if not ids:
        return ()

    now = datetime.now(timezone.utc)
    counts = db.session.query(
        Submission.student_id, db.func.count(Submission.submission_id),
    ).join(Assignment).filter(
        Submission.student_id.in_(ids), Assignment.is_active.is_(True),
        Submission.status.notin_(('CHECKED', 'GRADED', 'COMPLETED')),
    ).group_by(Submission.student_id).all()
    review_counts = db.session.query(
        Submission.student_id, db.func.count(Submission.submission_id),
    ).filter(Submission.student_id.in_(ids), Submission.status.in_(('SUBMITTED', 'IN_REVIEW', 'RETURNED'))
    ).group_by(Submission.student_id).all()

    overdue_counts = db.session.query(
        Submission.student_id, db.func.count(Submission.submission_id),
    ).join(Assignment).filter(
        Submission.student_id.in_(ids), Assignment.is_active.is_(True),
        Submission.status.notin_(('CHECKED', 'GRADED', 'COMPLETED')),
        Assignment.deadline.isnot(None), Assignment.deadline < now,
    ).group_by(Submission.student_id).all()

    teacher_lesson_cond = or_(
        Lesson.teacher_id == user.id,
        and_(Lesson.student_id.in_(ids), Lesson.teacher_id.is_(None)),
    )
    next_lessons = db.session.query(Lesson).filter(
        Lesson.student_id.in_(ids),
        teacher_lesson_cond,
        Lesson.lesson_date.isnot(None),
        Lesson.lesson_date >= now - timedelta(hours=3),
        Lesson.status.notin_(('cancelled', 'completed')),
    ).order_by(Lesson.lesson_date.asc()).all()
    next_lesson_by_st: dict[int, Lesson] = {}
    for l in next_lessons:
        st_utc = coerce_to_utc(l.lesson_date)
        dur = int(l.duration or 60)
        if st_utc and st_utc + timedelta(minutes=dur) >= now:
            next_lesson_by_st.setdefault(int(l.student_id), l)

    from collections import Counter
    name_counts = Counter(s.name for s in students)
    result = []
    for student in students:
        display_name = student.name
        if name_counts[student.name] > 1:
            if getattr(student, "category", None):
                display_name = f"{student.name} ({student.category})"
            else:
                display_name = f"{student.name} (#{student.student_id})"

        nl = next_lesson_by_st.get(int(student.student_id))
        result.append({
            'student_id': int(student.student_id),
            'user_id': int(student.user_id) if student.user_id is not None else None,
            'name': display_name,
            'raw_name': student.name,
            'category': getattr(student, "category", None) or "ЕГЭ",
            'target_score': getattr(student, "target_score", None),
            'active_assignments': int(dict(counts).get(student.student_id, 0)),
            'in_review': int(dict(review_counts).get(student.student_id, 0)),
            'overdue_assignments': int(dict(overdue_counts).get(student.student_id, 0)),
            'next_lesson_topic': nl.topic if nl else None,
            'next_lesson_date': coerce_to_utc(nl.lesson_date) if nl else None,
            'deep_link': deep_links.student(student.student_id),
        })
    return tuple(result)



def build_parent_children(user: User, *, limit: int = 20) -> tuple[ParentChildSummary, ...]:
    """Build a privacy-safe summary for confirmed children only."""
    if not user.is_parent() or not has_permission(user, "assignment.view"):
        return ()
    limit = max(1, min(int(limit), 50))
    child_ids = _student_ids_for_context(user, "parent")[:limit]
    if not child_ids:
        return ()
    now = datetime.now(timezone.utc)
    students = db.session.query(Student).filter(Student.student_id.in_(child_ids)).all()
    lessons = db.session.query(Lesson).filter(
        Lesson.student_id.in_(child_ids),
        Lesson.lesson_date.isnot(None),
        Lesson.lesson_date >= now,
    ).order_by(Lesson.lesson_date.asc()).all()
    submissions = db.session.query(Submission).join(Assignment).filter(
        Submission.student_id.in_(child_ids),
        Assignment.is_active.is_(True),
    ).all()
    lesson_by_student: dict[int, Lesson] = {}
    for lesson in lessons:
        lesson_by_student.setdefault(int(lesson.student_id), lesson)
    submissions_by_student: dict[int, list[Submission]] = {}
    for submission in submissions:
        submissions_by_student.setdefault(int(submission.student_id), []).append(submission)

    result: list[ParentChildSummary] = []
    for student in students:
        lesson = lesson_by_student.get(int(student.student_id))
        submissions = submissions_by_student.get(int(student.student_id), [])
        active = [s for s in submissions if str(s.status).upper() not in {"CHECKED", "GRADED", "COMPLETED"}]
        overdue = [s for s in active if s.assignment and s.assignment.deadline and coerce_to_utc(s.assignment.deadline) < now]
        graded = [s for s in submissions if s.percentage is not None]
        latest = max(graded, key=lambda s: coerce_to_utc(s.graded_at) or datetime.min.replace(tzinfo=timezone.utc)) if graded else None
        overdue_items = tuple(_assignment_dict(s.assignment, s) for s in overdue if s.assignment)
        latest_graded_info = _assignment_dict(latest.assignment, latest) if latest and latest.assignment else None
        category = "overdue" if overdue else ("active" if active else "good")
        result.append(ParentChildSummary(
            student_id=int(student.student_id),
            name=student.name,
            next_lesson=_lesson_dict(lesson) if lesson else None,
            active_assignments=len(active),
            overdue_assignments=len(overdue),
            latest_result_percent=float(latest.percentage) if latest and latest.percentage is not None else None,
            category=category,
            overdue_items=overdue_items,
            latest_graded_info=latest_graded_info,
        ))
    return tuple(result)


def build_parent_digest(user: User, student_id: int | None = None) -> ParentDigest | None:
    """Safe bounded weekly digest for one confirmed child."""
    if not user.is_parent() or not has_permission(user, "assignment.view"):
        return None
    allowed = set(_student_ids_for_context(user, "parent"))
    if student_id is None:
        student_id = next(iter(allowed), None)
    if student_id is None or int(student_id) not in allowed:
        return None
    rows = (db.session.query(Submission).join(Assignment)
            .filter(Submission.student_id == int(student_id), Assignment.is_active.is_(True))
            .order_by(Submission.graded_at.desc().nullslast(), Submission.submission_id.desc())
            .limit(50).all())
    completed = [row for row in rows if str(row.status or '').upper() in {"CHECKED", "GRADED", "COMPLETED"}]
    active = [row for row in rows if row not in completed]
    now = datetime.now(timezone.utc)
    overdue = [row for row in active if row.assignment and row.assignment.deadline and coerce_to_utc(row.assignment.deadline) < now]
    results = tuple(float(row.percentage) for row in completed if row.percentage is not None)[:3]
    return ParentDigest(int(student_id), len(completed), len(active), len(overdue), results)


def selected_parent_child_id(user: User) -> int | None:
    if not user.is_parent():
        return None
    selected = getattr(getattr(user, 'profile', None), 'telegram_selected_child_id', None)
    allowed = set(_student_ids_for_context(user, "parent"))
    return int(selected) if selected is not None and int(selected) in allowed else None


def select_parent_child(user: User, student_id: int) -> int | None:
    allowed = {int(row[0]) for row in db.session.query(FamilyTie.student_id).filter(
        FamilyTie.parent_id == user.id, FamilyTie.is_confirmed.is_(True)
    ).all()}
    if not user.is_parent() or int(student_id) not in allowed:
        return None
    profile = getattr(user, 'profile', None)
    if profile is None:
        return None
    profile.telegram_selected_child_id = int(student_id)
    db.session.commit()
    return int(student_id)


def build_student_assignments(
    user: User,
    *,
    status_filter: str | None = None,
    limit: int = 100,
) -> tuple[dict[str, Any], ...]:
    """Return assignments using the canonical submission lifecycle labels."""
    if not user.is_student() or not has_permission(user, "assignment.view"):
        return ()
    student_ids = _student_ids_for_context(user, "student")
    if not student_ids:
        return ()
    limit = max(1, min(int(limit), 100))
    rows = db.session.query(Submission).join(Assignment).filter(
        Submission.student_id.in_(student_ids),
        Assignment.is_active.is_(True),
    ).order_by(Assignment.deadline.asc().nullslast(), Submission.submission_id.desc()).limit(limit).all()
    normalized_filter = (status_filter or "").strip().lower()
    now = datetime.now(timezone.utc)
    result: list[dict[str, Any]] = []
    for submission in rows:
        asgn = submission.assignment
        status = str(submission.status or "ASSIGNED").upper()
        is_graded = status in {"CHECKED", "GRADED", "COMPLETED"}
        is_in_review = status in {"SUBMITTED", "IN_REVIEW"}
        is_active = not is_graded and not is_in_review
        dl = coerce_to_utc(asgn.deadline)
        is_urgent = is_active and dl is not None and (dl < now or (dl - now).total_seconds() <= 172800)

        # Canonical category
        if is_graded:
            cat = "graded"
        elif is_in_review:
            cat = "review"
        elif is_urgent:
            cat = "urgent"
        else:
            cat = "active"

        # Filter check
        if normalized_filter in {"urgent"}:
            if not is_urgent:
                continue
        elif normalized_filter in {"active", "in_progress", "pending", "needs_action"}:
            if not is_active:
                continue
        elif normalized_filter in {"review", "in_review"}:
            if not is_in_review:
                continue
        elif normalized_filter in {"graded", "checked"}:
            if not is_graded:
                continue

        # Teacher info
        teacher_name = None
        if asgn.created_by_id:
            tch = db.session.get(User, asgn.created_by_id)
            if tch:
                teacher_name = tch.full_name or tch.username

        result.append({
            "submission_id": int(submission.submission_id),
            "assignment_id": int(asgn.assignment_id),
            "title": asgn.title,
            "description": asgn.description,
            "assignment_type": asgn.assignment_type or "ДЗ",
            "teacher_name": teacher_name,
            "teacher_id": asgn.created_by_id,
            "status": status,
            "category": cat,
            "deadline": dl,
            "percentage": submission.percentage,
            "total_score": getattr(submission, "total_score", None),
            "max_score": getattr(submission, "max_score", None),
            "teacher_feedback": getattr(submission, "teacher_feedback", None) or getattr(submission, "teacher_comment", None),
            "submitted_at": coerce_to_utc(submission.submitted_at),
            "graded_at": coerce_to_utc(submission.graded_at),
            "is_urgent": is_urgent,
            "url": deep_links.assignment(asgn.assignment_id),
        })
    return tuple(result)


def build_student_schedule(user: User, *, limit: int = 20) -> tuple[dict[str, Any], ...]:
    if not user.is_student() or not has_permission(user, 'schedule.view'):
        return ()
    ids = _student_ids_for_context(user, 'student')
    if not ids:
        return ()
    now = datetime.now(timezone.utc)
    rows = (db.session.query(Lesson).filter(
        Lesson.student_id.in_(ids), Lesson.lesson_date.isnot(None),
        Lesson.lesson_date >= now - timedelta(hours=3), Lesson.status.in_(('planned', 'in_progress')),
    ).order_by(Lesson.lesson_date.asc()).limit(max(1, min(int(limit), 50))).all())
    teacher_ids = {row.teacher_id for row in rows if row.teacher_id}
    teachers = {u.id: (u.full_name or u.username) for u in db.session.query(User).filter(User.id.in_(teacher_ids)).all()} if teacher_ids else {}
    active_lessons = []
    for row in rows:
        st_utc = coerce_to_utc(row.lesson_date)
        dur = int(row.duration or 60)
        if not st_utc or st_utc + timedelta(minutes=dur) < now:
            continue
        is_live = (st_utc <= now <= st_utc + timedelta(minutes=dur))
        active_lessons.append({
            'lesson_id': int(row.lesson_id),
            'topic': row.topic or 'Урок',
            'subject': row.subject or 'Информатика',
            'starts_at': st_utc,
            'duration': dur,
            'status': row.status,
            'is_live': is_live,
            'lesson_url': deep_links.lesson(row.lesson_id),
            'teacher_name': teachers.get(row.teacher_id) if row.teacher_id else None,
        })
    return tuple(active_lessons[:limit])


def build_parent_schedule(user: User, *, limit: int = 20) -> tuple[dict[str, Any], ...] | None:
    if not user.is_parent() or not has_permission(user, 'schedule.view'):
        return None
    ids = _student_ids_for_context(user, 'parent')
    if not ids:
        return ()
    now = datetime.now(timezone.utc)
    rows = (db.session.query(Lesson).filter(
        Lesson.student_id.in_(ids), Lesson.lesson_date.isnot(None),
        Lesson.lesson_date >= now, Lesson.status.in_(('planned', 'in_progress')),
    ).order_by(Lesson.lesson_date.asc()).limit(max(1, min(int(limit), 50))).all())
    teacher_ids = {row.teacher_id for row in rows if row.teacher_id}
    teachers = {u.id: (u.full_name or u.username) for u in db.session.query(User).filter(User.id.in_(teacher_ids)).all()} if teacher_ids else {}
    return tuple({
        'lesson_id': int(row.lesson_id), 'student_id': int(row.student_id),
        'topic': row.topic or 'Урок', 'starts_at': coerce_to_utc(row.lesson_date),
        'duration': int(row.duration or 60), 'status': row.status,
        'lesson_url': deep_links.lesson(row.lesson_id),
        'teacher_name': teachers.get(row.teacher_id) if row.teacher_id else None,
    } for row in rows)


def build_student_progress(user: User, *, limit: int = 25) -> dict[str, Any] | None:
    if not user.is_student() or not has_permission(user, 'assignment.view'):
        return None
    ids = _student_ids_for_context(user, 'student')
    if not ids:
        return {'pending_homework': 0, 'submissions': [], 'by_subject': {}, 'gradebook': []}
    rows = (db.session.query(Submission).join(Assignment).filter(
        Submission.student_id.in_(ids), Assignment.is_active.is_(True),
    ).order_by(Submission.graded_at.desc().nullslast(), Submission.submitted_at.desc().nullslast(), Submission.submission_id.desc())
     .limit(max(1, min(int(limit), 50))).all())
    active = [row for row in rows if str(row.status or '').upper() in {'ASSIGNED', 'IN_PROGRESS', 'RETURNED'}]

    teacher_ids = {row.assignment.created_by_id for row in rows if row.assignment and row.assignment.created_by_id}
    teachers = {u.id: (u.full_name or u.username) for u in db.session.query(User).filter(User.id.in_(teacher_ids)).all()} if teacher_ids else {}

    submissions = []
    subject_scores: dict[str, list[float]] = {}
    for row in rows:
        t_name = teachers.get(row.assignment.created_by_id) if row.assignment and row.assignment.created_by_id else None
        subj = row.assignment.assignment_type or "Курс"
        pct = float(row.percentage) if row.percentage is not None else None
        sub_dict = {
            'submission_id': int(row.submission_id),
            'assignment_id': int(row.assignment_id),
            'title': row.assignment.title,
            'subject': subj,
            'teacher_name': t_name,
            'status': row.status,
            'percentage': pct,
            'total_score': getattr(row, 'total_score', None),
            'max_score': getattr(row, 'max_score', None),
            'graded_at': coerce_to_utc(row.graded_at),
            'updated_at': coerce_to_utc(row.updated_at or row.submitted_at),
            'assignment_url': deep_links.assignment(row.assignment_id),
        }
        submissions.append(sub_dict)
        if pct is not None:
            subj_label = f"{subj} ({t_name})" if t_name else subj
            subject_scores.setdefault(subj_label, []).append(pct)

    by_subject = {
        k: {
            "count": len(scores),
            "avg": sum(scores) / len(scores),
        }
        for k, scores in subject_scores.items()
    }

    return {
        'pending_homework': len(active),
        'submissions': submissions,
        'by_subject': by_subject,
        'gradebook': [],
    }


def build_parent_progress(user: User, *, limit: int = 25) -> dict[str, Any] | None:
    if not user.is_parent() or not has_permission(user, 'gradebook.view'):
        return None
    ids = _student_ids_for_context(user, 'parent')
    if not ids:
        return {'pending_homework': 0, 'submissions': [], 'gradebook': []}
    rows = (db.session.query(Submission).join(Assignment).filter(
        Submission.student_id.in_(ids), Assignment.is_active.is_(True),
    ).order_by(Submission.graded_at.desc().nullslast(), Submission.submission_id.desc())
     .limit(max(1, min(int(limit), 50))).all())
    active = [row for row in rows if str(row.status or '').upper() not in {'CHECKED', 'GRADED', 'COMPLETED'}]
    gradebook = [{
        'title': row.assignment.title, 'score': float(row.percentage) if row.percentage is not None else None,
        'max_score': 100, 'created_at': coerce_to_utc(row.graded_at),
    } for row in rows if row.percentage is not None][:8]
    return {'pending_homework': len(active), 'submissions': [], 'gradebook': gradebook}


def build_operational_summary(user: User) -> OperationalSummary | None:
    """Read-only admin/creator counts backed by existing tables only."""
    if not _can_view_operations(user):
        return None
    pending_reviews = db.session.query(Submission).filter(
        Submission.status.in_(("SUBMITTED", "IN_REVIEW", "RETURNED"))
    ).count()
    open_bugs = db.session.query(BugReport).filter(
        BugReport.status.in_(("NEW", "IN_PROGRESS", "new", "in_progress"))
    ).count()
    delivery_counts = dict(db.session.query(
        TelegramDelivery.status, db.func.count(TelegramDelivery.delivery_id)
    ).filter(TelegramDelivery.status.in_(("pending", "retry", "failed", "sent")))
     .group_by(TelegramDelivery.status).all())

    oldest_sub = db.session.query(Submission).filter(
        Submission.status.in_(("SUBMITTED", "IN_REVIEW", "RETURNED")),
        Submission.submitted_at.isnot(None),
    ).order_by(Submission.submitted_at.asc()).first()
    oldest_review_wait_days = 0
    if oldest_sub and oldest_sub.submitted_at:
        wait_sec = (datetime.now(timezone.utc) - coerce_to_utc(oldest_sub.submitted_at)).total_seconds()
        oldest_review_wait_days = max(0, int(wait_sec // 86400))

    critical_bugs = db.session.query(BugReport).filter(
        BugReport.status.in_(("NEW", "IN_PROGRESS", "new", "in_progress")),
        BugReport.severity.in_(("CRITICAL", "HIGH", "critical", "high")),
    ).count()

    return OperationalSummary(
        users=db.session.query(User).filter(User.is_active.is_(True)).count(),
        active_students=db.session.query(Student).filter(Student.is_active.is_(True)).count(),
        active_teachers=db.session.query(User).filter(
            User.is_active.is_(True),
            User.role.in_(("teacher", "tutor")),
        ).count(),
        pending_reviews=int(pending_reviews),
        open_bug_reports=int(open_bugs),
        pending_deliveries=int(delivery_counts.get('pending', 0)),
        retry_deliveries=int(delivery_counts.get('retry', 0)),
        failed_deliveries=int(delivery_counts.get('failed', 0)),
        sent_deliveries=int(delivery_counts.get('sent', 0)),
        oldest_review_wait_days=oldest_review_wait_days,
        critical_bugs_count=int(critical_bugs),
    )


def build_action_center(user: User, requested_context: str | None = None) -> tuple[ActionItem, ...]:
    """Return curated attention items for the active context."""
    context = resolve_active_context(user, requested_context)
    view = build_today_view(user, context)
    actions = list(view.actions)
    if context in TEACHER_CONTEXTS or context == "teacher":
        queue = build_teacher_review_queue(user)
        if queue:
            actions.append(ActionItem(
                "submission.review",
                "high",
                "Работы ждут проверки",
                f"{len(queue)} работ",
                entity_type="submission",
                primary_action="open_review_queue",
            ))
    priority_rank = {'critical': 0, 'high': 1, 'normal': 2, 'low': 3}
    actions.sort(key=lambda item: (
        priority_rank.get(item.priority, 9),
        coerce_to_utc(item.timestamp) or datetime.max.replace(tzinfo=timezone.utc),
        item.type,
    ))
    return tuple(actions[:20])
