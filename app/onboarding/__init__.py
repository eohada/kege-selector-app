"""
Блюпринт: онбординг (приглашения)
"""
from flask import Blueprint

onboarding_bp = Blueprint('onboarding', __name__)

from app.onboarding import routes  # noqa: E402,F401

