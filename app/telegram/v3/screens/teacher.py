"""Teacher and tutor screens for BooStudy Bot V3."""
from __future__ import annotations

import math
from typing import Any
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

from datetime import datetime, timedelta, timezone
from sqlalchemy import or_, and_

from app.models import db, User, Student, Submission, Lesson, Assignment
from app.telegram.application import (
    build_today_view,
    build_teacher_review_queue,
    build_teacher_students,
    can_teacher_review_submission,
    _student_ids_for_context,
    coerce_to_utc,
)

from app.telegram.v3.constants import (
    CB_PREFIX,
    DOMAIN_BROADCAST,
    DOMAIN_NAV,
    DOMAIN_SETTINGS,
    DOMAIN_TEACHER,
    PAGE_SIZE_HW,
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
    now = datetime.now(timezone.utc)

    text = f"{card_header(f'👨‍🏫 Преподавательская · {name}', 'Учебный процесс')}\n"

    # 1. Nearest lesson block
    from zoneinfo import ZoneInfo
    try:
        teacher_tz = ZoneInfo(tz_name)
    except Exception:
        teacher_tz = timezone.utc
    today_date = datetime.now(teacher_tz).date()

    today_lessons = []
    future_lessons = []
    for l in today.lessons:
        st_dt = l.get("starts_at")
        if st_dt:
            if st_dt.astimezone(teacher_tz).date() == today_date:
                today_lessons.append(l)
            elif st_dt.astimezone(teacher_tz).date() > today_date:
                future_lessons.append(l)

    lesson_to_join = None
    if today_lessons:
        next_lesson = today_lessons[0]
        topic = escape(next_lesson.get("topic") or "Занятие")
        subject = escape(next_lesson.get("subject") or "Информатика")
        starts_at = format_dt(next_lesson.get("starts_at"), tz_name)
        duration = next_lesson.get("duration", 60)
        lesson_to_join = next_lesson.get("lesson_url")
        st_id = next_lesson.get("student_id")
        st_info = ""
        if st_id:
            st_obj = db.session.get(Student, st_id)
            if st_obj:
                st_info = f" · Ученик: {escape(st_obj.name)}"

        text += (
            f"📅 <b>Ближайший урок сегодня:</b>\n"
            f"• <b>{topic}</b> ({subject})\n"
            f"  🕒 {starts_at} · {duration} мин{st_info}\n"
            f"• Всего уроков сегодня: <b>{len(today_lessons)}</b>\n\n"
        )
    elif future_lessons:
        next_lesson = future_lessons[0]
        topic = escape(next_lesson.get("topic") or "Занятие")
        subject = escape(next_lesson.get("subject") or "Информатика")
        starts_at = format_dt(next_lesson.get("starts_at"), tz_name)
        duration = next_lesson.get("duration", 60)
        lesson_to_join = next_lesson.get("lesson_url")
        st_id = next_lesson.get("student_id")
        st_info = ""
        if st_id:
            st_obj = db.session.get(Student, st_id)
            if st_obj:
                st_info = f" · Ученик: {escape(st_obj.name)}"

        text += (
            f"📅 <b>Ближайший урок:</b>\n"
            f"• <b>{topic}</b> ({subject})\n"
            f"  🕒 {starts_at} · {duration} мин{st_info}\n"
            f"• <i>(Сегодня уроков в расписании нет)</i>\n\n"
        )
    else:
        text += (
            "📅 <b>Занятия:</b>\n"
            "• <i>В ближайшие дни занятий в расписании нет</i>\n\n"
        )

    # 2. Review queue spotlight
    text += (
        f"📥 <b>Очередь проверки:</b>\n"
        f"• Работ ожидают проверки: <b>{today.pending_review_count}</b>\n"
    )
    oldest_sub_btn = None
    if today.oldest_submission:
        osub = today.oldest_submission
        st_name = escape(osub.get("student_name") or "Ученик")
        asg_title = escape(osub.get("assignment_title") or "Задание")
        wait_days = osub.get("wait_days", 0)
        wait_str = f"{wait_days} дн." if wait_days > 0 else "сегодня"
        text += f"• ⏳ Старейшая работа: <b>{st_name}</b> — «{asg_title}» (ждёт: <b>{wait_str}</b>)\n"
        oldest_sub_btn = (osub["submission_id"], osub.get("student_name", "Ученик")[:14], wait_days)
    elif today.pending_review_count > 0:
        oldest_sub = db.session.query(Submission).join(
            Assignment, Submission.assignment_id == Assignment.assignment_id
        ).filter(
            Assignment.created_by_id == user.id,
            Submission.status.in_(("SUBMITTED", "IN_REVIEW", "RETURNED")),
        ).order_by(Submission.submitted_at.asc()).first()
        if oldest_sub and oldest_sub.submitted_at:
            sub_utc = oldest_sub.submitted_at if oldest_sub.submitted_at.tzinfo else oldest_sub.submitted_at.replace(tzinfo=timezone.utc)
            wait_days = (now - sub_utc).days
            if wait_days > 0:
                text += f"• ⏳ Старейшая сдача ожидает: <b>{wait_days} дн.</b>\n"
            oldest_sub_btn = (oldest_sub.submission_id, oldest_sub.student.name[:14] if oldest_sub.student else "Ученик", wait_days)

    if today.overdue_count:
        text += f"• ⚠️ Заданий учеников с истёкшим дедлайном: <b>{today.overdue_count}</b>\n"

    # 3. Actionable Keyboard
    keyboard: list[list[InlineKeyboardButton]] = []
    if lesson_to_join:
        keyboard.append([InlineKeyboardButton("🎥 Войти в комнату ближайшего урока", url=lesson_to_join)])

    if oldest_sub_btn:
        s_id, s_name, w_days = oldest_sub_btn
        w_suffix = f" ({w_days}д)" if w_days > 0 else ""
        keyboard.append([
            InlineKeyboardButton(f"📥 Проверить: {s_name}{w_suffix}", callback_data=f"{CB_PREFIX}:{DOMAIN_TEACHER}:q_item:{s_id}:1")
        ])

    mini_app_btn = build_mini_app_button("📱 Открыть Mini App")
    if mini_app_btn:
        keyboard.append([mini_app_btn])

    keyboard.extend([
        [InlineKeyboardButton(f"📥 Очередь проверки ({today.pending_review_count})", callback_data=f"{CB_PREFIX}:{DOMAIN_TEACHER}:queue:1")],
        [InlineKeyboardButton("📅 Моё расписание на сегодня", callback_data=f"{CB_PREFIX}:{DOMAIN_TEACHER}:sch")],
        [InlineKeyboardButton("👥 Мои ученики", callback_data=f"{CB_PREFIX}:{DOMAIN_TEACHER}:st:1")],
        [
            InlineKeyboardButton("👥 Уведомления учеников", callback_data=f"{CB_PREFIX}:{DOMAIN_TEACHER}:st_notif:list"),
            InlineKeyboardButton("📢 Рассылка ученикам", callback_data=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:start"),
        ],
        [
            InlineKeyboardButton("⚙️ Настройки", callback_data=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:home"),
            InlineKeyboardButton("🔄 Обновить", callback_data=f"{CB_PREFIX}:{DOMAIN_NAV}:home"),
        ],
    ])

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_teacher_schedule(update: Update, user: User) -> None:
    """Render teacher's lessons today and upcoming."""
    today = build_today_view(user, "teacher")
    lessons = today.lessons
    tz_name = today.timezone

    text = f"{card_header('📅 Расписание уроков', 'Преподавательское расписание')}\n"
    keyboard: list[list[InlineKeyboardButton]] = []

    if not lessons:
        text += empty_state("📅", "Нет занятий на сегодня", "На сегодня уроков в расписании нет. Можно проверить сданные домашние работы учеников.")
    else:
        text += "Занятия на сегодня:\n\n"
        for idx, item in enumerate(lessons, 1):
            topic = escape(item.get("topic") or "Урок")
            subject = escape(item.get("subject") or "Информатика")
            when = format_dt(item.get("starts_at"), tz_name)
            duration = item.get("duration", 60)
            text += f"<b>{idx}. {topic}</b> ({subject})\n   🕒 {when} ({duration} мин)\n\n"

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

    if not can_teacher_review_submission(user, submission_id):
        text = f"{card_header('Доступ ограничен')}\n<i>У вас нет прав на просмотр этой сдачи или она уже проверена.</i>"
        keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_TEACHER}:queue:{return_page}")]
        await render_screen(update, text, InlineKeyboardMarkup(keyboard))
        return

    student = submission.student
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
        text += empty_state("👥", "Нет прикреплённых учеников", "У вас пока нет активных учеников в расписании платформы.")
    else:
        tz_name = getattr(user.profile, "timezone", "Europe/Moscow")
        for item in page_items:
            name = escape(item.get("name") or "Ученик")
            cat = escape(item.get("category") or "ЕГЭ")
            active_hw = item.get("active_assignments", 0)
            in_rev = item.get("in_review", 0)
            overdue = item.get("overdue_assignments", 0)
            sid = item.get("student_id")
            next_date = item.get("next_lesson_date")

            status_parts = []
            if overdue > 0:
                status_parts.append(f"⚠️ {overdue} просроч.")
            if in_rev > 0:
                status_parts.append(f"🟡 {in_rev} на проверке")
            if not status_parts:
                status_parts.append(f"🟢 В графике (ДЗ: {active_hw})")

            status_line = " · ".join(status_parts)
            lesson_line = f"📅 Урок: {format_dt(next_date, tz_name)}" if next_date else "📅 Уроков не запланировано"

            text += (
                f"• <b>{name}</b> ({cat})\n"
                f"  {status_line}\n"
                f"  {lesson_line}\n\n"
            )
            keyboard.append([InlineKeyboardButton(f"👤 {name}", callback_data=f"{CB_PREFIX}:{DOMAIN_TEACHER}:st_item:{sid}:{page}")])

    # Pagination row
    pag_row = build_pagination_row(DOMAIN_TEACHER, "st", page, total_pages)
    if pag_row:
        keyboard.append(pag_row)

    keyboard.append(build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_NAV}:home"))
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_teacher_student_card(update: Update, user: User, student_id: int, return_page: int = 1) -> None:
    """Render single student profile summary for teacher with multi-teacher isolation."""
    student = db.session.get(Student, student_id)
    allowed_students = _student_ids_for_context(user, "teacher")
    if not student or (student.student_id not in allowed_students and not (user.is_creator() or user.is_admin())):
        text = f"{card_header('Ученик не найден')}\n<i>Доступ к профилю ограничен или ученик не найден.</i>"
        keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_TEACHER}:st:{return_page}")]
        await render_screen(update, text, InlineKeyboardMarkup(keyboard))
        return

    name = escape(student.name)
    category = escape(getattr(student, "category", None) or "ЕГЭ")
    goal_text = escape(student.goal_text) if getattr(student, "goal_text", None) else None
    target_score = getattr(student, "target_score", None)

    tz_name = getattr(user.profile, "timezone", "Europe/Moscow")
    now = datetime.now(timezone.utc)

    # 1. Telegram connection status
    st_user = student.user
    st_prof = getattr(st_user, "profile", None) if st_user else None
    if st_prof and getattr(st_prof, "telegram_chat_id", None):
        tg_uname = getattr(st_prof, "telegram_username", None) or getattr(st_user, "telegram_username", None)
        tg_status = f"✅ Подключён (@{escape(tg_uname)})" if tg_uname else "✅ Подключён"
    else:
        tg_status = "⚠️ Не подключён к платформе"

    # 2. Upcoming lesson with THIS teacher
    cand_lessons = Lesson.query.filter(
        Lesson.student_id == student.student_id,
        Lesson.lesson_date.isnot(None),
        Lesson.lesson_date >= now - timedelta(hours=3),
        Lesson.status.notin_(('cancelled', 'completed')),
        or_(Lesson.teacher_id == user.id, Lesson.teacher_id.is_(None)),
    ).order_by(Lesson.lesson_date.asc()).all()
    next_lesson = None
    for cand in cand_lessons:
        st_utc = coerce_to_utc(cand.lesson_date)
        dur = int(cand.duration or 60)
        if st_utc and st_utc + timedelta(minutes=dur) >= now:
            next_lesson = cand
            break

    # 3. Last completed lesson with this teacher
    last_lesson = Lesson.query.filter(
        Lesson.student_id == student.student_id,
        Lesson.lesson_date.isnot(None),
        Lesson.lesson_date < now,
        or_(Lesson.teacher_id == user.id, Lesson.teacher_id.is_(None)),
    ).order_by(Lesson.lesson_date.desc()).first()

    # 4. Multi-teacher isolated homework breakdown
    sub_q = db.session.query(Submission, Assignment).join(
        Assignment, Submission.assignment_id == Assignment.assignment_id
    ).filter(
        Submission.student_id == student.student_id,
        Assignment.is_active.is_(True),
        or_(
            Assignment.created_by_id == user.id,
            Assignment.lesson_id.in_(
                db.session.query(Lesson.lesson_id).filter(Lesson.teacher_id == user.id)
            ),
        ),
    )
    submissions = sub_q.all()

    active_count = 0
    overdue_count = 0
    in_review_count = 0
    graded_count = 0
    latest_percentage = None

    for sub, asgn in submissions:
        st_val = str(sub.status or "").upper()
        dl = asgn.deadline
        if dl and dl.tzinfo is None:
            dl = dl.replace(tzinfo=timezone.utc)

        if st_val in {"ASSIGNED", "IN_PROGRESS"}:
            if dl and dl < now:
                overdue_count += 1
            else:
                active_count += 1
        elif st_val in {"SUBMITTED", "IN_REVIEW", "RETURNED"}:
            in_review_count += 1
        elif st_val in {"CHECKED", "GRADED", "COMPLETED"}:
            graded_count += 1
            if sub.percentage is not None and latest_percentage is None:
                latest_percentage = sub.percentage

    text = f"{card_header(f'👤 Карточка ученика · {name}', category)}\n"
    text += (
        f"<b>Ученик:</b> {name}\n"
        f"<b>Направление:</b> {category}\n"
        f"<b>Telegram:</b> {tg_status}\n"
    )
    if target_score:
        text += f"🎯 <b>Целевой балл:</b> {target_score}\n"
    elif goal_text:
        text += f"🎯 <b>Цель:</b> {goal_text}\n"

    # Lessons info
    text += "\n📅 <b>Занятия:</b>\n"
    if next_lesson:
        next_topic = escape(next_lesson.topic or "Занятие")
        next_dt = format_dt(next_lesson.lesson_date, tz_name)
        text += f"• Ближайший урок: <b>{next_topic}</b> ({next_dt})\n"
    else:
        text += "• Ближайших уроков не запланировано\n"

    if last_lesson:
        last_topic = escape(last_lesson.topic or "Занятие")
        last_dt = format_dt(last_lesson.lesson_date, tz_name)
        text += f"• Прошлый урок: {last_topic} ({last_dt})\n"

    # Homework breakdown
    text += (
        f"\n📝 <b>Домашние задания:</b>\n"
        f"• В работе: <b>{active_count}</b>\n"
    )
    if overdue_count:
        text += f"• ⚠️ Просрочено: <b>{overdue_count}</b>\n"
    text += (
        f"• На проверке: <b>{in_review_count}</b>\n"
        f"• Проверено работ: <b>{graded_count}</b>\n"
    )
    if latest_percentage is not None:
        text += f"• Последняя оценка: <b>{latest_percentage}%</b>\n"

    # Lessons balance if permitted
    if student.lessons_balance is not None:
        text += f"\n💳 <b>Баланс уроков:</b> {student.lessons_balance} зан.\n"

    keyboard: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(f"📝 Задания ({active_count + overdue_count})", callback_data=f"{CB_PREFIX}:{DOMAIN_TEACHER}:st_hw:{student_id}:1"),
            InlineKeyboardButton("📅 Расписание", callback_data=f"{CB_PREFIX}:{DOMAIN_TEACHER}:st_sch:{student_id}"),
        ]
    ]

    # Action buttons: Notifications inspection
    if student.user_id:
        keyboard.append([
            InlineKeyboardButton(
                "👥 Уведомления ученика",
                callback_data=f"{CB_PREFIX}:{DOMAIN_TEACHER}:st_notif:view:{student.user_id}",
            )
        ])

    from app.telegram import deep_links
    web_url = deep_links.student(student.student_id)
    if web_url and not is_localhost_url(web_url):
        keyboard.append([InlineKeyboardButton("💻 Открыть профиль на сайте", url=web_url)])

    keyboard.append(build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_TEACHER}:st:{return_page}"))

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_teacher_student_hw_list(update: Update, user: User, student_id: int, page: int = 1) -> None:
    """Render paginated homework assignments for a specific student."""
    allowed_students = _student_ids_for_context(user, "teacher")
    if student_id not in allowed_students and not (user.is_creator() or user.is_admin()):
        text = f"{card_header('Доступ ограничен')}\n<i>У вас нет доступа к домашним заданиям этого ученика.</i>"
        keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_TEACHER}:st:1")]
        await render_screen(update, text, InlineKeyboardMarkup(keyboard))
        return

    student = db.session.get(Student, student_id)
    name = escape(student.name if student else f"Ученик #{student_id}")
    tz_name = getattr(user.profile, "timezone", "Europe/Moscow")
    now = datetime.now(timezone.utc)

    sub_q = db.session.query(Submission, Assignment).join(
        Assignment, Submission.assignment_id == Assignment.assignment_id
    ).filter(
        Submission.student_id == student_id,
        Assignment.is_active.is_(True),
        or_(
            Assignment.created_by_id == user.id,
            Assignment.lesson_id.in_(
                db.session.query(Lesson.lesson_id).filter(Lesson.teacher_id == user.id)
            ),
        ),
    )
    submissions = sub_q.order_by(Assignment.deadline.asc().nullslast(), Submission.submission_id.desc()).all()

    total_count = len(submissions)
    total_pages = max(1, math.ceil(total_count / PAGE_SIZE_HW))
    page = max(1, min(page, total_pages))

    start = (page - 1) * PAGE_SIZE_HW
    page_items = submissions[start : start + PAGE_SIZE_HW]

    text = f"{card_header(f'📝 Задания · {name}', f'Всего заданий: {total_count}')}\n"
    keyboard: list[list[InlineKeyboardButton]] = []

    if not page_items:
        text += empty_state("📝", "Нет заданий", "Для этого ученика пока нет назначенных домашних заданий.")
    else:
        for sub, asg in page_items:
            title = escape(asg.title)
            st_val = str(sub.status or "ASSIGNED").upper()
            dl_utc = coerce_to_utc(asg.deadline)
            dl_str = format_dt(dl_utc, tz_name, relative=False) if dl_utc else "бессрочно"

            if st_val in {"CHECKED", "GRADED", "COMPLETED"}:
                badge = f"🟢 Сдано ({sub.percentage:.0f}%)" if sub.percentage is not None else "🟢 Сдано"
            elif st_val in {"SUBMITTED", "IN_REVIEW"}:
                badge = "🟡 На проверке"
            elif dl_utc and dl_utc < now:
                badge = "⚠️ Просрочено"
            else:
                badge = "⚪ В работе"

            text += (
                f"• <b>{title}</b>\n"
                f"  Статус: {badge} | Дедлайн: {dl_str}\n\n"
            )

    pag_row = build_pagination_row(DOMAIN_TEACHER, f"st_hw:{student_id}", page, total_pages)
    if pag_row:
        keyboard.append(pag_row)

    keyboard.append(build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_TEACHER}:st_item:{student_id}:1"))
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_teacher_student_schedule(update: Update, user: User, student_id: int) -> None:
    """Render upcoming lessons for a specific student with this teacher."""
    allowed_students = _student_ids_for_context(user, "teacher")
    if student_id not in allowed_students and not (user.is_creator() or user.is_admin()):
        text = f"{card_header('Доступ ограничен')}\n<i>У вас нет доступа к расписанию этого ученика.</i>"
        keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_TEACHER}:st:1")]
        await render_screen(update, text, InlineKeyboardMarkup(keyboard))
        return

    student = db.session.get(Student, student_id)
    name = escape(student.name if student else f"Ученик #{student_id}")
    tz_name = getattr(user.profile, "timezone", "Europe/Moscow")
    now = datetime.now(timezone.utc)

    raw_lessons = Lesson.query.filter(
        Lesson.student_id == student_id,
        Lesson.lesson_date.isnot(None),
        Lesson.lesson_date >= now - timedelta(hours=3),
        Lesson.status.notin_(("cancelled", "completed")),
        or_(Lesson.teacher_id == user.id, Lesson.teacher_id.is_(None)),
    ).order_by(Lesson.lesson_date.asc()).limit(15).all()

    lessons = []
    for l in raw_lessons:
        st_utc = coerce_to_utc(l.lesson_date)
        dur = int(l.duration or 60)
        if st_utc and st_utc + timedelta(minutes=dur) >= now:
            lessons.append(l)
    lessons = lessons[:10]

    text = f"{card_header(f'📅 Расписание · {name}', 'Ближайшие занятия')}\n"
    keyboard: list[list[InlineKeyboardButton]] = []

    if not lessons:
        text += empty_state("📅", "Нет запланированных занятий", "Ученику пока не назначены ближайшие уроки в расписании.")
    else:
        text += "Список ближайших уроков:\n\n"
        for idx, l in enumerate(lessons, 1):
            topic = escape(l.topic or "Занятие")
            subject = escape(l.subject or "Информатика")
            when = format_dt(l.lesson_date, tz_name)
            duration = l.duration or 60
            text += f"<b>{idx}. {topic}</b> ({subject})\n   🕒 {when} ({duration} мин)\n\n"
            from app.telegram import deep_links
            l_url = deep_links.lesson(l.lesson_id)
            if l_url and idx <= 2:
                keyboard.append([InlineKeyboardButton(f"🎥 Войти: {topic[:25]}", url=l_url)])

    keyboard.append(build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_TEACHER}:st_item:{student_id}:1"))
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))
