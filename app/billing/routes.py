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


@billing_bp.route('/billing/plans/public')
def billing_plans_public():
    """Публичная страница тарифов (без авторизации). Полностью статический шаблон.

    Раньше здесь подгружались TariffGroup/TariffPlan, но шаблон их не использует.
    Любой запрос к БД при недоступном или медленном Postgres может «висеть» до таймаута
    прокси и превращаться в 502; отдельный try/except не спасает от блокировки без исключения.
    """
    return render_template('billing_plans_public.html')


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
        price_per_lesson_rub=request.form.get('price_per_lesson_rub', type=int),
        period_days=request.form.get('period_days', type=int),
        lessons_count=request.form.get('lessons_count', type=int),
        allow_lessons=True if (request.form.get('allow_lessons') or 'off') == 'on' else False,
        allow_trainer=True if (request.form.get('allow_trainer') or 'off') == 'on' else False,
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
    plan.price_per_lesson_rub = request.form.get('price_per_lesson_rub', type=int)
    plan.period_days = request.form.get('period_days', type=int)
    plan.lessons_count = request.form.get('lessons_count', type=int)
    plan.group_id = request.form.get('group_id', type=int) or None
    plan.order_index = request.form.get('order_index', type=int) or 0
    plan.allow_lessons = True if (request.form.get('allow_lessons') or 'off') == 'on' else False
    plan.allow_trainer = True if (request.form.get('allow_trainer') or 'off') == 'on' else False
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
        users_q = users_q.filter(User.username.ilike(like))
    users = users_q.order_by(User.id.desc()).limit(200).all()
    return render_template('billing_subscriptions.html', subs=subs, groups=groups, plans=plans, plans_by_group=plans_by_group, ungrouped_plans=ungrouped_plans, users=users, q=q, preselect_plan_id=preselect_plan_id)


@billing_bp.route('/billing/subscriptions/assign', methods=['POST'])
@login_required
def billing_subscription_assign():
    """Назначить/продлить подписку пользователю (upsert)."""
    _require_admin()
    user_id = request.form.get('user_id', type=int)
    plan_id = request.form.get('plan_id', type=int)
    days = request.form.get('days', type=int)
    lessons = request.form.get('lessons', type=int)
    note = (request.form.get('note') or '').strip() or None
    if not user_id:
        flash('Выберите пользователя.', 'danger')
        return redirect(url_for('billing.billing_subscriptions'))

    now = datetime.utcnow()

    active = UserSubscription.query.filter_by(user_id=user_id, status='active').order_by(UserSubscription.ends_at.desc().nullslast(), UserSubscription.subscription_id.desc()).all()
    sub = active[0] if active else None
    for extra in active[1:]:
        extra.status = 'cancelled'

    before_lessons = sub.lessons_remaining if sub else None
    if sub:
        if days:
            base_end = sub.ends_at or now
            if base_end < now:
                base_end = now
            sub.ends_at = base_end + timedelta(days=int(days))
        if lessons:
            current_lessons = sub.lessons_remaining or 0
            sub.lessons_remaining = current_lessons + int(lessons)
        sub.plan_id = plan_id or sub.plan_id
        sub.started_at = sub.started_at or now
        if note:
            sub.note = note
    else:
        sub = UserSubscription(
            user_id=user_id,
            plan_id=plan_id or None,
            status='active',
            started_at=now,
            ends_at=(now + timedelta(days=int(days))) if days else None,
            lessons_remaining=lessons,
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
        if sub and sub.lessons_remaining is not None and (lessons is not None or before_lessons is not None):
            from app.telegram.notifications import notify_lesson_balance_changed
            notify_lesson_balance_changed(
                student_user_id=int(user_id),
                before=before_lessons,
                after=sub.lessons_remaining,
                reason=note or ('Назначение тарифа' if not sub.note else sub.note),
                source='tariff',
            )
    except Exception:
        logger.warning('Failed to notify lesson balance after billing_subscription_assign for user %s', user_id, exc_info=True)

    try:
        audit_logger.log(action='billing_subscription_assign', entity='UserSubscription', entity_id=sub.subscription_id, status='success', metadata={'user_id': user_id, 'plan_id': plan_id, 'days': days, 'lessons': lessons})
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


@billing_bp.route('/billing/plans/buy_simulate', methods=['POST'])
@login_required
def billing_plans_buy_simulate():
    from datetime import datetime, timedelta
    import re
    from flask import request, redirect, url_for, flash
    from flask_login import current_user
    from app.models import PromoCode, PromoCodeUsage

    goal = request.form.get('goal', 'ege')
    fmt = request.form.get('format', 'solo')
    volume = request.form.get('volume', 'Junior')
    price_str = request.form.get('price', '15000')
    promocode_str = (request.form.get('promocode') or '').strip().upper()

    plan_title = f"{fmt.capitalize()} ({goal.upper()}) - {volume}"
    
    try:
        # Ищем существующий тариф или создаем его
        plan = TariffPlan.query.filter_by(title=plan_title).first()
        if not plan:
            # Извлекаем кол-во уроков из лейбла, например "Junior (8 уроков)" -> 8
            lessons_match = re.search(r'(\d+)\s*урок', volume, re.IGNORECASE)
            lessons_count = int(lessons_match.group(1)) if lessons_match else 8
            if 'solo' in fmt.lower():
                lessons_count = 0 # В solo уроков может не быть, это доступ к тренажеру

            plan = TariffPlan(
                title=plan_title,
                description=f"Имитационный тариф для {goal.upper()} {fmt.capitalize()} ({volume})",
                price_rub=int(price_str),
                lessons_count=lessons_count,
                allow_lessons=True,
                allow_trainer=True,
                is_active=True
            )
            db.session.add(plan)
            db.session.commit()

        # Применяем промокод
        promocode = None
        discount_percent = 0
        discount_rub = 0
        bonus_lessons = 0
        bonus_days = 0
        
        if promocode_str:
            promocode = PromoCode.query.filter_by(code=promocode_str).first()
            if not promocode:
                flash(f"Промокод '{promocode_str}' не существует.", "danger")
                return redirect(url_for('billing.billing_plans_public'))
            
            if not promocode.is_active:
                flash(f"Промокод '{promocode_str}' неактивен.", "danger")
                return redirect(url_for('billing.billing_plans_public'))
                
            now = datetime.utcnow()
            if promocode.starts_at and promocode.starts_at > now:
                flash(f"Промокод '{promocode_str}' еще не действует.", "danger")
                return redirect(url_for('billing.billing_plans_public'))
                
            if promocode.expires_at and promocode.expires_at < now:
                flash(f"Срок действия промокода '{promocode_str}' истек.", "danger")
                return redirect(url_for('billing.billing_plans_public'))
                
            if promocode.usage_limit is not None and promocode.usage_count >= promocode.usage_limit:
                flash(f"Промокод '{promocode_str}' исчерпал лимит использований.", "danger")
                return redirect(url_for('billing.billing_plans_public'))
                
            # Промокод валиден! Собираем бонусы
            discount_percent = promocode.discount_percent or 0
            discount_rub = promocode.discount_rub or 0
            bonus_lessons = promocode.bonus_lessons or 0
            bonus_days = promocode.bonus_days or 0

        # Рассчитываем итоговую цену и параметры подписки
        price_val = int(price_str)
        if discount_percent:
            price_val = int(price_val * (100 - discount_percent) / 100)
        if discount_rub:
            price_val = max(0, price_val - discount_rub)

        subscription_days = 30 + bonus_days
        total_lessons = plan.lessons_count + bonus_lessons

        # Создаем подписку
        sub = UserSubscription(
            user_id=current_user.id,
            plan_id=plan.plan_id,
            status='active',
            started_at=datetime.utcnow(),
            ends_at=datetime.utcnow() + timedelta(days=subscription_days),
            lessons_remaining=total_lessons,
            note=f"Имитация покупки тарифа на сайте. Цена: {price_val} руб. (промокод: {promocode_str or 'нет'})"
        )
        db.session.add(sub)
        db.session.commit()

        # Логируем использование промокода
        if promocode:
            promocode.usage_count += 1
            usage = PromoCodeUsage(
                promocode_id=promocode.id,
                user_id=current_user.id,
                subscription_id=sub.subscription_id
            )
            db.session.add(usage)
            db.session.commit()

        msg = f"Оплата проведена успешно! Начислен тариф: {plan_title}. Доступно уроков: {total_lessons}"
        if promocode_str:
            msg += f" (применен промокод {promocode_str})"
        flash(msg, "success")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error simulating purchase: {e}", exc_info=True)
        flash(f"Ошибка при обработке платежа: {str(e)}", "danger")

    return redirect(url_for('main.dashboard'))


@billing_bp.route('/billing/promocode/check', methods=['POST'])
@login_required
def billing_promocode_check():
    import datetime
    from flask import request, jsonify
    from app.models import PromoCode
    
    code_str = (request.json.get('code') or '').strip().upper()
    if not code_str:
        return jsonify({'success': False, 'message': 'Промокод не введен.'})
        
    promocode = PromoCode.query.filter_by(code=code_str).first()
    if not promocode:
        return jsonify({'success': False, 'message': 'Такого промокода не существует.'})
        
    if not promocode.is_active:
        return jsonify({'success': False, 'message': 'Этот промокод неактивен.'})
        
    now = datetime.datetime.utcnow()
    if promocode.starts_at and promocode.starts_at > now:
        return jsonify({'success': False, 'message': 'Этот промокод еще не действует.'})
        
    if promocode.expires_at and promocode.expires_at < now:
        return jsonify({'success': False, 'message': 'Срок действия промокода истек.'})
        
    if promocode.usage_limit is not None and promocode.usage_count >= promocode.usage_limit:
        return jsonify({'success': False, 'message': 'Этот промокод уже использован максимальное количество раз.'})
        
    # Все ок! Возвращаем детали
    return jsonify({
        'success': True,
        'code': promocode.code,
        'discount_percent': promocode.discount_percent,
        'discount_rub': promocode.discount_rub,
        'bonus_lessons': promocode.bonus_lessons,
        'bonus_days': promocode.bonus_days
    })
