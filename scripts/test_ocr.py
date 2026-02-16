#!/usr/bin/env python3
"""
Тест OCR на изображениях заданий. Запуск без LLM — только смотрим, что извлекает EasyOCR.

Запуск:
  python scripts/test_ocr.py                          # тест на встроенном примере
  python scripts/test_ocr.py --url URL                # по URL
  python scripts/test_ocr.py --task-id N              # картинка из задания N в БД
  python scripts/test_ocr.py --task-number 1 --limit 3  # первые 3 задания №1
"""
from __future__ import annotations

import argparse
import base64
import io
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

SITE_BASE = 'https://kompege.ru'


def _get_image_bytes_from_url(url: str) -> bytes | None:
    try:
        import requests
        verify = os.environ.get('GIGACHAT_VERIFY_SSL_CERTS', 'true').strip().lower() not in ('0', 'false', 'no')
        resp = requests.get(url, timeout=15, verify=verify)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        print(f"  Ошибка загрузки {url}: {e}", file=sys.stderr)
        return None


def _ocr_preprocess(img):
    """Предобработка: масштабирование, контраст, резкость. Возвращает RGB-массив для easyocr."""
    from PIL import Image, ImageEnhance
    import numpy as np
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
    return np.stack([arr, arr, arr], axis=-1)


def _ocr_extract(data: bytes, preprocess: bool = True, save_path: str | None = None) -> str:
    """OCR через easyocr. Возвращает текст или сообщение об ошибке."""
    try:
        import numpy as np
        from PIL import Image
    except ImportError as e:
        return f"[Ошибка импорта: {e}]"
    try:
        from scripts.generate_solutions_for_all_tasks import _get_ocr_reader
        reader = _get_ocr_reader()
        if reader is None:
            return "[EasyOCR не инициализирован]"
    except Exception as e:
        return f"[Ошибка инициализации OCR: {e}]"
    try:
        img = Image.open(io.BytesIO(data)).convert('RGB')
        if preprocess:
            arr = _ocr_preprocess(img)
            if save_path:
                from PIL import Image as PILImage
                PILImage.fromarray(arr).save(save_path)
                print(f"  (сохранено: {save_path})")
        else:
            arr = np.array(img)
        result = reader.readtext(arr)
        if result:
            return ' '.join(r[1] for r in result if r[1])
        return "[OCR не нашёл текст] (распознано 0 блоков)"
    except Exception as e:
        return f"[Ошибка OCR: {e}]"


def main():
    parser = argparse.ArgumentParser(description='Тест OCR на изображениях')
    parser.add_argument('--url', type=str, help='URL картинки')
    parser.add_argument('--task-id', type=int, help='task_id из БД')
    parser.add_argument('--task-number', type=int, help='Номер задания (1-27)')
    parser.add_argument('--limit', type=int, default=3, help='Сколько заданий (для --task-number)')
    parser.add_argument('--minimal', action='store_true', help='Минимальный тест: 1x1 PNG без OCR')
    parser.add_argument('--no-preprocess', action='store_true', help='Без предобработки (масштаб, контраст)')
    parser.add_argument('--save', type=str, metavar='FILE', help='Сохранить предобработанное изображение для проверки')
    args = parser.parse_args()

    if args.minimal:
        print("Проверка импортов...")
        try:
            import easyocr
            print("  easyocr: OK")
        except ImportError as e:
            print(f"  easyocr: {e}")
            return 1
        try:
            from scripts.generate_solutions_for_all_tasks import _get_ocr_reader
            r = _get_ocr_reader()
            print(f"  Reader: {'OK' if r else 'не создан'}")
        except Exception as e:
            print(f"  Reader: {e}")
            return 1
        print("OK")
        return 0

    images_to_test: list[tuple[str, bytes]] = []

    if args.url:
        data = _get_image_bytes_from_url(args.url)
        if data:
            images_to_test.append((args.url, data))
        else:
            return 1

    elif args.task_id or args.task_number:
        from app import create_app
        from app.models import Tasks
        app = create_app()
        with app.app_context():
            if args.task_id:
                q = Tasks.query.filter_by(task_id=args.task_id)
            else:
                q = Tasks.query.filter_by(task_number=args.task_number).order_by(Tasks.task_id.asc()).limit(args.limit)
            tasks = q.all()
            if not tasks:
                print("Заданий не найдено.", file=sys.stderr)
                return 1
            for task in tasks:
                html = task.content_html or ''
                srcs = re.findall(r'src=["\']([^"\']+)["\']', html, re.IGNORECASE)
                for s in srcs:
                    s = (s or '').strip()
                    if not s:
                        continue
                    if s.lower().startswith('data:image/'):
                        try:
                            parts = s.split(',', 1)
                            if len(parts) == 2 and 'base64' in parts[0].lower():
                                data = base64.b64decode(parts[1].strip())
                                if data:
                                    images_to_test.append((f"task_id={task.task_id} (data URI)", data))
                                    break
                        except Exception:
                            pass
                    elif s.startswith(('http://', 'https://')) or (s.startswith('/') and not s.startswith('//')):
                        url = s if s.startswith('http') else SITE_BASE.rstrip('/') + s
                        data = _get_image_bytes_from_url(url)
                        if data:
                            images_to_test.append((f"task_id={task.task_id} ({url[:60]}...)", data))
                            break
                if not any(t[0].startswith(f"task_id={task.task_id}") for t in images_to_test):
                    sid = (task.site_task_id or '').strip()
                    if not sid and task.source_url:
                        m = re.search(r'[?&]id=(\d+)', task.source_url)
                        if m:
                            sid = m.group(1)
                    if sid and sid.isdigit():
                        url = f"{SITE_BASE}/images/{sid}.png"
                        data = _get_image_bytes_from_url(url)
                        if data:
                            images_to_test.append((f"task_id={task.task_id} (fallback {url})", data))

    else:
        print("Проверка OCR (маленькое изображение без текста — OCR вернёт пустое или мало).")
        print("Для реального теста используйте: --task-number 1 --limit 1  или  --url https://kompege.ru/images/25.png")
        b64 = 'iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAYAAACNMs+9AAAAFklEQVQYlWNgYGD4z0ABYBg1ahQAAE4KAR0n+O8eAAAAAElFTkSuQmCC'
        try:
            from PIL import Image
            data = base64.b64decode(b64)
            img = Image.open(io.BytesIO(data))
            print(f"  Размер: {img.size}")
            images_to_test.append(("встроенный пример (маленький PNG)", data))
        except Exception as e:
            print(f"  Ошибка: {e}")
            return 1

    if not images_to_test:
        print("Нет изображений для теста. Укажите --url, --task-id или --task-number.", file=sys.stderr)
        return 1

    print(f"\nТестируем OCR на {len(images_to_test)} изображении(ях)...\n")
    for i, (label, data) in enumerate(images_to_test, 1):
        print(f"--- [{i}] {label} ({len(data)} bytes) ---")
        save = args.save if i == 1 else None
        text = _ocr_extract(data, preprocess=not args.no_preprocess, save_path=save)
        print(text)
        print()
    return 0


if __name__ == '__main__':
    sys.exit(main())
