"""Parent screens for BooStudy Bot V3."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

from app.models import db, User, Student
from app.telegram.application import (
    build_parent_children,
    build_parent_schedule,
    build_parent_digest,
)
from app.telegram.v3.constants import CB_PREFIX, DOMAIN_NAV, DOMAIN_PARENT, DOMAIN_SETTINGS
from app.telegram.v3.identity import get_display_name
from app.telegram.v3.ui import (
    card_header,
    empty_state,
    escape,
    format_dt,
    build_mini_app_button,
    build_nav_row,
    render_screen,
)


async def show_parent_home(update: Update, user: User) -> None:
    """Render the Parent Home dashboard."""
    children = build_parent_children(user)
    name = escape(get_display_name(user))
    tz_name = getattr(user.profile, "timezone", "Europe/Moscow")

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


async def show_parent_child_view(update: Update, user: User, student_id: int) -> None:
    """Render specific child's overview card."""
    children = build_parent_children(user)
    target = next((c for c in children if c.student_id == student_id), None)

    if not target:
        text = f"{card_header('Доступ ограничен')}\n<i>Профиль ученика не найден среди ваших привязанных детей.</i>"
        keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_PARENT}:home")]
        await render_screen(update, text, InlineKeyboardMarkup(keyboard))
        return

    tz_name = getattr(user.profile, "timezone", "Europe/Moscow")
    cname = escape(target.name)
    next_l = target.next_lesson
    lesson_str = format_dt(next_l.get("starts_at"), tz_name) if next_l else "Занятий на ближайшие дни нет"

    text = (
        f"{card_header(f'👧 Ученик: {cname}', 'Учебная активность ребёнка')}\n"
        f"📅 <b>Ближайший урок:</b>\n"
        f"• {lesson_str}\n\n"
        f"📝 <b>Домашние задания:</b>\n"
        f"• В процессе выполнения: <b>{target.active_assignments}</b>\n"
        f"• Просроченных: <b>{target.overdue_assignments}</b>\n\n"
    )

    if target.latest_result_percent is not None:
        text += f"📊 <b>Последняя оценка за проверенную работу:</b> <b>{target.latest_result_percent:.0f}%</b>\n\n"

    keyboard: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton("📅 Расписание занятий", callback_data=f"{CB_PREFIX}:{DOMAIN_PARENT}:sch:{student_id}")],
        [InlineKeyboardButton("📊 Учебный дайджест", callback_data=f"{CB_PREFIX}:{DOMAIN_PARENT}:dig:{student_id}")],
        build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_PARENT}:home"),
    ]

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_parent_child_schedule(update: Update, user: User, student_id: int) -> None:
    """Render child's upcoming lessons."""
    children = build_parent_children(user)
    target = next((c for c in children if c.student_id == student_id), None)
    if not target:
        text = f"{card_header('Доступ ограничен')}\n<i>Профиль ученика не найден среди ваших привязанных детей.</i>"
        keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_PARENT}:home")]
        await render_screen(update, text, InlineKeyboardMarkup(keyboard))
        return

    all_sch = build_parent_schedule(user, limit=10) or ()
    child_sch = [item for item in all_sch if item.get("student_id") == student_id]
    tz_name = getattr(user.profile, "timezone", "Europe/Moscow")

    cname = escape(target.name)

    text = f"{card_header(f'📅 Расписание · {cname}', 'Ближайшие уроки')}\n"

    if not child_sch:
        text += empty_state("🎉", "Нет ближайших уроков", "Уроки на ближайшие дни не запланированы.")
    else:
        text += "Список ближайших уроков:\n\n"
        for idx, item in enumerate(child_sch, 1):
            topic = escape(item.get("topic") or "Занятие")
            when = format_dt(item.get("starts_at"), tz_name)
            duration = item.get("duration", 60)
            text += f"<b>{idx}. {topic}</b>\n   🕒 {when} ({duration} мин)\n\n"

    keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_PARENT}:ch:{student_id}")]
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_parent_child_digest(update: Update, user: User, student_id: int) -> None:
    """Render weekly learning digest for child."""
    children = build_parent_children(user)
    target = next((c for c in children if c.student_id == student_id), None)
    if not target:
        text = f"{card_header('Доступ ограничен')}\n<i>Профиль ученика не найден среди ваших привязанных детей.</i>"
        keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_PARENT}:home")]
        await render_screen(update, text, InlineKeyboardMarkup(keyboard))
        return

    digest = build_parent_digest(user, student_id)
    cname = escape(target.name)

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
