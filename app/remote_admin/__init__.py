"""
Удаленная админка для контроля платформы
Отдельный софт для управления production и sandbox окружениями
"""
from flask import Blueprint

remote_admin_bp = Blueprint('remote_admin', __name__, url_prefix='/remote-admin')

from app.remote_admin import routes
from app.remote_admin import environment_manager
from app.remote_admin import api_routes
