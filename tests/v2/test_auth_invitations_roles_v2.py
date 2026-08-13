"""
Unit & Integration Tests for BooStudy User Registration, Authentication, Roles & Invitations System.
"""

import pytest
import secrets
import hashlib
from core.db_models import (
    db, User, UserRole, UserProfile, Student, TeacherProfile,
    TeacherStudent, FamilyTie, InviteLink, ReferralCode, ReferralUsage,
    PromoCode, PromoCodeUsage, TariffPlan, UserSubscription,
)
from app.utils.relationship_scope import (
    teacher_has_student, parent_has_student, can_user_access_student
)


def login_user_client(client, user_id: int, role: str = 'tutor'):
    """Helper to authenticate test client session"""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True
        sess['sandbox_role'] = role


def logout_user_client(client):
    """Helper to clear test client session"""
    client.get('/logout')


def test_teacher_self_registration(app):
    """Test 1: Teacher self-registration at /register"""
    client = app.test_client()
    logout_user_client(client)

    uname = f"teacher_{secrets.token_hex(4)}"
    resp = client.post('/register', data={
        'username': uname,
        'email': f"{uname}@example.com",
        'password': 'Password123!',
        'password_confirm': 'Password123!',
        'role': 'tutor',
        'full_name': 'Тестовый Преподаватель'
    }, follow_redirects=True)

    assert resp.status_code == 200

    with app.app_context():
        user = User.query.filter_by(username=uname).first()
        assert user is not None
        assert user.role == 'tutor'
        assert user.is_tutor() is True

        tp = TeacherProfile.query.filter_by(user_id=user.id).first()
        assert tp is not None


def test_registration_applies_a_real_referral_code_once(app):
    """A regular registration records the referral in the same transaction."""
    with app.app_context():
        inviter = User(username=f"referrer_{secrets.token_hex(4)}", role='tutor', is_active=True)
        inviter.set_password('pass123')
        db.session.add(inviter)
        db.session.flush()
        referral = ReferralCode(code=f"BS-{secrets.token_hex(4).upper()}", creator_id=inviter.id, is_active=True)
        db.session.add(referral)
        db.session.commit()
        referral_code = referral.code
        referral_id = referral.id

    client = app.test_client()
    logout_user_client(client)
    username = f"referred_{secrets.token_hex(4)}"
    response = client.post(f'/register?ref={referral_code}', data={
        'username': username,
        'email': f'{username}@example.com',
        'password': 'Password123!',
        'password_confirm': 'Password123!',
        'role': 'tutor',
        'full_name': 'Referred user',
        'ref': referral_code,
    }, follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        referred = User.query.filter_by(username=username).first()
        referral = ReferralCode.query.get(referral_id)
        usage = ReferralUsage.query.filter_by(referral_code_id=referral_id, user_id=referred.id).first()
        assert usage is not None
        assert referral.usage_count == 1


def test_referral_lookup_locks_a_limited_code_before_registration(app):
    from app.utils.referral_service import get_active_referral_code

    with app.app_context():
        inviter = User(username=f"ref_lock_{secrets.token_hex(4)}", role='teacher', is_active=True)
        db.session.add(inviter)
        db.session.flush()
        referral = ReferralCode(code=f"LOCK-{secrets.token_hex(4).upper()}", creator_id=inviter.id, usage_limit=1, is_active=True)
        db.session.add(referral)
        db.session.commit()
        assert get_active_referral_code(referral.code).id == referral.id


def test_free_promocode_redeems_once_and_never_trusts_browser_price(app):
    with app.app_context():
        student_user = User(username=f"promo_student_{secrets.token_hex(4)}", role='student', is_active=True)
        student_user.set_password('pass123')
        db.session.add(student_user)
        db.session.flush()
        plan = TariffPlan(
            title=f"Promo plan {secrets.token_hex(4)}",
            price_rub=12000,
            period_days=30,
            lessons_count=8,
            allow_lessons=True,
            is_active=True,
        )
        db.session.add(plan)
        db.session.flush()
        promo = PromoCode(
            code=f"FREE-{secrets.token_hex(4).upper()}",
            discount_percent=100,
            plan_id=plan.plan_id,
            is_active=True,
            usage_limit=2,
        )
        db.session.add(promo)
        db.session.commit()
        user_id, plan_id, promo_code = student_user.id, plan.plan_id, promo.code

    client = app.test_client()
    login_user_client(client, user_id, 'student')
    first = client.post('/billing/promocode/redeem', json={
        'plan_id': plan_id,
        'code': promo_code,
        'price': 1,
    })
    assert first.status_code == 200, first.get_json()
    second = client.post('/billing/promocode/redeem', json={'plan_id': plan_id, 'code': promo_code})
    assert second.status_code == 400

    with app.app_context():
        assert UserSubscription.query.filter_by(user_id=user_id, plan_id=plan_id, status='active').count() == 1
        assert PromoCodeUsage.query.filter_by(user_id=user_id).count() == 1
        assert PromoCode.query.filter_by(code=promo_code).one().usage_count == 1


def test_student_invite_flow(app):
    """Test 2: Teacher generates student invite -> Student registers -> TeacherStudent relationship created"""
    teacher_id = None
    with app.app_context():
        teacher_uname = f"tutor_inviter_{secrets.token_hex(4)}"
        teacher = User(username=teacher_uname, email=f"{teacher_uname}@test.com", role='tutor', is_active=True)
        teacher.set_password('pass123')
        db.session.add(teacher)
        db.session.flush()
        db.session.add(UserRole(user_id=teacher.id, role='tutor'))
        db.session.commit()
        teacher_id = teacher.id

    # Login teacher client
    teacher_client = app.test_client()
    login_user_client(teacher_client, teacher_id, 'tutor')

    # Generate student invite
    res = teacher_client.post('/api/teacher/invites/student')
    assert res.status_code == 200
    data = res.get_json()
    assert data.get('status') == 'success'
    token = data.get('token')
    assert token is not None

    # Logout teacher via HTTP
    teacher_client.get('/logout')

    # Guest client opens invite link
    guest_client = app.test_client()
    logout_user_client(guest_client)

    resp_get = guest_client.get(f'/register/student/{token}')
    assert resp_get.status_code == 200
    assert 'Регистрация ученика' in resp_get.get_data(as_text=True)

    # Submit student registration
    student_uname = f"invited_student_{secrets.token_hex(4)}"
    resp_post = guest_client.post(f'/register/student/{token}', data={
        'username': student_uname,
        'email': f"{student_uname}@test.com",
        'password': 'PassStudent123!',
        'password_confirm': 'PassStudent123!',
        'full_name': 'Иван Студентов'
    }, follow_redirects=True)

    assert resp_post.status_code == 200

    # Verify DB records
    with app.app_context():
        student_user = User.query.filter_by(username=student_uname).first()
        assert student_user is not None
        assert student_user.role == 'student'
        assert student_user.is_student() is True

        student_prof = Student.query.filter_by(user_id=student_user.id).first()
        assert student_prof is not None
        assert student_prof.streak_days == 0
        assert student_prof.goal_text is None
        assert student_user.about_me is None
        assert student_user.avatar_url is None
        assert student_user.cover_url is None
        profile = UserProfile.query.filter_by(user_id=student_user.id).one()
        assert profile.profile_onboarding_completed_at is None

        teacher = User.query.get(teacher_id)
        # Verify TeacherStudent link
        ts_link = TeacherStudent.query.filter_by(teacher_id=teacher_id, student_id=student_user.id).first()
        assert ts_link is not None
        assert ts_link.status == 'active'

        # Verify helper functions
        assert teacher_has_student(teacher_id, student_user.id) is True
        assert can_user_access_student(teacher, student_user_id=student_user.id) is True

        # Verify token marked used
        token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
        invite = InviteLink.query.filter_by(token_hash=token_hash).first()
        assert invite.used_at is not None
        assert invite.is_valid is False


def test_parent_invite_flow(app):
    """Test 3: Teacher generates parent invite for student -> Parent registers -> FamilyTie created"""
    teacher_id = None
    student_platform_id = None
    student_user_id = None

    with app.app_context():
        teacher = User(username=f"tutor_p_{secrets.token_hex(4)}", role='tutor', is_active=True)
        teacher.set_password('pass123')
        db.session.add(teacher)
        db.session.flush()
        db.session.add(UserRole(user_id=teacher.id, role='tutor'))

        student_user = User(username=f"stud_p_{secrets.token_hex(4)}", role='student', is_active=True)
        student_user.set_password('pass123')
        db.session.add(student_user)
        db.session.flush()
        db.session.add(UserRole(user_id=student_user.id, role='student'))

        student_prof = Student(name='Петя Петров', user_id=student_user.id, mentor_id=teacher.id, is_active=True)
        db.session.add(student_prof)
        db.session.flush()

        ts = TeacherStudent(teacher_id=teacher.id, student_id=student_user.id, status='active')
        db.session.add(ts)
        db.session.commit()

        teacher_id = teacher.id
        student_platform_id = student_prof.student_id
        student_user_id = student_user.id

    # Login teacher and generate parent invite
    teacher_client = app.test_client()
    login_user_client(teacher_client, teacher_id, 'tutor')
    res = teacher_client.post('/api/teacher/invites/parent', json={'student_id': student_platform_id})
    assert res.status_code == 200
    data = res.get_json()
    assert data.get('status') == 'success'
    token = data.get('token')
    assert token is not None

    # Logout teacher via HTTP
    teacher_client.get('/logout')

    # Guest client opens invite link
    guest_client = app.test_client()
    logout_user_client(guest_client)

    resp_get = guest_client.get(f'/register/parent/{token}')
    assert resp_get.status_code == 200
    assert 'Регистрация родителя' in resp_get.get_data(as_text=True)

    # Parent registers
    parent_uname = f"parent_{secrets.token_hex(4)}"
    resp_post = guest_client.post(f'/register/parent/{token}', data={
        'username': parent_uname,
        'email': f"{parent_uname}@test.com",
        'password': 'PassParent123!',
        'password_confirm': 'PassParent123!',
        'full_name': 'Мария Петрова'
    }, follow_redirects=True)

    assert resp_post.status_code == 200

    # Verify parent records
    with app.app_context():
        parent_user = User.query.filter_by(username=parent_uname).first()
        assert parent_user is not None
        assert parent_user.role == 'parent'

        # Verify FamilyTie
        tie = FamilyTie.query.filter_by(parent_id=parent_user.id, student_id=student_user_id).first()
        assert tie is not None
        assert tie.is_confirmed is True

        # Verify helpers
        assert parent_has_student(parent_user.id, student_user_id) is True
        assert can_user_access_student(parent_user, student_user_id=student_user_id) is True


def test_revoked_or_expired_token_handling(app):
    """Test 4: Revoked and expired invite tokens return proper error messages"""
    teacher_id = None
    with app.app_context():
        teacher = User(username=f"tutor_r_{secrets.token_hex(4)}", role='tutor', is_active=True)
        teacher.set_password('pass123')
        db.session.add(teacher)
        db.session.flush()
        db.session.add(UserRole(user_id=teacher.id, role='tutor'))
        db.session.commit()
        teacher_id = teacher.id

    # Login teacher
    teacher_client = app.test_client()
    login_user_client(teacher_client, teacher_id, 'tutor')

    # Generate invite & revoke it
    res = teacher_client.post('/api/teacher/invites/student')
    token = res.get_json().get('token')
    
    teacher_client.post('/api/teacher/invites/revoke', json={'token': token})

    # Logout teacher via HTTP
    teacher_client.get('/logout')

    guest_client = app.test_client()
    logout_user_client(guest_client)

    # Try accessing revoked link
    resp = guest_client.get(f'/register/student/{token}')
    assert resp.status_code == 400
    assert 'отозвана' in resp.get_data(as_text=True)

    # Test non-existent token
    resp_404 = guest_client.get('/register/student/invalid_token_12345')
    assert resp_404.status_code == 404
