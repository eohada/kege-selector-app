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


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == '':
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning('Invalid %s=%r, using default %s', name, raw, default)
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == '':
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning('Invalid %s=%r, using default %s', name, raw, default)
        return default


def _get_token() -> str:
    token = os.environ.get('BOT_TOKEN') or os.environ.get('TELEGRAM_BOT_TOKEN')
    if not token:
        raise RuntimeError('BOT_TOKEN / TELEGRAM_BOT_TOKEN env var not set')
    return token


def _build_request() -> HTTPXRequest:
    proxy = telegram_proxy_parts()
    kwargs = {
        'connection_pool_size': _env_int('TELEGRAM_HTTP_POOL_SIZE', 32),
        'read_timeout': _env_float('TELEGRAM_HTTP_READ_TIMEOUT', 20.0),
        'write_timeout': _env_float('TELEGRAM_HTTP_WRITE_TIMEOUT', 20.0),
        'connect_timeout': _env_float('TELEGRAM_HTTP_CONNECT_TIMEOUT', 10.0),
        'pool_timeout': _env_float('TELEGRAM_HTTP_POOL_TIMEOUT', 10.0),
        'media_write_timeout': _env_float('TELEGRAM_HTTP_MEDIA_WRITE_TIMEOUT', 60.0),
    }
    if proxy:
        kwargs['proxy'] = httpx.Proxy(proxy['url'], auth=proxy['auth'])
    return HTTPXRequest(**kwargs)


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
        cmd_start, cmd_link, cmd_linkforce, cmd_menu, cmd_help, cmd_status, cmd_random, cmd_settings, cmd_findstudent, cmd_whatsnew, cmd_lessonnotes,
        cmd_claim_creator, cmd_testnotify, cmd_broadcast,
        # FSM
        bug_report_start, bug_report_receive, bug_report_cancel,
        creator_reply_start, creator_reply_receive, creator_reply_cancel,
        lesson_call_link_start, lesson_call_link_receive, lesson_call_link_cancel,
        lesson_hw_note_start, lesson_hw_note_receive_text, lesson_hw_note_receive_remind, lesson_hw_note_cancel,
        BUG_REPORT_TEXT, CREATOR_REPLY_TEXT, LESSON_CALL_LINK_TEXT, LESSON_HW_NOTE_TEXT, LESSON_HW_NOTE_REMIND,
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

    lesson_hw_note_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(lesson_hw_note_start, pattern=r'^lesson_hw_note:\d+$'),
        ],
        states={
            LESSON_HW_NOTE_TEXT: [
                MessageHandler(
                    filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND,
                    lesson_hw_note_receive_text,
                ),
            ],
            LESSON_HW_NOTE_REMIND: [
                MessageHandler(
                    filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND,
                    lesson_hw_note_receive_remind,
                ),
            ],
        },
        fallbacks=[CommandHandler('cancel', lesson_hw_note_cancel)],
        allow_reentry=True,
        conversation_timeout=900,
    )

    # Register ConversationHandlers FIRST (highest priority)
    app.add_handler(bug_report_conv)
    app.add_handler(creator_reply_conv)
    app.add_handler(lesson_call_link_conv)
    app.add_handler(lesson_hw_note_conv)

    # Regular commands
    app.add_handler(CommandHandler('start', cmd_start))
    app.add_handler(CommandHandler('link', cmd_link))
    app.add_handler(CommandHandler('linkforce', cmd_linkforce))
    app.add_handler(CommandHandler('menu', cmd_menu))
    app.add_handler(CommandHandler('help', cmd_help))
    app.add_handler(CommandHandler('status', cmd_status))
    app.add_handler(CommandHandler('random', cmd_random))
    app.add_handler(CommandHandler('settings', cmd_settings))
    app.add_handler(CommandHandler('lessonnotes', cmd_lessonnotes))
    app.add_handler(CommandHandler('findstudent', cmd_findstudent))
    app.add_handler(CommandHandler('whatsnew', cmd_whatsnew))
    app.add_handler(CommandHandler('claimcreator', cmd_claim_creator))
    app.add_handler(CommandHandler('testnotify', cmd_testnotify))
    app.add_handler(CommandHandler('broadcast', cmd_broadcast))

    # Inline callbacks (after ConversationHandlers so FSM gets priority)
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Catch-all private text
    app.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND,
        handle_private_text,
    ))


def _build_application(token: str | None = None, with_updater: bool = False) -> Application:
    builder = Application.builder().token(token or _get_token())
    builder = builder.request(_build_request())
    if with_updater:
        builder = builder.get_updates_request(_build_request())
    else:
        builder = builder.updater(None)
    app = builder.build()
    _register_handlers(app)
    return app


def get_application() -> Application:
    global _application
    if _application is not None:
        return _application
    with _init_lock:
        if _application is not None:
            return _application
        loop = _ensure_event_loop()
        app = _build_application()
        future = asyncio.run_coroutine_threadsafe(app.initialize(), loop)
        future.result(timeout=30)
        _application = app
        logger.info('Telegram Application initialised (webhook mode)')
    return _application


def _run_async(coro):
    loop = _ensure_event_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=60)


def process_update_sync(update_data: dict) -> dict:
    """
    Process a Telegram update through a per-process Application.

    Do not use this from Celery prefork workers: the background loop/thread
    lock can be inherited in an unsafe state after fork. Celery uses the
    one-shot async path below instead.
    """
    app = get_application()
    update = Update.de_json(update_data, app.bot)
    _run_async(app.process_update(update))
    return {'ok': True}


async def _process_update_once(update_data: dict) -> dict:
    """
    Process a single Telegram update without the background loop/thread.

    Kept as a low-level fallback for scripts/tests that need a one-shot
    Application lifecycle. Celery uses ``process_update_sync`` so callbacks do
    not pay initialize/shutdown latency before acknowledgement.
    """
    app = _build_application()
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
