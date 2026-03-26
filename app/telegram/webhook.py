"""
Telegram Bot 2.0 — webhook integration with Flask.
Replaces polling with webhook for better reliability and scalability.

Architecture:
  - A dedicated asyncio event loop runs in a background daemon thread.
  - The python-telegram-bot Application (with all handlers) lives on that loop.
  - Flask routes push updates to the loop via ``run_coroutine_threadsafe``.
  - DB access inside handlers uses ``urep_bot.db`` (plain SQLAlchemy sessions),
    so no Flask app-context is required in the bot thread.
"""
import asyncio
import logging
import os
import threading

from flask import Blueprint, request, jsonify
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

logger = logging.getLogger(__name__)

telegram_bp = Blueprint('telegram', __name__, url_prefix='/webhook')

_application: Application | None = None
_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None
_init_lock = threading.Lock()


def _get_token() -> str:
    token = os.environ.get('BOT_TOKEN') or os.environ.get('TELEGRAM_BOT_TOKEN')
    if not token:
        raise RuntimeError('BOT_TOKEN / TELEGRAM_BOT_TOKEN env var not set')
    return token


def _ensure_event_loop() -> asyncio.AbstractEventLoop:
    """Start a background thread running an asyncio event loop (singleton)."""
    global _loop, _thread
    if _loop is not None and _thread is not None and _thread.is_alive():
        return _loop
    with _init_lock:
        if _loop is not None and _thread is not None and _thread.is_alive():
            return _loop
        _loop = asyncio.new_event_loop()
        _thread = threading.Thread(
            target=_loop.run_forever, daemon=True, name='tg-webhook-loop',
        )
        _thread.start()
    return _loop


def _register_handlers(app: Application) -> None:
    """Attach all command / callback / message handlers."""
    from app.telegram.handlers import (
        cmd_start,
        cmd_menu,
        cmd_help,
        callback_handler,
        handle_private_text,
    )

    app.add_handler(CommandHandler('start', cmd_start))
    app.add_handler(CommandHandler('menu', cmd_menu))
    app.add_handler(CommandHandler('help', cmd_help))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND,
        handle_private_text,
    ))


def get_application() -> Application:
    """Get (or lazily create) the Telegram Application singleton."""
    global _application
    if _application is not None:
        return _application
    with _init_lock:
        if _application is not None:
            return _application
        loop = _ensure_event_loop()
        token = _get_token()
        app = (
            Application.builder()
            .token(token)
            .updater(None)
            .build()
        )
        _register_handlers(app)
        future = asyncio.run_coroutine_threadsafe(app.initialize(), loop)
        future.result(timeout=30)
        _application = app
        logger.info('Telegram Application initialised (webhook mode)')
    return _application


def _run_async(coro):
    """Submit *coro* to the bot's event loop and block until done."""
    loop = _ensure_event_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=60)


# ---------------------------------------------------------------------------
# Flask routes
# ---------------------------------------------------------------------------

@telegram_bp.route('/telegram', methods=['POST'])
def telegram_webhook():
    """Receive Telegram updates via webhook."""
    try:
        data = request.get_json(force=True)
        bot_app = get_application()
        update = Update.de_json(data, bot_app.bot)
        _run_async(bot_app.process_update(update))
        return jsonify({'ok': True})
    except Exception as e:
        logger.error('Webhook processing error: %s', e, exc_info=True)
        return jsonify({'ok': False, 'error': str(e)}), 500


@telegram_bp.route('/telegram/set', methods=['POST'])
def set_webhook():
    """Set the Telegram webhook URL.  Requires ``X-Bot-Token`` header."""
    internal_token = os.environ.get('BOT_INTERNAL_TOKEN', '').strip()
    if not internal_token or request.headers.get('X-Bot-Token', '') != internal_token:
        return jsonify({'ok': False, 'error': 'unauthorized'}), 403

    payload = request.get_json(force=True) if request.is_json else {}
    webhook_url = (payload.get('url') or '').strip()
    if not webhook_url:
        base = request.url_root.rstrip('/')
        webhook_url = f'{base}/webhook/telegram'

    try:
        bot_app = get_application()
        _run_async(bot_app.bot.set_webhook(url=webhook_url))
        logger.info('Webhook set to %s', webhook_url)
        return jsonify({'ok': True, 'webhook_url': webhook_url})
    except Exception as e:
        logger.error('Failed to set webhook: %s', e, exc_info=True)
        return jsonify({'ok': False, 'error': str(e)}), 500


@telegram_bp.route('/telegram/info', methods=['GET'])
def webhook_info():
    """Return current webhook info (debug / health-check)."""
    internal_token = os.environ.get('BOT_INTERNAL_TOKEN', '').strip()
    if internal_token and request.headers.get('X-Bot-Token', '') != internal_token:
        return jsonify({'ok': False, 'error': 'unauthorized'}), 403
    try:
        bot_app = get_application()
        info = _run_async(bot_app.bot.get_webhook_info())
        return jsonify({
            'ok': True,
            'url': info.url,
            'pending_update_count': info.pending_update_count,
            'last_error_date': str(info.last_error_date) if info.last_error_date else None,
            'last_error_message': info.last_error_message,
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
