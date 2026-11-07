"""Administrative policy audit, role overview, and user notification inspection screen."""
from __future__ import annotations

import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

from app.models import db, User, UserProfile
from app.telegram.registry import (
    CATEGORY_TITLES,
    NotificationTypeRegistry,
)
from app.telegram.user_notify import (
    get_user_notification_preference,
    is_notification_enabled_for_user,
)
from app.telegram.v3.constants import (
    CB_PREFIX,
    DOMAIN_ADMIN,
    DOMAIN_NAV,
    ROLE_EMOJIS,
    ROLE_TITLES,
)
from app.telegram.v3.identity import get_display_name
from app.telegram.v3.ui import build_nav_row, card_header, escape, render_screen

logger = logging.getLogger(__name__)


def _is_admin_authorized(user: User) -> bool:
    role = getattr(user, "role", "") or ""
    return role.lower() in ("creator", "chief_admin", "admin")


async def show_admin_notifications_hub(update: Update, user: User) -> None:
    """Render administrative notification audit dashboard."""
    if not _is_admin_authorized(user):
        await render_screen(
            update,
            "🚫 <b>Доступ ограничен</b>\n\nРаздел доступен только администрации платформы BooStudy.",
            InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Главное меню", callback_data=f"{CB_PREFIX}:{DOMAIN_NAV}:home")]]),
        )
        return

    text = (
        f"{card_header('🛡️ Аудит уведомлений', 'Административный центр')}\n"
        "Инструмент контроля политик доставки, системных настроек и инспекции пользователей:\n\n"
        "• <b>Обзор по ролям:</b> просмотр системных дефолтов и матрицы прав.\n"
        "• <b>Инспекция пользователя:</b> проверка персональных настроек конкретного пользователя "
        "с определением источника <i>(По умолчанию / Личный выбор / Блокировка)</i>."
    )

    keyboard = [
        [InlineKeyboardButton("📊 Обзор системных настроек по ролям", callback_data=f"{CB_PREFIX}:{DOMAIN_ADMIN}:notif:roles")],
        [InlineKeyboardButton("🔍 Инспекция настроек пользователя", callback_data=f"{CB_PREFIX}:{DOMAIN_ADMIN}:notif:users")],
        build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_NAV}:home"),
    ]

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_admin_roles_overview(update: Update, user: User) -> None:
    """List roles for policy inspection."""
    if not _is_admin_authorized(user):
        return

    text = (
        f"{card_header('📊 Обзор политик по ролям', 'Системные правила')}\n"
        "Выберите роль для просмотра зарегистрированных типов уведомлений и их стандартных статусов:"
    )

    roles = ("student", "teacher", "parent", "admin", "creator")
    keyboard: list[list[InlineKeyboardButton]] = []

    for r in roles:
        r_title = ROLE_TITLES.get(r, r.capitalize())
        r_emoji = ROLE_EMOJIS.get(r, "👤")
        items = NotificationTypeRegistry.list_for_role(r)
        keyboard.append([
            InlineKeyboardButton(
                f"{r_emoji} {r_title} ({len(items)} типов)",
                callback_data=f"{CB_PREFIX}:{DOMAIN_ADMIN}:notif:role_view:{r}",
            )
        ])

    keyboard.append(build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_ADMIN}:notif:hub"))
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_admin_role_policy_detail(update: Update, user: User, role: str) -> None:
    """Show detailed matrix for a single role."""
    role_norm = str(role).lower().strip()
    r_title = ROLE_TITLES.get(role_norm, role_norm.capitalize())
    r_emoji = ROLE_EMOJIS.get(role_norm, "👤")

    items = NotificationTypeRegistry.list_for_role(role_norm)

    lines = [
        card_header(f"{r_emoji} Политики роли: {r_title}", f"Всего типов: {len(items)}"),
        "<b>Матрица доставки по умолчанию:</b>",
    ]

    for item in items:
        def_on = item.is_enabled_by_default(role_norm)
        icon = "✅" if def_on else "❌"
        lock = " 🔒" if not item.allow_opt_out else ""
        lines.append(f"• {icon} <b>{escape(item.title)}</b>{lock} (<code>{item.kind}</code>)")

    lines.append("\n<i>🔒 = Обязательное оповещение (отключение запрещено).</i>")

    keyboard = [
        build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_ADMIN}:notif:roles"),
    ]

    await render_screen(update, "\n".join(lines), InlineKeyboardMarkup(keyboard))


async def show_admin_user_inspection_list(update: Update, user: User) -> None:
    """List sample users for inspection."""
    users = User.query.filter(User.is_active == True).order_by(User.id.desc()).limit(8).all()

    text = (
        f"{card_header('🔍 Инспекция пользователя', 'Выбор профиля')}\n"
        "Выберите пользователя для детального аудита настроек доставки и источников прав:"
    )

    keyboard: list[list[InlineKeyboardButton]] = []
    for u in users:
        u_name = escape(get_display_name(u))
        u_role = ROLE_TITLES.get(u.role, u.role or "user")
        keyboard.append([
            InlineKeyboardButton(
                f"👤 {u_name} ({u_role}, ID {u.id})",
                callback_data=f"{CB_PREFIX}:{DOMAIN_ADMIN}:notif:u_inspect:{u.id}",
            )
        ])

    keyboard.append(build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_ADMIN}:notif:hub"))
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_admin_user_inspection_details(update: Update, admin: User, target_user_id: int) -> None:
    """Detailed provenance inspection of a user's notification preferences."""
    target_user = User.query.get(target_user_id)
    if not target_user:
        await render_screen(
            update,
            "❌ <b>Пользователь не найден</b>",
            InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data=f"{CB_PREFIX}:{DOMAIN_ADMIN}:notif:users")]]),
        )
        return

    name = escape(get_display_name(target_user))
    prof = getattr(target_user, "profile", None)
    chat_id = getattr(prof, "telegram_chat_id", None)
    global_enabled = bool(prof and prof.telegram_notifications_enabled)
    role_norm = str(target_user.role or "student").lower()

    lines = [
        card_header(f"🔍 Аудит: {name}", f"ID: {target_user.id} | Роль: {role_norm}"),
        f"<b>Telegram Chat ID:</b> <code>{chat_id or 'не привязан'}</code>",
        f"<b>Глобальная доставка:</b> {'✅ Включена' if global_enabled else '❌ Отключена'}",
        "",
        "<b>Статус типов событий и источник:</b>",
    ]

    items = NotificationTypeRegistry.list_for_role(role_norm)
    for itm in items:
        is_on = is_notification_enabled_for_user(target_user.id, role_norm, itm.kind)
        _, provenance = get_user_notification_preference(target_user.id, role_norm, itm.kind)

        icon = "✅" if is_on else "❌"
        if provenance == "user":
            src = "Личный выбор пользователя"
        elif provenance == "legacy":
            src = "Мигрировано из профиля"
        else:
            src = "По умолчанию платформы"

        if not global_enabled:
            src += " [Глобально заблокировано]"

        lines.append(f"• {icon} <b>{escape(itm.title)}</b>: <i>{src}</i>")

    keyboard = [
        build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_ADMIN}:notif:users"),
    ]

    await render_screen(update, "\n".join(lines), InlineKeyboardMarkup(keyboard))
