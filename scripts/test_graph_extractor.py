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


def _preprocess_image_bytes(data: bytes) -> bytes | None:
    """Предобработка как в generate_solutions."""
    if not data or len(data) > 10 * 1024 * 1024:
        return None
    try:
        import io
        import numpy as np
        from PIL import Image, ImageEnhance
        img = Image.open(io.BytesIO(data)).convert('RGB')
        w, h = img.size
        if w < 800 or h < 500:
            scale = max(800 / w, 500 / h, 2.0)
            new_w = min(int(w * scale), 2800)
            new_h = min(int(h * scale), 2000)
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        img = img.convert('L')
        img = ImageEnhance.Contrast(img).enhance(1.3)
        img = ImageEnhance.Sharpness(img).enhance(1.2)
        arr = np.array(img)
        pil = Image.fromarray(arr)
        buf = io.BytesIO()
        pil.save(buf, format='PNG')
        return buf.getvalue()
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', type=str, help='URL картинки')
    parser.add_argument('--file', type=str, help='Путь к файлу')
    parser.add_argument('--task-number', type=int, default=1)
    parser.add_argument('--limit', type=int, default=1)
    parser.add_argument('--save', type=str, metavar='DIR', help='Сохранить table_part.png, graph_part.png в каталог')
    parser.add_argument('--preprocess', action='store_true', help='Применить предобработку перед split')
    parser.add_argument('--debug', action='store_true', help='Вывести отладочную информацию')
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

    if args.preprocess:
        print("Применяем предобработку...")
        data = _preprocess_image_bytes(data) or data

    from scripts.graph_extractor import GraphExtractor, split_table_and_graph
    from scripts.table_extractor import TableExtractor, table_to_adjacency_dict

    print("Разрезаем на таблицу и граф...")
    table_bytes, graph_bytes = split_table_and_graph(data)
    if not table_bytes or not graph_bytes:
        print("Не удалось разрезать.")
        return 1

    if args.save:
        os.makedirs(args.save, exist_ok=True)
        with open(os.path.join(args.save, 'table_part.png'), 'wb') as f:
            f.write(table_bytes)
        with open(os.path.join(args.save, 'graph_part.png'), 'wb') as f:
            f.write(graph_bytes)
        print(f"Сохранено: {args.save}/table_part.png, {args.save}/graph_part.png")

    print("\n--- Граф (правая часть) ---")
    ge = GraphExtractor()
    if args.debug:
        graph, debug_info = ge.process_image_with_debug(graph_bytes)
        if debug_info:
            print("Debug:", json.dumps(debug_info, ensure_ascii=False, indent=2))
    else:
        graph = ge.process_image(graph_bytes)
    if graph:
        print(json.dumps(graph, ensure_ascii=False, indent=2))
    else:
        print("Не распознан")

    print("\n--- Таблица (левая часть) ---")
    te = TableExtractor()
    table_data = te.process_image(table_bytes)
    if table_data:
        print(f"Размер: {table_data['size']}x{len(table_data['matrix'][0]) if table_data['matrix'] else 0}")
        for i, row in enumerate(table_data['matrix']):
            print(f"  {i+1}: {row}")
    else:
        print("Не распознана")

    return 0


if __name__ == '__main__':
    sys.exit(main())
