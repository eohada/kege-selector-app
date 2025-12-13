"""
Блюпринт генератора КЕГЭ
"""
from flask import Blueprint

kege_generator_bp = Blueprint('kege_generator', __name__)

from app.kege_generator import routes

