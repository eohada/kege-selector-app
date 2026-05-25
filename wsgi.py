import os

# Apply eventlet monkey patch as early as possible in production before any other imports
def should_use_eventlet():
    # Only use eventlet if explicitly requested via env variable.
    # If Gunicorn is running with eventlet worker, Gunicorn itself applies monkey patching before loading this file.
    # Therefore, we do not need to apply it here unless explicitly forced.
    return os.environ.get('USE_EVENTLET', '').lower() == 'true'

if should_use_eventlet():
    try:
        import os
        # Disable eventlet's custom greendns resolver which can cause DNS timeouts/hangs in Docker containers
        os.environ['EVENTLET_NO_GREENDNS'] = 'yes'
        import eventlet
        eventlet.monkey_patch()
        print("[OK] Eventlet monkey patching applied (greendns disabled)")
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

