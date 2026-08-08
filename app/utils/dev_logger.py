import os
import logging
import traceback
from datetime import datetime
from flask import request, jsonify

logger = logging.getLogger(__name__)

LOG_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'logs', 'dev_debug.log'))

def init_dev_logger(app):
    """Инициализация модуля автономного перехвата и логирования ошибок (dev_logger)."""
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

    @app.errorhandler(Exception)
    def handle_exception(e):
        tb = traceback.format_exc()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        user_obj = getattr(request, 'user', None) or getattr(request, 'current_user', None)
        username = getattr(user_obj, 'username', 'Anonymous')
        
        log_entry = (
            f"\n{'='*80}\n"
            f"❌ [{timestamp}] ERROR {getattr(e, 'code', 500)} on {request.method} {request.path}\n"
            f"📥 Query Args: {dict(request.args)}\n"
            f"📥 Payload: {request.get_json(silent=True) or (request.form.to_dict() if request.form else {})}\n"
            f"👤 User: {username}\n"
            f"💥 Exception: {str(e)}\n"
            f"📜 Traceback:\n{tb}"
            f"{'='*80}\n"
        )
        
        try:
            with open(LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(log_entry)
        except Exception as write_err:
            logger.warning(f"Could not write to dev_debug.log: {write_err}")
            
        print(log_entry)
        
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'status': 'error',
                'error_code': getattr(e, 'code', 500),
                'message': str(e),
                'traceback': tb.splitlines()[-3:] if tb else []
            }), getattr(e, 'code', 500)
            
        return e

    @app.route('/api/dev/last_error', methods=['GET'])
    def get_last_error():
        if not os.path.exists(LOG_FILE):
            return jsonify({'status': 'info', 'message': 'Лог-файл пуст, ошибок не зафиксировано.'})
        try:
            with open(LOG_FILE, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            return jsonify({'status': 'success', 'last_log': ''.join(lines[-100:])})
        except Exception as err:
            return jsonify({'status': 'error', 'message': str(err)}), 500
