"""Teacher and tutor screens for BooStudy Bot V3."""
from __future__ import annotations

import math
from typing import Any
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

from app.models import db, User, Student, Submission
from app.telegram.application import (
    build_today_view,
    build_teacher_review_queue,
    build_teacher_students,
)
from app.telegram.v3.constants import (
    CB_PREFIX,
    DOMAIN_NAV,
    DOMAIN_SETTINGS,
    DOMAIN_TEACHER,
    PAGE_SIZE_QUEUE,
    PAGE_SIZE_STUDENTS,
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


async def show_teacher_home(update: Update, user: User) -> None:
    """Render the Teacher Home dashboard."""
    today = build_today_view(user, "teacher")
    name = escape(get_display_name(user))
    tz_name = today.timezone

    text = f"{card_header(f'👨‍🏫 Преподавательская · {name}', 'Учебный процесс')}\n"

    # Lessons today block
    lessons_today = today.lessons
    if lessons_today:
        next_lesson = lessons_today[0]
        topic = escape(next_lesson.get("topic") or "Занятие")
        starts_at = format_dt(next_lesson.get("starts_at"), tz_name)
        text += (
            f"📅 <b>Ближайший урок:</b>\n"
            f"• <b>{topic}</b>\n"
            f"  {starts_at}\n"
            f"• Всего уроков сегодня: <b>{len(lessons_today)}</b>\n\n"
        )
    else:
        text += (
            "📅 <b>Занятия на сегодня:</b>\n"
            "• <i>Уроков на сегодня не запланировано</i> 🎉\n\n"
        )

    # Review queue indicator
    text += (
        f"📥 <b>Очередь проверки:</b>\n"
        f"• Работ ожидают проверки: <b>{today.pending_review_count}</b>\n"
    )
    if today.overdue_count:
        text += f"• ⚠️ Заданий учеников с истёкшим дедлайном: <b>{today.overdue_count}</b>\n"

    # Keyboard
    keyboard: list[list[InlineKeyboardButton]] = []
    mini_app_btn = build_mini_app_button("📱 Открыть Mini App")
    if mini_app_btn:
        keyboard.append([mini_app_btn])

    keyboard.extend([
        [InlineKeyboardButton(f"📥 Очередь проверки ({today.pending_review_count})", callback_data=f"{CB_PREFIX}:{DOMAIN_TEACHER}:queue:1")],
        [InlineKeyboardButton("📅 Моё расписание на сегодня", callback_data=f"{CB_PREFIX}:{DOMAIN_TEACHER}:sch")],
        [InlineKeyboardButton("👥 Мои ученики", callback_data=f"{CB_PREFIX}:{DOMAIN_TEACHER}:st:1")],
        [
            InlineKeyboardButton("⚙️ Настройки", callback_data=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:home"),
            InlineKeyboardButton("🔄 Обновить", callback_data=f"{CB_PREFIX}:{DOMAIN_NAV}:home"),
        ],
    ])

    # Join room button if next lesson has call link
    if lessons_today and lessons_today[0].get("lesson_url"):
        url = lessons_today[0].get("lesson_url")
        keyboard.insert(0, [InlineKeyboardButton("🎥 Войти в комнату ближайшего урока", url=url)])

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_teacher_schedule(update: Update, user: User) -> None:
    """Render teacher's lessons today and upcoming."""
    today = build_today_view(user, "teacher")
    lessons = today.lessons
    tz_name = today.timezone

    text = f"{card_header('📅 Расписание уроков', 'Преподавательское расписание')}\n"
    keyboard: list[list[InlineKeyboardButton]] = []

    if not lessons:
        text += empty_state("🎉", "Нет занятий на сегодня", "На сегодня уроков нет. Можно проверить сданные домашние работы учеников.")
    else:
        text += "Занятия на сегодня:\n\n"
        for idx, item in enumerate(lessons, 1):
            topic = escape(item.get("topic") or "Урок")
            when = format_dt(item.get("starts_at"), tz_name)
            duration = item.get("duration", 60)
            text += f"<b>{idx}. {topic}</b>\n   🕒 {when} ({duration} мин)\n\n"

            if item.get("lesson_url") and idx <= 2:
                keyboard.append([InlineKeyboardButton(f"🎥 Войти: {topic[:28]}", url=item["lesson_url"])])

    keyboard.append(build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_NAV}:home"))
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_teacher_review_queue(update: Update, user: User, page: int = 1) -> None:
    """Render paginated review queue of homework submissions."""
    queue = build_teacher_review_queue(user, limit=50)
    tz_name = getattr(user.profile, "timezone", "Europe/Moscow")

    total_count = len(queue)
    total_pages = max(1, math.ceil(total_count / PAGE_SIZE_QUEUE))
    page = max(1, min(page, total_pages))

    start = (page - 1) * PAGE_SIZE_QUEUE
    page_items = queue[start : start + PAGE_SIZE_QUEUE]

    text = f"{card_header('📥 Очередь проверки ДЗ', f'Работ на проверке: {total_count}')}\n"
    keyboard: list[list[InlineKeyboardButton]] = []

    if not page_items:
        text += empty_state("✨", "Очередь проверки пуста", "Все сданные работы проверены. Отличная работа!")
    else:
        for item in page_items:
            student_name = escape(item.student_name)
            title = escape(item.assignment_title)
            submitted_str = format_dt(item.submitted_at, tz_name)

            text += (
                f"• <b>{student_name}</b> — {title}\n"
                f"  Сдано: {submitted_str}\n\n"
            )

            btn_label = f"🔍 {student_name[:15]}: {title[:18]}"
            keyboard.append([InlineKeyboardButton(btn_label, callback_data=f"{CB_PREFIX}:{DOMAIN_TEACHER}:q_item:{item.submission_id}:{page}")])

    # Pagination row
    pag_row = build_pagination_row(DOMAIN_TEACHER, "queue", page, total_pages)
    if pag_row:
        keyboard.append(pag_row)

    keyboard.append(build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_NAV}:home"))
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_teacher_submission_item(update: Update, user: User, submission_id: int, return_page: int = 1) -> None:
    """Render detailed view of a submission awaiting review."""
    submission = db.session.get(Submission, submission_id)
    if not submission:
        text = f"{card_header('Работа не найдена')}\n<i>Запрошенная сдача не найдена или уже удалена.</i>"
        keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_TEACHER}:queue:{return_page}")]
        await render_screen(update, text, InlineKeyboardMarkup(keyboard))
        return

    student = submission.student
    if not (user.is_creator() or user.is_admin()):
        if not student or student.mentor_id != user.id:
            text = f"{card_header('Доступ ограничен')}\n<i>У вас нет прав на просмотр этой сдачи.</i>"
            keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_TEACHER}:queue:{return_page}")]
            await render_screen(update, text, InlineKeyboardMarkup(keyboard))
            return

    assignment = submission.assignment
    tz_name = getattr(user.profile, "timezone", "Europe/Moscow")

    student_name = escape(student.name if student else "Ученик")
    title = escape(assignment.title if assignment else "Задание")
    submitted_at = format_dt(submission.submitted_at, tz_name) if submission.submitted_at else "Не указано"
    status = submission.status or "SUBMITTED"

    text = (
        f"{card_header('🔍 Проверка работы', title)}\n"
        f"<b>Ученик:</b> {student_name}\n"
        f"<b>Статус:</b> 🟡 {status}\n"
        f"<b>Дата сдачи:</b> {submitted_at}\n\n"
        f"<i>Для полноценной проверки с код-ревью и выставлением баллов перейдите на веб-платформу:</i>\n"
    )

    from app.telegram import deep_links
    web_url = deep_links.submission(submission.submission_id) or (deep_links.assignment(assignment.assignment_id) if assignment else None)

    if web_url and is_localhost_url(web_url):
        text += f"\n{localhost_hint()}"

    keyboard: list[list[InlineKeyboardButton]] = []
    if web_url:
        keyboard.append([InlineKeyboardButton("📝 Проверить работу на сайте", url=web_url)])
    keyboard.append(build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_TEACHER}:queue:{return_page}"))

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_teacher_students_list(update: Update, user: User, page: int = 1) -> None:
    """Render paginated list of teacher's students."""
    students = build_teacher_students(user, limit=50)

    total_count = len(students)
    total_pages = max(1, math.ceil(total_count / PAGE_SIZE_STUDENTS))
    page = max(1, min(page, total_pages))

    start = (page - 1) * PAGE_SIZE_STUDENTS
    page_items = students[start : start + PAGE_SIZE_STUDENTS]

    text = f"{card_header('👥 Мои ученики', f'Всего прикреплено: {total_count}')}\n"
    keyboard: list[list[InlineKeyboardButton]] = []

    if not page_items:
        text += empty_state("👤", "Нет прикреплённых учеников", "У вас пока нет активных учеников в расписании платформы.")
    else:
        for item in page_items:
            name = escape(item.get("name") or "Ученик")
            active_hw = item.get("active_assignments", 0)
            in_rev = item.get("in_review", 0)
            sid = item.get("student_id")

            text += (
                f"• <b>{name}</b>\n"
                f"  ДЗ в работе: {active_hw} | На проверке: {in_rev}\n\n"
            )
            keyboard.append([InlineKeyboardButton(f"👤 {name}", callback_data=f"{CB_PREFIX}:{DOMAIN_TEACHER}:st_item:{sid}:{page}")])

    # Pagination row
    pag_row = build_pagination_row(DOMAIN_TEACHER, "st", page, total_pages)
    if pag_row:
        keyboard.append(pag_row)

    keyboard.append(build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_NAV}:home"))
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_teacher_student_card(update: Update, user: User, student_id: int, return_page: int = 1) -> None:
    """Render single student profile summary for teacher."""
    student = db.session.get(Student, student_id)
    if not student or (student.mentor_id != user.id and not (user.is_creator() or user.is_admin())):
        text = f"{card_header('Ученик не найден')}\n<i>Доступ к профилю ограничен или ученик не найден.</i>"
        keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_TEACHER}:st:{return_page}")]
        await render_screen(update, text, InlineKeyboardMarkup(keyboard))
        return

    name = escape(student.name)
    category = escape(getattr(student, "category", None) or "ЕГЭ")
    email = escape(student.email or "Не указан")
    active_assignments = Submission.query.filter(
        Submission.student_id == student.student_id,
        Submission.status.in_(("ASSIGNED", "IN_PROGRESS", "RETURNED"))
    ).count()

    text = (
        f"{card_header('👤 Карточка ученика', name)}\n"
        f"<b>Имя:</b> {name}\n"
        f"<b>Направление:</b> {category}\n"
        f"<b>Email:</b> {email}\n"
        f"<b>Заданий в работе:</b> {active_assignments}\n\n"
    )

    from app.telegram import deep_links
    web_url = deep_links.student(student.student_id)

    if web_url and is_localhost_url(web_url):
        text += f"{localhost_hint()}"

    keyboard: list[list[InlineKeyboardButton]] = []
    if web_url:
        keyboard.append([InlineKeyboardButton("💻 Открыть профиль на сайте", url=web_url)])
    keyboard.append(build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_TEACHER}:st:{return_page}"))

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))
