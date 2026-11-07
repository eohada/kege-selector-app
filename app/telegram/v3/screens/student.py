"""Student cabinet screens for BooStudy Bot V3."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

from app.models import User, Assignment, Submission, db, Lesson, Student
from app.telegram.application import (
    build_today_view,
    build_student_schedule,
    build_student_assignments,
    build_student_progress,
    _student_ids_for_context,
    coerce_to_utc,
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

    # 1. Lesson block
    try:
        st_tz = ZoneInfo(tz_name)
    except Exception:
        st_tz = timezone.utc
    st_today_date = datetime.now(st_tz).date()

    lesson_to_join = None
    live_lesson = None
    today_lesson = None
    future_lesson = None

    all_lessons = list(today.lessons)
    if not all_lessons:
        future_candidates = build_student_schedule(user, limit=3)
        all_lessons = list(future_candidates)

    for l in all_lessons:
        st_dt = l.get("starts_at")
        dur = int(l.get("duration") or 60)
        if st_dt:
            ends_dt = st_dt + timedelta(minutes=dur)
            if (st_dt <= now <= ends_dt) and l.get("status") != "cancelled":
                if not live_lesson:
                    live_lesson = l
            elif st_dt.astimezone(st_tz).date() == st_today_date and st_dt > now:
                if not today_lesson:
                    today_lesson = l
            elif st_dt.astimezone(st_tz).date() > st_today_date:
                if not future_lesson:
                    future_lesson = l

    if live_lesson:
        topic = escape(live_lesson.get("topic") or "Занятие")
        subject = escape(live_lesson.get("subject") or "Информатика")
        teacher_name = escape(live_lesson.get("teacher_name") or "")
        duration = live_lesson.get("duration", 60)
        lesson_to_join = live_lesson.get("lesson_url")
        text += (
            f"🔴 <b>Урок идёт прямо сейчас!</b>\n"
            f"• <b>{topic}</b> ({subject})\n"
            f"  ⏱ Длительность: {duration} мин\n"
        )
        if teacher_name:
            text += f"  👨‍🏫 Преподаватель: {teacher_name}\n"
        text += "\n"
    elif today_lesson:
        topic = escape(today_lesson.get("topic") or "Занятие")
        subject = escape(today_lesson.get("subject") or "Информатика")
        starts_at = format_dt(today_lesson.get("starts_at"), tz_name)
        teacher_name = escape(today_lesson.get("teacher_name") or "")
        duration = today_lesson.get("duration", 60)
        lesson_to_join = today_lesson.get("lesson_url")
        text += (
            f"📅 <b>Ближайший урок сегодня:</b>\n"
            f"• <b>{topic}</b> ({subject})\n"
            f"  🕒 {starts_at} · {duration} мин\n"
        )
        if teacher_name:
            text += f"  👨‍🏫 Преподаватель: {teacher_name}\n"
        text += "\n"
    elif future_lesson:
        topic = escape(future_lesson.get("topic") or "Занятие")
        subject = escape(future_lesson.get("subject") or "Информатика")
        starts_at = format_dt(future_lesson.get("starts_at"), tz_name)
        teacher_name = escape(future_lesson.get("teacher_name") or "")
        duration = future_lesson.get("duration", 60)
        lesson_to_join = future_lesson.get("lesson_url")
        text += (
            f"📅 <b>Ближайший урок:</b>\n"
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
    if live_lesson and lesson_to_join:
        keyboard.append([InlineKeyboardButton("🔴 Войти в урок", url=lesson_to_join)])
    elif lesson_to_join:
        keyboard.append([InlineKeyboardButton("🎥 Войти в комнату урока", url=lesson_to_join)])

    if urgent_btn_target:
        u_id = urgent_btn_target[0]
        keyboard.append([InlineKeyboardButton("📝 Открыть задание", callback_data=f"{CB_PREFIX}:{DOMAIN_STUDENT}:hw_item:{u_id}:urgent:1")])
    if graded_btn_target:
        g_id = graded_btn_target[0]
        keyboard.append([InlineKeyboardButton("📊 Отзыв учителя", callback_data=f"{CB_PREFIX}:{DOMAIN_STUDENT}:hw_item:{g_id}:graded:1")])

    mini_app_btn = build_mini_app_button("📱 Открыть Mini App")
    if mini_app_btn:
        keyboard.append([mini_app_btn])

    keyboard.extend([
        [InlineKeyboardButton("📅 Расписание занятий", callback_data=f"{CB_PREFIX}:{DOMAIN_STUDENT}:sch")],
        [InlineKeyboardButton(f"📝 Домашние задания ({len(active_in_progress) + len(overdue_hw)})", callback_data=f"{CB_PREFIX}:{DOMAIN_STUDENT}:hw:all:1")],
        [InlineKeyboardButton("🏆 Мой прогресс и оценки", callback_data=f"{CB_PREFIX}:{DOMAIN_STUDENT}:prog")],
        [InlineKeyboardButton("❓ Справка и помощь", callback_data=f"{CB_PREFIX}:{DOMAIN_STUDENT}:help")],
        [
            InlineKeyboardButton("⚙️ Настройки", callback_data=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:home"),
            InlineKeyboardButton("🔄 Обновить", callback_data=f"{CB_PREFIX}:{DOMAIN_NAV}:home"),
        ],
    ])

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_student_schedule(update: Update, user: User) -> None:
    """Render student's upcoming schedule with clickable cards."""
    schedule = build_student_schedule(user, limit=10)
    tz_name = getattr(user.profile, "timezone", "Europe/Moscow")

    text = f"{card_header('📅 Расписание занятий', 'Ближайшие уроки')}\n"
    keyboard: list[list[InlineKeyboardButton]] = []

    if not schedule:
        text += empty_state("📅", "Нет запланированных занятий", "В ближайшие дни уроков не запланировано. Расписание обновляется преподавателем.")
    else:
        text += "Список ближайших уроков (нажмите на урок для деталей):\n\n"
        for idx, item in enumerate(schedule, 1):
            topic = escape(item.get("topic") or "Урок")
            subject = escape(item.get("subject") or "Информатика")
            teacher_name = escape(item.get("teacher_name") or "")
            when = format_dt(item.get("starts_at"), tz_name)
            duration = item.get("duration", 60)
            teacher_str = f" · {teacher_name}" if teacher_name else ""
            live_prefix = "🔴 " if item.get("is_live") else ""

            text += f"{live_prefix}<b>{idx}. {topic}</b> ({subject})\n   🕒 {when} ({duration} мин){teacher_str}\n\n"

            btn_label = f"🕒 {when[:11]} — {topic[:20]}"
            if item.get("is_live"):
                btn_label = f"🔴 {topic[:22]}"
            keyboard.append([InlineKeyboardButton(btn_label, callback_data=f"{CB_PREFIX}:{DOMAIN_STUDENT}:les:{item['lesson_id']}")])

    keyboard.append(build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_NAV}:home"))
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_student_lesson_card(update: Update, user: User, lesson_id: int) -> None:
    """Render single lesson detail view for student."""
    lesson = db.session.get(Lesson, lesson_id)
    allowed_students = _student_ids_for_context(user, "student")
    if not lesson or (lesson.student_id not in allowed_students and not (user.is_creator() or user.is_admin())):
        text = f"{card_header('Урок не найден')}\n<i>Запрошенный урок недоступен или удалён из расписания.</i>"
        keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_STUDENT}:sch")]
        await render_screen(update, text, InlineKeyboardMarkup(keyboard))
        return

    tz_name = getattr(user.profile, "timezone", "Europe/Moscow")
    now = datetime.now(timezone.utc)
    topic = escape(lesson.topic or "Занятие")
    subject = escape(lesson.subject or "Информатика")
    duration = int(lesson.duration or 60)
    starts_utc = coerce_to_utc(lesson.lesson_date)
    ends_utc = starts_utc + timedelta(minutes=duration) if starts_utc else None

    # Status
    if starts_utc and ends_utc and starts_utc <= now <= ends_utc and lesson.status != "cancelled":
        status_badge = "🔴 Идёт прямо сейчас"
        is_live = True
    elif starts_utc and starts_utc > now:
        status_badge = "⏳ Запланирован"
        is_live = False
    elif lesson.status == "cancelled":
        status_badge = "❌ Отменён"
        is_live = False
    else:
        status_badge = "✅ Завершён"
        is_live = False

    starts_str = format_dt(starts_utc, tz_name) if starts_utc else "Не указано"

    teacher_name = None
    if lesson.teacher_id:
        tch = db.session.get(User, lesson.teacher_id)
        if tch:
            teacher_name = tch.full_name or tch.username

    text = (
        f"{card_header('📅 Карточка урока', topic)}\n"
        f"<b>Предмет:</b> {subject}\n"
        f"<b>Статус:</b> {status_badge}\n"
        f"<b>🕒 Начало:</b> {starts_str}\n"
        f"<b>⏱ Длительность:</b> {duration} мин\n"
    )
    if teacher_name:
        text += f"<b>👨‍🏫 Преподаватель:</b> {escape(teacher_name)}\n"

    if lesson.notes:
        text += f"\n<b>📝 Заметки к уроку:</b>\n<i>{escape(lesson.notes)}</i>\n"

    # Related homework
    related_asgn = Assignment.query.filter_by(lesson_id=lesson.lesson_id, is_active=True).first()
    hw_btn = None
    if related_asgn:
        text += f"\n📝 <b>Домашнее задание к уроку:</b>\n• <b>{escape(related_asgn.title)}</b>"
        if related_asgn.deadline:
            dl_str = format_dt(related_asgn.deadline, tz_name, relative=False)
            text += f" (до {dl_str})"
        text += "\n"
        hw_btn = InlineKeyboardButton("📝 Домашнее задание к уроку", callback_data=f"{CB_PREFIX}:{DOMAIN_STUDENT}:hw_item:{related_asgn.assignment_id}:all:1")

    from app.telegram import deep_links
    room_url = deep_links.lesson(lesson.lesson_id)

    keyboard: list[list[InlineKeyboardButton]] = []
    if is_live and room_url:
        keyboard.append([InlineKeyboardButton("🔴 Войти в урок", url=room_url)])
    elif room_url:
        keyboard.append([InlineKeyboardButton("🎥 Комната урока", url=room_url)])

    if hw_btn:
        keyboard.append([hw_btn])

    keyboard.append([
        InlineKeyboardButton("◀️ К расписанию", callback_data=f"{CB_PREFIX}:{DOMAIN_STUDENT}:sch"),
        InlineKeyboardButton("🏠 Главное меню", callback_data=f"{CB_PREFIX}:{DOMAIN_NAV}:home"),
    ])

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_student_hw_list(update: Update, user: User, category: str = "all", page: int = 1) -> None:
    """Render paginated student assignments list with category tabs."""
    valid_categories = {"all", "urgent", "active", "review", "graded"}
    if category not in valid_categories:
        category = "all"

    all_filtered_hw = build_student_assignments(user, status_filter=category, limit=100)
    tz_name = getattr(user.profile, "timezone", "Europe/Moscow")

    total_count = len(all_filtered_hw)
    total_pages = max(1, math.ceil(total_count / PAGE_SIZE_HW))
    page = max(1, min(page, total_pages))

    start = (page - 1) * PAGE_SIZE_HW
    page_items = all_filtered_hw[start : start + PAGE_SIZE_HW]

    cat_titles = {
        "all": "Все задания",
        "urgent": "Срочные задания",
        "active": "Задания в работе",
        "review": "На проверке",
        "graded": "Проверенные работы",
    }
    header_subtitle = f"{cat_titles[category]} ({total_count})"
    text = f"{card_header('📝 Домашние задания', header_subtitle)}\n"

    keyboard: list[list[InlineKeyboardButton]] = []

    # Category tabs (2 rows)
    tab_row_1 = []
    for c_id, c_lbl in [("all", "Все"), ("urgent", "⚠️ Срочные"), ("active", "⏳ В работе")]:
        lbl = f"• {c_lbl} •" if c_id == category else c_lbl
        tab_row_1.append(InlineKeyboardButton(lbl, callback_data=f"{CB_PREFIX}:{DOMAIN_STUDENT}:hw:{c_id}:1"))
    tab_row_2 = []
    for c_id, c_lbl in [("review", "🟡 На проверке"), ("graded", "🟢 Проверенные")]:
        lbl = f"• {c_lbl} •" if c_id == category else c_lbl
        tab_row_2.append(InlineKeyboardButton(lbl, callback_data=f"{CB_PREFIX}:{DOMAIN_STUDENT}:hw:{c_id}:1"))
    keyboard.append(tab_row_1)
    keyboard.append(tab_row_2)

    if not page_items:
        empty_descs = {
            "urgent": ("Нет срочных заданий", "Все ближайшие дедлайны соблюдены или сданы на проверку."),
            "active": ("Нет заданий в работе", "У вас нет текущих несданных домашних заданий."),
            "review": ("Нет работ на проверке", "В данный момент ни одна работа не ожидает проверки преподавателем."),
            "graded": ("Нет проверенных работ", "Проверенные работы с оценками появятся здесь."),
            "all": ("Нет назначенных заданий", "Все домашние задания выполнены или ещё не назначены преподавателем."),
        }
        e_title, e_sub = empty_descs.get(category, ("Нет заданий", ""))
        text += empty_state("📝", e_title, e_sub)
    else:
        now = datetime.now(timezone.utc)
        for item in page_items:
            title = escape(item.get("title") or "Задание")
            badge = _status_badge(item.get("status"))
            deadline_dt = item.get("deadline")
            deadline_str = format_dt(deadline_dt, tz_name, relative=False) if deadline_dt else "бессрочно"
            assignment_id = item.get("assignment_id")
            teacher = escape(item.get("teacher_name") or "")
            teacher_str = f" · 👨‍🏫 {teacher}" if teacher else ""

            # Urgency indicator
            st = str(item.get("status") or "").upper()
            urgency = ""
            if st not in {"CHECKED", "GRADED", "COMPLETED", "SUBMITTED", "IN_REVIEW"}:
                if deadline_dt and deadline_dt < now:
                    urgency = " ⚠️ [Просрочено]"
                elif deadline_dt and (deadline_dt - now).total_seconds() <= 86400:
                    urgency = " ⏳ [Срок сегодня/завтра]"

            score_info = ""
            if st in {"CHECKED", "GRADED", "COMPLETED"} and item.get("percentage") is not None:
                score_info = f" | Оценка: <b>{item['percentage']:.0f}%</b>"

            text += (
                f"• <b>{title}</b>{urgency}\n"
                f"  Статус: {badge}{score_info} | Дедлайн: {deadline_str}{teacher_str}\n\n"
            )

            btn_title = f"📄 {title[:28]}" if len(title) > 28 else f"📄 {title}"
            keyboard.append([InlineKeyboardButton(btn_title, callback_data=f"{CB_PREFIX}:{DOMAIN_STUDENT}:hw_item:{assignment_id}:{category}:{page}")])

    # Pagination row
    pag_row = build_pagination_row(DOMAIN_STUDENT, f"hw:{category}", page, total_pages)
    if pag_row:
        keyboard.append(pag_row)

    keyboard.append(build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_NAV}:home"))
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_student_hw_item(
    update: Update,
    user: User,
    assignment_id: int,
    return_category: str = "all",
    return_page: int = 1,
) -> None:
    """Render detailed view of a single assignment with clean category return."""
    assignment = db.session.get(Assignment, assignment_id)
    if not assignment or not assignment.is_active:
        text = f"{card_header('Задание не найдено')}\n<i>Запрошенное задание недоступно или удалено.</i>"
        keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_STUDENT}:hw:{return_category}:{return_page}")]
        await render_screen(update, text, InlineKeyboardMarkup(keyboard))
        return

    student_ids = _student_ids_for_context(user, "student")
    submission = None
    if student_ids:
        submission = Submission.query.filter(
            Submission.assignment_id == assignment.assignment_id,
            Submission.student_id.in_(student_ids),
        ).first()

    if not submission and not (user.is_creator() or user.is_admin()):
        text = f"{card_header('Доступ ограничен')}\n<i>У вас нет доступа к материалам этого домашнего задания.</i>"
        keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_STUDENT}:hw:{return_category}:{return_page}")]
        await render_screen(update, text, InlineKeyboardMarkup(keyboard))
        return

    tz_name = getattr(user.profile, "timezone", "Europe/Moscow")
    now = datetime.now(timezone.utc)
    title = escape(assignment.title)
    desc = escape(assignment.description or "Без дополнительного описания.")
    deadline = format_dt(assignment.deadline, tz_name) if assignment.deadline else "Бессрочно"
    st_val = str(submission.status if submission else "ASSIGNED").upper()
    status = _status_badge(st_val)

    # Urgency check
    is_overdue = bool(assignment.deadline and coerce_to_utc(assignment.deadline) < now and st_val not in {"CHECKED", "GRADED", "COMPLETED", "SUBMITTED", "IN_REVIEW"})

    teacher_name = None
    if assignment.created_by_id:
        tch = db.session.get(User, assignment.created_by_id)
        if tch:
            teacher_name = tch.full_name or tch.username

    text = f"{card_header('📝 Карточка задания', title)}\n"
    if is_overdue:
        text += "🚨 <b>Внимание: срок сдачи задания истёк!</b>\n\n"

    text += (
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
    keyboard.append([
        InlineKeyboardButton("◀️ Назад к заданиям", callback_data=f"{CB_PREFIX}:{DOMAIN_STUDENT}:hw:{return_category}:{return_page}"),
        InlineKeyboardButton("🏠 Главное меню", callback_data=f"{CB_PREFIX}:{DOMAIN_NAV}:home"),
    ])

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_student_progress(update: Update, user: User) -> None:
    """Render student's learning progress and achievements."""
    progress = build_student_progress(user)
    name = escape(get_display_name(user))
    tz_name = getattr(user.profile, "timezone", "Europe/Moscow")

    text = f"{card_header(f'🏆 Прогресс обучения · {name}', 'Успеваемость и результаты')}\n"

    submissions = progress.get("submissions", []) if progress else []
    graded = [s for s in submissions if s.get("percentage") is not None]

    keyboard: list[list[InlineKeyboardButton]] = []

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
            latest_str = f"<b>{latest_score:.0f}%</b> ({trend})"
        else:
            latest_str = f"<b>{latest_score:.0f}%</b> (🎯 Первый результат)"

        text += (
            f"📈 <b>Сводка успеваемости:</b>\n"
            f"• Проверено работ: <b>{len(graded)}</b>\n"
            f"• Средний балл: <b>{avg_score:.1f}%</b>\n"
            f"• Последняя оценка: {latest_str}\n"
            f"• Лучший результат: <b>{best_score:.0f}%</b> | Нижний: <b>{lowest_score:.0f}%</b>\n"
            f"• Заданий в работе: <b>{pending}</b>\n\n"
        )

        by_subj = progress.get("by_subject", {}) if progress else {}
        if by_subj and len(by_subj) > 1:
            text += "📚 <b>Успеваемость по предметам:</b>\n"
            for subj_name, stats in by_subj.items():
                s_avg = stats.get("avg", 0)
                s_cnt = stats.get("count", 0)
                text += f"• <b>{escape(subj_name)}</b>: средний балл <b>{s_avg:.1f}%</b> ({s_cnt} раб.)\n"
            text += "\n"

        text += "<b>Недавно проверенные работы (нажмите для просмотра):</b>\n"
        for item in graded[:5]:
            title = escape(item.get("title") or "Работа")
            score = item.get("percentage")
            graded_at = item.get("graded_at")
            date_str = f" · {format_dt(graded_at, tz_name, relative=False)}" if graded_at else ""
            text += f"• <b>{title}</b>: <b>{score:.0f}%</b>{date_str}\n"

            btn_label = f"📊 {title[:20]} — {score:.0f}%"
            asgn_id = item.get("assignment_id")
            if asgn_id:
                keyboard.append([InlineKeyboardButton(btn_label, callback_data=f"{CB_PREFIX}:{DOMAIN_STUDENT}:hw_item:{asgn_id}:graded:1")])
        text += "\n"

    keyboard.append([
        InlineKeyboardButton("📝 К моим заданиям", callback_data=f"{CB_PREFIX}:{DOMAIN_STUDENT}:hw:all:1"),
        InlineKeyboardButton("🏠 Главное меню", callback_data=f"{CB_PREFIX}:{DOMAIN_NAV}:home"),
    ])

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_student_help(update: Update, user: User) -> None:
    """Render friendly onboarding and guide for students."""
    name = escape(get_display_name(user))
    text = (
        f"{card_header(f'❓ Справка и помощь · {name}', 'Гид по Telegram-боту BooStudy')}\n"
        f"Добро пожаловать в личный кабинет ученика BooStudy!\n\n"
        f"📅 <b>Уроки и видеокомната:</b>\n"
        f"• В разделе «Расписание» доступны все ваши запланированные занятия.\n"
        f"• Кнопка входа в интерактивную видеокомнату появляется за 15 минут до начала и активна во время занятия.\n\n"
        f"📝 <b>Домашние задания:</b>\n"
        f"• Вкладка «Домашние задания» разделена на удобные категории: Все, Срочные, В работе, На проверке и Проверенные.\n"
        f"• Нажмите на любое задание, чтобы открыть карточку с дедлайном, условием и комментариями преподавателя.\n\n"
        f"🏆 <b>Прогресс и оценки:</b>\n"
        f"• В разделе «Мой прогресс» отображается средний балл по предметам и динамика ваших результатов.\n\n"
        f"🔔 <b>Уведомления:</b>\n"
        f"• Бот автоматически напоминает об уроках и сообщает, когда преподаватель проверил ваше задание.\n"
        f"• Настроить оповещения можно в «Настройках».\n\n"
        f"💬 <b>Поддержка:</b>\n"
        f"• Если возникли вопросы или технические сложности, обратитесь к вашему преподавателю или в поддержку платформы.\n"
    )
    keyboard = [
        [InlineKeyboardButton("⚙️ Настройки уведомлений", callback_data=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:home")],
        build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_NAV}:home"),
    ]
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))
