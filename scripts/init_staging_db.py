
import os
import sys
import sqlite3
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from psycopg2.extras import execute_values
from urllib.parse import urlparse
import io

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
    pg_cursor.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND (table_name = %s OR table_name = LOWER(%s))
        );
    """, (table_name, table_name))
    exists = pg_cursor.fetchone()[0]
    if not exists:
        pg_cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = %s
            );
        """, (table_name,))
        exists = pg_cursor.fetchone()[0]
    return exists

def update_sequences(pg_conn):
    """Обновляет sequences в PostgreSQL после копирования данных"""
    pg_cursor = pg_conn.cursor()
    
    sequences_map = {
        'Students': 'student_id',
        'Lessons': 'lesson_id',
        'LessonTasks': 'lesson_task_id',
        'Tasks': 'task_id',
        'UsageHistory': 'usage_id',
        'SkippedTasks': 'skipped_id',
        'BlacklistTasks': 'blacklist_id',
        'Testers': 'tester_id',
        'AuditLog': 'id'
    }
    
    try:
        for table_name, pk_column in sequences_map.items():
            pg_cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND (table_name = %s OR table_name = LOWER(%s))
                );
            """, (table_name, table_name))
            
            if not pg_cursor.fetchone()[0]:
                continue
            
            pg_cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND (table_name = %s OR table_name = LOWER(%s))
                LIMIT 1
            """, (table_name, table_name))
            real_table_name = pg_cursor.fetchone()
            if not real_table_name:
                continue
            real_table_name = real_table_name[0]
            
            pg_cursor.execute(f'SELECT MAX("{pk_column}") FROM "{real_table_name}"')
            max_id = pg_cursor.fetchone()[0]
            
            if max_id is None:
                max_id = 0
            
            sequence_name = f'"{real_table_name}_{pk_column}_seq"'
            try:
                pg_cursor.execute(f'SELECT setval(\'{sequence_name}\', %s, true)', (max_id,))
                pg_conn.commit()
                print(f"  ✅ Обновлена sequence для {table_name}: установлено значение {max_id}")
            except Exception as seq_error:
                alt_sequences = [
                    f'"{real_table_name.lower()}_{pk_column}_seq"',
                    f'"{real_table_name}_{pk_column}_seq"'.lower(),
                    f'{real_table_name}_{pk_column}_seq',
                ]
                updated = False
                for alt_seq in alt_sequences:
                    try:
                        pg_cursor.execute(f'SELECT setval(\'{alt_seq}\', %s, true)', (max_id,))
                        pg_conn.commit()
                        print(f"  ✅ Обновлена sequence {alt_seq} для {table_name}: установлено значение {max_id}")
                        updated = True
                        break
                    except:
                        continue
                if not updated:
                    print(f"  ⚠️  Не удалось обновить sequence для {table_name}: {seq_error}")
            
    except Exception as e:
        pg_conn.rollback()
        print(f"  ⚠️  Ошибка при обновлении sequences: {e}")
        import traceback
        traceback.print_exc()

def copy_table_data(sqlite_conn, pg_conn, table_name, valid_tester_ids=None):

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
        sqlite_columns = {col[1]: col[2] for col in sqlite_cursor.fetchall()}  # name -> type
        sqlite_column_names = list(sqlite_columns.keys())
        
        pg_cursor.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_schema = 'public' 
            AND (table_name = %s OR table_name = LOWER(%s) OR table_name = %s)
            ORDER BY ordinal_position
        """, (table_name, table_name, table_name.lower()))
        pg_columns_info = {row[0]: row[1] for row in pg_cursor.fetchall()}
        pg_column_names = list(pg_columns_info.keys())
        
        matching_columns = []
        column_indices = []
        for idx, col_name in enumerate(sqlite_column_names):
            if col_name.lower() in pg_column_names or col_name in pg_column_names:
                matching_columns.append(col_name)
                column_indices.append(idx)
        
        if not matching_columns:
            print(f"  ⚠️  Нет совпадающих колонок между SQLite и PostgreSQL, пропускаем")
            return 0
        
        skipped_cols = set(sqlite_column_names) - set(matching_columns)
        if skipped_cols:
            print(f"  ⚠️  Пропущены колонки (нет в PostgreSQL): {', '.join(skipped_cols)}")
        
        columns_str = ', '.join([f'"{col}"' for col in matching_columns])
        placeholders = ', '.join(['%s'] * len(matching_columns))

        pg_cursor.execute(f'TRUNCATE TABLE "{table_name}" CASCADE')
        pg_conn.commit()

        print(f"  📊 Всего записей: {len(rows)}, колонок: {len(matching_columns)}")
        print(f"  ⚡ Используем COPY для быстрой вставки...")
        
        import time
        start_time = time.time()
        
        converted_rows = []
        nullified_fk_count = 0
        for row in rows:
            converted_row = []
            row_nullified = False
            
            for idx in column_indices:
                val = row[idx]
                
                col_name = sqlite_column_names[idx]
                pg_col_name = col_name.lower() if col_name.lower() in pg_column_names else col_name
                
                if table_name == 'AuditLog' and pg_col_name == 'tester_id' and val is not None:
                    if valid_tester_ids is not None and val not in valid_tester_ids:
                        val = None
                        if not row_nullified:
                            nullified_fk_count += 1
                            row_nullified = True
                
                if pg_col_name in pg_columns_info:
                    pg_type = pg_columns_info[pg_col_name]
                    if pg_type == 'boolean':
                        if val is None:
                            val = None
                        elif isinstance(val, bool):
                            val = val
                        elif isinstance(val, int):
                            val = bool(val)
                        elif isinstance(val, str):
                            val = val.lower() in ('1', 'true', 'yes', 'on')
                        else:
                            val = bool(val)
                
                elif isinstance(val, str) and ('T' in val or (len(val) > 10 and val[4] == '-' and val[7] == '-')):
                    try:
                        from datetime import datetime
                        if 'T' in val:
                            val = datetime.fromisoformat(val.replace('Z', '+00:00'))
                        else:
                            val = datetime.strptime(val, '%Y-%m-%d %H:%M:%S')
                    except:
                        pass  # Оставляем как строку, если не получилось
                
                if isinstance(val, str) and pg_col_name in pg_columns_info:
                    if 'varying' in pg_columns_info[pg_col_name] or 'character' in pg_columns_info[pg_col_name]:
                        import re
                        match = re.search(r'\((\d+)\)', pg_columns_info[pg_col_name])
                        if match:
                            max_len = int(match.group(1))
                            if len(val) > max_len:
                                val = val[:max_len]
                                print(f"  ⚠️  Обрезано значение в колонке {col_name} до {max_len} символов")
                
                converted_row.append(val)
            
            converted_rows.append(tuple(converted_row))
        
        if nullified_fk_count > 0:
            print(f"  ⚠️  Обнулено {nullified_fk_count} невалидных tester_id в AuditLog")
        
        try:
            insert_query = f'INSERT INTO "{table_name}" ({columns_str}) VALUES %s'
            execute_values(
                pg_cursor,
                insert_query,
                converted_rows,
                template=f'({placeholders})',
                page_size=1000  # Вставляем по 1000 записей за раз
            )
            pg_conn.commit()
            elapsed = time.time() - start_time
            print(f"  ✅ Скопировано {len(rows)} записей за {elapsed:.1f}с ({len(rows)/elapsed:.0f} записей/сек)")
            return len(rows)
        except Exception as copy_error:
            pg_conn.rollback()
            print(f"  ❌ Ошибка при COPY: {copy_error}")
            print(f"  🔄 Пробую использовать обычный INSERT...")
            
            insert_query = f'INSERT INTO "{table_name}" ({columns_str}) VALUES ({placeholders})'
            batch_size = 100
            total_batches = (len(converted_rows) + batch_size - 1) // batch_size
            
            for batch_num, i in enumerate(range(0, len(converted_rows), batch_size), 1):
                batch = converted_rows[i:i + batch_size]
                try:
                    pg_cursor.executemany(insert_query, batch)
                    pg_conn.commit()
                    if batch_num % 10 == 0 or batch_num == total_batches:
                        print(f"  ⏳ Батч {batch_num}/{total_batches}...")
                except Exception as batch_error:
                    pg_conn.rollback()
                    print(f"  ❌ Ошибка в батче {batch_num}: {batch_error}")
                    raise
            
            elapsed = time.time() - start_time
            print(f"  ✅ Скопировано {len(rows)} записей за {elapsed:.1f}с")
            return len(rows)

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
        tables = [
            'Tasks',           # Основные данные
            'Students',         # Ученики
            'Lessons',          # Уроки
            'LessonTasks',      # Связь уроков и заданий
            'UsageHistory',     # История использования
            'SkippedTasks',     # Пропущенные задания
            'BlacklistTasks',   # Черный список
            'Testers',          # Тестировщики (если есть) - ДО AuditLog!
            'AuditLog'          # Логи аудита (если есть) - ПОСЛЕ Testers!
        ]
        total_copied = 0
        
        valid_tester_ids = None

        for idx, table in enumerate(tables, 1):
            print(f"\n[{idx}/{len(tables)}] Обработка таблицы: {table}")
            try:
                if table == 'Testers':
                    count = copy_table_data(sqlite_conn, pg_conn, table)
                    total_copied += count
                    pg_cursor = pg_conn.cursor()
                    pg_cursor.execute('SELECT "tester_id" FROM "Testers"')
                    valid_tester_ids = {row[0] for row in pg_cursor.fetchall()}
                    print(f"  ✅ Загружено {len(valid_tester_ids)} валидных tester_id для проверки внешних ключей")
                elif table == 'AuditLog' and valid_tester_ids is not None:
                    count = copy_table_data(sqlite_conn, pg_conn, table, valid_tester_ids=valid_tester_ids)
                    total_copied += count
                else:
                    count = copy_table_data(sqlite_conn, pg_conn, table)
                    total_copied += count
            except Exception as e:
                print(f"  ❌ Критическая ошибка при копировании {table}: {e}")
                import traceback
                traceback.print_exc()
                print(f"  ⚠️  Продолжаю со следующей таблицей...")
                continue

        print(f"\n🔄 Обновление sequences для автоинкремента...")
        update_sequences(pg_conn)
        
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
