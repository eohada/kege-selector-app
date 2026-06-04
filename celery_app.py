"""
Celery application factory for BooStudy.
Shares Flask config and app context with Celery workers.
"""
import os

from celery import Celery


def make_celery(app=None):
    """Create a Celery instance that uses the Flask app context."""
    celery = Celery(
        'boostudy',
        broker=None,
        backend=None,
    )

    if app is None:
        from wsgi import app as flask_app
        app = flask_app

    celery.conf.update(
        broker_url=app.config.get('CELERY_BROKER_URL', 'redis://localhost:6379/0'),
        result_backend=app.config.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0'),
        task_serializer='json',
        result_serializer='json',
        accept_content=['json'],
        timezone='Europe/Moscow',
        task_track_started=True,
        task_time_limit=120,
        task_soft_time_limit=90,
        worker_prefetch_multiplier=1,
        worker_max_tasks_per_child=100,
    )

    beat = dict(app.config.get('CELERY_BEAT_SCHEDULE') or {})

    # Deadline reminders (каждые 15 мин)
    if os.environ.get('TELEGRAM_DEADLINE_REMINDERS_DISABLED', '').strip().lower() not in ('1', 'true', 'yes'):
        beat.setdefault(
            'telegram-deadline-reminders',
            {
                'task': 'app.tasks.telegram_deadlines.telegram_deadline_reminders_task',
                'schedule': float(os.environ.get('TELEGRAM_DEADLINE_BEAT_SECONDS', '900')),
            },
        )

    # Lesson reminders (каждые 5 мин)
    if os.environ.get('TELEGRAM_LESSON_REMINDERS_DISABLED', '').strip().lower() not in ('1', 'true', 'yes'):
        beat.setdefault(
            'telegram-lesson-reminders-30min',
            {
                'task': 'app.tasks.telegram_lesson_reminders.telegram_lesson_reminders_task',
                'schedule': float(os.environ.get('TELEGRAM_LESSON_BEAT_SECONDS', '300')),
            },
        )

    # Daily digest (8:00 МСК пн–сб)
    if os.environ.get('TELEGRAM_DAILY_DIGEST_DISABLED', '').strip().lower() not in ('1', 'true', 'yes'):
        from celery.schedules import crontab
        beat.setdefault(
            'telegram-daily-digest',
            {
                'task': 'app.tasks.telegram_daily_digest.telegram_daily_digest_task',
                'schedule': crontab(hour=8, minute=0, day_of_week='1-6'),
            },
        )

    # Subscription expiry check (раз в сутки в 9:00 МСК)
    if os.environ.get('TELEGRAM_SUBSCRIPTION_EXPIRY_DISABLED', '').strip().lower() not in ('1', 'true', 'yes'):
        from celery.schedules import crontab as _crontab
        beat.setdefault(
            'telegram-subscription-expiry',
            {
                'task': 'app.tasks.telegram_subscription_expiry.telegram_subscription_expiry_task',
                'schedule': _crontab(hour=9, minute=0),
            },
        )

    celery.conf.beat_schedule = beat

    class ContextTask(celery.Task):
        abstract = True

        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask

    # Import task modules so decorator-registered tasks are actually loaded
    # when the worker process starts. Without this, the worker can connect to
    # Redis but still show an empty task registry.
    import app.tasks  # noqa: F401

    return celery


celery = make_celery()
