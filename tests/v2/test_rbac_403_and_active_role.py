import sys
import os
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from app import create_app
from app.models import db, User, Student, Course

app = create_app()
app.config['WTF_CSRF_ENABLED'] = False
app.config['DEBUG'] = True
app.config['TESTING'] = True

def run_rbac_sync_tests():
    with app.app_context():
        # Setup test tutor and student
        tutor_user = User(
            username=f'tutor_sync_{uuid.uuid4().hex[:4]}',
            email=f'tutor_{uuid.uuid4().hex[:4]}@test.com',
            role='tutor',
            password_hash='hash',
            is_active=True
        )
        student_user = User(
            username=f'student_sync_{uuid.uuid4().hex[:4]}',
            email=f'student_{uuid.uuid4().hex[:4]}@test.com',
            role='student',
            password_hash='hash',
            is_active=True
        )
        db.session.add_all([tutor_user, student_user])
        db.session.commit()

        student = Student(
            student_id=student_user.id,
            user_id=student_user.id,
            name='Test Sync Student',
            mentor_id=tutor_user.id,
            lessons_balance=10
        )
        db.session.add(student)
        db.session.commit()

        tutor_id = tutor_user.id
        student_id = student_user.id

    client = app.test_client()

    print("\n--- TEST 1: Switch Dev Role to Tutor -> GET /students -> 200 OK ---")
    with client.session_transaction() as sess:
        sess['_user_id'] = str(tutor_id)
        sess['_fresh'] = True
        sess['sandbox_role'] = 'tutor'

    res1 = client.get('/students')
    assert res1.status_code == 200, f"Expected 200 for Tutor on /students, got {res1.status_code}"
    print("SUCCESS: GET /students under tutor role returned 200 OK (no 403 error)!")

    print("\n--- TEST 2: Switch Dev Role to Student -> GET /students -> Soft Redirect to /dashboard ---")
    with client.session_transaction() as sess:
        sess['_user_id'] = str(tutor_id)
        sess['_fresh'] = True
        sess['sandbox_role'] = 'student'

    res2 = client.get('/students', follow_redirects=False)
    assert res2.status_code == 302, f"Expected 302 soft redirect for Student on /students, got {res2.status_code}"
    loc2 = res2.headers.get('Location')
    assert loc2 == '/dashboard', f"Expected redirect to '/dashboard', got '{loc2}'"
    print("SUCCESS: GET /students under student role smoothly redirected to /dashboard without 403 error screen!")

    print("\n--- TEST 3: Impersonation with login_user and sandbox_role sync ---")
    res_imp = client.get(f'/sandbox/impersonate/{student_id}', follow_redirects=True)
    assert res_imp.status_code == 200, f"Expected 200 after impersonation redirect, got {res_imp.status_code}"
    with client.session_transaction() as sess:
        assert sess.get('sandbox_role') == 'student', f"Expected session['sandbox_role'] == 'student', got {sess.get('sandbox_role')}"
    print("SUCCESS: Impersonation updated session['sandbox_role'] and logged in target user successfully!")

    print("\nALL RBAC 403 FIX AND ACTIVE ROLE SYNC TESTS PASSED PERFECTLY!")

if __name__ == '__main__':
    run_rbac_sync_tests()
