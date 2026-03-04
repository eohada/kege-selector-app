#!/usr/bin/env python3
"""
Экспорт всех заданий из продакшн-БД в JSON-файл.
Запускать НА СЕРВЕРЕ (где БД доступна по db:5432):

    cd /путь/к/проекту
    python scripts/export_tasks_from_prod.py

Результат: data/tasks_export.json
"""
import json
import os
import sys

DB_URL = os.environ.get(
    'DATABASE_URL',
    'postgresql://boostudy_user:boostudy_password@db:5432/boostudy_prod'
)

OUTPUT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'tasks_export.json')


def main():
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        print("psycopg2 не установлен. Попробуй: pip install psycopg2-binary")
        sys.exit(1)

    print(f"Подключаюсь к БД...")
    try:
        conn = psycopg2.connect(DB_URL)
    except Exception as e:
        print(f"Ошибка подключения: {e}")
        sys.exit(1)

    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT
            task_id,
            task_number,
            task_group_id,
            site_task_id,
            source_url,
            content_html,
            answer,
            attached_files,
            difficulty_level,
            hints,
            source_prototype,
            course_id
        FROM "Tasks"
        ORDER BY task_number, task_id
    """)

    rows = cur.fetchall()
    cur.close()
    conn.close()

    tasks = []
    for row in rows:
        task = {}
        for key, value in row.items():
            if value is None:
                task[key] = None
            elif isinstance(value, (dict, list)):
                task[key] = value
            else:
                task[key] = str(value) if not isinstance(value, (int, float, bool)) else value
        tasks.append(task)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)

    by_number = {}
    for t in tasks:
        tn = t['task_number']
        by_number[tn] = by_number.get(tn, 0) + 1

    print(f"\nЭкспортировано {len(tasks)} заданий в {OUTPUT_PATH}")
    print(f"\nРаспределение по номерам:")
    for tn in sorted(by_number.keys()):
        print(f"  Задание {tn:2d}: {by_number[tn]:4d} шт.")


if __name__ == '__main__':
    main()
