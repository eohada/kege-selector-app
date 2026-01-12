"""
Блюпринт администрирования
"""
from flask import Blueprint

admin_bp = Blueprint('admin', __name__)

from app.admin import routes
from app.admin import routes_permissions  # Импортируем новый файл с роутами
from app.admin import diagnostics
from app.admin import user_management  # API endpoints для управления пользователями
from app.admin import family_management  # API endpoints для управления семейными связями
from app.admin import enrollment_management  # API endpoints для управления учебными контрактами
from app.admin import remote_admin_api  # Внутренние API для удаленной админки

