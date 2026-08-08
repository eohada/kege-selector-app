"""
Блюпринт для родителей
"""
from flask import Blueprint

parents_bp = Blueprint('parents', __name__, url_prefix='/parents')

from app.parents import routes
