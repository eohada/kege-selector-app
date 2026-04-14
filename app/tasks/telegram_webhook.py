"""Celery task for processing Telegram webhook updates asynchronously."""
from __future__ import annotations

import asyncio
import logging

from celery_app import celery
from telegram import Update

logger = logging.getLogger(__name__)


@celery.task(
    bind=True,
    max_retries=3,
    default_retry_delay=2,
    name='app.tasks.telegram_webhook.process_telegram_update_task',
)
def process_telegram_update_task(self, update_data: dict) -> dict:
    """
    Process a Telegram update in a Celery worker.

    The webhook route only enqueues this task and returns 200 immediately.
    """
    try:
        # Lazy import to avoid circular imports during app bootstrap.
        from app.telegram.webhook import get_application, _run_async

        bot_app = get_application()
        update = Update.de_json(update_data, bot_app.bot)
        _run_async(bot_app.process_update(update))
        return {'ok': True}
    except Exception as exc:
        logger.error('process_telegram_update_task failed: %s', exc, exc_info=True)
        try:
            raise self.retry(exc=exc)
        except Exception:
            return {'ok': False, 'error': str(exc)}
