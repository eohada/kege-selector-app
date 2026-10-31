"""Creator management screens for BooStudy Bot V3."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

from app.models import User
from app.telegram.application import build_operational_summary
from app.telegram.v3.constants import (
    CB_PREFIX,
    DOMAIN_ADMIN,
    DOMAIN_CREATOR,
    DOMAIN_NAV,
    DOMAIN_SETTINGS,
    DOMAIN_STUDENT,
    DOMAIN_TEACHER,
)
from app.telegram.v3.identity import get_display_name
from app.telegram.v3.ui import build_mini_app_button, card_header, escape, build_nav_row, render_screen


def _is_creator(user: User) -> bool:
    actual = {str(r).lower() for r in (user.roles() if hasattr(user, "roles") else [user.role])}
    return "creator" in actual


async def show_creator_home(update: Update, user: User) -> None:
    """Render Creator executive overview and switcher."""
    if not _is_creator(user):
        text = f"{card_header('Доступ ограничен')}\n<i>Раздел доступен только Создателю платформы.</i>"
        keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_NAV}:home")]
        await render_screen(update, text, InlineKeyboardMarkup(keyboard))
        return

    name = escape(get_display_name(user))
    mode = str(getattr(user, "creator_bot_mode", "ADMIN")).upper()
    is_teacher_mode = mode == "TEACHER"

    summary = build_operational_summary(user)

    text = f"{card_header(f'👑 Кабинет Создателя · {name}', 'Управление платформой BooStudy')}\n"

    if is_teacher_mode:
        text += (
            "🎯 <b>Текущий рабочий режим:</b> 👨‍🏫 <b>Преподаватель</b>\n"
            "<i>Бот оптимизирован под ведение уроков и проверку заданий.</i>\n\n"
        )
    else:
        text += (
            "🎯 <b>Текущий рабочий режим:</b> 👑 <b>Создатель платформы</b>\n"
            "<i>Полный доступ ко всем подсистемам, администрированию и метрикам.</i>\n\n"
        )

    if summary:
        text += (
            f"📊 <b>Живые показатели BooStudy:</b>\n"
            f"• Всего пользователей: <b>{summary.users}</b>\n"
            f"• Учеников: <b>{summary.active_students}</b> | Учителей: <b>{summary.active_teachers}</b>\n"
            f"• Заданий на проверке: <b>{summary.pending_reviews}</b>\n"
            f"• Открытых обращений: <b>{summary.open_bug_reports}</b>\n"
        )
        if summary.failed_deliveries:
            text += f"• ⚠️ Ошибок очереди сообщений: <b>{summary.failed_deliveries}</b>\n"
        text += "\n"

    toggle_btn_title = (
        "🔄 Переключить в режим Создателя" if is_teacher_mode else "🔄 Переключить в режим Преподавателя"
    )

    keyboard: list[list[InlineKeyboardButton]] = []
    mini_app_btn = build_mini_app_button("📱 Открыть Mini App")
    if mini_app_btn:
        keyboard.append([mini_app_btn])

    keyboard.extend([
        [InlineKeyboardButton(toggle_btn_title, callback_data=f"{CB_PREFIX}:{DOMAIN_CREATOR}:toggle_mode")],
        [
            InlineKeyboardButton("👨‍🏫 Преподавательская", callback_data=f"{CB_PREFIX}:{DOMAIN_TEACHER}:home"),
            InlineKeyboardButton("🎓 Кабинет Ученика", callback_data=f"{CB_PREFIX}:{DOMAIN_STUDENT}:home"),
        ],
        [
            InlineKeyboardButton("⚙️ Админ-панель", callback_data=f"{CB_PREFIX}:{DOMAIN_ADMIN}:home"),
            InlineKeyboardButton("👥 Пользователи", callback_data=f"{CB_PREFIX}:{DOMAIN_ADMIN}:u:1:all"),
        ],
        [
            InlineKeyboardButton("⚙️ Настройки", callback_data=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:home"),
            InlineKeyboardButton("🔄 Обновить", callback_data=f"{CB_PREFIX}:{DOMAIN_NAV}:home"),
        ],
    ])

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))
