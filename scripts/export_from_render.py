#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Скрипт для экспорта данных из Render PostgreSQL базы данных
Используй этот скрипт перед миграцией на Beget
"""

import os
import sys
import psycopg2
from urllib.parse import urlparse

def export_database():
    """Экспортирует данные из Render PostgreSQL"""
    
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        print("❌ DATABASE_URL не установлен в переменных окружения")
        print("Установи переменную: export DATABASE_URL='postgresql://...'")
        return False
    
    # Исправляем postgres:// на postgresql://
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
        
        print("✅ Подключение к базе данных установлено")
        
        cursor = conn.cursor()
        
        # Получаем список таблиц
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        
        tables = [row[0] for row in cursor.fetchall()]
        print(f"📋 Найдено таблиц: {len(tables)}")
        for table in tables:
            print(f"  - {table}")
        
        # Экспортируем данные из каждой таблицы
        export_dir = "render_export"
        os.makedirs(export_dir, exist_ok=True)
        
        for table in tables:
            print(f"\n📦 Экспорт таблицы {table}...")
            
            # Получаем данные
            cursor.execute(f"SELECT * FROM \"{table}\"")
            rows = cursor.fetchall()
            
            # Получаем названия колонок
            column_names = [desc[0] for desc in cursor.description]
            
            # Сохраняем в CSV
            import csv
            csv_file = os.path.join(export_dir, f"{table}.csv")
            with open(csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(column_names)
                writer.writerows(rows)
            
            print(f"  ✅ Экспортировано {len(rows)} записей в {csv_file}")
        
        conn.close()
        print(f"\n✅ Экспорт завершен! Данные сохранены в директории {export_dir}/")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка при экспорте: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    print("🚀 Начало экспорта данных из Render...")
    success = export_database()
    if success:
        print("\n✅ Готово! Теперь можно импортировать данные на Beget")
    else:
        print("\n❌ Экспорт не удался. Проверь ошибки выше.")
        sys.exit(1)



