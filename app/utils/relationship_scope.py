from __future__ import annotations

"""Shared helpers for role- and relationship-based access.

These helpers centralize how we resolve parent/child and tutor/student
relationships so routes, notifications and dashboards use the same rules.
"""

from typing import Iterable

from app.models import db, FamilyTie, Enrollment, User


def get_user_roles(user: User | None) -> set[str]:
    if not user:
        return set()
    try:
        roles = user.roles() if callable(getattr(user, 'roles', None)) else []
        return {str(r).strip() for r in roles if r}
    except Exception:
        role = getattr(user, 'role', None)
        return {str(role).strip()} if role else set()


def is_creator_or_admin(user: User | None) -> bool:
    roles = get_user_roles(user)
    return bool({'creator', 'chief_admin', 'admin'} & roles)


def get_confirmed_family_ties_for_parent(parent_id: int) -> list[FamilyTie]:
    return (
        FamilyTie.query
        .filter_by(parent_id=parent_id, is_confirmed=True)
        .order_by(FamilyTie.created_at.asc(), FamilyTie.tie_id.asc())
        .all()
    )


def get_family_ties_for_parent(parent_id: int, *, include_pending: bool = False) -> list[FamilyTie]:
    query = FamilyTie.query.filter_by(parent_id=parent_id)
    if not include_pending:
        query = query.filter_by(is_confirmed=True)
    return query.order_by(FamilyTie.created_at.asc(), FamilyTie.tie_id.asc()).all()


def get_family_tie_between(parent_id: int, student_id: int, *, include_pending: bool = True) -> FamilyTie | None:
    query = FamilyTie.query.filter_by(parent_id=parent_id, student_id=student_id)
    if not include_pending:
        query = query.filter_by(is_confirmed=True)
    return query.order_by(FamilyTie.created_at.asc(), FamilyTie.tie_id.asc()).first()


def get_confirmed_student_user_ids_for_parent(parent_id: int) -> list[int]:
    return [tie.student_id for tie in get_confirmed_family_ties_for_parent(parent_id) if tie.student_id]


def get_family_ties_for_student(student_user_id: int, *, include_pending: bool = False) -> list[FamilyTie]:
    query = FamilyTie.query.filter_by(student_id=student_user_id)
    if not include_pending:
        query = query.filter_by(is_confirmed=True)
    return query.order_by(FamilyTie.created_at.asc(), FamilyTie.tie_id.asc()).all()


def get_all_family_ties() -> list[FamilyTie]:
    return FamilyTie.query.order_by(FamilyTie.created_at.asc(), FamilyTie.tie_id.asc()).all()


def get_family_tie_by_id(tie_id: int) -> FamilyTie | None:
    return FamilyTie.query.filter_by(tie_id=tie_id).first()


def remove_family_ties_for_parent(parent_id: int) -> list[FamilyTie]:
    ties = get_family_ties_for_parent(parent_id, include_pending=True)
    for tie in ties:
        db.session.delete(tie)
    return ties


def remove_family_ties_for_student(student_user_id: int) -> list[FamilyTie]:
    ties = get_family_ties_for_student(student_user_id, include_pending=True)
    for tie in ties:
        db.session.delete(tie)
    return ties


def get_parent_user_ids_for_student(student_user_id: int) -> list[int]:
    return [tie.parent_id for tie in get_family_ties_for_student(student_user_id) if tie.parent_id]


def get_student_user_ids_for_tutor(tutor_id: int) -> list[int]:
    enrollments = (
        Enrollment.query
        .filter(Enrollment.tutor_id == tutor_id, Enrollment.status != 'archived')
        .all()
    )
    return [e.student_id for e in enrollments if e.student_id]


def get_visible_student_ids_for_user(user: User | None) -> list[int]:
    if not user:
        return []
    if is_creator_or_admin(user) or getattr(user, 'is_chief_tester', lambda: False)():
        return []

    visible: set[int] = set()
    if getattr(user, 'is_tutor', lambda: False)():
        visible.update(get_student_user_ids_for_tutor(int(user.id)))
    if getattr(user, 'is_parent', lambda: False)():
        visible.update(get_confirmed_student_user_ids_for_parent(int(user.id)))
    if getattr(user, 'is_student', lambda: False)():
        visible.add(int(user.id))
    return sorted(visible)


def can_user_access_student(user: User | None, student_user_id: int | None = None, student_platform_id: int | str | None = None) -> bool:
    if not user or student_user_id is None and student_platform_id is None:
        return False
    if is_creator_or_admin(user) or getattr(user, 'is_chief_tester', lambda: False)():
        return True
    visible = set(get_visible_student_ids_for_user(user))
    if student_user_id is not None and int(student_user_id) in visible:
        return True
    if student_platform_id is not None:
        try:
            sid = int(student_platform_id)
            if sid in visible:
                return True
        except Exception:
            pass
    return False


def get_family_tie_status_label(tie: FamilyTie | None) -> str:
    if not tie:
        return '—'
    return 'Подтверждена' if tie.is_confirmed else 'Ожидает подтверждения'
