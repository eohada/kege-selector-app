"""
Telegram Bot — webhook integration with Flask.

Architecture:
  - A dedicated asyncio event loop runs in a background daemon thread.
  - The python-telegram-bot Application lives on that loop.
  - Flask routes push updates to the loop via ``run_coroutine_threadsafe``.
  - ConversationHandlers manage multi-step FSMs (bug report, creator reply).
"""
import asyncio
import logging
import os
import threading

from flask import Blueprint, request, jsonify
import httpx
from telegram import Update
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters,
)

from app.telegram.config import telegram_proxy_parts

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


def _build_request() -> HTTPXRequest | None:
    proxy = telegram_proxy_parts()
    if not proxy:
        return None
    return HTTPXRequest(proxy=httpx.Proxy(proxy['url'], auth=proxy['auth']))


def _ensure_event_loop() -> asyncio.AbstractEventLoop:
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
    from app.telegram.handlers import (
        # Commands
        cmd_start, cmd_link, cmd_menu, cmd_help, cmd_status, cmd_random, cmd_settings,
        # FSM
        bug_report_start, bug_report_receive, bug_report_cancel,
        creator_reply_start, creator_reply_receive, creator_reply_cancel,
        BUG_REPORT_TEXT, CREATOR_REPLY_TEXT,
        # Callbacks / text
        callback_handler, handle_private_text,
    )

    # --- Bug Report ConversationHandler ---
    # Entry via /report command OR callback 'bug_report_start'
    bug_report_conv = ConversationHandler(
        entry_points=[
            CommandHandler('report', bug_report_start),
            CallbackQueryHandler(bug_report_start, pattern='^bug_report_start$'),
        ],
        states={
            BUG_REPORT_TEXT: [
                MessageHandler(
                    (filters.TEXT | filters.PHOTO | filters.Document.IMAGE) & filters.ChatType.PRIVATE & ~filters.COMMAND,
                    bug_report_receive,
                ),
            ],
        },
        fallbacks=[CommandHandler('cancel', bug_report_cancel)],
        allow_reentry=True,
        conversation_timeout=300,
    )

    # --- Creator Reply ConversationHandler ---
    # Entry via callback 'bug_reply_<report_id>_<student_chat_id>'
    creator_reply_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(creator_reply_start, pattern=r'^bug_reply_\d+_\d+$'),
        ],
        states={
            CREATOR_REPLY_TEXT: [
                MessageHandler(
                    filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND,
                    creator_reply_receive,
                ),
            ],
        },
        fallbacks=[CommandHandler('cancel', creator_reply_cancel)],
        allow_reentry=True,
        conversation_timeout=300,
    )

    # Register ConversationHandlers FIRST (highest priority)
    app.add_handler(bug_report_conv)
    app.add_handler(creator_reply_conv)

    # Regular commands
    app.add_handler(CommandHandler('start', cmd_start))
    app.add_handler(CommandHandler('link', cmd_link))
    app.add_handler(CommandHandler('menu', cmd_menu))
    app.add_handler(CommandHandler('help', cmd_help))
    app.add_handler(CommandHandler('status', cmd_status))
    app.add_handler(CommandHandler('random', cmd_random))
    app.add_handler(CommandHandler('settings', cmd_settings))

    # Inline callbacks (after ConversationHandlers so FSM gets priority)
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Catch-all private text
    app.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND,
        handle_private_text,
    ))


def get_application() -> Application:
    global _application
    if _application is not None:
        return _application
    with _init_lock:
        if _application is not None:
            return _application
        loop = _ensure_event_loop()
        token = _get_token()
        request = _build_request()
        builder = Application.builder().token(token)
        if request:
            builder = builder.request(request)
        app = builder.updater(None).build()
        _register_handlers(app)
        future = asyncio.run_coroutine_threadsafe(app.initialize(), loop)
        future.result(timeout=30)
        _application = app
        logger.info('Telegram Application initialised (webhook mode)')
    return _application


def _run_async(coro):
    loop = _ensure_event_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=60)


async def _process_update_once(update_data: dict) -> dict:
    """
    Process a single Telegram update without the background loop/thread.

    This path is used from Celery workers, where prefork + thread locks can
    become poisonous after fork. The Flask runtime still uses the singleton
    loop, but the worker uses this one-shot path.
    """
    token = _get_token()
    request = _build_request()
    builder = Application.builder().token(token)
    if request:
        builder = builder.request(request)
    app = builder.updater(None).build()
    _register_handlers(app)
    await app.initialize()
    try:
        update = Update.de_json(update_data, app.bot)
        await app.process_update(update)
        return {'ok': True}
    finally:
        try:
            await app.shutdown()
        except Exception:
            logger.debug('one-shot telegram app shutdown failed', exc_info=True)


# ---------------------------------------------------------------------------
# Flask routes
# ---------------------------------------------------------------------------

@telegram_bp.route('/telegram', methods=['POST'])
def telegram_webhook():
    """Receive Telegram updates via webhook."""
    try:
        data = request.get_json(force=True)
        # IMPORTANT: return 200 immediately, process update asynchronously in Celery.
        from app.tasks.telegram_webhook import process_telegram_update_task

        process_telegram_update_task.delay(data)
        return jsonify({'ok': True, 'queued': True}), 200
    except Exception as e:
        logger.error('Webhook processing error: %s', e, exc_info=True)
        return jsonify({'ok': False, 'error': str(e)}), 500


@telegram_bp.route('/telegram/set', methods=['POST'])
def set_webhook():
    """Set the Telegram webhook URL. Requires ``X-Bot-Token`` header."""
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
