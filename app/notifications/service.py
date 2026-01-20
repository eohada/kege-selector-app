from __future__ import annotations

import logging
from typing import Iterable

from app.models import db, User, Student, UserNotification, FamilyTie

logger = logging.getLogger(__name__)


def _get_student_user(student: Student) -> User | None:
    if not student:
        return None
    if getattr(student, 'email', None):
        u = User.query.filter_by(email=student.email, role='student').first()
        if u:
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


def notify_student_and_parents(student: Student, *, kind: str, title: str, body: str | None = None, link_url: str | None = None, meta: dict | None = None) -> None:
    st_user = _get_student_user(student)
    if not st_user:
        return

    notify_user(st_user.id, kind=kind, title=title, body=body, link_url=link_url, meta=meta)
    for parent_id in _get_parent_user_ids_for_student_user(st_user.id):
        notify_user(parent_id, kind=kind, title=title, body=body, link_url=link_url, meta=meta)

