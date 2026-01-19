from flask import Blueprint

courses_bp = Blueprint('courses', __name__, template_folder='../../templates')

from app.courses import routes  # noqa: E402,F401

