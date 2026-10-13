from flask import Blueprint

demo_bp = Blueprint('demo', __name__, template_folder='../../templates')

from app.demo import routes  # noqa: E402, F401
