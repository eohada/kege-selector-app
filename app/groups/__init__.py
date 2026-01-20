"""
Блюпринт: группы/классы
"""
from flask import Blueprint

groups_bp = Blueprint('groups', __name__)

from app.groups import routes  # noqa: E402,F401

