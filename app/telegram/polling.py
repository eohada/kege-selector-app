"""Long-polling runner for the built-in production Telegram bot."""
from __future__ import annotations

import logging
import os

from app.telegram.webhook import _build_application
from wsgi import app as flask_app

logger = logging.getLogger(__name__)


def _truthy(value: str | None) -> bool:
    return (value or '').strip().lower() in {'1', 'true', 'yes', 'on'}


def main() -> None:
    """
    Run the same Telegram handlers as the webhook integration via getUpdates.

    This is a production fallback for environments where Telegram cannot reach
    the public webhook endpoint, while outbound access through TELEGRAM_PROXY_URL
    is available.
    """
    drop_pending = _truthy(os.environ.get('TELEGRAM_POLLING_DROP_PENDING_UPDATES'))
    with flask_app.app_context():
        application = _build_application()
        logger.info('Starting Telegram long-polling runner')
        application.run_polling(
            allowed_updates=['message', 'callback_query'],
            drop_pending_updates=drop_pending,
            close_loop=True,
        )


if __name__ == '__main__':
    main()
