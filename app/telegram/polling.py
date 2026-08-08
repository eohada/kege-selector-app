"""Long-polling runner for the built-in production Telegram bot."""
from __future__ import annotations

import logging
import os
import asyncio

from telegram import Update
from telegram.error import Conflict
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters

from app.telegram.webhook import _build_application
from wsgi import app as flask_app

logger = logging.getLogger(__name__)


def _truthy(value: str | None) -> bool:
    return (value or '').strip().lower() in {'1', 'true', 'yes', 'on'}


async def _debug_incoming_logger(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    username = f"@{user.username}" if user and user.username else "no_username"
    user_id = user.id if user else "unknown"
    if update.message:
        text = update.message.text or "не текст (media/other)"
        print(f"📥 [ВХОДЯЩЕЕ СООБЩЕНИЕ] От: {username} (ID: {user_id}) | Текст: {text}")
        logger.info("📥 [ВХОДЯЩЕЕ СООБЩЕНИЕ] От: %s (ID: %s) | Текст: %s", username, user_id, text)
    elif update.callback_query:
        cb_data = update.callback_query.data or ""
        print(f"📥 [НАЖАТИЕ КНОПКИ] От: {username} (ID: {user_id}) | Data: {cb_data}")
        logger.info("📥 [НАЖАТИЕ КНОПКИ] От: %s (ID: %s) | Data: %s", username, user_id, cb_data)


async def _log_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if isinstance(context.error, Conflict):
        logger.warning('Telegram polling conflict: another getUpdates client is active')
        return
    logger.exception('Telegram polling error while processing update=%r', update, exc_info=context.error)


def main() -> None:
    """
    Run Telegram handlers in Long Polling mode.
    Clears active webhooks before starting to ensure getUpdates is not blocked.
    """
    logging.getLogger('httpx').setLevel(logging.WARNING)
    with flask_app.app_context():
        application = _build_application(with_updater=True)
        from app.telegram.handlers import (
            lesson_call_link_start, lesson_call_link_receive, lesson_call_link_cancel, LESSON_CALL_LINK_TEXT,
            lesson_hw_note_start, lesson_hw_note_receive_text, lesson_hw_note_receive_remind, lesson_hw_note_cancel,
            LESSON_HW_NOTE_TEXT, LESSON_HW_NOTE_REMIND,
            cmd_lessonnotes,
        )
        
        # Добавляем глобальный отладочный логгер входящих сообщений (group=-1)
        application.add_handler(MessageHandler(filters.ALL, _debug_incoming_logger), group=-1)
        application.add_handler(CallbackQueryHandler(_debug_incoming_logger), group=-1)

        lesson_call_link_conv = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(lesson_call_link_start, pattern=r'^lesson_call_link:\d+$'),
            ],
            states={
                LESSON_CALL_LINK_TEXT: [
                    MessageHandler(
                        filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND,
                        lesson_call_link_receive,
                    ),
                ],
            },
            fallbacks=[CommandHandler('cancel', lesson_call_link_cancel)],
            allow_reentry=True,
            conversation_timeout=300,
        )
        application.add_handler(lesson_call_link_conv)
        lesson_hw_note_conv = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(lesson_hw_note_start, pattern=r'^lesson_hw_note:\d+$'),
            ],
            states={
                LESSON_HW_NOTE_TEXT: [
                    MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, lesson_hw_note_receive_text),
                ],
                LESSON_HW_NOTE_REMIND: [
                    MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, lesson_hw_note_receive_remind),
                ],
            },
            fallbacks=[CommandHandler('cancel', lesson_hw_note_cancel)],
            allow_reentry=True,
            conversation_timeout=900,
        )
        application.add_handler(lesson_hw_note_conv)
        application.add_handler(CommandHandler('lessonnotes', cmd_lessonnotes))
        application.add_error_handler(_log_error)

        print("🔄 Очищаем Webhook и старые очереди обновлений...")
        logger.info("Clearing Telegram Webhook and pending updates for long polling...")
        
        async def _clear_webhook():
            try:
                await application.bot.delete_webhook(drop_pending_updates=True)
                print("✅ Webhook успешно сброшен, переходим в режим Long Polling")
                logger.info("✅ Telegram Webhook cleared successfully.")
            except Exception as e:
                print(f"⚠️ Ошибка при сбросе Webhook: {e}")
                logger.warning("Failed to delete webhook: %s", e)

        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_clear_webhook())
        else:
            loop.run_until_complete(_clear_webhook())

        logger.info('Starting Telegram long-polling runner')
        application.run_polling(
            allowed_updates=['message', 'callback_query'],
            drop_pending_updates=True,
            bootstrap_retries=-1,
            close_loop=True,
        )


if __name__ == '__main__':
    main()
