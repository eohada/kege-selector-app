"""
Скрипт локального запуска Telegram-бота в режиме Long Polling.
Читает TELEGRAM_BOT_TOKEN из файла .env и работает с локальной БД SQLite/Postgres.
"""
import os
import sys
import logging

# Добавляем корень проекта в sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json

from dotenv import load_dotenv
load_dotenv()

# Check for dynamic Mini App tunnel configuration (untracked dev tunnel)
tunnel_cfg_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'mini_app_tunnel_env.json')
if os.path.exists(tunnel_cfg_file):
    try:
        with open(tunnel_cfg_file, 'r', encoding='utf-8-sig') as f:
            tcfg = json.load(f)
            if tcfg.get('public_url'):
                os.environ['TELEGRAM_MINI_APP_URL'] = tcfg['public_url']
            if tcfg.get('allowlist_chat_ids'):
                os.environ['TELEGRAM_MINI_APP_ALLOWLIST_CHAT_IDS'] = str(tcfg['allowlist_chat_ids'])
                os.environ['TELEGRAM_MINI_APP_ALLOWLIST_ONLY'] = '1'
    except Exception as e:
        print(f"[WARN] Failed to load mini_app_tunnel_env.json: {e}")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger('run_bot')

def run():
    dev_token = (os.environ.get('TELEGRAM_DEV_BOT_TOKEN') or '').strip()
    prod_token = (os.environ.get('TELEGRAM_BOT_TOKEN') or os.environ.get('MAIN_BOT_TOKEN') or '').strip()

    if not dev_token:
        logger.error("=" * 60)
        logger.error("ОШИБКА: TELEGRAM_DEV_BOT_TOKEN не задан в .env файле!")
        logger.error("Для локальной разработки ЗАПРЕЩЕНО использовать общий/production токен,")
        logger.error("так как это приводит к ошибкам '409 Conflict: another getUpdates client is active'.")
        logger.error("Пожалуйста, добавьте в ваш .env файл:")
        logger.error("  TELEGRAM_DEV_BOT_TOKEN=<токен_вашего_dev_бота>")
        logger.error("  TELEGRAM_DEV_BOT_USERNAME=<юзернейм_вашего_dev_бота>")
        logger.error("=" * 60)
        sys.exit(1)

    # Защита от случайного копирования production токена в TELEGRAM_DEV_BOT_TOKEN
    # ID продакшн-бота BooStudy: 8581074364
    PROD_BOT_IDS = {'8581074364'}
    dev_bot_id = dev_token.split(':')[0] if ':' in dev_token else ''

    if dev_bot_id in PROD_BOT_IDS or (prod_token and dev_token == prod_token):
        logger.error("=" * 60)
        logger.error("ОШИБКА БЕЗОПАСНОСТИ: TELEGRAM_DEV_BOT_TOKEN совпадает с production-токеном (%s:***)!", dev_bot_id)
        logger.error("Локальный опрос production-бота запрещён во избежание 409 Conflict.")
        logger.error("=" * 60)
        sys.exit(1)

    token = dev_token
    os.environ['TELEGRAM_BOT_TOKEN'] = token
    os.environ['MAIN_BOT_TOKEN'] = token
    os.environ['BOT_TOKEN'] = token
    if os.environ.get('TELEGRAM_DEV_BOT_USERNAME'):
        os.environ['TELEGRAM_BOT_USERNAME'] = os.environ['TELEGRAM_DEV_BOT_USERNAME']

    logger.info("Запуск Telegram Dev-бота (%s:***)", dev_bot_id)
    
    # Запускаем штатный long-polling модуль приложения
    from app.telegram.polling import main
    main()

if __name__ == '__main__':
    run()
