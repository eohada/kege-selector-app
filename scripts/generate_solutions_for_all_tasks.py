#!/usr/bin/env python3
"""
Генерация решений для ВСЕХ заданий из БД через LLM.

Проходит по таблице Tasks, для каждого задания без решения вызывает LLM
и сохраняет в TaskSolutions. Создатель может просматривать в админке.

Запуск:
  python scripts/generate_solutions_for_all_tasks.py [--limit N] [--task-number N] [--force] [--dry-run]
"""
from __future__ import annotations

import re
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def _strip_html(s: str) -> str:
    if not s:
        return ''
    s = re.sub(r'<[^>]+>', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def _build_solution_prompt(task_text: str, task_number: int, knowledge: dict | None) -> list[dict]:
    """Промпт для генерации полного решения."""
    system = (
        "Ты — опытный репетитор по информатике ЕГЭ. Напиши полное пошаговое решение задания. "
        "Формат: **Шаг 1.** Объяснение. При необходимости код в ```python. "
        "**Шаг 2.** ... В конце **Ответ:** значение. "
        "Пиши чётко, структурированно, без лишних слов."
    )
    ctx = []
    if knowledge and knowledge.get('reference_solution'):
        ref = (knowledge.get('reference_solution') or '')[:1500]
        if ref:
            ctx.append(f"Пример эталонного решения для заданий этого типа (ориентируйся по стилю):\n{ref}")
    user = f"Задание №{task_number}:\n\n{task_text[:4000]}"
    if ctx:
        user = '\n\n'.join(ctx) + '\n\n---\n\n' + user
    return [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': user},
    ]


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Генерация решений для всех заданий')
    parser.add_argument('--limit', type=int, default=0, help='Макс. число заданий (0 = все)')
    parser.add_argument('--task-number', type=int, default=0, help='Только задания с этим номером')
    parser.add_argument('--force', action='store_true', help='Перезаписать существующие решения')
    parser.add_argument('--dry-run', action='store_true', help='Не сохранять в БД')
    parser.add_argument('--batch-size', type=int, default=10, help='Коммитить каждые N заданий')
    args = parser.parse_args()

    from app import create_app
    from app.models import db, Tasks, TaskSolution
    from trainer_app.knowledge import load_task_knowledge
    from trainer_app.llm.providers import get_llm_client

    app = create_app()
    with app.app_context():
        from app.utils.db_migrations import ensure_schema_columns
        ensure_schema_columns(app)

        llm = get_llm_client()
        if not llm:
            print('LLM не настроен. Задайте GIGACHAT_CREDENTIALS в окружении.', file=sys.stderr)
            return 1

        q = Tasks.query.order_by(Tasks.task_id.asc())
        if args.task_number:
            q = q.filter(Tasks.task_number == args.task_number)
        if args.limit:
            q = q.limit(args.limit)
        tasks = q.all()

        total = len(tasks)
        if total == 0:
            print('Нет заданий для обработки.')
            return 0

        done = 0
        skipped = 0
        errors = 0

        for i, task in enumerate(tasks):
            existing = TaskSolution.query.filter_by(task_id=task.task_id).first()
            if existing and not args.force:
                skipped += 1
                if (i + 1) % 50 == 0:
                    print(f'  [{i+1}/{total}] skipped (already have), done={done}, errors={errors}')
                continue

            task_text = _strip_html(task.content_html or '')
            if len(task_text) < 30:
                skipped += 1
                continue

            knowledge = load_task_knowledge(task.task_id, task_number=task.task_number)
            messages = _build_solution_prompt(task_text, task.task_number, knowledge)

            try:
                solution_text = llm.chat(messages=messages, temperature=0.2, max_tokens=1200)
                if not solution_text or len(solution_text.strip()) < 20:
                    print(f'  task_id={task.task_id}: пустой ответ LLM')
                    errors += 1
                    continue

                if not args.dry_run:
                    if existing:
                        existing.solution_text = solution_text.strip()
                        existing.source = 'llm'
                    else:
                        db.session.add(TaskSolution(
                            task_id=task.task_id,
                            solution_text=solution_text.strip(),
                            source='llm',
                        ))
                    done += 1
                    if done % args.batch_size == 0:
                        db.session.commit()
                else:
                    done += 1
                    print(f'  [dry-run] task_id={task.task_id} -> {len(solution_text)} chars')

            except Exception as e:
                print(f'  task_id={task.task_id}: {e}', file=sys.stderr)
                errors += 1
                db.session.rollback()

            if (i + 1) % 20 == 0 and not args.dry_run:
                print(f'  [{i+1}/{total}] done={done}, skipped={skipped}, errors={errors}')

        if not args.dry_run and done % args.batch_size != 0:
            db.session.commit()

        print(f'\n[OK] Обработано: {done} создано/обновлено, {skipped} пропущено, {errors} ошибок')
        if args.dry_run:
            print('  (dry-run: в БД ничего не записано)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
