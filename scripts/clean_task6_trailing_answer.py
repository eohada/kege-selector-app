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
    Удаляет дублирующееся в конце число-ответ: условие, пустые строки, число без подписи.
    Число может быть просто в конце текста («...\n\n48») или внутри тега («<p>48</p>»).
    Не отрезает, если ответ — часть числа (например «128» при ответе «8»).
    """
    if not content or not answer:
        return content
    # Перед ответом: либо пробелы/переносы, либо конец открывающего тега «>»
    # После ответа: пробелы и закрывающие теги до конца строки
    pattern = re.compile(
        r'([\s>]*)' + re.escape(answer) + r'\s*(?:</[^>]+>)*\s*$',
        re.DOTALL,
    )
    m = pattern.search(content)
    if not m:
        return content
    # Не отрезать, если ответ — часть числа (символ перед ответом — не цифра и не «>» внутри числа)
    lead = m.group(1)
    answer_start = m.start() + len(lead)
    if answer_start > 0:
        prev = content[answer_start - 1]
        if prev.isdigit():
            return content
    new_content = content[: m.start()].rstrip()
    # Убрать «висящий» открывающий тег в конце (например «<p» после удаления «>48</p>»)
    new_content = re.sub(r'<[a-zA-Z][^>]*$', '', new_content).rstrip()
    # Убрать trailing разделители
    for _ in range(6):
        if new_content.endswith(' ') or new_content.endswith('−') or new_content.endswith('-') or new_content.endswith(','):
            new_content = new_content[:-1].rstrip()
    for suffix in ('Ответ:', 'Ответ: ', 'ответ:', 'ответ: '):
        if new_content.rstrip().endswith(suffix):
            new_content = new_content.rstrip()[: -len(suffix)].rstrip()
            break
    return new_content


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Убрать лишний ответ в конце условия у заданий 6')
    parser.add_argument('--dry-run', action='store_true', help='Не сохранять в БД, только показать изменения')
    parser.add_argument('--verbose', '-v', action='store_true', help='Показать конец content_html для первых 3 заданий (для отладки)')
    args = parser.parse_args()

    from app import create_app
    from app.models import db, Tasks

    app = create_app()
    with app.app_context():
        tasks = Tasks.query.filter(
            Tasks.task_number == 6,
            Tasks.content_html.isnot(None),
        ).order_by(Tasks.task_id.asc()).all()

        with_answer = sum(1 for t in tasks if (t.answer or '').strip())
        print(f'Заданий с task_number=6 (с контентом): {len(tasks)}, из них с непустым ответом: {with_answer}')

        if args.verbose and tasks:
            for task in tasks[:3]:
                c = (task.content_html or '')[-200:]
                a = (task.answer or '').strip()
                print(f'  task_id={task.task_id} answer={a!r} конец content: ...{repr(c)}')

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
