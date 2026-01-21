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
        # filters (applied client-side/server-side after fetch; remote API supports role/is_active)
        q = (request.args.get('q') or '').strip().lower()
        roles_raw = (request.args.get('roles') or '').strip()
        role_single = (request.args.get('role') or '').strip()
        is_active_filter = (request.args.get('is_active') or '').strip().lower()

        selected_roles = []
        if roles_raw:
            selected_roles = [r.strip() for r in roles_raw.split(',') if r.strip()]
        elif role_single:
            selected_roles = [role_single]

        # Build query string for remote API (only single role supported there)
        api_path = '/internal/remote-admin/api/users'
        qs_parts = []
        if len(selected_roles) == 1:
            qs_parts.append(f"role={selected_roles[0]}")
        if is_active_filter in ('true', 'false'):
            qs_parts.append(f"is_active={is_active_filter}")
        if qs_parts:
            api_path = api_path + '?' + '&'.join(qs_parts)

        resp = make_remote_request('GET', api_path)
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

    # extra filtering (multi-role and query) on remote-admin side
    if users:
        if selected_roles:
            users = [u for u in users if (u.get('role') in selected_roles)]
        if q:
            def _hay(u):
                return ' '.join([
                    str(u.get('username') or ''),
                    str(u.get('email') or ''),
                    str(u.get('role') or ''),
                ]).lower()
            users = [u for u in users if q in _hay(u)]

    # stats for quick role filters (within current result set)
    role_stats = {}
    for u in users or []:
        r = (u.get('role') or 'unknown')
        role_stats[r] = role_stats.get(r, 0) + 1

    return render_template('remote_admin/users_list.html',
                         users=users,
                         role_stats=role_stats,
                         selected_roles=selected_roles,
                         q=(request.args.get('q') or '').strip(),
                         is_active_filter=(request.args.get('is_active') or '').strip().lower(),
                         current_environment=current_env,
                         environment_name=environments.get(current_env, {}).get('name', current_env))


def _get_users_by_role(role):  # comment
    """Получает список пользователей по роли через API"""  # comment
    try:  # comment
        path = f"/internal/remote-admin/api/users?role={role}&is_active=true"  # comment
        resp = make_remote_request('GET', path)  # comment
        if resp.status_code == 200:  # comment
            return resp.json().get('users', [])  # comment
    except Exception as e:  # comment
        logger.error(f"Error fetching {role}s: {e}")  # comment
    return []  # comment


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
                'is_active': request.form.get('is_active') == 'on',
                'platform_id': request.form.get('platform_id', '').strip() or None,
                'tutor_id': request.form.get('tutor_id'),
                'parent_ids': request.form.getlist('parent_ids'),
                'child_ids': request.form.getlist('child_ids')
            }
            
            if not data['username']:
                flash('Имя пользователя обязательно', 'error')
                tutors = _get_users_by_role('tutor')
                parents = _get_users_by_role('parent')
                students = _get_users_by_role('student')
                return render_template('remote_admin/user_edit.html', user=None, 
                                     current_environment=current_env,
                                     environment_name=environments.get(current_env, {}).get('name', current_env),
                                     tutors=tutors, parents=parents, students=students)
            
            if not data['password']:
                flash('Пароль обязателен', 'error')
                tutors = _get_users_by_role('tutor')
                parents = _get_users_by_role('parent')
                students = _get_users_by_role('student')
                return render_template('remote_admin/user_edit.html', user=None,
                                     current_environment=current_env,
                                     environment_name=environments.get(current_env, {}).get('name', current_env),
                                     tutors=tutors, parents=parents, students=students)
            
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
    
    # Загружаем списки для селектов
    tutors = _get_users_by_role('tutor')
    parents = _get_users_by_role('parent')
    students = _get_users_by_role('student')
    
    return render_template('remote_admin/user_edit.html', user=None,
                         current_environment=current_env,
                         environment_name=environments.get(current_env, {}).get('name', current_env),
                         tutors=tutors, parents=parents, students=students)


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
                'is_active': request.form.get('is_active') == 'on',
                'platform_id': request.form.get('platform_id', '').strip() or None,
                'tutor_id': request.form.get('tutor_id'),
                'parent_ids': request.form.getlist('parent_ids'),
                'child_ids': request.form.getlist('child_ids')
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
    
    # Загружаем списки для селектов
    tutors = _get_users_by_role('tutor')
    parents = _get_users_by_role('parent')
    students = _get_users_by_role('student')
    
    return render_template('remote_admin/user_edit.html', user=user_data,
                         current_environment=current_env,
                         environment_name=environments.get(current_env, {}).get('name', current_env),
                         tutors=tutors, parents=parents, students=students)


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
    per_page = request.args.get('per_page', 50, type=int)
    action = (request.args.get('action') or '').strip()
    entity = (request.args.get('entity') or '').strip()
    status = (request.args.get('status') or '').strip()
    date_from = (request.args.get('date_from') or '').strip()
    date_to = (request.args.get('date_to') or '').strip()
    user_id = request.args.get('user_id', type=int)
    
    try:
        query_params = f"?page={page}&per_page={per_page}"
        if action:
            query_params += f"&action={action}"
        if entity:
            query_params += f"&entity={entity}"
        if status:
            query_params += f"&status={status}"
        if user_id:
            query_params += f"&user_id={user_id}"
        if date_from:
            query_params += f"&date_from={date_from}"
        if date_to:
            query_params += f"&date_to={date_to}"
            
        resp = make_remote_request('GET', f'/internal/remote-admin/api/audit-logs{query_params}')
        
        if resp.status_code == 200:
            data = resp.json()
            logs = data.get('logs', [])
            pagination = data.get('pagination', {})
            meta = data.get('meta', {}) or {}
            actions = meta.get('actions', []) or []
            entities = meta.get('entities', []) or []
            statuses = meta.get('statuses', []) or []
        else:
            logs = []
            pagination = {}
            actions = []
            entities = []
            statuses = []
            flash(f'Ошибка загрузки логов: {resp.status_code}', 'error')
            
    except Exception as e:
        logger.error(f"Error loading audit logs: {e}", exc_info=True)
        logs = []
        pagination = {}
        actions = []
        entities = []
        statuses = []
        flash(f'Ошибка загрузки логов: {str(e)}', 'error')
    
    return render_template('remote_admin/audit_logs.html',
                         logs=logs,
                         pagination=pagination,
                         actions=actions,
                         entities=entities,
                         statuses=statuses,
                         current_environment=current_env,
                         environment_name=environments.get(current_env, {}).get('name', current_env),
                         filter_action=action,
                         filter_entity=entity,
                         filter_status=status,
                         filter_date_from=date_from,
                         filter_date_to=date_to,
                         filter_per_page=per_page,
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
    logger.info(f"Permissions page accessed: method={request.method}, user={current_user.username if current_user.is_authenticated else 'anonymous'}")
    
    if not current_user.is_creator():
        logger.warning(f"Non-creator user {current_user.username} attempted to access permissions page")
        flash('Доступ только для Создателя', 'danger')
        return redirect(url_for('main.dashboard'))
    
    current_env = get_current_environment()
    environments = get_environments()
    logger.info(f"Current environment: {current_env}")
    
    if not is_environment_configured(current_env):
        logger.warning(f"Environment {current_env} is not configured")
        flash(f'Окружение {environments.get(current_env, {}).get("name", current_env)} не настроено', 'error')
        return redirect(url_for('remote_admin.dashboard'))
    
    if request.method == 'POST':
        try:
            role = request.form.get('role', '').strip()
            permissions_list = []
            
            # Собираем все разрешения из формы (только включенные)
            for key, value in request.form.items():
                if key.startswith('perm_') and value == 'on':
                    perm_name = key[5:]  # Убираем префикс 'perm_'
                    permissions_list.append(perm_name)
            
            logger.info(f"Updating permissions for role '{role}': {len(permissions_list)} permissions")
            
            payload = {
                'role': role,
                'permissions': permissions_list  # Отправляем список, а не словарь
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
        logger.info(f"Fetching permissions from environment: {current_env}")
        resp = make_remote_request('GET', '/internal/remote-admin/api/permissions')
        logger.info(f"Permissions API response: status={resp.status_code}, content-type={resp.headers.get('Content-Type', 'unknown')}")
        
        if resp.status_code == 200:
            try:
                data = resp.json()
                logger.debug(f"Permissions data received: roles={len(data.get('roles_permissions', {}))}, all_perms={len(data.get('all_permissions', {}))}, categories={len(data.get('permission_categories', {}))}")
                roles_permissions = data.get('roles_permissions', {})
                all_permissions = data.get('all_permissions', {})  # Это словарь, не список!
                permission_categories = data.get('permission_categories', {})
            except ValueError as json_error:
                logger.error(f"Failed to parse JSON from permissions API: {json_error}. Response: {resp.text[:500]}")
                roles_permissions = {}
                all_permissions = {}
                permission_categories = {}
                flash(f'Ошибка: неверный формат ответа от сервера', 'error')
        else:
            roles_permissions = {}
            all_permissions = {}
            permission_categories = {}
            error_text = resp.text[:200] if resp.text else f'HTTP {resp.status_code}'
            logger.error(f"Permissions API returned error: {resp.status_code}, response: {error_text}")
            flash(f'Ошибка загрузки прав: {error_text}', 'error')
    except Exception as e:
        logger.error(f"Error loading permissions: {e}", exc_info=True)
        roles_permissions = {}
        all_permissions = {}
        permission_categories = {}
        flash(f'Ошибка загрузки прав: {str(e)}', 'error')
    
    try:
        # Подготавливаем данные для шаблона
        # Список ролей из roles_permissions
        roles_list = list(roles_permissions.keys()) if roles_permissions else []
        logger.info(f"Preparing template data: roles_list={len(roles_list)}, roles={roles_list}")
        
        # Группируем права по категориям
        categories_dict = {}
        if all_permissions and permission_categories:
            # Если all_permissions - это словарь вида {'perm_key': {'name': '...', 'category': '...'}}
            for perm_key, perm_data in all_permissions.items():
                if isinstance(perm_data, dict):
                    category = perm_data.get('category', 'other')
                    if category not in categories_dict:
                        categories_dict[category] = []
                    categories_dict[category].append(perm_key)
                else:
                    # Если perm_data - не словарь, используем ключ категории из permission_categories
                    category = 'other'
                    for cat_key, cat_name in permission_categories.items():
                        # Попробуем найти категорию по ключу разрешения
                        if perm_key.startswith(cat_key) or cat_key in perm_key:
                            category = cat_key
                            break
                    if category not in categories_dict:
                        categories_dict[category] = []
                    categories_dict[category].append(perm_key)
        elif all_permissions:
            # Если есть только all_permissions без категорий, создаем одну категорию
            categories_dict['other'] = list(all_permissions.keys())
        
        logger.info(f"Categories prepared: {len(categories_dict)} categories, keys: {list(categories_dict.keys())}")
        
        logger.info(f"Rendering permissions template with: roles={len(roles_list)}, all_perms={len(all_permissions)}, categories={len(categories_dict)}")
        result = render_template('remote_admin/permissions.html',
                             roles=roles_list,
                             roles_permissions=roles_permissions,
                             all_permissions=all_permissions,
                             permission_categories=permission_categories,
                             categories=categories_dict,
                             current_environment=current_env,
                             environment_name=environments.get(current_env, {}).get('name', current_env))
        logger.info(f"Permissions template rendered successfully")
        return result
    except Exception as template_error:
        logger.error(f"Error rendering permissions template: {template_error}", exc_info=True)
        flash(f'Ошибка отображения страницы: {str(template_error)}', 'error')
        return redirect(url_for('remote_admin.dashboard'))


@remote_admin_bp.route('/task-formator')
@login_required
def task_formator():
    """Формироватор банка заданий (remote-admin UI)."""
    if not current_user.is_creator():
        flash('Доступ только для Создателя', 'danger')
        return redirect(url_for('main.dashboard'))

    current_env = get_current_environment()
    environments = get_environments()

    if not is_environment_configured(current_env):
        flash(f'Окружение {environments.get(current_env, {}).get("name", current_env)} не настроено', 'error')
        return redirect(url_for('remote_admin.dashboard'))

    q = (request.args.get('q') or '').strip()
    task_number = request.args.get('task_number', type=int)
    review_status = (request.args.get('review_status') or 'all').strip().lower()
    page = max(1, request.args.get('page', type=int) or 1)

    try:
        qs = request.query_string.decode('utf-8') if request.query_string else ''
        path = '/internal/remote-admin/api/tasks/formator'
        if qs:
            path = f"{path}?{qs}"
        resp = make_remote_request('GET', path)
        if resp.status_code == 200:
            data = resp.json()
        else:
            data = {'success': False, 'items': [], 'summary': {'new': 0, 'ok': 0, 'needs_fix': 0, 'skip': 0}, 'total': 0, 'page': page, 'per_page': 30}
            flash(f'Ошибка загрузки списка заданий: {resp.status_code}', 'error')
    except Exception as e:
        logger.error(f"Error loading task formator list: {e}", exc_info=True)
        data = {'success': False, 'items': [], 'summary': {'new': 0, 'ok': 0, 'needs_fix': 0, 'skip': 0}, 'total': 0, 'page': page, 'per_page': 30}
        flash(f'Ошибка загрузки: {str(e)}', 'error')

    task_numbers = list(range(1, 28))

    return render_template(
        'remote_admin/task_formator.html',
        current_environment=current_env,
        environment_name=environments.get(current_env, {}).get('name', current_env),
        q=q,
        task_number=task_number,
        review_status=review_status,
        page=data.get('page', page),
        per_page=data.get('per_page', 30),
        total=data.get('total', 0),
        summary=data.get('summary', {'new': 0, 'ok': 0, 'needs_fix': 0, 'skip': 0}),
        items=data.get('items', []),
        task_numbers=task_numbers,
    )
