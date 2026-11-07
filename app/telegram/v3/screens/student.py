"""Student cabinet screens for BooStudy Bot V3."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

from app.models import User, Assignment, Submission, db, Lesson
from app.telegram.application import (
    build_today_view,
    build_student_schedule,
    build_student_assignments,
    build_student_progress,
    _student_ids_for_context,
)

from app.telegram.v3.constants import (
    CB_PREFIX,
    DOMAIN_NAV,
    DOMAIN_SETTINGS,
    DOMAIN_STUDENT,
    PAGE_SIZE_HW,
)
from app.telegram.v3.identity import get_display_name
from app.telegram.v3.ui import (
    card_header,
    empty_state,
    escape,
    format_dt,
    is_localhost_url,
    localhost_hint,
    build_mini_app_button,
    build_nav_row,
    build_pagination_row,
    render_screen,
)


def _status_badge(status: str) -> str:
    s = (status or "").upper()
    if s in {"CHECKED", "GRADED", "COMPLETED"}:
        return "🟢 Сдано"
    if s in {"SUBMITTED", "IN_REVIEW"}:
        return "🟡 На проверке"
    if s == "RETURNED":
        return "🟠 На доработке"
    return "⚪ Назначено"


async def show_student_home(update: Update, user: User) -> None:
    """Render the Student Home dashboard."""
    today = build_today_view(user, "student")
    name = escape(get_display_name(user))
    tz_name = today.timezone
    now = datetime.now(timezone.utc)

    text = f"{card_header(f'🎓 Личный кабинет · {name}', 'Ученик BooStudy')}\n"

    # 1. Next lesson block
    lesson_to_join = None
    if today.lessons:
        next_lesson = today.lessons[0]
        topic = escape(next_lesson.get("topic") or "Занятие")
        subject = escape(next_lesson.get("subject") or "Информатика")
        starts_at = format_dt(next_lesson.get("starts_at"), tz_name)
        teacher_name = escape(next_lesson.get("teacher_name") or "")
        duration = next_lesson.get("duration", 60)
        lesson_to_join = next_lesson.get("lesson_url")

        text += (
            f"📅 <b>Ближайший урок:</b>\n"
            f"• <b>{topic}</b> ({subject})\n"
            f"  🕒 {starts_at} · {duration} мин\n"
        )
        if teacher_name:
            text += f"  👨‍🏫 Преподаватель: {teacher_name}\n"
        text += "\n"
    else:
        future_lessons = build_student_schedule(user, limit=1)
        if future_lessons:
            fl = future_lessons[0]
            topic = escape(fl.get("topic") or "Занятие")
            subject = escape(fl.get("subject") or "Информатика")
            starts_at = format_dt(fl.get("starts_at"), tz_name)
            teacher_name = escape(fl.get("teacher_name") or "")
            duration = fl.get("duration", 60)
            lesson_to_join = fl.get("lesson_url")

            text += (
                f"📅 <b>Ближайший урок (в расписании):</b>\n"
                f"• <b>{topic}</b> ({subject})\n"
                f"  🕒 {starts_at} · {duration} мин\n"
            )
            if teacher_name:
                text += f"  👨‍🏫 Преподаватель: {teacher_name}\n"
            text += "\n"
        else:
            text += (
                "📅 <b>Расписание уроков:</b>\n"
                "• <i>В ближайшие дни занятий не запланировано. Расписание обновляется преподавателем.</i>\n\n"
            )

    # 2. Urgent homework block (if any overdue or due soon)
    urgent_btn_target = None
    if today.urgent_assignments:
        text += "⚠️ <b>Срочные задания:</b>\n"
        for idx, u_hw in enumerate(today.urgent_assignments[:2]):
            u_title = escape(u_hw.get("title") or "Задание")
            u_dl = format_dt(u_hw.get("deadline"), tz_name)
            is_over = u_hw.get("is_overdue", False)
            badge = "🚨 Просрочено" if is_over else "⏳ Срок подходит"
            t_name = escape(u_hw.get("teacher_name") or "")
            t_info = f" · {t_name}" if t_name else ""
            text += f"• {badge}: <b>{u_title}</b>{t_info}\n  Сдать до: {u_dl}\n"
            if idx == 0 and u_hw.get("id"):
                urgent_btn_target = (u_hw["id"], u_title)
        text += "\n"

    # 3. Recently graded homework
    graded_btn_target = None
    if today.recently_graded:
        rg = today.recently_graded
        rg_title = escape(rg.get("title") or "Задание")
        rg_score = rg.get("total_score")
        rg_max = rg.get("max_score")
        rg_pct = rg.get("percentage")
        score_str = f"{rg_score}/{rg_max} ({rg_pct:.0f}%)" if rg_score is not None and rg_max else (f"{rg_pct:.0f}%" if rg_pct is not None else "Проверено")
        text += (
            f"🎉 <b>Недавно проверено:</b>\n"
            f"• <b>{rg_title}</b> — оценка: <b>{score_str}</b>\n"
        )
        fb = rg.get("teacher_feedback")
        if fb:
            fb_preview = escape(fb[:70] + "..." if len(fb) > 70 else fb)
            text += f"  💬 <i>«{fb_preview}»</i>\n"
        text += "\n"
        if rg.get("id"):
            graded_btn_target = (rg["id"], rg_title)

    # 4. Multi-teacher block (if student has multiple teachers)
    if len(today.teachers) > 1:
        text += "👨‍🏫 <b>Ваши преподаватели:</b>\n"
        for tch in today.teachers:
            t_n = escape(tch.get("name") or "Преподаватель")
            t_s = escape(tch.get("subject") or "Предмет")
            text += f"• {t_n} ({t_s})\n"
        text += "\n"

    # 5. Assignment metrics
    all_asg = today.assignments or ()
    active_in_progress = []
    overdue_hw = []
    review_hw = []

    for a in all_asg:
        st = str(a.get("status") or "").upper()
        dl = a.get("deadline")
        if st in {"CHECKED", "GRADED", "COMPLETED"}:
            continue
        elif st in {"SUBMITTED", "IN_REVIEW"}:
            review_hw.append(a)
        else:
            if dl and dl < now:
                overdue_hw.append(a)
            else:
                active_in_progress.append(a)

    text += (
        f"📝 <b>Домашние задания:</b>\n"
        f"• В работе (активные): <b>{len(active_in_progress)}</b>\n"
    )
    if overdue_hw:
        text += f"• ⚠️ <b>Просроченные (требуют сдачи):</b> <b>{len(overdue_hw)}</b>\n"
    else:
        text += "• Просроченных заданий: <b>0</b> ✅\n"

    if review_hw:
        text += f"• На проверке у учителя: <b>{len(review_hw)}</b>\n"

    # 6. Actionable Keyboard
    keyboard: list[list[InlineKeyboardButton]] = []
    if lesson_to_join:
        keyboard.append([InlineKeyboardButton("🎥 Войти в комнату урока", url=lesson_to_join)])
    if urgent_btn_target:
        u_id, u_t = urgent_btn_target
        keyboard.append([InlineKeyboardButton(f"📝 Открыть задание: {u_t[:20]}", callback_data=f"{CB_PREFIX}:{DOMAIN_STUDENT}:hw_item:{u_id}:1")])
    elif graded_btn_target:
        g_id, g_t = graded_btn_target
        keyboard.append([InlineKeyboardButton(f"📊 Отзыв: {g_t[:20]}", callback_data=f"{CB_PREFIX}:{DOMAIN_STUDENT}:hw_item:{g_id}:1")])

    mini_app_btn = build_mini_app_button("📱 Открыть Mini App")
    if mini_app_btn:
        keyboard.append([mini_app_btn])

    keyboard.extend([
        [InlineKeyboardButton("📅 Расписание занятий", callback_data=f"{CB_PREFIX}:{DOMAIN_STUDENT}:sch")],
        [InlineKeyboardButton(f"📝 Домашние задания ({len(active_in_progress) + len(overdue_hw)})", callback_data=f"{CB_PREFIX}:{DOMAIN_STUDENT}:hw:1")],
        [InlineKeyboardButton("🏆 Мой прогресс и оценки", callback_data=f"{CB_PREFIX}:{DOMAIN_STUDENT}:prog")],
        [
            InlineKeyboardButton("⚙️ Настройки", callback_data=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:home"),
            InlineKeyboardButton("🔄 Обновить", callback_data=f"{CB_PREFIX}:{DOMAIN_NAV}:home"),
        ],
    ])

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_student_schedule(update: Update, user: User) -> None:
    """Render student's upcoming schedule."""
    schedule = build_student_schedule(user, limit=10)
    tz_name = getattr(user.profile, "timezone", "Europe/Moscow")

    text = f"{card_header('📅 Расписание занятий', 'Ближайшие уроки')}\n"

    keyboard: list[list[InlineKeyboardButton]] = []

    if not schedule:
        text += empty_state("📅", "Нет запланированных занятий", "В ближайшие дни уроков не запланировано. Расписание обновляется преподавателем.")
    else:
        text += "Список ближайших уроков:\n\n"
        for idx, item in enumerate(schedule, 1):
            topic = escape(item.get("topic") or "Урок")
            subject = escape(item.get("subject") or "Информатика")
            teacher_name = escape(item.get("teacher_name") or "")
            when = format_dt(item.get("starts_at"), tz_name)
            duration = item.get("duration", 60)
            teacher_str = f" · Преподаватель: {teacher_name}" if teacher_name else ""
            text += f"<b>{idx}. {topic}</b> ({subject})\n   🕒 {when} ({duration} мин){teacher_str}\n\n"

            if item.get("lesson_url") and idx <= 2:
                keyboard.append([InlineKeyboardButton(f"🎥 Войти: {topic[:25]}", url=item["lesson_url"])])

    keyboard.append(build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_NAV}:home"))
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_student_hw_list(update: Update, user: User, page: int = 1) -> None:
    """Render paginated student assignments list."""
    all_hw = build_student_assignments(user, limit=50)
    tz_name = getattr(user.profile, "timezone", "Europe/Moscow")

    total_count = len(all_hw)
    total_pages = max(1, math.ceil(total_count / PAGE_SIZE_HW))
    page = max(1, min(page, total_pages))

    start = (page - 1) * PAGE_SIZE_HW
    page_items = all_hw[start : start + PAGE_SIZE_HW]

    text = f"{card_header('📝 Домашние задания', f'Всего заданий: {total_count}')}\n"

    keyboard: list[list[InlineKeyboardButton]] = []

    if not page_items:
        text += empty_state("📝", "Нет назначенных заданий", "Все домашние задания выполнены или ещё не назначены преподавателем.")
    else:
        now = datetime.now(timezone.utc)
        for item in page_items:
            title = escape(item.get("title") or "Задание")
            badge = _status_badge(item.get("status"))
            deadline_dt = item.get("deadline")
            deadline_str = format_dt(deadline_dt, tz_name, relative=False)
            assignment_id = item.get("assignment_id")

            # Urgency indicator
            st = str(item.get("status") or "").upper()
            urgency = ""
            if st not in {"CHECKED", "GRADED", "COMPLETED", "SUBMITTED", "IN_REVIEW"}:
                if deadline_dt and deadline_dt < now:
                    urgency = " ⚠️ [Просрочено]"
                elif deadline_dt and (deadline_dt - now).total_seconds() <= 86400:
                    urgency = " ⏳ [Срок сегодня/завтра]"

            text += (
                f"• <b>{title}</b>{urgency}\n"
                f"  Статус: {badge} | До: {deadline_str}\n\n"
            )

            btn_title = f"📄 {title[:28]}" if len(title) > 28 else f"📄 {title}"
            keyboard.append([InlineKeyboardButton(btn_title, callback_data=f"{CB_PREFIX}:{DOMAIN_STUDENT}:hw_item:{assignment_id}:{page}")])

    # Pagination row
    pag_row = build_pagination_row(DOMAIN_STUDENT, "hw", page, total_pages)
    if pag_row:
        keyboard.append(pag_row)

    keyboard.append(build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_NAV}:home"))
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_student_hw_item(update: Update, user: User, assignment_id: int, return_page: int = 1) -> None:
    """Render detailed view of a single assignment."""
    assignment = db.session.get(Assignment, assignment_id)
    if not assignment or not assignment.is_active:
        text = f"{card_header('Задание не найдено')}\n<i>Запрошенное задание недоступно или удалено.</i>"
        keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_STUDENT}:hw:{return_page}")]
        await render_screen(update, text, InlineKeyboardMarkup(keyboard))
        return

    # Check student has submission or access (prevent IDOR)
    student_ids = _student_ids_for_context(user, "student")
    submission = None
    if student_ids:
        submission = Submission.query.filter(
            Submission.assignment_id == assignment.assignment_id,
            Submission.student_id.in_(student_ids),
        ).first()

    if not submission and not (user.is_creator() or user.is_admin()):
        text = f"{card_header('Доступ ограничен')}\n<i>У вас нет доступа к материалам этого домашнего задания.</i>"
        keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_STUDENT}:hw:{return_page}")]
        await render_screen(update, text, InlineKeyboardMarkup(keyboard))
        return

    tz_name = getattr(user.profile, "timezone", "Europe/Moscow")
    title = escape(assignment.title)
    desc = escape(assignment.description or "Без дополнительного описания.")
    deadline = format_dt(assignment.deadline, tz_name) if assignment.deadline else "Бессрочно"
    status = _status_badge(submission.status if submission else "ASSIGNED")

    teacher_name = None
    if assignment.created_by_id:
        tch = db.session.get(User, assignment.created_by_id)
        if tch:
            teacher_name = tch.full_name or tch.username

    text = (
        f"{card_header('📝 Карточка задания', title)}\n"
        f"<b>Статус:</b> {status}\n"
        f"<b>Срок сдачи:</b> {deadline}\n"
    )
    if teacher_name:
        text += f"<b>Преподаватель:</b> {escape(teacher_name)}\n"
    if assignment.assignment_type:
        text += f"<b>Тип задания:</b> {escape(assignment.assignment_type)}\n"

    text += f"\n<b>Описание:</b>\n{desc}\n\n"

    if submission and submission.submitted_at:
        text += f"📤 <b>Сдано на проверку:</b> {format_dt(submission.submitted_at, tz_name)}\n"

    if submission and submission.percentage is not None:
        score_val = f"{submission.percentage:.0f}%"
        if getattr(submission, "total_score", None) is not None and getattr(submission, "max_score", None):
            score_val = f"{submission.total_score} из {submission.max_score} ({score_val})"
        text += f"📊 <b>Результат проверки:</b> <b>{score_val}</b>\n"

    if submission and submission.graded_at:
        text += f"🕒 <b>Дата оценки:</b> {format_dt(submission.graded_at, tz_name)}\n"

    t_comment = getattr(submission, "teacher_feedback", None) or getattr(submission, "teacher_comment", None)
    if t_comment:
        text += f"\n💬 <b>Комментарий учителя:</b>\n<i>«{escape(t_comment)}»</i>\n"

    from app.telegram import deep_links
    web_url = deep_links.assignment(assignment.assignment_id)

    if web_url and is_localhost_url(web_url):
        text += f"\n{localhost_hint()}"

    keyboard: list[list[InlineKeyboardButton]] = []
    if web_url:
        keyboard.append([InlineKeyboardButton("💻 Открыть на платформе BooStudy", url=web_url)])
    keyboard.append(build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_STUDENT}:hw:{return_page}"))

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_student_progress(update: Update, user: User) -> None:
    """Render student's learning progress and achievements."""
    progress = build_student_progress(user)
    name = escape(get_display_name(user))
    tz_name = getattr(user.profile, "timezone", "Europe/Moscow")

    text = f"{card_header(f'🏆 Прогресс обучения · {name}', 'Успеваемость и результаты')}\n"

    submissions = progress.get("submissions", []) if progress else []
    graded = [s for s in submissions if s.get("percentage") is not None]

    if not graded:
        text += empty_state(
            "📊",
            "Оценок пока нет",
            "Вы ещё не сдавали работы на проверку или они ожидают оценки преподавателя.\n"
            "После проверки первого домашнего задания здесь появятся ваш средний балл и динамика успеваемости."
        )
    else:
        pending = progress.get("pending_homework", 0) if progress else 0
        percentages = [float(s["percentage"]) for s in graded]
        avg_score = sum(percentages) / len(percentages)
        latest_score = percentages[0]
        best_score = max(percentages)
        lowest_score = min(percentages)

        # Dynamic trend
        if len(percentages) >= 2:
            trend = "📈 Положительная динамика" if percentages[0] >= percentages[1] else "📉 Результат ниже предыдущего"
        else:
            trend = "🎯 Первые результаты"

        text += (
            f"📈 <b>Сводка успеваемости:</b>\n"
            f"• Проверено работ: <b>{len(graded)}</b>\n"
            f"• Средний балл: <b>{avg_score:.1f}%</b>\n"
            f"• Последняя оценка: <b>{latest_score:.0f}%</b> ({trend})\n"
            f"• Лучший результат: <b>{best_score:.0f}%</b> | Нижний: <b>{lowest_score:.0f}%</b>\n"
            f"• Заданий в работе: <b>{pending}</b>\n\n"
        )

        text += "<b>Проверенные работы:</b>\n"
        for item in graded[:5]:
            title = escape(item.get("title") or "Работа")
            score = item.get("percentage")
            graded_at = item.get("graded_at")
            date_str = f" · {format_dt(graded_at, tz_name, relative=False)}" if graded_at else ""
            text += f"• {title}: <b>{score:.0f}%</b>{date_str}\n"
        text += "\n"

    keyboard = [
        [InlineKeyboardButton("📝 К моим заданиям", callback_data=f"{CB_PREFIX}:{DOMAIN_STUDENT}:hw:1")],
        build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_NAV}:home"),
    ]

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))
