"""Teacher inspection screen for student notification settings and dynamic comparison mode."""
from __future__ import annotations

import logging
import math
from typing import Any
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

from app.models import db, User, Student
from app.utils.relationship_scope import teacher_has_student, get_student_user_ids_for_tutor
from app.telegram.application import build_teacher_students
from app.telegram.config import ALLOWLIST_CHAT_IDS
from app.telegram.registry import (
    CATEGORY_TITLES,
    NotificationCategory,
    NotificationTypeRegistry,
)
from app.telegram.user_notify import (
    get_user_notification_preference,
    is_notification_enabled_for_user,
)
from app.telegram.v3.constants import (
    CB_PREFIX,
    DOMAIN_TEACHER,
    DOMAIN_NAV,
    DOMAIN_PREVIEW,
    PAGE_SIZE_STUDENTS,
)
from app.telegram.v3.identity import get_display_name
from app.telegram.v3.ui import build_nav_row, build_pagination_row, card_header, escape, render_screen

logger = logging.getLogger(__name__)

COMPARISON_EVENTS = [
    ("lesson_scheduled", "📅 Назначение урока"),
    ("lesson_rescheduled", "🔄 Перенос времени"),
    ("lesson_cancelled", "❌ Отмена урока"),
    ("lesson_reminder", "⏰ Напоминание"),
    ("assignment_assigned", "📝 Новое задание"),
    ("homework_submitted", "📥 Сдача работы"),
    ("assignment_graded", "⭐ Проверка ДЗ"),
    ("lesson_comment", "💬 Комментарий"),
]


def _is_teacher_authorized(user: User) -> bool:
    role = getattr(user, "role", "") or ""
    return role.lower() in ("teacher", "tutor", "creator", "chief_admin", "admin")


async def show_teacher_students_list(update: Update, user: User, page: int = 1) -> None:
    """Render paginated list of confirmed students linked to this teacher, unified with Teacher cabinet."""
    if not _is_teacher_authorized(user):
        await render_screen(
            update,
            "🚫 <b>Доступ ограничен</b>\n\nЭтот раздел предназначен только для преподавателей BooStudy.",
            InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Главное меню", callback_data=f"{CB_PREFIX}:{DOMAIN_NAV}:home")]]),
        )
        return

    # Use the same unified student resolver as Teacher Home
    all_students = build_teacher_students(user, limit=50)

    total_count = len(all_students)
    total_pages = max(1, math.ceil(total_count / PAGE_SIZE_STUDENTS))
    page = max(1, min(page, total_pages))

    start = (page - 1) * PAGE_SIZE_STUDENTS
    page_items = all_students[start : start + PAGE_SIZE_STUDENTS]

    text = (
        f"{card_header('👥 Уведомления учеников', f'Всего в кабинете: {total_count}')}\n"
        "Здесь вы можете проверить каналы связи ваших учеников, статус доставки сообщений, "
        "а также рассчитать сценарий <b>«Что получу я / Что получит ученик»</b>.\n\n"
        "<b>Выберите ученика для аудита:</b>"
    )

    keyboard: list[list[InlineKeyboardButton]] = []

    if not page_items:
        text += "\n\n<i>У вас пока нет прикреплённых учеников с активными связями.</i>"
    else:
        for item in page_items:
            name = escape(item.get("name") or "Ученик")
            suid = item.get("user_id")
            sid = item.get("student_id")

            if suid:
                st_user = User.query.get(suid)
                st_prof = getattr(st_user, "profile", None) if st_user else None
                tg_badge = "✅ TG" if (st_prof and st_prof.telegram_chat_id) else "⚪ Нет TG"
                btn_label = f"🎓 {name} ({tg_badge})"
                keyboard.append([
                    InlineKeyboardButton(
                        btn_label,
                        callback_data=f"{CB_PREFIX}:{DOMAIN_TEACHER}:st_notif:view:{suid}",
                    )
                ])
            else:
                keyboard.append([
                    InlineKeyboardButton(
                        f"🎓 {name} (аккаунт не привязан)",
                        callback_data=f"{CB_PREFIX}:{DOMAIN_TEACHER}:st_item:{sid}:1",
                    )
                ])

    # Pagination row
    pag_row = build_pagination_row(DOMAIN_TEACHER, "st_notif:list", page, total_pages)
    if pag_row:
        keyboard.append(pag_row)

    keyboard.append(build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_TEACHER}:home"))
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_student_notification_details(update: Update, teacher: User, student_user_id: int) -> None:
    """Show audit view of student's notifications with strict RBAC security check."""
    if not _is_teacher_authorized(teacher):
        await render_screen(
            update,
            "🚫 <b>Доступ ограничен</b>",
            InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data=f"{CB_PREFIX}:{DOMAIN_NAV}:home")]]),
        )
        return

    # Strict RBAC enforcement: verify teacher_has_student relationship
    is_creator = getattr(teacher, "role", "") in ("creator", "chief_admin")
    if not is_creator and not teacher_has_student(teacher.id, student_user_id):
        logger.warning(
            "Access violation attempt: teacher_id=%s tried to inspect student_id=%s without confirmed tie",
            teacher.id,
            student_user_id,
        )
        await render_screen(
            update,
            "🚫 <b>Ошибка доступа (403 Forbidden)</b>\n\n"
            "Вы можете просматривать настройки только своих подтверждённых учеников.\n"
            "Этот ученик не прикреплён к вашему преподавательскому кабинету.",
            InlineKeyboardMarkup([[InlineKeyboardButton("◀️ К списку учеников", callback_data=f"{CB_PREFIX}:{DOMAIN_TEACHER}:st_notif:list:1")]]),
        )
        return

    st_user = User.query.get(student_user_id)
    if not st_user:
        await render_screen(
            update,
            "❌ <b>Ученик не найден</b>",
            InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data=f"{CB_PREFIX}:{DOMAIN_TEACHER}:st_notif:list:1")]]),
        )
        return

    st_name = escape(get_display_name(st_user))
    st_prof = getattr(st_user, "profile", None)
    tg_connected = bool(st_prof and st_prof.telegram_chat_id)
    notif_enabled = bool(st_prof and st_prof.telegram_notifications_enabled)

    categories = NotificationTypeRegistry.list_categories_for_role("student")

    text_lines = [
        card_header(f"🎓 Уведомления: {st_name}", "Статус доставки и каналы связи"),
        f"<b>Telegram подключён:</b> {'✅ Да' if tg_connected else '❌ Нет'}",
        f"<b>Общий переключатель:</b> {'✅ Включён' if notif_enabled else '❌ Отключён'}",
        "",
    ]

    if not tg_connected:
        text_lines.append(
            "⚠️ <b>Внимание:</b> Ученик ещё не привязал Telegram-аккаунт к платформе BooStudy.\n"
            "Настройки сохранены в профиле, но реальная отправка сообщений невозможна до подключения.\n"
        )

    text_lines.append("<b>Статус по категориям:</b>")
    for cat in categories:
        cat_title = CATEGORY_TITLES.get(cat, cat.capitalize())
        items = NotificationTypeRegistry.list_for_role_and_category("student", cat)
        total = len(items)
        enabled = sum(1 for itm in items if is_notification_enabled_for_user(student_user_id, "student", itm.kind))
        text_lines.append(f"• <b>{cat_title}:</b> {enabled} из {total} разрешено")

    text_lines.append("\n<i>💡 Преподаватель может просматривать статус каналов связи для контроля доходимости информации до ученика.</i>")

    keyboard = [
        [InlineKeyboardButton("⚖️ Сравнить доставку «Я / Ученик»", callback_data=f"{CB_PREFIX}:{DOMAIN_TEACHER}:st_notif:cmp:{student_user_id}:lesson_scheduled")],
        build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_TEACHER}:st_notif:list:1"),
    ]

    await render_screen(update, "\n".join(text_lines), InlineKeyboardMarkup(keyboard))


def evaluate_delivery_for_comparison(
    teacher: User,
    student_user_id: int,
    event_kind: str,
) -> tuple[str, str, str]:
    """Dynamically evaluate notification policy for both Teacher and Student.

    Returns: (event_title, teacher_verdict, student_verdict)
    """
    defn = NotificationTypeRegistry.get(event_kind)
    event_title = defn.title if defn else event_kind

    if hasattr(student_user_id, "user_id"):
        st_user = db.session.get(User, student_user_id.user_id) if student_user_id.user_id else None
    elif isinstance(student_user_id, User):
        st_user = student_user_id
    else:
        st_user = db.session.get(User, student_user_id)
    st_prof = getattr(st_user, "profile", None) if st_user else None
    tch_prof = getattr(teacher, "profile", None)

    tch_tg = bool(tch_prof and tch_prof.telegram_chat_id)
    st_tg = bool(st_prof and st_prof.telegram_chat_id)

    # Scenarios based on event kind
    if event_kind in ("lesson_scheduled", "lesson_rescheduled", "lesson_cancelled"):
        # Teacher is actor
        teacher_verdict = (
            "⚪ <b>Подавлено (автор действия):</b>\n"
            "Вы создали или изменили урок. Telegram-сообщение автору действия не отправляется, "
            "чтобы не засорять чат собственными действиями."
        )
        if not st_tg:
            student_verdict = (
                "❌ <b>Доставка невозможна:</b>\n"
                "Ученик не подключил Telegram. Событие отобразится только в личном кабинете на сайте."
            )
        elif not getattr(st_prof, "telegram_notifications_enabled", True):
            student_verdict = (
                "⚪ <b>Отключено учеником:</b>\n"
                "Общий тумблер Telegram-уведомлений выключен в профиле ученика."
            )
        elif not is_notification_enabled_for_user(student_user_id, "student", event_kind):
            student_verdict = (
                "⚪ <b>Отключено учеником:</b>\n"
                "Ученик отключил данный тип уведомлений в персональных настройках расписания."
            )
        else:
            student_verdict = (
                "✅ <b>Будет доставлено:</b>\n"
                "Ученик получит карточку урока с датой, временем, преподавателем и кнопкой входа в комнату."
            )

    elif event_kind == "homework_submitted":
        # Student is actor
        student_verdict = (
            "⚪ <b>Подавлено (автор действия):</b>\n"
            "Ученик видит подтверждение сдачи в интерфейсе платформы. Эхо-сообщение в Telegram не отправляется."
        )
        if not tch_tg:
            teacher_verdict = (
                "❌ <b>Доставка невозможна:</b>\n"
                "Ваш Telegram не привязан к аккаунту BooStudy."
            )
        elif not is_notification_enabled_for_user(teacher.id, "teacher", "teacher_homework_submitted"):
            teacher_verdict = (
                "⚪ <b>Отключено в ваших настройках:</b>\n"
                "Вы выключили уведомления о сдаче работ в настройках преподавателя."
            )
        else:
            teacher_verdict = (
                "✅ <b>Будет доставлено:</b>\n"
                "Вы получите карточку сдачи с именем ученика, названием работы и кнопкой перехода к проверке."
            )

    elif event_kind in ("assignment_assigned", "assignment_graded"):
        # Teacher is actor
        teacher_verdict = (
            "⚪ <b>Подавлено (автор действия):</b>\n"
            "Вы назначили или проверили задание на платформе. Эхо-сообщение автору не дублируется."
        )
        if not st_tg:
            student_verdict = (
                "❌ <b>Доставка невозможна:</b>\n"
                "Ученик не подключил Telegram. Результат проверки доступен на сайте."
            )
        elif not is_notification_enabled_for_user(student_user_id, "student", event_kind):
            student_verdict = (
                "⚪ <b>Отключено учеником:</b>\n"
                "Ученик выключил уведомления о домашних заданиях в своих настройках."
            )
        else:
            action_desc = "новое домашнее задание с дедлайном" if event_kind == "assignment_assigned" else "оценку, комментарий учителя и ссылку на разбор"
            student_verdict = (
                f"✅ <b>Будет доставлено:</b>\n"
                f"Ученик получит карточку в Telegram с информацией про {action_desc}."
            )

    elif event_kind == "lesson_reminder":
        # System scheduled
        if not tch_tg:
            teacher_verdict = "❌ Ваш Telegram не подключён к платформе."
        elif not is_notification_enabled_for_user(teacher.id, "teacher", "lesson_reminder"):
            teacher_verdict = "⚪ Вы отключили напоминания перед уроком в настройках."
        else:
            teacher_verdict = "✅ Вы получите напоминание за 1 час и за 15 минут до начала занятия."

        if not st_tg:
            student_verdict = "❌ Ученик не подключил Telegram к платформе."
        elif not is_notification_enabled_for_user(student_user_id, "student", "lesson_reminder"):
            student_verdict = "⚪ Ученик отключил напоминания в своих настройках."
        else:
            student_verdict = "✅ Ученик получит напоминание перед уроком со ссылкой на онлайн-класс."

    else:  # lesson_comment or generic
        teacher_verdict = "✅ Уведомление поступит, если комментарий оставит ученик (и подавится, если вы автор)."
        if not st_tg:
            student_verdict = "❌ Telegram не подключён у ученика."
        else:
            student_verdict = "✅ Ученик получит оповещение о вашем комментарии в Telegram."

    return event_title, teacher_verdict, student_verdict


async def show_delivery_comparison_mode(
    update: Update,
    teacher: User,
    student_user_id: int,
    event_kind: str | None = None,
) -> None:
    """Render dynamic side-by-side comparison explaining what teacher vs student receives."""
    cur_event = event_kind or "lesson_scheduled"

    st_user = User.query.get(student_user_id)
    st_name = escape(get_display_name(st_user)) if st_user else "Ученик"

    event_title, tch_verdict, st_verdict = evaluate_delivery_for_comparison(
        teacher, student_user_id, cur_event
    )

    text = (
        f"{card_header('⚖️ Сравнение доставки: Я / Ученик', f'Ученик: {st_name}')}\n"
        f"<b>Анализируемое событие:</b> <b>{escape(event_title)}</b>\n\n"
        f"👨‍🏫 <b>Преподаватель (Вы):</b>\n{tch_verdict}\n\n"
        f"🎓 <b>Ученик ({st_name}):</b>\n{st_verdict}\n\n"
        "<i>💡 Расчёт выполнен на основе действующих настроек аккаунтов платформы BooStudy.</i>"
    )

    # Event selector buttons
    keyboard: list[list[InlineKeyboardButton]] = []

    # Quick selector row with common events
    sel_rows: list[InlineKeyboardButton] = []
    for ek, elabel in COMPARISON_EVENTS[:4]:
        short_lbl = elabel.split()[0] + " " + elabel.split()[1] if len(elabel.split()) > 1 else elabel
        if ek == cur_event:
            sel_rows.append(InlineKeyboardButton(f"• {short_lbl} •", callback_data=f"{CB_PREFIX}:{DOMAIN_TEACHER}:st_notif:cmp:{student_user_id}:{ek}"))
        else:
            sel_rows.append(InlineKeyboardButton(short_lbl, callback_data=f"{CB_PREFIX}:{DOMAIN_TEACHER}:st_notif:cmp:{student_user_id}:{ek}"))
    keyboard.append(sel_rows)

    sel_rows_2: list[InlineKeyboardButton] = []
    for ek, elabel in COMPARISON_EVENTS[4:]:
        short_lbl = elabel.split()[0] + " " + elabel.split()[1] if len(elabel.split()) > 1 else elabel
        if ek == cur_event:
            sel_rows_2.append(InlineKeyboardButton(f"• {short_lbl} •", callback_data=f"{CB_PREFIX}:{DOMAIN_TEACHER}:st_notif:cmp:{student_user_id}:{ek}"))
        else:
            sel_rows_2.append(InlineKeyboardButton(short_lbl, callback_data=f"{CB_PREFIX}:{DOMAIN_TEACHER}:st_notif:cmp:{student_user_id}:{ek}"))
    keyboard.append(sel_rows_2)

    # Preview sample button
    prev_cb = f"{CB_PREFIX}:{DOMAIN_PREVIEW}:student:{cur_event}"
    keyboard.append([
        InlineKeyboardButton("👁️ Посмотреть образец карточки ученика", callback_data=prev_cb)
    ])

    keyboard.append(build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_TEACHER}:st_notif:view:{student_user_id}"))

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))
