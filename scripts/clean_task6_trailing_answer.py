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
    Удаляет одно вхождение ответа в самом конце условия (content_html).
    Учитывает, что конец может быть « 48</p></div>» — ответ перед закрывающими тегами.
    Не отрезает, если ответ — часть числа (например «128» при ответе «8»).
    """
    if not content or not answer:
        return content
    # Паттерн: пробелы, затем ответ, затем пробелы и закрывающие теги до конца
    pattern = re.compile(
        r'(\s*)' + re.escape(answer) + r'\s*(?:</[^>]+>)*\s*$',
        re.DOTALL,
    )
    m = pattern.search(content)
    if not m:
        # Раньше проверяли только конец без тегов — оставляем как запасной вариант
        s = content.rstrip()
        if not s.endswith(answer):
            return content
        pos = len(s) - len(answer)
        if pos > 0 and s[pos - 1].isdigit():
            return content
        new_end = s[:pos].rstrip()
        for _ in range(3):
            if new_end.endswith(' ') or new_end.endswith('−') or new_end.endswith('-') or new_end.endswith(','):
                new_end = new_end[:-1].rstrip()
        for suffix in ('Ответ:', 'Ответ: ', 'ответ:', 'ответ: '):
            if new_end.endswith(suffix):
                new_end = new_end[: -len(suffix)].rstrip()
                break
        return new_end
    # Ответ не должен быть частью числа (символ перед ответом — не цифра)
    answer_start = m.start() + len(m.group(1))
    if answer_start > 0 and content[answer_start - 1].isdigit():
        return content
    new_content = content[: m.start()].rstrip()
    # Убрать trailing разделители ( − , запятая, пробел)
    for _ in range(5):
        if new_content.endswith(' ') or new_content.endswith('−') or new_content.endswith('-') or new_content.endswith(','):
            new_content = new_content[:-1].rstrip()
    # Убрать оставшееся в конце «Ответ:» / «Ответ: »
    for suffix in ('Ответ:', 'Ответ: ', 'Ответ :', 'ответ:', 'ответ: '):
        if new_content.rstrip().endswith(suffix):
            new_content = new_content.rstrip()[: -len(suffix)].rstrip()
            break
    return new_content


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

        with_answer = sum(1 for t in tasks if (t.answer or '').strip())
        print(f'Заданий с task_number=6 (с контентом): {len(tasks)}, из них с непустым ответом: {with_answer}')

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
