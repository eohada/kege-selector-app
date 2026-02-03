"""
Конфигурация бота.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot
BOT_TOKEN = os.environ.get('BOT_TOKEN') or os.environ.get('UREP_BOT_TOKEN')

# Database
DATABASE_URL = os.environ.get('DATABASE_URL')

# App URL (для ссылок в сообщениях)
APP_URL = os.environ.get('APP_URL', 'https://urep.up.railway.app')

# Logging
LOG_LEVEL = os.environ.get('BOT_LOG_LEVEL', 'INFO')

# Интервалы проверки (секунды)
NOTIFICATION_CHECK_INTERVAL = 30  # Проверка новых уведомлений
REMINDER_CHECK_INTERVAL = 300     # Проверка напоминаний (5 мин)


def validate_config():
    """Проверка обязательных переменных окружения."""
    errors = []
    
    if not BOT_TOKEN:
        errors.append("BOT_TOKEN не задан")
    
    if not DATABASE_URL:
        errors.append("DATABASE_URL не задан")
    
    if errors:
        raise ValueError("Ошибки конфигурации:\n" + "\n".join(errors))
    
    return True
