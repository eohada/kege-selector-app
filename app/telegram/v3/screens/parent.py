"""Parent screens for BooStudy Bot V3."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

from app.models import db, User, Student, Lesson, Assignment, Submission, FamilyTie
from app.telegram.application import (
    build_parent_children,
    build_parent_schedule,
    build_parent_digest,
    _student_ids_for_context,
    coerce_to_utc,
)
from app.telegram.v3.constants import CB_PREFIX, DOMAIN_NAV, DOMAIN_PARENT, DOMAIN_SETTINGS, PAGE_SIZE_HW
from app.telegram.v3.identity import get_display_name
from app.telegram.v3.ui import (
    card_header,
    empty_state,
    escape,
    format_dt,
    build_mini_app_button,
    build_nav_row,
    build_pagination_row,
    render_screen,
)


def _parent_hw_status_badge(submission: Submission | None, deadline: datetime | None, now: datetime) -> str:
    if not submission:
        if deadline and deadline < now:
            return "⚠️ Просрочено (не сдано)"
        return "⚪ Ожидает выполнения"

    st = str(submission.status or "").upper()
    if st in {"CHECKED", "GRADED", "COMPLETED"}:
        pct = f" ({submission.percentage:.0f}%)" if submission.percentage is not None else ""
        return f"🟢 Проверено{pct}"
    if st in {"SUBMITTED", "IN_REVIEW"}:
        return "🟡 На проверке"
    if st == "RETURNED":
        return "🟠 На доработке"
    if deadline and deadline < now:
        return "⚠️ Просрочено (не сдано)"
    return "⚪ В процессе выполнения"


async def show_parent_home(update: Update, user: User) -> None:
    """Render the Parent Home dashboard."""
    children = build_parent_children(user)
    name = escape(get_display_name(user))
    tz_name = getattr(user.profile, "timezone", "Europe/Moscow")

    if len(children) == 1:
        # Single child: jump straight to child card
        await show_parent_child_view(update, user, children[0].student_id, is_single_child=True)
        return

    text = f"{card_header(f'👨‍👩‍👧 Родительский кабинет · {name}', 'Контроль успеваемости')}\n"

    keyboard: list[list[InlineKeyboardButton]] = []
    mini_app_btn = build_mini_app_button("📱 Открыть Mini App")
    if mini_app_btn:
        keyboard.append([mini_app_btn])

    if not children:
        text += empty_state(
            "👨‍👩‍👧",
            "Дети не привязаны",
            "К вашему аккаунту пока не привязаны подтверждённые профили детей. "
            "Привязка выполняется через приглашение на платформе BooStudy."
        )
    else:
        text += f"Прикреплено детей: <b>{len(children)}</b>\n\n"
        for child in children:
            cname = escape(child.name)
            next_l = child.next_lesson
            lesson_str = format_dt(next_l.get("starts_at"), tz_name) if next_l else "уроков нет"

            text += (
                f"• <b>{cname}</b>\n"
                f"  Ближайший урок: {lesson_str}\n"
                f"  Активных ДЗ: <b>{child.active_assignments}</b>"
            )
            if child.overdue_assignments:
                text += f" (⚠️ просрочено: {child.overdue_assignments})"
            if child.latest_result_percent is not None:
                text += f" | Посл. оценка: <b>{child.latest_result_percent:.0f}%</b>"
            text += "\n\n"

            keyboard.append([InlineKeyboardButton(f"👧 {cname} — подробнее", callback_data=f"{CB_PREFIX}:{DOMAIN_PARENT}:ch:{child.student_id}")])

    keyboard.append([
        InlineKeyboardButton("⚙️ Настройки", callback_data=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:home"),
        InlineKeyboardButton("🔄 Обновить", callback_data=f"{CB_PREFIX}:{DOMAIN_NAV}:home"),
    ])

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_parent_child_view(update: Update, user: User, student_id: int, is_single_child: bool = False) -> None:
    """Render specific child's overview card."""
    allowed_students = set(_student_ids_for_context(user, "parent"))
    if student_id not in allowed_students:
        text = f"{card_header('Доступ ограничен')}\n<i>Профиль ученика не найден среди ваших привязанных детей.</i>"
        keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_PARENT}:home")]
        await render_screen(update, text, InlineKeyboardMarkup(keyboard))
        return

    student = db.session.get(Student, student_id)
    cname = escape(student.name if student else f"Ученик #{student_id}")
    tz_name = getattr(user.profile, "timezone", "Europe/Moscow")
    now = datetime.now(timezone.utc)

    # Nearest lesson across days with teacher name
    next_lesson = (
        db.session.query(Lesson)
        .filter(
            Lesson.student_id == student_id,
            Lesson.lesson_date.isnot(None),
            Lesson.lesson_date >= now,
            Lesson.status.notin_(("cancelled", "completed")),
        )
        .order_by(Lesson.lesson_date.asc())
        .first()
    )

    lesson_block = "📅 <b>Ближайшее занятие:</b>\n"
    if next_lesson:
        topic = escape(next_lesson.topic or "Занятие")
        subject = escape(next_lesson.subject or "Информатика")
        when = format_dt(next_lesson.lesson_date, tz_name)
        duration = next_lesson.duration or 60
        teacher_name = None
        if next_lesson.teacher_id:
            t_user = db.session.get(User, next_lesson.teacher_id)
            if t_user:
                teacher_name = t_user.full_name or t_user.username
        teacher_str = f"👨‍🏫 Преподаватель: {escape(teacher_name)}\n" if teacher_name else ""
        lesson_block += f"• <b>{topic}</b> ({subject})\n  🕒 {when} · {duration} мин\n  {teacher_str}\n"
    else:
        lesson_block += "• <i>В ближайшие дни занятий не запланировано. Расписание обновляется преподавателем.</i>\n\n"

    # Homework stats
    submissions = (
        db.session.query(Submission)
        .join(Assignment)
        .filter(
            Submission.student_id == student_id,
            Assignment.is_active.is_(True),
        )
        .all()
    )
    active_hw = [s for s in submissions if str(s.status).upper() not in {"CHECKED", "GRADED", "COMPLETED"}]
    overdue_hw = [s for s in active_hw if s.assignment and s.assignment.deadline and coerce_to_utc(s.assignment.deadline) < now]

    hw_block = (
        f"📝 <b>Домашние задания:</b>\n"
        f"• В процессе выполнения: <b>{len(active_hw)}</b>\n"
        f"• Просроченных (ждут сдачи): <b>{len(overdue_hw)}</b>\n"
    )
    if overdue_hw:
        hw_block += "\n⚠️ <b>Просроченные задания:</b>\n"
        for o_sub in overdue_hw[:3]:
            asg_t = escape(o_sub.assignment.title if o_sub.assignment else "Задание")
            asg_dl = format_dt(o_sub.assignment.deadline, tz_name) if o_sub.assignment else ""
            hw_block += f"• <b>{asg_t}</b> — сдать до: {asg_dl}\n"
    hw_block += "\n"

    # Contextual latest grade
    latest_graded = (
        db.session.query(Submission)
        .join(Assignment)
        .filter(
            Submission.student_id == student_id,
            Submission.percentage.isnot(None),
        )
        .order_by(Submission.graded_at.desc().nullslast(), Submission.submission_id.desc())
        .first()
    )

    if latest_graded:
        work_title = escape(latest_graded.assignment.title if latest_graded.assignment else "Работа")
        score_text = f"<b>{latest_graded.percentage:.0f}%</b>"
        if latest_graded.total_score is not None and latest_graded.max_score:
            score_text += f" ({latest_graded.total_score} из {latest_graded.max_score} баллов)"
        grade_date = format_dt(latest_graded.graded_at, tz_name) if latest_graded.graded_at else ""
        date_str = f" <i>({grade_date})</i>" if grade_date else ""
        grade_block = f"📊 <b>Последняя проверенная работа:</b>\n• {work_title}: {score_text}{date_str}\n"
        fb = getattr(latest_graded, "teacher_feedback", None) or getattr(latest_graded, "teacher_comment", None)
        if fb:
            grade_block += f"  💬 <i>«{escape(fb[:80])}»</i>\n"
        grade_block += "\n"
    else:
        grade_block = "📊 <b>Последняя оценка:</b> <i>Оценок пока нет — проверенные работы появятся здесь.</i>\n\n"

    text = (
        f"{card_header(f'👧 Ученик: {cname}', 'Учебная активность ребёнка')}\n"
        f"{lesson_block}"
        f"{hw_block}"
        f"{grade_block}"
    )

    all_children = build_parent_children(user)
    has_multiple = len(all_children) > 1

    keyboard: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(f"📝 Домашние задания ({len(active_hw)})", callback_data=f"{CB_PREFIX}:{DOMAIN_PARENT}:hw:{student_id}:1")],
        [InlineKeyboardButton("📅 Расписание занятий", callback_data=f"{CB_PREFIX}:{DOMAIN_PARENT}:sch:{student_id}")],
        [InlineKeyboardButton("📊 Учебный дайджест", callback_data=f"{CB_PREFIX}:{DOMAIN_PARENT}:dig:{student_id}")],
    ]

    back_cb = f"{CB_PREFIX}:{DOMAIN_PARENT}:home" if has_multiple and not is_single_child else f"{CB_PREFIX}:{DOMAIN_NAV}:home"
    keyboard.append(build_nav_row(back_cb=back_cb))

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_parent_child_hw_list(update: Update, user: User, student_id: int, page: int = 1) -> None:
    """Render paginated list of child's homework assignments for parent."""
    allowed_students = set(_student_ids_for_context(user, "parent"))
    if student_id not in allowed_students:
        text = f"{card_header('Доступ ограничен')}\n<i>Профиль ученика не найден среди ваших привязанных детей.</i>"
        keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_PARENT}:home")]
        await render_screen(update, text, InlineKeyboardMarkup(keyboard))
        return

    student = db.session.get(Student, student_id)
    cname = escape(student.name if student else f"Ученик #{student_id}")
    tz_name = getattr(user.profile, "timezone", "Europe/Moscow")
    now = datetime.now(timezone.utc)

    submissions = (
        db.session.query(Submission)
        .join(Assignment)
        .filter(
            Submission.student_id == student_id,
            Assignment.is_active.is_(True),
        )
        .order_by(
            Submission.graded_at.desc().nullslast(),
            Assignment.deadline.asc().nullslast(),
            Submission.submission_id.desc(),
        )
        .all()
    )

    total_count = len(submissions)
    total_pages = max(1, math.ceil(total_count / PAGE_SIZE_HW))
    page = max(1, min(page, total_pages))

    start = (page - 1) * PAGE_SIZE_HW
    page_items = submissions[start : start + PAGE_SIZE_HW]

    text = f"{card_header(f'📝 Задания ребёнка · {cname}', f'Всего заданий: {total_count}')}\n"

    keyboard: list[list[InlineKeyboardButton]] = []

    if not page_items:
        text += empty_state("✨", "Нет заданий", "Ученику пока не назначены домашние задания.")
    else:
        for sub in page_items:
            asg = sub.assignment
            title = escape(asg.title if asg else "Задание")
            deadline_utc = coerce_to_utc(asg.deadline) if asg else None
            badge = _parent_hw_status_badge(sub, deadline_utc, now)
            dl_str = format_dt(deadline_utc, tz_name, relative=False) if deadline_utc else "бессрочно"

            text += (
                f"• <b>{title}</b>\n"
                f"  Статус: {badge}\n"
                f"  Дедлайн: {dl_str}\n\n"
            )

            btn_title = f"📄 {asg.title[:26]}" if asg and len(asg.title) > 26 else f"📄 {asg.title if asg else 'Задание'}"
            keyboard.append([InlineKeyboardButton(btn_title, callback_data=f"{CB_PREFIX}:{DOMAIN_PARENT}:hw_item:{student_id}:{sub.assignment_id}:{page}")])

    pag_row = build_pagination_row(DOMAIN_PARENT, f"hw:{student_id}", page, total_pages)
    if pag_row:
        keyboard.append(pag_row)

    keyboard.append(build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_PARENT}:ch:{student_id}"))
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_parent_child_hw_item(update: Update, user: User, student_id: int, assignment_id: int, return_page: int = 1) -> None:
    """Render detailed view of a child's specific homework assignment for parent."""
    allowed_students = set(_student_ids_for_context(user, "parent"))
    if student_id not in allowed_students:
        text = f"{card_header('Доступ ограничен')}\n<i>Профиль ученика не найден среди ваших привязанных детей.</i>"
        keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_PARENT}:home")]
        await render_screen(update, text, InlineKeyboardMarkup(keyboard))
        return

    student = db.session.get(Student, student_id)
    cname = escape(student.name if student else f"Ученик #{student_id}")
    asg = db.session.get(Assignment, assignment_id)
    if not asg or not asg.is_active:
        text = f"{card_header('Задание не найдено')}\n<i>Запрошенное задание не найдено или удалено.</i>"
        keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_PARENT}:hw:{student_id}:{return_page}")]
        await render_screen(update, text, InlineKeyboardMarkup(keyboard))
        return

    sub = (
        db.session.query(Submission)
        .filter(
            Submission.student_id == student_id,
            Submission.assignment_id == assignment_id,
        )
        .first()
    )

    tz_name = getattr(user.profile, "timezone", "Europe/Moscow")
    now = datetime.now(timezone.utc)
    deadline_utc = coerce_to_utc(asg.deadline)
    badge = _parent_hw_status_badge(sub, deadline_utc, now)
    dl_str = format_dt(deadline_utc, tz_name) if deadline_utc else "Бессрочно"

    text = (
        f"{card_header('📝 Домашнее задание', cname)}\n"
        f"<b>Тема:</b> <b>{escape(asg.title)}</b>\n"
        f"<b>Статус:</b> {badge}\n"
        f"<b>Срок сдачи:</b> {dl_str}\n\n"
    )

    if asg.description:
        text += f"<b>Инструкция:</b>\n<i>{escape(asg.description)}</i>\n\n"

    if sub and sub.percentage is not None:
        score_text = f"<b>{sub.percentage:.0f}%</b>"
        if sub.total_score is not None and sub.max_score:
            score_text += f" ({sub.total_score} из {sub.max_score} баллов)"
        text += f"📊 <b>Результат проверки:</b> {score_text}\n"

    feedback = getattr(sub, "teacher_feedback", None) or getattr(sub, "teacher_comment", None) if sub else None
    if feedback:
        text += f"💬 <b>Комментарий учителя:</b>\n<i>{escape(feedback)}</i>\n\n"

    keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_PARENT}:hw:{student_id}:{return_page}")]
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_parent_child_schedule(update: Update, user: User, student_id: int) -> None:
    """Render child's upcoming lessons."""
    allowed_students = set(_student_ids_for_context(user, "parent"))
    if student_id not in allowed_students:
        text = f"{card_header('Доступ ограничен')}\n<i>Профиль ученика не найден среди ваших привязанных детей.</i>"
        keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_PARENT}:home")]
        await render_screen(update, text, InlineKeyboardMarkup(keyboard))
        return

    student = db.session.get(Student, student_id)
    cname = escape(student.name if student else f"Ученик #{student_id}")

    all_sch = build_parent_schedule(user, limit=10) or ()
    child_sch = [item for item in all_sch if item.get("student_id") == student_id]
    tz_name = getattr(user.profile, "timezone", "Europe/Moscow")

    text = f"{card_header(f'📅 Расписание · {cname}', 'Ближайшие уроки')}\n"

    if not child_sch:
        text += empty_state("📅", "Нет запланированных занятий", "В ближайшие дни уроков не запланировано. Расписание обновляется преподавателем.")
    else:
        text += "Список ближайших уроков:\n\n"
        for idx, item in enumerate(child_sch, 1):
            topic = escape(item.get("topic") or "Занятие")
            when = format_dt(item.get("starts_at"), tz_name)
            duration = item.get("duration", 60)
            teacher_str = f"👨‍🏫 {escape(item['teacher_name'])}\n   " if item.get("teacher_name") else ""
            text += f"<b>{idx}. {topic}</b>\n   {teacher_str}🕒 {when} ({duration} мин)\n\n"

    keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_PARENT}:ch:{student_id}")]
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_parent_child_digest(update: Update, user: User, student_id: int) -> None:
    """Render weekly learning digest for child."""
    allowed_students = set(_student_ids_for_context(user, "parent"))
    if student_id not in allowed_students:
        text = f"{card_header('Доступ ограничен')}\n<i>Профиль ученика не найден среди ваших привязанных детей.</i>"
        keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_PARENT}:home")]
        await render_screen(update, text, InlineKeyboardMarkup(keyboard))
        return

    student = db.session.get(Student, student_id)
    cname = escape(student.name if student else f"Ученик #{student_id}")

    digest = build_parent_digest(user, student_id)

    text = f"{card_header(f'📊 Учебный дайджест · {cname}', 'Сводка успеваемости')}\n"

    if not digest:
        text += empty_state("📊", "Нет данных", "Учебные показатели появятся после выполнения первых заданий.")
    else:
        text += (
            f"📈 <b>Показатели за период:</b>\n"
            f"• Выполнено заданий: <b>{digest.completed_count}</b>\n"
            f"• Заданий в работе: <b>{digest.active_count}</b>\n"
            f"• Просроченных заданий: <b>{digest.overdue_count}</b>\n\n"
        )
        if digest.latest_results:
            text += "<b>Недавние результаты проверок:</b>\n"
            for score in digest.latest_results:
                text += f"• Оценка: <b>{score:.0f}%</b>\n"
            text += "\n"

    keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_PARENT}:ch:{student_id}")]
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))
