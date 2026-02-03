#!/usr/bin/env python3
"""
Точка входа для запуска бота.
"""
import asyncio
import logging
import sys

from config import validate_config, LOG_LEVEL, NOTIFICATION_CHECK_INTERVAL, REMINDER_CHECK_INTERVAL
from db import init_db
from bot import create_bot_application
from notifications import process_pending_notifications, process_lesson_reminders, check_low_lessons

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO)
)
logger = logging.getLogger(__name__)

# Уменьшаем логи от httpx
logging.getLogger("httpx").setLevel(logging.WARNING)


async def background_tasks(application):
    """Фоновые задачи бота."""
    bot = application.bot
    notification_counter = 0
    reminder_counter = 0
    
    while True:
        try:
            # Проверяем уведомления каждые NOTIFICATION_CHECK_INTERVAL секунд
            await process_pending_notifications(bot)
            
            notification_counter += NOTIFICATION_CHECK_INTERVAL
            reminder_counter += NOTIFICATION_CHECK_INTERVAL
            
            # Проверяем напоминания каждые REMINDER_CHECK_INTERVAL секунд
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
    
    # Валидация конфигурации
    try:
        validate_config()
        logger.info("Configuration validated")
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)
    
    # Инициализация БД
    try:
        init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Database error: {e}")
        sys.exit(1)
    
    # Создание приложения
    application = create_bot_application()
    
    # Добавляем post_init callback
    application.post_init = post_init
    
    # Запуск
    logger.info("Starting polling...")
    application.run_polling(
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
