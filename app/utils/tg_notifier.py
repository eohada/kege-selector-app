import os
import requests
import secrets
import logging
from core.db_models import db, User

logger = logging.getLogger(__name__)
TELEGRAM_BOT_TOKEN = (
    os.environ.get('MAIN_BOT_TOKEN')
    or os.environ.get('BOT_TOKEN')
    or os.environ.get('TELEGRAM_BOT_TOKEN')
    or ''
).strip()
ADMIN_TG_ID = (os.environ.get('TELEGRAM_ADMIN_CHAT_ID') or '').strip()

def send_tg_message(chat_id, text):
    if not chat_id or not TELEGRAM_BOT_TOKEN:
        logger.warning('send_tg_message skipped: Telegram token or chat_id is not configured')
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        response = requests.post(url, json=payload, timeout=5)
        return response.ok
    except Exception as e:
        logger.error('Error sending Telegram message: %s', e)
        return False

def get_or_create_tg_key(user):
    if not user.tg_auth_key:
        user.tg_auth_key = secrets.token_urlsafe(8)
        db.session.commit()
    return user.tg_auth_key
