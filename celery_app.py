"""
Celery application factory for BooStudy.
Shares Flask config and app context with Celery workers.
"""
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

    class ContextTask(celery.Task):
        abstract = True

        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    return celery


celery = make_celery()
