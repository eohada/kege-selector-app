from flask import Blueprint

trainer_bp = Blueprint('trainer', __name__)

from app.trainer import routes  # noqa: E402,F401

