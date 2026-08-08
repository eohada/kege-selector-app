from app import create_app
from flask import url_for
import traceback

app = create_app()
with app.app_context():
    try:
        from core.db_models import QAReport, User
        # Взьмем любой репорт
        r = QAReport.query.first()
        if r:
            with app.test_request_context(f'/admin/qa/reports/{r.id}'):
                # симулируем логин админа
                admin = User.query.filter_by(role='admin').first()
                if admin:
                    from flask_login import login_user
                    login_user(admin)
                
                from app.admin.qa_management import view_report
                view_report(r.id)
                print("RENDER SUCCESS")
        else:
            print("No reports found")
    except Exception as e:
        print("RENDER ERROR:")
        traceback.print_exc()
