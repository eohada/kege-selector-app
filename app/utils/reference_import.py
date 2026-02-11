"""
Импорт эталонных прототипов (reference_prototypes) в таблицу Tasks.
Используется скриптом import_prototype_to_tasks.py и админ-кнопкой «Синхронизировать эталоны».
"""
import os
import json
import re
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
PROTOTYPES_DIR = os.path.join(REPO_ROOT, 'data', 'reference_prototypes')
KEGE_JSON = os.path.join(REPO_ROOT, 'data', 'analytics_kege_difficulty.json')


def parse_combined_answer(answer_str: str, task_numbers: list) -> dict:
    out = {tn: '' for tn in task_numbers}
    s = (answer_str or '').strip()
    if not s:
        return out
    parts = [p.strip() for p in re.split(r'\s*;\s*', s)]
    by_num = {}
    for part in parts:
        m = re.match(r'^(\d+)\s*:\s*(.*)$', part, re.DOTALL)
        if m:
            by_num[int(m.group(1))] = m.group(2).strip()
    if by_num:
        for tn in task_numbers:
            out[tn] = by_num.get(tn, '')
        return out
    for i, tn in enumerate(task_numbers):
        if i < len(parts):
            out[tn] = parts[i]
    return out


def get_node_code_by_task_number(task_number: int) -> str | None:
    if not os.path.isfile(KEGE_JSON):
        return None
    with open(KEGE_JSON, 'r', encoding='utf-8') as f:
        rows = json.load(f)
    for row in rows:
        if row.get('task_number') == task_number:
            return row.get('node_code')
    return None


def run_import(data: dict, source_prototype_key: str, dry_run: bool = False, db=None, subject=None):
    """
    Создаёт или обновляет задания в БД по данным эталонного JSON.
    Возвращает (created_count, updated_count).
    """
    from core.db_models import Tasks, KnowledgeNode

    if not subject or not db:
        return 0, 0
    prototype = data.get('prototype') or {}
    content_html = (prototype.get('text') or '').strip() or '(нет текста)'
    difficulty_level = data.get('difficulty_level')
    hints = data.get('hint_ladder') if data.get('hint_ladder') else None

    task_numbers = data.get('series_task_numbers')
    if isinstance(task_numbers, list) and len(task_numbers) >= 2:
        task_numbers = [t for t in task_numbers if isinstance(t, int) and 1 <= t <= 27]
    else:
        task_numbers = None

    if task_numbers:
        answers = parse_combined_answer(data.get('answer') or '', task_numbers)
        existing = {}
        if source_prototype_key:
            for t in Tasks.query.filter(
                Tasks.source_prototype == source_prototype_key,
                Tasks.task_number.in_(task_numbers),
            ).all():
                existing[t.task_number] = t
        created_count = 0
        updated_count = 0
        for tn in task_numbers:
            node_code = get_node_code_by_task_number(tn)
            knowledge_node_id = None
            if node_code:
                node = KnowledgeNode.query.filter_by(subject_id=subject.id, code=node_code).first()
                if node:
                    knowledge_node_id = node.id
            ans = (answers.get(tn) or '').strip() or None
            if existing.get(tn):
                task = existing[tn]
                if not dry_run:
                    task.content_html = content_html
                    task.answer = ans
                    task.difficulty_level = difficulty_level
                    task.hints = hints
                    task.knowledge_node_id = knowledge_node_id
                updated_count += 1
            else:
                if not dry_run:
                    task = Tasks(
                        task_number=tn,
                        content_html=content_html,
                        answer=ans,
                        knowledge_node_id=knowledge_node_id,
                        difficulty_level=difficulty_level,
                        hints=hints,
                        source_prototype=source_prototype_key,
                        site_task_id=None,
                        source_url=None,
                    )
                    db.session.add(task)
                created_count += 1
        return created_count, updated_count

    tn = data.get('task_number')
    if not isinstance(tn, int) or tn < 1 or tn > 27:
        return 0, 0
    node_code = get_node_code_by_task_number(tn) or data.get('topic_code')
    knowledge_node_id = None
    if node_code:
        node = KnowledgeNode.query.filter_by(subject_id=subject.id, code=node_code).first()
        if node:
            knowledge_node_id = node.id
    if not dry_run:
        task = Tasks(
            task_number=tn,
            content_html=content_html,
            answer=(data.get('answer') or '').strip() or None,
            knowledge_node_id=knowledge_node_id,
            difficulty_level=difficulty_level,
            hints=hints,
            source_prototype=source_prototype_key or None,
            site_task_id=None,
            source_url=None,
        )
        db.session.add(task)
    return 1, 0


def sync_all_series_prototypes(dry_run: bool = False):
    """
    Сканирует data/reference_prototypes, находит все JSON с series_task_numbers,
    для каждого выполняет run_import. Возвращает список {path, created, updated}.
    """
    import glob
    from app.models import db
    from core.db_models import Subject

    subject = Subject.query.filter_by(slug='kege').first()
    if not subject:
        return []
    pattern = os.path.join(PROTOTYPES_DIR, '**', '*.json')
    files = [
        f for f in glob.glob(pattern, recursive=True)
        if not os.path.basename(f).startswith('_') and os.path.basename(f) != 'prototype_schema.json'
    ]
    results = []
    for path in sorted(files):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            continue
        if not isinstance(data.get('series_task_numbers'), list) or len(data.get('series_task_numbers', [])) < 2:
            continue
        try:
            rel = os.path.relpath(path, PROTOTYPES_DIR).replace('\\', '/')
        except ValueError:
            rel = os.path.basename(path)
        created, updated = run_import(data, rel, dry_run=dry_run, db=db, subject=subject)
        if created or updated:
            results.append({'path': rel, 'created': created, 'updated': updated})
    return results
