#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Быстрое исправление sequences в PostgreSQL"""

import os
import sys
import psycopg2
from urllib.parse import urlparse

def get_postgres_connection():
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        print("[ERROR] DATABASE_URL not set")
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
        print(f"[ERROR] Connection error: {e}")
        return None

def fix_sequences():
    print("Fixing PostgreSQL sequences...\n")
    
    conn = get_postgres_connection()
    if not conn:
        return
    
    cursor = conn.cursor()
    
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
    
    for table_name, pk_column in sequences_map.items():
        try:
            # Получаем реальное имя таблицы
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND (table_name = %s OR table_name = LOWER(%s))
                LIMIT 1
            """, (table_name, table_name))
            result = cursor.fetchone()
            if not result:
                continue
            real_table_name = result[0]
            
            # Получаем максимальный ID
            cursor.execute(f'SELECT MAX("{pk_column}") FROM "{real_table_name}"')
            max_id = cursor.fetchone()[0]
            
            if max_id is None:
                max_id = 0
            
            # Пробуем разные варианты имени sequence
            sequence_variants = [
                f'"{real_table_name}_{pk_column}_seq"',
                f'"{real_table_name.lower()}_{pk_column}_seq"',
                f'{real_table_name.lower()}_{pk_column}_seq',
            ]
            
            updated = False
            for seq_name in sequence_variants:
                try:
                    cursor.execute(f"SELECT setval('{seq_name}', %s, true)", (max_id,))
                    conn.commit()
                    print(f"[OK] {table_name}: sequence updated to {max_id}")
                    updated = True
                    break
                except Exception as e:
                    continue
            
            if not updated:
                print(f"[WARNING] {table_name}: could not update sequence")
                
        except Exception as e:
            print(f"[ERROR] {table_name}: {e}")
    
    cursor.close()
    conn.close()
    print("\nDone!")

if __name__ == '__main__':
    fix_sequences()

