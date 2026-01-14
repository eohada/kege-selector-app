#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для переноса данных из старых баз в новые централизованные базы Railway
Использование:
    # Для production:
    export OLD_PRODUCTION_DATABASE_URL="postgresql://..."  # Старая база
    export NEW_PRODUCTION_DATABASE_URL="postgresql://..."  # Новая централизованная база
    python scripts/migrate_to_centralized_db.py production
    
    # Для sandbox:
    export OLD_SANDBOX_DATABASE_URL="postgresql://..."
    export NEW_SANDBOX_DATABASE_URL="postgresql://..."
    python scripts/migrate_to_centralized_db.py sandbox
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
    """Нормализует URL базы данных"""
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
            database=parsed.path[1:] if parsed.path.startswith('/') else parsed.path,
            connect_timeout=10
        )
        if readonly:
            conn.set_session(readonly=True, autocommit=True)
        return conn
    except Exception as e:
        print(f"❌ Ошибка подключения к {name}: {e}")
        return None

def create_tables_if_not_exist(new_conn):
    """Создает структуру таблиц в новой базе, если их нет"""
    print("\n📋 Проверка структуры таблиц в новой базе...")
    
    try:
        # Импортируем Flask app для создания таблиц через SQLAlchemy
        sys.path.insert(0, project_root)
        os.chdir(project_root)
        
        from app import create_app, db
        
        app = create_app()
        with app.app_context():
            # Создаем все таблицы
            db.create_all()
            print("✅ Структура таблиц создана/проверена")
            
            # Применяем дополнительные миграции, если есть
            try:
                from app import ensure_schema_columns
                ensure_schema_columns()
                print("✅ Дополнительные миграции применены")
            except Exception as e:
                print(f"⚠️  Предупреждение при применении миграций: {e}")
        
        return True
    except Exception as e:
        print(f"❌ Ошибка создания структуры: {e}")
        import traceback
        traceback.print_exc()
        return False

def migrate_table(old_conn, new_conn, table_name, primary_key='id', exclude_columns=None):
    """Переносит данные одной таблицы из старой базы в новую"""
    exclude_columns = exclude_columns or []
    
    print(f"\n📋 Перенос таблицы: {table_name}")
    
    try:
        old_cursor = old_conn.cursor()
        
        # Проверяем, существует ли таблица в старой базе
        old_cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = %s
            )
        """, (table_name,))
        if not old_cursor.fetchone()[0]:
            print(f"  ⚠️  Таблица {table_name} не найдена в старой базе, пропускаем")
            return 0
        
        # Получаем структуру таблицы
        old_cursor.execute(f"""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = '{table_name}' 
            AND table_schema = 'public'
            ORDER BY ordinal_position
        """)
        columns = [row[0] for row in old_cursor.fetchall() if row[0] not in exclude_columns]
        
        if not columns:
            print(f"  ⚠️  Таблица {table_name} не имеет колонок")
            return 0
        
        # Получаем данные из старой базы
        columns_str = ', '.join([f'"{col}"' for col in columns])
        old_cursor.execute(f'SELECT {columns_str} FROM "{table_name}"')
        rows = old_cursor.fetchall()
        
        if not rows:
            print(f"  ℹ️  Нет данных для переноса")
            return 0
        
        print(f"  📊 Найдено записей: {len(rows)}")
        
        # Проверяем, существует ли таблица в новой базе
        new_cursor = new_conn.cursor()
        new_cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = %s
            )
        """, (table_name,))
        if not new_cursor.fetchone()[0]:
            print(f"  ⚠️  Таблица {table_name} не найдена в новой базе, пропускаем")
            return 0
        
        # Очищаем таблицу в новой базе (опционально)
        # Закомментируйте следующую строку, если хотите добавить данные, а не заменить
        new_cursor.execute(f'TRUNCATE TABLE "{table_name}" CASCADE')
        print(f"  🗑️  Таблица очищена")
        
        # Вставляем данные в новую базу
        if primary_key in columns:
            pk_index = columns.index(primary_key)
            # Используем ON CONFLICT для обновления существующих записей
            update_cols = ', '.join([f'"{col}" = EXCLUDED."{col}"' for col in columns if col != primary_key])
            execute_values(
                new_cursor,
                f'INSERT INTO "{table_name}" ({columns_str}) VALUES %s ON CONFLICT ("{primary_key}") DO UPDATE SET {update_cols}',
                rows
            )
        else:
            execute_values(
                new_cursor,
                f'INSERT INTO "{table_name}" ({columns_str}) VALUES %s',
                rows
            )
        
        new_conn.commit()
        print(f"  ✅ Перенесено {len(rows)} записей")
        return len(rows)
        
    except Exception as e:
        new_conn.rollback()
        print(f"  ❌ Ошибка переноса {table_name}: {e}")
        import traceback
        traceback.print_exc()
        return 0

def fix_sequences(new_conn, tables):
    """Исправляет sequences после переноса данных"""
    print("\n🔧 Исправление sequences...")
    
    new_cursor = new_conn.cursor()
    
    for table_name, primary_key in tables:
        try:
            # Получаем максимальный ID
            new_cursor.execute(f'SELECT MAX("{primary_key}") FROM "{table_name}"')
            max_id = new_cursor.fetchone()[0]
            max_id = int(max_id) if max_id is not None else 0

            # Получаем имя sequence
            new_cursor.execute(
                "SELECT pg_get_serial_sequence(%s, %s)",
                (f'"{table_name}"', primary_key)
            )
            seq_result = new_cursor.fetchone()
            
            if not seq_result or not seq_result[0]:
                print(f"  ⚠️  {table_name}: sequence не найден (возможно, не SERIAL/IDENTITY)")
                continue

            seq_name = seq_result[0]

            if max_id <= 0:
                new_cursor.execute("SELECT setval(%s, %s, false)", (seq_name, 1))
                new_conn.commit()
                print(f"  ✅ {table_name}: sequence '{seq_name}' установлен на 1")
            else:
                new_cursor.execute("SELECT setval(%s, %s, true)", (seq_name, max_id + 1))
                new_conn.commit()
                print(f"  ✅ {table_name}: sequence '{seq_name}' установлен на {max_id + 1}")
        except Exception as e:
            new_conn.rollback()
            print(f"  ⚠️  {table_name}: не удалось обновить sequence ({e})")

def migrate_environment(env_name):
    """Переносит данные для указанного окружения"""
    print("=" * 70)
    print(f"ПЕРЕНОС ДАННЫХ ДЛЯ ОКРУЖЕНИЯ: {env_name.upper()}")
    print("=" * 70)
    
    # Определяем переменные окружения в зависимости от окружения
    if env_name.lower() == 'production':
        old_url_var = 'OLD_PRODUCTION_DATABASE_URL'
        new_url_var = 'NEW_PRODUCTION_DATABASE_URL'
    elif env_name.lower() == 'sandbox':
        old_url_var = 'OLD_SANDBOX_DATABASE_URL'
        new_url_var = 'NEW_SANDBOX_DATABASE_URL'
    else:
        print(f"❌ Неизвестное окружение: {env_name}")
        print("   Используйте: production или sandbox")
        return False
    
    old_url = os.environ.get(old_url_var)
    new_url = os.environ.get(new_url_var)
    
    if not old_url or not new_url:
        print(f"❌ Необходимо установить переменные окружения:")
        print(f"   {old_url_var} - URL старой базы данных")
        print(f"   {new_url_var} - URL новой централизованной базы")
        return False
    
    if _normalize_url(old_url) == _normalize_url(new_url):
        print("❌ Старая и новая базы совпадают. Остановлено для безопасности.")
        return False
    
    # Подключаемся к базам
    old_conn = get_connection(old_url, f"Старая {env_name}", readonly=True)
    new_conn = get_connection(new_url, f"Новая {env_name}", readonly=False)
    
    if not old_conn or not new_conn:
        return False
    
    try:
        # Создаем структуру таблиц в новой базе
        if not create_tables_if_not_exist(new_conn):
            print("⚠️  Продолжаем без создания структуры...")
        
        # Список таблиц для переноса (в порядке зависимостей)
        tables = [
            ('Tasks', 'task_id'),
            ('Topics', 'topic_id'),
            ('Students', 'student_id'),
            ('Users', 'id'),
            ('UserProfiles', 'id'),
            ('Lessons', 'lesson_id'),
            ('LessonTasks', 'lesson_task_id'),
            ('UsageHistory', 'usage_id'),
            ('SkippedTasks', 'skipped_id'),
            ('BlacklistTasks', 'blacklist_id'),
            ('StudentTaskStatistics', 'id'),
            ('FamilyTie', 'id'),
            ('Enrollment', 'id'),
            ('Assignment', 'id'),
            ('AssignmentTask', 'id'),
            ('Submission', 'id'),
            ('Answer', 'id'),
            ('Reminder', 'id'),
            ('TaskTemplate', 'id'),
            ('TemplateTask', 'id'),
            ('Tester', 'id'),
            ('AuditLog', 'id'),
        ]
        
        # Таблицы, которые НЕ переносим (опционально)
        exclude_tables = []  # Можно добавить таблицы, которые не нужно переносить
        
        total_migrated = 0
        
        for table_name, primary_key in tables:
            if table_name not in exclude_tables:
                count = migrate_table(old_conn, new_conn, table_name, primary_key)
                total_migrated += count
        
        # Исправляем sequences
        fix_sequences(new_conn, tables)
        
        print("\n" + "=" * 70)
        print(f"✅ Перенос завершен! Всего записей: {total_migrated}")
        print(f"📅 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)
        
        return True
        
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        old_conn.close()
        new_conn.close()

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Использование:")
        print("  python scripts/migrate_to_centralized_db.py <environment>")
        print()
        print("Примеры:")
        print("  python scripts/migrate_to_centralized_db.py production")
        print("  python scripts/migrate_to_centralized_db.py sandbox")
        sys.exit(1)
    
    env_name = sys.argv[1]
    success = migrate_environment(env_name)
    sys.exit(0 if success else 1)
