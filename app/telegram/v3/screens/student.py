"""Student cabinet screens for BooStudy Bot V3."""
from __future__ import annotations

import math
from typing import Any
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

from app.models import User, Assignment, Submission, db
from app.telegram.application import (
    build_today_view,
    build_student_schedule,
    build_student_assignments,
    build_student_progress,
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

    text = f"{card_header(f'🎓 Личный кабинет · {name}', 'Ученик BooStudy')}\n"

    # Next lesson block
    if today.lessons:
        next_lesson = today.lessons[0]
        topic = escape(next_lesson.get("topic") or "Занятие")
        starts_at = format_dt(next_lesson.get("starts_at"), tz_name)
        text += (
            f"📅 <b>Ближайший урок:</b>\n"
            f"• <b>{topic}</b>\n"
            f"  {starts_at}\n\n"
        )
    else:
        text += (
            "📅 <b>Уроки на сегодня:</b>\n"
            "• <i>Запланированных уроков нет</i> 🎉\n\n"
        )

    # Assignments summary
    active_hw = [a for a in today.assignments if a.get("status") in {"ASSIGNED", "IN_PROGRESS", "RETURNED"}]
    review_hw = [a for a in today.assignments if a.get("status") in {"SUBMITTED", "IN_REVIEW"}]

    text += (
        f"📝 <b>Домашние задания:</b>\n"
        f"• Активных к сдаче: <b>{len(active_hw)}</b>\n"
        f"• На проверке у учителя: <b>{len(review_hw)}</b>\n"
    )

    if today.overdue_count:
        text += f"• ⚠️ Требуют внимания (дедлайн): <b>{today.overdue_count}</b>\n"

    # Keyboard
    keyboard: list[list[InlineKeyboardButton]] = []
    mini_app_btn = build_mini_app_button("📱 Открыть Mini App")
    if mini_app_btn:
        keyboard.append([mini_app_btn])

    keyboard.extend([
        [InlineKeyboardButton("📅 Расписание занятий", callback_data=f"{CB_PREFIX}:{DOMAIN_STUDENT}:sch")],
        [InlineKeyboardButton("📝 Домашние задания", callback_data=f"{CB_PREFIX}:{DOMAIN_STUDENT}:hw:1")],
        [InlineKeyboardButton("🏆 Мой прогресс и оценки", callback_data=f"{CB_PREFIX}:{DOMAIN_STUDENT}:prog")],
        [
            InlineKeyboardButton("⚙️ Настройки", callback_data=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:home"),
            InlineKeyboardButton("🔄 Обновить", callback_data=f"{CB_PREFIX}:{DOMAIN_NAV}:home"),
        ],
    ])

    # If first lesson has a room link, provide direct join button
    if today.lessons and today.lessons[0].get("lesson_url"):
        url = today.lessons[0].get("lesson_url")
        keyboard.insert(0, [InlineKeyboardButton("🎥 Войти в комнату урока", url=url)])

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_student_schedule(update: Update, user: User) -> None:
    """Render student's upcoming schedule."""
    schedule = build_student_schedule(user, limit=10)
    tz_name = getattr(user.profile, "timezone", "Europe/Moscow")

    text = f"{card_header('📅 Расписание занятий', 'Ближайшие уроки')}\n"

    keyboard: list[list[InlineKeyboardButton]] = []

    if not schedule:
        text += empty_state("🎉", "Нет запланированных занятий", "Все ближайшие уроки завершены или ещё не добавлены в расписание.")
    else:
        text += "Список ближайших уроков:\n\n"
        for idx, item in enumerate(schedule, 1):
            topic = escape(item.get("topic") or "Урок")
            when = format_dt(item.get("starts_at"), tz_name)
            duration = item.get("duration", 60)
            text += f"<b>{idx}. {topic}</b>\n   🕒 {when} ({duration} мин)\n\n"

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
        text += empty_state("✨", "Нет активных заданий", "Все домашние задания выполнены или ещё не назначены преподавателем.")
    else:
        for item in page_items:
            title = escape(item.get("title") or "Задание")
            badge = _status_badge(item.get("status"))
            deadline_str = format_dt(item.get("deadline"), tz_name, relative=False)
            assignment_id = item.get("assignment_id")

            text += (
                f"• <b>{title}</b>\n"
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
    student_obj = user.student_profile
    submission = None
    if student_obj:
        submission = Submission.query.filter_by(
            assignment_id=assignment.assignment_id, student_id=student_obj.student_id
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

    text = (
        f"{card_header('📝 Карточка задания', title)}\n"
        f"<b>Статус:</b> {status}\n"
        f"<b>Срок сдачи:</b> {deadline}\n\n"
        f"<b>Описание:</b>\n{desc}\n\n"
    )

    if submission and submission.percentage is not None:
        text += f"📊 <b>Результат проверки:</b> {submission.percentage}%\n"
    if submission and submission.teacher_comment:
        text += f"💬 <b>Комментарий учителя:</b>\n<i>{escape(submission.teacher_comment)}</i>\n\n"

    from app.telegram import deep_links
    web_url = deep_links.assignment(assignment.assignment_id)

    if web_url and is_localhost_url(web_url):
        text += f"{localhost_hint()}"

    keyboard: list[list[InlineKeyboardButton]] = []
    if web_url:
        keyboard.append([InlineKeyboardButton("💻 Открыть на платформе BooStudy", url=web_url)])
    keyboard.append(build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_STUDENT}:hw:{return_page}"))

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_student_progress(update: Update, user: User) -> None:
    """Render student's learning progress and achievements."""
    progress = build_student_progress(user)
    name = escape(get_display_name(user))

    text = f"{card_header(f'🏆 Прогресс обучения · {name}', 'Успеваемость и результаты')}\n"

    if not progress:
        text += empty_state("📊", "Нет данных успеваемости", "Результаты проверок и оценки появятся после сдачи первых заданий.")
    else:
        pending = progress.get("pending_homework", 0)
        submissions = progress.get("submissions", [])
        graded = [s for s in submissions if s.get("percentage") is not None]

        avg_score = (sum(s["percentage"] for s in graded) / len(graded)) if graded else 0

        text += (
            f"📈 <b>Общие показатели:</b>\n"
            f"• Проверено работ: <b>{len(graded)}</b>\n"
            f"• Средний балл: <b>{avg_score:.1f}%</b>\n"
            f"• Заданий в работе: <b>{pending}</b>\n\n"
        )

        if graded:
            text += "<b>Недавние оценки:</b>\n"
            for item in graded[:4]:
                title = escape(item.get("title") or "Работа")
                score = item.get("percentage")
                text += f"• {title}: <b>{score}%</b>\n"
            text += "\n"

    keyboard = [
        [InlineKeyboardButton("📝 К моим заданиям", callback_data=f"{CB_PREFIX}:{DOMAIN_STUDENT}:hw:1")],
        build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_NAV}:home"),
    ]

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))
