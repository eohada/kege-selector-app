"""
Адаптер данных для Parent Nexus в Oristera.
Строго соблюдает разграничение доступа FamilyTie: отображает только подтверждённых детей.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.models import db, User, Student, Lesson, FamilyTie, Submission, Assignment
from app.utils.relationship_scope import get_family_ties_for_parent

logger = logging.getLogger(__name__)


def get_parent_nexus_data(parent_user: User) -> Dict[str, Any]:
    """Сборка данных для Parent Nexus."""
    family_ties = get_family_ties_for_parent(parent_user.id, include_pending=True)
    confirmed_ties = [t for t in family_ties if t.is_confirmed]
    pending_ties = [t for t in family_ties if not t.is_confirmed]

    children_data = []
    for tie in confirmed_ties:
        # tie.student_id указывает либо на student.student_id, либо на student_user.id
        student = None
        student_user = None
        if tie.student_id:
            # Сначала ищем по student_id
            student = Student.query.get(tie.student_id)
            if not student:
                # Пробуем по user_id
                student = Student.query.filter_by(user_id=tie.student_id).first()
                if student:
                    student_user = db.session.get(User, tie.student_id)
            else:
                if student.user_id:
                    student_user = db.session.get(User, student.user_id)

        if not student:
            continue

        # Уроки ребёнка
        lessons = Lesson.query.filter_by(student_id=student.student_id).order_by(Lesson.lesson_date.asc()).all()
        upcoming_lessons = [l for l in lessons if l.status == "planned"][:3]
        recent_lessons = [l for l in lessons if l.status == "completed"][-3:]
        recent_lessons.reverse()

        # Наставник
        mentor = None
        if student.mentor_id:
            mentor = db.session.get(User, student.mentor_id)

        # Выполненные задания
        submissions = (
            Submission.query.options(db.joinedload(Submission.assignment))
            .filter_by(student_id=student.student_id)
            .order_by(Submission.submission_id.desc())
            .limit(5)
            .all()
        )

        total_lessons = len(lessons)
        completed_count = sum(1 for l in lessons if l.status == "completed")

        children_data.append({
            "student": student,
            "student_user": student_user,
            "child_name": student.name or (student_user.full_name if student_user else f"Ребёнок #{student.student_id}"),
            "mentor": mentor,
            "total_lessons": total_lessons,
            "completed_lessons": completed_count,
            "upcoming_lessons": upcoming_lessons,
            "recent_lessons": recent_lessons,
            "submissions": submissions,
            "target_score": getattr(student, "target_score", None),
            "current_score": getattr(student, "current_score", None),
        })

    return {
        "parent": parent_user,
        "children": children_data,
        "pending_count": len(pending_ties),
        "has_children": len(children_data) > 0,
    }
