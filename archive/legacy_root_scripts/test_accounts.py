from app import create_app
from core.db_models import User
import traceback

app = create_app()
with app.app_context():
    users = ['qa_student_1', 'qa_student_2', 'qa_student_3', 'qa_tutor_1', 'qa_tutor_2', 'qa_tutor_3']
    for u in users:
        db_user = User.query.filter_by(username=u).first()
        print(f"User {u}: {'Exists' if db_user else 'Missing'}")
