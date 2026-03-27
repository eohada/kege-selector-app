"""
Cabinet for Chief Tester.
New UI layer over existing QA task storage (QATask).
"""

from flask import Blueprint

chief_tester_bp = Blueprint('chief_tester', __name__, url_prefix='/chief-tester')

from app.chief_tester import routes  # noqa: E402,F401

