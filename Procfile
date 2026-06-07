web: EVENTLET_NO_GREENDNS=yes gunicorn wsgi:app --worker-class eventlet -w 1 --bind 0.0.0.0:$PORT --timeout 180 --keep-alive 5
worker: celery -A celery_app.celery worker --loglevel=info --concurrency=2
beat: celery -A celery_app.celery beat --loglevel=info
