"""
Скрипт для синхронизации локальной SQLite базы с production PostgreSQL
Использование:
    export PRODUCTION_DATABASE_URL="postgresql://..."
    python scripts/sync_local_from_production.py
"""
import os
import sys
import sqlite3
import psycopg2
from psycopg2.extras import execute_values
from urllib.parse import urlparse
from datetime import datetime

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)

def get_postgres_connection():
    """Подключение к production PostgreSQL"""
    database_url = os.environ.get('PRODUCTION_DATABASE_URL')
    if not database_url:
        print("❌ PRODUCTION_DATABASE_URL не установлен")
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
        print(f"❌ Ошибка подключения к production: {e}")
        return None

def get_sqlite_connection():
    """Подключение к локальной SQLite базе"""
    db_path = os.path.join(project_root, 'data', 'keg_tasks.db')
    
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    conn.execute('PRAGMA foreign_keys = ON')
    return conn

def sync_table(pg_conn, sqlite_conn, table_name, primary_key='id', disable_fk=True):
    """Синхронизация одной таблицы из PostgreSQL в SQLite"""
    print(f"\n📋 Синхронизация таблицы: {table_name}")
    
    try:
        pg_cursor = pg_conn.cursor()
        pg_cursor.execute(f"""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = '{table_name}' 
            ORDER BY ordinal_position
        """)
        columns = [row[0] for row in pg_cursor.fetchall()]
        
        if not columns:
            print(f"  ⚠️  Таблица {table_name} не найдена в production")
            return 0
        
        columns_str = ', '.join(columns)
        pg_cursor.execute(f'SELECT {columns_str} FROM "{table_name}"')
        rows = pg_cursor.fetchall()
        
        if not rows:
            print(f"  ℹ️  Нет данных для синхронизации")
            return 0
        
        sqlite_cursor = sqlite_conn.cursor()
        
        sqlite_cursor.execute(f"""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='{table_name}'
        """)
        if not sqlite_cursor.fetchone():
            print(f"  ⚠️  Таблица {table_name} не существует в локальной БД, пропускаем")
            return 0
        
        if disable_fk:
            sqlite_cursor.execute('PRAGMA foreign_keys = OFF')
        
        sqlite_cursor.execute(f'DELETE FROM "{table_name}"')
        
        placeholders = ', '.join(['?' for _ in columns])
        insert_sql = f'INSERT OR REPLACE INTO "{table_name}" ({columns_str}) VALUES ({placeholders})'
        
        sqlite_cursor.executemany(insert_sql, rows)
        
        if disable_fk:
            sqlite_cursor.execute('PRAGMA foreign_keys = ON')
        
        sqlite_conn.commit()
        
        print(f"  ✅ Синхронизировано {len(rows)} записей")
        return len(rows)
        
    except Exception as e:
        sqlite_conn.rollback()
        try:
            sqlite_conn.execute('PRAGMA foreign_keys = ON')
        except:
            pass
        print(f"  ❌ Ошибка синхронизации {table_name}: {e}")
        import traceback
        traceback.print_exc()
        return 0

def sync_databases():
    """Основная функция синхронизации"""
    print("🔄 Синхронизация Production PostgreSQL → Локальная SQLite")
    print("=" * 60)
    
    pg_conn = get_postgres_connection()
    if not pg_conn:
        return False
    
    sqlite_conn = get_sqlite_connection()
    
    try:
        tables = [
            ('Tasks', 'task_id'),           # Независимая
            ('Students', 'student_id'),     # Независимая
            ('Lessons', 'lesson_id'),       # Зависит от Students
            ('LessonTasks', 'id'),          # Зависит от Lessons и Tasks
            ('UsageHistory', 'id'),         # Зависит от Tasks и Students
            ('SkippedTasks', 'id'),         # Зависит от Tasks
            ('BlacklistTasks', 'id'),       # Зависит от Tasks
        ]
        
        exclude_tables = ['AuditLog', 'Testers', 'Users']  # Users может не быть в старой локальной БД
        
        total_synced = 0
        
        sqlite_cursor = sqlite_conn.cursor()
        sqlite_cursor.execute('PRAGMA foreign_keys = OFF')
        
        for table_name, primary_key in tables:
            if table_name not in exclude_tables:
                count = sync_table(pg_conn, sqlite_conn, table_name, primary_key, disable_fk=False)
                total_synced += count
        
        sqlite_cursor.execute('PRAGMA foreign_keys = ON')
        sqlite_conn.commit()
        
        print("\n" + "=" * 60)
        print(f"✅ Синхронизация завершена! Всего записей: {total_synced}")
        print(f"📅 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"💾 Локальная база: {os.path.join(project_root, 'data', 'keg_tasks.db')}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        pg_conn.close()
        sqlite_conn.close()

if __name__ == '__main__':
    success = sync_databases()
    sys.exit(0 if success else 1)

