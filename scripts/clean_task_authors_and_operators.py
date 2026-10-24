#!/usr/bin/env python3
"""
scripts/clean_task_authors_and_operators.py

Однократный скрипт миграции базы данных заданий (Tasks):
1. Нормализует логические операторы:
   - \\/ -> ∨ (U+2228, дизъюнкция)
   - /\\ -> ∧ (U+2227, конъюнкция)
   - " -> " -> " → " (U+2192, импликация)
2. Удаляет авторские подписи и префиксы в начале условия задания:
   - (Д. Бахтиев), [Л. Шастин], (PRO100 ЕГЭ), (Е. Джобс), ссылки на vk/tg и т.д.
3. Очищает оставшиеся пустые теги в начале фрагмента (<strong></strong>, <a></a>, &nbsp;).
4. Защита от повреждения данных: валидация минимальной длины, транзакции пакетами, опциональный бэкап.

Usage:
  python scripts/clean_task_authors_and_operators.py --dry-run
  python scripts/clean_task_authors_and_operators.py --backup --apply
"""

import os
import sys
import argparse
import logging
from datetime import datetime

# Обеспечиваем корректный импорт приложения
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Поддержка UTF-8 вывода в Windows консоли
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from app import create_app
from core.db_models import db, Tasks
from app.utils.jinja_filters import clean_task_condition, normalize_task_logic_operators

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger('clean_task_authors')


def backup_tasks_table():
    """Создаёт резервную копию таблицы Tasks в PostgreSQL/SQLite."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_table_name = f"tasks_backup_{timestamp}"
    logger.info(f"Создание бэкапа таблицы Tasks -> {backup_table_name}...")
    try:
        db.session.execute(db.text(f'CREATE TABLE "{backup_table_name}" AS SELECT * FROM "Tasks";'))
        db.session.commit()
        logger.info(f"Бэкап успешно создан: {backup_table_name}")
        return backup_table_name
    except Exception as exc:
        db.session.rollback()
        logger.error(f"Ошибка создания бэкапа: {exc}")
        raise


def process_task_content(content_html: str) -> str:
    """Обрабатывает HTML условия задания: убирает авторов и нормализует логику."""
    if not content_html:
        return content_html
    return clean_task_condition(content_html)


def run_migration(dry_run: bool = True, batch_size: int = 500, do_backup: bool = False):
    app = create_app()
    with app.app_context():
        if not dry_run and do_backup:
            backup_tasks_table()

        total_tasks = Tasks.query.count()
        logger.info(f"Всего заданий в базе данных: {total_tasks}")
        logger.info(f"Режим работы: {'DRY-RUN (без изменений)' if dry_run else 'APPLY (применение к БД)'}")

        modified_count = 0
        operator_changes_count = 0
        author_changes_count = 0
        skipped_short_count = 0

        sample_changes = []

        query = Tasks.query.order_by(Tasks.task_id)
        offset = 0

        while True:
            batch = query.offset(offset).limit(batch_size).all()
            if not batch:
                break

            for task in batch:
                original = task.content_html or ""
                if not original:
                    continue

                cleaned = process_task_content(original)

                if cleaned != original:
                    # Валидация безопасности: не очистили ли задание до пустоты
                    if len(cleaned.strip()) < 15 and len(original.strip()) >= 15:
                        logger.warning(f"Task ID {task.task_id}: условие стало слишком коротким ({len(cleaned)} chars), пропуск!")
                        skipped_short_count += 1
                        continue

                    # Статистика изменений
                    had_operators = ('\\/' in original) or ('/\\' in original) or (' -> ' in original)
                    if had_operators:
                        operator_changes_count += 1
                    else:
                        author_changes_count += 1

                    modified_count += 1

                    if len(sample_changes) < 8:
                        sample_changes.append({
                            'id': task.task_id,
                            'number': task.task_number,
                            'orig_len': len(original),
                            'clean_len': len(cleaned),
                            'original_preview': original[:120].replace('\n', ' '),
                            'cleaned_preview': cleaned[:120].replace('\n', ' '),
                        })

                    if not dry_run:
                        task.content_html = cleaned

            if not dry_run:
                db.session.commit()
                logger.info(f"Обработано {min(offset + batch_size, total_tasks)} / {total_tasks} заданий (изменено {modified_count})...")
            else:
                if (offset + batch_size) % 2000 == 0 or offset + batch_size >= total_tasks:
                    logger.info(f"Проверено {min(offset + batch_size, total_tasks)} / {total_tasks} заданий (нашлось {modified_count} для изменения)...")

            offset += batch_size

        logger.info("=== ИТОГИ МИГРАЦИИ ===")
        logger.info(f"Всего заданий проверено: {total_tasks}")
        logger.info(f"Найдено заданий для очистки: {modified_count}")
        logger.info(f"  - С авторскими подписями: ~{author_changes_count}")
        logger.info(f"  - С логическими операторами: ~{operator_changes_count}")
        if skipped_short_count > 0:
            logger.warning(f"  - Пропущено из-за риска потери данных: {skipped_short_count}")

        logger.info("\nПримеры очищенных заданий:")
        for idx, s in enumerate(sample_changes, 1):
            logger.info(f"[{idx}] Task #{s['id']} (№{s['number']}):")
            logger.info(f"    ДО:    {s['original_preview']}...")
            logger.info(f"    ПОСЛЕ: {s['cleaned_preview']}...")

        if dry_run:
            logger.info("\n[DRY-RUN ЗАВЕРШЁН] База данных НЕ изменялась. Для применения выполните с флагом --apply.")
        else:
            logger.info("\n[APPLY ЗАВЕРШЁН] Изменения успешно сохранены в базе данных.")


def main():
    parser = argparse.ArgumentParser(description="Очистка авторских подписей и нормализация операторов в Tasks")
    parser.add_argument('--apply', action='store_true', help="Применить изменения к базе данных")
    parser.add_argument('--dry-run', action='store_true', help="Только показать статистику без записи")
    parser.add_argument('--backup', action='store_true', help="Сделать резервную копию таблицы Tasks перед применением")
    parser.add_argument('--batch-size', type=int, default=500, help="Размер пакета транзакции")

    args = parser.parse_args()

    if not args.apply and not args.dry_run:
        parser.print_help()
        sys.exit(1)

    run_migration(dry_run=args.dry_run, batch_size=args.batch_size, do_backup=args.backup)


if __name__ == '__main__':
    main()
