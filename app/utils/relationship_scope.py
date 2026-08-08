from __future__ import annotations

"""Shared helpers for role- and relationship-based access.

These helpers centralize how we resolve parent/child and tutor/student
relationships so routes, notifications and dashboards use the same rules.
"""

from typing import Iterable

from app.models import db, FamilyTie, Enrollment, User


def _resolve_active_user(user: User | None) -> User | None:
    """Return a request-session user when Flask-Login holds a detached one."""
    if not user:
        return None
    state = getattr(user, '_sa_instance_state', None)
    if state is not None and state.detached and state.identity:
        return db.session.get(User, state.identity[0])
    return user


def get_user_roles(user: User | None) -> set[str]:
    user = _resolve_active_user(user)
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
    visible = set()
    try:
        from app.models import Enrollment, Student, User, SchoolGroup, GroupStudent, TeacherStudent
        ts_links = TeacherStudent.query.filter_by(teacher_id=tutor_id).all()
        for ts in ts_links:
            if ts.student_id:
                visible.add(ts.student_id)

        enrollments = (
            Enrollment.query
            .filter(Enrollment.tutor_id == tutor_id, Enrollment.status != 'archived')
            .all()
        )
        for e in enrollments:
            if e.student_id:
                visible.add(e.student_id)

        students_by_mentor = Student.query.filter(Student.mentor_id == tutor_id).all()
        for s in students_by_mentor:
            if s.user_id:
                visible.add(s.user_id)
            elif s.student_id:
                visible.add(s.student_id)

        if hasattr(User, 'teacher_id'):
            users_by_teacher = User.query.filter(
                User.role.in_(['student', 'STUDENT']),
                getattr(User, 'teacher_id') == tutor_id
            ).all()
            for u in users_by_teacher:
                visible.add(u.id)

        groups = SchoolGroup.query.filter(
            (SchoolGroup.owner_user_id == tutor_id) | (getattr(SchoolGroup, 'teacher_id', None) == tutor_id)
        ).all()
        group_ids = [g.group_id for g in groups if hasattr(g, 'group_id')]
        if group_ids:
            group_students = GroupStudent.query.filter(GroupStudent.group_id.in_(group_ids)).all()
            for gs in group_students:
                if gs.student:
                    if gs.student.user_id:
                        visible.add(gs.student.user_id)
                    elif gs.student.student_id:
                        visible.add(gs.student.student_id)
    except Exception as ex:
        import logging
        logging.getLogger('boostudy').warning(f"Error in get_student_user_ids_for_tutor({tutor_id}): {ex}")

    return list(visible)


def teacher_has_student(teacher_id: int, student_user_id: int) -> bool:
    """Проверяет, привязан ли данный ученик к преподавателю."""
    if not teacher_id or not student_user_id:
        return False
    user_ids = get_student_user_ids_for_tutor(teacher_id)
    return int(student_user_id) in user_ids


def parent_has_student(parent_id: int, student_user_id: int) -> bool:
    """Проверяет, привязан ли данный ученик к родителю."""
    if not parent_id or not student_user_id:
        return False
    tie = get_family_tie_between(parent_id, student_user_id, include_pending=False)
    return tie is not None


def get_visible_student_ids_for_user(user: User | None) -> list[int]:
    user = _resolve_active_user(user)
    if not user:
        return []
    if is_creator_or_admin(user) or getattr(user, 'is_chief_tester', lambda: False)():
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
        try:
            from core.db_models import Student
            stud = Student.query.filter_by(user_id=int(user.id)).first()
            if stud:
                visible.add(int(stud.student_id))
        except Exception:
            pass
    return sorted(visible)


def can_user_access_student(user: User | None, student_user_id: int | None = None, student_platform_id: int | str | None = None) -> bool:
    user = _resolve_active_user(user)
    if not user or (student_user_id is None and student_platform_id is None):
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
        try:
            from core.db_models import Student
            st = Student.query.filter(
                (Student.student_id == student_platform_id) | (Student.platform_id == str(student_platform_id))
            ).first()
            if st and ((st.user_id and int(st.user_id) in visible) or (st.student_id and int(st.student_id) in visible)):
                return True
        except Exception:
            pass
    return False


def get_family_tie_status_label(tie: FamilyTie | None) -> str:
    if not tie:
        return '—'
    return 'Подтверждена' if tie.is_confirmed else 'Ожидает подтверждения'
