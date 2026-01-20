from __future__ import annotations

import logging
from datetime import datetime, timedelta

from flask import render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from app.billing import billing_bp
from app.models import db, TariffGroup, TariffPlan, UserSubscription, User
from app.auth.rbac_utils import has_permission
from core.audit_logger import audit_logger

logger = logging.getLogger(__name__)


def _require_admin():
    if not has_permission(current_user, 'billing.manage'):
        abort(403)


@billing_bp.route('/billing/plans')
@login_required
def billing_plans():
    _require_admin()
    groups = TariffGroup.query.filter_by(is_active=True).order_by(TariffGroup.order_index.asc(), TariffGroup.group_id.asc()).all()
    plans = TariffPlan.query.order_by(
        TariffPlan.is_active.desc(),
        TariffPlan.group_id.asc().nullsfirst(),
        TariffPlan.order_index.asc(),
        TariffPlan.updated_at.desc(),
        TariffPlan.plan_id.desc(),
    ).all()
    plans_by_group: list[tuple[TariffGroup, list[TariffPlan]]] = []
    for g in groups:
        items = [p for p in plans if p.group_id == g.group_id]
        plans_by_group.append((g, items))
    ungrouped_plans = [p for p in plans if not p.group_id]
    return render_template('billing_plans.html', groups=groups, plans_by_group=plans_by_group, ungrouped_plans=ungrouped_plans)


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
        group_id=request.form.get('group_id', type=int) or None,
        order_index=request.form.get('order_index', type=int) or 0,
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


@billing_bp.route('/billing/plans/<int:plan_id>/update', methods=['POST'])
@login_required
def billing_plan_update(plan_id: int):
    _require_admin()
    plan = TariffPlan.query.get_or_404(plan_id)
    title = (request.form.get('title') or '').strip()
    if title:
        plan.title = title
    plan.description = (request.form.get('description') or '').strip() or None
    plan.price_rub = request.form.get('price_rub', type=int)
    plan.period_days = request.form.get('period_days', type=int)
    plan.group_id = request.form.get('group_id', type=int) or None
    plan.order_index = request.form.get('order_index', type=int) or 0
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='billing_plan_update', entity='TariffPlan', entity_id=plan_id, error=str(e))
        flash('Не удалось обновить тариф.', 'danger')
        return redirect(url_for('billing.billing_plans'))
    flash('Тариф обновлён.', 'success')
    return redirect(url_for('billing.billing_plans'))


@billing_bp.route('/billing/groups/new', methods=['POST'])
@login_required
def billing_group_create():
    _require_admin()
    title = (request.form.get('title') or '').strip()
    if not title:
        flash('Название группы обязательно.', 'danger')
        return redirect(url_for('billing.billing_plans'))
    g = TariffGroup(
        title=title,
        order_index=request.form.get('order_index', type=int) or 0,
        is_active=True,
    )
    db.session.add(g)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='billing_group_create', entity='TariffGroup', error=str(e))
        flash('Не удалось создать группу.', 'danger')
        return redirect(url_for('billing.billing_plans'))
    flash('Группа создана.', 'success')
    return redirect(url_for('billing.billing_plans'))


@billing_bp.route('/billing/groups/<int:group_id>/toggle', methods=['POST'])
@login_required
def billing_group_toggle(group_id: int):
    _require_admin()
    g = TariffGroup.query.get_or_404(group_id)
    g.is_active = not bool(g.is_active)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='billing_group_toggle', entity='TariffGroup', entity_id=group_id, error=str(e))
        flash('Не удалось изменить статус группы.', 'danger')
        return redirect(url_for('billing.billing_plans'))
    flash('Статус группы обновлён.', 'success')
    return redirect(url_for('billing.billing_plans'))


@billing_bp.route('/billing/subscriptions')
@login_required
def billing_subscriptions():
    _require_admin()
    preselect_plan_id = request.args.get('plan_id', type=int)
    subs = UserSubscription.query.options(db.joinedload(UserSubscription.user), db.joinedload(UserSubscription.plan)).order_by(UserSubscription.updated_at.desc(), UserSubscription.subscription_id.desc()).limit(300).all()
    groups = TariffGroup.query.filter_by(is_active=True).order_by(TariffGroup.order_index.asc(), TariffGroup.group_id.asc()).all()
    plans = TariffPlan.query.filter_by(is_active=True).order_by(
        TariffPlan.group_id.asc().nullsfirst(),
        TariffPlan.order_index.asc(),
        TariffPlan.title.asc(),
        TariffPlan.plan_id.asc(),
    ).all()
    plans_by_group: list[tuple[TariffGroup, list[TariffPlan]]] = []
    for g in groups:
        items = [p for p in plans if p.group_id == g.group_id]
        if items:
            plans_by_group.append((g, items))
    ungrouped_plans = [p for p in plans if not p.group_id]
    q = (request.args.get('q') or '').strip()
    users_q = User.query
    if q:
        like = f"%{q}%"
        users_q = users_q.filter((User.username.ilike(like)) | (User.email.ilike(like)))
    users = users_q.order_by(User.id.desc()).limit(200).all()
    return render_template('billing_subscriptions.html', subs=subs, groups=groups, plans=plans, plans_by_group=plans_by_group, ungrouped_plans=ungrouped_plans, users=users, q=q, preselect_plan_id=preselect_plan_id)


@billing_bp.route('/billing/subscriptions/assign', methods=['POST'])
@login_required
def billing_subscription_assign():
    """Назначить/продлить подписку пользователю (upsert)."""
    _require_admin()
    user_id = request.form.get('user_id', type=int)
    plan_id = request.form.get('plan_id', type=int)
    days = request.form.get('days', type=int) or 30
    note = (request.form.get('note') or '').strip() or None
    if not user_id:
        flash('Выберите пользователя.', 'danger')
        return redirect(url_for('billing.billing_subscriptions'))

    now = datetime.utcnow()

    active = UserSubscription.query.filter_by(user_id=user_id, status='active').order_by(UserSubscription.ends_at.desc().nullslast(), UserSubscription.subscription_id.desc()).all()
    sub = active[0] if active else None
    # оставляем одну активную, остальные отменяем (чтобы не было “двух активных”)
    for extra in active[1:]:
        extra.status = 'cancelled'

    if sub:
        base_end = sub.ends_at or now
        if base_end < now:
            base_end = now
        sub.plan_id = plan_id or None
        sub.started_at = sub.started_at or now
        sub.ends_at = base_end + timedelta(days=int(days))
        if note:
            sub.note = note
    else:
        sub = UserSubscription(
            user_id=user_id,
            plan_id=plan_id or None,
            status='active',
            started_at=now,
            ends_at=(now + timedelta(days=int(days))),
            note=note,
        )
        db.session.add(sub)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='billing_subscription_assign', entity='UserSubscription', error=str(e))
        flash('Не удалось назначить подписку.', 'danger')
        return redirect(url_for('billing.billing_subscriptions'))

    try:
        audit_logger.log(action='billing_subscription_assign', entity='UserSubscription', entity_id=sub.subscription_id, status='success', metadata={'user_id': user_id, 'plan_id': plan_id, 'days': days})
    except Exception:
        pass
    flash('Подписка назначена.', 'success')
    return redirect(url_for('billing.billing_subscriptions', plan_id=plan_id or None))


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

