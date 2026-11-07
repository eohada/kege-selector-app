"""Handler registration for BooStudy Bot V3."""
from __future__ import annotations

import logging
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.telegram.v3.router import (
    handle_cancel_command,
    handle_help_command,
    handle_menu_command,
    handle_role_command,
    handle_settings_command,
    handle_start_command,
    handle_text_message,
    handle_unlink_command,
    handle_v3_callback,
)

logger = logging.getLogger(__name__)


async def handle_link_command_alias(update, context):
    """Alias for /link: allows manual /link BS-XXXXXX code submission."""
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text(
            "ℹ️ <b>Привязка аккаунта BooStudy</b>\n\n"
            "Использование: <code>/link BS-XXXXXX</code>\n"
            "Где BS-XXXXXX — 6-значный код из вашего профиля на сайте.",
            parse_mode="HTML",
        )
        return
    await handle_start_command(update, context)


async def handle_status_command(update, context):
    """Show current bot connection status."""
    from app.telegram.v3.context import get_active_context
    from app.telegram.v3.identity import get_display_name, resolve_user_identity
    from app.telegram.v3.screens.unlinked import show_unlinked_screen

    chat_id = update.effective_chat.id
    user, profile = resolve_user_identity(chat_id)
    if not user:
        await show_unlinked_screen(update)
        return

    name = get_display_name(user, profile)
    ctx = get_active_context(user, context.user_data)
    await update.message.reply_text(
        f"✅ <b>Telegram подключен</b>\n\n"
        f"👤 <b>Пользователь:</b> {name}\n"
        f"🎭 <b>Активная роль:</b> {ctx.upper()}\n"
        f"🆔 <b>Chat ID:</b> <code>{chat_id}</code>\n\n"
        "Для перехода в меню используйте /menu.",
        parse_mode="HTML",
    )


async def handle_miniapp_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not update.effective_message:
        return
    from app.telegram.config import is_mini_app_permitted_for_chat_id, get_mini_app_url
    if not is_mini_app_permitted_for_chat_id(user.id):
        return

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
    app_url = get_mini_app_url()
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Открыть Mini App (Pilot)", web_app=WebAppInfo(url=app_url))]
    ])
    await update.effective_message.reply_text(
        "👋 <b>BooStudy Mini App (Pilot)</b>\n\nНажми кнопку ниже для открытия мобильного кабинета:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


def register_v3_handlers(application: Application) -> None:
    """Register all BooStudy Bot V3 commands, callbacks, and message dispatchers.

    Ensures single source of truth for Telegram handlers and avoids dual-handling conflicts.
    """
    logger.info("Registering BooStudy Bot V3 handlers")

    # 1. Primary Commands
    application.add_handler(CommandHandler("start", handle_start_command))
    application.add_handler(CommandHandler("menu", handle_menu_command))
    application.add_handler(CommandHandler("help", handle_help_command))
    application.add_handler(CommandHandler("settings", handle_settings_command))
    application.add_handler(CommandHandler("role", handle_role_command))
    application.add_handler(CommandHandler("unlink", handle_unlink_command))
    application.add_handler(CommandHandler("cancel", handle_cancel_command))
    application.add_handler(CommandHandler("link", handle_link_command_alias))
    application.add_handler(CommandHandler("status", handle_status_command))
    application.add_handler(CommandHandler("miniapp", handle_miniapp_command))
    application.add_handler(CommandHandler("pilot", handle_miniapp_command))

    # 2. V3 Callback Query Handler (handles all v3:* actions)
    application.add_handler(CallbackQueryHandler(handle_v3_callback, pattern=r"^v3:"))

    # 3. Private Text Message Handler (link codes, interactive responses, fallbacks)
    application.add_handler(
        MessageHandler(
            filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND,
            handle_text_message,
        )
    )

    logger.info("BooStudy Bot V3 handlers successfully registered")
