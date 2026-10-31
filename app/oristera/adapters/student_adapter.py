"""
Адаптер данных для Student Nexus и связанных пространств Oristera.
Использует настоящие записи БД (Student, Lesson, Assignment, Submission, Course).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from flask_login import current_user
from sqlalchemy import or_, desc, asc

from app.models import (
    db,
    User,
    Student,
    Lesson,
    Assignment,
    Submission,
    StudentLearningPlanItem,
    StudentCourseEnrollment,
    LearningTrajectory,
    TrajectoryModule,
    LearningItem,
    GradebookEntry,
)
from app.oristera.adapters.tutor_core_adapter import get_student_skills_atlas, get_tutor_recommendations

logger = logging.getLogger(__name__)

RU_MONTHS = [
    "", "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря"
]


def _format_lesson_time(dt: Optional[datetime]) -> str:
    if not dt:
        return "Время согласовывается"
    # Приводим к МСК или отображаем HH:MM
    return dt.strftime("%H:%M")


def _format_lesson_date(dt: Optional[datetime]) -> str:
    if not dt:
        return "Дата не назначена"
    return f"{dt.day} {RU_MONTHS[dt.month]}"


def get_student_nexus_data(user: User) -> Dict[str, Any]:
    """Сборка полного контекста для Student Nexus."""
    student = Student.query.filter_by(user_id=user.id).first()
    if not student:
        # Поиск по fallback student_id == user.id
        candidate = Student.query.get(user.id)
        if candidate and (candidate.user_id is None or candidate.user_id == user.id):
            student = candidate

    now_utc = datetime.now(timezone.utc)
    hour = datetime.now().hour
    if 5 <= hour < 12:
        greeting = "Доброе утро"
    elif 12 <= hour < 18:
        greeting = "Добрый день"
    elif 18 <= hour < 23:
        greeting = "Добрый вечер"
    else:
        greeting = "Доброй ночи"

    active_lesson = None
    upcoming_lessons = []
    recent_lessons = []
    total_lessons = 0
    completed_lessons = 0
    completion_pct = 0
    mentor = None
    learning_path = []
    active_assignments = []
    recent_grades = []
    avg_score = "—"

    if student:
        # Наставник
        mentor_id = student.mentor_id or getattr(student, "tutor_id", None)
        if mentor_id:
            mentor = db.session.get(User, mentor_id)

        # Все уроки студента
        all_lessons = Lesson.query.filter_by(student_id=student.student_id).order_by(Lesson.lesson_date.asc()).all()
        total_lessons = len(all_lessons)
        completed_lessons = sum(1 for l in all_lessons if l.status == "completed")
        completion_pct = int(round((completed_lessons / total_lessons) * 100)) if total_lessons > 0 else 0

        # Активный урок (in_progress)
        active_lesson = next((l for l in all_lessons if l.status == "in_progress"), None)

        # Будущие уроки
        upcoming_lessons = [
            l for l in all_lessons
            if l.status == "planned" and (l.lesson_date is None or l.lesson_date.replace(tzinfo=timezone.utc) >= now_utc - timedelta(hours=2))
        ][:4]

        # Недавние завершенные
        recent_lessons = [l for l in all_lessons if l.status == "completed"][-4:]
        recent_lessons.reverse()

        # Активные домашние задания и работы
        try:
            submissions = (
                Submission.query.options(db.joinedload(Submission.assignment))
                .filter(
                    Submission.student_id == student.student_id,
                    Submission.status.in_(["ASSIGNED", "IN_PROGRESS", "RETURNED", "SUBMITTED"])
                )
                .order_by(Submission.submission_id.desc())
                .limit(6)
                .all()
            )
            for sub in submissions:
                asg = sub.assignment
                if asg and asg.is_active:
                    active_assignments.append({
                        "submission_id": sub.submission_id,
                        "assignment_id": asg.assignment_id,
                        "title": asg.title or f"Задание #{asg.assignment_id}",
                        "description": asg.description or "",
                        "status": sub.status,
                        "deadline": asg.deadline,
                        "deadline_formatted": _format_lesson_date(asg.deadline) if asg.deadline else "Без дедлайна",
                        "score": sub.score,
                        "max_score": sub.max_score,
                    })
        except Exception as e:
            logger.debug(f"Error fetching active assignments: {e}")

        # Средний балл
        try:
            graded = Submission.query.filter(
                Submission.student_id == student.student_id,
                Submission.status == "GRADED",
                Submission.score.isnot(None),
                Submission.max_score.isnot(None),
                Submission.max_score > 0
            ).all()
            if graded:
                pcts = [(float(s.score) / float(s.max_score)) * 100.0 for s in graded]
                avg_score = str(int(round(sum(pcts) / len(pcts))))
        except Exception as e:
            logger.debug(f"Error calculating avg score: {e}")

        # Образовательный маршрут (Learning Trajectory)
        try:
            plan_items = StudentLearningPlanItem.query.filter_by(student_id=student.student_id).order_by(
                StudentLearningPlanItem.priority.desc(),
                StudentLearningPlanItem.item_id.asc()
            ).limit(8).all()
            for p in plan_items:
                learning_path.append({
                    "id": p.item_id,
                    "title": p.title,
                    "notes": p.notes or "",
                    "status": p.status,  # 'planned', 'in_progress', 'done'
                    "due_date": p.due_date,
                    "due_formatted": _format_lesson_date(p.due_date) if p.due_date else None,
                })
        except Exception as e:
            logger.debug(f"Error fetching plan items: {e}")

    # Созвездия знаний из Atlas
    constellations = get_student_skills_atlas(user.id)
    tutor_recommendations = get_tutor_recommendations(user.id)

    # Целевые значения показываются только если они заданы в профиле.
    goal_target = getattr(student, "target_score", None) if student else None
    goal_current = getattr(student, "current_score", None) if student else None

    return {
        "user": user,
        "student": student,
        "greeting": greeting,
        "mentor": mentor,
        "active_lesson": active_lesson,
        "upcoming_lessons": upcoming_lessons,
        "recent_lessons": recent_lessons,
        "total_lessons": total_lessons,
        "completed_lessons": completed_lessons,
        "completion_pct": completion_pct,
        "avg_score": avg_score,
        "active_assignments": active_assignments,
        "learning_path": learning_path,
        "constellations": constellations,
        "tutor_recommendations": tutor_recommendations,
        "goal_target": goal_target,
        "goal_current": goal_current,
        "format_time": _format_lesson_time,
        "format_date": _format_lesson_date,
    }
