"""User settings, granular notification preferences, role switcher, and account linking."""
from __future__ import annotations

import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

from app.models import db, User, UserProfile
from app.telegram.application import available_contexts
from app.telegram.linking import unlink_telegram_identity
from app.telegram.registry import (
    CATEGORY_ICONS,
    CATEGORY_TITLES,
    NotificationCategory,
    NotificationTypeRegistry,
)
from app.telegram.user_notify import (
    get_user_notification_preference,
    is_notification_enabled_for_user,
    reset_user_notification_preferences_to_defaults,
    set_user_notification_preference,
)
from app.telegram.v3.constants import (
    CB_PREFIX,
    DOMAIN_CONTEXT,
    DOMAIN_NAV,
    DOMAIN_PREVIEW,
    DOMAIN_SETTINGS,
    ROLE_EMOJIS,
    ROLE_TITLES,
)
from app.telegram.v3.identity import get_display_name
from app.telegram.v3.ui import build_nav_row, card_header, escape, render_screen

logger = logging.getLogger(__name__)


async def show_settings_home(update: Update, user: User, active_context: str) -> None:
    """Render the primary Settings dashboard."""
    name = escape(get_display_name(user))
    uname = escape(user.username or f"user_{user.id}")
    prof = getattr(user, "profile", None)
    tz_name = getattr(prof, "timezone", None) or getattr(prof, "timezone_iana", None) or "Europe/Moscow"

    role_title = ROLE_TITLES.get(active_context, active_context.capitalize())
    role_emoji = ROLE_EMOJIS.get(active_context, "👤")
    all_roles = available_contexts(user)

    text = (
        f"{card_header('⚙️ Настройки и профиль', name)}\n"
        f"<b>Логин в BooStudy:</b> <code>{uname}</code>\n"
        f"<b>Активная роль:</b> {role_emoji} <b>{role_title}</b>\n"
        f"<b>Часовой пояс:</b> <code>{escape(tz_name)}</code>\n\n"
        "<i>Здесь вы можете гибко настроить уведомления по каждой вашей роли или отвязать Telegram.</i>"
    )

    keyboard: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton("🔔 Настройка уведомлений", callback_data=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:notif:roles")],
    ]

    if len(all_roles) > 1:
        keyboard.append([InlineKeyboardButton(f"🔄 Сменить активную роль ({len(all_roles)})", callback_data=f"{CB_PREFIX}:{DOMAIN_CONTEXT}:menu")])

    keyboard.append([InlineKeyboardButton("ℹ️ Справка и команды", callback_data=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:help")])
    keyboard.append([InlineKeyboardButton("🔓 Отвязать Telegram от профиля", callback_data=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:unlink:ask")])
    keyboard.append(build_nav_row(back_cb=None, home_cb=f"{CB_PREFIX}:{DOMAIN_NAV}:home"))

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_notifications_menu(update: Update, user: User, role: str | None = None) -> None:
    """Entry point for notification settings menu."""
    if role:
        await show_role_categories_menu(update, user, role)
        return
    await show_notifications_role_selector(update, user, getattr(user, "role", "student") or "student")


async def show_notifications_role_selector(update: Update, user: User, active_context: str) -> None:
    """Render role selection for granular notification management."""
    roles = available_contexts(user)
    if len(roles) == 1:
        # Single role: jump straight to categories for that role
        await show_role_categories_menu(update, user, roles[0])
        return

    text = (
        f"{card_header('🔔 Настройка уведомлений: Выбор роли', 'Гранулярные настройки')}\n"
        "У вас активно несколько ролей в системе BooStudy.\n"
        "Каждая роль настраивается независимо, чтобы уведомления преподавателя "
        "не смешивались с уведомлениями ученика или родителя.\n\n"
        "<b>Выберите роль для настройки:</b>"
    )

    keyboard: list[list[InlineKeyboardButton]] = []
    for r in roles:
        r_title = ROLE_TITLES.get(r, r.capitalize())
        r_emoji = ROLE_EMOJIS.get(r, "👤")
        is_cur = (r == active_context)
        label = f"{r_emoji} {r_title}" + (" (активная)" if is_cur else "")
        keyboard.append([InlineKeyboardButton(label, callback_data=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:notif:role:{r}")])

    keyboard.append(build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:home"))
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_role_categories_menu(update: Update, user: User, role: str) -> None:
    """Render categories list for a specific role with enabled/total counters."""
    role_norm = str(role).lower().strip()
    r_title = ROLE_TITLES.get(role_norm, role_norm.capitalize())
    r_emoji = ROLE_EMOJIS.get(role_norm, "👤")

    categories = NotificationTypeRegistry.list_categories_for_role(role_norm)

    text = (
        f"{card_header(f'{r_emoji} Настройка уведомлений: {r_title}', 'Категории сообщений')}\n"
        "Выберите раздел, чтобы включить/отключить конкретные типы оповещений "
        "или посмотреть пример карточки:\n"
    )

    keyboard: list[list[InlineKeyboardButton]] = []

    for cat in categories:
        cat_title = CATEGORY_TITLES.get(cat, cat.capitalize())
        items = NotificationTypeRegistry.list_for_role_and_category(role_norm, cat)
        total = len(items)
        enabled = sum(1 for item in items if is_notification_enabled_for_user(user.id, role_norm, item.kind))
        label = f"{cat_title} ({enabled}/{total})"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:notif:cat:{role_norm}:{cat}")])

    # Global reset button for this role
    keyboard.append([InlineKeyboardButton("🔄 Сбросить к настройкам по умолчанию", callback_data=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:notif:reset_ask:{role_norm}")])
    
    # Navigation back
    all_roles = available_contexts(user)
    back_cb = f"{CB_PREFIX}:{DOMAIN_SETTINGS}:notif:roles" if len(all_roles) > 1 else f"{CB_PREFIX}:{DOMAIN_SETTINGS}:home"
    keyboard.append(build_nav_row(back_cb=back_cb))

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_category_events_menu(update: Update, user: User, role: str, category: str) -> None:
    """Render full-width buttons for each notification type opening a detail card."""
    role_norm = str(role).lower().strip()
    r_title = ROLE_TITLES.get(role_norm, role_norm.capitalize())
    r_emoji = ROLE_EMOJIS.get(role_norm, "👤")
    cat_title = CATEGORY_TITLES.get(category, category.capitalize())

    items = NotificationTypeRegistry.list_for_role_and_category(role_norm, category)

    text = (
        f"{card_header(f'{r_emoji} {r_title} → {cat_title}', 'Настройка типов событий')}\n"
        "Выберите событие, чтобы открыть подробное описание, изменить статус доставки или посмотреть образец карточки:\n"
    )

    keyboard: list[list[InlineKeyboardButton]] = []

    for item in items:
        is_on = is_notification_enabled_for_user(user.id, role_norm, item.kind)
        status_icon = "✅" if is_on else "❌"
        lock_hint = " 🔒" if not item.allow_opt_out else ""
        btn_text = f"{status_icon} {item.title}{lock_hint}"
        detail_cb = f"{CB_PREFIX}:{DOMAIN_SETTINGS}:notif:ev:{role_norm}:{category}:{item.kind}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=detail_cb)])

    back_cb = f"{CB_PREFIX}:{DOMAIN_SETTINGS}:notif:role:{role_norm}"
    keyboard.append(build_nav_row(back_cb=back_cb))

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_event_detail_card(update: Update, user: User, role: str, category: str, kind: str) -> None:
    """Render detailed card for a single notification type with toggle, description, and preview."""
    role_norm = str(role).lower().strip()
    defn = NotificationTypeRegistry.get(kind)
    if not defn:
        await show_category_events_menu(update, user, role_norm, category)
        return

    r_title = ROLE_TITLES.get(role_norm, role_norm.capitalize())
    r_emoji = ROLE_EMOJIS.get(role_norm, "👤")
    cat_title = CATEGORY_TITLES.get(category, category.capitalize())

    is_on = is_notification_enabled_for_user(user.id, role_norm, kind)
    _, provenance = get_user_notification_preference(user.id, role_norm, kind)

    status_str = "✅ <b>Включено</b>" if is_on else "❌ <b>Отключено</b>"
    prov_str = "Пользовательская (ручная)" if provenance == "user" else "По умолчанию для роли"

    text = (
        f"{card_header(f'{r_emoji} {defn.title}', f'{r_title} • {cat_title}')}\n"
        f"<b>Статус доставки:</b> {status_str}\n"
        f"<b>Источник настройки:</b> {prov_str}\n\n"
        f"<b>Назначение оповещения:</b>\n"
        f"{escape(defn.description or 'Уведомление платформы BooStudy.')}\n\n"
    )
    if not defn.allow_opt_out:
        text += "🔒 <i>Это системное обязательное уведомление платформы. Его нельзя отключить, чтобы гарантировать доставку критически важных событий.</i>"

    keyboard: list[list[InlineKeyboardButton]] = []
    if defn.allow_opt_out:
        toggle_label = "❌ Отключить уведомление" if is_on else "✅ Включить уведомление"
        toggle_cb = f"{CB_PREFIX}:{DOMAIN_SETTINGS}:notif:toggle:{role_norm}:{category}:{kind}"
        keyboard.append([InlineKeyboardButton(toggle_label, callback_data=toggle_cb)])

    prev_cb = f"{CB_PREFIX}:{DOMAIN_PREVIEW}:{role_norm}:{kind}"
    keyboard.append([InlineKeyboardButton("👁️ Посмотреть образец карточки", callback_data=prev_cb)])

    back_cb = f"{CB_PREFIX}:{DOMAIN_SETTINGS}:notif:cat:{role_norm}:{category}"
    keyboard.append(build_nav_row(back_cb=back_cb))

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def toggle_event_preference(update: Update, user: User, role: str, category: str, kind: str) -> None:
    """Toggle specific notification type for user and role and refresh detail card."""
    role_norm = str(role).lower().strip()
    current_val = is_notification_enabled_for_user(user.id, role_norm, kind)
    set_user_notification_preference(user.id, role_norm, kind, not current_val)
    await show_event_detail_card(update, user, role_norm, category, kind)


async def show_reset_preferences_dialog(update: Update, user: User, role: str) -> None:
    """Confirm resetting role notification preferences to platform defaults."""
    role_norm = str(role).lower().strip()
    r_title = ROLE_TITLES.get(role_norm, role_norm.capitalize())
    r_emoji = ROLE_EMOJIS.get(role_norm, "👤")

    text = (
        f"{card_header('🔄 Сброс настроек уведомлений', f'{r_emoji} {r_title}')}\n"
        f"Вы действительно хотите сбросить все персональные настройки уведомлений "
        f"для роли <b>{r_title}</b> к стандартным значениям платформы BooStudy?\n\n"
        "Все индивидуальные переключатели будут возвращены к системным по умолчанию."
    )

    keyboard = [
        [
            InlineKeyboardButton("✅ Да, сбросить", callback_data=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:notif:reset_do:{role_norm}"),
            InlineKeyboardButton("Отмена", callback_data=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:notif:role:{role_norm}"),
        ]
    ]

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def execute_reset_preferences(update: Update, user: User, role: str) -> None:
    """Execute reset to defaults for role and re-render role categories."""
    role_norm = str(role).lower().strip()
    reset_user_notification_preferences_to_defaults(user.id, role_norm)
    await show_role_categories_menu(update, user, role_norm)


async def show_role_switcher_menu(update: Update, user: User, current_context: str) -> None:
    """Render multi-role switcher allowing user to jump between authorized cabinets."""
    allowed = available_contexts(user)

    text = (
        f"{card_header('🔄 Выбор роли', 'Переключение активного кабинета')}\n"
        "Вам доступны несколько ролей на платформе BooStudy.\n"
        "Выберите кабинет для работы:\n"
    )

    keyboard: list[list[InlineKeyboardButton]] = []
    for r in allowed:
        emoji = ROLE_EMOJIS.get(r, "👤")
        title = ROLE_TITLES.get(r, r.capitalize())
        is_cur = (r == current_context)
        label = f"• {emoji} {title} (текущий) •" if is_cur else f"{emoji} {title}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"{CB_PREFIX}:{DOMAIN_CONTEXT}:set:{r}")])

    keyboard.append(build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:home"))
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_help_screen(update: Update, user: User | None = None) -> None:
    """Render clean help and command guide."""
    text = (
        f"{card_header('ℹ️ Справка и команды', 'BooStudy Bot V3')}\n"
        "<b>Основные команды бота:</b>\n"
        "• <code>/start</code> — Главное меню вашего активного кабинета.\n"
        "• <code>/menu</code> — Показать клавиатуру быстрого перехода.\n"
        "• <code>/settings</code> — Гранулярные настройки уведомлений по ролям.\n"
        "• <code>/role</code> — Быстрое переключение роли (для мульти-ролей).\n"
        "• <code>/status</code> — Проверка связи и Chat ID.\n"
        "• <code>/help</code> — Эта справочная информация.\n\n"
        "<b>Интеллектуальные уведомления BooStudy 2.1:</b>\n"
        "• Подавление самоуведомлений: вы не получаете спам о собственных действиях.\n"
        "• Пакетная группировка: расписание из 3+ уроков приходит одной карточкой.\n"
        "• Гранулярные настройки: раздельное управление уведомлениями для каждой роли.\n\n"
        "<i>Вопросы и предложения: обратитесь к куратору или администратору.</i>"
    )

    back_target = f"{CB_PREFIX}:{DOMAIN_SETTINGS}:home" if user else None
    keyboard = [build_nav_row(back_cb=back_target)]
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_unlink_confirmation(update: Update, user: User) -> None:
    """Ask user to confirm unlinking their Telegram account."""
    text = (
        f"{card_header('🔓 Отвязка Telegram', 'Подтверждение действия')}\n"
        "Вы действительно хотите отвязать ваш Telegram-аккаунт от профиля BooStudy?\n\n"
        "После отвязки вы перестанете получать напоминания об уроках и проверке домашних заданий."
    )
    keyboard = [
        [
            InlineKeyboardButton("❌ Да, отвязать", callback_data=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:unlink:do"),
            InlineKeyboardButton("Отмена", callback_data=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:home"),
        ]
    ]
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def execute_unlink(update: Update, user: User) -> None:
    """Execute account unlinking and notify user."""
    chat_id = update.effective_chat.id if update.effective_chat else None
    from app.telegram.linking import unlink_telegram_identity
    from app.telegram.v3.screens.unlinked import show_unlinked_screen

    unlink_telegram_identity(db.session, user=user)
    db.session.commit()

    if update.callback_query:
        try:
            await update.callback_query.answer("Telegram отвязан от профиля", show_alert=False)
        except Exception:
            pass

    await show_unlinked_screen(update)
