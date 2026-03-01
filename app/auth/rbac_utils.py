"""
Утилиты для реализации Role-Based Access Control (RBAC) и Data Scoping
Обеспечивает автоматическую фильтрацию данных в зависимости от роли пользователя
"""
from functools import wraps
from flask import abort, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import and_, or_
from app.models import db, User, Enrollment, FamilyTie, RolePermission
from app.auth.permissions import DEFAULT_ROLE_PERMISSIONS
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
        
    if user.is_creator():
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
            if role_perm and role_perm.is_enabled:
                return True
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
    scope = {
        'role': user.role if user and user.is_authenticated else None,
        'can_see_all': False,
        'student_ids': []
    }

    if not user or not user.is_authenticated:
         return scope
    
    if user.is_creator() or user.is_admin() or user.is_chief_tester():
        scope['can_see_all'] = True
        return scope
    
    student_ids = set()
    
    if user.is_tutor():
        enrollments = Enrollment.query.filter(
            Enrollment.tutor_id == user.id,
            Enrollment.status != 'archived'
        ).all()
        student_ids.update(e.student_id for e in enrollments)
    
    if user.is_parent():
        family_ties = FamilyTie.query.filter_by(parent_id=user.id, is_confirmed=True).all()
        if not family_ties:
            family_ties = FamilyTie.query.filter_by(parent_id=user.id).all()
        student_ids.update(ft.student_id for ft in family_ties)
    
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
        if not current_user.is_authenticated or not current_user.is_admin():
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


def require_tutor(f):
    """Декоратор для проверки, что пользователь - тьютор"""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_tutor():
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


def require_student(f):
    """Декоратор для проверки, что пользователь - ученик"""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_student():
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
