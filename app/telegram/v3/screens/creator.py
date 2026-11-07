"""Creator management screens for BooStudy Bot V3."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

from app.models import User
from app.telegram.application import build_operational_summary
from app.telegram.v3.constants import (
    CB_PREFIX,
    DOMAIN_ADMIN,
    DOMAIN_BROADCAST,
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
    uname = escape(user.username or f"user_{user.id}")
    mode = str(getattr(user, "creator_bot_mode", "ADMIN")).upper()
    is_teacher_mode = mode == "TEACHER"

    summary = build_operational_summary(user)

    mode_title = "👨‍🏫 Преподаватель" if is_teacher_mode else "👑 Создатель"
    text = (
        f"{card_header('👑 Кабинет Создателя платформы', f'Пользователь: {uname}')}\n"
        f"🎯 <b>Текущий рабочий режим:</b> <b>{mode_title}</b> (по умолчанию при /start)\n"
        f"<i>(При вызове /start бот сразу открывает {mode_title.lower()})</i>\n\n"
    )

    quick_alert_buttons: list[InlineKeyboardButton] = []
    if summary:
        text += (
            f"📊 <b>Общеплатформенная сводка BooStudy (все пользователи):</b>\n"
            f"• Пользователей: <b>{summary.users}</b> (учеников: {summary.active_students}, учителей: {summary.active_teachers})\n"
            f"• Заданий на проверке у учителей: <b>{summary.pending_reviews}</b>"
        )
        if summary.oldest_review_wait_days > 0:
            text += f" (макс. задержка: <b>{summary.oldest_review_wait_days} дн.</b>)"
        text += f"\n• Открытых обращений и багов: <b>{summary.open_bug_reports}</b>"
        if summary.critical_bugs_count > 0:
            text += f" (⚠️ критичных: <b>{summary.critical_bugs_count}</b>)"
        text += f"\n• Доставок Outbox: отправлено <b>{summary.sent_deliveries}</b>"
        if summary.failed_deliveries > 0:
            text += f" | ⚠️ <b>сбоев: {summary.failed_deliveries}</b>"
        text += "\n\n"

        if summary.failed_deliveries > 0:
            quick_alert_buttons.append(InlineKeyboardButton(f"⚠️ Сбои Outbox ({summary.failed_deliveries})", callback_data=f"{CB_PREFIX}:{DOMAIN_ADMIN}:deliveries:1"))
        if summary.critical_bugs_count > 0:
            quick_alert_buttons.append(InlineKeyboardButton(f"🐞 Критичные баги ({summary.critical_bugs_count})", callback_data=f"{CB_PREFIX}:{DOMAIN_ADMIN}:probs"))

    toggle_btn_title = (
        "🔄 Сменить дефолт /start на Создатель" if is_teacher_mode else "🔄 Сменить дефолт /start на Преподаватель"
    )

    keyboard: list[list[InlineKeyboardButton]] = []
    if quick_alert_buttons:
        keyboard.append(quick_alert_buttons)

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
            InlineKeyboardButton("🛡️ Аудит уведомлений", callback_data=f"{CB_PREFIX}:{DOMAIN_ADMIN}:notif:hub"),
            InlineKeyboardButton("📢 Центр рассылок", callback_data=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:start"),
        ],
        [
            InlineKeyboardButton("⚙️ Настройки", callback_data=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:home"),
            InlineKeyboardButton("🔄 Обновить", callback_data=f"{CB_PREFIX}:{DOMAIN_NAV}:home"),
        ],
    ])

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))
