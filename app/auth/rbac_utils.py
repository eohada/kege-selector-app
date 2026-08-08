from flask import session, current_app

def get_active_role():
    if not current_user or not current_user.is_authenticated:
        return None
    if (current_app.config.get('DEBUG') or current_app.config.get('TESTING')) and 'sandbox_role' in session:
        return session['sandbox_role']
    return getattr(current_user, 'role', 'student')

"""
Утилиты для реализации Role-Based Access Control (RBAC) и Data Scoping
Обеспечивает автоматическую фильтрацию данных в зависимости от роли пользователя
"""
from functools import wraps
from flask import abort, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import and_, or_
from app.models import db, User, RolePermission
from app.auth.permissions import DEFAULT_ROLE_PERMISSIONS
from app.utils.relationship_scope import (
    get_confirmed_student_user_ids_for_parent,
    get_student_user_ids_for_tutor,
    is_creator_or_admin,
)
import logging

logger = logging.getLogger(__name__)

def has_permission(user, permission_name):
    """
    Проверяет наличие права у пользователя. Учитываются все роли пользователя (объединение прав).
    1. Индивидуальные права (custom_permissions)
    2. Права каждой из ролей (RolePermission)
    3. Дефолтные права (DEFAULT_ROLE_PERMISSIONS)
    """
    if not user or not user.is_authenticated:
        return False
        
    if user.is_creator() or user.is_chief_admin() or user.is_admin():
        return True
    if user.is_chief_tester():
        return True

    try:
        cp = getattr(user, 'custom_permissions', None)
        if isinstance(cp, dict) and (permission_name in cp):
            return bool(cp.get(permission_name))
    except Exception:
        pass
        
    roles = user.roles() if hasattr(user, 'roles') and callable(getattr(user, 'roles')) else [getattr(user, 'role', '')]
    for role in roles:
        if not role:
            continue
        try:
            role_perm = RolePermission.query.filter_by(role=role, permission_name=permission_name).first()
            # An explicit matrix record overrides the role default. Without this,
            # a disabled default permission continued to grant access.
            if role_perm is not None:
                if role_perm.is_enabled:
                    return True
                continue
        except Exception as e:
            logger.error(f"Error checking DB permissions: {e}")
        if permission_name in DEFAULT_ROLE_PERMISSIONS.get(role, []):
            return True
    return False

def check_access(permission_name):
    """Декоратор для проверки наличия конкретного права"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not has_permission(current_user, permission_name):
                logger.warning(f"Access denied: User {current_user.id} ({current_user.role}) tried to access protected route requiring '{permission_name}'")
                flash('У вас недостаточно прав для выполнения этого действия.', 'danger')
                return redirect(url_for('main.dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def get_user_scope(user):
    """
    Возвращает область видимости данных для пользователя (объединение по всем ролям).
    """
    if not user or not user.is_authenticated:
        return {'role': None, 'user_id': None, 'can_see_all': False, 'student_ids': []}

    # Celery eager mode and nested app initialization can remove the scoped
    # SQLAlchemy session after Flask-Login has loaded its user. Re-resolve that
    # identity before reading scalar fields or relationship-based roles.
    state = getattr(user, '_sa_instance_state', None)
    if state is not None and state.detached and state.identity:
        user = db.session.get(User, state.identity[0])
        if user is None:
            return {'role': None, 'user_id': None, 'can_see_all': False, 'student_ids': []}

    scope = {
        'role': user.role,
        'user_id': user.id,
        'can_see_all': False,
        'student_ids': []
    }
    
    if is_creator_or_admin(user) or user.is_chief_tester():
        scope['can_see_all'] = True
        return scope
    
    student_ids = set()
    
    if user.is_tutor():
        student_ids.update(get_student_user_ids_for_tutor(user.id))
    
    if user.is_parent():
        student_ids.update(get_confirmed_student_user_ids_for_parent(user.id))
    
    if user.is_student():
        student_ids.add(user.id)
    
    scope['student_ids'] = list(student_ids)
    return scope


def apply_data_scope(query, model_class, student_id_field='student_id'):
    """
    Применяет фильтр Data Scoping к SQLAlchemy запросу.
    
    Args:
        query: SQLAlchemy query объект
        model_class: Класс модели (для определения связей)
        student_id_field: Имя поля с ID ученика (по умолчанию 'student_id')
        
    Returns:
        Отфильтрованный query объект
    """
    if not current_user.is_authenticated:
        return query.filter(False)
    
    scope = get_user_scope(current_user)
    
    if scope['can_see_all']:
        return query
    
    if not scope['student_ids']:
        return query.filter(False)
    
    if hasattr(model_class, student_id_field):
        return query.filter(getattr(model_class, student_id_field).in_(scope['student_ids']))
    
    return query


def require_role(*allowed_roles):
    """
    Декоратор для проверки роли пользователя.
    
    Usage:
        @require_role('admin', 'tutor')
        def my_view():
            ...
    """
    def decorator(f):
        @wraps(f)
        @login_required
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(403)

            # 👑 CREATOR GOD-MODE BYPASS
            if getattr(current_user, 'role', '') == 'creator' or current_user.is_creator() or session.get('sandbox_role') == 'creator':
                return f(*args, **kwargs)

            allowed = set(allowed_roles)
            user_roles = current_user.roles() if hasattr(current_user, 'roles') and callable(getattr(current_user, 'roles')) else [getattr(current_user, 'role', '')]
            if not (allowed & set(user_roles)):
                abort(403)
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def require_admin(f):
    """Декоратор для проверки, что пользователь - администратор"""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(403)
        if getattr(current_user, 'role', '') == 'creator' or current_user.is_creator() or session.get('sandbox_role') == 'creator':
            return f(*args, **kwargs)
        if not current_user.is_admin():
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


def require_tutor(f):
    """Декоратор для проверки, что пользователь - тьютор"""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(403)
        if getattr(current_user, 'role', '') == 'creator' or current_user.is_creator() or session.get('sandbox_role') == 'creator':
            return f(*args, **kwargs)
        if not current_user.is_tutor():
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


def require_student(f):
    """Декоратор для проверки, что пользователь - ученик"""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(403)
        if getattr(current_user, 'role', '') == 'creator' or current_user.is_creator() or session.get('sandbox_role') == 'creator':
            return f(*args, **kwargs)
        if not current_user.is_student():
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


def require_parent(f):
    """Декоратор для проверки, что пользователь - родитель"""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_parent():
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


def mask_contact_info(contact_string):
    """
    Маскирует контактную информацию (телефон или email) для защиты приватности.
    Пример: +7 900 123 45 67 -> +7 900 *** ** 67
            user@example.com -> u***@example.com
    """
    if not contact_string:
        return ""

    if '@' in contact_string:
        parts = contact_string.split('@')
        if len(parts[0]) > 1:
            return parts[0][0] + '***' + '@' + parts[1]
        return '***@' + parts[1]
    else:
        import re
        digits = re.sub(r'\D', '', contact_string) # Оставляем только цифры
        if len(digits) >= 4:
            if len(digits) > 7:
                return contact_string.replace(digits[len(digits)-7:len(digits)-2], '*****')
            elif len(digits) > 4:
                return contact_string.replace(digits[len(digits)-4:len(digits)-2], '***')
        return contact_string
