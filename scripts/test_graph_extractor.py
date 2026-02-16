#!/usr/bin/env python3
"""
Тест GraphExtractor и TableExtractor на изображениях заданий ЕГЭ №1.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

SITE_BASE = 'https://kompege.ru'


def _get_image_bytes(url: str) -> bytes | None:
    try:
        import requests
        verify = os.environ.get('GIGACHAT_VERIFY_SSL_CERTS', 'true').strip().lower() not in ('0', 'false', 'no')
        r = requests.get(url, timeout=15, verify=verify)
        r.raise_for_status()
        return r.content
    except Exception as e:
        print(f"Ошибка загрузки: {e}", file=sys.stderr)
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', type=str, help='URL картинки')
    parser.add_argument('--file', type=str, help='Путь к файлу')
    parser.add_argument('--task-number', type=int, default=1)
    parser.add_argument('--limit', type=int, default=1)
    args = parser.parse_args()

    data = None
    if args.file and os.path.isfile(args.file):
        with open(args.file, 'rb') as f:
            data = f.read()
    elif args.url:
        data = _get_image_bytes(args.url)
    else:
        from app import create_app
        from app.models import Tasks
        app = create_app()
        with app.app_context():
            tasks = Tasks.query.filter_by(task_number=args.task_number).order_by(Tasks.task_id.asc()).limit(args.limit).all()
            for task in tasks:
                html = task.content_html or ''
                for s in re.findall(r'src=["\']([^"\']+)["\']', html):
                    s = s.strip()
                    if s.lower().startswith('data:image/'):
                        parts = s.split(',', 1)
                        if len(parts) == 2 and 'base64' in parts[0].lower():
                            data = base64.b64decode(parts[1].strip())
                            break
                    elif s.startswith(('http', '/')):
                        url = s if s.startswith('http') else SITE_BASE + s
                        data = _get_image_bytes(url)
                        if data:
                            break
                if not data and task.site_task_id:
                    data = _get_image_bytes(f"{SITE_BASE}/images/{task.site_task_id}.png")
                if data:
                    break

    if not data:
        print("Нет изображения. Укажите --url, --file или используйте БД (--task-number 1).", file=sys.stderr)
        return 1

    from scripts.graph_extractor import GraphExtractor, split_table_and_graph
    from scripts.table_extractor import TableExtractor, table_to_adjacency_dict

    print("Разрезаем на таблицу и граф...")
    table_bytes, graph_bytes = split_table_and_graph(data)
    if not table_bytes or not graph_bytes:
        print("Не удалось разрезать.")
        return 1

    print("\n--- Граф (правая часть) ---")
    ge = GraphExtractor()
    graph = ge.process_image(graph_bytes)
    if graph:
        print(json.dumps(graph, ensure_ascii=False, indent=2))
    else:
        print("Не распознан")

    print("\n--- Таблица (левая часть) ---")
    te = TableExtractor()
    table_data = te.process_image(table_bytes)
    if table_data:
        print(f"Размер: {table_data['size']}x{table_data['size']}")
        for i, row in enumerate(table_data['matrix']):
            print(f"  {i+1}: {row}")
    else:
        print("Не распознана")

    return 0


if __name__ == '__main__':
    sys.exit(main())
