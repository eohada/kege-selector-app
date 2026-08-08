import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from app import create_app
from app.models import db, User, Student

app = create_app()

with app.app_context():
    users = User.query.all()
    print("USERS COUNT:", len(users))
    for u in users:
        st = Student.query.filter_by(user_id=u.id).first()
        st_by_id = Student.query.get(u.id)
        print(f"User ID={u.id}, username={u.username}, role={u.role}")
        print(f"  -> Student by user_id: {st.student_id if st else None}")
        print(f"  -> Student by get(id): {st_by_id.student_id if st_by_id else None}")
        print(f"  -> u.student_profile: {u.student_profile.student_id if u.student_profile else None}")
