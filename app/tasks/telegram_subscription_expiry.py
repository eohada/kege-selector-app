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
    from app.models import db
    from core.db_models import MOSCOW_TZ, moscow_now
    from sqlalchemy import text
    from app.telegram.notifications import notify_subscription_expiring
    from app.telegram.user_notify import get_profile_for_user, user_allows_telegram_notification

    now = moscow_now()
    sent = 0

    try:
        from urep_bot.db import get_session, close_session
        session = get_session()
        try:
            # Подписки, истекающие через 1 или 3 дня
            rows = session.execute(text("""
                SELECT us.user_id, us.end_date
                FROM "UserSubscriptions" us
                WHERE us.status = 'active'
                  AND us.end_date IS NOT NULL
                  AND DATE(us.end_date) IN (
                      CURRENT_DATE + INTERVAL '1 day',
                      CURRENT_DATE + INTERVAL '3 days'
                  )
            """)).fetchall()

            for user_id, end_date in rows:
                try:
                    profile = get_profile_for_user(int(user_id))
                    if not user_allows_telegram_notification(profile, 'subscription_expiring'):
                        continue

                    end_dt = end_date
                    if hasattr(end_dt, 'tzinfo') and end_dt.tzinfo:
                        end_dt = end_dt.astimezone(MOSCOW_TZ)
                    delta = (end_dt.replace(tzinfo=None) if end_dt.tzinfo else end_dt) - now.replace(tzinfo=None)
                    days_left = max(0, delta.days)

                    if notify_subscription_expiring(
                        student_user_id=int(user_id),
                        days_left=days_left,
                        subscription_end=end_dt.strftime('%d.%m.%Y') if end_dt else '—',
                    ):
                        sent += 1
                except Exception as loop_err:
                    logger.warning('subscription_expiry skip user %s: %s', user_id, loop_err)
        finally:
            close_session(session)

    except Exception as e:
        logger.error('telegram_subscription_expiry_task: %s', e, exc_info=True)
        return {'ok': False, 'error': str(e), 'sent': sent}

    return {'ok': True, 'sent': sent}
