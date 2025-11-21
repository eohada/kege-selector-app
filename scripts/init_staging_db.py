
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
        print("💡 Получи внешний DATABASE_URL из Railway:")
        print("   1. Открой PostgreSQL базу в Railway")
        print("   2. Перейди на вкладку 'Connect' или 'Variables'")
        print("   3. Используй 'Public Network' URL (не 'Private Network')")
        return None

    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)

    # Проверяем, не внутренний ли это URL Railway
    parsed = urlparse(database_url)
    if 'railway.internal' in parsed.hostname or parsed.hostname == 'postgres.railway.internal':
        print("⚠️  Обнаружен внутренний Railway URL (postgres.railway.internal)")
        print("💡 Для подключения с локальной машины нужен внешний URL:")
        print("   1. В Railway открой PostgreSQL базу")
        print("   2. Перейди на вкладку 'Connect'")
        print("   3. Выбери 'Public Network' (не 'Private Network')")
        print("   4. Скопируй Connection URL и используй его")
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
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        return conn
    except Exception as e:
        print(f"❌ Ошибка подключения к PostgreSQL: {e}")
        print(f"💡 Проверь, что используешь внешний URL (Public Network), а не внутренний")
        return None

def table_exists(pg_cursor, table_name):
    # PostgreSQL хранит имена таблиц в нижнем регистре, но может быть и в кавычках
    # Проверяем оба варианта
    pg_cursor.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND (table_name = %s OR table_name = LOWER(%s))
        );
    """, (table_name, table_name))
    exists = pg_cursor.fetchone()[0]
    if not exists:
        # Проверяем с кавычками (чувствительный к регистру)
        pg_cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = %s
            );
        """, (table_name,))
        exists = pg_cursor.fetchone()[0]
    return exists

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

        # Очищаем таблицу перед копированием
        pg_cursor.execute(f'TRUNCATE TABLE "{table_name}" CASCADE')
        pg_conn.commit()

        # Копируем данные порциями для больших таблиц
        insert_query = f'INSERT INTO "{table_name}" ({columns_str}) VALUES ({placeholders})'
        # Для таблицы Tasks с большим HTML контентом используем меньший батч
        batch_size = 50 if table_name == 'Tasks' else 200
        
        total_batches = (len(rows) + batch_size - 1) // batch_size
        print(f"  📊 Всего записей: {len(rows)}, батчей: {total_batches}, размер батча: {batch_size}")
        
        import time
        start_time = time.time()
        
        for batch_num, i in enumerate(range(0, len(rows), batch_size), 1):
            batch_start = time.time()
            batch = rows[i:i + batch_size]
            
            # Конвертируем данные для PostgreSQL
            converted_batch = []
            for row_idx, row in enumerate(batch):
                converted_row = []
                for val in row:
                    # SQLite возвращает datetime как строку, PostgreSQL ожидает datetime объект
                    if isinstance(val, str) and ('T' in val or (len(val) > 10 and val[4] == '-' and val[7] == '-')):
                        try:
                            from datetime import datetime
                            # Пробуем распарсить как datetime
                            if 'T' in val:
                                val = datetime.fromisoformat(val.replace('Z', '+00:00'))
                            else:
                                val = datetime.strptime(val, '%Y-%m-%d %H:%M:%S')
                        except:
                            pass  # Оставляем как строку, если не получилось
                    converted_row.append(val)
                converted_batch.append(tuple(converted_row))
            
            try:
                insert_start = time.time()
                pg_cursor.executemany(insert_query, converted_batch)
                pg_conn.commit()
                batch_time = time.time() - batch_start
                insert_time = time.time() - insert_start
                elapsed = time.time() - start_time
                avg_time = elapsed / batch_num
                remaining = avg_time * (total_batches - batch_num)
                print(f"  ✅ Батч {batch_num}/{total_batches} ({len(batch)} записей) - OK | "
                      f"Время: {batch_time:.1f}с (вставка: {insert_time:.1f}с) | "
                      f"Осталось: ~{remaining/60:.1f} мин")
            except Exception as batch_error:
                pg_conn.rollback()
                print(f"  ❌ Ошибка в батче {batch_num}: {batch_error}")
                # Пробуем вставить по одной записи для диагностики
                if batch_num == 1:
                    print(f"  🔍 Пробую вставить первую запись отдельно для диагностики...")
                    try:
                        pg_cursor.execute(insert_query, converted_batch[0])
                        pg_conn.commit()
                        print(f"  ✅ Первая запись вставлена успешно")
                    except Exception as single_error:
                        print(f"  ❌ Ошибка при вставке первой записи: {single_error}")
                        print(f"  📋 Первая запись: {converted_batch[0][:3]}... (первые 3 поля)")
                raise

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
        # Порядок важен: сначала основные таблицы, потом связанные
        tables = [
            'Tasks',           # Основные данные
            'Students',         # Ученики
            'Lessons',          # Уроки
            'LessonTasks',      # Связь уроков и заданий
            'UsageHistory',     # История использования
            'SkippedTasks',     # Пропущенные задания
            'BlacklistTasks',   # Черный список
            'Testers',          # Тестировщики (если есть)
            'AuditLog'          # Логи аудита (если есть)
        ]
        total_copied = 0

        for idx, table in enumerate(tables, 1):
            print(f"\n[{idx}/{len(tables)}] Обработка таблицы: {table}")
            try:
                count = copy_table_data(sqlite_conn, pg_conn, table)
                total_copied += count
            except Exception as e:
                print(f"  ❌ Критическая ошибка при копировании {table}: {e}")
                import traceback
                traceback.print_exc()
                print(f"  ⚠️  Продолжаю со следующей таблицей...")
                continue

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
