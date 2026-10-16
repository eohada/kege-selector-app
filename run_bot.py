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
    token = (
        os.environ.get('TELEGRAM_DEV_BOT_TOKEN')
        or os.environ.get('TELEGRAM_BOT_TOKEN')
        or os.environ.get('MAIN_BOT_TOKEN')
        or os.environ.get('BOT_TOKEN')
    )
    if not token or not token.strip():
        logger.error("ОШИБКА: Токен Telegram-бота не найден в переменных окружения или .env!")
        logger.error("Задайте TELEGRAM_BOT_TOKEN (или TELEGRAM_DEV_BOT_TOKEN) в .env файле.")
        sys.exit(1)

    token = token.strip()
    os.environ['TELEGRAM_BOT_TOKEN'] = token
    os.environ['MAIN_BOT_TOKEN'] = token
    os.environ['BOT_TOKEN'] = token

    bot_id = token.split(':')[0] if ':' in token else 'bot'
    logger.info("Запуск Telegram Dev-бота (%s:***)", bot_id)
    
    # Запускаем штатный long-polling модуль приложения
    from app.telegram.polling import main
    main()

if __name__ == '__main__':
    run()
