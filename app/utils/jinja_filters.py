"""
Jinja2 фильтры для шаблонов
"""
from app.auth.rbac_utils import mask_contact_info
from flask_login import current_user


def mask_contact_if_tutor(value):
    """
    Маскирует контактную информацию, если текущий пользователь - тьютор.
    Используется в шаблонах для защиты приватности учеников.
    
    Args:
        value: Контактная информация (телефон, email)
        
    Returns:
        Замаскированная или оригинальная информация в зависимости от роли
    """
    if not value:
        return value
    
    # Если пользователь - тьютор, маскируем контакты
    if current_user.is_authenticated and current_user.is_tutor():
        return mask_contact_info(value)
    
    # Для администраторов и других ролей показываем полную информацию
    return value


def init_jinja_filters(app):
    """Инициализация Jinja2 фильтров"""
    app.jinja_env.filters['mask_contact'] = mask_contact_if_tutor
