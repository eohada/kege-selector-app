"""
Маршруты администрирования
"""
import logging
import csv
from io import StringIO
from datetime import datetime, timedelta
from flask import render_template, request, redirect, url_for, flash, make_response, jsonify
from flask_login import login_required, current_user
from sqlalchemy import func, delete
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.admin import admin_bp
from app.models import User, AuditLog, MaintenanceMode, db, moscow_now, MOSCOW_TZ
from core.audit_logger import audit_logger

logger = logging.getLogger(__name__)

@admin_bp.route('/admin')
@login_required
def admin_panel():
    """Админ панель (только для создателя)"""
    if not current_user.is_creator():
        flash('Доступ запрещен. Требуется роль "Создатель".', 'danger')
        return redirect(url_for('main.dashboard'))
    
    try:
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
        
        return render_template('admin_panel.html',
                             total_users=total_users,
                             active_users=active_users,
                             creators_count=creators_count,
                             testers_count=testers_count,
                             total_logs=total_logs,
                             today_logs=today_logs,
                             maintenance_enabled=maintenance_status.is_enabled,
                             maintenance_message=maintenance_status.message)
    except Exception as e:
        logger.error(f"Error in admin_panel route: {e}", exc_info=True)
        flash(f'Ошибка при загрузке статистики: {str(e)}', 'error')
        try:
            total_users = User.query.count()
            active_users = User.query.filter_by(is_active=True).count()
            creators_count = User.query.filter_by(role='creator').count()
            testers_count = User.query.filter_by(role='tester').count()
            return render_template('admin_panel.html',
                                 total_users=total_users,
                                 active_users=active_users,
                                 creators_count=creators_count,
                                 testers_count=testers_count,
                                 total_logs=0,
                                 today_logs=0)
        except Exception as e2:
            logger.error(f"Error in fallback: {e2}", exc_info=True)
            flash('Критическая ошибка при загрузке данных', 'error')
            return redirect(url_for('main.dashboard'))

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
    status = MaintenanceMode.get_status()
    return render_template('maintenance.html', message=status.message)

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
