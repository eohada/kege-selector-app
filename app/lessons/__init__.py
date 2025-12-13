"""
Блюпринт управления уроками
"""
from flask import Blueprint

lessons_bp = Blueprint('lessons', __name__)

from app.lessons import routes

