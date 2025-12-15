#!/usr/bin/env python3
"""
Скрипт для создания таблиц TaskTemplates и TemplateTasks в production базе данных
Использование:
    $env:PRODUCTION_DATABASE_URL="postgresql://..."
    python scripts/create_tables_in_production.py
"""
import os
import sys
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from urllib.parse import urlparse

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)

def get_connection(database_url):
    """Подключение к базе данных"""
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
        print(f"❌ Ошибка подключения: {e}")
        return None

def create_tables(conn):
    """Создание таблиц для шаблонов"""
    cursor = conn.cursor()
    
    try:
        # Проверяем, существует ли таблица TaskTemplates
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'TaskTemplates'
            );
        """)
        task_templates_exists = cursor.fetchone()[0]
        
        if not task_templates_exists:
            print("📋 Создание таблицы TaskTemplates...")
            cursor.execute("""
                CREATE TABLE "TaskTemplates" (
                    template_id SERIAL PRIMARY KEY,
                    name VARCHAR(200) NOT NULL,
                    description TEXT,
                    template_type VARCHAR(20) NOT NULL,
                    category VARCHAR(50),
                    created_by INTEGER REFERENCES "Users"(id),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE
                );
            """)
            print("✅ Таблица TaskTemplates создана")
        else:
            print("ℹ️  Таблица TaskTemplates уже существует")
        
        # Проверяем, существует ли таблица TemplateTasks
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'TemplateTasks'
            );
        """)
        template_tasks_exists = cursor.fetchone()[0]
        
        if not template_tasks_exists:
            print("📋 Создание таблицы TemplateTasks...")
            cursor.execute("""
                CREATE TABLE "TemplateTasks" (
                    template_task_id SERIAL PRIMARY KEY,
                    template_id INTEGER NOT NULL REFERENCES "TaskTemplates"(template_id) ON DELETE CASCADE,
                    task_id INTEGER NOT NULL REFERENCES "Tasks"(task_id) ON DELETE CASCADE,
                    "order" INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            print("✅ Таблица TemplateTasks создана")
        else:
            print("ℹ️  Таблица TemplateTasks уже существует")
        
        # Создаем индексы для производительности
        print("📋 Создание индексов...")
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_template_tasks_template_id ON "TemplateTasks"(template_id);')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_template_tasks_task_id ON "TemplateTasks"(task_id);')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_task_templates_type ON "TaskTemplates"(template_type);')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_task_templates_category ON "TaskTemplates"(category);')
            print("✅ Индексы созданы")
        except Exception as e:
            print(f"⚠️  Ошибка при создании индексов (возможно, уже существуют): {e}")
        
        conn.commit()
        print("\n✅ Все таблицы успешно созданы в production базе данных!")
        return True
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Ошибка при создании таблиц: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        cursor.close()

if __name__ == '__main__':
    print("🔧 Создание таблиц для библиотеки шаблонов в production...")
    print("=" * 60)
    
    production_url = os.environ.get('PRODUCTION_DATABASE_URL')
    if not production_url:
        print("❌ Переменная окружения PRODUCTION_DATABASE_URL не установлена")
        print("   Установите её командой:")
        print('   $env:PRODUCTION_DATABASE_URL="postgresql://..."')
        sys.exit(1)
    
    conn = get_connection(production_url)
    if not conn:
        sys.exit(1)
    
    try:
        success = create_tables(conn)
        if not success:
            sys.exit(1)
    finally:
        conn.close()
    
    print("=" * 60)
    print("✅ Готово!")












