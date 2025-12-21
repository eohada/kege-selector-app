#!/usr/bin/env python3
"""
Скрипт для синхронизации данных из production в sandbox
Использование:
    export PRODUCTION_DATABASE_URL="postgresql://..."
    export SANDBOX_DATABASE_URL="postgresql://..."
    python scripts/sync_to_sandbox.py
"""
import os
import sys
import psycopg2
from psycopg2.extras import execute_values
from urllib.parse import urlparse
from datetime import datetime

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)

def _normalize_url(database_url: str) -> str:
    if not database_url:
        return ''
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    return database_url.strip()


def get_connection(database_url, name="database", readonly=False):
    """Подключение к базе данных"""
    database_url = _normalize_url(database_url)

    if not database_url:
        print(f"❌ {name} URL не установлен")
        return None
    
    try:
        parsed = urlparse(database_url)
        conn = psycopg2.connect(
            host=parsed.hostname,
            port=parsed.port or 5432,
            user=parsed.username,
            password=parsed.password,
            database=parsed.path[1:] if parsed.path.startswith('/') else parsed.path
        )
        if readonly:
            conn.set_session(readonly=True, autocommit=True)
        return conn
    except Exception as e:
        print(f"❌ Ошибка подключения к {name}: {e}")
        return None

def sync_table(prod_conn, sandbox_conn, table_name, primary_key='id', exclude_columns=None):
    """Синхронизация одной таблицы"""
    exclude_columns = exclude_columns or []
    
    print(f"\n📋 Синхронизация таблицы: {table_name}")
    
    try:
        # Получаем структуру таблицы
        prod_cursor = prod_conn.cursor()
        prod_cursor.execute(f"""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = '{table_name}' 
            ORDER BY ordinal_position
        """)
        columns = [row[0] for row in prod_cursor.fetchall() if row[0] not in exclude_columns]
        
        if not columns:
            print(f"  ⚠️  Таблица {table_name} не найдена или пуста")
            return 0
        
        # Получаем данные из production
        columns_str = ', '.join(columns)
        prod_cursor.execute(f"SELECT {columns_str} FROM \"{table_name}\"")
        rows = prod_cursor.fetchall()
        
        if not rows:
            print(f"  ℹ️  Нет данных для синхронизации")
            return 0
        
        # Очищаем таблицу в sandbox (опционально, можно закомментировать для инкрементальной синхронизации)
        sandbox_cursor = sandbox_conn.cursor()
        sandbox_cursor.execute(f'TRUNCATE TABLE "{table_name}" CASCADE')
        
        # Вставляем данные в sandbox
        if primary_key in columns:
            pk_index = columns.index(primary_key)
            # Используем execute_values для быстрой вставки
            execute_values(
                sandbox_cursor,
                f'INSERT INTO "{table_name}" ({columns_str}) VALUES %s ON CONFLICT ({primary_key}) DO UPDATE SET ' + 
                ', '.join([f'"{col}" = EXCLUDED."{col}"' for col in columns if col != primary_key]),
                rows
            )
        else:
            execute_values(
                sandbox_cursor,
                f'INSERT INTO "{table_name}" ({columns_str}) VALUES %s',
                rows
            )
        
        sandbox_conn.commit()
        print(f"  ✅ Синхронизировано {len(rows)} записей")
        return len(rows)
        
    except Exception as e:
        sandbox_conn.rollback()
        print(f"  ❌ Ошибка синхронизации {table_name}: {e}")
        return 0

def sync_databases(prod_url=None, sandbox_url=None, include_users=False):
    """Основная функция синхронизации"""
    print("🔄 Синхронизация Production → Sandbox")
    print("=" * 50)
    
    # Получаем URL баз данных
    prod_url = prod_url or os.environ.get('PRODUCTION_DATABASE_URL')
    sandbox_url = sandbox_url or os.environ.get('SANDBOX_DATABASE_URL')

    prod_url_norm = _normalize_url(prod_url or '')
    sandbox_url_norm = _normalize_url(sandbox_url or '')
    
    if not prod_url_norm or not sandbox_url_norm:
        print("❌ Необходимо установить переменные окружения:")
        print("   PRODUCTION_DATABASE_URL - URL production базы")
        print("   SANDBOX_DATABASE_URL - URL sandbox базы")
        print("\n💡 Как получить URL:")
        print("   1. Railway → Ваш проект → PostgreSQL")
        print("   2. Вкладка 'Connect'")
        print("   3. Скопируйте 'Public Network' URL")
        return False

    if prod_url_norm == sandbox_url_norm:
        print("❌ PRODUCTION_DATABASE_URL и SANDBOX_DATABASE_URL совпадают. Остановлено для безопасности.")
        return False
    
    # Подключаемся к базам
    prod_conn = get_connection(prod_url_norm, "Production", readonly=True)
    sandbox_conn = get_connection(sandbox_url_norm, "Sandbox", readonly=False)
    
    if not prod_conn or not sandbox_conn:
        return False
    
    try:
        # Список таблиц для синхронизации (в порядке зависимостей)
        tables = [
            ('Tasks', 'task_id'),
            ('Students', 'student_id'),
            ('Lessons', 'lesson_id'),
            ('LessonTasks', 'lesson_task_id'),
            ('UsageHistory', 'usage_id'),
            ('SkippedTasks', 'skipped_id'),
            ('BlacklistTasks', 'blacklist_id'),
        ]

        # Users синкать опасно: это снесёт sandbox тестировщиков (логины/пароли) и оставит только продовых.
        # Поэтому по умолчанию Users НЕ синхронизируем. Включается явно через include_users=True.
        if include_users:
            tables.insert(2, ('Users', 'id'))
        
        # Таблицы, которые НЕ синхронизируем (логи, временные данные)
        exclude_tables = ['AuditLog', 'Testers']  # Логи не синхронизируем
        
        total_synced = 0
        
        for table_name, primary_key in tables:
            if table_name not in exclude_tables:
                count = sync_table(prod_conn, sandbox_conn, table_name, primary_key)
                total_synced += count
        
        # Исправляем sequences после синхронизации
        print("\n🔧 Исправление sequences...")
        sandbox_cursor = sandbox_conn.cursor()
        
        for table_name, primary_key in tables:
            try:
                sandbox_cursor.execute(f'SELECT MAX("{primary_key}") FROM "{table_name}"')
                max_id = sandbox_cursor.fetchone()[0]
                max_id = int(max_id) if max_id is not None else 0

                sandbox_cursor.execute(
                    "SELECT pg_get_serial_sequence(%s, %s)",
                    (f'"{table_name}"', primary_key)
                )
                seq_name = sandbox_cursor.fetchone()[0]

                if not seq_name:
                    print(f"  ⚠️  {table_name}: sequence не найден (возможно, не SERIAL/IDENTITY)")
                    continue

                if max_id <= 0:
                    sandbox_cursor.execute("SELECT setval(%s, %s, false)", (seq_name, 1))
                    sandbox_conn.commit()
                    print(f"  ✅ {table_name}: sequence '{seq_name}' установлен на 1")
                else:
                    sandbox_cursor.execute("SELECT setval(%s, %s, true)", (seq_name, max_id))
                    sandbox_conn.commit()
                    print(f"  ✅ {table_name}: sequence '{seq_name}' установлен на {max_id}")
            except Exception as e:
                sandbox_conn.rollback()
                print(f"  ⚠️  {table_name}: не удалось обновить sequence ({e})")
        
        print("\n" + "=" * 50)
        print(f"✅ Синхронизация завершена! Всего записей: {total_synced}")
        print(f"📅 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        prod_conn.close()
        sandbox_conn.close()

if __name__ == '__main__':
    success = sync_databases()
    sys.exit(0 if success else 1)
