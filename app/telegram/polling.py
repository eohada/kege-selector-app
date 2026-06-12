"""Long-polling runner for the built-in production Telegram bot."""
from __future__ import annotations

import logging
import os

from telegram import Update
from telegram.error import Conflict
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters

from app.telegram.webhook import _build_application
from wsgi import app as flask_app

logger = logging.getLogger(__name__)


def _truthy(value: str | None) -> bool:
    return (value or '').strip().lower() in {'1', 'true', 'yes', 'on'}


async def _log_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query:
        update_type = 'callback_query'
    elif update.message:
        update_type = 'message'
    else:
        update_type = 'other'
    logger.debug('Telegram polling received update_id=%s type=%s', update.update_id, update_type)


async def _log_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if isinstance(context.error, Conflict):
        logger.warning('Telegram polling conflict: another getUpdates client is active')
        return
    logger.exception('Telegram polling error while processing update=%r', update, exc_info=context.error)


def main() -> None:
    """
    Run the same Telegram handlers as the webhook integration via getUpdates.

    This is a production fallback for environments where Telegram cannot reach
    the public webhook endpoint, while outbound access through TELEGRAM_PROXY_URL
    is available.
    """
    logging.getLogger('httpx').setLevel(logging.WARNING)
    drop_pending = _truthy(os.environ.get('TELEGRAM_POLLING_DROP_PENDING_UPDATES'))
    with flask_app.app_context():
        application = _build_application(with_updater=True)
        from app.telegram.handlers import lesson_call_link_start, lesson_call_link_receive, lesson_call_link_cancel, LESSON_CALL_LINK_TEXT
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
        application.add_handler(MessageHandler(filters.ALL, _log_update, block=False), group=-1000)
        application.add_handler(CallbackQueryHandler(_log_update, block=False), group=-1000)
        application.add_error_handler(_log_error)
        logger.info('Starting Telegram long-polling runner')
        application.run_polling(
            allowed_updates=['message', 'callback_query'],
            drop_pending_updates=drop_pending,
            close_loop=True,
        )


if __name__ == '__main__':
    main()
