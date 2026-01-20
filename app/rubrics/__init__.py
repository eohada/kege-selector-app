from flask import Blueprint

rubrics_bp = Blueprint('rubrics', __name__)

from app.rubrics import routes  # noqa: E402,F401

