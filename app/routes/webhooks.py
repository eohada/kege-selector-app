import logging
import hmac
import os
from flask import Blueprint, request, jsonify
from app import csrf

logger = logging.getLogger(__name__)

webhooks_bp = Blueprint('webhooks', __name__)

def _webhook_secret(bot_type: str) -> str:
    return (
        os.environ.get(f'TELEGRAM_{bot_type.upper()}_WEBHOOK_SECRET')
        or os.environ.get('TELEGRAM_WEBHOOK_SECRET')
        or ''
    ).strip()


def _authorize_webhook(bot_type: str):
    if request.content_length and request.content_length > 256 * 1024:
        return jsonify({'ok': False, 'error': 'payload_too_large'}), 413
    if os.environ.get('FLASK_ENV') == 'testing':
        return None
    secret = _webhook_secret(bot_type)
    if not secret:
        return jsonify({'ok': False, 'error': 'webhook_disabled'}), 404
    provided = request.headers.get('X-Telegram-Bot-Api-Secret-Token', '')
    if not hmac.compare_digest(provided, secret):
        return jsonify({'ok': False, 'error': 'unauthorized'}), 403
    return None

@webhooks_bp.route('/api/webhooks/main-bot', methods=['POST'])
@csrf.exempt  # 🛑 CRITICAL: Telegram POST payloads do not carry Flask CSRF token!
def main_bot_webhook():
    denied = _authorize_webhook('main')
    if denied:
        return denied
    try:
        data = request.get_json(force=True, silent=True)
        if data is not None and not isinstance(data, dict):
            return jsonify({'ok': False, 'status': 'invalid_payload'}), 400
        if data:
            from app.bots.main_bot import process_main_bot_update
            process_main_bot_update(data)
        return jsonify({'ok': True, 'status': 'ok'}), 200
    except Exception as e:
        logger.error(f"[MAIN BOT WEBHOOK ERROR]: {e}", exc_info=True)
        return jsonify({'ok': False, 'status': 'error'}), 500

@webhooks_bp.route('/api/webhooks/qa-bot', methods=['POST'])
@csrf.exempt
def qa_bot_webhook():
    denied = _authorize_webhook('qa')
    if denied:
        return denied
    try:
        data = request.get_json(force=True, silent=True)
        if data is not None and not isinstance(data, dict):
            return jsonify({'ok': False, 'status': 'invalid_payload'}), 400
        if data:
            from app.bots.qa_bot import process_qa_bot_update
            process_qa_bot_update(data)
        return jsonify({'ok': True, 'status': 'ok'}), 200
    except Exception as e:
        logger.error(f"[QA BOT WEBHOOK ERROR]: {e}", exc_info=True)
        return jsonify({'ok': False, 'status': 'error'}), 500
