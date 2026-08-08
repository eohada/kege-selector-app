import sys
import os
import json

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from core.db_models import db, User, Student, UserAchievement

def run_student_profile_and_achievements_qa_tests():
    print("============================================================")
    print("STARTING QA TESTS: STUDENT PROFILE EDIT & ACHIEVEMENTS V2")
    print("============================================================\n")

    app = create_app('testing')
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False

    with app.app_context():
        # Setup test database
        db.create_all()

        # Create or fetch test student user
        student_user = User.query.filter_by(username='qa_student_edit_test').first()
        if not student_user:
            from werkzeug.security import generate_password_hash
            student_user = User(
                username='qa_student_edit_test',
                email='qa_student_edit@boostudy.ru',
                role='student',
                full_name='Иван Исходный',
                password_hash=generate_password_hash('Password123!')
            )
            db.session.add(student_user)
            db.session.commit()

        student_profile = Student.query.filter_by(user_id=student_user.id).first()
        if not student_profile:
            student_profile = Student(
                user_id=student_user.id,
                name=student_user.full_name,
                category='10 Класс',
                goal_text='Сдать КЕГЭ на 80 баллов'
            )
            db.session.add(student_profile)
            db.session.commit()

        client = app.test_client()

        # Login as student via session transaction
        with client.session_transaction() as sess:
            sess['_user_id'] = str(student_user.id)
            sess['_fresh'] = True

        # --- TEST 1: GET /profile (Renders Universal Profile with Modals) ---
        print("--- TEST 1: GET /profile (Student Profile Page & Modals) ---")
        res_prof = client.get('/profile')
        assert res_prof.status_code == 200, f"Expected 200, got {res_prof.status_code}"
        html_prof = res_prof.get_data(as_text=True)
        assert 'profile-edit-modal' in html_prof, "Modal #profile-edit-modal must exist in HTML"
        assert 'achievements-modal' in html_prof, "Modal #achievements-modal must exist in HTML"
        assert 'Достижения &amp; Ачивки' in html_prof or 'Достижения & Ачивки' in html_prof or 'Достижения' in html_prof
        print("SUCCESS: GET /profile renders student profile with edit and achievement modals!")

        # --- TEST 2: POST /sandbox/api/profile/edit (Update Profile API) ---
        print("\n--- TEST 2: POST /sandbox/api/profile/edit (Profile Edit API) ---")
        update_payload = {
            'full_name': 'Иван Обновленный',
            'goal_text': 'Сдать КЕГЭ 2026 на 100 баллов!',
            'school_class': '11',
            'about_me': 'Увлеченный разработчик и отличник КЕГЭ.',
            'telegram_link': '@ivan_kege_pro'
        }
        res_edit = client.post('/sandbox/api/profile/edit', data=update_payload)
        assert res_edit.status_code == 200, f"Expected 200, got {res_edit.status_code}"
        data_edit = json.loads(res_edit.get_data(as_text=True))
        assert data_edit.get('status') == 'ok' or data_edit.get('success') is True
        assert 'Профиль успешно обновлен!' in data_edit.get('message', '')

        # Verify DB updates
        db.session.refresh(student_user)
        db.session.refresh(student_profile)
        assert student_user.full_name == 'Иван Обновленный', f"Expected 'Иван Обновленный', got '{student_user.full_name}'"
        assert student_profile.goal_text == 'Сдать КЕГЭ 2026 на 100 баллов!', f"Got '{student_profile.goal_text}'"
        assert student_profile.category == '11 Класс', f"Got '{student_profile.category}'"
        assert student_user.about_me == 'Увлеченный разработчик и отличник КЕГЭ.', f"Got '{student_user.about_me}'"
        assert student_user.telegram_link == '@ivan_kege_pro', f"Got '{student_user.telegram_link}'"
        print("SUCCESS: Student profile attributes updated in DB and response 200 OK!")

        # --- TEST 3: Zero Native alert()/confirm() Audit ---
        print("\n--- TEST 3: Zero Native alert()/confirm() Audit ---")
        for fname in ['universal_profile.html', '_student_body.html']:
            fpath = os.path.join(app.root_path, '..', 'templates', 'sandbox', 'profile', fname)
            with open(fpath, 'r', encoding='utf-8') as f:
                content = f.read()
                assert 'confirm(' not in content, f"Native confirm() found in {fname}!"
                assert 'alert(' not in content, f"Native alert() found in {fname}!"
        print("SUCCESS: 0 native alert() and 0 native confirm() in student profile templates!")

        print("\n============================================================")
        print("ALL QA TESTS FOR STUDENT PROFILE EDIT & ACHIEVEMENTS PASSED!")
        print("============================================================\n")

if __name__ == '__main__':
    run_student_profile_and_achievements_qa_tests()
