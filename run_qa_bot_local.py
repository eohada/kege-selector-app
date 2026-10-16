import os
import sys
import time
import requests
import logging

# Ensure root directory is on PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app import create_app
from app.bots.qa_bot import process_qa_bot_update

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("qa_bot_local")
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BOT_TOKEN = (
    os.environ.get("QA_BOT_TOKEN")
    or os.environ.get("TELEGRAM_TESTERS_BOT_TOKEN")
    or ""
).strip()
if BOT_TOKEN:
    os.environ["QA_BOT_TOKEN"] = BOT_TOKEN

def run_polling():
    if not BOT_TOKEN:
        logger.error("ОШИБКА: QA_BOT_TOKEN или TELEGRAM_TESTERS_BOT_TOKEN не задан в .env или переменных окружения!")
        sys.exit(1)

    app = create_app()
    logger.info("🚀 Starting local Telegram Long-Polling for QA bot...")
    
    # 1. Delete Webhook to allow getUpdates
    try:
        resp = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook", timeout=10)
        logger.info(f"Webhook deleted response: {resp.json()}")
    except Exception as e:
        logger.error(f"Failed to delete webhook: {e}")

    offset = 0
    with app.app_context():
        while True:
            try:
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={offset}&timeout=20"
                res = requests.get(url, timeout=25)
                if res.status_code == 200:
                    data = res.json()
                    if data.get("ok"):
                        for update in data.get("result", []):
                            update_id = update["update_id"]
                            offset = update_id + 1
                            logger.info(f"Processing Telegram update {update_id}")
                            try:
                                process_qa_bot_update(update)
                            except Exception as ex:
                                logger.error(f"Error processing update {update_id}: {ex}", exc_info=True)
                else:
                    logger.warning(f"getUpdates returned HTTP {res.status_code}: {res.text}")
                    time.sleep(2)
            except requests.exceptions.Timeout:
                continue
            except KeyboardInterrupt:
                logger.info("Poller stopped by user.")
                break
            except Exception as e:
                logger.error(f"Polling loop error: {e}")
                time.sleep(3)

if __name__ == "__main__":
    run_polling()
