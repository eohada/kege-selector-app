"""
Внутренние API endpoints для удаленной админки
Доступны из production и sandbox окружений для управления через remote_admin
"""
import logging
import hmac
import os
from flask import request, jsonify
from sqlalchemy import func, delete
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.admin import admin_bp
from app.models import User, AuditLog, MaintenanceMode, db, UserProfile
from app.models import FamilyTie, Enrollment, Student, Lesson
from core.audit_logger import audit_logger

logger = logging.getLogger(__name__)


def _remote_admin_guard() -> bool:
    """Проверка токена для удаленной админки"""
    provided = request.headers.get('X-Admin-Token', '')
    
    if not provided:
        return False
    
    # Проверяем все возможные токены из переменных окружения
    # Production
    expected_prod = (os.environ.get('PRODUCTION_ADMIN_TOKEN') or '').strip()
    if expected_prod and hmac.compare_digest(provided, expected_prod):
        return True
    
    # Sandbox
    expected_sandbox = (os.environ.get('SANDBOX_ADMIN_TOKEN') or '').strip()
    if expected_sandbox and hmac.compare_digest(provided, expected_sandbox):
        return True
    
    # Admin
    expected_admin = (os.environ.get('ADMIN_ADMIN_TOKEN') or '').strip()
    if expected_admin and hmac.compare_digest(provided, expected_admin):
        return True
    
    # Произвольные окружения (ENV_<NAME>_TOKEN)
    for key, value in os.environ.items():
        if key.startswith('ENV_') and key.endswith('_TOKEN'):
            token = value.strip()
            if token and hmac.compare_digest(provided, token):
                return True
    
    return False


@admin_bp.route('/internal/remote-admin/status', methods=['GET'])
def remote_admin_status():
    """Статус окружения для удаленной админки"""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401
    
    try:
        total_users = User.query.count()
        active_users = User.query.filter_by(is_active=True).count()
        
        # Статистика по логам
        try:
            total_logs = AuditLog.query.count()
            today_logs = AuditLog.query.filter(
                func.date(AuditLog.timestamp) == func.current_date()
            ).count()
        except Exception:
            total_logs = 0
            today_logs = 0
        
        # Статус тех работ
        maintenance_status = MaintenanceMode.get_status()
        
        return jsonify({
            'status': 'ok',
            'stats': {
                'total_users': total_users,
                'active_users': active_users,
                'total_logs': total_logs,
                'today_logs': today_logs,
                'maintenance_enabled': maintenance_status.enabled
            }
        })
    except Exception as e:
        logger.error(f"Error in remote_admin_status: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/users', methods=['GET'])
def remote_admin_api_users():
    """API: Список пользователей"""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401
    
    try:
        role_filter = request.args.get('role')
        is_active_filter = request.args.get('is_active')
        
        query = User.query
        
        if role_filter:
            query = query.filter(User.role == role_filter)
        if is_active_filter is not None:
            is_active = is_active_filter.lower() == 'true'
            query = query.filter(User.is_active == is_active)
        
        users = query.order_by(User.created_at.desc()).all()
        
        return jsonify({
            'success': True,
            'users': [{
                'id': u.id,
                'username': u.username,
                'email': u.email,
                'role': u.role,
                'is_active': u.is_active,
                'created_at': u.created_at.isoformat() if u.created_at else None,
                'last_login': u.last_login.isoformat() if u.last_login else None
            } for u in users]
        })
    except Exception as e:
        logger.error(f"Error in remote_admin_api_users: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/users/<int:user_id>', methods=['GET', 'POST', 'DELETE'])
def remote_admin_api_user(user_id):
    """API: Управление пользователем"""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401
    
    try:
        if request.method == 'GET':
            user = User.query.get(user_id)
            if not user:
                return jsonify({'error': 'user not found'}), 404
            
            # Получаем профиль
            profile = UserProfile.query.filter_by(user_id=user_id).first()
            
            return jsonify({
                'success': True,
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                    'role': user.role,
                    'is_active': user.is_active,
                    'created_at': user.created_at.isoformat() if user.created_at else None,
                    'last_login': user.last_login.isoformat() if user.last_login else None,
                    'profile': {
                        'first_name': profile.first_name if profile else None,
                        'last_name': profile.last_name if profile else None,
                        'phone': profile.phone if profile else None,
                    } if profile else None
                }
            })
        
        elif request.method == 'POST':
            data = request.get_json() or {}
            user = User.query.get(user_id)
            if not user:
                return jsonify({'error': 'user not found'}), 404
            
            if user.is_creator():
                return jsonify({'error': 'cannot modify creator'}), 403
            
            # Обновляем поля
            if 'username' in data:
                user.username = data['username']
            if 'email' in data:
                user.email = data['email'] or None
            if 'role' in data:
                user.role = data['role']
            if 'is_active' in data:
                user.is_active = bool(data['is_active'])
            
            db.session.commit()
            
            return jsonify({'success': True, 'user_id': user_id})
        
        elif request.method == 'DELETE':
            user = User.query.get(user_id)
            if not user:
                return jsonify({'error': 'user not found'}), 404
            
            if user.is_creator():
                return jsonify({'error': 'cannot delete creator'}), 403
            
            username = user.username
            
            # Удаляем логи
            try:
                deleted_logs = db.session.execute(
                    delete(AuditLog).where(AuditLog.user_id == user_id)
                ).rowcount
            except Exception as e:
                logger.warning(f"Error deleting user logs: {e}")
                db.session.rollback()
                deleted_logs = 0
            
            # Удаляем профиль
            try:
                profile = UserProfile.query.filter_by(user_id=user_id).first()
                if profile:
                    db.session.delete(profile)
            except Exception as e:
                logger.warning(f"Error deleting user profile: {e}")
            
            db.session.delete(user)
            db.session.commit()
            
            audit_logger.log(
                action='delete_user',
                entity='User',
                entity_id=user_id,
                status='success',
                metadata={
                    'username': username,
                    'deleted_logs': deleted_logs,
                    'deleted_by_remote_admin': True
                }
            )
            
            return jsonify({'success': True, 'deleted_logs': deleted_logs})
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in remote_admin_api_user: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/stats', methods=['GET'])
def remote_admin_api_stats():
    """API: Статистика окружения"""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401
    
    try:
        stats = {
            'users': {
                'total': User.query.count(),
                'active': User.query.filter_by(is_active=True).count(),
                'by_role': {}
            },
            'students': {
                'total': Student.query.filter_by(is_active=True).count(),
                'archived': Student.query.filter_by(is_active=False).count()
            },
            'lessons': {
                'total': Lesson.query.count(),
                'completed': Lesson.query.filter_by(status='completed').count(),
                'planned': Lesson.query.filter_by(status='planned').count()
            }
        }
        
        # Статистика по ролям
        for role in ['admin', 'tutor', 'student', 'parent', 'tester', 'creator', 'chief_tester', 'designer']:
            stats['users']['by_role'][role] = User.query.filter_by(role=role).count()
        
        # Статистика по логам
        try:
            stats['audit_logs'] = {
                'total': AuditLog.query.count(),
                'today': AuditLog.query.filter(
                    func.date(AuditLog.timestamp) == func.current_date()
                ).count()
            }
        except Exception:
            stats['audit_logs'] = {'total': 0, 'today': 0}
        
        return jsonify({'success': True, 'stats': stats})
    except Exception as e:
        logger.error(f"Error in remote_admin_api_stats: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/audit-logs', methods=['GET'])
def remote_admin_api_audit_logs():
    """API: Список логов действий"""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401
    
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 50))
        action_filter = request.args.get('action')
        user_id_filter = request.args.get('user_id')
        
        query = AuditLog.query
        
        if action_filter:
            query = query.filter(AuditLog.action == action_filter)
        if user_id_filter:
            query = query.filter(AuditLog.user_id == int(user_id_filter))
        
        logs = query.order_by(AuditLog.timestamp.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        return jsonify({
            'success': True,
            'logs': [{
                'id': log.id,
                'action': log.action,
                'entity': log.entity,
                'entity_id': log.entity_id,
                'user_id': log.user_id,
                'timestamp': log.timestamp.isoformat() if log.timestamp else None,
                'status': log.status,
                'metadata': log.metadata
            } for log in logs.items],
            'pagination': {
                'page': logs.page,
                'pages': logs.pages,
                'per_page': logs.per_page,
                'total': logs.total
            }
        })
    except Exception as e:
        logger.error(f"Error in remote_admin_api_audit_logs: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/maintenance', methods=['GET', 'POST'])
def remote_admin_api_maintenance():
    """API: Управление техническими работами"""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401
    
    try:
        if request.method == 'GET':
            status = MaintenanceMode.get_status()
            return jsonify({
                'success': True,
                'enabled': status.is_enabled,
                'message': status.message or ''
            })
        
        elif request.method == 'POST':
            data = request.get_json() or {}
            action = data.get('action')
            
            status = MaintenanceMode.get_status()
            
            if action == 'toggle':
                status.is_enabled = not status.is_enabled
            elif action == 'update_message':
                status.message = data.get('message', '')
            
            db.session.commit()
            
            return jsonify({
                'success': True,
                'enabled': status.is_enabled,
                'message': status.message or ''
            })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in remote_admin_api_maintenance: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/permissions', methods=['GET', 'POST'])
def remote_admin_api_permissions():
    """API: Управление правами доступа"""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401
    
    try:
        from app.models import RolePermission
        from app.auth.permissions import ALL_PERMISSIONS, DEFAULT_ROLE_PERMISSIONS
        
        if request.method == 'GET':
            roles = ['creator', 'admin', 'chief_tester', 'tutor', 'designer', 'tester', 'student', 'parent']
            permissions_data = {}
            
            for role in roles:
                permissions_data[role] = {}
                for perm_key in ALL_PERMISSIONS.keys():
                    perm_record = RolePermission.query.filter_by(role=role, permission_name=perm_key).first()
                    if perm_record:
                        permissions_data[role][perm_key] = perm_record.is_enabled
                    else:
                        # Используем значение по умолчанию
                        permissions_data[role][perm_key] = perm_key in DEFAULT_ROLE_PERMISSIONS.get(role, [])
            
            return jsonify({
                'success': True,
                'permissions': permissions_data
            })
        
        elif request.method == 'POST':
            data = request.get_json() or {}
            role = data.get('role')
            permission = data.get('permission')
            enabled = data.get('enabled', False)
            
            if not role or not permission:
                return jsonify({'error': 'role and permission required'}), 400
            
            perm_record = RolePermission.query.filter_by(role=role, permission_name=permission).first()
            if not perm_record:
                perm_record = RolePermission(role=role, permission_name=permission, is_enabled=enabled)
                db.session.add(perm_record)
            else:
                perm_record.is_enabled = enabled
            
            db.session.commit()
            
            return jsonify({'success': True})
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in remote_admin_api_permissions: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
