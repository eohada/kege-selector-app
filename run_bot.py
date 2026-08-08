"""
Скрипт локального запуска Telegram-бота в режиме Long Polling.
Читает TELEGRAM_BOT_TOKEN из файла .env и работает с локальной БД SQLite/Postgres.
"""
import os
import sys
import logging

# Добавляем корень проекта в sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger('run_bot')

def run():
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not token:
        logger.error("ОШИБКА: TELEGRAM_BOT_TOKEN не задан в .env!")
        sys.exit(1)

    logger.info("Запуск Telegram Dev-бота (%s...)", token[:12])
    
    # Запускаем штатный long-polling модуль приложения
    from app.telegram.polling import main
    main()

if __name__ == '__main__':
    run()
