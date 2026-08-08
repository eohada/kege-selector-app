import sys
import os
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from app import create_app
from app.models import db, User, Student, Course
from core.db_models import SchoolGroup, GroupStudent

app = create_app()
app.config['WTF_CSRF_ENABLED'] = False
app.config['DEBUG'] = True
app.config['TESTING'] = True

def run_groups_page_tests():
    with app.app_context():
        # Setup test tutor
        tutor_user = User(
            username=f'tutor_grp_{uuid.uuid4().hex[:4]}',
            email=f'tutor_grp_{uuid.uuid4().hex[:4]}@test.com',
            role='tutor',
            password_hash='hash',
            is_active=True
        )
        db.session.add(tutor_user)
        db.session.commit()

        # Setup test student
        student_user = User(
            username=f'student_grp_{uuid.uuid4().hex[:4]}',
            email=f'student_grp_{uuid.uuid4().hex[:4]}@test.com',
            role='student',
            password_hash='hash',
            is_active=True
        )
        db.session.add(student_user)
        db.session.commit()

        student = Student(
            student_id=student_user.id,
            user_id=student_user.id,
            name='Иван Иванов',
            email=student_user.email,
            school_class='11А'
        )
        db.session.add(student)
        db.session.commit()

        # Setup test group
        group = SchoolGroup(
            title='ЕГЭ Информатика 2026',
            subject='Информатика',
            tag='Мини-группа',
            description='Подготовка к ЕГЭ на 90+ баллов',
            owner_user_id=tutor_user.id,
            telegram_chat_link='https://t.me/test_group_chat',
            status='active'
        )
        db.session.add(group)
        db.session.commit()

        # Attach student
        gs = GroupStudent(group_id=group.group_id, student_id=student.student_id, added_by_user_id=tutor_user.id)
        db.session.add(gs)
        db.session.commit()

        tutor_id = tutor_user.id
        group_id = group.group_id
        student_id = student.student_id

    client = app.test_client()

    print("\n--- TEST 1: GET /groups as Tutor ---")
    with client.session_transaction() as sess:
        sess['_user_id'] = str(tutor_id)
        sess['_fresh'] = True
        sess['sandbox_role'] = 'tutor'

    res1 = client.get('/groups')
    assert res1.status_code == 200, f"Expected 200 for GET /groups, got {res1.status_code}"
    html1 = res1.get_data(as_text=True)
    assert 'Группы и классы' in html1, "Page title 'Группы и классы' should be present"
    assert 'ЕГЭ Информатика 2026' in html1, "Group title should be rendered on page"
    print("SUCCESS: GET /groups returned 200 OK (V2 Groups List Page Loaded!)")

    print("\n--- TEST 2: GET /teacher/group/<id> (Group Detail Page) ---")
    res2 = client.get(f'/teacher/group/{group_id}')
    assert res2.status_code == 200, f"Expected 200 for group detail, got {res2.status_code}"
    html2 = res2.get_data(as_text=True)
    assert 'ЕГЭ Информатика 2026' in html2, "Group detail title should be present"
    assert 'Иван Иванов' in html2, "Attached student name should be rendered"
    print("SUCCESS: GET /teacher/group/<id> returned 200 OK (Group Detail Page Loaded!)")

    print("\n--- TEST 3: POST /api/teacher/groups (Create Group API) ---")
    res3 = client.post('/api/teacher/groups', json={
        'name': 'ОГЭ Физика 2026',
        'subject': 'Физика',
        'tag': 'Школьный класс',
        'description': 'Интенсивный разбор заданий',
        'telegram_chat_link': 'https://t.me/physics_chat',
        'student_ids': [student_id]
    })
    assert res3.status_code == 201, f"Expected 201 for POST group, got {res3.status_code}"
    data3 = res3.get_json()
    assert data3['status'] == 'success', f"Expected success status, got {data3}"
    new_group_id = data3['group_id']
    print(f"SUCCESS: Group created successfully via API! New ID: {new_group_id}")

    print("\n--- TEST 4: DELETE /api/teacher/groups/<id> (Delete Group API) ---")
    res4 = client.delete(f'/api/teacher/groups/{new_group_id}')
    assert res4.status_code == 200, f"Expected 200 for DELETE group, got {res4.status_code}"
    data4 = res4.get_json()
    assert data4['status'] == 'success', f"Expected success status, got {data4}"
    print("SUCCESS: Group deleted successfully via API!")

    print("\n--- TEST 5: Attempt GET /groups as Student (Soft Redirect) ---")
    with client.session_transaction() as sess:
        sess['_user_id'] = str(tutor_id)
        sess['_fresh'] = True
        sess['sandbox_role'] = 'student'

    res5 = client.get('/groups', follow_redirects=False)
    assert res5.status_code == 302, f"Expected 302 redirect for student, got {res5.status_code}"
    loc5 = res5.headers.get('Location')
    assert loc5 == '/dashboard', f"Expected redirect to '/dashboard', got '{loc5}'"
    print("SUCCESS: Student access to /groups smoothly redirected to /dashboard!")

    print("\nALL GROUPS AND CLASSES V2 QA TESTS PASSED PERFECTLY!")

if __name__ == '__main__':
    run_groups_page_tests()
