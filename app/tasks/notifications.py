"""Async notification tasks."""
from celery_app import celery


@celery.task(bind=True, max_retries=3, default_retry_delay=30)
def send_notification_task(self, user_id: int, message: str, notification_type: str = 'info'):
    """Send a notification to a user (creates a Notification record in DB)."""
    try:
        from app.models import db, Notification

        notification = Notification(
            user_id=user_id,
            message=message,
            type=notification_type,
        )
        db.session.add(notification)
        db.session.commit()
        return {'status': 'sent', 'user_id': user_id, 'notification_id': notification.id}
    except Exception as exc:
        self.retry(exc=exc)
