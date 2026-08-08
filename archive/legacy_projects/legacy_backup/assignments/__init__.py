"""
Blueprint для системы заданий и сдачи работ
"""
from flask import Blueprint

assignments_bp = Blueprint('assignments', __name__)

from app.assignments import routes
