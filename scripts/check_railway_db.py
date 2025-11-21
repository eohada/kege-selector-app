#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Скрипт для проверки данных в Railway PostgreSQL БД"""

import os
import sys
import psycopg2
from urllib.parse import urlparse

project_root = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, project_root)

def get_postgres_connection():
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        print("[ERROR] DATABASE_URL not set in environment variables")
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
        print(f"[ERROR] PostgreSQL connection error: {e}")
        return None

def check_data():
    print("Checking data in Railway PostgreSQL database...\n")
    
    conn = get_postgres_connection()
    if not conn:
        return
    
    cursor = conn.cursor()
    
    try:
        # Проверяем таблицы
        tables = ['Students', 'Lessons', 'LessonTasks', 'Tasks']
        
        for table in tables:
            # Проверяем существование таблицы
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND (table_name = %s OR table_name = LOWER(%s))
                );
            """, (table, table))
            exists = cursor.fetchone()[0]
            
            if not exists:
                print(f"[ERROR] Table {table} does not exist")
                continue
            
            # Получаем реальное имя таблицы
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND (table_name = %s OR table_name = LOWER(%s))
                LIMIT 1
            """, (table, table))
            real_name = cursor.fetchone()[0]
            
            # Считаем записи
            cursor.execute(f'SELECT COUNT(*) FROM "{real_name}"')
            count = cursor.fetchone()[0]
            
            print(f"[INFO] {table}: {count} records")
            
            # Для Students проверяем is_active
            if table == 'Students':
                cursor.execute(f'SELECT COUNT(*) FROM "{real_name}" WHERE is_active = TRUE')
                active_count = cursor.fetchone()[0]
                cursor.execute(f'SELECT COUNT(*) FROM "{real_name}" WHERE is_active = FALSE OR is_active IS NULL')
                inactive_count = cursor.fetchone()[0]
                print(f"   [OK] Active: {active_count}, [INACTIVE] Inactive: {inactive_count}")
                
                # Показываем несколько примеров
                cursor.execute(f'SELECT student_id, name, platform_id, category, is_active FROM "{real_name}" LIMIT 5')
                samples = cursor.fetchall()
                print(f"   Sample records:")
                for sample in samples:
                    print(f"      ID: {sample[0]}, Name: {sample[1]}, Platform ID: {sample[2]}, Category: {sample[3]}, Active: {sample[4]}")
            
            # Для Lessons показываем статусы
            elif table == 'Lessons':
                cursor.execute(f'SELECT status, COUNT(*) FROM "{real_name}" GROUP BY status')
                statuses = cursor.fetchall()
                print(f"   Statuses:")
                for status, cnt in statuses:
                    print(f"      {status}: {cnt}")
        
        # Проверяем связь между таблицами
        print(f"\n[INFO] Checking relationships:")
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND (table_name = 'Lessons' OR table_name = 'lessons')
            LIMIT 1
        """)
        lessons_table = cursor.fetchone()
        if lessons_table:
            cursor.execute(f'SELECT COUNT(*) FROM "{lessons_table[0]}" l LEFT JOIN "{real_name}" s ON l.student_id = s.student_id WHERE s.student_id IS NULL')
            orphan_lessons = cursor.fetchone()[0]
            if orphan_lessons > 0:
                print(f"   [WARNING] Found {orphan_lessons} lessons without linked students")
        
    except Exception as e:
        print(f"[ERROR] Error during check: {e}")
        import traceback
        traceback.print_exc()
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    check_data()

