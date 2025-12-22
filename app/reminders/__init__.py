"""
Блюпринт напоминаний
"""
from flask import Blueprint

reminders_bp = Blueprint('reminders', __name__)

from app.reminders import routes

