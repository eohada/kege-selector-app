"""
Точка входа для запуска бота.
"""
import asyncio
import logging
import sys
import os
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

from urep_bot.config import validate_config, LOG_LEVEL, NOTIFICATION_CHECK_INTERVAL, REMINDER_CHECK_INTERVAL, BOT_INSTANCE_LOCK_KEY, DATABASE_URL
from urep_bot.db import init_db, get_session, close_session
from sqlalchemy import text
from urep_bot.bot import create_bot_application
from urep_bot.notifications import (
    process_pending_notifications,
    process_lesson_reminders,
    check_low_lessons,
    process_error_report_replies,
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO)
)
logger = logging.getLogger(__name__)

logging.getLogger("httpx").setLevel(logging.WARNING)


async def background_tasks(application):
    """Фоновые задачи бота."""
    bot = application.bot
    notification_counter = 0
    reminder_counter = 0
    
    while True:
        try:
            await process_pending_notifications(bot)
            await process_error_report_replies(bot)
            
            notification_counter += NOTIFICATION_CHECK_INTERVAL
            reminder_counter += NOTIFICATION_CHECK_INTERVAL
            
            if reminder_counter >= REMINDER_CHECK_INTERVAL:
                await process_lesson_reminders(bot)
                await check_low_lessons(bot)
                reminder_counter = 0
            
        except Exception as e:
            logger.error(f"Error in background tasks: {e}", exc_info=True)
        
        await asyncio.sleep(NOTIFICATION_CHECK_INTERVAL)


async def post_init(application):
    """Инициализация после запуска."""
    logger.info("Bot started, initializing background tasks...")
    asyncio.create_task(background_tasks(application))


def main():
    """Главная функция запуска бота."""
    logger.info("=" * 50)
    logger.info("URep Telegram Bot starting...")
    logger.info("=" * 50)
    logger.info(f"PID: {os.getpid()}")
    logger.info(f"HOSTNAME: {os.environ.get('HOSTNAME') or ''}")
    service_name = (os.environ.get('SERVICE_NAME') or os.environ.get('RAILWAY_SERVICE_NAME') or '').strip().lower()
    allow_web = (os.environ.get('BOT_ALLOW_WEB') or '').strip().lower() in {'1', 'true', 'yes'}
    allow_list_raw = (os.environ.get('BOT_SERVICE_NAME_ALLOW') or '').strip().lower()
    allow_list = {s.strip() for s in allow_list_raw.split(',') if s.strip()}
    if allow_list:
        if service_name not in allow_list:
            logger.error(f"Bot start blocked: service '{service_name}' is not in BOT_SERVICE_NAME_ALLOW.")
            sys.exit(3)
    elif service_name == 'web' and not allow_web:
        logger.error("Bot start blocked: running as web service. Set BOT_ALLOW_WEB=1 or BOT_SERVICE_NAME_ALLOW.")
        sys.exit(3)
    
    try:
        validate_config()
        logger.info("Configuration validated")
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)
    
    try:
        init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Database error: {e}")
        sys.exit(1)

    lock_session = None
    try:
        db_url = (DATABASE_URL or '').lower()
        if 'postgres' in db_url:
            lock_session = get_session()
            res = lock_session.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": BOT_INSTANCE_LOCK_KEY}).fetchone()
            locked = bool(res and res[0])
            if not locked:
                close_session(lock_session)
                logger.error("Another bot instance already holds advisory lock. Exiting.")
                sys.exit(3)
            logger.info(f"Advisory lock acquired: {BOT_INSTANCE_LOCK_KEY} (session held until exit)")
            # НЕ закрываем lock_session — блокировка привязана к соединению, иначе другие экземпляры начнут polling
        else:
            logger.info("Advisory lock skipped (non-Postgres DB).")
    except Exception as e:
        logger.error(f"Failed to acquire advisory lock: {e}")
        sys.exit(1)
    
    application = create_bot_application()
    
    application.post_init = post_init
    
    logger.info("Starting polling...")
    application.run_polling(
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
