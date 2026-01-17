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
from app.auth.permissions import ALL_PERMISSIONS, PERMISSION_CATEGORIES, DEFAULT_ROLE_PERMISSIONS
from core.audit_logger import audit_logger
from core.db_models import moscow_now

logger = logging.getLogger(__name__)

# Импортируем csrf безопасным способом (после всех других импортов)
try:
    from app import csrf
except ImportError:
    # Если циклический импорт, используем current_app
    csrf = None


def _remote_admin_guard() -> bool:
    """Проверка токена для удаленной админки"""
    provided = request.headers.get('X-Admin-Token', '')
    
    if not provided:
        logger.warning(f"Remote admin API request without X-Admin-Token header: {request.path}")
        return False
    
    # Проверяем все возможные токены из переменных окружения
    # Production
    expected_prod = (os.environ.get('PRODUCTION_ADMIN_TOKEN') or '').strip()
    if expected_prod and hmac.compare_digest(provided, expected_prod):
        logger.debug(f"Remote admin request authenticated with PRODUCTION_ADMIN_TOKEN")
        return True
    
    # Sandbox
    expected_sandbox = (os.environ.get('SANDBOX_ADMIN_TOKEN') or '').strip()
    if expected_sandbox and hmac.compare_digest(provided, expected_sandbox):
        logger.debug(f"Remote admin request authenticated with SANDBOX_ADMIN_TOKEN")
        return True
    
    # Admin
    expected_admin = (os.environ.get('ADMIN_ADMIN_TOKEN') or '').strip()
    if expected_admin and hmac.compare_digest(provided, expected_admin):
        logger.debug(f"Remote admin request authenticated with ADMIN_ADMIN_TOKEN")
        return True
    
    # Произвольные окружения (ENV_<NAME>_TOKEN)
    for key, value in os.environ.items():
        if key.startswith('ENV_') and key.endswith('_TOKEN'):
            token = value.strip()
            if token and hmac.compare_digest(provided, token):
                logger.debug(f"Remote admin request authenticated with {key}")
                return True
    
    logger.warning(f"Remote admin API request with invalid token: {request.path}, provided_token_preview: {provided[:10]}...")
    return False


@admin_bp.route('/internal/remote-admin/status', methods=['GET'])
@csrf.exempt
def remote_admin_status():
    """Статус окружения для удаленной админки"""
    logger.info(f"Remote admin status request received: path={request.path}, method={request.method}")
    logger.debug(f"Request headers: {dict(request.headers)}")
    
    if not _remote_admin_guard():
        logger.warning(f"Remote admin status request rejected: no valid token")
        return jsonify({'error': 'unauthorized'}), 401
    
    logger.info(f"Remote admin status request authenticated successfully")
    
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
                'maintenance_enabled': maintenance_status.is_enabled
            }
        })
    except Exception as e:
        logger.error(f"Error in remote_admin_status: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/users', methods=['GET', 'POST'])
@csrf.exempt
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
            platform_id = data.get('platform_id', '').strip() or None
            
            if not username:
                return jsonify({'error': 'username is required'}), 400
            
            if not password:
                return jsonify({'error': 'password is required'}), 400
            
            # Проверка уникальности
            if User.query.filter_by(username=username).first():
                return jsonify({'error': 'username already exists'}), 409
            
            if email and User.query.filter_by(email=email).first():
                return jsonify({'error': 'email already exists'}), 409
            
            # Если роль - студент, проверяем уникальность platform_id
            if role == 'student' and platform_id:
                from app.models import Student
                from app.utils.student_id_manager import is_valid_three_digit_id
                
                # Проверяем формат идентификатора
                if not is_valid_three_digit_id(platform_id):
                    return jsonify({'error': 'platform_id must be a three-digit number between 100 and 999'}), 400
                
                # Проверяем уникальность
                existing_student = Student.query.filter_by(platform_id=platform_id).first()
                if existing_student:
                    return jsonify({'error': f'platform_id "{platform_id}" already exists'}), 409
            
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
            
            # Если роль - студент, создаем запись Student
            if role == 'student':
                from app.models import Student
                from app.utils.student_id_manager import assign_platform_id_if_needed
                
                # Проверяем, нет ли уже студента с таким email
                student_record = None
                if email:
                    student_record = Student.query.filter_by(email=email).first()
                
                if not student_record:
                    # Создаем новую запись Student
                    student_record = Student(
                        name=username,  # Используем username как имя по умолчанию
                        email=email,
                        platform_id=platform_id,
                        is_active=is_active
                    )
                    db.session.add(student_record)
                    db.session.flush()
                    
                    # Автоматически присваиваем идентификатор, если не указан
                    if not platform_id:
                        assign_platform_id_if_needed(student_record)
                        db.session.flush()
                else:
                    # Обновляем существующую запись
                    student_record.name = username
                    student_record.email = email
                    student_record.is_active = is_active
                    if platform_id:
                        student_record.platform_id = platform_id
                    elif not student_record.platform_id:
                        # Присваиваем идентификатор, если его нет
                        assign_platform_id_if_needed(student_record)
                        db.session.flush()
            
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
@csrf.exempt
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
            
            # Получаем Student, если роль - студент
            student = None
            if user.role == 'student':
                from app.models import Student
                if user.email:
                    student = Student.query.filter_by(email=user.email).first()
                # Если не найден по email, ищем по связи через User.id (если есть такая связь)
                if not student:
                    # Пробуем найти по user_id, если есть поле user_id в Student
                    try:
                        student = Student.query.filter_by(user_id=user_id).first()
                    except:
                        pass
            
            user_data = {
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
            
            # Добавляем platform_id для студентов
            if student:
                user_data['student'] = {
                    'platform_id': student.platform_id,
                    'name': student.name
                }
            
            return jsonify({
                'success': True,
                'user': user_data
            })
        
        elif request.method == 'POST':
            data = request.get_json() or {}
            user = User.query.get(user_id)
            if not user:
                return jsonify({'error': 'user not found'}), 404
            
            if user.is_creator():
                return jsonify({'error': 'cannot modify creator'}), 403
            
            # Обновляем поля пользователя
            if 'username' in data:
                user.username = data['username']
            if 'email' in data:
                user.email = data['email'] or None
            if 'role' in data:
                user.role = data['role']
            if 'is_active' in data:
                user.is_active = bool(data['is_active'])
            
            # Обновляем пароль, если указан
            if 'password' in data and data['password']:
                from werkzeug.security import generate_password_hash
                user.password_hash = generate_password_hash(data['password'])
            
            # Если роль - студент, обновляем или создаем запись Student
            if user.role == 'student':
                from app.models import Student
                from app.utils.student_id_manager import is_valid_three_digit_id, assign_platform_id_if_needed
                
                platform_id = data.get('platform_id', '').strip() or None
                
                # Проверяем формат идентификатора, если указан
                if platform_id and not is_valid_three_digit_id(platform_id):
                    return jsonify({'error': 'platform_id must be a three-digit number between 100 and 999'}), 400
                
                # Ищем существующую запись Student
                student_record = None
                if user.email:
                    student_record = Student.query.filter_by(email=user.email).first()
                
                # Если не найден по email, пробуем найти по user_id (если есть такая связь)
                if not student_record:
                    try:
                        student_record = Student.query.filter_by(user_id=user_id).first()
                    except:
                        pass
                
                if not student_record:
                    # Создаем новую запись Student
                    student_record = Student(
                        name=user.username,  # Используем username как имя по умолчанию
                        email=user.email,
                        platform_id=platform_id,
                        is_active=user.is_active
                    )
                    db.session.add(student_record)
                    db.session.flush()
                    
                    # Автоматически присваиваем идентификатор, если не указан
                    if not platform_id:
                        assign_platform_id_if_needed(student_record)
                        db.session.flush()
                else:
                    # Обновляем существующую запись
                    student_record.name = user.username
                    student_record.email = user.email
                    student_record.is_active = user.is_active
                    
                    # Обновляем platform_id, если указан
                    if platform_id:
                        # Проверяем уникальность (кроме текущего студента)
                        existing = Student.query.filter(
                            Student.platform_id == platform_id,
                            Student.student_id != student_record.student_id
                        ).first()
                        if existing:
                            return jsonify({'error': f'platform_id "{platform_id}" already exists'}), 409
                        student_record.platform_id = platform_id
                    elif not student_record.platform_id:
                        # Присваиваем идентификатор, если его нет
                        assign_platform_id_if_needed(student_record)
                        db.session.flush()
            
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
@csrf.exempt
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
@csrf.exempt
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
@csrf.exempt
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
                    'enabled': status.is_enabled,
                    'message': status.message,
                    'updated_at': status.updated_at.isoformat() if status.updated_at else None,
                    'updated_by': status.updated_by
                }
            })
            
        elif request.method == 'POST':
            data = request.get_json() or {}
            
            enabled = bool(data.get('enabled', False))
            message = data.get('message', '').strip()
            
            # Устанавливаем статус напрямую
            status = MaintenanceMode.get_status()
            status.is_enabled = enabled
            status.message = message
            status.updated_by = None  # System/Remote Admin
            db.session.commit()
            
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
@csrf.exempt
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
@csrf.exempt
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
@csrf.exempt
def remote_admin_api_permissions():
    """API: Управление правами доступа"""
    logger.info(f"Remote admin permissions API request: method={request.method}, path={request.path}")
    
    if not _remote_admin_guard():
        logger.warning(f"Remote admin permissions API request rejected: no valid token")
        return jsonify({'error': 'unauthorized'}), 401
    
    logger.info(f"Remote admin permissions API request authenticated successfully")
    
    try:
        if request.method == 'GET':
            # Все возможные роли в системе
            ALL_ROLES = ['creator', 'admin', 'tutor', 'student', 'parent', 'tester', 'chief_tester', 'designer']
            
            # Получаем все права из БД
            try:
                role_permissions = RolePermission.query.all()
                
                # Если в базе нет прав, инициализируем их из DEFAULT_ROLE_PERMISSIONS
                if len(role_permissions) == 0:
                    logger.info("No role permissions found in database. Initializing from DEFAULT_ROLE_PERMISSIONS...")
                    try:
                        count = 0
                        for role, perms in DEFAULT_ROLE_PERMISSIONS.items():
                            for perm_name in perms:
                                # Проверяем, что право существует в ALL_PERMISSIONS
                                if perm_name not in ALL_PERMISSIONS:
                                    logger.warning(f"Permission '{perm_name}' not found in ALL_PERMISSIONS, skipping")
                                    continue
                                
                                rp = RolePermission(
                                    role=role, 
                                    permission_name=perm_name, 
                                    is_enabled=True
                                )
                                db.session.add(rp)
                                count += 1
                        
                        db.session.commit()
                        logger.info(f"Initialized {count} default permission records")
                        
                        # Перезагружаем права из БД
                        role_permissions = RolePermission.query.all()
                    except Exception as init_error:
                        db.session.rollback()
                        logger.error(f"Error initializing default permissions: {init_error}", exc_info=True)
                        # Продолжаем работу, даже если инициализация не удалась
                
                permissions_map = {}
                
                # Инициализируем все роли пустыми списками
                for role in ALL_ROLES:
                    permissions_map[role] = []
                
                # Заполняем правами из БД
                for rp in role_permissions:
                    if rp.role not in permissions_map:
                        permissions_map[rp.role] = []
                    # Используем только включенные права (is_enabled=True)
                    if rp.is_enabled:
                        permissions_map[rp.role].append(rp.permission_name)
                
                logger.debug(f"Found {len(role_permissions)} role permissions, {len(permissions_map)} roles")
                logger.debug(f"Roles in permissions_map: {list(permissions_map.keys())}")
                logger.debug(f"ALL_PERMISSIONS count: {len(ALL_PERMISSIONS) if ALL_PERMISSIONS else 0}")
                logger.debug(f"PERMISSION_CATEGORIES count: {len(PERMISSION_CATEGORIES) if PERMISSION_CATEGORIES else 0}")
            except Exception as db_error:
                logger.error(f"Database error in permissions GET: {db_error}", exc_info=True)
                raise
            
            # Проверяем, что ALL_PERMISSIONS и PERMISSION_CATEGORIES доступны
            try:
                all_perms = dict(ALL_PERMISSIONS) if ALL_PERMISSIONS else {}
                perm_cats = dict(PERMISSION_CATEGORIES) if PERMISSION_CATEGORIES else {}
            except Exception as e:
                logger.error(f"Error converting permissions to dict: {e}", exc_info=True)
                all_perms = {}
                perm_cats = {}
            
            return jsonify({
                'success': True,
                'roles_permissions': permissions_map,
                'all_permissions': all_perms,
                'permission_categories': perm_cats
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
                    rp = RolePermission(role=role, permission_name=perm, is_enabled=True)
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
