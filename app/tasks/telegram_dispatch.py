"""Асинхронная доставка Telegram через Celery (внутренние события)."""
from celery_app import celery


@celery.task(bind=True, max_retries=2, default_retry_delay=5)
def telegram_notify_user_task(self, user_id: int, text: str, kind: str | None = None) -> dict:
    try:
        from app.telegram.delivery import enqueue_delivery

        row = enqueue_delivery(int(user_id), text, kind=kind)
        return {'ok': True, 'queued': True, 'delivery_id': row.delivery_id, 'user_id': user_id}
    except Exception as exc:
        try:
            self.retry(exc=exc)
        except Exception:
            return {'ok': False, 'error': str(exc), 'user_id': user_id}


@celery.task
def telegram_delivery_dispatch_task(limit=50):
    from app.telegram.delivery import claim_due_deliveries, deliver_one
    ids = claim_due_deliveries(limit)
    results = [deliver_one(delivery_id) for delivery_id in ids]
    return {'claimed': len(ids), 'sent': sum(1 for item in results if item.get('ok'))}


@celery.task
def telegram_delivery_recovery_task():
    from app.telegram.delivery import recover_stale_processing
    return {'recovered': recover_stale_processing()}
