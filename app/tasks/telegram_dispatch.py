"""Асинхронная доставка Telegram через Celery (внутренние события)."""
from celery_app import celery


@celery.task(bind=True, max_retries=2, default_retry_delay=5)
def telegram_notify_user_task(self, user_id: int, text: str, kind: str | None = None) -> dict:
    try:
        from app.telegram.user_notify import notify_user_by_id

        ok = notify_user_by_id(int(user_id), text, kind=kind)
        return {'ok': bool(ok), 'user_id': user_id}
    except Exception as exc:
        try:
            self.retry(exc=exc)
        except Exception:
            return {'ok': False, 'error': str(exc), 'user_id': user_id}
