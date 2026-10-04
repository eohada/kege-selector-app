"""Long-polling runtime for the separate QA Telegram bot."""
from __future__ import annotations

import asyncio
import logging
import os

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes, MessageHandler, filters

from app.telegram.config import QA_BOT_TOKEN
from wsgi import app as flask_app

logger = logging.getLogger(__name__)


def _truthy(value: str | None) -> bool:
    return (value or '').strip().lower() in {'1', 'true', 'yes', 'on'}


async def _dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from app.bots.qa_bot import process_qa_bot_update

    with flask_app.app_context():
        process_qa_bot_update(update.to_dict())


def main() -> None:
    if not QA_BOT_TOKEN:
        raise RuntimeError('QA_BOT_TOKEN or TELEGRAM_TESTERS_BOT_TOKEN is required')

    application = Application.builder().token(QA_BOT_TOKEN).build()
    application.add_handler(MessageHandler(filters.ALL, _dispatch))
    application.add_handler(CallbackQueryHandler(_dispatch))

    drop_pending = _truthy(os.environ.get('TELEGRAM_QA_POLLING_DROP_PENDING_UPDATES'))

    async def clear_webhook() -> None:
        await application.bot.delete_webhook(drop_pending_updates=drop_pending)

    with flask_app.app_context():
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(clear_webhook())
        finally:
            loop.close()
        application.run_polling(
            allowed_updates=['message', 'callback_query'],
            drop_pending_updates=drop_pending,
            bootstrap_retries=-1,
            close_loop=True,
        )


if __name__ == '__main__':
    main()
