"""Application/read-model layer for the official BooStudy Telegram surface.

Telegram handlers should translate updates and render these DTOs.  This module
owns the bounded, permission-aware read queries so handlers do not grow more
role-specific SQL.  It deliberately contains no Telegram SDK types.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_

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
        rows = db.session.query(Student.student_id).filter(
            Student.mentor_id == user.id,
            Student.is_active.is_(True),
        ).all()
        return [int(row[0]) for row in rows]
    return []


def _lesson_dict(lesson: Lesson) -> dict[str, Any]:
    return {
        "id": int(lesson.lesson_id),
        "student_id": int(lesson.student_id) if lesson.student_id is not None else None,
        "topic": lesson.topic or "Урок",
        "starts_at": coerce_to_utc(lesson.lesson_date),
        "duration_minutes": int(lesson.duration or 60),
        "status": lesson.status or "planned",
        "room_available": bool(lesson.lesson_id),
        "deep_link": deep_links.lesson(lesson.lesson_id),
    }


def _assignment_dict(assignment: Assignment, submission: Submission | None) -> dict[str, Any]:
    status = (submission.status if submission else "ASSIGNED") or "ASSIGNED"
    return {
        "id": int(assignment.assignment_id),
        "title": assignment.title,
        "type": assignment.assignment_type,
        "deadline": coerce_to_utc(assignment.deadline),
        "submission_id": int(submission.submission_id) if submission else None,
        "status": status,
        "percentage": submission.percentage if submission else None,
        "deep_link": deep_links.assignment(assignment.assignment_id),
    }


def _student_today(user: User, context: str, student_ids: list[int]) -> TodayView:
    now = datetime.now(timezone.utc)
    lessons = db.session.query(Lesson).filter(
        Lesson.student_id.in_(student_ids),
        Lesson.lesson_date.isnot(None),
        Lesson.lesson_date >= now,
    ).order_by(Lesson.lesson_date.asc()).limit(8).all() if student_ids else []
    submissions = db.session.query(Submission).join(Assignment).filter(
        Submission.student_id.in_(student_ids),
        Assignment.is_active.is_(True),
    ).order_by(Assignment.deadline.asc()).limit(25).all() if student_ids else []
    assignments = [_assignment_dict(sub.assignment, sub) for sub in submissions]
    actions: list[ActionItem] = []
    for item in assignments:
        deadline = item["deadline"]
        status = str(item["status"]).upper()
        if deadline and status not in {"CHECKED", "GRADED", "COMPLETED"} and deadline < now:
            actions.append(ActionItem("assignment.overdue", "high", "Просроченное задание", item["title"], deadline, "assignment", item["id"], "open_assignment"))
        elif deadline and status not in {"CHECKED", "GRADED", "COMPLETED"}:
            actions.append(ActionItem("assignment.deadline", "normal", "Приближается дедлайн", item["title"], deadline, "assignment", item["id"], "open_assignment"))
    return TodayView(
        context=context,
        user_id=int(user.id),
        display_name=getattr(getattr(user, "profile", None), "first_name", None) or user.username,
        timezone=effective_timezone_name(user),
        lessons=tuple(_lesson_dict(lesson) for lesson in lessons),
        assignments=tuple(assignments),
        overdue_count=sum(1 for action in actions if action.type == "assignment.overdue"),
        actions=tuple(actions[:10]),
    )


def build_today_view(user: User, requested_context: str | None = None) -> TodayView:
    """Build the bounded Home read model for the active role."""
    context = resolve_active_context(user, requested_context)
    student_ids = _student_ids_for_context(user, context)
    if context in {"student", "parent"}:
        return _student_today(user, context, student_ids)

    now = datetime.now(timezone.utc)
    lessons = db.session.query(Lesson).join(Student, Lesson.student_id == Student.student_id).filter(
        Student.mentor_id == user.id,
        Lesson.lesson_date.isnot(None),
        Lesson.lesson_date >= now,
    ).order_by(Lesson.lesson_date.asc()).limit(12).all() if context in TEACHER_CONTEXTS or context == "teacher" else []
    review_count = db.session.query(Submission).join(Student, Submission.student_id == Student.student_id).filter(
        Student.mentor_id == user.id,
        Submission.status.in_(("SUBMITTED", "RETURNED", "IN_REVIEW")),
    ).count() if context in TEACHER_CONTEXTS or context == "teacher" else 0
    overdue_count = db.session.query(Submission).join(Student, Submission.student_id == Student.student_id).join(Assignment).filter(
        Student.mentor_id == user.id,
        Assignment.is_active.is_(True),
        Submission.status.notin_(('CHECKED', 'GRADED', 'COMPLETED')),
        Assignment.deadline.isnot(None), Assignment.deadline < now,
    ).count() if context in TEACHER_CONTEXTS or context == "teacher" else 0
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
    )


def build_teacher_review_queue(user: User, *, limit: int = 50) -> tuple[ReviewQueueItem, ...]:
    """Return only submissions belonging to the teacher's current scope."""
    if not (has_permission(user, "assignment.grade") or has_permission(user, "assignment.view")):
        return ()
    limit = max(1, min(int(limit), 100))
    rows = db.session.query(Submission, Student, Assignment).join(
        Student, Submission.student_id == Student.student_id
    ).join(
        Assignment, Submission.assignment_id == Assignment.assignment_id
    ).filter(
        Student.mentor_id == user.id,
        Submission.status.in_(("SUBMITTED", "IN_REVIEW", "RETURNED")),
    ).order_by(
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
    limit = max(1, min(int(limit), 100))
    rows = db.session.query(Student).filter(Student.mentor_id == user.id, Student.is_active.is_(True))
    term = (query or '').strip()
    if term:
        rows = rows.filter(Student.name.ilike(f'%{term}%'))
    students = rows.order_by(Student.name.asc()).limit(limit).all()
    ids = [int(item.student_id) for item in students]
    if not ids:
        return ()
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
    return tuple({
        'student_id': int(student.student_id), 'name': student.name,
        'active_assignments': int(dict(counts).get(student.student_id, 0)),
        'in_review': int(dict(review_counts).get(student.student_id, 0)),
        'deep_link': deep_links.student(student.student_id),
    } for student in students)


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
        result.append(ParentChildSummary(
            student_id=int(student.student_id),
            name=student.name,
            next_lesson=_lesson_dict(lesson) if lesson else None,
            active_assignments=len(active),
            overdue_assignments=len(overdue),
            latest_result_percent=float(latest.percentage) if latest and latest.percentage is not None else None,
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
    ).order_by(Assignment.deadline.asc()).limit(limit).all()
    normalized_filter = (status_filter or "").strip().lower()
    result: list[dict[str, Any]] = []
    for submission in rows:
        status = str(submission.status or "ASSIGNED").upper()
        category = "checked" if status in {"CHECKED", "GRADED", "COMPLETED"} else "in_review" if status in {"SUBMITTED", "IN_REVIEW", "RETURNED"} else "needs_action"
        if normalized_filter in {"pending", "needs_action"} and category != "needs_action":
            continue
        if normalized_filter in {"graded", "checked"} and category != "checked":
            continue
        result.append({
            "submission_id": int(submission.submission_id),
            "assignment_id": int(submission.assignment_id),
            "title": submission.assignment.title,
            "status": status,
            "category": category,
            "deadline": coerce_to_utc(submission.assignment.deadline),
            "percentage": submission.percentage,
            "url": deep_links.assignment(submission.assignment_id),
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
        Lesson.lesson_date >= now, Lesson.status.in_(('planned', 'in_progress')),
    ).order_by(Lesson.lesson_date.asc()).limit(max(1, min(int(limit), 50))).all())
    return tuple({
        'lesson_id': int(row.lesson_id), 'topic': row.topic or 'Урок',
        'starts_at': coerce_to_utc(row.lesson_date), 'duration': int(row.duration or 60),
        'status': row.status, 'lesson_url': deep_links.lesson(row.lesson_id),
    } for row in rows)


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
    return tuple({
        'lesson_id': int(row.lesson_id), 'student_id': int(row.student_id),
        'topic': row.topic or 'Урок', 'starts_at': coerce_to_utc(row.lesson_date),
        'duration': int(row.duration or 60), 'status': row.status,
        'lesson_url': deep_links.lesson(row.lesson_id),
    } for row in rows)


def build_student_progress(user: User, *, limit: int = 25) -> dict[str, Any] | None:
    if not user.is_student() or not has_permission(user, 'assignment.view'):
        return None
    ids = _student_ids_for_context(user, 'student')
    if not ids:
        return {'pending_homework': 0, 'submissions': [], 'gradebook': []}
    rows = (db.session.query(Submission).join(Assignment).filter(
        Submission.student_id.in_(ids), Assignment.is_active.is_(True),
    ).order_by(Submission.submitted_at.desc().nullslast(), Submission.submission_id.desc())
     .limit(max(1, min(int(limit), 50))).all())
    active = [row for row in rows if str(row.status or '').upper() in {'ASSIGNED', 'IN_PROGRESS', 'RETURNED'}]
    submissions = [{
        'assignment_id': int(row.assignment_id), 'title': row.assignment.title,
        'status': row.status, 'percentage': row.percentage,
        'updated_at': coerce_to_utc(row.updated_at or row.submitted_at),
        'assignment_url': deep_links.assignment(row.assignment_id),
    } for row in rows]
    return {'pending_homework': len(active), 'submissions': submissions, 'gradebook': []}


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
    ).filter(TelegramDelivery.status.in_(("pending", "retry", "failed")))
     .group_by(TelegramDelivery.status).all())
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
