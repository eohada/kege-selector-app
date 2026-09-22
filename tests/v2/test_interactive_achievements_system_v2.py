import sys
import os
import json
import pytest

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from core.db_models import db, User, Student, UserAchievement
from app.utils.achievement_service import (
    ACHIEVEMENTS_REGISTRY,
    build_student_achievement_catalog,
    process_achievement_event,
    check_and_grant_dynamic_achievements
)

def test_achievements_registry_structure():
    """Verify registry has 53 achievements, with exactly 10 secret achievements."""
    assert len(ACHIEVEMENTS_REGISTRY) == 53, f"Expected 53 achievements, found {len(ACHIEVEMENTS_REGISTRY)}"

    secrets = [k for k, v in ACHIEVEMENTS_REGISTRY.items() if v.get('is_secret')]
    assert len(secrets) == 10, f"Expected exactly 10 secret achievements, got {len(secrets)}: {secrets}"

    expected_categories = {'workspace', 'tasks', 'theory', 'lessons', 'milestone', 'secret'}
    found_categories = set(v.get('category') for v in ACHIEVEMENTS_REGISTRY.values())
    assert expected_categories.issubset(found_categories), f"Missing categories: {expected_categories - found_categories}"

    # Verify each achievement has mandatory fields
    for key, ach in ACHIEVEMENTS_REGISTRY.items():
        assert 'title' in ach, f"Missing title in {key}"
        assert 'desc' in ach, f"Missing desc in {key}"
        assert 'icon' in ach, f"Missing icon in {key}"
        assert 'category' in ach, f"Missing category in {key}"
        assert 'rarity' in ach, f"Missing rarity in {key}"
        assert 'target' in ach, f"Missing target in {key}"
        assert 'xp_reward' in ach and ach['xp_reward'] > 0, f"Missing or invalid xp_reward in {key}"


def test_build_student_achievement_catalog_masking():
    """Test that build_student_achievement_catalog masks secret achievements until unlocked."""
    app = create_app('testing')
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False

    with app.app_context():
        db.create_all()

        user = User.query.filter_by(username='test_ach_catalog_user').first()
        if not user:
            from werkzeug.security import generate_password_hash
            user = User(
                username='test_ach_catalog_user',
                email='test_ach_catalog@boostudy.ru',
                role='student',
                full_name='Каталог Тестер',
                password_hash=generate_password_hash('Password123!')
            )
            db.session.add(user)
            db.session.commit()

        student = Student.query.filter_by(user_id=user.id).first()
        if not student:
            student = Student(user_id=user.id, name=user.full_name)
            db.session.add(student)
            db.session.commit()

        # Clean any existing achievements for this student
        UserAchievement.query.filter_by(student_id=student.student_id).delete()
        db.session.commit()

        # 1. Check catalog with 0 achievements
        catalog = build_student_achievement_catalog(student)
        assert len(catalog) == 53

        # Check an unearned secret achievement
        secret_locked = next((a for a in catalog if a['key'] == 'secret_ghost_friend'), None)
        assert secret_locked is not None
        assert secret_locked['is_secret'] is True
        assert secret_locked['unlocked'] is False
        assert secret_locked['status_type'] == 'secret_locked'
        assert secret_locked['title'] == 'Тайное достижение'
        assert secret_locked['icon'] == 'ph-lock-key'
        assert '???' in secret_locked['progress_display']

        # Check an unearned regular achievement
        regular_unearned = next((a for a in catalog if a['key'] == 'ide_run_shortcut'), None)
        assert regular_unearned is not None
        assert regular_unearned['is_secret'] is False
        assert regular_unearned['unlocked'] is False
        assert regular_unearned['title'] == ACHIEVEMENTS_REGISTRY['ide_run_shortcut']['title']

        # 2. Unlock the secret achievement and verify unmasking
        result = process_achievement_event(student, 'secret_ghost_friend', {'clicks': 5}, commit=True)
        assert result['unlocked'] is True
        assert result['achievement']['key'] == 'secret_ghost_friend'

        catalog_unlocked = build_student_achievement_catalog(student)
        secret_unmasked = next((a for a in catalog_unlocked if a['key'] == 'secret_ghost_friend'), None)
        assert secret_unmasked is not None
        assert secret_unmasked['unlocked'] is True
        assert secret_unmasked['status_type'] == 'unlocked'
        assert secret_unmasked['title'] == ACHIEVEMENTS_REGISTRY['secret_ghost_friend']['title']
        assert secret_unmasked['icon'] == ACHIEVEMENTS_REGISTRY['secret_ghost_friend']['icon']
        assert secret_unmasked['progress_display'] == '1 / 1'


def test_api_achievements_trigger_endpoint():
    """Test POST /api/achievements/trigger for client-side events."""
    app = create_app('testing')
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False

    with app.app_context():
        db.create_all()

        user = User.query.filter_by(username='test_api_trigger_user').first()
        if not user:
            from werkzeug.security import generate_password_hash
            user = User(
                username='test_api_trigger_user',
                email='test_api_trigger@boostudy.ru',
                role='student',
                full_name='API Триггер Тестер',
                password_hash=generate_password_hash('Password123!')
            )
            db.session.add(user)
            db.session.commit()

        student = Student.query.filter_by(user_id=user.id).first()
        if not student:
            student = Student(user_id=user.id, name=user.full_name)
            db.session.add(student)
            db.session.commit()

        UserAchievement.query.filter_by(student_id=student.student_id).delete()
        db.session.commit()

        client = app.test_client()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user.id)
            sess['_fresh'] = True

        # First trigger: ide_run_shortcut
        res1 = client.post('/api/achievements/trigger', json={'event': 'ide_run_shortcut'})
        assert res1.status_code == 200
        data1 = json.loads(res1.get_data(as_text=True))
        assert data1['status'] == 'ok'
        assert data1['unlocked'] is True
        assert data1['achievement']['key'] == 'ide_run_shortcut'
        assert data1['achievement']['xp_reward'] == ACHIEVEMENTS_REGISTRY['ide_run_shortcut']['xp_reward']

        # Triggering the same event again should not re-unlock
        res2 = client.post('/api/achievements/trigger', json={'event': 'ide_run_shortcut'})
        assert res2.status_code == 200
        data2 = json.loads(res2.get_data(as_text=True))
        assert data2['status'] == 'ok'
        assert data2['unlocked'] is False

        # Trigger secret easter egg
        res3 = client.post('/api/achievements/trigger', json={'event': 'secret_ghost_friend', 'clicks': 5})
        assert res3.status_code == 200
        data3 = json.loads(res3.get_data(as_text=True))
        assert data3['status'] == 'ok'
        assert data3['unlocked'] is True
        assert data3['achievement']['key'] == 'secret_ghost_friend'


def test_python_runtime_and_custom_events():
    """Test Python runtime error triggers and custom events (recursion, zerodivision, zen, syntax recovery)."""
    app = create_app('testing')
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False

    with app.app_context():
        db.create_all()

        user = User.query.filter_by(username='test_py_events_user').first()
        if not user:
            from werkzeug.security import generate_password_hash
            user = User(
                username='test_py_events_user',
                email='test_py_events@boostudy.ru',
                role='student',
                full_name='Python События Тестер',
                password_hash=generate_password_hash('Password123!')
            )
            db.session.add(user)
            db.session.commit()

        student = Student.query.filter_by(user_id=user.id).first()
        if not student:
            student = Student(user_id=user.id, name=user.full_name)
            db.session.add(student)
            db.session.commit()

        UserAchievement.query.filter_by(student_id=student.student_id).delete()
        db.session.commit()

        # 1. RecursionError
        res_rec = process_achievement_event(student, 'python_error', {'error_type': 'RecursionError: maximum recursion depth exceeded'})
        assert res_rec['unlocked'] is True
        assert res_rec['achievement']['key'] == 'secret_recursion_depth'

        # 2. ZeroDivisionError
        res_zero = process_achievement_event(student, 'python_error', {'error_type': 'ZeroDivisionError: division by zero'})
        assert res_zero['unlocked'] is True
        assert res_zero['achievement']['key'] == 'secret_zero_division'

        # 3. Zen of Python
        res_zen = process_achievement_event(student, 'zen_python')
        assert res_zen['unlocked'] is True
        assert res_zen['achievement']['key'] == 'secret_zen_python'

        # 4. Syntax recovery
        res_syn = process_achievement_event(student, 'syntax_recovery')
        assert res_syn['unlocked'] is True
        assert res_syn['achievement']['key'] == 'secret_syntax_recovery'

        # 5. KEGE Task 27
        res_task27 = process_achievement_event(student, 'task_correct', {'task_number': 27})
        assert res_task27['unlocked'] is True
        assert res_task27['achievement']['key'] == 'ege_task_27'

        # 6. Speedrun < 30s
        res_speed = process_achievement_event(student, 'task_speedrun', {'seconds': 20})
        assert res_speed['unlocked'] is True
        assert res_speed['achievement']['key'] == 'speedrun_task'

        # 7. Section visit (secret_all_sections)
        res_all = process_achievement_event(student, 'secret_all_sections')
        assert res_all['unlocked'] is True
        assert res_all['achievement']['key'] == 'secret_all_sections'


def test_profile_page_renders_achievements_catalog():
    """Test that /workspace/profile renders achievements and the secret tab."""
    app = create_app('testing')
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False

    with app.app_context():
        db.create_all()

        user = User.query.filter_by(username='test_render_profile_user').first()
        if not user:
            from werkzeug.security import generate_password_hash
            user = User(
                username='test_render_profile_user',
                email='test_render_profile@boostudy.ru',
                role='student',
                full_name='Рендер Профиль Тестер',
                password_hash=generate_password_hash('Password123!')
            )
            db.session.add(user)
            db.session.commit()

        student = Student.query.filter_by(user_id=user.id).first()
        if not student:
            student = Student(user_id=user.id, name=user.full_name)
            db.session.add(student)
            db.session.commit()

        client = app.test_client()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user.id)
            sess['_fresh'] = True

        res = client.get('/workspace/profile')
        assert res.status_code == 200
        html = res.get_data(as_text=True)

        assert 'achievements-modal' in html
        assert 'Секретные' in html
        assert 'Тайное достижение' in html
        assert 'profile-mascot-ghost' in html
