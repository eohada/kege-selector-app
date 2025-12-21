"""
Маршруты администрирования
"""
import logging
import csv
from io import StringIO
from datetime import datetime, timedelta
import os  # Окружение (ENVIRONMENT/RAILWAY_ENVIRONMENT) для безопасных ограничений. # comment
import hmac
import requests
from flask import render_template, request, redirect, url_for, flash, make_response, jsonify
from flask_login import login_required, current_user
from sqlalchemy import func, delete
from sqlalchemy.exc import OperationalError, ProgrammingError
from werkzeug.security import generate_password_hash  # Хешируем пароль как в scripts/create_tester_user.py. # comment

from app.admin import admin_bp
from app.models import User, AuditLog, MaintenanceMode, db, moscow_now, MOSCOW_TZ, Tasks, Lesson, LessonTask
from core.db_models import Tester
from core.audit_logger import audit_logger

logger = logging.getLogger(__name__)


def _get_environment():
    environment = os.environ.get('ENVIRONMENT', 'local')
    railway_environment = os.environ.get('RAILWAY_ENVIRONMENT', '')
    return environment, railway_environment


def _is_production(environment: str, railway_environment: str) -> bool:
    return environment == 'production' or ('production' in railway_environment.lower() and 'sandbox' not in railway_environment.lower())


def _is_sandbox(environment: str, railway_environment: str) -> bool:
    return environment == 'sandbox' or 'sandbox' in railway_environment.lower()


def _sandbox_remote_config():
    base_url = (os.environ.get('SANDBOX_ADMIN_URL') or '').strip().rstrip('/')
    token = (os.environ.get('SANDBOX_ADMIN_TOKEN') or '').strip()
    return base_url, token


def _sandbox_remote_request(method: str, path: str, payload=None):
    base_url, token = _sandbox_remote_config()
    if not base_url or not token:
        raise RuntimeError('Sandbox remote admin is not configured')

    url = f"{base_url}{path}"
    headers = {'X-Admin-Token': token, 'User-Agent': 'Prod-Admin/1.0'}
    timeout = 8

    if method.upper() == 'GET':
        return requests.get(url, headers=headers, timeout=timeout)

    return requests.post(url, headers=headers, json=(payload or {}), timeout=timeout)


def _sandbox_internal_guard():
    environment, railway_environment = _get_environment()
    if not _is_sandbox(environment, railway_environment):
        return False

    expected = (os.environ.get('SANDBOX_ADMIN_TOKEN') or '').strip()
    if not expected:
        return False

    provided = (request.headers.get('X-Admin-Token') or '').strip()
    return hmac.compare_digest(provided, expected)

@admin_bp.route('/admin')
@login_required
def admin_panel():
    """Админ панель (только для создателя)"""
    if not current_user.is_creator():
        flash('Доступ запрещен. Требуется роль "Создатель".', 'danger')
        return redirect(url_for('main.dashboard'))
    
    try:
        environment, railway_environment = _get_environment()
        is_production = _is_production(environment, railway_environment)

        total_users = User.query.count()
        active_users = User.query.filter_by(is_active=True).count()
        creators_count = User.query.filter_by(role='creator').count()
        testers_count = User.query.filter_by(role='tester').count()
        
        # Статистика по логам - с обработкой ошибок
        try:
            db.session.query(AuditLog).limit(1).all()
            audit_log_exists = True
        except (OperationalError, ProgrammingError) as e:
            logger.warning(f"AuditLog table not found or not accessible: {e}")
            db.session.rollback()
            audit_log_exists = False
        
        if audit_log_exists:
            try:
                total_logs = AuditLog.query.count()
                today_logs = AuditLog.query.filter(
                    func.date(AuditLog.timestamp) == func.current_date()
                ).count()
            except Exception as e:
                logger.error(f"Error querying AuditLog statistics: {e}", exc_info=True)
                db.session.rollback()
                total_logs = 0
                today_logs = 0
        else:
            total_logs = 0
            today_logs = 0
        
        # Получаем статус тех работ
        maintenance_status = MaintenanceMode.get_status()

        sandbox_summary = None
        sandbox_error = None
        sandbox_base_url, _ = _sandbox_remote_config()
        if is_production and sandbox_base_url:
            try:
                resp = _sandbox_remote_request('GET', '/internal/sandbox-admin/summary')
                content_type = (resp.headers.get('Content-Type') or '').lower()
                if resp.status_code == 200 and 'application/json' in content_type:
                    sandbox_summary = resp.json()
                else:
                    preview = (resp.text or '')[:200]
                    sandbox_error = f"Sandbox API error: {resp.status_code} {content_type} {preview}"
            except Exception as e:
                sandbox_error = str(e)
        
        return render_template('admin_panel.html',
                             total_users=total_users,
                             active_users=active_users,
                             creators_count=creators_count,
                             testers_count=testers_count,
                             total_logs=total_logs,
                             today_logs=today_logs,
                             maintenance_enabled=maintenance_status.is_enabled,
                             maintenance_message=maintenance_status.message,
                             environment=environment,
                             is_production=is_production,
                             sandbox_base_url=sandbox_base_url,
                             sandbox_summary=sandbox_summary,
                             sandbox_error=sandbox_error)
    except Exception as e:
        logger.error(f"Error in admin_panel route: {e}", exc_info=True)
        flash(f'Ошибка при загрузке статистики: {str(e)}', 'error')
        try:
            environment, railway_environment = _get_environment()
            is_production = _is_production(environment, railway_environment)

            total_users = User.query.count()
            active_users = User.query.filter_by(is_active=True).count()
            creators_count = User.query.filter_by(role='creator').count()
            testers_count = User.query.filter_by(role='tester').count()

            sandbox_summary = None
            sandbox_error = None
            sandbox_base_url, _ = _sandbox_remote_config()
            if is_production and sandbox_base_url:
                try:
                    resp = _sandbox_remote_request('GET', '/internal/sandbox-admin/summary')
                    content_type = (resp.headers.get('Content-Type') or '').lower()
                    if resp.status_code == 200 and 'application/json' in content_type:
                        sandbox_summary = resp.json()
                    else:
                        preview = (resp.text or '')[:200]
                        sandbox_error = f"Sandbox API error: {resp.status_code} {content_type} {preview}"
                except Exception as e:
                    sandbox_error = str(e)

            return render_template('admin_panel.html',
                                 total_users=total_users,
                                 active_users=active_users,
                                 creators_count=creators_count,
                                 testers_count=testers_count,
                                 total_logs=0,
                                 today_logs=0,
                                 environment=environment,
                                 is_production=is_production,
                                 sandbox_base_url=sandbox_base_url,
                                 sandbox_summary=sandbox_summary,
                                 sandbox_error=sandbox_error)
        except Exception as e2:
            logger.error(f"Error in fallback: {e2}", exc_info=True)
            flash('Критическая ошибка при загрузке данных', 'error')
            return redirect(url_for('main.dashboard'))


@admin_bp.route('/admin-testers/create', methods=['POST'])
@login_required
def admin_testers_create():
    """Создание user-тестировщика (username + password) - только для создателя."""  # Докстринг маршрута. # comment
    if not current_user.is_creator():  # Проверяем права доступа. # comment
        flash('Доступ запрещен. Требуется роль "Создатель".', 'danger')  # Сообщаем об отказе. # comment
        return redirect(url_for('main.dashboard'))  # Возвращаем в основной раздел. # comment

    username = (request.form.get('username') or '').strip()  # Имя пользователя из формы. # comment
    password = request.form.get('password') or ''  # Пароль из формы (сырой, только для хеширования). # comment
    allow_update = request.form.get('allow_update') == 'on'  # Разрешение обновлять существующего пользователя. # comment
    force_production = request.form.get('force_production') == 'on'  # Явное подтверждение для production. # comment

    if not username:  # Валидация имени. # comment
        flash('Имя пользователя обязательно.', 'error')  # Показываем ошибку. # comment
        return redirect(url_for('admin.admin_panel'))  # Возвращаем на админ-панель. # comment

    if not password:  # Валидация пароля. # comment
        flash('Пароль обязателен.', 'error')  # Показываем ошибку. # comment
        return redirect(url_for('admin.admin_panel'))  # Возвращаем на админ-панель. # comment

    environment = os.environ.get('ENVIRONMENT', 'local')  # Текущее окружение приложения. # comment
    railway_environment = os.environ.get('RAILWAY_ENVIRONMENT', '')  # Окружение Railway (если есть). # comment
    is_production = environment == 'production' or ('production' in railway_environment.lower() and 'sandbox' not in railway_environment.lower())  # Признак production. # comment

    if is_production and not force_production:  # В production блокируем без явного подтверждения. # comment
        flash('Тестировщиков нельзя создавать в production без подтверждения. Включите чекбокс "force production".', 'danger')  # Предупреждаем. # comment
        return redirect(url_for('admin.admin_panel'))  # Возвращаем на админ-панель. # comment

    try:  # Основной блок создания/обновления. # comment
        user = User.query.filter_by(username=username).first()  # Ищем пользователя по имени. # comment

        if user and not allow_update:  # Если пользователь уже есть, но апдейт запрещён. # comment
            flash('Пользователь с таким именем уже существует. Включите "обновить существующего", если хотите перезаписать пароль.', 'warning')  # Подсказка. # comment
            return redirect(url_for('admin.admin_panel'))  # Возвращаем на админ-панель. # comment

        if user:  # Ветка обновления существующего пользователя. # comment
            old_role = user.role  # Запоминаем старую роль для аудита. # comment
            user.password_hash = generate_password_hash(password)  # Обновляем хеш пароля. # comment
            user.role = 'tester'  # Проставляем роль тестировщика. # comment
            user.is_active = True  # Активируем пользователя. # comment
            db.session.commit()  # Фиксируем изменения. # comment

            audit_logger.log(  # Пишем событие аудита. # comment
                action='update_user_password',  # Тип действия. # comment
                entity='User',  # Сущность. # comment
                entity_id=user.id,  # Идентификатор сущности. # comment
                status='success',  # Статус операции. # comment
                metadata={'username': username, 'old_role': old_role, 'new_role': 'tester'}  # Метаданные. # comment
            )  # Конец audit_logger.log. # comment

            flash(f'Тестировщик "{username}" обновлён (пароль перезаписан).', 'success')  # Уведомляем об успехе. # comment
            return redirect(url_for('admin.admin_panel'))  # Возвращаем на админ-панель. # comment

        user = User(  # Создаём нового пользователя. # comment
            username=username,  # Имя пользователя. # comment
            password_hash=generate_password_hash(password),  # Хеш пароля. # comment
            role='tester',  # Роль тестировщика. # comment
            is_active=True,  # Активный пользователь. # comment
            created_at=moscow_now()  # Дата создания. # comment
        )  # Конец инициализации User. # comment
        db.session.add(user)  # Добавляем в сессию. # comment
        db.session.commit()  # Сохраняем в БД. # comment

        audit_logger.log(  # Пишем событие аудита. # comment
            action='create_user',  # Тип действия. # comment
            entity='User',  # Сущность. # comment
            entity_id=user.id,  # Идентификатор сущности. # comment
            status='success',  # Статус операции. # comment
            metadata={'username': username, 'role': 'tester'}  # Метаданные. # comment
        )  # Конец audit_logger.log. # comment

        flash(f'Тестировщик "{username}" создан.', 'success')  # Уведомляем об успехе. # comment
        return redirect(url_for('admin.admin_panel'))  # Возвращаем на админ-панель. # comment
    except Exception as e:  # Обрабатываем любые ошибки. # comment
        db.session.rollback()  # Откатываем транзакцию. # comment
        logger.error(f"Error creating tester user: {e}", exc_info=True)  # Логируем ошибку. # comment
        flash(f'Ошибка при создании тестировщика: {str(e)}', 'error')  # Показываем ошибку. # comment
        return redirect(url_for('admin.admin_panel'))  # Возвращаем на админ-панель. # comment


@admin_bp.route('/admin/sandbox/user-tester/create', methods=['POST'])
@login_required
def admin_sandbox_user_tester_create():
    if not current_user.is_creator():
        flash('Доступ запрещен. Требуется роль "Создатель".', 'danger')
        return redirect(url_for('main.dashboard'))

    username = (request.form.get('username') or '').strip()
    password = request.form.get('password') or ''
    allow_update = request.form.get('allow_update') == 'on'

    if not username or not password:
        flash('Логин и пароль обязательны.', 'error')
        return redirect(url_for('admin.admin_panel'))

    try:
        resp = _sandbox_remote_request('POST', '/internal/sandbox-admin/user-tester', {
            'username': username,
            'password': password,
            'allow_update': allow_update,
        })
        data = resp.json() if resp.headers.get('Content-Type', '').startswith('application/json') else {}
        if resp.status_code == 200 and data.get('success'):
            flash(f'Sandbox: тестировщик "{username}" создан/обновлён.', 'success')
        else:
            flash(f"Sandbox: ошибка создания: {data.get('error') or resp.text}", 'error')
    except Exception as e:
        flash(f'Sandbox: ошибка запроса: {str(e)}', 'error')

    return redirect(url_for('admin.admin_panel'))


@admin_bp.route('/admin/sandbox/user/<int:user_id>/set-password', methods=['POST'])
@login_required
def admin_sandbox_user_set_password(user_id):
    if not current_user.is_creator():
        flash('Доступ запрещен. Требуется роль "Создатель".', 'danger')
        return redirect(url_for('main.dashboard'))

    password = request.form.get('password') or ''
    if not password:
        flash('Пароль обязателен.', 'error')
        return redirect(url_for('admin.admin_panel'))

    try:
        resp = _sandbox_remote_request('POST', f'/internal/sandbox-admin/user/{user_id}/set-password', {'password': password})
        data = resp.json() if resp.headers.get('Content-Type', '').startswith('application/json') else {}
        if resp.status_code == 200 and data.get('success'):
            flash('Sandbox: пароль обновлён.', 'success')
        else:
            flash(f"Sandbox: ошибка обновления пароля: {data.get('error') or resp.text}", 'error')
    except Exception as e:
        flash(f'Sandbox: ошибка запроса: {str(e)}', 'error')

    return redirect(url_for('admin.admin_panel'))


@admin_bp.route('/admin/sandbox/user/<int:user_id>/toggle-active', methods=['POST'])
@login_required
def admin_sandbox_user_toggle_active(user_id):
    if not current_user.is_creator():
        flash('Доступ запрещен. Требуется роль "Создатель".', 'danger')
        return redirect(url_for('main.dashboard'))

    try:
        resp = _sandbox_remote_request('POST', f'/internal/sandbox-admin/user/{user_id}/toggle-active', {})
        data = resp.json() if resp.headers.get('Content-Type', '').startswith('application/json') else {}
        if resp.status_code == 200 and data.get('success'):
            flash('Sandbox: статус обновлён.', 'success')
        else:
            flash(f"Sandbox: ошибка обновления статуса: {data.get('error') or resp.text}", 'error')
    except Exception as e:
        flash(f'Sandbox: ошибка запроса: {str(e)}', 'error')

    return redirect(url_for('admin.admin_panel'))


@admin_bp.route('/admin/sandbox/user/<int:user_id>/delete', methods=['POST'])
@login_required
def admin_sandbox_user_delete(user_id):
    if not current_user.is_creator():
        flash('Доступ запрещен. Требуется роль "Создатель".', 'danger')
        return redirect(url_for('main.dashboard'))

    try:
        resp = _sandbox_remote_request('POST', f'/internal/sandbox-admin/user/{user_id}/delete', {})
        data = resp.json() if resp.headers.get('Content-Type', '').startswith('application/json') else {}
        if resp.status_code == 200 and data.get('success'):
            flash('Sandbox: пользователь удалён.', 'success')
        else:
            flash(f"Sandbox: ошибка удаления: {data.get('error') or resp.text}", 'error')
    except Exception as e:
        flash(f'Sandbox: ошибка запроса: {str(e)}', 'error')

    return redirect(url_for('admin.admin_panel'))


@admin_bp.route('/admin/sandbox/tester-entity/create', methods=['POST'])
@login_required
def admin_sandbox_tester_entity_create():
    if not current_user.is_creator():
        flash('Доступ запрещен. Требуется роль "Создатель".', 'danger')
        return redirect(url_for('main.dashboard'))

    name = (request.form.get('name') or '').strip()
    is_active = request.form.get('is_active') == 'on'
    if not name:
        flash('Имя обязательно.', 'error')
        return redirect(url_for('admin.admin_panel'))

    try:
        resp = _sandbox_remote_request('POST', '/internal/sandbox-admin/tester-entity', {'name': name, 'is_active': is_active})
        data = resp.json() if resp.headers.get('Content-Type', '').startswith('application/json') else {}
        if resp.status_code == 200 and data.get('success'):
            flash('Sandbox: tester entity создан.', 'success')
        else:
            flash(f"Sandbox: ошибка создания tester entity: {data.get('error') or resp.text}", 'error')
    except Exception as e:
        flash(f'Sandbox: ошибка запроса: {str(e)}', 'error')

    return redirect(url_for('admin.admin_panel'))


@admin_bp.route('/admin/sandbox/tester-entity/<tester_id>/toggle-active', methods=['POST'])
@login_required
def admin_sandbox_tester_entity_toggle_active(tester_id):
    if not current_user.is_creator():
        flash('Доступ запрещен. Требуется роль "Создатель".', 'danger')
        return redirect(url_for('main.dashboard'))

    try:
        resp = _sandbox_remote_request('POST', f'/internal/sandbox-admin/tester-entity/{tester_id}/toggle-active', {})
        data = resp.json() if resp.headers.get('Content-Type', '').startswith('application/json') else {}
        if resp.status_code == 200 and data.get('success'):
            flash('Sandbox: tester entity обновлён.', 'success')
        else:
            flash(f"Sandbox: ошибка обновления tester entity: {data.get('error') or resp.text}", 'error')
    except Exception as e:
        flash(f'Sandbox: ошибка запроса: {str(e)}', 'error')

    return redirect(url_for('admin.admin_panel'))


@admin_bp.route('/admin/sandbox/tester-entity/<tester_id>/delete', methods=['POST'])
@login_required
def admin_sandbox_tester_entity_delete(tester_id):
    if not current_user.is_creator():
        flash('Доступ запрещен. Требуется роль "Создатель".', 'danger')
        return redirect(url_for('main.dashboard'))

    try:
        resp = _sandbox_remote_request('POST', f'/internal/sandbox-admin/tester-entity/{tester_id}/delete', {})
        data = resp.json() if resp.headers.get('Content-Type', '').startswith('application/json') else {}
        if resp.status_code == 200 and data.get('success'):
            flash('Sandbox: tester entity удалён.', 'success')
        else:
            flash(f"Sandbox: ошибка удаления tester entity: {data.get('error') or resp.text}", 'error')
    except Exception as e:
        flash(f'Sandbox: ошибка запроса: {str(e)}', 'error')

    return redirect(url_for('admin.admin_panel'))


@admin_bp.route('/internal/sandbox-admin/summary', methods=['GET'])
def sandbox_internal_summary():
    if not _sandbox_internal_guard():
        return jsonify({'success': False, 'error': 'not found'}), 404

    users_rows = db.session.query(
        User,
        func.count(AuditLog.id).label('logs_count'),
        func.max(AuditLog.timestamp).label('last_action')
    ).outerjoin(
        AuditLog, User.id == AuditLog.user_id
    ).filter(
        User.role == 'tester'
    ).group_by(
        User.id
    ).order_by(
        User.id.desc()
    ).limit(300).all()

    testers_rows = db.session.query(
        Tester,
        func.count(AuditLog.id).label('logs_count'),
        func.max(AuditLog.timestamp).label('last_action')
    ).outerjoin(
        AuditLog, Tester.tester_id == AuditLog.tester_id
    ).group_by(
        Tester.tester_id
    ).order_by(
        Tester.last_seen.desc()
    ).limit(300).all()

    users = []
    for user, logs_count, last_action in users_rows:
        users.append({
            'id': user.id,
            'username': user.username,
            'role': user.role,
            'is_active': bool(user.is_active),
            'created_at': user.created_at.isoformat() if user.created_at else None,
            'last_login': user.last_login.isoformat() if user.last_login else None,
            'logs_count': int(logs_count or 0),
            'last_action': last_action.isoformat() if last_action else None,
        })

    tester_entities = []
    for tester, logs_count, last_action in testers_rows:
        tester_entities.append({
            'tester_id': tester.tester_id,
            'name': tester.name,
            'is_active': bool(tester.is_active),
            'first_seen': tester.first_seen.isoformat() if tester.first_seen else None,
            'last_seen': tester.last_seen.isoformat() if tester.last_seen else None,
            'logs_count': int(logs_count or 0),
            'last_action': last_action.isoformat() if last_action else None,
        })

    return jsonify({'success': True, 'users': users, 'tester_entities': tester_entities}), 200


@admin_bp.route('/internal/sandbox-admin/user-tester', methods=['POST'])
def sandbox_internal_user_tester_create():
    if not _sandbox_internal_guard():
        return jsonify({'success': False, 'error': 'not found'}), 404

    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    allow_update = bool(data.get('allow_update'))

    if not username or not password:
        return jsonify({'success': False, 'error': 'username and password required'}), 400

    user = User.query.filter_by(username=username).first()
    if user and not allow_update:
        return jsonify({'success': False, 'error': 'user exists'}), 409

    try:
        if user:
            user.password_hash = generate_password_hash(password)
            user.role = 'tester'
            user.is_active = True
            db.session.commit()
            return jsonify({'success': True, 'updated': True, 'user_id': user.id}), 200

        user = User(username=username, password_hash=generate_password_hash(password), role='tester', is_active=True, created_at=moscow_now())
        db.session.add(user)
        db.session.commit()
        return jsonify({'success': True, 'created': True, 'user_id': user.id}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/internal/sandbox-admin/user/<int:user_id>/set-password', methods=['POST'])
def sandbox_internal_user_set_password(user_id):
    if not _sandbox_internal_guard():
        return jsonify({'success': False, 'error': 'not found'}), 404

    data = request.get_json(silent=True) or {}
    password = data.get('password') or ''
    if not password:
        return jsonify({'success': False, 'error': 'password required'}), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({'success': False, 'error': 'user not found'}), 404

    if user.is_creator():
        return jsonify({'success': False, 'error': 'cannot change creator password'}), 403

    try:
        user.password_hash = generate_password_hash(password)
        db.session.commit()
        return jsonify({'success': True}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/internal/sandbox-admin/user/<int:user_id>/toggle-active', methods=['POST'])
def sandbox_internal_user_toggle_active(user_id):
    if not _sandbox_internal_guard():
        return jsonify({'success': False, 'error': 'not found'}), 404

    user = User.query.get(user_id)
    if not user:
        return jsonify({'success': False, 'error': 'user not found'}), 404

    if user.is_creator():
        return jsonify({'success': False, 'error': 'cannot disable creator'}), 403

    try:
        user.is_active = not bool(user.is_active)
        db.session.commit()
        return jsonify({'success': True, 'is_active': bool(user.is_active)}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/internal/sandbox-admin/user/<int:user_id>/delete', methods=['POST'])
def sandbox_internal_user_delete(user_id):
    if not _sandbox_internal_guard():
        return jsonify({'success': False, 'error': 'not found'}), 404

    user = User.query.get(user_id)
    if not user:
        return jsonify({'success': False, 'error': 'user not found'}), 404

    if user.is_creator():
        return jsonify({'success': False, 'error': 'cannot delete creator'}), 403

    try:
        db.session.delete(user)
        db.session.commit()
        return jsonify({'success': True}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/internal/sandbox-admin/tester-entity', methods=['POST'])
def sandbox_internal_tester_entity_create():
    if not _sandbox_internal_guard():
        return jsonify({'success': False, 'error': 'not found'}), 404

    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    is_active = bool(data.get('is_active', True))
    if not name:
        return jsonify({'success': False, 'error': 'name required'}), 400

    existing = Tester.query.filter_by(name=name).first()
    if existing:
        return jsonify({'success': False, 'error': 'tester entity exists'}), 409

    import uuid
    tester = Tester(tester_id=str(uuid.uuid4()), name=name, is_active=is_active)
    try:
        db.session.add(tester)
        db.session.commit()
        return jsonify({'success': True, 'tester_id': tester.tester_id}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/internal/sandbox-admin/tester-entity/<tester_id>/toggle-active', methods=['POST'])
def sandbox_internal_tester_entity_toggle_active(tester_id):
    if not _sandbox_internal_guard():
        return jsonify({'success': False, 'error': 'not found'}), 404

    tester = Tester.query.get(tester_id)
    if not tester:
        return jsonify({'success': False, 'error': 'tester entity not found'}), 404

    try:
        tester.is_active = not bool(tester.is_active)
        db.session.commit()
        return jsonify({'success': True, 'is_active': bool(tester.is_active)}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/internal/sandbox-admin/tester-entity/<tester_id>/delete', methods=['POST'])
def sandbox_internal_tester_entity_delete(tester_id):
    if not _sandbox_internal_guard():
        return jsonify({'success': False, 'error': 'not found'}), 404

    tester = Tester.query.get(tester_id)
    if not tester:
        return jsonify({'success': False, 'error': 'tester entity not found'}), 404

    try:
        db.session.delete(tester)
        db.session.commit()
        return jsonify({'success': True}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@admin_bp.route('/admin-audit')
@login_required
def admin_audit():
    """Журнал аудита (только для создателя)"""
    if not current_user.is_creator():
        flash('Доступ запрещен. Требуется роль "Создатель".', 'danger')
        return redirect(url_for('main.dashboard'))

    try:
        # Проверяем, существует ли таблица AuditLog
        try:
            db.session.query(AuditLog).limit(1).all()
            audit_log_exists = True
        except (OperationalError, ProgrammingError) as e:
            logger.warning(f"AuditLog table not found or not accessible: {e}")
            db.session.rollback()
            audit_log_exists = False
        
        if not audit_log_exists:
            users = User.query.order_by(User.id).all()
            return render_template('admin_audit.html',
                                 logs=[],
                                 pagination=None,
                                 stats={
                                     'total_events': 0,
                                     'total_testers': 0,
                                     'error_count': 0,
                                     'today_events': 0
                                 },
                                 filters={},
                                 actions=[],
                                 entities=[],
                                 users=users)

        user_id = request.args.get('user_id', '')
        action = request.args.get('action', '')
        entity = request.args.get('entity', '')
        status = request.args.get('status', '')
        date_from = request.args.get('date_from', '')
        date_to = request.args.get('date_to', '')

        query = AuditLog.query.filter(AuditLog.user_id.isnot(None))

        if user_id:
            try:
                user_id_int = int(user_id)
                query = query.filter(AuditLog.user_id == user_id_int)
            except:
                pass
        if action:
            query = query.filter(AuditLog.action == action)
        if entity:
            query = query.filter(AuditLog.entity == entity)
        if status:
            query = query.filter(AuditLog.status == status)
        if date_from:
            try:
                date_from_obj = datetime.strptime(date_from, '%Y-%m-%dT%H:%M')
                query = query.filter(AuditLog.timestamp >= date_from_obj)
            except:
                pass
        if date_to:
            try:
                date_to_obj = datetime.strptime(date_to, '%Y-%m-%dT%H:%M')
                query = query.filter(AuditLog.timestamp <= date_to_obj)
            except:
                pass

        try:
            total_events = AuditLog.query.filter(AuditLog.user_id.isnot(None)).count()
        except Exception as e:
            logger.warning(f"Error getting total_events: {e}")
            db.session.rollback()
            total_events = 0
        
        total_testers = User.query.count()
        
        try:
            error_count = AuditLog.query.filter(AuditLog.status == 'error', AuditLog.user_id.isnot(None)).count()
        except Exception as e:
            logger.warning(f"Error getting error_count: {e}")
            db.session.rollback()
            error_count = 0

        today_start = datetime.now(MOSCOW_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            today_events = AuditLog.query.filter(AuditLog.timestamp >= today_start, AuditLog.user_id.isnot(None)).count()
        except Exception as e:
            logger.warning(f"Error getting today_events: {e}")
            db.session.rollback()
            today_events = 0

        try:
            actions = db.session.query(AuditLog.action).filter(AuditLog.user_id.isnot(None)).distinct().order_by(AuditLog.action).all()
            actions = [a[0] for a in actions if a[0]]
        except Exception as e:
            logger.warning(f"Error getting actions: {e}")
            db.session.rollback()
            actions = []
        
        try:
            entities = db.session.query(AuditLog.entity).filter(AuditLog.user_id.isnot(None)).distinct().order_by(AuditLog.entity).all()
            entities = [e[0] for e in entities if e[0]]
        except Exception as e:
            logger.warning(f"Error getting entities: {e}")
            db.session.rollback()
            entities = []
        
        users = User.query.order_by(User.id).all()

        page = request.args.get('page', 1, type=int)
        per_page = 50
        try:
            pagination = query.order_by(AuditLog.timestamp.desc()).paginate(page=page, per_page=per_page, error_out=False)
            logs = pagination.items
        except Exception as e:
            logger.warning(f"Error getting pagination: {e}")
            db.session.rollback()
            logs = []
            pagination = None

        filters = {
            'user_id': user_id,
            'action': action,
            'entity': entity,
            'status': status,
            'date_from': date_from,
            'date_to': date_to
        }

        return render_template('admin_audit.html',
                             logs=logs,
                             pagination=pagination,
                             stats={
                                 'total_events': total_events,
                                 'total_testers': 0,
                                 'error_count': error_count,
                                 'today_events': today_events
                             },
                             filters=filters,
                             actions=actions,
                             entities=entities,
                             users=users)
    except Exception as e:
        logger.error(f"Error in admin_audit route: {e}", exc_info=True)
        db.session.rollback()
        flash(f'Ошибка при загрузке журнала аудита: {str(e)}', 'error')
        try:
            users = User.query.order_by(User.id).all()
            return render_template('admin_audit.html',
                                 logs=[],
                                 pagination=None,
                                 stats={
                                     'total_events': 0,
                                     'total_testers': 0,
                                     'error_count': 0,
                                     'today_events': 0
                                 },
                                 filters={},
                                 actions=[],
                                 entities=[],
                                 users=users)
        except Exception as e2:
            logger.error(f"Error in fallback: {e2}", exc_info=True)
            db.session.rollback()
            flash('Критическая ошибка при загрузке данных', 'error')
            return redirect(url_for('admin.admin_panel'))

@admin_bp.route('/admin-testers')
@login_required
def admin_testers():
    """Управление пользователями (только для создателя)"""
    logger.info(f"admin_testers route called by user: {current_user.username if current_user.is_authenticated else 'anonymous'}")
    
    if not current_user.is_creator():
        logger.warning(f"Access denied to admin_testers for user: {current_user.username if current_user.is_authenticated else 'anonymous'}")
        flash('Доступ запрещен. Требуется роль "Создатель".', 'danger')
        return redirect(url_for('main.dashboard'))
    
    try:
        logger.info("Starting admin_testers query")
        
        # Проверяем, существует ли таблица AuditLog
        try:
            db.session.query(AuditLog).limit(1).all()
            audit_log_exists = True
        except (OperationalError, ProgrammingError) as e:
            logger.warning(f"AuditLog table not found or not accessible: {e}")
            db.session.rollback()
            audit_log_exists = False
        
        if audit_log_exists:
            try:
                users = db.session.query(
                    User,
                    func.count(AuditLog.id).label('logs_count'),
                    func.max(AuditLog.timestamp).label('last_action')
                ).outerjoin(
                    AuditLog, User.id == AuditLog.user_id
                ).group_by(
                    User.id
                ).order_by(
                    User.id.desc()
                ).all()
            except Exception as e:
                logger.error(f"Error querying users with AuditLog: {e}", exc_info=True)
                db.session.rollback()
                users = [(user, 0, None) for user in User.query.order_by(User.id.desc()).all()]
        else:
            users = [(user, 0, None) for user in User.query.order_by(User.id.desc()).all()]
        
        logger.info(f"admin_testers: found {len(users)} users, rendering template")
        return render_template('admin_testers.html', users=users)
    except Exception as e:
        logger.error(f"Error in admin_testers route: {e}", exc_info=True)
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        db.session.rollback()
        flash(f'Ошибка при загрузке данных: {str(e)}', 'error')
        try:
            users = [(user, 0, None) for user in User.query.order_by(User.id.desc()).all()]
            return render_template('admin_testers.html', users=users)
        except Exception as e2:
            db.session.rollback()
            logger.error(f"Error in fallback: {e2}", exc_info=True)
            flash('Критическая ошибка при загрузке данных', 'error')
            return redirect(url_for('admin.admin_panel'))

@admin_bp.route('/admin-testers/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_testers_edit(user_id):
    """Редактирование пользователя (только для создателя)"""
    if not current_user.is_creator():
        flash('Доступ запрещен. Требуется роль "Создатель".', 'danger')
        return redirect(url_for('main.dashboard'))
    
    user = User.query.get_or_404(user_id)
    
    if request.method == 'POST':
        new_username = request.form.get('username', '').strip()
        new_role = request.form.get('role', 'tester')
        
        if not new_username:
            flash('Имя пользователя не может быть пустым', 'error')
            return redirect(url_for('admin.admin_testers_edit', user_id=user_id))
        
        old_username = user.username
        old_role = user.role
        
        if user.is_creator() and new_role != 'creator':
            flash('Нельзя изменить роль создателя', 'error')
            return redirect(url_for('admin.admin_testers_edit', user_id=user_id))
        
        user.username = new_username
        user.role = new_role
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise
        
        audit_logger.log(
            action='edit_user',
            entity='User',
            entity_id=user_id,
            status='success',
            metadata={
                'old_username': old_username,
                'new_username': new_username,
                'old_role': old_role,
                'new_role': new_role
            }
        )
        
        flash(f'Пользователь "{new_username}" обновлен', 'success')
        return redirect(url_for('admin.admin_testers'))
    
    return render_template('admin_testers_edit.html', user=user)

@admin_bp.route('/admin-testers/<int:user_id>/delete', methods=['POST'])
@login_required
def admin_testers_delete(user_id):
    """Удаление пользователя (только для создателя)"""
    if not current_user.is_creator():
        flash('Доступ запрещен. Требуется роль "Создатель".', 'danger')
        return redirect(url_for('main.dashboard'))
    
    user = User.query.get_or_404(user_id)
    
    if user.is_creator():
        flash('Нельзя удалить создателя', 'error')
        return redirect(url_for('admin.admin_testers'))
    
    username = user.username
    
    try:
        try:
            deleted_logs = db.session.execute(
                delete(AuditLog).where(AuditLog.user_id == user_id)
            ).rowcount
        except Exception as e:
            logger.warning(f"Error deleting user logs: {e}")
            db.session.rollback()
            deleted_logs = 0
        
        db.session.delete(user)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise
        
        audit_logger.log(
            action='delete_user',
            entity='User',
            entity_id=user_id,
            status='success',
            metadata={
                'username': username,
                'deleted_logs': deleted_logs
            }
        )
        
        flash(f'Пользователь "{username}" и {deleted_logs} его логов удалены', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при удалении пользователя: {e}')
        flash(f'Ошибка при удалении: {str(e)}', 'error')
    
    return redirect(url_for('admin.admin_testers'))

@admin_bp.route('/admin-testers/clear-all', methods=['POST'])
@login_required
def admin_testers_clear_all():
    """Очистить все логи пользователей (только для создателя)"""
    if not current_user.is_creator():
        flash('Доступ запрещен. Требуется роль "Создатель".', 'danger')
        return redirect(url_for('main.dashboard'))
    
    try:
        try:
            logs_count = AuditLog.query.filter(AuditLog.user_id.isnot(None)).count()
        except Exception as e:
            logger.warning(f"Error getting logs_count: {e}")
            db.session.rollback()
            logs_count = 0
        
        if logs_count == 0:
            flash('Нет логов для очистки', 'info')
            return redirect(url_for('admin.admin_testers'))
        
        try:
            deleted_logs = db.session.execute(
                delete(AuditLog).where(AuditLog.user_id.isnot(None))
            ).rowcount
            db.session.commit()
        except Exception as e:
            logger.error(f"Error deleting logs: {e}")
            db.session.rollback()
            raise
        
        audit_logger.log(
            action='clear_all_user_logs',
            entity='AuditLog',
            entity_id=None,
            status='success',
            metadata={
                'deleted_logs': deleted_logs
            }
        )
        
        flash(f'Удалено {deleted_logs} логов пользователей', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при очистке логов: {e}')
        flash(f'Ошибка при очистке: {str(e)}', 'error')
    
    return redirect(url_for('admin.admin_testers'))

@admin_bp.route('/admin-audit/export')
@login_required
def admin_audit_export():
    """Экспорт журнала аудита в CSV"""
    if not current_user.is_creator():
        flash('Доступ запрещен. Требуется роль "Создатель".', 'danger')
        return redirect(url_for('main.dashboard'))

    from sqlalchemy.exc import OperationalError, ProgrammingError

    try:
        try:
            db.session.query(AuditLog).limit(1).all()
            audit_log_exists = True
        except (OperationalError, ProgrammingError) as e:
            logger.warning(f"AuditLog table not found or not accessible: {e}")
            db.session.rollback()
            audit_log_exists = False
        
        if not audit_log_exists:
            flash('Таблица AuditLog недоступна', 'error')
            return redirect(url_for('admin.admin_audit'))
        
        query = AuditLog.query
        user_id = request.args.get('user_id', '')
        action = request.args.get('action', '')
        entity = request.args.get('entity', '')
        status = request.args.get('status', '')

        if user_id:
            try:
                user_id_int = int(user_id)
                query = query.filter(AuditLog.user_id == user_id_int)
            except:
                pass
        if action:
            query = query.filter(AuditLog.action == action)
        if entity:
            query = query.filter(AuditLog.entity == entity)
        if status:
            query = query.filter(AuditLog.status == status)

        logs = query.order_by(AuditLog.timestamp.desc()).limit(10000).all()
    except Exception as e:
        logger.error(f"Error in admin_audit_export: {e}", exc_info=True)
        db.session.rollback()
        flash(f'Ошибка при экспорте: {str(e)}', 'error')
        return redirect(url_for('admin.admin_audit'))

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Время', 'Пользователь', 'Действие', 'Сущность', 'ID сущности', 'Статус', 'URL', 'Метод', 'IP', 'Длительность (мс)', 'Метаданные'])

    for log in logs:
        user_name = None
        if log.user_id:
            user = User.query.get(log.user_id)
            user_name = user.username if user else f'User {log.user_id}'
        
        writer.writerow([
            log.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            user_name or 'Anonymous',
            log.action,
            log.entity or '',
            log.entity_id or '',
            log.status,
            log.url or '',
            log.method or '',
            log.ip_address or '',
            log.duration_ms or '',
            log.meta_data or ''
        ])

    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename=audit_logs_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    return response

@admin_bp.route('/maintenance')
def maintenance_page():
    """Страница технических работ"""
    # Приоритет: 1) сообщение из query параметра (от редиректа), 2) сообщение из БД, 3) дефолтное
    message_from_query = request.args.get('message', '').strip()
    status = MaintenanceMode.get_status()
    
    if message_from_query:
        message = message_from_query
        logger.debug(f"Maintenance page: using message from query parameter: '{message[:50]}'")
    elif status.message:
        message = status.message
        logger.debug(f"Maintenance page: using message from DB: '{message[:50]}'")
    else:
        message = 'В настоящее время ведутся технические работы. Пожалуйста, зайдите позже.'
        logger.debug(f"Maintenance page: using default message")
    
    return render_template('maintenance.html', message=message)

@admin_bp.route('/api/maintenance-status')
def maintenance_status_api():
    """Публичный API для проверки статуса тех работ (используется песочницей) - без авторизации"""
    try:
        status = MaintenanceMode.get_status()
        response_data = {
            'enabled': status.is_enabled,
            'message': status.message or 'Ведутся технические работы. Скоро вернемся!'
        }
        logger.debug(f"Maintenance status API called: enabled={status.is_enabled}")
        return jsonify(response_data), 200
    except Exception as e:
        logger.error(f'Ошибка при получении статуса тех работ: {e}', exc_info=True)
        return jsonify({'enabled': False, 'message': ''}), 500

@admin_bp.route('/admin/maintenance/toggle', methods=['POST'])
@login_required
def toggle_maintenance():
    """Переключение режима технических работ (только для создателя)"""
    if not current_user.is_creator():
        flash('Доступ запрещен. Требуется роль "Создатель".', 'danger')
        return redirect(url_for('main.dashboard'))
    
    import os
    environment = os.environ.get('ENVIRONMENT', 'local')
    railway_environment = os.environ.get('RAILWAY_ENVIRONMENT', '')
    is_production = environment == 'production' or ('production' in railway_environment.lower() and 'sandbox' not in railway_environment.lower())
    
    try:
        status = MaintenanceMode.get_status()
        status.is_enabled = not status.is_enabled
        status.updated_by = current_user.id
        db.session.commit()
        
        # В продакшене: устанавливаем переменную окружения для песочницы через Railway API
        # Но так как мы не можем напрямую менять переменные окружения другого сервиса,
        # используем другой подход: сохраняем статус в БД, а песочница будет проверять БД продакшена
        # Или проще: используем переменную окружения MAINTENANCE_ENABLED, которую нужно установить вручную в Railway
        
        if is_production:
            # В продакшене: песочница автоматически проверит статус через API /api/maintenance-status
            # Убедитесь, что в песочнице установлена переменная окружения PRODUCTION_URL с URL продакшена
            if status.is_enabled:
                flash(f'Режим технических работ включен. Песочница автоматически проверит статус через API. Убедитесь, что в песочнице установлена переменная PRODUCTION_URL.', 'success')
            else:
                flash(f'Режим технических работ выключен. Песочница автоматически получит обновление через API.', 'success')
        else:
            flash(f'Режим технических работ {"включен" if status.is_enabled else "выключен"}', 'success')
        
        audit_logger.log(
            action='toggle_maintenance',
            entity='MaintenanceMode',
            entity_id=status.id,
            status='success',
            metadata={
                'is_enabled': status.is_enabled,
                'updated_by': current_user.username,
                'environment': environment
            }
        )
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при переключении режима тех работ: {e}')
        flash(f'Ошибка при переключении: {str(e)}', 'error')
    
    return redirect(url_for('admin.admin_panel'))

@admin_bp.route('/admin/maintenance/update-message', methods=['POST'])
@login_required
def update_maintenance_message():
    """Обновление сообщения на странице тех работ (только для создателя)"""
    if not current_user.is_creator():
        flash('Доступ запрещен. Требуется роль "Создатель".', 'danger')
        return redirect(url_for('main.dashboard'))
    
    try:
        message = request.form.get('message', '').strip()
        status = MaintenanceMode.get_status()
        status.message = message if message else 'Ведутся технические работы. Пожалуйста, зайдите позже.'
        status.updated_by = current_user.id
        db.session.commit()
        
        audit_logger.log(
            action='update_maintenance_message',
            entity='MaintenanceMode',
            entity_id=status.id,
            status='success',
            metadata={
                'message': message,
                'updated_by': current_user.username
            }
        )
        
        flash('Сообщение обновлено', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при обновлении сообщения: {e}')
        flash(f'Ошибка при обновлении: {str(e)}', 'error')
    
    return redirect(url_for('admin.admin_panel'))


@admin_bp.route('/admin/debug-export')
@login_required
def debug_export():
    """Отладочный инструмент для проверки экспорта заданий в Markdown"""
    if not current_user.is_creator():
        flash('Доступ запрещен. Требуется роль "Создатель".', 'danger')
        return redirect(url_for('main.dashboard'))
    
    # Получаем параметры из запроса
    task_id = request.args.get('task_id', type=int)
    task_number = request.args.get('task_number', type=int)
    custom_html = request.args.get('custom_html', '')
    
    # Получаем список номеров заданий (1-27)
    available_numbers = sorted([n for n in range(1, 28) if Tasks.query.filter_by(task_number=n).first()])
    
    # Получаем список заданий для выбора
    tasks_list = []
    
    if task_id:
        task = Tasks.query.get(task_id)
        if task:
            tasks_list = [task]
            task_number = task.task_number  # Устанавливаем номер для отображения
    elif task_number:
        # Получаем до 10 заданий выбранного номера
        tasks_list = Tasks.query.filter_by(task_number=task_number).order_by(Tasks.task_id.desc()).limit(10).all()
    
    # Если передан task_id или custom_html, обрабатываем экспорт
    original_html = ''
    exported_markdown = ''
    task_info = None
    
    if custom_html:
        # Тестируем с пользовательским HTML
        original_html = custom_html
        from app.lessons.export import html_to_text
        try:
            exported_markdown = html_to_text(custom_html)
        except Exception as e:
            exported_markdown = f"Ошибка при экспорте: {str(e)}"
    elif task_id:
        task = Tasks.query.get(task_id)
        if task:
            task_info = {
                'task_id': task.task_id,
                'task_number': task.task_number,
                'site_task_id': task.site_task_id
            }
            original_html = task.content_html or ''
            # Импортируем и вызываем функцию экспорта
            from app.lessons.export import html_to_text
            try:
                exported_markdown = html_to_text(original_html)
            except Exception as e:
                exported_markdown = f"Ошибка при экспорте: {str(e)}"
    
    return render_template('admin/debug_export.html',
                         tasks_list=tasks_list,
                         available_numbers=available_numbers,
                         task_number=task_number,
                         original_html=original_html,
                         exported_markdown=exported_markdown,
                         task_info=task_info,
                         selected_task_id=task_id)


@admin_bp.route('/admin/tester-entities')
@login_required
def admin_tester_entities():
    """Управление тестировщиками (модель Tester) - только для создателя"""
    if not current_user.is_creator():
        flash('Доступ запрещен. Требуется роль "Создатель".', 'danger')
        return redirect(url_for('main.dashboard'))
    
    try:
        environment, railway_environment = _get_environment()
        is_production = _is_production(environment, railway_environment)
        sandbox_base_url, _ = _sandbox_remote_config()

        # Получаем всех тестировщиков с количеством логов
        query = db.session.query(
            Tester,
            func.count(AuditLog.id).label('logs_count'),
            func.max(AuditLog.timestamp).label('last_action')
        ).outerjoin(
            AuditLog, Tester.tester_id == AuditLog.tester_id
        )
        
        # Всегда скрываем legacy записи "Anonymous" (это не "профили", а исторический мусор)
        query = query.filter(Tester.name != 'Anonymous')
        
        testers = query.group_by(
            Tester.tester_id
        ).order_by(
            Tester.last_seen.desc()
        ).all()
        
        # Показываем только созданные вручную записи; Anonymous держим отдельно для очистки
        anonymous_count = Tester.query.filter_by(name='Anonymous').count()
        
        return render_template('admin/tester_entities.html', 
                             testers=testers,
                             anonymous_count=anonymous_count,
                             is_production=is_production,
                             sandbox_base_url=sandbox_base_url)
    except Exception as e:
        logger.error(f"Error in admin_tester_entities: {e}", exc_info=True)
        db.session.rollback()
        flash('Ошибка при загрузке списка тестировщиков.', 'error')
        return redirect(url_for('admin.admin_panel'))


@admin_bp.route('/admin/tester-entities/create', methods=['GET', 'POST'])
@login_required
def admin_tester_entities_create():
    """Создание нового тестировщика - только для создателя"""
    if not current_user.is_creator():
        flash('Доступ запрещен. Требуется роль "Создатель".', 'danger')
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            if not name:
                flash('Имя тестировщика обязательно.', 'error')
                return render_template('admin/tester_entities_form.html', tester=None)
            
            # Проверяем, нет ли уже тестировщика с таким именем
            existing = Tester.query.filter_by(name=name).first()
            if existing:
                flash('Тестировщик с таким именем уже существует.', 'error')
                return render_template('admin/tester_entities_form.html', tester=None)
            
            # Создаем нового тестировщика
            import uuid
            tester = Tester(
                tester_id=str(uuid.uuid4()),
                name=name,
                ip_address=request.form.get('ip_address', '').strip() or None,
                user_agent=request.form.get('user_agent', '').strip() or None,
                session_id=request.form.get('session_id', '').strip() or None,
                is_active=request.form.get('is_active') == 'on'
            )
            
            db.session.add(tester)
            db.session.commit()
            
            audit_logger.log(
                action='create',
                entity='Tester',
                entity_id=tester.tester_id,
                status='success',
                metadata={'name': tester.name}
            )
            
            flash(f'Тестировщик "{tester.name}" успешно создан.', 'success')
            return redirect(url_for('admin.admin_tester_entities'))
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating tester: {e}", exc_info=True)
            flash('Ошибка при создании тестировщика.', 'error')
            return render_template('admin/tester_entities_form.html', tester=None)
    
    return render_template('admin/tester_entities_form.html', tester=None)


@admin_bp.route('/admin/tester-entities/<tester_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_tester_entities_edit(tester_id):
    """Редактирование тестировщика - только для создателя"""
    if not current_user.is_creator():
        flash('Доступ запрещен. Требуется роль "Создатель".', 'danger')
        return redirect(url_for('main.dashboard'))
    
    tester = Tester.query.get_or_404(tester_id)
    
    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            if not name:
                flash('Имя тестировщика обязательно.', 'error')
                return render_template('admin/tester_entities_form.html', tester=tester)
            
            # Проверяем, нет ли другого тестировщика с таким именем
            existing = Tester.query.filter(Tester.name == name, Tester.tester_id != tester_id).first()
            if existing:
                flash('Тестировщик с таким именем уже существует.', 'error')
                return render_template('admin/tester_entities_form.html', tester=tester)
            
            # Обновляем данные
            old_name = tester.name
            tester.name = name
            tester.ip_address = request.form.get('ip_address', '').strip() or None
            tester.user_agent = request.form.get('user_agent', '').strip() or None
            tester.session_id = request.form.get('session_id', '').strip() or None
            tester.is_active = request.form.get('is_active') == 'on'
            
            db.session.commit()
            
            audit_logger.log(
                action='update',
                entity='Tester',
                entity_id=tester.tester_id,
                status='success',
                metadata={'old_name': old_name, 'new_name': tester.name}
            )
            
            flash(f'Тестировщик "{tester.name}" успешно обновлен.', 'success')
            return redirect(url_for('admin.admin_tester_entities'))
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating tester: {e}", exc_info=True)
            flash('Ошибка при обновлении тестировщика.', 'error')
            return render_template('admin/tester_entities_form.html', tester=tester)
    
    return render_template('admin/tester_entities_form.html', tester=tester)


@admin_bp.route('/admin/tester-entities/<tester_id>/delete', methods=['POST'])
@login_required
def admin_tester_entities_delete(tester_id):
    """Удаление тестировщика - только для создателя"""
    if not current_user.is_creator():
        flash('Доступ запрещен. Требуется роль "Создатель".', 'danger')
        return redirect(url_for('main.dashboard'))
    
    tester = Tester.query.get_or_404(tester_id)
    tester_name = tester.name
    
    try:
        # Удаляем связанные логи (опционально, можно оставить)
        # AuditLog.query.filter_by(tester_id=tester_id).delete()
        
        db.session.delete(tester)
        db.session.commit()
        
        audit_logger.log(
            action='delete',
            entity='Tester',
            entity_id=tester_id,
            status='success',
            metadata={'name': tester_name}
        )
        
        flash(f'Тестировщик "{tester_name}" успешно удален.', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting tester: {e}", exc_info=True)
        flash('Ошибка при удалении тестировщика.', 'error')
    
    return redirect(url_for('admin.admin_tester_entities'))


@admin_bp.route('/admin/tester-entities/delete-anonymous', methods=['POST'])
@login_required
def admin_tester_entities_delete_anonymous():
    """Массовое удаление всех записей Anonymous - только для создателя"""
    if not current_user.is_creator():
        flash('Доступ запрещен. Требуется роль "Создатель".', 'danger')
        return redirect(url_for('main.dashboard'))
    
    try:
        # Находим все записи с именем "Anonymous"
        anonymous_testers = Tester.query.filter_by(name='Anonymous').all()
        count = len(anonymous_testers)
        
        if count == 0:
            flash('Записи Anonymous не найдены.', 'info')
            return redirect(url_for('admin.admin_tester_entities'))
        
        # Удаляем все записи
        for tester in anonymous_testers:
            db.session.delete(tester)
        
        db.session.commit()
        
        audit_logger.log(
            action='bulk_delete',
            entity='Tester',
            entity_id=None,
            status='success',
            metadata={'count': count, 'name_filter': 'Anonymous'}
        )
        
        flash(f'Удалено {count} автоматически созданных записей «Anonymous».', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting anonymous testers: {e}", exc_info=True)
        flash('Ошибка при удалении записей Anonymous.', 'error')
    
    return redirect(url_for('admin.admin_tester_entities'))
