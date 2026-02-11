#!/usr/bin/env python3
"""
Скачивание всех вложений заданий с источника (kompege.ru) на хост.

Сохраняет файлы в uploads/task_attachments/<task_id>/<filename> и обновляет
attached_files в БД: добавляет path — локальный путь для скачивания.

Запуск:
  python scripts/download_all_task_attachments.py [--limit N] [--dry-run]
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

ATTACHMENTS_DIR = 'uploads/task_attachments'
# URL path для локальных вложений (маршрут /attachments/task/<task_id>/<filename>)
ATTACHMENTS_URL_PREFIX = '/attachments/task'
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36'


def _safe_filename(name: str) -> str:
    """Безопасное имя файла."""
    if not name:
        return 'file'
    name = re.sub(r'[^\w\s.\-]', '_', name)
    return name.strip() or 'file'


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Скачивание вложений заданий на хост')
    parser.add_argument('--limit', type=int, default=0, help='Макс. число заданий (0 = все)')
    parser.add_argument('--dry-run', action='store_true', help='Не сохранять файлы и не обновлять БД')
    args = parser.parse_args()

    from app import create_app
    from app.models import db, Tasks

    app = create_app()
    with app.app_context():
        root = app.root_path or os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        base_dir = os.path.join(root, ATTACHMENTS_DIR.replace('/', os.sep))
        os.makedirs(base_dir, exist_ok=True)

        q = Tasks.query.filter(Tasks.attached_files.isnot(None)).order_by(Tasks.task_id.asc())
        if args.limit:
            q = q.limit(args.limit)
        tasks = q.all()

        total = len(tasks)
        if total == 0:
            print('Нет заданий с вложениями.')
            return 0

        downloaded = 0
        updated = 0
        errors = 0

        for i, task in enumerate(tasks):
            try:
                files = json.loads(task.attached_files or '[]')
            except Exception:
                files = []

            if not files:
                continue

            task_dir = os.path.join(base_dir, str(task.task_id))
            if not args.dry_run:
                os.makedirs(task_dir, exist_ok=True)

            changed = False
            new_files = []

            for f in files:
                if not isinstance(f, dict):
                    new_files.append(f)
                    continue
                url = (f.get('url') or f.get('href') or '').strip()
                if not url:
                    new_files.append(f)
                    continue
                if url.startswith('//'):
                    url = 'https:' + url
                elif url.startswith('/'):
                    url = 'https://kompege.ru' + url

                if not (url.startswith('https://kompege.ru') or url.startswith('http://kompege.ru')):
                    new_files.append(f)
                    continue

                name = (f.get('name') or f.get('text') or url.split('/')[-1].split('?')[0] or 'file').strip()
                safe_name = _safe_filename(name)
                if not safe_name:
                    safe_name = f"file_{hash(url) % 10**6}"
                local_path = os.path.join(task_dir, safe_name)
                rel_path = f"{ATTACHMENTS_URL_PREFIX}/{task.task_id}/{safe_name}"

                if f.get('path') and f.get('path').startswith(ATTACHMENTS_URL_PREFIX):
                    new_files.append(f)
                    continue

                if args.dry_run:
                    print(f'  [dry-run] task_id={task.task_id}: {url} -> {rel_path}')
                    downloaded += 1
                    changed = True
                    continue

                try:
                    r = requests.get(url, stream=True, timeout=30, headers={'User-Agent': USER_AGENT})
                    r.raise_for_status()
                    with open(local_path, 'wb') as out:
                        for chunk in r.iter_content(chunk_size=8192):
                            if chunk:
                                out.write(chunk)
                    new_entry = dict(f)
                    new_entry['path'] = rel_path
                    new_entry['url'] = url
                    new_entry['name'] = name
                    new_files.append(new_entry)
                    downloaded += 1
                    changed = True
                except Exception as e:
                    print(f'  task_id={task.task_id} {name}: {e}', file=sys.stderr)
                    errors += 1
                    new_files.append(f)

                time.sleep(0.3)

            if changed and not args.dry_run:
                task.attached_files = json.dumps(new_files, ensure_ascii=False)
                updated += 1
                db.session.commit()

            if (i + 1) % 20 == 0:
                print(f'  [{i+1}/{total}] downloaded={downloaded}, updated={updated}, errors={errors}')

        print(f'\n[OK] Скачано файлов: {downloaded}, обновлено заданий: {updated}, ошибок: {errors}')
        if args.dry_run:
            print('  (dry-run: файлы и БД не изменены)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
