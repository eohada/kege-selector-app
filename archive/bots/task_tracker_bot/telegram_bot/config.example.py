"""
Пример конфигурационного файла для Telegram-бота

Скопируйте этот файл в config.py и заполните своими данными
"""
import os

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')

TELEGRAM_ADMIN_ID = os.getenv('TELEGRAM_ADMIN_ID', 'YOUR_ADMIN_ID_HERE')

TELEGRAM_GROUP_ID = os.getenv('TELEGRAM_GROUP_ID', None)

REPORTS_DB_PATH = os.getenv('REPORTS_DB_PATH', 'data/reports.db')

TELEGRAM_TOPIC_ID = os.getenv('TELEGRAM_TOPIC_ID', None)

TELEGRAM_MAIN_TESTER_ID = os.getenv('TELEGRAM_MAIN_TESTER_ID', None)

TELEGRAM_MAIN_TESTER_ID_2 = os.getenv('TELEGRAM_MAIN_TESTER_ID_2', None)