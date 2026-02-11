#!/usr/bin/env python3
"""
Импорт эталонного прототипа в банк заданий (таблица Tasks).

Если в JSON есть series_task_numbers (напр. [19, 20, 21]), создаёт или обновляет **три отдельных задания**
в БД. Повторный запуск обновляет те же задания (upsert по source_prototype).

Запуск:
  python scripts/import_prototype_to_tasks.py <path-to-prototype.json> [--dry-run]
"""
import os
import sys
import json
import argparse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
PROTOTYPES_DIR = os.path.join(REPO_ROOT, 'data', 'reference_prototypes')


def main():
    parser = argparse.ArgumentParser(description='Импорт эталона в Tasks (серия 19–21 → три задания)')
    parser.add_argument('json_path', help='Путь к JSON эталонного прототипа')
    parser.add_argument('--dry-run', action='store_true', help='Не записывать в БД')
    args = parser.parse_args()

    path = os.path.abspath(args.json_path)
    if not os.path.isfile(path):
        print(f'Файл не найден: {path}', file=sys.stderr)
        sys.exit(1)

    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if not data.get('prototype') or not (data.get('prototype').get('text') or data.get('answer')):
        print('В JSON нужны prototype.text и answer.', file=sys.stderr)
        sys.exit(1)

    # Относительный путь от reference_prototypes для upsert
    try:
        rel = os.path.relpath(path, PROTOTYPES_DIR).replace('\\', '/')
    except ValueError:
        rel = os.path.basename(path)

    from app import create_app
    from app.models import db
    from core.db_models import Subject
    from app.utils.reference_import import run_import

    app = create_app()
    with app.app_context():
        subject = Subject.query.filter_by(slug='kege').first()
        if not subject:
            print('Предмет kege не найден. Запустите seed_analytics_kege.py.', file=sys.stderr)
            sys.exit(1)
        created, updated = run_import(data, rel, dry_run=args.dry_run, db=db, subject=subject)
        if not args.dry_run:
            db.session.commit()
        print(f'Создано: {created}, обновлено: {updated}')
        if args.dry_run:
            print('(dry-run: в БД ничего не записано)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
