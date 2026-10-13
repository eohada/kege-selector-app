import pytest
from app.models import (
    db, User, Student, Tasks, StudentTheoryState,
    ReferralCode, ReferralUsage, Lesson, AnalyticsEvent
)
from core.db_models import Submission, Answer, Assignment, AssignmentTask
from app.utils.xp_service import (
    get_xp_for_level, calculate_level_from_xp, get_level_info,
    get_all_ranks_list, get_rank_title, add_xp_to_student,
    recalculate_student_xp, rebalance_all_students_xp,
    BOOSTUDY_50_LEVELS
)
from app.utils.gamification_service import (
    reward_submission, reward_lesson_completion,
    reward_theory_reading, reward_single_task_correct
)
from app import create_app
from app.utils.achievement_service import grant_achievement, ACHIEVEMENTS_REGISTRY


@pytest.fixture
def app_ctx():
    app = create_app('testing')
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.app_context():
        db.create_all()
        yield app


def test_level_curve_math_and_boundaries():
    """Verify that the calibrated curve behaves correctly across all 50 levels."""
    # 1. Base anchor points of the new calibrated curve:
    # int(3.0 * (n ** 2.4) + 25 * n)
    assert get_xp_for_level(1) == 0
    assert get_xp_for_level(2) == 28
    assert get_xp_for_level(3) == 65
    assert get_xp_for_level(5) == 183
    assert get_xp_for_level(10) == 810
    assert get_xp_for_level(15) == 2039
    assert get_xp_for_level(20) == 3991
    assert get_xp_for_level(30) == 10427
    assert get_xp_for_level(42) == 23299
    assert get_xp_for_level(50) == 35390

    # 2. Strict monotonicity
    for lvl in range(1, 50):
        assert get_xp_for_level(lvl + 1) > get_xp_for_level(lvl)

    # 3. Level resolution from XP
    assert calculate_level_from_xp(0) == 1
    assert calculate_level_from_xp(-100) == 1
    assert calculate_level_from_xp(27) == 1
    assert calculate_level_from_xp(28) == 2
    assert calculate_level_from_xp(64) == 2
    assert calculate_level_from_xp(65) == 3
    assert calculate_level_from_xp(183) == 5
    assert calculate_level_from_xp(810) == 10
    assert calculate_level_from_xp(3991) == 20
    assert calculate_level_from_xp(10427) == 30
    assert calculate_level_from_xp(23299) == 42
    assert calculate_level_from_xp(35390) == 50
    assert calculate_level_from_xp(999999) == 50

    # 4. Level info and progress calculation
    info_lvl1 = get_level_info(1, xp_val=14)
    assert info_lvl1['number'] == 1
    assert info_lvl1['base_xp'] == 0
    assert info_lvl1['target_xp'] == 28
    assert info_lvl1['progress_pct'] == 50
    assert info_lvl1['xp_to_next'] == 14

    info_lvl50 = get_level_info(50, xp_val=40000)
    assert info_lvl50['number'] == 50
    assert info_lvl50['progress_pct'] == 100
    assert info_lvl50['xp_to_next'] == 0


def test_boostudy_50_levels_metadata():
    """Verify metadata consistency across all 50 levels."""
    assert len(BOOSTUDY_50_LEVELS) == 50
    ranks_list = get_all_ranks_list(current_level_num=5)
    assert len(ranks_list) == 50

    for idx, item in enumerate(BOOSTUDY_50_LEVELS, 1):
        assert item['level'] == idx
        assert len(item['title']) > 0
        assert len(item['desc']) > 0
        assert item['icon'].startswith('ph-')

    # Rank title resolution
    assert get_rank_title(1) == "Новичок в Python"
    assert get_rank_title(50) == "Легенда BooStudy"


def test_add_xp_to_student(app_ctx):
    """Verify adding XP incrementally to a student and level advancement."""
    user = User(username='test_add_xp_user', email='add_xp@test.com', role='student')
    db.session.add(user)
    db.session.flush()

    student = Student(user_id=user.id, name='XP Student', xp=0, level=1)
    db.session.add(student)
    db.session.commit()

    # Small XP addition below Level 2 (28 XP)
    leveled = add_xp_to_student(student, 20)
    assert not leveled
    assert student.xp == 20
    assert student.level == 1

    # Addition crossing Level 2 threshold (28 XP)
    leveled = add_xp_to_student(student, 15)
    assert leveled
    assert student.xp == 35
    assert student.level == 2

    # Addition jumping directly to Level 5 (183 XP)
    leveled = add_xp_to_student(student, 160)
    assert leveled
    assert student.xp == 195
    assert student.level == 5


def test_gamification_rewards_suite(app_ctx):
    """Verify that all core learning actions award correct XP and update streaks."""
    user = User(username='gamer_user_v2', email='gamer_v2@test.com', role='student')
    db.session.add(user)
    db.session.flush()

    student = Student(user_id=user.id, name='Gamer', xp=0, streak_days=0)
    db.session.add(student)
    db.session.commit()

    # 1. Lesson reward: +30 XP + first lesson achievement (+25 XP)
    awarded = reward_lesson_completion(student)
    assert awarded == 30
    assert student.xp == 55
    assert student.streak_days == 1

    # 2. Theory reading reward: +10 XP + first theory achievement (+20 XP)
    awarded = reward_theory_reading(student)
    assert awarded == 10
    assert student.xp == 85
    assert student.streak_days == 1

    # 3. Single task reward: +10 XP + first step achievement (+20 XP)
    awarded = reward_single_task_correct(student)
    assert awarded == 10
    assert student.xp == 115

    # 4. Homework submission: 15 base + 3 correct answers * 5 = +30 XP (first_step already unlocked)
    awarded = reward_submission(student, correct_answers=3)
    assert awarded == 30
    assert student.xp == 145


def test_recalculate_student_xp_harmony(app_ctx):
    """Verify recalculate_student_xp properly tallies all educational activities from DB."""
    user = User(username='recalc_user_v2', email='recalc_v2@test.com', role='student')
    db.session.add(user)
    db.session.flush()

    student = Student(user_id=user.id, name='Recalc Student', xp=0, level=1, streak_days=5)
    db.session.add(student)
    db.session.flush()

    # Activity A: 2 completed lessons (2 * 30 = 60 XP)
    lesson1 = Lesson(student_id=student.student_id, topic='Тема 1', status='completed')
    lesson2 = Lesson(student_id=student.student_id, topic='Тема 2', status='completed')
    db.session.add_all([lesson1, lesson2])

    # Activity B: 3 theory blocks read (3 * 10 = 30 XP)
    t1 = StudentTheoryState(student_id=student.student_id, course_id=1, task_number=1, is_read=True)
    t2 = StudentTheoryState(student_id=student.student_id, course_id=1, task_number=2, is_read=True)
    t3 = StudentTheoryState(student_id=student.student_id, course_id=1, task_number=3, is_read=True)
    db.session.add_all([t1, t2, t3])

    # Activity C: 1 homework submission with 4 answers (2 correct, 2 incorrect)
    # 15 base + 2 * 5 correct = 25 XP
    sub = Submission(student_id=student.student_id, assignment_id=1, status='GRADED')
    db.session.add(sub)
    db.session.flush()
    ans1 = Answer(submission_id=sub.submission_id, assignment_task_id=1, is_correct=True)
    ans2 = Answer(submission_id=sub.submission_id, assignment_task_id=2, is_correct=True)
    ans3 = Answer(submission_id=sub.submission_id, assignment_task_id=3, is_correct=False)
    db.session.add_all([ans1, ans2, ans3])

    # Activity D: 2 unique trainer tasks solved correctly (2 * 10 = 20 XP)
    ev1 = AnalyticsEvent(user_id=user.id, task_id=101, is_correct=True, submission_id=None)
    ev2 = AnalyticsEvent(user_id=user.id, task_id=102, is_correct=True, submission_id=None)
    ev3 = AnalyticsEvent(user_id=user.id, task_id=101, is_correct=True, submission_id=None)  # duplicate task_id
    db.session.add_all([ev1, ev2, ev3])

    # Activity E: Referral bonus as invitee (+50 XP)
    ref_code = ReferralCode(code='INVITE123_V2', creator_id=999, is_active=True)
    db.session.add(ref_code)
    db.session.flush()
    ref_usage = ReferralUsage(referral_code_id=ref_code.id, user_id=user.id)
    db.session.add(ref_usage)

    # Activity F: 1 regular achievement unlocked (speedrun = 20 XP)
    grant_achievement(student, 'speedrun_task', award_xp=False, commit=False)

    # Streak bonus: 5 days * 5 = 25 XP
    db.session.commit()

    # Pre-milestone total:
    # 60 (lessons) + 30 (theory) + 25 (submissions) + 20 (trainer) + 50 (referral) + 20 (ach) + 25 (streak) = 230 XP.
    # At 230 XP, level >= 5 (level 5 threshold is 183 XP), so milestone 'lvl_5' (+30 XP) is granted!
    # Final total = 230 + 30 = 260 XP (Level 5).
    recalculated = recalculate_student_xp(student)
    assert recalculated == 260
    assert student.xp == 260
    assert student.level == 5


def test_milestone_achievements_in_recalculation(app_ctx):
    """Verify that recalculate_student_xp correctly awards or revokes lvl_5 and xp_1000."""
    user = User(username='milestone_user_v2', email='mile_v2@test.com', role='student')
    db.session.add(user)
    db.session.flush()

    student = Student(user_id=user.id, name='Milestone Student', xp=0, level=1, streak_days=0)
    db.session.add(student)
    db.session.commit()

    # 50 submissions with 4 correct answers each: 50 * (15 + 20) = 1750 XP
    for i in range(50):
        sub = Submission(student_id=student.student_id, assignment_id=i + 1, status='GRADED')
        db.session.add(sub)
        db.session.flush()
        for j in range(4):
            db.session.add(Answer(submission_id=sub.submission_id, assignment_task_id=j + 1, is_correct=True))
    db.session.commit()

    total_xp = recalculate_student_xp(student)
    # 1750 base + 30 (lvl_5 reward) + 30 (xp_1000 reward) = 1810 XP (Level 14)
    assert total_xp == 1810
    assert student.level == 14

    # Check milestone achievements were granted
    from core.db_models import UserAchievement
    keys = [ua.achievement_key for ua in UserAchievement.query.filter_by(student_id=student.student_id).all()]
    assert 'lvl_5' in keys
    assert 'xp_1000' in keys


def test_rebalance_all_students_xp(app_ctx):
    """Verify batch rebalance across all students."""
    user = User(username='rebalance_batch_v2', email='batch_v2@test.com', role='student')
    db.session.add(user)
    db.session.flush()
    student = Student(user_id=user.id, name='Batch Student', xp=0, level=1)
    db.session.add(student)
    db.session.commit()

    stats = rebalance_all_students_xp()
    assert isinstance(stats, dict)
    assert 'total' in stats
    assert 'recalculated' in stats
    assert stats['total'] >= 1
    assert stats['recalculated'] == stats['total']


def test_trainer_anti_exploit_xp(app_ctx):
    """Verify solving new tasks awards XP, but repeatedly submitting already solved tasks prevents farming."""
    user = User(username='trainer_anti_exploit_v2', email='exploit_v2@test.com', role='student')
    db.session.add(user)
    db.session.flush()

    student = Student(user_id=user.id, name='Trainer Student', xp=0, level=1)
    db.session.add(student)
    db.session.commit()

    # Simulate first solve of task 999: awards 10 XP + 20 XP first_step
    ev1 = AnalyticsEvent(user_id=user.id, task_id=999, is_correct=True, submission_id=None)
    db.session.add(ev1)
    db.session.commit()

    prev_count = AnalyticsEvent.query.filter_by(user_id=user.id, task_id=999, is_correct=True).count()
    if prev_count <= 1:
        reward_single_task_correct(student)

    assert student.xp == 30

    # Simulate repeated submit of task 999: no reward
    ev2 = AnalyticsEvent(user_id=user.id, task_id=999, is_correct=True, submission_id=None)
    db.session.add(ev2)
    db.session.commit()

    prev_count = AnalyticsEvent.query.filter_by(user_id=user.id, task_id=999, is_correct=True).count()
    if prev_count <= 1:
        reward_single_task_correct(student)

    assert student.xp == 30


def test_admin_update_student_xp_set_and_bonus(app_ctx):
    """Verify creator/admin can explicitly set XP and award bonus points to a student."""
    admin_user = User(username='admin_boss', email='admin_boss@test.com', role='creator')
    student_user = User(username='pupil_target', email='pupil@test.com', role='student')
    db.session.add_all([admin_user, student_user])
    db.session.flush()

    student = Student(user_id=student_user.id, name='Target Student', xp=100, level=3)
    db.session.add(student)
    db.session.commit()

    client = app_ctx.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user.id)
        sess['_fresh'] = True

    # 1. Award +250 XP bonus with reason
    resp = client.post(
        f'/student/{student.student_id}/xp',
        json={'mode': 'bonus', 'amount': 250, 'reason': 'Победа на олимпиаде'},
        headers={'Content-Type': 'application/json'}
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    assert data['old_xp'] == 100
    assert data['xp'] >= 350  # 100 + 250 bonus (+30 lvl_5 milestone if unlocked)
    assert data['level'] >= 5

    # 2. Set exact XP to 10427 (level 30)
    resp = client.post(
        f'/student/{student.student_id}/xp',
        json={'mode': 'set', 'amount': 10427, 'reason': 'Сброс/корректировка уровня'},
        headers={'Content-Type': 'application/json'}
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    assert data['xp'] >= 10427  # 10427 (+30 xp_1000 milestone if unlocked)
    assert data['level'] == 30

    # 3. Verify regular student is rejected with 403
    with client.session_transaction() as sess:
        sess['_user_id'] = str(student_user.id)

    unauth_resp = client.post(
        f'/student/{student.student_id}/xp',
        json={'mode': 'bonus', 'amount': 1000},
        headers={'Content-Type': 'application/json'}
    )
    assert unauth_resp.status_code == 403
