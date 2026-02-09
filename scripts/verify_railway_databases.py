"""
Скрипт для проверки подключений к новым централизованным базам данных в Railway
Использование:
    python scripts/verify_railway_databases.py
"""
import os
import sys
from urllib.parse import urlparse
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.exc import OperationalError

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

def mask_url(url):
    """Маскирует пароль в URL для безопасного вывода"""
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

def check_database_connection(name, url):
    """Проверяет подключение к базе данных"""
    if not url:
        print(f"❌ {name}: URL не установлен")
        return False, None
    
    try:
        if url.startswith('postgres://'):
            url = url.replace('postgres://', 'postgresql://', 1)
        
        engine = create_engine(url, pool_pre_ping=True, connect_args={'connect_timeout': 10})
        
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            result.fetchone()
        
        print(f"✅ {name}: Подключение успешно")
        print(f"   URL: {mask_url(url)}")
        return True, engine
    except OperationalError as e:
        print(f"❌ {name}: Ошибка подключения")
        print(f"   URL: {mask_url(url)}")
        print(f"   Ошибка: {str(e)}")
        return False, None
    except Exception as e:
        print(f"❌ {name}: Неожиданная ошибка")
        print(f"   URL: {mask_url(url)}")
        print(f"   Ошибка: {str(e)}")
        return False, None

def check_database_structure(engine, name):
    """Проверяет структуру базы данных (таблицы)"""
    try:
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        if not tables:
            print(f"   ⚠️  {name}: База данных пуста (нет таблиц)")
            return False, []
        else:
            print(f"   ✅ {name}: Найдено таблиц: {len(tables)}")
            return True, tables
    except Exception as e:
        print(f"   ⚠️  {name}: Не удалось проверить структуру: {e}")
        return False, []

def check_table_data(engine, table_name):
    """Проверяет количество записей в таблице"""
    try:
        with engine.connect() as conn:
            result = conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))
            count = result.fetchone()[0]
            return count
    except Exception as e:
        return None

def main():
    """Основная функция проверки"""
    print("=" * 70)
    print("ПРОВЕРКА ПОДКЛЮЧЕНИЯ К БАЗЕ ДАННЫХ")
    print("=" * 70)
    print()
    
    environment = os.environ.get('ENVIRONMENT', 'unknown').upper()
    
    database_url = os.environ.get('DATABASE_URL')
    
    if not database_url:
        print("❌ DATABASE_URL не установлен в переменных окружения")
        print()
        print("💡 Как исправить:")
        print("   1. В Railway откройте ваш сервис (production/sandbox/admin)")
        print("   2. Перейдите в 'Variables' (вверху)")
        print("   3. Найдите или создайте переменную 'DATABASE_URL'")
        print("   4. Установите значение из соответствующей БД:")
        print("      - Production: из 'production-db' в проекте 'Databases'")
        print("      - Sandbox: из 'sandbox-db' в проекте 'Databases'")
        print("      - Admin: из 'admin-db' в проекте 'Databases'")
        print("   5. Сохраните и перезапустите сервис")
        print()
        print("   Или используйте Service Reference в Railway:")
        print("   - При создании переменной выберите 'Reference'")
        print("   - Выберите нужную БД (production-db/sandbox-db/admin-db)")
        print("   - Выберите переменную 'DATABASE_URL'")
        print()
        return False
    
    if environment == 'PRODUCTION':
        db_name = f'Production DB ({environment})'
    elif environment == 'SANDBOX':
        db_name = f'Sandbox DB ({environment})'
    elif environment == 'ADMIN':
        db_name = f'Admin DB ({environment})'
    else:
        db_name = f'Current DB ({environment})'
    
    print(f"🌍 Окружение: {environment}")
    print(f"📊 Проверяем: {db_name}")
    print()
    
    success, engine = check_database_connection(db_name, database_url)
    
    if success and engine:
        has_tables, tables = check_database_structure(engine, db_name)
        
        if has_tables and tables:
            important_tables = ['Users', 'Students', 'Lessons', 'Tasks']
            print(f"   📊 Проверка основных таблиц:")
            for table in important_tables:
                if table in tables:
                    count = check_table_data(engine, table)
                    if count is not None:
                        print(f"      - {table}: {count} записей")
                    else:
                        print(f"      - {table}: ошибка чтения")
                else:
                    print(f"      - {table}: не найдена (это нормально для новой базы)")
        else:
            print()
            print("💡 База данных пуста - это нормально для новой базы!")
            print("   Приложение автоматически создаст таблицы при первом запуске.")
            print("   Или создайте вручную:")
            print("   python -c \"from app import create_app, db; app = create_app(); app.app_context().push(); db.create_all()\"")
    
    print()
    print("=" * 70)
    
    if success:
        print("✅ База данных доступна и готова к использованию!")
    else:
        print("❌ База данных недоступна. Проверьте настройки.")
    
    print("=" * 70)
    
    return success

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
