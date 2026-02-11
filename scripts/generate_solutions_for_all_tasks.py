#!/usr/bin/env python3
"""
Генерация решений для ВСЕХ заданий из БД через LLM.

Проходит по таблице Tasks, для каждого задания без решения вызывает LLM
и сохраняет в TaskSolutions. Создатель может просматривать в админке.

Запуск:
  python scripts/generate_solutions_for_all_tasks.py [--limit N] [--task-number N] [--force] [--dry-run]
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

SITE_BASE = 'https://kompege.ru'
MAX_ATTACHMENT_TEXT = 8000


def _strip_html(s: str) -> str:
    if not s:
        return ''
    s = re.sub(r'<[^>]+>', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def _extract_answer_from_solution(text: str) -> str | None:
    """Извлекает ответ из текста решения (после **Ответ:**)."""
    if not text:
        return None
    m = re.search(r'\*\*Ответ:\*\*\s*(.+?)(?:\n|$)', text, re.IGNORECASE | re.DOTALL)
    if m:
        return (m.group(1) or '').strip()
    m = re.search(r'Ответ:\s*(.+?)(?:\n|$)', text, re.IGNORECASE | re.DOTALL)
    if m:
        return (m.group(1) or '').strip()
    return None


def _normalize_answer(a: str | None) -> str:
    """Нормализация ответа для сравнения."""
    if not a:
        return ''
    s = str(a).strip().lower()
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'[^\w\s.,\-]', '', s)  # убрать лишние символы
    return s


def _answers_match(expected: str | None, actual: str | None) -> bool:
    """Сравнение ответов (ожидаемый из источника и полученный LLM)."""
    e = _normalize_answer(expected)
    a = _normalize_answer(actual)
    if not e:
        return True  # нет эталона — не помечаем на ручную проверку
    return e == a or a.endswith(e) or e.endswith(a)


def _read_excel_as_text(path: str) -> str:
    """Читает Excel в текстовую таблицу (листы, строки)."""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        out = []
        for sh in wb.worksheets:
            out.append(f"Лист: {sh.title}")
            rows = list(sh.iter_rows(values_only=True))
            for row in rows[:100]:  # лимит строк
                vals = [str(v) if v is not None else '' for v in (row or [])]
                out.append(' | '.join(vals))
            if len(rows) > 100:
                out.append(f"... (ещё {len(rows) - 100} строк)")
            out.append('')
        wb.close()
        return '\n'.join(out)[:MAX_ATTACHMENT_TEXT]
    except Exception as e:
        return f"[Ошибка чтения Excel: {e}]"


def _read_text_file(path: str) -> str:
    """Читает текстовый файл."""
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read(MAX_ATTACHMENT_TEXT)
    except Exception:
        try:
            with open(path, 'r', encoding='cp1251', errors='replace') as f:
                return f.read(MAX_ATTACHMENT_TEXT)
        except Exception as e:
            return f"[Ошибка чтения: {e}]"


def _extract_attachments_content(task, app_root: str) -> str:
    """Извлекает содержимое вложений для промпта."""
    raw = task.attached_files
    if not raw:
        return ''
    try:
        files = json.loads(raw)
    except Exception:
        return ''
    if not isinstance(files, list):
        return ''
    parts = []
    for f in files:
        if not isinstance(f, dict):
            continue
        path = (f.get('path') or '').strip()
        url = (f.get('url') or '').strip()
        name = (f.get('name') or f.get('text') or 'file').strip()
        local_path = None
        if path and path.startswith('/attachments/task/'):
            # /attachments/task/123/file.xlsx -> uploads/task_attachments/123/file.xlsx
            parts_path = [p for p in path.split('/') if p]
            if len(parts_path) >= 3:  # attachments, task, 123, file.xlsx
                task_id = parts_path[2]
                fname = '/'.join(parts_path[3:]) if len(parts_path) > 3 else ''
                if fname:
                    local_path = os.path.join(app_root, 'uploads', 'task_attachments', task_id, fname)
        if not local_path or not os.path.isfile(local_path):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext in ('.xlsx', '.xls'):
            text = _read_excel_as_text(local_path)
        elif ext in ('.txt', '.csv', '.dat'):
            text = _read_text_file(local_path)
        else:
            continue
        parts.append(f"[Вложение: {name}]\n{text}\n")
    if not parts:
        return ''
    return '--- Вложения ---\n' + '\n'.join(parts) + '\n---'


def _get_source_url(task) -> str | None:
    """Источник: source_url или из site_task_id."""
    url = (task.source_url or '').strip()
    if url:
        return url
    sid = (task.site_task_id or '').strip()
    if sid:
        return f"{SITE_BASE}/task?id={sid}"
    return None


def _build_solution_prompt(
    task_text: str,
    task_number: int,
    source_url: str | None,
    attachments_content: str,
    knowledge: dict | None,
) -> list[dict]:
    """Промпт для генерации полного решения."""
    system = (
        "Ты — опытный репетитор по информатике ЕГЭ. Напиши полное пошаговое решение задания в Markdown.\n\n"
        "ОБЯЗАТЕЛЬНЫЙ формат вывода:\n"
        "1. **Источник:** [ссылка на задание](URL) — если URL известен.\n"
        "2. **Условие задачи:** кратко перескажи или выдели ключевые данные из условия.\n"
        "3. **Шаг 1.** Объяснение. При необходимости код в ```python.\n"
        "4. **Шаг 2.** ... и т.д.\n"
        "5. **Ответ:** точное значение (число, строка и т.д.).\n\n"
        "Используй **жирный** для заголовков шагов. Пиши чётко, структурированно. "
        "Если в задании есть вложения (Excel, текст) — опирайся на их содержимое при решении."
    )
    ctx = []
    if knowledge and knowledge.get('reference_solution'):
        ref = (knowledge.get('reference_solution') or '')[:1500]
        if ref:
            ctx.append(f"Пример эталонного решения для заданий этого типа (ориентируйся по стилю):\n{ref}")
    user_parts = []
    if source_url:
        user_parts.append(f"Источник: {source_url}")
    user_parts.append(f"Задание №{task_number}:")
    user_parts.append('')
    user_parts.append(task_text[:4000])
    if attachments_content:
        user_parts.append('')
        user_parts.append(attachments_content)
    user = '\n'.join(user_parts)
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

            source_url = _get_source_url(task)
            app_root = app.root_path or os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
            attachments_content = _extract_attachments_content(task, app_root)
            knowledge = load_task_knowledge(task.task_id, task_number=task.task_number)
            messages = _build_solution_prompt(task_text, task.task_number, source_url, attachments_content, knowledge)

            try:
                solution_text = llm.chat(messages=messages, temperature=0.2, max_tokens=1500)
                if not solution_text or len(solution_text.strip()) < 20:
                    print(f'  task_id={task.task_id}: пустой ответ LLM')
                    errors += 1
                    continue

                sol_text = solution_text.strip()
                # Всегда добавляем префикс: источник и условие (гарантированно в выводе)
                prefix_parts = []
                if source_url:
                    prefix_parts.append(f"**Источник:** [{source_url}]({source_url})")
                if task_text:
                    cond_short = (task_text[:600] + '...') if len(task_text) > 600 else task_text
                    prefix_parts.append(f"**Условие задачи:** {cond_short}")
                if prefix_parts:
                    prefix = '\n\n'.join(prefix_parts) + '\n\n---\n\n'
                    sol_text = prefix + sol_text

                extracted = _extract_answer_from_solution(sol_text)
                needs_review = not _answers_match(task.answer, extracted)

                if not args.dry_run:
                    if existing:
                        existing.solution_text = sol_text
                        existing.source = 'llm'
                        existing.needs_manual_review = needs_review
                    else:
                        db.session.add(TaskSolution(
                            task_id=task.task_id,
                            solution_text=sol_text,
                            source='llm',
                            needs_manual_review=needs_review,
                        ))
                    done += 1
                    if done % args.batch_size == 0:
                        db.session.commit()
                else:
                    done += 1
                    rev = ' [РУЧНАЯ ПРОВЕРКА]' if needs_review else ''
                    print(f'  [dry-run] task_id={task.task_id} -> {len(sol_text)} chars{rev}')

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
