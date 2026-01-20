from flask import Blueprint

uploads_bp = Blueprint('uploads', __name__)

from app.uploads import routes  # noqa: E402,F401

