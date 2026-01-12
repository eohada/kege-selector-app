"""
Основные маршруты удаленной админки
"""
import logging
from flask import render_template, request, redirect, url_for, flash, session, jsonify
from flask_login import login_required, current_user

from app.remote_admin import remote_admin_bp
from app.remote_admin.environment_manager import (
    get_current_environment, set_current_environment, 
    get_environment_config, is_environment_configured,
    get_all_environments_status, ENVIRONMENTS
)

logger = logging.getLogger(__name__)


@remote_admin_bp.route('/')
@login_required
def dashboard():
    """Главная страница удаленной админки"""
    # Только для создателя
    if not current_user.is_creator():
        flash('Доступ только для Создателя', 'danger')
        return redirect(url_for('main.dashboard'))
    
    current_env = get_current_environment()
    env_statuses = get_all_environments_status()
    
    return render_template('remote_admin/dashboard.html',
                         current_environment=current_env,
                         environments=ENVIRONMENTS,
                         env_statuses=env_statuses)


@remote_admin_bp.route('/environment/select', methods=['POST'])
@login_required
def select_environment():
    """Выбор окружения"""
    if not current_user.is_creator():
        flash('Доступ только для Создателя', 'danger')
        return redirect(url_for('main.dashboard'))
    
    env = request.form.get('environment', '').strip()
    
    if not env or env not in ENVIRONMENTS:
        flash('Неверное окружение', 'error')
        return redirect(url_for('remote_admin.dashboard'))
    
    if not is_environment_configured(env):
        flash(f'Окружение {ENVIRONMENTS[env]["name"]} не настроено. Проверьте переменные окружения.', 'warning')
        return redirect(url_for('remote_admin.dashboard'))
    
    if set_current_environment(env):
        flash(f'Окружение изменено на {ENVIRONMENTS[env]["name"]}', 'success')
    else:
        flash('Ошибка при изменении окружения', 'error')
    
    return redirect(url_for('remote_admin.dashboard'))


@remote_admin_bp.route('/environment/status')
@login_required
def environment_status():
    """API: Получить статус окружений"""
    if not current_user.is_creator():
        return jsonify({'error': 'Access denied'}), 403
    
    env_statuses = get_all_environments_status()
    return jsonify({
        'current': get_current_environment(),
        'environments': env_statuses
    })


@remote_admin_bp.route('/users')
@login_required
def users_list():
    """Список пользователей из выбранного окружения"""
    if not current_user.is_creator():
        flash('Доступ только для Создателя', 'danger')
        return redirect(url_for('main.dashboard'))
    
    current_env = get_current_environment()
    
    if not is_environment_configured(current_env):
        flash(f'Окружение {ENVIRONMENTS[current_env]["name"]} не настроено', 'error')
        return redirect(url_for('remote_admin.dashboard'))
    
    try:
        resp = make_remote_request('GET', '/internal/remote-admin/api/users')
        if resp.status_code == 200:
            data = resp.json()
            users = data.get('users', [])
        else:
            users = []
            flash(f'Ошибка загрузки пользователей: {resp.status_code}', 'error')
    except Exception as e:
        logger.error(f"Error loading users: {e}", exc_info=True)
        users = []
        flash(f'Ошибка загрузки пользователей: {str(e)}', 'error')
    
    return render_template('remote_admin/users_list.html',
                         users=users,
                         current_environment=current_env,
                         environment_name=ENVIRONMENTS[current_env]['name'])


@remote_admin_bp.route('/permissions')
@login_required
def permissions():
    """Управление правами доступа (через удаленный API)"""
    if not current_user.is_creator():
        flash('Доступ только для Создателя', 'danger')
        return redirect(url_for('main.dashboard'))
    
    current_env = get_current_environment()
    
    # Пока используем локальное управление правами
    # В будущем можно добавить удаленное управление
    return redirect(url_for('admin.admin_permissions'))


@remote_admin_bp.route('/audit-logs')
@login_required
def audit_logs():
    """Просмотр логов действий"""
    if not current_user.is_creator():
        flash('Доступ только для Создателя', 'danger')
        return redirect(url_for('main.dashboard'))
    
    current_env = get_current_environment()
    
    # Пока используем локальные логи
    # В будущем можно добавить удаленный просмотр
    return redirect(url_for('admin.admin_audit_logs'))


@remote_admin_bp.route('/maintenance')
@login_required
def maintenance():
    """Управление техническими работами"""
    if not current_user.is_creator():
        flash('Доступ только для Создателя', 'danger')
        return redirect(url_for('main.dashboard'))
    
    current_env = get_current_environment()
    
    # Пока используем локальное управление
    return redirect(url_for('admin.admin_maintenance'))
