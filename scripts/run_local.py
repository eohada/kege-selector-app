
"""
Запуск приложения локально для разработки (в т.ч. страница тарифов без деплоя).


Перед первым запуском: pip install -r requirements.txt (или активируй свой venv).

Использование:
  python scripts/run_local.py

Либо из корня проекта: python wsgi.py

После запуска открой в браузере:
  http://127.0.0.1:5000/billing/plans/public   — страница тарифов
  http://127.0.0.1:5000/                        — главная / лендинг
"""
import os
import sys

root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, root)
os.chdir(root)

# Подгружаем .env если есть
try:
    from dotenv import load_dotenv
    env_path = os.path.join(root, '.env')
    if os.path.exists(env_path):
        load_dotenv(env_path, override=True)
except ImportError:
    pass

os.environ.setdefault('SECRET_KEY', 'dev-secret-key-123')
os.environ.setdefault('RATELIMIT_ENABLED', 'false')

def main():
    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', 5000))
    print(f'Запуск приложения на http://{host}:{port}')
    print(f'Локально: http://127.0.0.1:{port}')
    print('Страница тарифов (для вёрстки): http://127.0.0.1:5000/billing/plans/public')
    print('Остановка: Ctrl+C')
    print()

    from app import create_app
    app = create_app()
    socketio = getattr(app, 'socketio', None)
    if socketio:
        socketio.run(app, debug=True, host=host, port=port, allow_unsafe_werkzeug=True, use_reloader=False)
    else:
        app.run(debug=True, host=host, port=port, use_reloader=False)

if __name__ == '__main__':
    main()
