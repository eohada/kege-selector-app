"""
Celery application factory for BooStudy.
Shares Flask config and app context with Celery workers.
"""
import os

from celery import Celery

CELERY_TASK_MODULES = [
    'app.tasks.code_check',
    'app.tasks.notifications',
    'app.tasks.submissions',
    'app.tasks.telegram_dispatch',
    'app.tasks.telegram_deadlines',
    'app.tasks.telegram_lesson_reminders',
    'app.tasks.telegram_homework_notes',
    'app.tasks.telegram_daily_digest',
    'app.tasks.telegram_subscription_expiry',
    'app.tasks.telegram_broadcast',
    'app.tasks.telegram_webhook',
]


def validate_celery_runtime_config(environment: str | None = None) -> dict[str, object]:
    """Validate the broker contract before a production worker starts.

    Local development deliberately uses an in-process broker. Production-like
    environments must never silently fall back to it because web and workers
    would then use different queues.
    """
    env = (environment or os.environ.get('ENVIRONMENT') or 'local').strip().lower()
    production_like = env in {'production', 'prod', 'staging', 'sandbox'}
    broker = (os.environ.get('CELERY_BROKER_URL') or '').strip()
    backend = (os.environ.get('CELERY_RESULT_BACKEND') or '').strip()
    if production_like:
        if not broker or not broker.startswith(('redis://', 'rediss://')):
            raise RuntimeError(
                'CELERY_BROKER_URL must be a Redis URL in production-like environments'
            )
        if not backend or not backend.startswith(('redis://', 'rediss://')):
            raise RuntimeError(
                'CELERY_RESULT_BACKEND must be a Redis URL in production-like environments'
            )
    return {
        'environment': env,
        'production_like': production_like,
        'broker_url': broker,
        'result_backend': backend,
    }


def make_celery(app=None):
    """Create a Celery instance that uses the Flask app context."""
    celery = Celery(
        'boostudy',
        broker=None,
        backend=None,
        include=CELERY_TASK_MODULES,
    )

    if app is None:
        from wsgi import app as flask_app
        app = flask_app

    runtime = validate_celery_runtime_config()
    is_local = not bool(runtime['production_like']) and runtime['environment'] in {
        'local', 'development', 'dev'
    }
    background_workers_disabled = (os.environ.get('DISABLE_BACKGROUND_WORKERS') or '').strip().lower() in {
        '1', 'true', 'yes', 'on'
    }
    celery.conf.update(
        broker_url=(app.config.get('CELERY_BROKER_URL') or runtime['broker_url'] or 'redis://localhost:6379/0') if not is_local else 'memory://',
        result_backend=(app.config.get('CELERY_RESULT_BACKEND') or runtime['result_backend'] or 'redis://localhost:6379/0') if not is_local else None,
        task_serializer='json',
        result_serializer='json',
        accept_content=['json'],
        timezone='Europe/Moscow',
        task_track_started=True,
        task_time_limit=120,
        task_soft_time_limit=90,
        worker_prefetch_multiplier=1,
        worker_max_tasks_per_child=100,
        # Tests and maintenance commands must never execute side effects in a
        # second implicit Flask application.  In production Celery workers
        # remain responsible for delivery; local development can still run
        # eagerly when background work is explicitly enabled.
        task_always_eager=is_local and not background_workers_disabled,
        task_ignore_result=is_local or background_workers_disabled,
    )

    beat = dict(app.config.get('CELERY_BEAT_SCHEDULE') or {})

    if os.environ.get('TELEGRAM_DELIVERY_DISABLED', '').strip().lower() not in ('1', 'true', 'yes'):
        beat.setdefault('telegram-delivery-dispatch', {
            'task': 'app.tasks.telegram_dispatch.telegram_delivery_dispatch_task',
            'schedule': float(os.environ.get('TELEGRAM_DELIVERY_BEAT_SECONDS', '15')),
        })
        beat.setdefault('telegram-delivery-recovery', {
            'task': 'app.tasks.telegram_dispatch.telegram_delivery_recovery_task',
            'schedule': float(os.environ.get('TELEGRAM_DELIVERY_RECOVERY_SECONDS', '60')),
        })

    # Deadline reminders (каждые 15 мин)
    if os.environ.get('TELEGRAM_DEADLINE_REMINDERS_DISABLED', '').strip().lower() not in ('1', 'true', 'yes'):
        beat.setdefault(
            'telegram-deadline-reminders',
            {
                'task': 'app.tasks.telegram_deadlines.telegram_deadline_reminders_task',
                'schedule': float(os.environ.get('TELEGRAM_DEADLINE_BEAT_SECONDS', '900')),
            },
        )

    # Lesson reminders (почти каждую минуту, узкое окно вокруг 30 минут)
    if os.environ.get('TELEGRAM_LESSON_REMINDERS_DISABLED', '').strip().lower() not in ('1', 'true', 'yes'):
        beat.setdefault(
            'telegram-lesson-reminders-30min',
            {
                'task': 'app.tasks.telegram_lesson_reminders.telegram_lesson_reminders_task',
                'schedule': float(os.environ.get('TELEGRAM_LESSON_BEAT_SECONDS', '30')),
            },
        )

    if os.environ.get('TELEGRAM_HOMEWORK_NOTES_DISABLED', '').strip().lower() not in ('1', 'true', 'yes'):
        beat.setdefault(
            'telegram-homework-notes',
            {
                'task': 'app.tasks.telegram_homework_notes.telegram_homework_notes_task',
                'schedule': float(os.environ.get('TELEGRAM_HOMEWORK_NOTES_BEAT_SECONDS', '30')),
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

    return celery


celery = make_celery()
