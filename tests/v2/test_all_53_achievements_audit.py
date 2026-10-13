"""
Comprehensive Audit Test Suite for BooStudy Achievements System.
Verifies all 53 achievements across all 6 categories, triggers,
condition evaluations, rewards, and dynamic checks.
"""
from datetime import datetime, timezone, timedelta
import pytest
from app import create_app
from core.db_models import (
    db, User, Student, UserAchievement, Submission, Assignment,
    AssignmentTask, Tasks, Answer, StudentTheoryState, TheoryGroup, TheoryBlock
)
from app.utils.achievement_service import (
    ACHIEVEMENTS_REGISTRY,
    build_student_achievement_catalog,
    grant_achievement,
    revoke_achievement,
    process_achievement_event,
    check_and_grant_dynamic_achievements,
    get_student_unlocked_achievement_keys,
)
from app.utils.gamification_service import (
    reward_submission,
    reward_theory_reading,
    reward_lesson_completion,
    reward_single_task_correct,
)


@pytest.fixture
def app_ctx():
    app = create_app('testing')
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.app_context():
        db.create_all()
        yield app


@pytest.fixture
def test_student(app_ctx):
    user = User.query.filter_by(username='ach_audit_student').first()
    if not user:
        from werkzeug.security import generate_password_hash
        user = User(
            username='ach_audit_student',
            email='ach_audit_student@boostudy.ru',
            role='student',
            full_name='Аудит Ученик',
            password_hash=generate_password_hash('Password123!')
        )
        db.session.add(user)
        db.session.commit()

    student = Student.query.filter_by(user_id=user.id).first()
    if not student:
        student = Student(user_id=user.id, name=user.full_name)
        db.session.add(student)
        db.session.commit()

    # Reset achievements for clean test slate
    UserAchievement.query.filter_by(student_id=student.student_id).delete()
    student.xp = 0
    student.streak_days = 0
    student.level = 1
    student.study_time_seconds = 0
    db.session.commit()
    return student


def test_registry_contains_all_53_achievements():
    """Verify registry has all 58 achievements (53 base + 4 weekly streak + 1 final test) and all 6 categories are populated."""
    assert len(ACHIEVEMENTS_REGISTRY) == 58, f"Expected 58 achievements, found {len(ACHIEVEMENTS_REGISTRY)}"

    expected_categories = {
        'workspace': 10,
        'tasks': 12,
        'theory': 6,
        'lessons': 7,
        'milestone': 12,
        'secret': 11,
    }

    category_counts = {}
    for key, ach in ACHIEVEMENTS_REGISTRY.items():
        cat = ach.get('category')
        category_counts[cat] = category_counts.get(cat, 0) + 1
        assert 'title' in ach and ach['title'], f"Missing title in {key}"
        assert 'desc' in ach and ach['desc'], f"Missing desc in {key}"
        assert 'icon' in ach and ach['icon'], f"Missing icon in {key}"
        assert 'rarity' in ach and ach['rarity'], f"Missing rarity in {key}"
        assert 'xp_reward' in ach and ach['xp_reward'] > 0, f"Missing xp_reward in {key}"
        assert 'target' in ach and ach['target'] > 0, f"Missing target in {key}"

    assert category_counts == expected_categories, f"Category counts mismatch: {category_counts}"


def test_grant_and_revoke_every_achievement(test_student):
    """Verify grant_achievement and revoke_achievement succeed for all 53 keys."""
    for key in ACHIEVEMENTS_REGISTRY.keys():
        granted = grant_achievement(test_student, key, award_xp=False, commit=True)
        assert granted is True, f"Failed to grant achievement {key}"

        # Duplicate grant should return False (idempotent)
        dup = grant_achievement(test_student, key, award_xp=False, commit=True)
        assert dup is False, f"Expected duplicate grant of {key} to return False"

        # Verify present in unlocked keys
        unlocked = get_student_unlocked_achievement_keys(test_student.student_id)
        assert key in unlocked, f"{key} not found in get_student_unlocked_achievement_keys"

        # Revoke
        revoked = revoke_achievement(test_student, key)
        assert revoked is True, f"Failed to revoke achievement {key}"

        unlocked_after = get_student_unlocked_achievement_keys(test_student.student_id)
        assert key not in unlocked_after, f"{key} still present after revoke"


def test_homework_perfect_and_early_bird_rewards(test_student):
    """Verify reward_submission correctly awards perfect_homework and early_bird_submission."""
    # Create test assignment with deadline 2 days in future
    now = datetime.now(timezone.utc)
    deadline = now + timedelta(days=2)
    assignment = Assignment(
        title='Тестовая домашка КЕГЭ',
        deadline=deadline,
        assignment_type='homework',
        created_by_id=test_student.user_id
    )
    db.session.add(assignment)
    db.session.commit()

    # Submission with 100% percentage
    submission = Submission(
        assignment_id=assignment.assignment_id,
        student_id=test_student.student_id,
        status='SUBMITTED',
        percentage=100.0,
        total_score=10,
        max_score=10,
        submitted_at=now,
    )
    db.session.add(submission)
    db.session.commit()

    awarded_xp = reward_submission(test_student, correct_answers=10, submission=submission)
    assert awarded_xp > 0

    unlocked = get_student_unlocked_achievement_keys(test_student.student_id)
    assert 'first_step' in unlocked, "first_step should be granted on submission"
    assert 'perfect_homework' in unlocked, "perfect_homework should be granted for 100% first try"
    assert 'early_bird_submission' in unlocked, "early_bird_submission should be granted >24h before deadline"


def test_kege_specific_tasks_and_speedrun(test_student):
    """Verify ege_task_X and speedrun_task achievements."""
    for task_num in [2, 8, 13, 16, 24, 26, 27]:
        res = process_achievement_event(test_student, 'task_correct', {'task_number': task_num}, commit=True)
        assert res['unlocked'] is True
        assert res['achievement']['key'] == f'ege_task_{task_num}'

    # Speedrun task
    res_speedrun = process_achievement_event(test_student, 'task_speedrun', commit=True)
    assert res_speedrun['unlocked'] is True
    assert res_speedrun['achievement']['key'] == 'speedrun_task'


def test_combo_5_correct_achievement(test_student):
    """Verify combo_5_correct when combo is passed or met."""
    res = process_achievement_event(test_student, 'task_correct', {'combo_correct': 5}, commit=True)
    unlocked = get_student_unlocked_achievement_keys(test_student.student_id)
    assert 'combo_5_correct' in unlocked


def test_theory_achievements(test_student):
    """Verify theory_first, theory_5_topics, and theory interactive triggers."""
    # 1. Interactive triggers
    res_quiz = process_achievement_event(test_student, 'theory_quiz_pass', commit=True)
    assert res_quiz['unlocked'] is True
    assert res_quiz['achievement']['key'] == 'theory_quiz_pass'

    res_snippet = process_achievement_event(test_student, 'theory_copy_snippet', commit=True)
    assert res_snippet['unlocked'] is True
    assert res_snippet['achievement']['key'] == 'theory_copy_snippet'

    res_search = process_achievement_event(test_student, 'theory_search_used', commit=True)
    assert res_search['unlocked'] is True
    assert res_search['achievement']['key'] == 'theory_search_used'

    # 2. Reading topics
    for i in range(1, 6):
        st = StudentTheoryState(
            student_id=test_student.student_id,
            task_number=i,
            reading_progress=100,
            is_read=True
        )
        db.session.add(st)
    db.session.commit()

    check_and_grant_dynamic_achievements(test_student, commit=True)
    unlocked = get_student_unlocked_achievement_keys(test_student.student_id)
    assert 'theory_first' in unlocked
    assert 'theory_5_topics' in unlocked


def test_lessons_and_profile_achievements(test_student):
    """Verify lesson_first_done, lesson_on_time, lesson_chat_active, lesson_code_live, and profile."""
    # Lesson completion
    reward_lesson_completion(test_student)
    unlocked = get_student_unlocked_achievement_keys(test_student.student_id)
    assert 'lesson_first_done' in unlocked

    # Lesson on time
    res_on_time = process_achievement_event(test_student, 'lesson_on_time', commit=True)
    assert res_on_time['unlocked'] is True

    # Lesson chat
    res_chat = process_achievement_event(test_student, 'lesson_chat_active', commit=True)
    assert res_chat['unlocked'] is True

    # Lesson code live
    res_code = process_achievement_event(test_student, 'lesson_code_live', commit=True)
    assert res_code['unlocked'] is True

    # Referral copied
    res_ref = process_achievement_event(test_student, 'referral_copied', commit=True)
    assert res_ref['unlocked'] is True

    # Profile avatar & bio
    res_avatar = process_achievement_event(test_student, 'profile_avatar_set', commit=True)
    assert res_avatar['unlocked'] is True

    res_bio = process_achievement_event(test_student, 'profile_bio_set', commit=True)
    assert res_bio['unlocked'] is True


def test_all_10_secret_easter_eggs(test_student):
    """Verify all 10 secret Easter egg achievements can be triggered and unlocked."""
    # 1. secret_night_owl
    res = process_achievement_event(test_student, 'time_based_submission', {'hour_msk': 2}, commit=True)
    assert res['unlocked'] is True
    assert res['achievement']['key'] == 'secret_night_owl'

    # 2. secret_early_bird
    res = process_achievement_event(test_student, 'time_based_submission', {'hour_msk': 6}, commit=True)
    assert res['unlocked'] is True
    assert res['achievement']['key'] == 'secret_early_bird'

    # 3. secret_recursion_depth
    res = process_achievement_event(test_student, 'python_error', {'error_type': 'RecursionError'}, commit=True)
    assert res['unlocked'] is True
    assert res['achievement']['key'] == 'secret_recursion_depth'

    # 4. secret_zero_division
    res = process_achievement_event(test_student, 'python_error', {'error_type': 'ZeroDivisionError'}, commit=True)
    assert res['unlocked'] is True
    assert res['achievement']['key'] == 'secret_zero_division'

    # 5. secret_ghost_friend
    res = process_achievement_event(test_student, 'secret_ghost_friend', {'clicks': 5}, commit=True)
    assert res['unlocked'] is True
    assert res['achievement']['key'] == 'secret_ghost_friend'

    # 6. secret_zen_python
    res = process_achievement_event(test_student, 'zen_python', commit=True)
    assert res['unlocked'] is True
    assert res['achievement']['key'] == 'secret_zen_python'

    # 7. secret_theme_toggle
    res = process_achievement_event(test_student, 'secret_theme_toggle', commit=True)
    assert res['unlocked'] is True
    assert res['achievement']['key'] == 'secret_theme_toggle'

    # 8. secret_syntax_recovery
    res = process_achievement_event(test_student, 'syntax_recovery', commit=True)
    assert res['unlocked'] is True
    assert res['achievement']['key'] == 'secret_syntax_recovery'

    # 9. secret_all_sections
    res = process_achievement_event(test_student, 'secret_all_sections', commit=True)
    assert res['unlocked'] is True
    assert res['achievement']['key'] == 'secret_all_sections'

    # 10. secret_marathon_hour
    res = process_achievement_event(test_student, 'secret_marathon_hour', commit=True)
    assert res['unlocked'] is True
    assert res['achievement']['key'] == 'secret_marathon_hour'


def test_milestones_and_catalog_generation(test_student):
    """Verify milestones (streaks, level, tasks, xp) and full catalog generation."""
    test_student.streak_days = 30
    test_student.streak_weeks = 4
    test_student.level = 5
    test_student.xp = 1600
    db.session.commit()

    check_and_grant_dynamic_achievements(test_student, commit=True)
    unlocked = get_student_unlocked_achievement_keys(test_student.student_id)

    assert 'streak_3' in unlocked
    assert 'streak_7' in unlocked
    assert 'streak_30' in unlocked
    assert 'weekly_streak_2' in unlocked
    assert 'weekly_streak_4' in unlocked
    assert 'lvl_5' in unlocked
    assert 'xp_1000' in unlocked

    catalog = build_student_achievement_catalog(test_student)
    assert len(catalog) == 58
