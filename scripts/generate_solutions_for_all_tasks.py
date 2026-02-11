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


def _load_prototype_data(task) -> str:
    """Загрузить данные ТОЛЬКО если задание явно привязано к эталону (source_prototype).
    НЕ подставляем эталон по task_number — задания с kompege имеют свои графы/таблицы
    (другие буквы, другие числа). Подстановка чужого эталона даёт бред."""
    if not getattr(task, 'source_prototype', None):
        return ''
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    path = os.path.join(repo_root, 'data', 'reference_prototypes', task.source_prototype)
    if not os.path.isfile(path):
        return ''
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        proto = data.get('prototype') or {}
        text = (proto.get('text') or '').strip()
        if text and len(text) > 50:
            return _strip_html_preserve_tables(text)
    except Exception:
        pass
    return ''


def _extract_images_from_html(content_html: str, site_base: str = SITE_BASE) -> list[str | bytes]:
    """Извлекает картинки из content_html (img src): URL или data URI (base64). Возвращает list[str | bytes]."""
    if not content_html:
        return []
    srcs = re.findall(r'src=["\']([^"\']+)["\']', content_html, re.IGNORECASE)
    result: list[str | bytes] = []
    seen: set[str] = set()
    for s in srcs:
        s = (s or '').strip()
        if not s:
            continue
        # data:image/png;base64,iVBORw0KGgo...
        if s.lower().startswith('data:image/'):
            try:
                import base64
                parts = s.split(',', 1)
                if len(parts) == 2:
                    header = parts[0].lower()
                    if 'base64' in header:
                        fmt = header.split('/')[-1].split(';')[0]
                        if fmt in ('png', 'jpeg', 'jpg', 'tiff', 'bmp'):
                            data = base64.b64decode(parts[1].strip())
                            if data and len(data) <= 15 * 1024 * 1024:
                                result.append(data)
            except Exception:
                pass
            continue
        if s in seen:
            continue
        if s.startswith('//'):
            s = 'https:' + s
        elif s.startswith('/') and not s.startswith('//'):
            s = site_base.rstrip('/') + s
        ext = os.path.splitext(s.split('?')[0])[1].lower()
        if ext in ('.jpg', '.jpeg', '.png', '.tiff', '.tif', '.bmp'):
            result.append(s)
            seen.add(s)
    return result


def _strip_html_preserve_tables(html: str) -> str:
    """Извлечение текста с сохранением структуры таблиц."""
    if not html:
        return ''
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html[:8000], 'html.parser')
        tables = soup.find_all('table')
        for t in tables:
            rows = []
            for tr in t.find_all('tr'):
                cells = [td.get_text(separator=' ', strip=True) for td in tr.find_all(['th', 'td'])]
                if cells:
                    rows.append(' | '.join(cells))
            if rows:
                t.replace_with(f'\n[ТАБЛИЦА]\n' + '\n'.join(rows) + '\n[/ТАБЛИЦА]\n')
        text = soup.get_text(separator='\n', strip=True)
        return re.sub(r'\n{3,}', '\n\n', text).strip()
    except Exception:
        pass
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html)).strip()


def _build_solution_prompt(
    task_text: str,
    task_number: int,
    source_url: str | None,
    attachments_content: str,
    knowledge: dict | None,
    prototype_data: str,
    has_images: bool = False,
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
        "Используй **жирный** для заголовков шагов. Пиши чётко, структурированно.\n\n"
        "КРИТИЧНО: используй ТОЛЬКО данные из условия. Буквы и числа в графе/таблице — ТОЛЬКО из условия. "
        "Если в условии граф с буквами A,B,C — не используй А,Б,В. Если таблица даёт числа 18,22,17 — не выдумывай 10,8,7. "
        "НЕ подставляй данные из примеров или эталонов. "
        "Если условие ссылается на рисунок/граф/таблицу на картинке — при наличии приложенных изображений используй их для анализа. "
        "Если изображений нет и конкретные числа/буквы не даны в тексте — не решай «из головы», напиши: «Откройте источник по ссылке.» "
        "Если есть вложения (Excel, текст) — опирайся на их содержимое."
    )
    if has_images:
        system += (
            "\n\n[!] К заданию ПРИЛОЖЕНЫ изображения (граф, таблица и т.п.). "
            "Ты ОБЯЗАН проанализировать их визуально и решить задачу по ТОЛЬКО данным с картинок. "
            "ИГНОРИРУЙ любые примеры, эталоны — в них ДРУГИЕ числа и буквы. "
            "ЗАПРЕЩЕНО писать «откройте источник» — у тебя ЕСТЬ изображение.\n\n"
            "ОБЯЗАТЕЛЬНО: напиши ПОЛНОЕ пошаговое решение (Шаг 1, Шаг 2, ...) с объяснением. "
            "НЕЛЬЗЯ писать только ответ. Алгоритм для графов: сопоставь степени вершин (граф ↔ таблица), "
            "сопоставь буквы с номерами, затем возьми значения из таблицы. Ответ — последним."
        )
    ctx = []
    # При has_images не даём reference_solution — модель может взять оттуда числа вместо данных с картинки
    if knowledge and knowledge.get('reference_solution') and not has_images:
        ref = (knowledge.get('reference_solution') or '')[:1200]
        if ref:
            ctx.append(f"Пример СТИЛЯ решения (структура шагов). НЕ копируй буквы, числа, таблицу — в твоём задании они ДРУГИЕ:\n{ref}")
    user_parts = []
    if source_url:
        user_parts.append(f"Источник: {source_url}")
    user_parts.append(f"Задание №{task_number}:")
    user_parts.append('')
    user_parts.append(task_text[:4000])
    has_img_ref = 'рисунк' in task_text.lower() or 'таблиц' in task_text.lower()
    has_table_data = '[ТАБЛИЦА]' in task_text or ('|' in task_text and any(c.isdigit() for c in task_text))
    if has_img_ref and not has_table_data and not has_images:
        user_parts.append('')
        user_parts.append("[!] В условии упомянут рисунок/таблица, но конкретные числа не приведены. Изображений нет. Не выдумывай данные — напиши: «Откройте источник по ссылке.»")
    elif has_images:
        user_parts.append('')
        user_parts.append(
            "[!] К сообщению приложено изображение (граф и таблица). "
            "Проанализируй его: 1) сопоставь степени вершин графа и таблицы; 2) сопоставь буквы (A–H) с номерами (1–8); "
            "3) найди нужные значения в таблице. Напиши решение пошагово, ответ — в конце в формате **Ответ:** число."
        )
    # prototype_data — НЕ добавлять при has_images! Эталон содержит ДРУГИЕ числа/буквы — модель начинает путаться.
    if prototype_data and not has_images:
        user_parts.append('')
        user_parts.append("--- Точные данные графа/таблицы из эталона (используй их): ---")
        user_parts.append(prototype_data[:3500])
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

            task_text = _strip_html_preserve_tables(task.content_html or '')
            if len(task_text) < 30:
                skipped += 1
                continue

            source_url = _get_source_url(task)
            app_root = app.root_path or os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
            attachments_content = _extract_attachments_content(task, app_root)
            knowledge = load_task_knowledge(task.task_id, task_number=task.task_number)
            prototype_data = _load_prototype_data(task)
            image_sources = _extract_images_from_html(task.content_html or '')
            # Fallback: если в content_html нет img — kompege хранит картинки как /images/{id}.png (id = site_task_id или id из source_url)
            if not image_sources:
                sid = (task.site_task_id or '').strip()
                if not sid and source_url:
                    m = re.search(r'[?&]id=(\d+)', source_url)
                    if m:
                        sid = m.group(1)
                if sid and sid.isdigit():
                    image_sources = [f"{SITE_BASE}/images/{sid}.png"]
            print(f'  task_id={task.task_id}: {"%d image(s) for vision" % len(image_sources) if image_sources else "no images"}')
            messages = _build_solution_prompt(
                task_text, task.task_number, source_url, attachments_content, knowledge, prototype_data,
                has_images=bool(image_sources),
            )

            try:
                max_tok = 2000 if image_sources else 1500
                solution_text = llm.chat(
                    messages=messages, temperature=0.2, max_tokens=max_tok, image_sources=image_sources or None
                )
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
