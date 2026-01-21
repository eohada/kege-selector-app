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


@remote_admin_bp.route('/api/users/graph')
@login_required
def api_users_graph():
    """Proxy: граф связей пользователей из выбранного окружения."""
    if not current_user.is_creator():
        return jsonify({'error': 'Access denied'}), 403

    try:
        env = get_current_environment()
        if not is_environment_configured(env):
            return jsonify({'error': f'Environment {env} is not configured'}), 400

        qs = request.query_string.decode('utf-8') if request.query_string else ''
        path = '/internal/remote-admin/api/users/graph'
        if qs:
            path = f"{path}?{qs}"

        resp = make_remote_request('GET', path)
        return jsonify(resp.json() if resp.headers.get('content-type', '').startswith('application/json') else {'error': 'Invalid response'}), resp.status_code
    except Exception as e:
        logger.error(f"Error proxying users graph: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@remote_admin_bp.route('/api/family-ties/<int:tie_id>', methods=['POST', 'DELETE'])
@login_required
def api_family_tie_manage(tie_id: int):
    """Proxy: управление FamilyTie (для графа связей)."""
    if not current_user.is_creator():
        return jsonify({'error': 'Access denied'}), 403

    try:
        env = get_current_environment()
        if not is_environment_configured(env):
            return jsonify({'error': f'Environment {env} is not configured'}), 400

        if request.method == 'DELETE':
            resp = make_remote_request('DELETE', f'/internal/remote-admin/api/family-ties/{tie_id}')
        else:
            payload = _extract_request_data()
            resp = make_remote_request('POST', f'/internal/remote-admin/api/family-ties/{tie_id}', payload=payload)

        return jsonify(resp.json() if resp.headers.get('content-type', '').startswith('application/json') else {'error': 'Invalid response'}), resp.status_code
    except Exception as e:
        logger.error(f"Error proxying family tie manage: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@remote_admin_bp.route('/api/enrollments/<int:enrollment_id>', methods=['POST', 'DELETE'])
@login_required
def api_enrollment_manage(enrollment_id: int):
    """Proxy: управление Enrollment (для графа связей)."""
    if not current_user.is_creator():
        return jsonify({'error': 'Access denied'}), 403

    try:
        env = get_current_environment()
        if not is_environment_configured(env):
            return jsonify({'error': f'Environment {env} is not configured'}), 400

        if request.method == 'DELETE':
            resp = make_remote_request('DELETE', f'/internal/remote-admin/api/enrollments/{enrollment_id}')
        else:
            payload = _extract_request_data()
            resp = make_remote_request('POST', f'/internal/remote-admin/api/enrollments/{enrollment_id}', payload=payload)

        return jsonify(resp.json() if resp.headers.get('content-type', '').startswith('application/json') else {'error': 'Invalid response'}), resp.status_code
    except Exception as e:
        logger.error(f"Error proxying enrollment manage: {e}", exc_info=True)
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
    csrf.exempt(api_users_graph)
    csrf.exempt(api_family_tie_manage)
    csrf.exempt(api_enrollment_manage)
    csrf.exempt(api_stats)


@remote_admin_bp.route('/api/task-formator/list')
@login_required
def api_task_formator_list():
    """Proxy: список заданий формироватора из выбранного окружения."""
    if not current_user.is_creator():
        return jsonify({'error': 'Access denied'}), 403

    try:
        env = get_current_environment()
        if not is_environment_configured(env):
            return jsonify({'error': f'Environment {env} is not configured'}), 400

        # forward query params
        qs = request.query_string.decode('utf-8') if request.query_string else ''
        path = '/internal/remote-admin/api/tasks/formator'
        if qs:
            path = f"{path}?{qs}"

        resp = make_remote_request('GET', path)
        return jsonify(resp.json() if resp.headers.get('content-type', '').startswith('application/json') else {'error': 'Invalid response'}), resp.status_code
    except Exception as e:
        logger.error(f"Error proxying task formator list: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@remote_admin_bp.route('/api/task-formator/task/<int:task_id>')
@login_required
def api_task_formator_task(task_id: int):
    """Proxy: карточка задания формироватора."""
    if not current_user.is_creator():
        return jsonify({'error': 'Access denied'}), 403

    try:
        env = get_current_environment()
        if not is_environment_configured(env):
            return jsonify({'error': f'Environment {env} is not configured'}), 400

        resp = make_remote_request('GET', f'/internal/remote-admin/api/tasks/formator/{task_id}')
        return jsonify(resp.json() if resp.headers.get('content-type', '').startswith('application/json') else {'error': 'Invalid response'}), resp.status_code
    except Exception as e:
        logger.error(f"Error proxying task formator task: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@remote_admin_bp.route('/api/task-formator/task/<int:task_id>/review', methods=['POST'])
@login_required
def api_task_formator_save(task_id: int):
    """Proxy: сохранить ревью задания."""
    if not current_user.is_creator():
        return jsonify({'error': 'Access denied'}), 403

    try:
        env = get_current_environment()
        if not is_environment_configured(env):
            return jsonify({'error': f'Environment {env} is not configured'}), 400

        payload = _extract_request_data()
        resp = make_remote_request('POST', f'/internal/remote-admin/api/tasks/formator/{task_id}/review', payload=payload)
        return jsonify(resp.json() if resp.headers.get('content-type', '').startswith('application/json') else {'error': 'Invalid response'}), resp.status_code
    except Exception as e:
        logger.error(f"Error proxying task formator save: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


if csrf:
    csrf.exempt(api_task_formator_list)
    csrf.exempt(api_task_formator_task)
    csrf.exempt(api_task_formator_save)
