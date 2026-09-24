from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, date
from typing import Any, Dict, List, Optional
from flask import current_app
from sqlalchemy import or_, and_, func

from app import db
from core.db_models import (
    User,
    Student,
    Lesson,
    Submission,
    Assignment,
    Course,
    TeacherStudent,
    moscow_now,
)
from app.utils.relationship_scope import get_student_user_ids_for_tutor, is_creator_or_admin

RU_WEEKDAYS = [
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
]
RU_MONTHS = [
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
]


def to_naive(dt: Any) -> Any:
    """Нормализует datetime к offset-naive для безопасного сравнения."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.replace(tzinfo=None) if getattr(dt, "tzinfo", None) else dt
    return dt


def _get_todo_filepath(user_id: int) -> str:
    instance_path = getattr(current_app, "instance_path", "/tmp")
    os.makedirs(instance_path, exist_ok=True)
    return os.path.join(instance_path, f"teacher_todo_{user_id}.json")


def load_teacher_todos(user_id: int) -> List[Dict[str, Any]]:
    path = _get_todo_filepath(user_id)
    if not os.path.exists(path):
        return [
            {"id": 1, "text": "Проверить поступившие ДЗ", "done": False},
            {"id": 2, "text": "Подготовиться к ближайшему уроку", "done": False},
            {"id": 3, "text": "Составить план на следующую неделю", "done": False},
        ]
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_teacher_todos(user_id: int, todos: List[Dict[str, Any]]) -> None:
    path = _get_todo_filepath(user_id)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(todos, f, ensure_ascii=False, indent=2)
    except Exception as e:
        current_app.logger.warning(f"Failed to save teacher todos: {e}")


def get_teacher_students(teacher_user: User) -> List[Student]:
    """Возвращает актуальный список учеников, привязанных к преподавателю."""
    is_admin = is_creator_or_admin(teacher_user)
    if is_admin:
        all_active = Student.query.filter(Student.is_active == True).order_by(Student.name.asc()).all()
        return all_active if all_active else Student.query.order_by(Student.name.asc()).all()

    student_user_ids = get_student_user_ids_for_tutor(teacher_user.id)

    conds = [Student.mentor_id == teacher_user.id]
    if student_user_ids:
        conds.append(Student.user_id.in_(student_user_ids))
        conds.append(Student.student_id.in_(student_user_ids))

    students = Student.query.filter(or_(*conds)).order_by(Student.name.asc()).all()

    # В режиме разработки/тестирования для нового тьютора без привязок показываем активных учеников
    if not students and (current_app.config.get("TESTING") or current_app.config.get("DEBUG")):
        students = Student.query.filter(Student.is_active == True).order_by(Student.name.asc()).limit(15).all()
        if not students:
            students = Student.query.order_by(Student.name.asc()).limit(15).all()

    return students


def generate_spline_path(points: List[tuple[float, float]]) -> str:
    """Генерация сглаженной кубической Безье-кривой SVG по точкам."""
    if not points:
        return "M 20 100 L 580 100"
    if len(points) == 1:
        return f"M 20 {points[0][1]:.1f} L 580 {points[0][1]:.1f}"

    path = f"M {points[0][0]:.1f} {points[0][1]:.1f}"
    for i in range(len(points) - 1):
        p0 = points[i - 1] if i > 0 else points[i]
        p1 = points[i]
        p2 = points[i + 1]
        p3 = points[i + 2] if i + 2 < len(points) else p2
        cp1x = p1[0] + (p2[0] - p0[0]) / 6.0
        cp1y = p1[1] + (p2[1] - p0[1]) / 6.0
        cp2x = p2[0] - (p3[0] - p1[0]) / 6.0
        cp2y = p2[1] - (p3[1] - p1[1]) / 6.0
        path += f" C {cp1x:.1f} {cp1y:.1f}, {cp2x:.1f} {cp2y:.1f}, {p2[0]:.1f} {p2[1]:.1f}"
    return path


def build_chart_dataset(data_points: List[Dict[str, Any]], width: float = 600.0, height: float = 160.0) -> Dict[str, Any]:
    """Строит данные SVG-кривой, заливки и тултипа по списку словарей {date, val}."""
    pad_x = 30.0
    pad_top = 25.0
    pad_bottom = 25.0
    usable_w = width - 2 * pad_x
    usable_h = height - pad_top - pad_bottom

    vals = [max(0, min(100, float(d.get("val", 0)))) for d in data_points]
    min_v = min(vals) if vals else 0
    max_v = max(vals) if vals else 100
    y_range = max_v - min_v if max_v != min_v else 50.0

    n = len(data_points)
    pts = []
    for i, d in enumerate(data_points):
        x = pad_x + (usable_w * (i / max(1, n - 1)))
        v = vals[i]
        y = pad_top + usable_h * (1.0 - ((v - min_v) / y_range))
        pts.append((x, y))

    spline_d = generate_spline_path(pts)
    first_x = pts[0][0] if pts else pad_x
    last_x = pts[-1][0] if pts else (width - pad_x)
    area_d = f"{spline_d} L {last_x:.1f} {height:.1f} L {first_x:.1f} {height:.1f} Z"

    peak_idx = 0
    if vals:
        peak_idx = vals.index(max(vals))
    peak_pt = pts[peak_idx] if pts else (width / 2, height / 2)
    peak_val = int(round(vals[peak_idx])) if vals else 0
    peak_label = data_points[peak_idx]["date"] if data_points else ""

    return {
        "points": data_points,
        "spline_d": spline_d,
        "area_d": area_d,
        "peak_x": peak_pt[0],
        "peak_y": peak_pt[1],
        "peak_val": peak_val,
        "peak_label": peak_label,
    }


def get_teacher_dashboard_data(teacher_user: User) -> Dict[str, Any]:
    now = to_naive(moscow_now())
    user_name = teacher_user.full_name or teacher_user.username or "Преподаватель"

    # 1. Greeting & Date
    hour = now.hour
    if 5 <= hour < 12:
        greeting_word = "Доброе утро"
    elif 12 <= hour < 18:
        greeting_word = "Добрый день"
    else:
        greeting_word = "Добрый вечер"

    weekday_str = RU_WEEKDAYS[now.weekday()]
    month_str = RU_MONTHS[now.month]
    date_formatted = f"{weekday_str}, {now.day} {month_str}"
    today_short = f"{now.day} {month_str}, {weekday_str.lower()}"

    # 2. Real Students
    students = get_teacher_students(teacher_user)
    student_ids = [s.student_id for s in students if s.student_id]
    active_students_count = len([s for s in students if getattr(s, "is_active", True)])

    # Delta students in last 30d vs 30-60d
    month_ago = now - timedelta(days=30)
    prev_month_start = now - timedelta(days=60)
    new_last_30 = sum(1 for s in students if getattr(s, "created_at", None) and to_naive(s.created_at) >= month_ago)
    new_prev_30 = sum(1 for s in students if getattr(s, "created_at", None) and prev_month_start <= to_naive(s.created_at) < month_ago)
    delta_st = new_last_30 - new_prev_30
    if delta_st > 0:
        students_delta = f"↑ +{delta_st} за месяц"
    elif delta_st < 0:
        students_delta = f"↓ {delta_st} за месяц"
    else:
        students_delta = "0 за месяц" if active_students_count > 0 else "нет учеников"

    # 3. Submissions & Reviews
    q_subs = Submission.query
    if not is_creator_or_admin(teacher_user):
        if student_ids:
            q_subs = q_subs.filter(Submission.student_id.in_(student_ids))
        else:
            q_subs = q_subs.filter(False)

    pending_submissions = (
        q_subs.filter(Submission.status.in_(["SUBMITTED", "NEEDS_MANUAL_REVIEW"]))
        .order_by(Submission.submitted_at.asc())
        .all()
    )
    pending_reviews = len(pending_submissions)
    overdue_count = 0
    for ps in pending_submissions:
        deadline_naive = to_naive(getattr(ps.assignment, "deadline", None))
        if deadline_naive and deadline_naive < now:
            overdue_count += 1
    if overdue_count > 0:
        overdue_reviews = f"↓ {overdue_count} просрочена" if overdue_count == 1 else f"↓ {overdue_count} просрочено"
    elif pending_reviews > 0:
        overdue_reviews = "все в рамках срока"
    else:
        overdue_reviews = "все проверены"

    # 4. Average Score & Weekly delta
    graded_subs = q_subs.filter(Submission.status == "GRADED", Submission.percentage.isnot(None)).all()
    if graded_subs:
        average_score = int(round(sum(float(s.percentage) for s in graded_subs) / len(graded_subs)))
    else:
        average_score = 0

    week_ago = now - timedelta(days=7)
    prev_week_start = now - timedelta(days=14)
    recent_graded = [s for s in graded_subs if s.graded_at and to_naive(s.graded_at) >= week_ago]
    prev_graded = [s for s in graded_subs if s.graded_at and prev_week_start <= to_naive(s.graded_at) < week_ago]
    if recent_graded and prev_graded:
        recent_avg = sum(float(s.percentage) for s in recent_graded) / len(recent_graded)
        prev_avg = sum(float(s.percentage) for s in prev_graded) / len(prev_graded)
        diff = int(round(recent_avg - prev_avg))
        score_delta = f"↑ +{diff}% к прошлой неделе" if diff >= 0 else f"↓ {diff}% к прошлой неделе"
    elif recent_graded:
        score_delta = f"↑ {len(recent_graded)} проверено за неделю"
    else:
        score_delta = "на этой неделе без оценок"

    # 5. Lessons & Lessons this week
    start_of_week = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())
    end_of_week = start_of_week + timedelta(days=7)

    q_lessons = Lesson.query
    if not is_creator_or_admin(teacher_user):
        if student_ids:
            q_lessons = q_lessons.filter(Lesson.student_id.in_(student_ids))
        else:
            q_lessons = q_lessons.filter(False)

    lessons_this_week_list = (
        q_lessons.filter(
            Lesson.lesson_date >= start_of_week,
            Lesson.lesson_date < end_of_week,
            Lesson.status.in_(["planned", "completed", "in_progress", "scheduled"]),
        )
        .order_by(Lesson.lesson_date.asc())
        .all()
    )
    lessons_this_week = len(lessons_this_week_list)

    next_lesson = (
        q_lessons.filter(
            Lesson.lesson_date >= now,
            Lesson.status.in_(["planned", "scheduled", "in_progress"]),
        )
        .order_by(Lesson.lesson_date.asc())
        .first()
    )
    if next_lesson and next_lesson.lesson_date:
        ld = next_lesson.lesson_date
        if ld.date() == now.date():
            next_lesson_subtext = f"следующий сегодня в {ld.strftime('%H:%M')}"
        elif ld.date() == (now + timedelta(days=1)).date():
            next_lesson_subtext = f"следующий завтра в {ld.strftime('%H:%M')}"
        else:
            next_lesson_subtext = f"следующий {ld.strftime('%d.%m в %H:%M')}"
    else:
        next_lesson_subtext = "нет запланированных уроков"

    # KPI dictionary
    kpi = {
        "active_students": active_students_count,
        "students_delta": students_delta,
        "pending_reviews": pending_reviews,
        "overdue_reviews": overdue_reviews,
        "average_score": average_score,
        "score_delta": score_delta,
        "lessons_this_week": lessons_this_week,
        "next_lesson_subtext": next_lesson_subtext,
    }

    # 6. Hero Card
    completed_works = q_subs.filter(
        Submission.status.in_(["GRADED", "SUBMITTED"]),
        Submission.submitted_at >= start_of_week,
    ).count()
    completed_works_prev = q_subs.filter(
        Submission.status.in_(["GRADED", "SUBMITTED"]),
        Submission.submitted_at >= (start_of_week - timedelta(days=7)),
        Submission.submitted_at < start_of_week,
    ).count()
    if completed_works_prev > 0:
        cw_pct = round(((completed_works - completed_works_prev) / completed_works_prev) * 100)
        completed_works_delta = f"+{cw_pct}%" if cw_pct >= 0 else f"{cw_pct}%"
    else:
        completed_works_delta = f"+{completed_works}" if completed_works > 0 else "0%"

    past_lessons = [l for l in lessons_this_week_list if l.lesson_date and to_naive(l.lesson_date) < now]
    attended = [l for l in past_lessons if l.status == "completed" or (l.status == "in_progress" and not getattr(l, "student_late", False))]
    attendance_pct = round((len(attended) / len(past_lessons)) * 100) if past_lessons else 100

    # Students with improved recent performance
    improved_count = 0
    for st in students:
        st_subs = [s for s in graded_subs if s.student_id == st.student_id]
        if len(st_subs) >= 2:
            st_subs.sort(key=lambda s: to_naive(s.graded_at or s.submitted_at or s.created_at) or datetime.min)
            if float(st_subs[-1].percentage or 0) > float(st_subs[-2].percentage or 0):
                improved_count += 1

    hero_card = {
        "badge": "Неделя идёт хорошо! ✨" if completed_works > 0 or lessons_this_week > 0 else "Продуктивной недели! 🚀",
        "completed_works": completed_works,
        "completed_works_delta": completed_works_delta,
        "attendance_pct": attendance_pct,
        "attendance_delta": "+100%" if past_lessons and attendance_pct == 100 else f"{attendance_pct}%",
        "improved_students": improved_count,
    }

    # 7. Focus on today (Фокус на сегодня — 4 items)
    focus_items = []

    # Focus 1: Check score decline
    decline_student = None
    decline_progression = []
    for st in students:
        st_subs = [s for s in graded_subs if s.student_id == st.student_id]
        if len(st_subs) >= 2:
            st_subs.sort(key=lambda s: to_naive(s.graded_at or s.submitted_at or s.created_at) or datetime.min)
            p_last = float(st_subs[-1].percentage or 0)
            p_prev = float(st_subs[-2].percentage or 0)
            if p_prev - p_last >= 10:
                decline_student = st
                decline_progression = [f"{int(round(float(s.percentage or 0)))}%" for s in st_subs[-3:]]
                break

    if decline_student:
        focus_items.append({
            "id": f"student_decline_{decline_student.student_id}",
            "type": "decline",
            "avatar": "/static/images/default-avatar.svg",
            "student_name": decline_student.name,
            "title": decline_student.name,
            "subtitle": "Заметное снижение балла по последним работам",
            "progression": decline_progression,
            "progression_colors": ["emerald", "amber", "rose"] if len(decline_progression) >= 3 else ["amber", "rose"],
            "action_text": "Посмотреть ученика →",
            "action_url": f"/student/{decline_student.student_id}/dashboard",
        })
    else:
        focus_items.append({
            "id": "status_ok",
            "type": "milestone",
            "icon": "ph-bold ph-trend-up",
            "title": "Успеваемость стабильна",
            "subtitle": "Резких падений среднего балла не зафиксировано",
            "action_text": "Все ученики →",
            "action_url": "/students",
        })

    # Focus 2: Pending reviews
    if pending_reviews > 0:
        oldest = pending_submissions[0]
        oldest_time = oldest.submitted_at.strftime('%d.%m в %H:%M') if oldest.submitted_at else 'недавно'
        st_name = oldest.student.name if oldest.student else 'ученика'
        focus_items.append({
            "id": "review_queue",
            "type": "review",
            "icon": "ph-bold ph-file-text",
            "title": f"{pending_reviews} работ ждут проверки",
            "subtitle": f"Самая ранняя от {st_name} ({oldest_time})",
            "action_text": "Перейти к проверке →",
            "action_url": "/assignments",
        })
    else:
        focus_items.append({
            "id": "review_clean",
            "type": "milestone",
            "icon": "ph-bold ph-check-circle",
            "title": "Все работы проверены ✨",
            "subtitle": "Очередь сданных заданий полностью разобрана",
            "action_text": "Создать работу →",
            "action_url": "/assignments/create",
        })

    # Focus 3: Today's lesson or schedule
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    lesson_today = (
        q_lessons.filter(
            Lesson.lesson_date >= now - timedelta(hours=1),
            Lesson.lesson_date < today_end,
            Lesson.status.in_(["planned", "scheduled", "in_progress"]),
        )
        .order_by(Lesson.lesson_date.asc())
        .first()
    )
    if lesson_today and lesson_today.lesson_date:
        st_name = lesson_today.student.name if lesson_today.student else "Ученик"
        time_str = lesson_today.lesson_date.strftime("%H:%M")
        topic_str = lesson_today.topic or "Занятие"
        focus_items.append({
            "id": f"upcoming_lesson_{lesson_today.lesson_id}",
            "type": "lesson",
            "avatar": "/static/images/default-avatar.svg",
            "student_name": st_name,
            "title": f"Урок с {st_name} сегодня в {time_str}",
            "subtitle": f"Тема: {topic_str} · {lesson_today.duration or 60} мин",
            "action_text": "Войти в урок →",
            "action_url": f"/lesson/{lesson_today.lesson_id}/room" if hasattr(lesson_today, "lesson_id") else "/schedule",
        })
    elif next_lesson and next_lesson.lesson_date:
        st_name = next_lesson.student.name if next_lesson.student else "Ученик"
        time_str = next_lesson.lesson_date.strftime("%d.%m в %H:%M")
        focus_items.append({
            "id": f"next_lesson_{next_lesson.lesson_id}",
            "type": "lesson",
            "avatar": "/static/images/default-avatar.svg",
            "student_name": st_name,
            "title": f"Ближайший урок: {st_name}",
            "subtitle": f"{time_str} · {next_lesson.topic or 'Занятие'}",
            "action_text": "Открыть расписание →",
            "action_url": "/schedule",
        })
    else:
        focus_items.append({
            "id": "add_lesson_prompt",
            "type": "lesson",
            "icon": "ph-bold ph-calendar-plus",
            "title": "Свободное расписание",
            "subtitle": "На сегодня уроков нет. Запланируйте занятие с учеником",
            "action_text": "+ Назначить урок",
            "action_url": "javascript:openAddLessonModal()",
        })

    # Focus 4: High score achievement
    top_sub = max(graded_subs, key=lambda s: float(s.percentage or 0), default=None)
    if top_sub and float(top_sub.percentage or 0) >= 80 and top_sub.student:
        focus_items.append({
            "id": f"milestone_top_{top_sub.submission_id}",
            "type": "milestone",
            "avatar": "/static/images/default-avatar.svg",
            "student_name": top_sub.student.name,
            "title": f"{top_sub.student.name} — отличный балл!",
            "subtitle": f"Сдал «{top_sub.assignment.title if top_sub.assignment else 'работу'}» на {int(round(float(top_sub.percentage)))}%",
            "action_text": "Посмотреть профиль →",
            "action_url": f"/student/{top_sub.student_id}/dashboard",
        })
    else:
        focus_items.append({
            "id": "bank_milestone",
            "type": "milestone",
            "icon": "ph-bold ph-sparkle",
            "title": "Банк задач BooStudy",
            "subtitle": "Свежие прототипы КЕГЭ и ОГЭ готовы к добавлению в работы",
            "action_text": "Открыть банк →",
            "action_url": "/tasks",
        })

    # 8. Today's Timeline
    today_lessons = (
        q_lessons.filter(
            Lesson.lesson_date >= today_start,
            Lesson.lesson_date < today_end,
            Lesson.status.in_(["planned", "scheduled", "in_progress", "completed"]),
        )
        .order_by(Lesson.lesson_date.asc())
        .all()
    )
    today_timeline = []
    for l in today_lessons:
        st_name = l.student.name if l.student else "Ученик"
        t_str = l.lesson_date.strftime("%H:%M") if l.lesson_date else "12:00"
        today_timeline.append({
            "id": l.lesson_id,
            "time": t_str,
            "is_lesson": True,
            "student_name": st_name,
            "topic": l.topic or "Занятие",
            "duration": f"{l.duration or 60} мин",
            "avatar": "/static/images/default-avatar.svg",
            "room_url": f"/lesson/{l.lesson_id}/room",
            "status": l.status,
        })

    # 9. Quick Actions
    quick_actions = [
        {
            "title": "Создать работу",
            "icon": "ph-bold ph-file-plus",
            "url": "/assignments/create",
            "color": "indigo",
            "bg": "bg-indigo-50",
            "text_color": "text-indigo-700",
            "border": "border-indigo-200",
        },
        {
            "title": "Назначить пробник",
            "icon": "ph-bold ph-target",
            "onclick": "openAssignMockModal()",
            "color": "sky",
            "bg": "bg-sky-50",
            "text_color": "text-sky-700",
            "border": "border-sky-200",
        },
        {
            "title": "Открыть банк задач",
            "icon": "ph-bold ph-book-open",
            "url": "/tasks",
            "color": "emerald",
            "bg": "bg-emerald-50",
            "text_color": "text-emerald-700",
            "border": "border-emerald-200",
        },
        {
            "title": "Добавить ученика",
            "icon": "ph-bold ph-user-plus",
            "onclick": "openAddStudentModal()",
            "color": "amber",
            "bg": "bg-amber-50",
            "text_color": "text-amber-700",
            "border": "border-amber-200",
        },
    ]

    # 10. ToDo Checklist
    todos = load_teacher_todos(teacher_user.id)

    # 11. Chart datasets (7d, 30d, all)
    days_7_points = []
    for offset in range(6, -1, -1):
        d_day = (now - timedelta(days=offset)).date()
        day_subs = [s for s in graded_subs if s.graded_at and to_naive(s.graded_at).date() == d_day]
        val = int(round(sum(float(s.percentage or 0) for s in day_subs) / len(day_subs))) if day_subs else (average_score if average_score > 0 else 75)
        days_7_points.append({"date": d_day.strftime("%d.%m"), "val": val})

    days_30_points = []
    for step in range(4, -1, -1):
        d_target = (now - timedelta(days=step * 7)).date()
        w_subs = [s for s in graded_subs if s.graded_at and abs((to_naive(s.graded_at).date() - d_target).days) <= 3]
        val = int(round(sum(float(s.percentage or 0) for s in w_subs) / len(w_subs))) if w_subs else (average_score if average_score > 0 else 72)
        days_30_points.append({"date": d_target.strftime("%d.%m"), "val": val})

    all_points = []
    for m_offset in range(3, -1, -1):
        m_date = (now - timedelta(days=m_offset * 30)).date()
        m_label = RU_MONTHS[m_date.month].capitalize() if RU_MONTHS[m_date.month] else "Месяц"
        m_subs = [s for s in graded_subs if s.graded_at and to_naive(s.graded_at).year == m_date.year and to_naive(s.graded_at).month == m_date.month]
        val = int(round(sum(float(s.percentage or 0) for s in m_subs) / len(m_subs))) if m_subs else (average_score if average_score > 0 else 70)
        all_points.append({"date": m_label, "val": val})

    chart_data_7d = build_chart_dataset(days_7_points)
    chart_data_30d = build_chart_dataset(days_30_points)
    chart_data_all = build_chart_dataset(all_points)

    # 12. Student Dynamics
    gaining_momentum = []
    needs_help = []
    for st in students:
        st_subs = [s for s in graded_subs if s.student_id == st.student_id]
        if len(st_subs) >= 2:
            st_subs.sort(key=lambda s: to_naive(s.graded_at or s.submitted_at or s.created_at) or datetime.min)
            diff = int(round(float(st_subs[-1].percentage or 0) - float(st_subs[-2].percentage or 0)))
            entry = {
                "name": st.name,
                "delta": f"+{diff}%" if diff >= 0 else f"{diff}%",
                "student_id": st.student_id,
                "avatar": "/static/images/default-avatar.svg",
                "positive": diff >= 0,
            }
            if diff >= 0:
                gaining_momentum.append(entry)
            else:
                needs_help.append(entry)
        elif st_subs:
            val = int(round(float(st_subs[-1].percentage or 0)))
            entry = {
                "name": st.name,
                "delta": f"{val}%",
                "student_id": st.student_id,
                "avatar": "/static/images/default-avatar.svg",
                "positive": val >= 65,
            }
            if val >= 65:
                gaining_momentum.append(entry)
            else:
                needs_help.append(entry)
        else:
            entry = {
                "name": st.name,
                "delta": f"Цель: {st.target_score or 80}",
                "student_id": st.student_id,
                "avatar": "/static/images/default-avatar.svg",
                "positive": True,
            }
            gaining_momentum.append(entry)

    gaining_momentum = gaining_momentum[:4]
    needs_help = needs_help[:4]

    # 13. Topic Mastery Map
    topics_map = []
    core_topics = [
        "Переменные и типы данных",
        "Условные конструкции",
        "Циклы for и while",
        "Строки и срезы",
    ]
    total_st_pool = max(1, active_students_count)
    for i, top_name in enumerate(core_topics):
        if graded_subs:
            m_cnt = sum(1 for st in students if any(float(s.percentage or 0) >= 75 for s in graded_subs if s.student_id == st.student_id))
            p_cnt = sum(1 for st in students if any(float(s.percentage or 0) < 50 for s in graded_subs if s.student_id == st.student_id))
            w_cnt = max(0, total_st_pool - m_cnt - p_cnt)
        else:
            m_cnt = int(round(total_st_pool * (0.6 - i * 0.05)))
            w_cnt = int(round(total_st_pool * 0.3))
            p_cnt = max(0, total_st_pool - m_cnt - w_cnt)

        pct_m = int(round((m_cnt / total_st_pool) * 100))
        pct_w = int(round((w_cnt / total_st_pool) * 100))
        pct_p = max(0, 100 - pct_m - pct_w)

        topics_map.append({
            "name": top_name,
            "mastered": m_cnt,
            "in_progress": w_cnt,
            "problem": p_cnt,
            "total": total_st_pool,
            "pct_mastered": pct_m,
            "pct_in_progress": pct_w,
            "pct_problem": pct_p,
        })

    # 14. Recent Live Activity
    recent_activity = []
    latest_subs = q_subs.order_by(Submission.updated_at.desc()).limit(8).all()
    for s in latest_subs:
        st_name = s.student.name if s.student else "Ученик"
        as_title = s.assignment.title if s.assignment else "Задание"
        t_act = to_naive(s.submitted_at or s.updated_at or s.created_at)
        if t_act:
            if t_act.date() == now.date():
                time_str = t_act.strftime("%H:%M")
            elif t_act.date() == (now - timedelta(days=1)).date():
                time_str = "Вчера"
            else:
                time_str = f"{t_act.day} {RU_MONTHS[t_act.month][:3]}"
        else:
            time_str = "Недавно"

        if s.status == "GRADED":
            action_desc = f"получил оценку за «{as_title}»"
            score_str = f"{int(round(float(s.percentage)))}%" if s.percentage is not None else (f"{s.total_score}/{s.max_score}" if s.max_score else "Сдано")
            color = "emerald" if (s.percentage or 0) >= 70 else ("amber" if (s.percentage or 0) >= 50 else "rose")
            icon = "ph-bold ph-check"
        elif s.status in ["SUBMITTED", "NEEDS_MANUAL_REVIEW"]:
            action_desc = f"сдал работу «{as_title}»"
            score_str = f"{s.total_score}/{s.max_score}" if s.max_score else "Ждёт проверки"
            color = "sky"
            icon = "ph-bold ph-paper-plane-tilt"
        else:
            action_desc = f"начал выполнение «{as_title}»"
            score_str = None
            color = "amber"
            icon = "ph-bold ph-clock"

        recent_activity.append({
            "time": time_str,
            "user": st_name,
            "action": action_desc,
            "score": score_str,
            "color": color,
            "icon": icon,
            "url": f"/student/{s.student_id}/dashboard" if s.student_id else "/assignments",
        })

    latest_lessons = q_lessons.filter(Lesson.status == "completed").order_by(Lesson.lesson_date.desc()).limit(3).all()
    for l in latest_lessons:
        st_name = l.student.name if l.student else "Ученик"
        ld = to_naive(l.lesson_date)
        if ld:
            if ld.date() == now.date():
                time_str = ld.strftime("%H:%M")
            elif ld.date() == (now - timedelta(days=1)).date():
                time_str = "Вчера"
            else:
                time_str = f"{ld.day} {RU_MONTHS[ld.month][:3]}"
        else:
            time_str = "Недавно"

        recent_activity.append({
            "time": time_str,
            "user": st_name,
            "action": f"завершил урок «{l.topic or 'Занятие'}»",
            "score": None,
            "color": "emerald",
            "icon": "ph-bold ph-graduation-cap",
            "url": f"/lesson/{l.lesson_id}/room" if hasattr(l, "lesson_id") else "/schedule",
        })

    recent_activity = recent_activity[:6]

    return {
        "teacher_name": user_name,
        "greeting_word": greeting_word,
        "date_formatted": date_formatted,
        "today_short": today_short,
        "students": students,
        "hero_card": hero_card,
        "kpi": kpi,
        "focus_items": focus_items,
        "today_timeline": today_timeline,
        "quick_actions": quick_actions,
        "todos": todos,
        "chart_data_7d": chart_data_7d,
        "chart_data_30d": chart_data_30d,
        "chart_data_all": chart_data_all,
        "chart_days_7": days_7_points,
        "chart_days_30": days_30_points,
        "chart_all": all_points,
        "gaining_momentum": gaining_momentum,
        "needs_help": needs_help,
        "topics_map": topics_map,
        "recent_activity": recent_activity,
    }
