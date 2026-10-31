"""
Адаптер данных для Teacher Studio в Oristera.
Связывает реальных учеников, расписание, проверку работ и дидактические инструменты.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from app.models import db, User, Student, Lesson, Submission, Assignment
from app.main.teacher_dashboard_service import (
    get_teacher_students,
    load_teacher_todos,
    save_teacher_todos,
    to_naive,
    moscow_now,
    RU_WEEKDAYS,
    RU_MONTHS,
)
from app.utils.relationship_scope import is_creator_or_admin

logger = logging.getLogger(__name__)


def get_teacher_studio_data(teacher_user: User) -> Dict[str, Any]:
    """Сборка данных для рабочего кабинета преподавателя Teacher Studio."""
    now = to_naive(moscow_now())
    hour = now.hour
    if 5 <= hour < 12:
        greeting = "Доброе утро"
    elif 12 <= hour < 18:
        greeting = "Добрый день"
    else:
        greeting = "Добрый вечер"

    date_formatted = f"{RU_WEEKDAYS[now.weekday()]}, {now.day} {RU_MONTHS[now.month]}"

    # Список реальных учеников
    students = get_teacher_students(teacher_user)
    student_ids = [s.student_id for s in students if s.student_id]
    active_students_count = len([s for s in students if getattr(s, "is_active", True)])

    # Уроки преподавателя
    # Уроки могут быть привязаны через student_id
    all_lessons = []
    if student_ids:
        all_lessons = (
            Lesson.query.options(db.joinedload(Lesson.student))
            .filter(Lesson.student_id.in_(student_ids))
            .order_by(Lesson.lesson_date.asc())
            .all()
        )

    # Разделяем на сегодняшние, будущие и активные
    active_lesson = next((l for l in all_lessons if l.status == "in_progress"), None)
    
    today_lessons = [
        l for l in all_lessons
        if l.lesson_date and to_naive(l.lesson_date).date() == now.date()
    ]

    upcoming_lessons = [
        l for l in all_lessons
        if l.status == "planned" and l.lesson_date and to_naive(l.lesson_date) >= now
    ][:6]

    # Работы на проверку (Pending Submissions)
    q_subs = Submission.query.options(
        db.joinedload(Submission.assignment),
        db.joinedload(Submission.student)
    )
    if not is_creator_or_admin(teacher_user):
        if student_ids:
            q_subs = q_subs.filter(Submission.student_id.in_(student_ids))
        else:
            q_subs = q_subs.filter(False)

    pending_submissions = (
        q_subs.filter(Submission.status.in_(["SUBMITTED", "NEEDS_MANUAL_REVIEW"]))
        .order_by(Submission.submitted_at.asc())
        .limit(10)
        .all()
    )

    # Список дел преподавателя
    todos = load_teacher_todos(teacher_user.id)

    # Детальная статистика по каждому ученику для быстрого выбора
    students_summary = []
    for s in students[:12]:
        st_lessons = [l for l in all_lessons if l.student_id == s.student_id]
        comp_count = sum(1 for l in st_lessons if l.status == "completed")
        next_les = next((l for l in st_lessons if l.status == "planned"), None)
        students_summary.append({
            "student_id": s.student_id,
            "user_id": s.user_id,
            "name": s.name or (f"Ученик #{s.student_id}"),
            "category": getattr(s, "category", "ЕГЭ"),
            "completed_lessons": comp_count,
            "next_lesson": next_les,
            "target_score": getattr(s, "target_score", None),
            "current_score": getattr(s, "current_score", None),
        })

    return {
        "teacher": teacher_user,
        "greeting": greeting,
        "date_formatted": date_formatted,
        "active_students_count": active_students_count,
        "active_lesson": active_lesson,
        "today_lessons": today_lessons,
        "upcoming_lessons": upcoming_lessons,
        "pending_submissions": pending_submissions,
        "pending_reviews_count": len(pending_submissions),
        "todos": todos,
        "students": students_summary,
    }
