"""Гостевой контур BooStudy: вводный урок и пробная диагностика."""
from flask import Blueprint

guest_bp = Blueprint('guest', __name__)

from app.guest import routes  # noqa: E402,F401
