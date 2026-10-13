import os

# Disable eventlet's custom greendns resolver before any optional eventlet import.
os.environ.setdefault('EVENTLET_NO_GREENDNS', 'yes')

# Apply eventlet monkey patch as early as possible in production before any other imports
def should_use_eventlet():
    # Only use eventlet if explicitly requested via env variable.
    # If Gunicorn is running with eventlet worker, Gunicorn itself applies monkey patching before loading this file.
    # Therefore, we do not need to apply it here unless explicitly forced.
    return os.environ.get('USE_EVENTLET', '').lower() == 'true'

if should_use_eventlet():
    try:
        import eventlet
        eventlet.monkey_patch()
        print("[OK] Eventlet monkey patching applied (greendns disabled)")
    except ImportError:
        print("[WARN] Eventlet not installed, skipping monkey patching")

try:
    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        # Deployment-provided environment variables must win over a local
        # .env file.  Overriding them could silently switch production back
        # to local settings or replace its secrets and database URL.
        load_dotenv(env_path, override=False)
        print(f"[OK] Loaded env vars from {env_path}")
except ImportError:
    pass

from app import create_app

import logging
logger = logging.getLogger(__name__)

app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    environment = (os.environ.get('ENVIRONMENT') or 'local').strip().lower()
    debug = environment in {'local', 'development', 'dev'}
    # Локальный сервер доступен с телефона/планшета в той же Wi‑Fi сети.
    # Внешний адрес всё равно ограничивается локальной сетью и Windows Firewall.
    host = os.environ.get('HOST', '0.0.0.0')
    logger.info(f'Запуск приложения на порту {port}')
    socketio = getattr(app, 'socketio', None)
    if socketio:
        socketio.run(app, debug=debug, host=host, port=port, allow_unsafe_werkzeug=debug, use_reloader=debug)
    else:
        app.run(debug=debug, host=host, port=port)
