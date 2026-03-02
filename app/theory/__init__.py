"""
Теоретический блок для учеников: теория по заданиям ЕГЭ (1–27).
Управление контентом — у тьютора/админа; просмотр — у учеников (с учётом запретов по номерам).
"""
from flask import Blueprint

theory_bp = Blueprint('theory', __name__)

from app.theory import routes  # регистрация маршрутов на blueprint
