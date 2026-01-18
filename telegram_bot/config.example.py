"""
Пример конфигурационного файла для Telegram-бота

Скопируйте этот файл в config.py и заполните своими данными
"""
import os

# Токен бота от @BotFather
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')

# ID администратора (ваш Telegram ID)
# Узнать свой ID можно у бота @userinfobot
TELEGRAM_ADMIN_ID = os.getenv('TELEGRAM_ADMIN_ID', 'YOUR_ADMIN_ID_HERE')

# ID группы тестировщиков (опционально, для дополнительной проверки)
# Можно оставить None, если бот должен работать в любой группе
TELEGRAM_GROUP_ID = os.getenv('TELEGRAM_GROUP_ID', None)

# Путь к базе данных репортов
REPORTS_DB_PATH = os.getenv('REPORTS_DB_PATH', 'data/reports.db')

# ID топика для отправки ответов (опционально)
TELEGRAM_TOPIC_ID = os.getenv('TELEGRAM_TOPIC_ID', None)

# ID главного тестировщика (опционально)
# Главный тестировщик может отправлять репорты через личку боту
# Ему не будут приходить уведомления о новых репортах из группы
TELEGRAM_MAIN_TESTER_ID = os.getenv('TELEGRAM_MAIN_TESTER_ID', None)

# ID второго главного тестировщика (опционально)
# Второй главный тестировщик имеет тот же функционал, что и первый
TELEGRAM_MAIN_TESTER_ID_2 = os.getenv('TELEGRAM_MAIN_TESTER_ID_2', None)