"""
Блюпринт управления шаблонами
"""
from flask import Blueprint

templates_bp = Blueprint('templates', __name__)

from app.templates_manager import routes

