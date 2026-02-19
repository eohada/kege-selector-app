#!/usr/bin/env python3
"""
Проверка и импорт правильных ответов в таблицу Tasks.

Правильные ответы в интерфейсе (ученик/преподаватель) берутся из:
  - LessonTask.student_answer (ключ, введённый преподавателем при проверке)
  - Tasks.answer (ответ из базы заданий)

Если везде прочерки — в БД у заданий пустое поле Tasks.answer.

Использование:
  # Статистика по ответам в БД
  python scripts/check_and_import_answers.py --check

  # По конкретному уроку: какие задания с ответами, какие без
  python scripts/check_and_import_answers.py --check --lesson-id 123

  # Импорт из JSON: ключ = task_id, значение = строка ответа или список [ans19, ans20, ans21]
  python scripts/check_and_import_answers.py --import-json answers_simple.json [--dry-run]

  # Для заданий 19–21 уже есть: scripts/reparse_task_19_21_answers.py --import answers.json
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def run_check(lesson_id: int | None) -> int:
    """Показать, сколько заданий в БД имеют ответ и по уроку — какие с ответом, какие без."""
    from app import create_app
    from app.models import Tasks, Lesson, LessonTask
    app = create_app()
    with app.app_context():
        total = Tasks.query.count()
        with_answer = Tasks.query.filter(Tasks.answer.isnot(None), Tasks.answer != '').count()
        without = total - with_answer
        print('=== Ответы в таблице Tasks ===')
        print(f'Всего заданий: {total}')
        print(f'С заполненным ответом: {with_answer}')
        print(f'Без ответа (будут прочерки в интерфейсе): {without}')
        if lesson_id:
            lesson = Lesson.query.get(lesson_id)
            if not lesson:
                print(f'Урок {lesson_id} не найден.')
                return 1
            tasks = lesson.homework_tasks
            print(f'\nУрок {lesson_id}, заданий в уроке: {len(tasks)}')
            for lt in sorted(tasks, key=lambda t: t.lesson_task_id):
                task = lt.task
                has_answer = bool(task and (task.answer or '').strip())
                key = (lt.student_answer or '').strip()
                src = 'Tasks.answer' if has_answer else '(пусто)'
                if key:
                    src += f' + ключ преподавателя'
                print(f'  lesson_task_id={lt.lesson_task_id} task_id={task.task_id if task else "?"} '
                      f'task_number={task.task_number if task else "?"} ответ: {src}')
    return 0


def run_import_json(path: str, dry_run: bool) -> int:
    """
    Импорт из JSON: { "task_id": "answer" } или { "task_id": [a19, a20, a21] }.
    Для заданий 19 с массивом из 3 элементов обновляет 19 и создаёт/обновляет 20, 21 по task_group_id.
    """
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if not data:
        print('Файл пуст.')
        return 0
    from app import create_app
    from app.models import db, Tasks
    app = create_app()
    updated = 0
    created = 0
    with app.app_context():
        for task_id_str, val in data.items():
            try:
                task_id = int(task_id_str)
            except (TypeError, ValueError):
                continue
            task = Tasks.query.get(task_id)
            if not task:
                continue
            if isinstance(val, list):
                lines = [str(x).strip() if x is not None else '' for x in val[:3]]
                lines = (lines + ['', '', ''])[:3]
            else:
                s = str(val).strip() if val else ''
                if s and '\n' in s and task.task_number == 19:
                    lines = [x.strip() for x in s.split('\n')[:3]]
                    lines = (lines + ['', '', ''])[:3]
                else:
                    lines = [s, '', '']
            if dry_run:
                print(f'task_id={task_id} task_number={task.task_number} -> {lines!r}')
                updated += 1
                continue
            if task.task_number == 19 and (len(lines) >= 3 or any(lines)):
                group_id = (task.site_task_id or str(task_id)).strip()
                task.answer = lines[0] or None
                if not task.task_group_id:
                    task.task_group_id = group_id
                db.session.add(task)
                updated += 1
                # Обновить или создать 20, 21
                for sub_num, ans in [(20, lines[1] if len(lines) > 1 else ''), (21, lines[2] if len(lines) > 2 else '')]:
                    existing = Tasks.query.filter(
                        Tasks.task_group_id == group_id,
                        Tasks.task_number == sub_num
                    ).first()
                    if existing:
                        existing.answer = ans or None
                        db.session.add(existing)
                    else:
                        new_t = Tasks(
                            task_number=sub_num,
                            task_group_id=group_id,
                            site_task_id=task.site_task_id,
                            source_url=task.source_url or '',
                            content_html=task.content_html or '',
                            answer=ans or None,
                            attached_files=task.attached_files,
                            last_scraped=task.last_scraped,
                        )
                        db.session.add(new_t)
                        created += 1
            else:
                task.answer = lines[0] if lines else None
                db.session.add(task)
                updated += 1
        if not dry_run:
            try:
                db.session.commit()
            except Exception as e:
                print(f'Ошибка commit: {e}', file=sys.stderr)
                db.session.rollback()
                return 1
    print(f'Обновлено: {updated}, создано заданий 20/21: {created}')
    if dry_run:
        print('[dry-run] БД не изменялась.')
    return 0


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Проверка и импорт ответов в Tasks')
    parser.add_argument('--check', action='store_true', help='Показать статистику по ответам в БД')
    parser.add_argument('--lesson-id', type=int, default=None, help='Для --check: разбор по уроку')
    parser.add_argument('--import-json', metavar='FILE', help='Импорт из JSON: task_id -> answer или [a19,a20,a21]')
    parser.add_argument('--dry-run', action='store_true', help='Не сохранять в БД (только вывод)')
    args = parser.parse_args()

    if args.check:
        return run_check(args.lesson_id)
    if args.import_json:
        if not os.path.isfile(args.import_json):
            print(f'Файл не найден: {args.import_json}', file=sys.stderr)
            return 1
        return run_import_json(args.import_json, args.dry_run)
    parser.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
