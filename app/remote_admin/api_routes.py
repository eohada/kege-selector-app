"""
API маршруты для удаленной админки
Все запросы идут через удаленные API окружений
"""
import logging
from flask import request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user

from app.remote_admin import remote_admin_bp
from app.remote_admin.environment_manager import (
    get_current_environment, make_remote_request, 
    get_environment_config, is_environment_configured
)

# Импортируем csrf для исключения API endpoints из CSRF защиты
try:
    from app import csrf
    if csrf:
        # Исключаем все API endpoints из CSRF защиты
        pass  # Будем использовать декоратор @csrf.exempt
except ImportError:
    csrf = None

logger = logging.getLogger(__name__)


def _extract_request_data():
    """Получить данные из JSON или form-data безопасно"""  # comment
    data = request.get_json(silent=True)  # comment
    if data is not None:  # comment
        return data  # comment
    if not request.form:  # comment
        return {}  # comment
    raw_form = request.form.to_dict(flat=False)  # comment
    normalized = {}  # comment
    for key, values in raw_form.items():  # comment
        if key in ('parent_ids', 'child_ids'):  # comment
            normalized[key] = values  # comment
        else:  # comment
            normalized[key] = values[0] if values else ''  # comment
    return normalized  # comment


@remote_admin_bp.route('/api/users')
@login_required
def api_users_list():
    """Получить список пользователей из выбранного окружения"""
    if not current_user.is_creator():
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        env = get_current_environment()
        if not is_environment_configured(env):
            return jsonify({'error': f'Environment {env} is not configured'}), 400
        
        resp = make_remote_request('GET', '/internal/remote-admin/api/users')
        
        if resp.status_code == 200:
            return jsonify(resp.json())
        else:
            return jsonify({'error': f'API returned {resp.status_code}'}), resp.status_code
            
    except Exception as e:
        logger.error(f"Error fetching users: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@remote_admin_bp.route('/api/users/<int:user_id>', methods=['GET', 'POST', 'DELETE'])
@login_required
def api_user_manage(user_id):
    """Управление пользователем (GET, POST для обновления, DELETE для удаления)"""
    if not current_user.is_creator():
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        env = get_current_environment()
        if not is_environment_configured(env):
            return jsonify({'error': f'Environment {env} is not configured'}), 400
        
        method = request.method
        
        if method == 'GET':
            resp = make_remote_request('GET', f'/internal/remote-admin/api/users/{user_id}')
        elif method == 'POST':
            data = _extract_request_data()  # comment
            resp = make_remote_request('POST', f'/internal/remote-admin/api/users/{user_id}', payload=data)
        elif method == 'DELETE':
            resp = make_remote_request('DELETE', f'/internal/remote-admin/api/users/{user_id}')
        else:
            return jsonify({'error': 'Method not allowed'}), 405
        
        if resp.status_code == 200:
            return jsonify(resp.json())
        else:
            return jsonify({'error': f'API returned {resp.status_code}'}), resp.status_code
            
    except Exception as e:
        logger.error(f"Error managing user: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@remote_admin_bp.route('/api/stats')
@login_required
def api_stats():
    """Получить статистику из выбранного окружения"""
    if not current_user.is_creator():
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        env = get_current_environment()
        if not is_environment_configured(env):
            return jsonify({'error': f'Environment {env} is not configured'}), 400
        
        resp = make_remote_request('GET', '/internal/remote-admin/api/stats')
        
        if resp.status_code == 200:
            return jsonify(resp.json())
        else:
            return jsonify({'error': f'API returned {resp.status_code}'}), resp.status_code
            
    except Exception as e:
        logger.error(f"Error fetching stats: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

# Исключаем все API endpoints из CSRF защиты после определения функций
if csrf:
    csrf.exempt(api_users_list)
    csrf.exempt(api_user_manage)
    csrf.exempt(api_stats)
