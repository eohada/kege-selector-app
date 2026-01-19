from flask import Blueprint

library_bp = Blueprint('library', __name__, template_folder='../../templates')

from app.library import routes  # noqa: E402,F401

