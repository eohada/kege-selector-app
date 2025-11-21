
import os
import sys
import sqlite3
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from urllib.parse import urlparse

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)

def get_sqlite_connection():

    db_path = os.path.join(project_root, 'data', 'keg_tasks.db')
    if not os.path.exists(db_path):
        print(f"❌ Локальная БД не найдена: {db_path}")
        return None
    return sqlite3.connect(db_path)

def get_postgres_connection():

    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        print("❌ DATABASE_URL не установлен в переменных окружения")
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
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        return conn
    except Exception as e:
        print(f"❌ Ошибка подключения к PostgreSQL: {e}")
        return None

def table_exists(pg_cursor, table_name):
    pg_cursor.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name = %s
        );
    """, (table_name,))
    return pg_cursor.fetchone()[0]

def copy_table_data(sqlite_conn, pg_conn, table_name):

    sqlite_cursor = sqlite_conn.cursor()
    pg_cursor = pg_conn.cursor()

    try:

        if not table_exists(pg_cursor, table_name):
            print(f"  ⚠️  Таблица {table_name} не существует в PostgreSQL, пропускаем")
            return 0

        sqlite_cursor.execute(f"SELECT * FROM {table_name}")
        rows = sqlite_cursor.fetchall()

        if not rows:
            print(f"  ⚠️  Таблица {table_name} пуста в SQLite, пропускаем")
            return 0

        sqlite_cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [col[1] for col in sqlite_cursor.fetchall()]
        columns_str = ', '.join([f'"{col}"' for col in columns])
        placeholders = ', '.join(['%s'] * len(columns))

        pg_cursor.execute(f'TRUNCATE TABLE "{table_name}" CASCADE')

        insert_query = f'INSERT INTO "{table_name}" ({columns_str}) VALUES ({placeholders})'
        pg_cursor.executemany(insert_query, rows)

        pg_conn.commit()
        print(f"  ✅ Скопировано {len(rows)} записей из {table_name}")
        return len(rows)
    except Exception as e:
        pg_conn.rollback()
        print(f"  ❌ Ошибка при копировании {table_name}: {e}")
        import traceback
        traceback.print_exc()
        return 0

def init_staging_db():

    print("🚀 Начало инициализации staging базы данных...")

    sqlite_conn = get_sqlite_connection()
    if not sqlite_conn:
        return False

    pg_conn = get_postgres_connection()
    if not pg_conn:
        sqlite_conn.close()
        return False

    try:

        sys.path.insert(0, project_root)
        os.chdir(project_root)

        from app import app, db
        with app.app_context():
            print("📋 Создание структуры таблиц...")
            db.create_all()
            print("✅ Структура таблиц создана")

            from app import ensure_schema_columns
            ensure_schema_columns()
            print("✅ Миграции применены")

        print("\n📦 Копирование данных...")
        tables = ['Tasks', 'Students', 'Lessons', 'LessonTasks', 'UsageHistory', 'SkippedTasks', 'BlacklistTasks']
        total_copied = 0

        for table in tables:
            count = copy_table_data(sqlite_conn, pg_conn, table)
            total_copied += count

        print(f"\n✅ Инициализация завершена! Всего скопировано записей: {total_copied}")
        return True

    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        sqlite_conn.close()
        pg_conn.close()

if __name__ == '__main__':
    success = init_staging_db()
    sys.exit(0 if success else 1)
