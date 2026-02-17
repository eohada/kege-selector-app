#!/usr/bin/env python3
"""
Разовая очистка заданий с номером 6: убрать из конца условия (content_html)
лишнюю цифру/значение, совпадающую с ответом задания.

Запуск (из корня проекта, лучше с активированным venv):
  python scripts/clean_task6_trailing_answer.py [--dry-run]
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def _strip_trailing_answer_once(content: str, answer: str) -> str:
    """
    Удаляет одно вхождение ответа в самом конце текста, если оно идёт отдельно
    (не часть более длинного числа). Возвращает новый content или тот же.
    """
    if not content or not answer:
        return content
    s = content.rstrip()
    if not s.endswith(answer):
        return content
    pos = len(s) - len(answer)
    # Не отрезать, если ответ — часть числа (например, ответ "8", конец "128")
    if pos > 0 and s[pos - 1].isdigit():
        return content
    # Убрать пробелы/знаки между концом условия и ответом (например " − 48")
    new_end = s[:pos].rstrip()
    # Убрать один trailing разделитель (пробел, минус, запятая)
    for _ in range(2):
        if new_end.endswith(' ') or new_end.endswith('−') or new_end.endswith('-') or new_end.endswith(','):
            new_end = new_end[:-1].rstrip()
    return new_end


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Убрать лишний ответ в конце условия у заданий 6')
    parser.add_argument('--dry-run', action='store_true', help='Не сохранять в БД, только показать изменения')
    args = parser.parse_args()

    from app import create_app
    from app.models import db, Tasks

    app = create_app()
    with app.app_context():
        tasks = Tasks.query.filter(
            Tasks.task_number == 6,
            Tasks.content_html.isnot(None),
        ).order_by(Tasks.task_id.asc()).all()

        updated = 0
        for task in tasks:
            answer = (task.answer or '').strip()
            if not answer:
                continue
            content = task.content_html or ''
            new_content = _strip_trailing_answer_once(content, answer)
            if new_content != content:
                if args.dry_run:
                    print(f'task_id={task.task_id} answer={answer!r}: обрезаем конец (длина {len(content)} -> {len(new_content)})')
                else:
                    task.content_html = new_content
                updated += 1

        if not args.dry_run and updated:
            db.session.commit()
            print(f'Обновлено заданий (task_number=6): {updated}')
        elif args.dry_run:
            print(f'[dry-run] Будет обновлено: {updated}')
        else:
            print('Нет изменений.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
