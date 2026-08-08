import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import traceback
from app import create_app
from core.db_models import db, User

def run_audit():
    app = create_app()
    app.config['TESTING'] = True
    app.config['DEBUG'] = True

    routes = [
        '/',
        '/dashboard',
        '/groups',
        '/library',
        '/schedule',
        '/analytics',
        '/tester',
        '/admin/qa',
        '/trainer',
        '/assignments',
        '/students',
        '/create_assignment',
        '/profile'
    ]

    with app.app_context():
        admin = User.query.filter_by(username='admin_1').first() or User.query.filter_by(role='admin').first()
        teacher = User.query.filter_by(username='teacher_1').first() or User.query.filter_by(role='teacher').first()
        student = User.query.filter_by(username='student_1').first() or User.query.filter_by(role='student').first()

    for role_name, user_obj in [('Admin', admin), ('Teacher', teacher), ('Student', student)]:
        if not user_obj:
            print(f"User for role {role_name} not found!")
            continue
        print(f"\n=== TESTING ROLE: {role_name} (ID: {user_obj.id}, username: {user_obj.username}) ===")
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['_user_id'] = str(user_obj.id)
                sess['user_id'] = user_obj.id
                sess['role'] = user_obj.role
                sess['active_role'] = user_obj.role

            for r in routes:
                try:
                    res = client.get(r, follow_redirects=True)
                    status = res.status_code
                    status_icon = "✅ 200" if status == 200 else f"❌ {status}"
                    print(f"  {r:<25} -> {status_icon}")
                    if status >= 500:
                        print(f"   !!! ERROR 500 ON {r} !!!")
                        html = res.data.decode('utf-8', 'ignore')
                        print("   " + repr(html[:300]))
                except Exception as e:
                    print(f"  {r:<25} -> EXCEPTION: {e}")
                    traceback.print_exc(file=sys.stdout)

if __name__ == '__main__':
    run_audit()
