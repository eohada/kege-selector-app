from flask import Blueprint

designer_bp = Blueprint('designer', __name__)

from app.designer import routes
