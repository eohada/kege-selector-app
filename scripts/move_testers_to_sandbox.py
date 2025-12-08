#!/usr/bin/env python3
"""
Скрипт для переноса всех тестеров из production в sandbox
Использование:
    export PRODUCTION_DATABASE_URL="postgresql://..."
    export SANDBOX_DATABASE_URL="postgresql://..."
    python scripts/move_testers_to_sandbox.py
"""
import os
import sys
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from psycopg2.extras import execute_values
from urllib.parse import urlparse
from werkzeug.security import generate_password_hash

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)

def get_connection(database_url, name="database"):
    """Подключение к базе данных"""
    if not database_url:
        print(f"❌ {name} URL не установлен")
        return None
    
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    
    try:
        parsed = urlparse(database_url)
        conn = psycopg2.connect(
            host=parsed.hostname,
            port=parsed.port or 5432,
            user=parsed.username,
            password=parsed.password,
            database=parsed.path[1:] if parsed.path.startswith('/') else parsed.path
        )
        return conn
    except Exception as e:
        print(f"❌ Ошибка подключения к {name}: {e}")
        return None

def move_testers():
    """Переносит всех тестеров из production в sandbox"""
    print("🔄 Перенос тестеров из Production → Sandbox")
    print("=" * 50)
    
    # Получаем URL баз данных
    prod_url = os.environ.get('PRODUCTION_DATABASE_URL')
    sandbox_url = os.environ.get('SANDBOX_DATABASE_URL')
    
    if not prod_url or not sandbox_url:
        print("❌ Необходимо установить переменные окружения:")
        print("   PRODUCTION_DATABASE_URL - URL production базы")
        print("   SANDBOX_DATABASE_URL - URL sandbox базы")
        print("\n💡 Как получить URL:")
        print("   1. Railway → Ваш проект → PostgreSQL")
        print("   2. Вкладка 'Connect'")
        print("   3. Скопируйте 'Public Network' URL")
        return False
    
    # Подключаемся к базам
    prod_conn = get_connection(prod_url, "Production")
    sandbox_conn = get_connection(sandbox_url, "Sandbox")
    
    if not prod_conn or not sandbox_conn:
        return False
    
    try:
        prod_cursor = prod_conn.cursor()
        sandbox_cursor = sandbox_conn.cursor()
        
        # Получаем всех тестеров из production (role = 'tester')
        print("\n📋 Получение списка тестеров из production...")
        prod_cursor.execute("""
            SELECT id, username, password_hash, role, is_active, created_at, last_login
            FROM "Users"
            WHERE role = 'tester'
            ORDER BY id
        """)
        
        testers = prod_cursor.fetchall()
        print(f"✅ Найдено тестеров в production: {len(testers)}")
        
        if len(testers) == 0:
            print("ℹ️  Тестеров для переноса не найдено")
            return True
        
        # Проверяем, существует ли таблица Users в sandbox
        sandbox_cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'Users'
            )
        """)
        table_exists = sandbox_cursor.fetchone()[0]
        
        if not table_exists:
            print("❌ Таблица 'Users' не существует в sandbox!")
            print("💡 Сначала создайте структуру базы данных в sandbox")
            return False
        
        # Получаем существующих пользователей в sandbox (чтобы не дублировать)
        sandbox_cursor.execute("SELECT username FROM \"Users\"")
        existing_usernames = {row[0] for row in sandbox_cursor.fetchall()}
        
        # Переносим тестеров
        moved_count = 0
        skipped_count = 0
        updated_count = 0
        
        print(f"\n📦 Перенос тестеров в sandbox...")
        for tester in testers:
            user_id, username, password_hash, role, is_active, created_at, last_login = tester
            
            if username in existing_usernames:
                # Пользователь уже существует - обновляем данные
                print(f"  🔄 Обновление: {username}")
                sandbox_cursor.execute("""
                    UPDATE "Users"
                    SET password_hash = %s,
                        role = %s,
                        is_active = %s,
                        created_at = %s,
                        last_login = %s
                    WHERE username = %s
                """, (password_hash, role, is_active, created_at, last_login, username))
                updated_count += 1
            else:
                # Создаем нового пользователя
                print(f"  ➕ Создание: {username}")
                sandbox_cursor.execute("""
                    INSERT INTO "Users" (username, password_hash, role, is_active, created_at, last_login)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (username, password_hash, role, is_active, created_at, last_login))
                moved_count += 1
        
        # Удаляем тестеров из production (только тестеров, не создателей!)
        print(f"\n🗑️  Удаление тестеров из production...")
        prod_cursor.execute("""
            DELETE FROM "Users"
            WHERE role = 'tester'
        """)
        deleted_count = prod_cursor.rowcount
        
        # Коммитим изменения
        sandbox_conn.commit()
        prod_conn.commit()
        
        print("\n" + "=" * 50)
        print("✅ Перенос завершен!")
        print(f"   ➕ Создано в sandbox: {moved_count}")
        print(f"   🔄 Обновлено в sandbox: {updated_count}")
        print(f"   🗑️  Удалено из production: {deleted_count}")
        print(f"   ⏭️  Пропущено: {skipped_count}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Ошибка при переносе тестеров: {e}")
        import traceback
        traceback.print_exc()
        prod_conn.rollback()
        sandbox_conn.rollback()
        return False
    finally:
        if prod_conn:
            prod_conn.close()
        if sandbox_conn:
            sandbox_conn.close()

if __name__ == '__main__':
    success = move_testers()
    sys.exit(0 if success else 1)

"""
Скрипт для переноса всех тестеров из production в sandbox
Использование:
    export PRODUCTION_DATABASE_URL="postgresql://..."
    export SANDBOX_DATABASE_URL="postgresql://..."
    python scripts/move_testers_to_sandbox.py
"""
import os
import sys
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from psycopg2.extras import execute_values
from urllib.parse import urlparse
from werkzeug.security import generate_password_hash

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)

def get_connection(database_url, name="database"):
    """Подключение к базе данных"""
    if not database_url:
        print(f"❌ {name} URL не установлен")
        return None
    
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    
    try:
        parsed = urlparse(database_url)
        conn = psycopg2.connect(
            host=parsed.hostname,
            port=parsed.port or 5432,
            user=parsed.username,
            password=parsed.password,
            database=parsed.path[1:] if parsed.path.startswith('/') else parsed.path
        )
        return conn
    except Exception as e:
        print(f"❌ Ошибка подключения к {name}: {e}")
        return None

def move_testers():
    """Переносит всех тестеров из production в sandbox"""
    print("🔄 Перенос тестеров из Production → Sandbox")
    print("=" * 50)
    
    # Получаем URL баз данных
    prod_url = os.environ.get('PRODUCTION_DATABASE_URL')
    sandbox_url = os.environ.get('SANDBOX_DATABASE_URL')
    
    if not prod_url or not sandbox_url:
        print("❌ Необходимо установить переменные окружения:")
        print("   PRODUCTION_DATABASE_URL - URL production базы")
        print("   SANDBOX_DATABASE_URL - URL sandbox базы")
        print("\n💡 Как получить URL:")
        print("   1. Railway → Ваш проект → PostgreSQL")
        print("   2. Вкладка 'Connect'")
        print("   3. Скопируйте 'Public Network' URL")
        return False
    
    # Подключаемся к базам
    prod_conn = get_connection(prod_url, "Production")
    sandbox_conn = get_connection(sandbox_url, "Sandbox")
    
    if not prod_conn or not sandbox_conn:
        return False
    
    try:
        prod_cursor = prod_conn.cursor()
        sandbox_cursor = sandbox_conn.cursor()
        
        # Получаем всех тестеров из production (role = 'tester')
        print("\n📋 Получение списка тестеров из production...")
        prod_cursor.execute("""
            SELECT id, username, password_hash, role, is_active, created_at, last_login
            FROM "Users"
            WHERE role = 'tester'
            ORDER BY id
        """)
        
        testers = prod_cursor.fetchall()
        print(f"✅ Найдено тестеров в production: {len(testers)}")
        
        if len(testers) == 0:
            print("ℹ️  Тестеров для переноса не найдено")
            return True
        
        # Проверяем, существует ли таблица Users в sandbox
        sandbox_cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'Users'
            )
        """)
        table_exists = sandbox_cursor.fetchone()[0]
        
        if not table_exists:
            print("❌ Таблица 'Users' не существует в sandbox!")
            print("💡 Сначала создайте структуру базы данных в sandbox")
            return False
        
        # Получаем существующих пользователей в sandbox (чтобы не дублировать)
        sandbox_cursor.execute("SELECT username FROM \"Users\"")
        existing_usernames = {row[0] for row in sandbox_cursor.fetchall()}
        
        # Переносим тестеров
        moved_count = 0
        skipped_count = 0
        updated_count = 0
        
        print(f"\n📦 Перенос тестеров в sandbox...")
        for tester in testers:
            user_id, username, password_hash, role, is_active, created_at, last_login = tester
            
            if username in existing_usernames:
                # Пользователь уже существует - обновляем данные
                print(f"  🔄 Обновление: {username}")
                sandbox_cursor.execute("""
                    UPDATE "Users"
                    SET password_hash = %s,
                        role = %s,
                        is_active = %s,
                        created_at = %s,
                        last_login = %s
                    WHERE username = %s
                """, (password_hash, role, is_active, created_at, last_login, username))
                updated_count += 1
            else:
                # Создаем нового пользователя
                print(f"  ➕ Создание: {username}")
                sandbox_cursor.execute("""
                    INSERT INTO "Users" (username, password_hash, role, is_active, created_at, last_login)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (username, password_hash, role, is_active, created_at, last_login))
                moved_count += 1
        
        # Удаляем тестеров из production (только тестеров, не создателей!)
        print(f"\n🗑️  Удаление тестеров из production...")
        prod_cursor.execute("""
            DELETE FROM "Users"
            WHERE role = 'tester'
        """)
        deleted_count = prod_cursor.rowcount
        
        # Коммитим изменения
        sandbox_conn.commit()
        prod_conn.commit()
        
        print("\n" + "=" * 50)
        print("✅ Перенос завершен!")
        print(f"   ➕ Создано в sandbox: {moved_count}")
        print(f"   🔄 Обновлено в sandbox: {updated_count}")
        print(f"   🗑️  Удалено из production: {deleted_count}")
        print(f"   ⏭️  Пропущено: {skipped_count}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Ошибка при переносе тестеров: {e}")
        import traceback
        traceback.print_exc()
        prod_conn.rollback()
        sandbox_conn.rollback()
        return False
    finally:
        if prod_conn:
            prod_conn.close()
        if sandbox_conn:
            sandbox_conn.close()

if __name__ == '__main__':
    success = move_testers()
    sys.exit(0 if success else 1)

