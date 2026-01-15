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
from app.models import FamilyTie, Enrollment, Student, Lesson, RolePermission
from app.auth.permissions import ALL_PERMISSIONS, PERMISSION_CATEGORIES
from core.audit_logger import audit_logger
from core.db_models import moscow_now

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


@admin_bp.route('/internal/remote-admin/api/users', methods=['GET', 'POST'])
def remote_admin_api_users():
    """API: Список пользователей или создание нового"""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401
    
    try:
        if request.method == 'POST':
            # Создание нового пользователя
            from werkzeug.security import generate_password_hash
            from core.db_models import moscow_now
            
            data = request.get_json() or {}
            username = data.get('username', '').strip()
            email = data.get('email', '').strip() or None
            password = data.get('password', '').strip()
            role = data.get('role', 'student').strip()
            is_active = data.get('is_active', True)
            
            if not username:
                return jsonify({'error': 'username is required'}), 400
            
            if not password:
                return jsonify({'error': 'password is required'}), 400
            
            # Проверка уникальности
            if User.query.filter_by(username=username).first():
                return jsonify({'error': 'username already exists'}), 409
            
            if email and User.query.filter_by(email=email).first():
                return jsonify({'error': 'email already exists'}), 409
            
            # Создаем пользователя
            user = User(
                username=username,
                email=email,
                password_hash=generate_password_hash(password),
                role=role,
                is_active=is_active,
                created_at=moscow_now()
            )
            db.session.add(user)
            db.session.flush()
            
            # Создаем профиль
            profile = UserProfile(user_id=user.id)
            db.session.add(profile)
            db.session.commit()
            
            audit_logger.log(
                action='create_user',
                entity='User',
                entity_id=user.id,
                status='success',
                metadata={
                    'username': username,
                    'role': role,
                    'created_by_remote_admin': True
                }
            )
            
            return jsonify({
                'success': True,
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                    'role': user.role,
                    'is_active': user.is_active
                }
            }), 201
        
        else:
            # GET - список пользователей
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
        db.session.rollback()
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
                'per_page': logs.per_page,
                'total': logs.total,
                'pages': logs.pages
            }
        })
    except Exception as e:
        logger.error(f"Error in remote_admin_api_audit_logs: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/maintenance', methods=['GET', 'POST'])
def remote_admin_api_maintenance():
    """API: Управление режимом обслуживания"""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401
    
    try:
        if request.method == 'GET':
            status = MaintenanceMode.get_status()
            return jsonify({
                'success': True,
                'status': {
                    'enabled': status.enabled,
                    'message': status.message,
                    'allowed_ips': status.allowed_ips,
                    'updated_at': status.updated_at.isoformat() if status.updated_at else None,
                    'updated_by': status.updated_by
                }
            })
            
        elif request.method == 'POST':
            data = request.get_json() or {}
            
            enabled = bool(data.get('enabled', False))
            message = data.get('message', '').strip()
            
            # Устанавливаем статус через модель
            MaintenanceMode.set_status(
                enabled=enabled,
                message=message,
                user_id=None, # System/Remote Admin
                username='Remote Admin'
            )
            
            audit_logger.log(
                action='toggle_maintenance',
                entity='MaintenanceMode',
                entity_id=None,
                status='success',
                metadata={
                    'enabled': enabled,
                    'message': message,
                    'source': 'remote_admin'
                }
            )
            
            return jsonify({'success': True})
            
    except Exception as e:
        logger.error(f"Error in remote_admin_api_maintenance: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/testers', methods=['GET', 'POST'])
def remote_admin_api_testers():
    """API: Управление тестерами (сущности Tester)"""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401
    
    # Тестеры доступны только если модель существует (обычно Sandbox)
    try:
        from core.db_models import Tester
    except ImportError:
        return jsonify({'error': 'Tester model not found'}), 501
    
    try:
        if request.method == 'GET':
            testers = Tester.query.order_by(Tester.created_at.desc()).all()
            return jsonify({
                'success': True,
                'testers': [{
                    'id': t.id,
                    'name': t.name,
                    'is_active': t.is_active,
                    'created_at': t.created_at.isoformat() if t.created_at else None
                } for t in testers]
            })
            
        elif request.method == 'POST':
            data = request.get_json() or {}
            name = data.get('name', '').strip()
            is_active = bool(data.get('is_active', True))
            
            if not name:
                return jsonify({'error': 'name is required'}), 400
                
            tester = Tester(
                name=name,
                is_active=is_active,
                created_at=moscow_now()
            )
            db.session.add(tester)
            db.session.commit()
            
            audit_logger.log(
                action='create_tester',
                entity='Tester',
                entity_id=tester.id,
                status='success',
                metadata={'name': name, 'source': 'remote_admin'}
            )
            
            return jsonify({'success': True, 'tester_id': tester.id})
            
    except Exception as e:
        logger.error(f"Error in remote_admin_api_testers: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/testers/<int:tester_id>', methods=['POST', 'DELETE'])
def remote_admin_api_tester(tester_id):
    """API: Управление конкретным тестером"""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401
        
    try:
        from core.db_models import Tester
    except ImportError:
        return jsonify({'error': 'Tester model not found'}), 501
    
    try:
        tester = Tester.query.get(tester_id)
        if not tester:
            return jsonify({'error': 'tester not found'}), 404
            
        if request.method == 'POST':
            # Обновление (toggle active или edit)
            data = request.get_json() or {}
            
            if 'is_active' in data:
                tester.is_active = bool(data['is_active'])
            
            if 'name' in data:
                tester.name = data['name'].strip()
                
            db.session.commit()
            return jsonify({'success': True})
            
        elif request.method == 'DELETE':
            db.session.delete(tester)
            db.session.commit()
            
            audit_logger.log(
                action='delete_tester',
                entity='Tester',
                entity_id=tester_id,
                status='success',
                metadata={'source': 'remote_admin'}
            )
            
            return jsonify({'success': True})
            
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in remote_admin_api_tester: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/permissions', methods=['GET', 'POST'])
def remote_admin_api_permissions():
    """API: Управление правами доступа"""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401
    
    try:
        if request.method == 'GET':
            # Получаем все права из БД
            role_permissions = RolePermission.query.all()
            permissions_map = {}
            for rp in role_permissions:
                if rp.role not in permissions_map:
                    permissions_map[rp.role] = []
                permissions_map[rp.role].append(rp.permission)
            
            return jsonify({
                'success': True,
                'permissions_map': permissions_map,
                'all_permissions': ALL_PERMISSIONS,
                'categories': PERMISSION_CATEGORIES
            })
            
        elif request.method == 'POST':
            data = request.get_json() or {}
            role = data.get('role')
            permissions = data.get('permissions', []) # Список permissions для этой роли
            
            if not role:
                return jsonify({'error': 'role is required'}), 400
                
            # Удаляем старые права для роли
            db.session.execute(
                delete(RolePermission).where(RolePermission.role == role)
            )
            
            # Добавляем новые
            for perm in permissions:
                if perm in ALL_PERMISSIONS:
                    rp = RolePermission(role=role, permission=perm)
                    db.session.add(rp)
            
            db.session.commit()
            
            audit_logger.log(
                action='update_permissions',
                entity='RolePermission',
                entity_id=None,
                status='success',
                metadata={'role': role, 'count': len(permissions), 'source': 'remote_admin'}
            )
            
            return jsonify({'success': True})
            
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in remote_admin_api_permissions: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
