import os
import requests
import secrets
from core.db_models import db, User

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8992987768:AAGMSCNlX4l4a2IRdWuY54PlM8SprAWea6A")
ADMIN_TG_ID = "854161398"

def send_tg_message(chat_id, text):
    if not chat_id:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Error sending TG msg: {e}")

def get_or_create_tg_key(user):
    if not user.tg_auth_key:
        user.tg_auth_key = secrets.token_urlsafe(8)
        db.session.commit()
    return user.tg_auth_key
