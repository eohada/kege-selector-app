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
    get_all_environments_status, get_environments,
    make_remote_request
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
    environments = get_environments()
    
    return render_template('remote_admin/dashboard.html',
                         current_environment=current_env,
                         environments=environments,
                         env_statuses=env_statuses)


@remote_admin_bp.route('/environment/select', methods=['POST'])
@login_required
def select_environment():
    """Выбор окружения"""
    if not current_user.is_creator():
        flash('Доступ только для Создателя', 'danger')
        return redirect(url_for('main.dashboard'))
    
    env = request.form.get('environment', '').strip()
    environments = get_environments()
    
    if not env or env not in environments:
        flash('Неверное окружение', 'error')
        return redirect(url_for('remote_admin.dashboard'))
    
    if not is_environment_configured(env):
        flash(f'Окружение {environments[env]["name"]} не настроено. Проверьте переменные окружения.', 'warning')
        return redirect(url_for('remote_admin.dashboard'))
    
    if set_current_environment(env):
        flash(f'Окружение изменено на {environments[env]["name"]}', 'success')
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
    environments = get_environments()
    
    if not is_environment_configured(current_env):
        flash(f'Окружение {environments.get(current_env, {}).get("name", current_env)} не настроено', 'error')
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
                         environment_name=environments.get(current_env, {}).get('name', current_env))


@remote_admin_bp.route('/users/new', methods=['GET', 'POST'])
@login_required
def user_new():
    """Создание нового пользователя"""
    if not current_user.is_creator():
        flash('Доступ только для Создателя', 'danger')
        return redirect(url_for('main.dashboard'))
    
    current_env = get_current_environment()
    environments = get_environments()
    
    if not is_environment_configured(current_env):
        flash(f'Окружение {environments.get(current_env, {}).get("name", current_env)} не настроено', 'error')
        return redirect(url_for('remote_admin.dashboard'))
    
    if request.method == 'POST':
        try:
            data = {
                'username': request.form.get('username', '').strip(),
                'email': request.form.get('email', '').strip() or None,
                'password': request.form.get('password', '').strip(),
                'role': request.form.get('role', 'student').strip(),
                'is_active': request.form.get('is_active') == 'on'
            }
            
            if not data['username']:
                flash('Имя пользователя обязательно', 'error')
                return render_template('remote_admin/user_edit.html', user=None, 
                                     current_environment=current_env,
                                     environment_name=environments.get(current_env, {}).get('name', current_env))
            
            if not data['password']:
                flash('Пароль обязателен', 'error')
                return render_template('remote_admin/user_edit.html', user=None,
                                     current_environment=current_env,
                                     environment_name=environments.get(current_env, {}).get('name', current_env))
            
            resp = make_remote_request('POST', '/internal/remote-admin/api/users', payload=data)
            
            if resp.status_code == 201:
                flash('Пользователь создан успешно', 'success')
                return redirect(url_for('remote_admin.users_list'))
            else:
                error_data = resp.json() if resp.headers.get('content-type', '').startswith('application/json') else {}
                flash(error_data.get('error', f'Ошибка создания пользователя: {resp.status_code}'), 'error')
                
        except Exception as e:
            logger.error(f"Error creating user: {e}", exc_info=True)
            flash(f'Ошибка создания пользователя: {str(e)}', 'error')
    
    return render_template('remote_admin/user_edit.html', user=None,
                         current_environment=current_env,
                         environment_name=environments.get(current_env, {}).get('name', current_env))


@remote_admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
def user_edit(user_id):
    """Редактирование пользователя"""
    if not current_user.is_creator():
        flash('Доступ только для Создателя', 'danger')
        return redirect(url_for('main.dashboard'))
    
    current_env = get_current_environment()
    environments = get_environments()
    
    if not is_environment_configured(current_env):
        flash(f'Окружение {environments.get(current_env, {}).get("name", current_env)} не настроено', 'error')
        return redirect(url_for('remote_admin.dashboard'))
    
    if request.method == 'POST':
        try:
            data = {
                'username': request.form.get('username', '').strip(),
                'email': request.form.get('email', '').strip() or None,
                'role': request.form.get('role', 'student').strip(),
                'is_active': request.form.get('is_active') == 'on'
            }
            
            # Пароль обновляется только если указан
            password = request.form.get('password', '').strip()
            if password:
                data['password'] = password
            
            resp = make_remote_request('POST', f'/internal/remote-admin/api/users/{user_id}', payload=data)
            
            if resp.status_code == 200:
                flash('Пользователь обновлен успешно', 'success')
                return redirect(url_for('remote_admin.users_list'))
            else:
                error_data = resp.json() if resp.headers.get('content-type', '').startswith('application/json') else {}
                flash(error_data.get('error', f'Ошибка обновления пользователя: {resp.status_code}'), 'error')
                
        except Exception as e:
            logger.error(f"Error updating user: {e}", exc_info=True)
            flash(f'Ошибка обновления пользователя: {str(e)}', 'error')
    
    # Загружаем данные пользователя
    try:
        resp = make_remote_request('GET', f'/internal/remote-admin/api/users/{user_id}')
        if resp.status_code == 200:
            user_data = resp.json().get('user', {})
        else:
            flash('Пользователь не найден', 'error')
            return redirect(url_for('remote_admin.users_list'))
    except Exception as e:
        logger.error(f"Error loading user: {e}", exc_info=True)
        flash(f'Ошибка загрузки пользователя: {str(e)}', 'error')
        return redirect(url_for('remote_admin.users_list'))
    
    return render_template('remote_admin/user_edit.html', user=user_data,
                         current_environment=current_env,
                         environment_name=environments.get(current_env, {}).get('name', current_env))


@remote_admin_bp.route('/testers', methods=['GET', 'POST'])
@login_required
def testers():
    """Управление тестерами"""
    if not current_user.is_creator():
        flash('Доступ только для Создателя', 'danger')
        return redirect(url_for('main.dashboard'))
    
    current_env = get_current_environment()
    environments = get_environments()
    
    if not is_environment_configured(current_env):
        flash(f'Окружение {environments.get(current_env, {}).get("name", current_env)} не настроено', 'error')
        return redirect(url_for('remote_admin.dashboard'))
    
    # Тестеры обычно только в sandbox, но дадим возможность проверить везде
    
    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            is_active = request.form.get('is_active') == 'on'
            
            if not name:
                flash('Имя обязательно', 'error')
            else:
                resp = make_remote_request('POST', '/internal/remote-admin/api/testers', payload={'name': name, 'is_active': is_active})
                if resp.status_code == 200:
                    flash('Тестер создан успешно', 'success')
                else:
                    flash(f'Ошибка создания тестера: {resp.status_code}', 'error')
                    
        except Exception as e:
            logger.error(f"Error creating tester: {e}", exc_info=True)
            flash(f'Ошибка: {str(e)}', 'error')
            
        return redirect(url_for('remote_admin.testers'))
    
    # GET - список тестеров
    try:
        resp = make_remote_request('GET', '/internal/remote-admin/api/testers')
        if resp.status_code == 200:
            testers = resp.json().get('testers', [])
        else:
            testers = []
            if resp.status_code == 501: # Not Implemented / Model not found
                flash('Управление тестерами недоступно в этом окружении', 'warning')
            else:
                flash(f'Ошибка загрузки тестеров: {resp.status_code}', 'error')
    except Exception as e:
        logger.error(f"Error loading testers: {e}", exc_info=True)
        testers = []
        flash(f'Ошибка загрузки тестеров: {str(e)}', 'error')
    
    return render_template('remote_admin/testers.html',
                         testers=testers,
                         current_environment=current_env,
                         environment_name=environments.get(current_env, {}).get('name', current_env))


@remote_admin_bp.route('/testers/<int:tester_id>/toggle', methods=['POST'])
@login_required
def tester_toggle(tester_id):
    """Переключение активности тестера"""
    if not current_user.is_creator():
        flash('Доступ только для Создателя', 'danger')
        return redirect(url_for('main.dashboard'))
    
    try:
        # Сначала получаем текущее состояние, чтобы инвертировать
        # Но у нас нет отдельного GET для одного тестера в API списка, 
        # поэтому просто передаем нужное состояние если бы знали, 
        # но проще добавить endpoint для toggle или передать is_active
        
        # В данном случае проще передать is_active из формы
        is_active = request.form.get('is_active') == 'true' # Новое состояние
        
        resp = make_remote_request('POST', f'/internal/remote-admin/api/testers/{tester_id}', payload={'is_active': is_active})
        
        if resp.status_code == 200:
            flash('Статус тестера обновлен', 'success')
        else:
            flash(f'Ошибка обновления: {resp.status_code}', 'error')
            
    except Exception as e:
        logger.error(f"Error toggling tester: {e}", exc_info=True)
        flash(f'Ошибка: {str(e)}', 'error')
        
    return redirect(url_for('remote_admin.testers'))


@remote_admin_bp.route('/testers/<int:tester_id>/delete', methods=['POST'])
@login_required
def tester_delete(tester_id):
    """Удаление тестера"""
    if not current_user.is_creator():
        flash('Доступ только для Создателя', 'danger')
        return redirect(url_for('main.dashboard'))
    
    try:
        resp = make_remote_request('DELETE', f'/internal/remote-admin/api/testers/{tester_id}')
        
        if resp.status_code == 200:
            flash('Тестер удален', 'success')
        else:
            flash(f'Ошибка удаления: {resp.status_code}', 'error')
            
    except Exception as e:
        logger.error(f"Error deleting tester: {e}", exc_info=True)
        flash(f'Ошибка: {str(e)}', 'error')
        
    return redirect(url_for('remote_admin.testers'))


@remote_admin_bp.route('/audit-logs')
@login_required
def audit_logs():
    """Просмотр логов действий из удаленного окружения"""
    if not current_user.is_creator():
        flash('Доступ только для Создателя', 'danger')
        return redirect(url_for('main.dashboard'))
    
    current_env = get_current_environment()
    environments = get_environments()
    
    if not is_environment_configured(current_env):
        flash(f'Окружение {environments.get(current_env, {}).get("name", current_env)} не настроено', 'error')
        return redirect(url_for('remote_admin.dashboard'))
    
    page = request.args.get('page', 1, type=int)
    action = request.args.get('action', '').strip()
    user_id = request.args.get('user_id', type=int)
    
    try:
        query_params = f"?page={page}"
        if action:
            query_params += f"&action={action}"
        if user_id:
            query_params += f"&user_id={user_id}"
            
        resp = make_remote_request('GET', f'/internal/remote-admin/api/audit-logs{query_params}')
        
        if resp.status_code == 200:
            data = resp.json()
            logs = data.get('logs', [])
            pagination = data.get('pagination', {})
        else:
            logs = []
            pagination = {}
            flash(f'Ошибка загрузки логов: {resp.status_code}', 'error')
            
    except Exception as e:
        logger.error(f"Error loading audit logs: {e}", exc_info=True)
        logs = []
        pagination = {}
        flash(f'Ошибка загрузки логов: {str(e)}', 'error')
    
    return render_template('remote_admin/audit_logs.html',
                         logs=logs,
                         pagination=pagination,
                         current_environment=current_env,
                         environment_name=environments.get(current_env, {}).get('name', current_env),
                         filter_action=action,
                         filter_user_id=user_id)


@remote_admin_bp.route('/maintenance', methods=['GET', 'POST'])
@login_required
def maintenance():
    """Управление техническими работами"""
    if not current_user.is_creator():
        flash('Доступ только для Создателя', 'danger')
        return redirect(url_for('main.dashboard'))
    
    current_env = get_current_environment()
    environments = get_environments()
    
    if not is_environment_configured(current_env):
        flash(f'Окружение {environments.get(current_env, {}).get("name", current_env)} не настроено', 'error')
        return redirect(url_for('remote_admin.dashboard'))
    
    if request.method == 'POST':
        try:
            action = request.form.get('action')
            
            if action == 'toggle':
                enabled = request.form.get('enabled') == 'on'
                message = request.form.get('message', '').strip()
                # allowed_ips = request.form.get('allowed_ips', '').strip() # В будущем можно добавить
                
                payload = {
                    'enabled': enabled,
                    'message': message
                }
                
                resp = make_remote_request('POST', '/internal/remote-admin/api/maintenance', payload=payload)
                
                if resp.status_code == 200:
                    status = "включен" if enabled else "выключен"
                    flash(f'Режим обслуживания {status}', 'success')
                else:
                    flash(f'Ошибка изменения режима: {resp.status_code}', 'error')
            
        except Exception as e:
            logger.error(f"Error updating maintenance mode: {e}", exc_info=True)
            flash(f'Ошибка: {str(e)}', 'error')
            
        return redirect(url_for('remote_admin.maintenance'))
    
    # GET запрос - получаем текущий статус
    try:
        resp = make_remote_request('GET', '/internal/remote-admin/api/maintenance')
        if resp.status_code == 200:
            status = resp.json().get('status', {})
        else:
            status = {}
            flash(f'Ошибка получения статуса: {resp.status_code}', 'error')
    except Exception as e:
        logger.error(f"Error getting maintenance status: {e}", exc_info=True)
        status = {}
        flash(f'Ошибка: {str(e)}', 'error')
    
    return render_template('remote_admin/maintenance.html',
                         status=status,
                         current_environment=current_env,
                         environment_name=environments.get(current_env, {}).get('name', current_env))


@remote_admin_bp.route('/permissions', methods=['GET', 'POST'])
@login_required
def permissions():
    """Управление правами доступа (RBAC)"""
    if not current_user.is_creator():
        flash('Доступ только для Создателя', 'danger')
        return redirect(url_for('main.dashboard'))
    
    current_env = get_current_environment()
    environments = get_environments()
    
    if not is_environment_configured(current_env):
        flash(f'Окружение {environments.get(current_env, {}).get("name", current_env)} не настроено', 'error')
        return redirect(url_for('remote_admin.dashboard'))
    
    if request.method == 'POST':
        try:
            role = request.form.get('role', '').strip()
            permissions_data = {}
            
            # Собираем все разрешения из формы
            for key, value in request.form.items():
                if key.startswith('perm_'):
                    perm_name = key[5:]  # Убираем префикс 'perm_'
                    permissions_data[perm_name] = value == 'on'
            
            payload = {
                'role': role,
                'permissions': permissions_data
            }
            
            resp = make_remote_request('POST', '/internal/remote-admin/api/permissions', payload=payload)
            
            if resp.status_code == 200:
                flash('Права обновлены успешно', 'success')
            else:
                error_data = resp.json() if resp.headers.get('content-type', '').startswith('application/json') else {}
                flash(error_data.get('error', f'Ошибка обновления прав: {resp.status_code}'), 'error')
                
        except Exception as e:
            logger.error(f"Error updating permissions: {e}", exc_info=True)
            flash(f'Ошибка: {str(e)}', 'error')
            
        return redirect(url_for('remote_admin.permissions'))
    
    # GET запрос - получаем текущие права
    try:
        resp = make_remote_request('GET', '/internal/remote-admin/api/permissions')
        if resp.status_code == 200:
            data = resp.json()
            roles_permissions = data.get('roles_permissions', {})
            all_permissions = data.get('all_permissions', [])
            permission_categories = data.get('permission_categories', {})
        else:
            roles_permissions = {}
            all_permissions = []
            permission_categories = {}
            flash(f'Ошибка загрузки прав: {resp.status_code}', 'error')
    except Exception as e:
        logger.error(f"Error loading permissions: {e}", exc_info=True)
        roles_permissions = {}
        all_permissions = []
        permission_categories = {}
        flash(f'Ошибка загрузки прав: {str(e)}', 'error')
    
    return render_template('remote_admin/permissions.html',
                         roles_permissions=roles_permissions,
                         all_permissions=all_permissions,
                         permission_categories=permission_categories,
                         current_environment=current_env,
                         environment_name=environments.get(current_env, {}).get('name', current_env))
