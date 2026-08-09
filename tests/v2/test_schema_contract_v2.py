from sqlalchemy import text

from app.models import db
from app.utils.schema_contract import schema_contract_report


def test_schema_audit_accepts_complete_mapped_schema(app):
    with app.app_context():
        report = schema_contract_report(app)
        assert report['ok'] is True
        assert report['issues'] == []


def test_schema_audit_detects_missing_teacher_student_table(app):
    with app.app_context():
        db.session.execute(text('DROP TABLE teacher_students'))
        db.session.commit()

        report = schema_contract_report(app)
        assert {'kind': 'table', 'table': 'teacher_students', 'name': 'teacher_students'} in report['issues']
