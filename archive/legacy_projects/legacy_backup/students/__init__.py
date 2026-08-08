"""
Блюпринт управления студентами
"""
from flask import Blueprint

students_bp = Blueprint('students', __name__)

from app.students import routes

