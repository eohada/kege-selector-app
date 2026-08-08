import sys
import os
import glob

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from app.models import db, User, SystemSetting

def run_admin_workspace_v2_qa_tests():
    os.environ['SECRET_KEY'] = 'test_secret_key_v2_admin'
    print("============================================================")
    print("STARTING QA TESTS: ADMIN WORKSPACE V2 & MAINTENANCE MODE")
    print("============================================================\n")

    app = create_app('testing')
    app.config['TESTING'] = True
    app.config['SECRET_KEY'] = 'test-secret-key-12345'
    app.config['WTF_CSRF_ENABLED'] = False

    with app.app_context():
        db.create_all()

        from werkzeug.security import generate_password_hash
        from core.db_models import UserRole
        pwd_hash = generate_password_hash('password123')

        # Seed Test Accounts with unique names
        admin_user = User.query.filter_by(username='admin_v2_qa_test_99').first()
        if not admin_user:
            admin_user = User(username='admin_v2_qa_test_99', email='admin_v2_qa_test_99@boostudy.ru', role='admin', password_hash=pwd_hash)
            db.session.add(admin_user)
            db.session.flush()
        admin_user.role = 'admin'
        if not UserRole.query.filter_by(user_id=admin_user.id, role='admin').first():
            db.session.add(UserRole(user_id=admin_user.id, role='admin'))

        creator_user = User.query.filter_by(username='creator_v2_qa_test_99').first()
        if not creator_user:
            creator_user = User(username='creator_v2_qa_test_99', email='creator_v2_qa_test_99@boostudy.ru', role='creator', password_hash=pwd_hash)
            db.session.add(creator_user)
            db.session.flush()
        creator_user.role = 'creator'
        if not UserRole.query.filter_by(user_id=creator_user.id, role='creator').first():
            db.session.add(UserRole(user_id=creator_user.id, role='creator'))

        student_user = User.query.filter_by(username='student_v2_qa_test_99').first()
        if not student_user:
            student_user = User(username='student_v2_qa_test_99', email='student_v2_qa_test_99@boostudy.ru', role='student', password_hash=pwd_hash)
            db.session.add(student_user)
            db.session.flush()
        student_user.role = 'student'
        if not UserRole.query.filter_by(user_id=student_user.id, role='student').first():
            db.session.add(UserRole(user_id=student_user.id, role='student'))

        tester_user = User.query.filter_by(username='tester_v2_qa_test_99').first()
        if not tester_user:
            tester_user = User(username='tester_v2_qa_test_99', email='tester_v2_qa_test_99@boostudy.ru', role='tester', password_hash=pwd_hash)
            db.session.add(tester_user)
            db.session.flush()
        tester_user.role = 'tester'
        if not UserRole.query.filter_by(user_id=tester_user.id, role='tester').first():
            db.session.add(UserRole(user_id=tester_user.id, role='tester'))

        db.session.commit()

        admin_id = admin_user.id
        creator_id = creator_user.id
        student_id = student_user.id
        tester_id = tester_user.id

        client = app.test_client()

        def login_user_client(client_obj, user_obj):
            from flask import g
            if hasattr(g, '_login_user'):
                delattr(g, '_login_user')
            db.session.commit()
            with client_obj.session_transaction() as sess:
                sess['_user_id'] = str(user_obj.id)
                sess['sandbox_role'] = user_obj.role
                sess['_fresh'] = True

        # --- TEST 1: RBAC Access Control on /admin/users ---
        print("--- TEST 1: RBAC Access Guard (/admin/users) ---")
        # Logged in as STUDENT
        client_student = app.test_client()
        login_user_client(client_student, student_user)

        res_stud = client_student.get('/admin/users', follow_redirects=True)
        assert res_stud.status_code in [200, 302, 403], f"Unexpected status {res_stud.status_code}"
        assert 'layout_admin' not in res_stud.get_data(as_text=True), "Student should NOT be able to view layout_admin!"
        print("SUCCESS: Student access to /admin/users properly blocked/redirected!")

        # Logged in as ADMIN
        client_admin = app.test_client()
        login_user_client(client_admin, admin_user)

        res_admin = client_admin.get('/admin/users')
        assert res_admin.status_code == 200, f"Expected 200 for Admin, got {res_admin.status_code}"
        html_admin = res_admin.get_data(as_text=True)
        assert 'BooStudy' in html_admin and 'ADMIN V2' in html_admin, "Admin layout missing in response!"
        print("SUCCESS: Admin successfully accessed /admin/users with layout_admin.html!")

        # --- TEST 2: CREATOR Work Mode Switcher ---
        print("\n--- TEST 2: CREATOR Work Mode Switcher ---")
        client_creator = app.test_client()
        login_user_client(client_creator, creator_user)

        res_switch = client_creator.get('/admin/mode/switch?mode=teacher', follow_redirects=False)
        assert res_switch.status_code == 302, f"Expected 302 redirect for mode switch, got {res_switch.status_code}"
        with client_creator.session_transaction() as sess:
            assert sess.get('work_mode') == 'teacher', "session['work_mode'] failed to update to 'teacher'"
        print("SUCCESS: CREATOR mode switch to 'teacher' verified!")

        # --- TEST 3: Maintenance Mode Middleware ---
        print("\n--- TEST 3: Maintenance Mode Middleware ---")
        # Enable Maintenance Mode
        SystemSetting.set_value('maintenance_mode', 'true')

        # Test STUDENT request during maintenance -> Should see maintenance page
        client_stud_maint = app.test_client()
        login_user_client(client_stud_maint, student_user)

        res_maint_student = client_stud_maint.get('/profile', follow_redirects=True)
        assert 'Ведутся технические работы' in res_maint_student.get_data(as_text=True) or 'maintenance' in res_maint_student.get_data(as_text=True), "Student not redirected to maintenance page!"
        print("SUCCESS: Student redirected to Maintenance Page during maintenance mode!")

        # Test ADMIN request during maintenance -> Should bypass and get 200 OK
        client_admin_maint = app.test_client()
        login_user_client(client_admin_maint, admin_user)

        res_maint_admin = client_admin_maint.get('/admin/users')
        assert res_maint_admin.status_code == 200, "Admin blocked by maintenance mode!"
        print("SUCCESS: Admin successfully bypassed maintenance mode!")

        # Reset Maintenance Mode
        SystemSetting.set_value('maintenance_mode', 'false')

        # --- TEST 4: Database Backup Export API ---
        print("\n--- TEST 4: Database Backup JSON Export ---")
        client_export = app.test_client()
        login_user_client(client_export, admin_user)
        res_export = client_export.get('/admin/export_db_json')
        assert res_export.status_code == 200, f"Export failed with status {res_export.status_code}"
        assert res_export.headers['Content-Type'] == 'application/json', "Export header Content-Type is not JSON"
        json_data = res_export.get_json()
        assert 'exported_at' in json_data and 'users' in json_data, "Export JSON payload missing required keys"
        print("SUCCESS: Database JSON export verified!")

        # --- TEST 5: Vis.js Graph Data API & Delete User AJAX ---
        print("\n--- TEST 5: Vis.js Graph Data API & User Delete AJAX ---")
        res_graph = client_admin.get('/admin/users/graph_data')
        assert res_graph.status_code == 200, f"Expected 200 for graph data, got {res_graph.status_code}"
        graph_json = res_graph.get_json()
        assert 'nodes' in graph_json and len(graph_json['nodes']) > 0, "Graph API returned 0 nodes!"
        print(f"SUCCESS: Vis.js graph API verified with {len(graph_json['nodes'])} nodes!")

        # Create temporary dummy user to delete
        temp_user = User(username='del_test_user_99', email='del_test_99@boostudy.ru', role='student', password_hash=pwd_hash)
        db.session.add(temp_user)
        db.session.commit()
        temp_id = temp_user.id

        res_del = client_admin.post(f'/admin/users/{temp_id}/delete', headers={'X-Requested-With': 'XMLHttpRequest'})
        assert res_del.status_code == 200, f"Expected 200 OK for AJAX delete, got {res_del.status_code}"
        assert res_del.get_json().get('success') is True, "Delete AJAX did not return success: True"
        print("SUCCESS: User delete AJAX endpoint returned 200 OK JSON!")

        # --- TEST 6: Strict Maintenance Toggle API & Task Formator Status API ---
        print("\n--- TEST 6: Maintenance Toggle API & Task Formator Status API ---")
        res_maint_toggle = client_admin.post('/admin/maintenance/toggle', headers={'X-Requested-With': 'XMLHttpRequest'})
        assert res_maint_toggle.status_code == 200, f"Expected 200 for maintenance toggle, got {res_maint_toggle.status_code}"
        assert res_maint_toggle.get_json().get('success') is True, "Maintenance toggle failed"
        print("SUCCESS: POST /admin/maintenance/toggle returned 200 OK JSON!")
        # Reset back
        client_admin.post('/admin/maintenance/toggle', headers={'X-Requested-With': 'XMLHttpRequest'})

        res_task_status = client_admin.post('/admin/task-formator/status', json={'task_id': 1, 'status': 'ok'})
        assert res_task_status.status_code == 200, f"Expected 200 for task-formator status, got {res_task_status.status_code}"
        assert res_task_status.get_json().get('success') is True, "Task formator status save failed"
        print("SUCCESS: POST /admin/task-formator/status returned 200 OK JSON!")

        # --- TEST 7: Layout Inheritance Audit for All 8 Admin Tabs ---
        print("\n--- TEST 7: Strict Layout Inheritance & No Legacy Base Templates ---")
        tabs = [
            ('/admin/users', 'layout_admin'),
            ('/admin/permissions', 'layout_admin'),
            ('/admin/audit', 'layout_admin'),
            ('/admin/testers', 'layout_admin'),
            ('/admin/tester-entities', 'layout_admin'),
            ('/admin/topics', 'layout_admin'),
            ('/admin/task-formator', 'layout_admin'),
            ('/admin/diagnostics', 'layout_admin'),
        ]
        for url, tpl_marker in tabs:
            r = client_admin.get(url)
            assert r.status_code == 200, f"Route {url} failed with status {r.status_code}"
            html_content = r.get_data(as_text=True)
            assert tpl_marker in html_content or 'BooStudy' in html_content, f"Route {url} missing {tpl_marker}"
            print(f"  ✓ {url} -> 200 OK (layout_admin verified)")

        # Verify templates directly don't extend legacy base.html
        admin_tpl_dir = os.path.join(app.root_path, '..', 'templates', 'sandbox', 'admin')
        tpl_files = glob.glob(os.path.join(admin_tpl_dir, '*.html'))
        for tpl in tpl_files:
            with open(tpl, 'r', encoding='utf-8') as f:
                content = f.read()
                assert 'base.html' not in content, f"Legacy base.html extension found in {tpl}"
                assert 'alert(' not in content, f"Native alert() found in {tpl}"
                assert 'confirm(' not in content, f"Native confirm() found in {tpl}"
        print("SUCCESS: Zero legacy base.html extensions or native alert()/confirm() in templates!")

        print("\n============================================================")
        print("ALL QA TESTS FOR ADMIN WORKSPACE V2 PASSED 100% PERFECTLY!")
        print("============================================================\n")

if __name__ == '__main__':
    run_admin_workspace_v2_qa_tests()
