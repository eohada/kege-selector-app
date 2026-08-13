"""Domain logic for safe promo-code validation and free-access redemption."""
from __future__ import annotations

from datetime import datetime, timedelta

from app.models import db, PromoCode, PromoCodeUsage, TariffPlan, UserSubscription


class PromoCodeError(ValueError):
    """The promo code cannot be applied to the requested plan."""


def _normalise_code(raw_code: str | None) -> str:
    return (raw_code or '').strip().upper()


def get_eligible_promo_code(raw_code: str | None, user_id: int, plan: TariffPlan) -> PromoCode:
    """Return a promo code which can be used once by this user for this plan."""
    code = _normalise_code(raw_code)
    if not code:
        raise PromoCodeError('Введите промокод.')
    if not plan or not plan.is_active:
        raise PromoCodeError('Тариф недоступен.')

    promo = PromoCode.query.filter_by(code=code).with_for_update().first()
    if not promo or not promo.is_active:
        raise PromoCodeError('Промокод не найден или отключён.')

    now = datetime.utcnow()
    if promo.starts_at and promo.starts_at > now:
        raise PromoCodeError('Промокод ещё не начал действовать.')
    if promo.expires_at and promo.expires_at < now:
        raise PromoCodeError('Срок действия промокода истёк.')
    if promo.plan_id and promo.plan_id != plan.plan_id:
        raise PromoCodeError('Промокод не действует для выбранного тарифа.')
    if promo.usage_limit is not None and int(promo.usage_count or 0) >= promo.usage_limit:
        raise PromoCodeError('Лимит использований промокода исчерпан.')
    if PromoCodeUsage.query.filter_by(promocode_id=promo.id, user_id=user_id).first():
        raise PromoCodeError('Этот промокод уже был использован вашим аккаунтом.')
    return promo


def get_final_price(plan: TariffPlan, promo: PromoCode) -> int:
    """Calculate the server-side price; browser-supplied prices are never trusted."""
    price = max(0, int(plan.price_rub or 0))
    percent = min(100, max(0, int(promo.discount_percent or 0)))
    price = price * (100 - percent) // 100
    return max(0, price - max(0, int(promo.discount_rub or 0)))


def redeem_free_promo(raw_code: str | None, user_id: int, plan_id: int) -> UserSubscription:
    """Grant a plan only when a promo makes its server-side price exactly zero."""
    plan = TariffPlan.query.filter_by(plan_id=plan_id, is_active=True).first()
    if not plan:
        raise PromoCodeError('Тариф недоступен.')

    promo = get_eligible_promo_code(raw_code, user_id, plan)
    if get_final_price(plan, promo) != 0:
        raise PromoCodeError('Этот промокод даёт скидку, но не бесплатный доступ. Оплата будет доступна после подключения платёжного сервиса.')

    now = datetime.utcnow()
    duration_days = max(1, int(plan.period_days or 30) + max(0, int(promo.bonus_days or 0)))
    lessons_remaining = None
    if plan.lessons_count is not None:
        lessons_remaining = max(0, int(plan.lessons_count)) + max(0, int(promo.bonus_lessons or 0))

    subscription = UserSubscription(
        user_id=user_id,
        plan_id=plan.plan_id,
        status='active',
        started_at=now,
        ends_at=now + timedelta(days=duration_days),
        lessons_remaining=lessons_remaining,
        note=f'Бесплатный доступ по промокоду {promo.code}',
    )
    promo.usage_count = int(promo.usage_count or 0) + 1
    db.session.add(subscription)
    db.session.flush()
    db.session.add(PromoCodeUsage(
        promocode_id=promo.id,
        user_id=user_id,
        subscription_id=subscription.subscription_id,
    ))
    return subscription
