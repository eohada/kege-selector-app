"""
Новый app.py, использующий фабрику приложений из app/__init__.py
"""
import os
import logging

try:
    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        load_dotenv(env_path, override=True)
        print(f"[OK] Loaded env vars from {env_path}")
except ImportError:
    pass

from app import create_app

logger = logging.getLogger(__name__)

app = create_app()

if __name__ == '__main__':
    logger.info('Запуск приложения')
    app.run(debug=True, host='127.0.0.1', port=5000)

