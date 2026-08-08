"""
QA Automated Test Suite for Admin Workspace V2 Entry Points & Mode Switcher
"""
import os
import sys
import glob

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from app.models import db, User
from werkzeug.security import generate_password_hash

def run_admin_workspace_entry_points_qa_tests():
    os.environ['SECRET_KEY'] = 'test_secret_key_v2_entry'
    print("============================================================")
    print("STARTING QA TESTS: ADMIN ENTRY POINTS & WORKSPACE SWITCHER")
    print("============================================================\n")

    app = create_app('testing')
    app.config['TESTING'] = True
    app.config['SECRET_KEY'] = 'test_secret_key_v2_entry'
    app.config['WTF_CSRF_ENABLED'] = False

    with app.app_context():
        db.create_all()
        pwd_hash = generate_password_hash('password123')
        from core.db_models import UserRole

        # Seed CREATOR test user
        creator_user = User.query.filter_by(username='creator_entry_test_99').first()
        if not creator_user:
            creator_user = User(username='creator_entry_test_99', email='creator_entry_test_99@boostudy.ru', role='creator', password_hash=pwd_hash)
            db.session.add(creator_user)
            db.session.flush()
        creator_user.role = 'creator'
        if not UserRole.query.filter_by(user_id=creator_user.id, role='creator').first():
            db.session.add(UserRole(user_id=creator_user.id, role='creator'))

        db.session.commit()
        creator_id = creator_user.id

        client = app.test_client()

        # Login CREATOR user
        with client.session_transaction() as sess:
            sess['_user_id'] = str(creator_id)
            sess['_fresh'] = True
            sess['sandbox_role'] = 'creator'
            sess['work_mode'] = 'admin'

        # --- TEST 1: Entry Point on Profile Page (/profile) ---
        print("--- TEST 1: Profile Page Action Bar & Mode Switcher Card ---")
        res_prof = client.get('/profile')
        assert res_prof.status_code == 200, f"Expected 200 for /profile, got {res_prof.status_code}"
        html_prof = res_prof.get_data(as_text=True)
        assert 'Панель управления' in html_prof and '/admin/users' in html_prof, "Missing [ 🏛️ Панель управления ] button in Profile Action Bar!"
        assert 'Переключение рабочего пространства' in html_prof, "Missing 'Переключение рабочего пространства' block in Profile!"
        assert '/admin/mode/switch?mode=admin' in html_prof and '/admin/mode/switch?mode=teacher' in html_prof, "Missing mode switch buttons in Profile!"
        print("SUCCESS: Profile page contains [ 🏛️ Панель управления ] button and Workspace Switcher!")

        # --- TEST 2: Admin Layout Header Mode Indicator & Quick Exit ---
        print("\n--- TEST 2: Admin Layout Mode Indicator & Teacher Exit Button ---")
        res_admin = client.get('/admin/users')
        assert res_admin.status_code == 200, f"Expected 200 for /admin/users, got {res_admin.status_code}"
        html_admin = res_admin.get_data(as_text=True)
        assert 'Режим Админа' in html_admin, "Missing Active Mode Indicator badge in Admin header!"
        assert 'В кабинет преподавателя' in html_admin and '/admin/mode/switch?mode=teacher' in html_admin, "Missing quick exit link to Teacher workspace in Admin header!"
        print("SUCCESS: Admin layout contains mode indicator and quick exit link!")

        # --- TEST 3: Sidebar Dock Shield Item Verification ---
        print("\n--- TEST 3: Sidebar Dock Shield Item in Teacher Layout ---")
        # Check that layout_teacher.html contains the shield-check icon and href="/admin/users"
        teacher_tpl_path = os.path.join(app.root_path, '..', 'templates', 'sandbox', 'layout_teacher.html')
        with open(teacher_tpl_path, 'r', encoding='utf-8') as f:
            t_content = f.read()
            assert 'ph-shield-check' in t_content and 'href="/admin/users"' in t_content, "Sidebar layout_teacher.html missing Admin shield item!"
            assert "role|upper in ['CREATOR', 'ADMIN']" in t_content or "is_admin()" in t_content, "Sidebar layout_teacher.html missing RBAC check for CREATOR/ADMIN!"
        print("SUCCESS: Sidebar layout_teacher.html contains Admin shield item for CREATOR/ADMIN!")

        # --- TEST 4: Zero Native alert() & confirm() Audit ---
        print("\n--- TEST 4: Zero Native alert() & confirm() Audit ---")
        modified_templates = [
            os.path.join(app.root_path, '..', 'templates', 'sandbox', 'profile', 'universal_profile.html'),
            os.path.join(app.root_path, '..', 'templates', 'sandbox', 'profile', '_generic_body.html'),
            os.path.join(app.root_path, '..', 'templates', 'sandbox', 'layout_teacher.html'),
            os.path.join(app.root_path, '..', 'templates', 'sandbox', 'layout_student.html'),
            os.path.join(app.root_path, '..', 'templates', 'sandbox', 'layout_parent.html'),
            os.path.join(app.root_path, '..', 'templates', 'sandbox', 'layout_admin.html')
        ]
        for tpl in modified_templates:
            with open(tpl, 'r', encoding='utf-8') as f:
                content = f.read()
                assert 'alert(' not in content, f"Native alert() found in {tpl}"
                assert 'confirm(' not in content, f"Native confirm() found in {tpl}"
        print("SUCCESS: Zero native alert() and confirm() in modified templates!")

        print("\n============================================================")
        print("ALL QA ENTRY POINT & MODE SWITCHER TESTS PASSED PERFECTLY!")
        print("============================================================\n")

if __name__ == '__main__':
    run_admin_workspace_entry_points_qa_tests()
