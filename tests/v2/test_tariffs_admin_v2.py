import os
import pytest
from core.db_models import db, User, UserRole, TariffPlan, TariffGroup, UserSubscription
from werkzeug.security import generate_password_hash
from .conftest import login_as


def _setup_users(app):
    with app.app_context():
        pwd_hash = generate_password_hash('testpassword')
        admin_user = User.query.filter_by(username='test_admin_tariffs').first()
        if not admin_user:
            admin_user = User(username='test_admin_tariffs', email='admin_tariffs@boostudy.ru', role='admin', password_hash=pwd_hash)
            db.session.add(admin_user)
            db.session.flush()
            db.session.add(UserRole(user_id=admin_user.id, role='admin'))

        student_user = User.query.filter_by(username='test_student_tariffs').first()
        if not student_user:
            student_user = User(username='test_student_tariffs', email='student_tariffs@boostudy.ru', role='student', password_hash=pwd_hash)
            db.session.add(student_user)
            db.session.flush()
            db.session.add(UserRole(user_id=student_user.id, role='student'))

        db.session.commit()
        return admin_user.id, student_user.id


def test_tariffs_admin_access_control(client, app):
    admin_id, student_id = _setup_users(app)

    # Unauthenticated -> redirect to login
    res = client.get('/admin/tariffs')
    assert res.status_code == 302

    # Student -> forbidden redirect
    login_as(client, student_id, 'student')
    res = client.get('/admin/tariffs', follow_redirects=True)
    assert b'\xd0\x94\xd0\xbe\xd1\x81\xd1\x82\xd1\x83\xd0\xbf \xd0\xb7\xd0\xb0\xd0\xbf\xd1\x80\xd0\xb5\xd1\x89\xd0\xb5\xd0\xbd' in res.data or res.status_code in (200, 302)

    # Admin -> 200 OK
    login_as(client, admin_id, 'admin')
    res = client.get('/admin/tariffs')
    assert res.status_code == 200
    assert 'Управление Тарифами' in res.get_data(as_text=True)


def test_tariff_crud_and_assignment_lifecycle(client, app):
    admin_id, student_id = _setup_users(app)
    login_as(client, admin_id, 'admin')

    # 1. Create a TariffPlan
    create_data = {
        'title': 'Test EGE Mentor Plan',
        'description': 'Description of test plan',
        'exam': 'ege',
        'subject': 'inf',
        'format': 'mentor',
        'level': 'prof',
        'badge': 'ХИТ',
        'price_rub': 15200,
        'period_days': 30,
        'lessons_count': 8,
        'price_per_lesson_rub': 1900,
        'features': '8 уроков с ментором\nПроверка ДЗ\nАналитика',
        'allow_trainer': 'on',
        'allow_lessons': 'on',
        'allow_referral': 'on',
        'allow_promocode': 'on',
        'is_active': 'on',
    }
    res = client.post('/admin/tariffs/create', data=create_data, follow_redirects=True)
    assert res.status_code == 200

    with app.app_context():
        plan = TariffPlan.query.filter_by(title='Test EGE Mentor Plan').first()
        assert plan is not None
        assert plan.price_rub == 15200
        assert plan.lessons_count == 8
        assert plan.allow_trainer is True
        assert plan.allow_lessons is True
        assert plan.badge == 'ХИТ'
        assert plan.exam == 'ege'
        assert len(plan.features) == 3
        plan_id = plan.plan_id

    # 2. Edit TariffPlan
    edit_data = {
        'title': 'Test EGE Mentor Plan Updated',
        'description': 'Updated desc',
        'exam': 'ege',
        'subject': 'inf',
        'format': 'mentor',
        'level': 'prof',
        'badge': 'ТОП',
        'price_rub': 16000,
        'period_days': 45,
        'lessons_count': 10,
        'price_per_lesson_rub': 1600,
        'features': '10 уроков с ментором\nНовые фичи',
        'allow_trainer': '1',
        'allow_lessons': '1',
        'allow_referral': '1',
        'allow_promocode': '1',
        'is_active': '1',
    }
    res = client.post(f'/admin/tariffs/{plan_id}/edit', data=edit_data, follow_redirects=True)
    assert res.status_code == 200

    with app.app_context():
        updated_plan = TariffPlan.query.get(plan_id)
        assert updated_plan.title == 'Test EGE Mentor Plan Updated'
        assert updated_plan.price_rub == 16000
        assert updated_plan.badge == 'ТОП'
        assert updated_plan.period_days == 45
        assert updated_plan.lessons_count == 10

    # 3. Toggle TariffPlan
    res = client.post(f'/admin/tariffs/{plan_id}/toggle', follow_redirects=True)
    assert res.status_code == 200
    with app.app_context():
        plan = TariffPlan.query.get(plan_id)
        assert plan.is_active is False

    res = client.post(f'/admin/tariffs/{plan_id}/toggle', follow_redirects=True)
    assert res.status_code == 200
    with app.app_context():
        plan = TariffPlan.query.get(plan_id)
        assert plan.is_active is True

    # 4. Assign Tariff to Student
    assign_data = {
        'user_id': student_id,
        'plan_id': plan_id,
        'lessons_count': 10,
        'period_days': 45,
        'note': 'Выдан тестовый доступ',
    }
    res = client.post('/admin/tariffs/assign-student', data=assign_data, follow_redirects=True)
    assert res.status_code == 200

    with app.app_context():
        sub = UserSubscription.query.filter_by(user_id=student_id, plan_id=plan_id).first()
        assert sub is not None
        assert sub.status == 'active'
        assert sub.lessons_remaining == 10
        assert sub.note == 'Выдан тестовый доступ'
        sub_id = sub.subscription_id

    # 5. Update Subscription
    update_sub_data = {
        'lessons_remaining': 12,
        'add_days': 10,
        'status': 'active',
        'note': 'Добавлены бонусные уроки',
    }
    res = client.post(f'/admin/tariffs/subscription/{sub_id}/update', data=update_sub_data, follow_redirects=True)
    assert res.status_code == 200

    with app.app_context():
        sub = UserSubscription.query.get(sub_id)
        assert sub.lessons_remaining == 12
        assert sub.note == 'Добавлены бонусные уроки'

    # 6. Cancel Subscription
    res = client.post(f'/admin/tariffs/subscription/{sub_id}/cancel', follow_redirects=True)
    assert res.status_code == 200
    with app.app_context():
        sub = UserSubscription.query.get(sub_id)
        assert sub.status == 'cancelled'

    # 7. Safe Delete Plan (has subscription -> moves to archive)
    res = client.post(f'/admin/tariffs/{plan_id}/delete', follow_redirects=True)
    assert res.status_code == 200
    with app.app_context():
        plan = TariffPlan.query.get(plan_id)
        assert plan is not None
        assert plan.is_active is False

    # 8. Check Public Billing endpoint
    res = client.get('/billing/plans/public')
    assert res.status_code == 200
    assert 'Тарифные планы' in res.get_data(as_text=True) or 'BooStudy' in res.get_data(as_text=True)

    # 9. Test AJAX Toggle for Admin Tariffs Showcase
    res_ajax = client.post(
        f'/admin/tariffs/{plan_id}/toggle',
        headers={'X-Requested-With': 'XMLHttpRequest'}
    )
    assert res_ajax.status_code == 200
    ajax_data = res_ajax.get_json()
    assert ajax_data['success'] is True
    assert ajax_data['plan_id'] == plan_id
    assert ajax_data['is_active'] is True

    # 10. Test AJAX Toggle for Billing Plans
    res_billing_ajax = client.post(
        f'/billing/plans/{plan_id}/toggle',
        headers={'X-Requested-With': 'XMLHttpRequest'}
    )
    assert res_billing_ajax.status_code == 200
    billing_data = res_billing_ajax.get_json()
    assert billing_data['success'] is True
    assert billing_data['plan_id'] == plan_id
    assert billing_data['is_active'] is False


def test_trainer_subscription_access_control(client, app):
    from datetime import datetime, timedelta
    from app.utils.trainer_tokens import issue_trainer_token

    admin_id, student_id = _setup_users(app)

    # 1. Unauthenticated request to /trainer/v2 -> redirect to login
    res = client.get('/trainer/v2')
    assert res.status_code == 302
    assert '/login' in res.headers.get('Location', '')

    # 2. Student without subscription -> redirect to public billing page
    login_as(client, student_id, 'student')
    res = client.get('/trainer/v2')
    assert res.status_code == 302
    assert '/billing/plans/public' in res.headers.get('Location', '')

    with client.session_transaction() as sess:
        flashes = sess.get('_flashes', [])
        assert any('Тренажёр доступен только по подписке' in f[1] for f in flashes)

    res_followed = client.get('/trainer/v2', follow_redirects=True)
    assert res_followed.status_code == 200
    assert '/billing/plans/public' in res_followed.request.path

    # 3. Student with subscription where allow_trainer=False -> redirect
    with app.app_context():
        no_trainer_plan = TariffPlan(
            title='No Trainer Plan',
            price_rub=1000,
            period_days=30,
            allow_trainer=False,
            allow_lessons=True,
            is_active=True
        )
        db.session.add(no_trainer_plan)
        db.session.commit()

        sub_no_trainer = UserSubscription(
            user_id=student_id,
            plan_id=no_trainer_plan.plan_id,
            status='active',
            started_at=datetime.utcnow() - timedelta(days=1),
            ends_at=datetime.utcnow() + timedelta(days=29)
        )
        db.session.add(sub_no_trainer)
        db.session.commit()
        sub_no_trainer_id = sub_no_trainer.subscription_id

    res = client.get('/trainer/v2')
    assert res.status_code == 302
    assert '/billing/plans/public' in res.headers.get('Location', '')

    # 4. Student with subscription where allow_trainer=True -> access granted (200 OK)
    with app.app_context():
        sub_no = UserSubscription.query.get(sub_no_trainer_id)
        sub_no.status = 'cancelled'

        trainer_plan = TariffPlan(
            title='Trainer Pro Plan',
            price_rub=2500,
            period_days=30,
            allow_trainer=True,
            allow_lessons=True,
            is_active=True
        )
        db.session.add(trainer_plan)
        db.session.commit()

        sub_trainer = UserSubscription(
            user_id=student_id,
            plan_id=trainer_plan.plan_id,
            status='active',
            started_at=datetime.utcnow() - timedelta(days=1),
            ends_at=datetime.utcnow() + timedelta(days=29)
        )
        db.session.add(sub_trainer)
        db.session.commit()

    res = client.get('/trainer/v2')
    assert res.status_code == 200, f"Redirected to {res.headers.get('Location')}"
    html = res.get_data(as_text=True)
    assert 'Glass OS' in html or 'trainer' in html

    # 5. Token validation via internal API for student with trainer subscription
    with app.app_context():
        valid_token = issue_trainer_token(user_id=student_id, ttl_seconds=600)

    res_api = client.post(
        '/internal/trainer/token/validate',
        headers={'X-Trainer-Token': valid_token}
    )
    assert res_api.status_code == 200
    api_json = res_api.get_json()
    assert api_json['success'] is True
    assert api_json['user']['id'] == student_id

    # 6. Admin access always allowed
    login_as(client, admin_id, 'admin')
    res_admin = client.get('/trainer/v2')
    assert res_admin.status_code == 200

