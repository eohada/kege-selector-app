"""
Блюпринт генератора заданий (универсальный — ЕГЭ / ОГЭ)
"""
from flask import Blueprint

task_generator_bp = Blueprint('task_generator', __name__)

from app.task_generator import routes  # noqa: E402,F401
