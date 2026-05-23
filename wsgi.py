import os

# Apply eventlet monkey patch as early as possible in production before any other imports
def should_use_eventlet():
    env = os.environ.get('ENVIRONMENT', 'local').lower()
    if env in ('local', 'dev', 'development'):
        return False
    if env in ('prod', 'production', 'stage', 'staging'):
        return True
    if 'gunicorn' in os.environ.get('SERVER_SOFTWARE', '').lower():
        return True
    db_url = os.environ.get('DATABASE_URL', '') or os.environ.get('DATABASE_EXTERNAL_URL', '') or os.environ.get('POSTGRES_URL', '')
    if db_url and ('postgres' in db_url.lower() or 'postgresql' in db_url.lower()):
        return True
    return False

if should_use_eventlet():
    try:
        import os
        # Disable eventlet's custom greendns resolver which can cause DNS timeouts/hangs in Docker containers
        os.environ['EVENTLET_NO_GREENDNS'] = 'yes'
        import eventlet
        eventlet.monkey_patch()
        print("[OK] Eventlet monkey patching applied for production (greendns disabled)")
    except ImportError:
        print("[WARN] Eventlet not installed, skipping monkey patching")

try:
    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        load_dotenv(env_path, override=True)
        print(f"[OK] Loaded env vars from {env_path}")
except ImportError:
    pass

from app import create_app

import logging
logger = logging.getLogger(__name__)

app = create_app()

if __name__ == '__main__':
    logger.info('Запуск приложения')
    socketio = getattr(app, 'socketio', None)
    if socketio:
        socketio.run(app, debug=True, host='127.0.0.1', port=5000)
    else:
        app.run(debug=True, host='127.0.0.1', port=5000)

