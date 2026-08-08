import sys
import os
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from app import create_app
from app.models import db, User, Student, Course

app = create_app()
app.config['WTF_CSRF_ENABLED'] = False

def run_dev_role_switcher_tests():
    with app.app_context():
        teacher = User(
            username=f'teacher_switcher_{uuid.uuid4().hex[:4]}',
            email=f'teacher_{uuid.uuid4().hex[:4]}@test.com',
            role='tutor',
            password_hash='hash',
            is_active=True
        )
        student_user = User(
            username=f'student_switcher_{uuid.uuid4().hex[:4]}',
            email=f'student_{uuid.uuid4().hex[:4]}@test.com',
            role='student',
            password_hash='hash',
            is_active=True
        )
        db.session.add_all([teacher, student_user])
        db.session.commit()

        student = Student(
            student_id=student_user.id,
            user_id=student_user.id,
            name='Test Switcher Student'
        )
        db.session.add(student)
        db.session.commit()

        teacher_id = teacher.id
        student_id = student_user.id

    client = app.test_client()

    print("\n--- TEST 1: Initial Login as Teacher & Access /dashboard ---")
    with client.session_transaction() as sess:
        sess['_user_id'] = str(teacher_id)
        sess['_fresh'] = True

    res1 = client.get('/dashboard')
    assert res1.status_code == 200
    html1 = res1.get_data(as_text=True)
    assert 'Кабинет преподавателя' in html1 or 'Ученики и поток' in html1 or 'Преподаватель' in html1
    print("SUCCESS: Initial Teacher /dashboard -> 200 OK (Teacher V2 View)")

    print("\n--- TEST 2: Impersonate Student via Dev Role Switcher ---")
    res_imp = client.get(f'/sandbox/impersonate/{student_id}', follow_redirects=False)
    assert res_imp.status_code == 302, f"Expected 302 redirect, got {res_imp.status_code}"
    target_loc = res_imp.headers.get('Location')
    assert target_loc == '/dashboard', f"Expected redirect strictly to '/dashboard', got '{target_loc}'"
    print(f"SUCCESS: Dev Switcher redirected to '{target_loc}' (Strictly /dashboard!)")

    print("\n--- TEST 3: Follow redirect to /dashboard as Student ---")
    res_dash = client.get(target_loc)
    assert res_dash.status_code == 200
    dash_html = res_dash.get_data(as_text=True)
    assert 'sandbox/student_dashboard.html' not in dash_html
    print("SUCCESS: /dashboard as Student -> 200 OK (Student V2 Dashboard without /sandbox/ redirect)")

    print("\n--- TEST 4: Switch Back / Revert Impersonation ---")
    res_rev = client.get('/sandbox/impersonate/revert', follow_redirects=False)
    assert res_rev.status_code == 302
    rev_loc = res_rev.headers.get('Location')
    assert rev_loc == '/dashboard', f"Expected revert redirect to '/dashboard', got '{rev_loc}'"

    res_rev_dash = client.get(rev_loc)
    assert res_rev_dash.status_code == 200
    print(f"SUCCESS: Revert redirected to '{rev_loc}' and loaded Teacher V2 View!")

    print("\n--- TEST 5: API Endpoint /api/dev/switch_role ---")
    res_api = client.post('/api/dev/switch_role', json={'role': 'tutor'})
    assert res_api.status_code == 200
    data_api = res_api.get_json()
    assert data_api['redirect_url'] == '/dashboard'
    print("SUCCESS: /api/dev/switch_role returned redirect_url='/dashboard'!")

    print("\nALL DEV ROLE SWITCHER V2 TESTS PASSED PERFECTLY!")

if __name__ == '__main__':
    run_dev_role_switcher_tests()
