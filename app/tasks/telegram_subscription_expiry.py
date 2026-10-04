"""Напоминания об истечении подписки (Celery beat, раз в сутки)."""
from __future__ import annotations

import logging
from datetime import timedelta

from celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(name='app.tasks.telegram_subscription_expiry.telegram_subscription_expiry_task')
def telegram_subscription_expiry_task() -> dict:
    """
    Раз в сутки проверяет подписки, которые истекают ровно через 3 дня или 1 день.
    Отправляет предупреждение ученику с кнопкой продления.
    """
    from app.models import db, UserSubscription
    from core.db_models import MOSCOW_TZ, moscow_now
    from app.telegram.notifications import notify_subscription_expiring
    from app.telegram.user_notify import get_profile_for_user, user_allows_telegram_notification

    now = moscow_now()
    sent = 0

    try:
        rows = UserSubscription.query.filter(
            UserSubscription.status == 'active',
            UserSubscription.ends_at.isnot(None),
        ).all()
        for subscription in rows:
            try:
                end_dt = subscription.ends_at
                if getattr(end_dt, 'tzinfo', None):
                    end_dt = end_dt.astimezone(MOSCOW_TZ).replace(tzinfo=None)
                days_left = (end_dt.date() - now.date()).days
                if days_left not in {1, 3}:
                    continue
                profile = get_profile_for_user(int(subscription.user_id))
                if not user_allows_telegram_notification(profile, 'subscription_expiring'):
                    continue
                if notify_subscription_expiring(
                    student_user_id=int(subscription.user_id),
                    days_left=days_left,
                    subscription_end=end_dt.strftime('%d.%m.%Y'),
                ):
                    sent += 1
            except Exception as loop_err:
                logger.warning('subscription_expiry skip user %s: %s', subscription.user_id, loop_err)

    except Exception as e:
        logger.error('telegram_subscription_expiry_task: %s', e, exc_info=True)
        return {'ok': False, 'error': str(e), 'sent': sent}

    return {'ok': True, 'sent': sent}
