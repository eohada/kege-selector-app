from flask import Blueprint

qa_tester_bp = Blueprint('qa_tester', __name__, url_prefix='/qa')

from . import routes
