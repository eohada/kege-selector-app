from flask import Blueprint

class QA_Blueprint(Blueprint):
    def route(self, rule, **options):
        options.setdefault('strict_slashes', False)
        return super().route(rule, **options)

qa_tester_bp = QA_Blueprint('qa_tester', __name__, url_prefix='/qa')

from . import routes
