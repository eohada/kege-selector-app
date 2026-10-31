"""User settings, notification preferences, role switcher and help screens."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

from app.models import db, User, UserProfile
from app.telegram.application import available_contexts
from app.telegram.linking import unlink_telegram_identity
from app.telegram.v3.constants import (
    CB_PREFIX,
    DOMAIN_CONTEXT,
    DOMAIN_NAV,
    DOMAIN_SETTINGS,
    ROLE_EMOJIS,
    ROLE_TITLES,
)
from app.telegram.v3.identity import get_display_name
from app.telegram.v3.ui import card_header, escape, build_nav_row, render_screen


async def show_settings_home(update: Update, user: User, active_context: str) -> None:
    """Render the Settings dashboard."""
    name = escape(get_display_name(user))
    uname = escape(user.username or f"user_{user.id}")
    prof = getattr(user, "profile", None)
    tz_name = getattr(prof, "timezone", None) or "Europe/Moscow"

    role_title = ROLE_TITLES.get(active_context, active_context)
    role_emoji = ROLE_EMOJIS.get(active_context, "👤")

    all_roles = available_contexts(user)

    text = (
        f"{card_header('⚙️ Настройки и профиль', name)}\n"
        f"<b>Логин в BooStudy:</b> <code>{uname}</code>\n"
        f"<b>Активная роль:</b> {role_emoji} <b>{role_title}</b>\n"
        f"<b>Часовой пояс:</b> <code>{escape(tz_name)}</code>\n\n"
        f"<i>Здесь вы можете настроить категории уведомлений или отвязать Telegram-аккаунт.</i>\n"
    )

    keyboard: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton("🔔 Категории уведомлений", callback_data=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:notif:menu")],
    ]

    if len(all_roles) > 1:
        keyboard.append([InlineKeyboardButton(f"🔄 Сменить активную роль ({len(all_roles)})", callback_data=f"{CB_PREFIX}:{DOMAIN_CONTEXT}:menu")])

    keyboard.append([InlineKeyboardButton("ℹ️ Справка и команды", callback_data=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:help")])
    keyboard.append([InlineKeyboardButton("🔓 Отвязать Telegram от профиля", callback_data=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:unlink:ask")])
    keyboard.append(build_nav_row(back_cb=None, home_cb=f"{CB_PREFIX}:{DOMAIN_NAV}:home"))

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_notifications_menu(update: Update, user: User) -> None:
    """Render interactive toggles for Telegram notification categories."""
    prof = getattr(user, "profile", None)
    if not prof:
        prof = UserProfile(user_id=user.id)
        db.session.add(prof)
        db.session.commit()

    r_remind = bool(getattr(prof, "tg_notify_lesson_reminder", True))
    r_hw = bool(getattr(prof, "tg_notify_homework_checked", True))
    r_sched = bool(getattr(prof, "tg_notify_lesson_scheduled", True))
    r_news = bool(getattr(prof, "tg_notify_news", True))

    text = (
        f"{card_header('🔔 Настройка уведомлений', 'Категории сообщений в бот')}\n"
        "Нажмите на пункт, чтобы включить или отключить категорию сообщений:\n"
    )

    def _mark(val: bool) -> str:
        return "✅ Вкл" if val else "❌ Выкл"

    keyboard: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(f"Напоминания об уроках: {_mark(r_remind)}", callback_data=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:notif:toggle:reminder")],
        [InlineKeyboardButton(f"Проверка домашних заданий: {_mark(r_hw)}", callback_data=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:notif:toggle:hw")],
        [InlineKeyboardButton(f"Новые назначения в расписании: {_mark(r_sched)}", callback_data=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:notif:toggle:sched")],
        [InlineKeyboardButton(f"Новости и обновления: {_mark(r_news)}", callback_data=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:notif:toggle:news")],
        build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:home"),
    ]

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def toggle_notification_setting(update: Update, user: User, category: str) -> None:
    """Toggle a notification field on UserProfile and refresh view."""
    prof = getattr(user, "profile", None)
    if not prof:
        prof = UserProfile(user_id=user.id)
        db.session.add(prof)

    if category == "reminder":
        prof.tg_notify_lesson_reminder = not bool(getattr(prof, "tg_notify_lesson_reminder", True))
    elif category == "hw":
        prof.tg_notify_homework_checked = not bool(getattr(prof, "tg_notify_homework_checked", True))
    elif category == "sched":
        prof.tg_notify_lesson_scheduled = not bool(getattr(prof, "tg_notify_lesson_scheduled", True))
    elif category == "news":
        prof.tg_notify_news = not bool(getattr(prof, "tg_notify_news", True))

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()

    await show_notifications_menu(update, user)


async def show_role_switcher_menu(update: Update, user: User, current_context: str) -> None:
    """Render multi-role switcher allowing user to jump between authorized cabinets."""
    allowed = available_contexts(user)

    text = (
        f"{card_header('🔄 Выбор роли', 'Переключение активного кабинета')}\n"
        "Вам доступны несколько ролей на платформе BooStudy.\n"
        "Выберите кабинет для работы:\n"
    )

    keyboard: list[list[InlineKeyboardButton]] = []
    for role in allowed:
        emoji = ROLE_EMOJIS.get(role, "👤")
        title = ROLE_TITLES.get(role, role.capitalize())
        is_cur = role == current_context
        label = f"• {emoji} {title} (текущий) •" if is_cur else f"{emoji} {title}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"{CB_PREFIX}:{DOMAIN_CONTEXT}:set:{role}")])

    keyboard.append(build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:home"))
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_help_screen(update: Update, user: User | None = None) -> None:
    """Render clean help and command guide."""
    text = (
        f"{card_header('ℹ️ Справка и команды', 'BooStudy Bot V3')}\n"
        "<b>Основные команды бота:</b>\n"
        "• <code>/start</code> — Открыть главное меню вашего кабинета.\n"
        "• <code>/menu</code> — Показать навигационную панель.\n"
        "• <code>/settings</code> — Настройки уведомлений и профиля.\n"
        "• <code>/role</code> — Быстрое переключение роли (для мульти-ролей).\n"
        "• <code>/help</code> — Эта справочная информация.\n\n"
        "<b>Как работают уведомления:</b>\n"
        "Бот автоматически присылает напоминания о предстоящих уроках за 1 час и за 10 минут, "
        "а также оповещает о проверке домашних заданий учителем.\n\n"
        "<i>Вопросы и поддержка: обратитесь к администратору платформы.</i>"
    )

    back_target = f"{CB_PREFIX}:{DOMAIN_SETTINGS}:home" if user else None
    keyboard = [build_nav_row(back_cb=back_target)]
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_unlink_confirmation(update: Update, user: User) -> None:
    """Render unlink confirmation step."""
    text = (
        f"{card_header('🔓 Отвязка Telegram', 'Внимание')}\n"
        "Вы действительно хотите отвязать свой Telegram от BooStudy?\n\n"
        "⚠️ <b>Последствия:</b>\n"
        "• Уведомления об уроках и проверке ДЗ перестанут приходить.\n"
        "• Доступ к боту будет закрыт до повторной привязки на сайте.\n\n"
        "Вы сможете привязать аккаунт заново в любой момент в личном кабинете на сайте."
    )

    keyboard: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton("❌ Да, отвязать аккаунт", callback_data=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:unlink:do")],
        [InlineKeyboardButton("◀ Отмена (оставить привязку)", callback_data=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:home")],
    ]

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def execute_unlink(update: Update, user: User) -> None:
    """Perform the actual account unlinking and show unlinked screen."""
    from app.telegram.v3.screens.unlinked import show_unlinked_screen
    try:
        unlink_telegram_identity(db.session, user=user, profile=user.profile)
        db.session.commit()
    except Exception as e:
        db.session.rollback()

    if update.callback_query:
        try:
            await update.callback_query.answer("Telegram успешно отвязан от профиля.", show_alert=True)
        except Exception:
            pass

    await show_unlinked_screen(update)
