"""
Конфигурация бота.
"""
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ.get('BOT_TOKEN') or os.environ.get('UREP_BOT_TOKEN')

DATABASE_URL = os.environ.get('DATABASE_URL')
DEMO_DATABASE_URL = os.environ.get('DEMO_DATABASE_URL')

APP_URL = os.environ.get('APP_URL', 'https://boostudy.ru/')
APP_OPEN_URL = os.environ.get('APP_OPEN_URL', 'https://boostudy.ru/login')
BOT_INTERNAL_TOKEN = os.environ.get('BOT_INTERNAL_TOKEN', '').strip()
BOT_FORCE_LINK_SECRET = os.environ.get('BOT_FORCE_LINK_SECRET', '').strip()

LOG_LEVEL = os.environ.get('BOT_LOG_LEVEL', 'INFO')

NOTIFICATION_CHECK_INTERVAL = 30  # Проверка новых уведомлений
REMINDER_CHECK_INTERVAL = 300     # Проверка напоминаний (5 мин)

BOT_INSTANCE_LOCK_KEY = int(os.environ.get('BOT_INSTANCE_LOCK_KEY', '735901'))


def validate_config():
    """Проверка обязательных переменных окружения."""
    errors = []
    
    if not BOT_TOKEN:
        errors.append("BOT_TOKEN не задан")
    
    if not DATABASE_URL:
        errors.append("DATABASE_URL не задан")

    # DEMO_DATABASE_URL опционален: нужен только для управления демо-рефералами из одного прод-бота
    
    if errors:
        raise ValueError("Ошибки конфигурации:\n" + "\n".join(errors))
    
    return True
