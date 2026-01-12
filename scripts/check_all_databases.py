#!/usr/bin/env python3
"""
Скрипт для проверки состояния всех баз данных
Использование:
  python scripts/check_all_databases.py
"""
import os
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def mask_url(url):
    """Маскирует пароль в URL"""
    if not url:
        return None
    try:
        parsed = urlparse(url)
        if parsed.password:
            masked = url.replace(parsed.password, '***')
            return masked
        return url
    except:
        return url

def check_database(name, url):
    """Проверяет подключение к БД"""
    if not url:
        print(f"❌ {name}: URL не установлен")
        return False
    
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(url, pool_pre_ping=True)
        
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            result.fetchone()
        
        print(f"✅ {name}: Подключение успешно")
        print(f"   URL: {mask_url(url)}")
        return True
    except Exception as e:
        print(f"❌ {name}: Ошибка подключения")
        print(f"   URL: {mask_url(url)}")
        print(f"   Ошибка: {str(e)}")
        return False

def main():
    """Проверяет все БД из переменных окружения"""
    print("=" * 60)
    print("ПРОВЕРКА БАЗ ДАННЫХ")
    print("=" * 60)
    
    databases = {
        'Production': os.environ.get('PRODUCTION_DATABASE_URL') or os.environ.get('PRODUCTION_DB_URL'),
        'Sandbox': os.environ.get('SANDBOX_DATABASE_URL') or os.environ.get('SANDBOX_DB_URL'),
        'Admin': os.environ.get('DATABASE_URL'),
        'Current': os.environ.get('DATABASE_URL')
    }
    
    results = {}
    for name, url in databases.items():
        if name == 'Current' and url == databases.get('Admin'):
            continue  # Пропускаем дубликат
        results[name] = check_database(name, url)
        print()
    
    print("=" * 60)
    total = len(results)
    success = sum(1 for v in results.values() if v)
    print(f"Итого: {success}/{total} БД доступны")
    print("=" * 60)
    
    return success == total

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
