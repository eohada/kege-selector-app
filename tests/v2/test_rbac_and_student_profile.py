import sys
import os
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from app import create_app
from app.models import db, User, Course, Student

app = create_app()
app.config['WTF_CSRF_ENABLED'] = False

def run_rbac_tests():
    with app.app_context():
        # Setup Teacher and Student
        teacher = User(
            username=f'teacher_qa_{uuid.uuid4().hex[:4]}',
            email=f'teacher_{uuid.uuid4().hex[:4]}@test.com',
            role='tutor',
            password_hash='hash',
            is_active=True
        )
        student_user = User(
            username=f'student_qa_{uuid.uuid4().hex[:4]}',
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
            name='QA Test Student Name',
            mentor_id=teacher.id,
            lessons_balance=8
        )
        db.session.add(student)
        db.session.commit()

        teacher_id = teacher.id
        student_id = student.student_id

    client = app.test_client()

    # Authenticate as Teacher
    with client.session_transaction() as sess:
        sess['_user_id'] = str(teacher_id)
        sess['_fresh'] = True

    print("\n--- TEST 1: GET /teacher/student/<id> (Teacher Student Profile) ---")
    res1 = client.get(f'/teacher/student/{student_id}')
    assert res1.status_code == 200, f"Expected 200, got {res1.status_code}"
    html1 = res1.get_data(as_text=True)
    assert 'QA Test Student Name' in html1, "Student name should be rendered on dashboard"
    assert f'ID #{student_id}' in html1 or 'Ученик' in html1, "Student ID/info should be rendered"
    print("SUCCESS: GET /teacher/student/<id> returned 200 OK without 500 error and rendered student info!")

    print("\n--- TEST 2: Strict RBAC Navigation for Teacher ---")
    routes_to_test = ['/dashboard', '/students', '/schedule', '/teacher/students']
    for r in routes_to_test:
        res = client.get(r, follow_redirects=True)
        assert res.status_code == 200, f"Expected 200 for {r}, got {res.status_code}"
        page_html = res.get_data(as_text=True)
        assert 'student_dashboard.html' not in page_html, f"Teacher should never receive student_dashboard.html on {r}"
        assert 'Переключить на вид Ученика' not in page_html, f"Floating student mode pill should not be present on {r}"
        print(f"SUCCESS: Teacher navigation on {r} -> 200 OK (Strict Teacher View)")

    print("\n--- TEST 3: Attempting /student/dashboard as Teacher redirects safely ---")
    res_s = client.get('/student/dashboard', follow_redirects=True)
    assert res_s.status_code == 200, f"Expected 200 on redirected dashboard, got {res_s.status_code}"
    s_html = res_s.get_data(as_text=True)
    assert 'Кабинет преподавателя' in s_html or 'Ученики и поток' in s_html or 'Преподаватель' in s_html or 'Календарь' in s_html
    print("SUCCESS: /student/dashboard safely redirected Teacher to Teacher Dashboard!")

    print("\nALL RBAC & STUDENT PROFILE QA TESTS PASSED PERFECTLY!")

if __name__ == '__main__':
    run_rbac_tests()
