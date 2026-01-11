"""
Утилиты для реализации Role-Based Access Control (RBAC) и Data Scoping
Обеспечивает автоматическую фильтрацию данных в зависимости от роли пользователя
"""
from functools import wraps
from flask import abort
from flask_login import login_required, current_user
from sqlalchemy import and_, or_
from app.models import db, User, Enrollment, FamilyTie


def get_user_scope(user):
    """
    Получает scope (область видимости) для пользователя в зависимости от роли.
    Возвращает словарь с фильтрами для запросов.
    
    Args:
        user: Объект User
        
    Returns:
        dict: Словарь с ключами:
            - 'student_ids': список ID учеников, которых видит пользователь
            - 'can_see_all': bool, может ли видеть всех
            - 'role': роль пользователя
    """
    if not user or not user.is_authenticated:
        return {
            'student_ids': [],
            'can_see_all': False,
            'role': None
        }
    
    scope = {
        'role': user.role,
        'can_see_all': False,
        'student_ids': []
    }
    
    if user.is_admin():
        # Администратор видит всех
        scope['can_see_all'] = True
        return scope
    
    elif user.is_tutor():
        # Тьютор видит только своих учеников (через Enrollment)
        # Включаем все статусы, кроме 'archived', чтобы видеть активных и приостановленных
        enrollments = Enrollment.query.filter(
            Enrollment.tutor_id == user.id,
            Enrollment.status != 'archived'
        ).all()
        scope['student_ids'] = [e.student_id for e in enrollments]
        # Логируем для отладки
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"Tutor {user.id} ({user.username}) has {len(enrollments)} enrollments, student_ids: {scope['student_ids']}")
        return scope
    
    elif user.is_parent():
        # Родитель видит только своих детей (через FamilyTie)
        family_ties = FamilyTie.query.filter_by(
            parent_id=user.id,
            is_confirmed=True
        ).all()
        scope['student_ids'] = [ft.student_id for ft in family_ties]
        return scope
    
    elif user.is_student():
        # Ученик видит только себя
        scope['student_ids'] = [user.id]
        return scope
    
    # Для старых ролей (tester, creator) - без ограничений (для обратной совместимости)
    scope['can_see_all'] = True
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
        # Неавторизованные пользователи не видят ничего
        return query.filter(False)
    
    scope = get_user_scope(current_user)
    
    if scope['can_see_all']:
        # Администратор или старые роли - видит всё
        return query
    
    if not scope['student_ids']:
        # Нет доступных учеников - не видит ничего
        return query.filter(False)
    
    # Применяем фильтр по student_id
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
            
            if current_user.role not in allowed_roles:
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

    # Маскирование email
    if '@' in contact_string:
        parts = contact_string.split('@')
        if len(parts[0]) > 1:
            return parts[0][0] + '***' + '@' + parts[1]
        return '***@' + parts[1]
    # Маскирование телефона (предполагаем формат +7 9XX XXX XX XX)
    else:
        import re
        digits = re.sub(r'\D', '', contact_string) # Оставляем только цифры
        if len(digits) >= 4:
            # Маскируем среднюю часть, оставляя первые 3-4 и последние 2-3 цифры
            # Например, для 10-значного номера: 9001234567 -> 900***4567
            # Для 11-значного номера: 79001234567 -> 7900***4567
            if len(digits) > 7:
                return contact_string.replace(digits[len(digits)-7:len(digits)-2], '*****')
            elif len(digits) > 4:
                return contact_string.replace(digits[len(digits)-4:len(digits)-2], '***')
        return contact_string
