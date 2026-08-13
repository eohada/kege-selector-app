"""
Automated Pytest Suite: Release Readiness Verification
Verifies Gamification (XP, Streak, Achievements), Referrals, Promo Codes, and Core User Workflows.
"""

import pytest
from datetime import datetime, timedelta
from app.models import db, User, Student, PromoCode, PromoCodeUsage, TariffPlan, UserSubscription
from core.db_models import ReferralCode, ReferralUsage
from app.utils.gamification_service import (
    reward_submission,
    reward_lesson_completion,
    reward_theory_reading,
    reward_single_task_correct,
)
from app.utils.streak_service import update_student_streak
from app.utils.xp_service import calculate_level_from_xp
from app.utils.referral_service import (
    get_or_create_personal_referral_code,
    apply_referral_code,
    get_active_referral_code,
)
from app.billing.promo_service import (
    get_eligible_promo_code,
    get_final_price,
    redeem_free_promo,
    PromoCodeError,
)


def test_gamification_xp_streak_and_levels(app):
    """Test XP rewards, level scaling, and daily streak calculation."""
    user = User(username='test_gamer', role='student', email='gamer@example.com')
    db.session.add(user)
    db.session.flush()

    student = Student(user_id=user.id, name='Test Gamer', xp=0, streak_days=0)
    db.session.add(student)
    db.session.commit()

    # 1. Lesson completion (+30 XP + streak)
    awarded_lesson = reward_lesson_completion(student)
    assert awarded_lesson == 30
    assert student.xp == 30
    assert student.streak_days == 1

    # 2. Theory reading (+10 XP)
    awarded_theory = reward_theory_reading(student)
    assert awarded_theory == 10
    assert student.xp == 40

    # 3. Single task solution (+10 XP)
    awarded_task = reward_single_task_correct(student)
    assert awarded_task == 10
    assert student.xp == 50

    # 4. Level calculation
    level = calculate_level_from_xp(student.xp)
    assert level >= 1


def test_referral_code_generation_and_rewards(app):
    """Test referral code generation and dual XP reward on application."""
    referrer = User(username='referrer_user', role='student', email='referrer@example.com')
    invitee = User(username='invitee_user', role='student', email='invitee@example.com')
    db.session.add_all([referrer, invitee])
    db.session.flush()

    referrer_student = Student(user_id=referrer.id, name='Referrer', xp=0)
    invitee_student = Student(user_id=invitee.id, name='Invitee', xp=0)
    db.session.add_all([referrer_student, invitee_student])
    db.session.commit()

    # 1. Generate referral code for referrer
    ref_obj = get_or_create_personal_referral_code(referrer)
    assert ref_obj is not None
    assert ref_obj.code.startswith('BS-')
    assert ref_obj.creator_id == referrer.id

    # 2. Lookup active code
    fetched_code = get_active_referral_code(ref_obj.code)
    assert fetched_code.id == ref_obj.id

    # 3. Apply referral code to invitee
    success = apply_referral_code(invitee, ref_obj)
    assert success is True
    db.session.commit()

    # 4. Verify dual XP rewards (+100 to referrer, +50 to invitee)
    assert referrer_student.xp == 100
    assert invitee_student.xp == 50
    assert ref_obj.usage_count == 1


def test_promo_code_validation_discounts_and_redemption(app):
    """Test promo code applicability, discounts, free redemption, and usage limits."""
    user = User(username='promo_user', role='student', email='promo@example.com')
    db.session.add(user)
    db.session.flush()

    plan = TariffPlan(
        title='Месячный Интенсив',
        price_rub=1000,
        period_days=30,
        lessons_count=8,
        is_active=True,
    )
    db.session.add(plan)
    db.session.flush()

    # 1. Create a 50% discount promo code
    promo_50 = PromoCode(
        code='HALF50',
        discount_percent=50,
        is_active=True,
        usage_limit=5,
        created_at=datetime.utcnow(),
    )
    db.session.add(promo_50)
    db.session.commit()

    price_50 = get_final_price(plan, promo_50)
    assert price_50 == 500

    # 2. Create a 100% free promo code
    promo_free = PromoCode(
        code='FREE100',
        discount_percent=100,
        is_active=True,
        usage_limit=1,
        bonus_lessons=2,
        bonus_days=5,
        created_at=datetime.utcnow(),
    )
    db.session.add(promo_free)
    db.session.commit()

    free_price = get_final_price(plan, promo_free)
    assert free_price == 0

    # 3. Redeem free promo code
    sub = redeem_free_promo('FREE100', user.id, plan.plan_id)
    db.session.commit()

    assert sub.status == 'active'
    assert sub.lessons_remaining == 10  # 8 + 2 bonus
    assert (sub.ends_at - sub.started_at).days >= 34  # 30 + 5 bonus - 1 day margin
    assert promo_free.usage_count == 1

    # 4. Attempt second redemption with exhausted limit
    with pytest.raises(PromoCodeError):
        redeem_free_promo('FREE100', user.id, plan.plan_id)
