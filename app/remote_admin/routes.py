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
