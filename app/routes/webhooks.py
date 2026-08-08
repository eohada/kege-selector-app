import logging
import threading
from flask import Blueprint, request, jsonify, current_app
from app import csrf

logger = logging.getLogger(__name__)

webhooks_bp = Blueprint('webhooks', __name__)

def _process_update_async(app_context, data, bot_type):
    with app_context:
        try:
            if bot_type == 'main':
                from app.bots.main_bot import process_main_bot_update
                process_main_bot_update(data)
            elif bot_type == 'qa':
                from app.bots.qa_bot import process_qa_bot_update
                process_qa_bot_update(data)
        except Exception as e:
            logger.error(f"[{bot_type.upper()} BOT ASYNC ERROR]: {e}", exc_info=True)

@webhooks_bp.route('/api/webhooks/main-bot', methods=['POST'])
@csrf.exempt  # 🛑 CRITICAL: Telegram POST payloads do not carry Flask CSRF token!
def main_bot_webhook():
    try:
        data = request.get_json(force=True, silent=True)
        if data:
            app_ctx = current_app._get_current_object().app_context()
            threading.Thread(
                target=_process_update_async,
                args=(app_ctx, data, 'main'),
                daemon=True
            ).start()
        return jsonify({'ok': True, 'status': 'ok'}), 200
    except Exception as e:
        logger.error(f"[MAIN BOT WEBHOOK ERROR]: {e}", exc_info=True)
        return jsonify({'ok': False, 'status': 'error', 'message': str(e)}), 200

@webhooks_bp.route('/api/webhooks/qa-bot', methods=['POST'])
@csrf.exempt
def qa_bot_webhook():
    try:
        data = request.get_json(force=True, silent=True)
        if data:
            app_ctx = current_app._get_current_object().app_context()
            threading.Thread(
                target=_process_update_async,
                args=(app_ctx, data, 'qa'),
                daemon=True
            ).start()
        return jsonify({'ok': True, 'status': 'ok'}), 200
    except Exception as e:
        logger.error(f"[QA BOT WEBHOOK ERROR]: {e}", exc_info=True)
        return jsonify({'ok': False, 'status': 'error', 'message': str(e)}), 200
