"""
Новый app.py, использующий фабрику приложений из app/__init__.py
"""
import logging
from app import create_app

logger = logging.getLogger(__name__)

# Создаем приложение используя фабрику
app = create_app()

if __name__ == '__main__':
    logger.info('Запуск приложения')
    app.run(debug=True, host='127.0.0.1', port=5000)

