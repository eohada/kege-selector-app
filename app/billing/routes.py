from __future__ import annotations

import logging
from datetime import datetime, timedelta

from flask import render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from app.billing import billing_bp
from app.models import db, TariffPlan, UserSubscription, User
from app.auth.rbac_utils import has_permission
from core.audit_logger import audit_logger

logger = logging.getLogger(__name__)


def _require_admin():
    if has_permission(current_user, 'billing.manage'):
        return
    if not (getattr(current_user, 'is_creator', None) and current_user.is_creator()) and not (getattr(current_user, 'is_admin', None) and current_user.is_admin()):
        abort(403)


@billing_bp.route('/billing/plans')
@login_required
def billing_plans():
    _require_admin()
    plans = TariffPlan.query.order_by(TariffPlan.is_active.desc(), TariffPlan.updated_at.desc(), TariffPlan.plan_id.desc()).all()
    return render_template('billing_plans.html', plans=plans)


@billing_bp.route('/billing/plans/new', methods=['POST'])
@login_required
def billing_plan_create():
    _require_admin()
    title = (request.form.get('title') or '').strip()
    if not title:
        flash('Название тарифа обязательно.', 'danger')
        return redirect(url_for('billing.billing_plans'))

    plan = TariffPlan(
        title=title,
        description=(request.form.get('description') or '').strip() or None,
        price_rub=request.form.get('price_rub', type=int),
        period_days=request.form.get('period_days', type=int),
        is_active=True,
    )
    db.session.add(plan)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='billing_plan_create', entity='TariffPlan', error=str(e))
        flash('Не удалось создать тариф.', 'danger')
        return redirect(url_for('billing.billing_plans'))

    try:
        audit_logger.log(action='billing_plan_create', entity='TariffPlan', entity_id=plan.plan_id, status='success')
    except Exception:
        pass
    flash('Тариф создан.', 'success')
    return redirect(url_for('billing.billing_plans'))


@billing_bp.route('/billing/plans/<int:plan_id>/toggle', methods=['POST'])
@login_required
def billing_plan_toggle(plan_id: int):
    _require_admin()
    plan = TariffPlan.query.get_or_404(plan_id)
    plan.is_active = not bool(plan.is_active)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='billing_plan_toggle', entity='TariffPlan', entity_id=plan_id, error=str(e))
        flash('Не удалось изменить статус тарифа.', 'danger')
        return redirect(url_for('billing.billing_plans'))
    flash('Статус тарифа обновлён.', 'success')
    return redirect(url_for('billing.billing_plans'))


@billing_bp.route('/billing/subscriptions')
@login_required
def billing_subscriptions():
    _require_admin()
    subs = UserSubscription.query.options(db.joinedload(UserSubscription.user), db.joinedload(UserSubscription.plan)).order_by(UserSubscription.updated_at.desc(), UserSubscription.subscription_id.desc()).limit(300).all()
    plans = TariffPlan.query.filter_by(is_active=True).order_by(TariffPlan.title.asc()).all()
    users = User.query.order_by(User.id.desc()).limit(200).all()
    return render_template('billing_subscriptions.html', subs=subs, plans=plans, users=users)


@billing_bp.route('/billing/subscriptions/new', methods=['POST'])
@login_required
def billing_subscription_create():
    _require_admin()
    user_id = request.form.get('user_id', type=int)
    plan_id = request.form.get('plan_id', type=int)
    days = request.form.get('days', type=int)
    note = (request.form.get('note') or '').strip() or None

    if not user_id:
        flash('Выберите пользователя.', 'danger')
        return redirect(url_for('billing.billing_subscriptions'))

    sub = UserSubscription(
        user_id=user_id,
        plan_id=plan_id or None,
        status='active',
        started_at=datetime.utcnow(),
        ends_at=(datetime.utcnow() + timedelta(days=int(days or 30))),
        note=note,
    )
    db.session.add(sub)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='billing_subscription_create', entity='UserSubscription', error=str(e))
        flash('Не удалось создать подписку.', 'danger')
        return redirect(url_for('billing.billing_subscriptions'))

    try:
        audit_logger.log(action='billing_subscription_create', entity='UserSubscription', entity_id=sub.subscription_id, status='success', metadata={'user_id': user_id, 'plan_id': plan_id})
    except Exception:
        pass
    flash('Подписка создана.', 'success')
    return redirect(url_for('billing.billing_subscriptions'))


@billing_bp.route('/billing/subscriptions/<int:subscription_id>/cancel', methods=['POST'])
@login_required
def billing_subscription_cancel(subscription_id: int):
    _require_admin()
    sub = UserSubscription.query.get_or_404(subscription_id)
    sub.status = 'cancelled'
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='billing_subscription_cancel', entity='UserSubscription', entity_id=subscription_id, error=str(e))
        flash('Не удалось отменить подписку.', 'danger')
        return redirect(url_for('billing.billing_subscriptions'))
    flash('Подписка отменена.', 'success')
    return redirect(url_for('billing.billing_subscriptions'))

