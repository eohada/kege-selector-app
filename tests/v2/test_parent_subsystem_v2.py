"""
QA Automated Test Suite for Parent Subsystem V2 (BooStudy V2)
Tests:
1. Student login & link_code generation (user.generate_parent_code()).
2. Parent login & POST /api/parent/link_child with student link_code -> 200 OK & FamilyTie record created.
3. GET /parents/dashboard as Parent -> 200 OK & linked child metrics rendered.
4. GET /profile as Parent -> 200 OK & _parent_body.html rendered.
5. Duplicate link attempt -> 400 Bad Request error response handled correctly.
6. DELETE /api/parent/unlink_child/<student_id> -> 200 OK & link removed from DB.
"""
import sys
import os
import json
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from app import create_app
from core.db_models import db, User, FamilyTie, Student, moscow_now
from flask import g

def run_parent_subsystem_qa_tests():
    app = create_app('testing')
    with app.app_context():
        from app.utils.db_migrations import ensure_schema_columns
        ensure_schema_columns(app)
        db.create_all()

        # 1. Seed or fetch test Student & Parent
        student_user = User.query.filter_by(username='qa_parent_test_student').first()
        if not student_user:
            student_user = User(
                username='qa_parent_test_student',
                email='student_qa_parent@boostudy.ru',
                password_hash='pbkdf2:sha256:testpassword',
                role='student'
            )
            db.session.add(student_user)
            db.session.commit()

        parent_user = User.query.filter_by(username='qa_parent_test_parent').first()
        if not parent_user:
            parent_user = User(
                username='qa_parent_test_parent',
                email='parent_qa_parent@boostudy.ru',
                password_hash='pbkdf2:sha256:testpassword',
                role='parent'
            )
            db.session.add(parent_user)
            db.session.commit()

        # Ensure student record in Students table
        student_db = Student.query.filter_by(user_id=student_user.id).first()
        if not student_db:
            student_db = Student(
                user_id=student_user.id,
                name='Иван Студентов',
                lessons_balance=10,
                xp=500
            )
            db.session.add(student_db)
            db.session.commit()

        # Clean any existing ties for these users
        FamilyTie.query.filter(
            (FamilyTie.parent_id == parent_user.id) & (FamilyTie.student_id == student_user.id)
        ).delete()
        db.session.commit()

        print(f"SEED VERIFICATION: student.id={student_user.id}, parent.id={parent_user.id}")

        client = app.test_client()

        # --- TEST 1: Link Code Generation ---
        print("\n--- TEST 1: Student Parent Link Code Generation ---")
        link_code = student_user.generate_parent_code()
        assert link_code is not None and link_code.startswith("BS-"), f"Invalid link_code: {link_code}"
        assert student_user.link_code == link_code
        print(f"SUCCESS: Student parent link code generated -> {link_code}")

        # --- TEST 2: POST /api/parent/link_child as Parent ---
        print("\n--- TEST 2: POST /api/parent/link_child (Link Child by Code) ---")
        if hasattr(g, '_login_user'):
            delattr(g, '_login_user')
        with client.session_transaction() as sess:
            sess['_user_id'] = str(parent_user.id)
            sess['sandbox_role'] = 'parent'
            sess['_fresh'] = True

        res_link = client.post('/api/parent/link_child', json={'student_code_or_email': link_code})
        assert res_link.status_code == 200, f"Expected 200, got {res_link.status_code}: {res_link.data}"
        data_link = json.loads(res_link.get_data(as_text=True))
        assert data_link.get('success') is True, f"Expected success=True: {data_link}"

        # Verify FamilyTie record in DB
        tie = FamilyTie.query.filter_by(parent_id=parent_user.id, student_id=student_user.id).first()
        assert tie is not None, "FamilyTie record must exist in DB!"
        assert tie.is_confirmed is True
        print(f"SUCCESS: POST /api/parent/link_child -> 200 OK & FamilyTie created in DB (tie_id={tie.tie_id})!")

        # --- TEST 3: GET /parents/dashboard ---
        print("\n--- TEST 3: GET /parents/dashboard (Parent Dashboard Rendering) ---")
        res_dash = client.get('/parents/dashboard')
        assert res_dash.status_code == 200, f"Expected 200, got {res_dash.status_code}"
        html_dash = res_dash.get_data(as_text=True)
        assert 'Кабинет родителя' in html_dash, "Page title 'Кабинет родителя' must be present"
        assert ('qa_parent_test_student' in html_dash or 'Иван Студентов' in html_dash), "Child's name must be in dashboard HTML"
        assert 'Семейный баланс' in html_dash
        print("SUCCESS: GET /parents/dashboard -> 200 OK with linked child metrics!")

        # --- TEST 4: GET /profile as Parent ---
        print("\n--- TEST 4: GET /profile as Parent (_parent_body.html Rendering) ---")
        res_prof = client.get('/profile')
        assert res_prof.status_code == 200, f"Expected 200, got {res_prof.status_code}"
        html_prof = res_prof.get_data(as_text=True)
        assert 'РОДИТЕЛЬСКИЙ КОНТРОЛЬ' in html_prof or 'Дети на платформе BooStudy' in html_prof, "Parent profile body must be rendered"
        print("SUCCESS: GET /profile -> 200 OK with _parent_body.html!")

        # --- TEST 5: Duplicate Link Attempt (400 Bad Request) ---
        print("\n--- TEST 5: Duplicate Link Attempt (Validation) ---")
        res_dup = client.post('/api/parent/link_child', json={'student_code_or_email': link_code})
        assert res_dup.status_code == 400, f"Expected 400, got {res_dup.status_code}"
        data_dup = json.loads(res_dup.get_data(as_text=True))
        assert data_dup.get('success') is False
        assert 'уже привязан' in data_dup.get('message', '')
        print("SUCCESS: Duplicate link attempt rejected with HTTP 400 Bad Request!")

        # --- TEST 6: DELETE /api/parent/unlink_child/<id> ---
        print("\n--- TEST 6: DELETE /api/parent/unlink_child/<id> (Unlink Child) ---")
        res_unlink = client.delete(f'/api/parent/unlink_child/{student_user.id}')
        assert res_unlink.status_code == 200, f"Expected 200, got {res_unlink.status_code}"
        data_unlink = json.loads(res_unlink.get_data(as_text=True))
        assert data_unlink.get('success') is True

        tie_deleted = FamilyTie.query.filter_by(parent_id=parent_user.id, student_id=student_user.id).first()
        assert tie_deleted is None, "FamilyTie record must be deleted from DB!"
        print("SUCCESS: DELETE /api/parent/unlink_child -> 200 OK & FamilyTie deleted from DB!")

        # --- TEST 7: GET /parents/schedule & GET /parents/faq ---
        print("\n--- TEST 7: GET /parents/schedule & GET /parents/faq (Isolated Parent Layout) ---")
        res_sched = client.get('/parents/schedule')
        assert res_sched.status_code == 200, f"Expected 200, got {res_sched.status_code}"
        html_sched = res_sched.get_data(as_text=True)
        assert 'Расписание уроков детей' in html_sched or 'Расписание занятий' in html_sched

        res_faq = client.get('/parents/faq')
        assert res_faq.status_code == 200, f"Expected 200, got {res_faq.status_code}"
        html_faq = res_faq.get_data(as_text=True)
        assert 'Раздел FAQ находится в разработке' in html_faq
        print("SUCCESS: GET /parents/schedule & GET /parents/faq -> 200 OK with isolated parent dock!")

        # --- TEST 8: Zero Native alert()/confirm() Verification ---
        print("\n--- TEST 8: Zero Native alert()/confirm() Audit ---")
        for fname in ['parents_dashboard.html', '_parent_body.html', '_student_body.html']:
            fpath = os.path.join(app.root_path, '..', 'templates', 'sandbox', fname)
            if not os.path.exists(fpath):
                fpath = os.path.join(app.root_path, '..', 'templates', 'sandbox', 'profile', fname)
            with open(fpath, 'r', encoding='utf-8') as f:
                content = f.read()
                assert 'confirm(' not in content, f"Native confirm() found in {fname}!"
                assert 'alert(' not in content, f"Native alert() found in {fname}!"
        print("SUCCESS: 0 native alert() and 0 native confirm() found in parent & student workspace templates!")

        print("\n============================================================")
        print("ALL QA TESTS FOR PARENT SUBSYSTEM V2 PASSED 100% PERFECTLY!")
        print("============================================================\n")

if __name__ == '__main__':
    run_parent_subsystem_qa_tests()
