"""Fill empty FIPI math fields from attributed, ID-matched Reshai records."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def validate_records(rows):
    if not isinstance(rows, list):
        raise ValueError('Expected an array of enrichment records')
    seen = set()
    for row in rows:
        key = str(row.get('target_source_key') or '')
        qid = str(row.get('reshai_id') or '').upper()
        if not re.fullmatch(r'fipi:ege-math-profile:[0-9a-f]{28,32}', key):
            raise ValueError(f'Invalid FIPI key: {key}')
        if not re.fullmatch(r'[0-9A-F]{6}', qid) or key in seen:
            raise ValueError(f'Invalid or duplicate enrichment ID: {qid}')
        seen.add(key)
        for field, suffix in [('source_url', ''), ('solution_url', '/solution')]:
            parsed = urlsplit(str(row.get(field) or ''))
            expected = f'/ege/subjects/math_profile/tasks/{qid}{suffix}'
            if parsed.scheme != 'https' or parsed.netloc != 'reshai.online' or parsed.path.upper() != expected.upper() or parsed.query or parsed.fragment:
                raise ValueError(f'Unexpected attribution URL for {qid}: {field}')
        if not isinstance(row.get('hints'), list) or any(not isinstance(h, str) for h in row['hints']):
            raise ValueError(f'Invalid hints for {qid}')
        for field in ('answer', 'solution'):
            if not isinstance(row.get(field), str) or len(row[field]) > 100000:
                raise ValueError(f'Invalid {field} for {qid}')
    return rows


def enrich(rows, *, apply=False):
    from core.db_models import TaskReview, TaskSolution, Tasks, db

    counts = Counter()
    for row in rows:
        try:
            task = Tasks.query.filter_by(source_key=row['target_source_key']).with_for_update().one_or_none()
            if task is None:
                counts['missing_target'] += 1
                db.session.rollback()
                continue
            original = urlsplit(task.source_url or '')
            original_qid = parse_qs(original.query).get('qid', [''])[0].upper()
            if original.hostname != 'ege.fipi.ru' or original_qid != row['reshai_id'].upper():
                raise ValueError(f'FIPI question identifier mismatch: {task.task_id}')
            answer = row['answer'].strip()
            if task.answer and answer and task.answer.strip() != answer:
                counts['answer_conflict'] += 1
                db.session.rollback()
                continue
            changes = Counter()
            if not task.answer and answer:
                task.answer = answer
                changes['answers_added'] += 1
            if not task.hints and row['hints']:
                task.hints = [
                    {'title': f'Подсказка {i}', 'text': hint + '\n\nИсточник: Решай — ' + row['source_url']}
                    for i, hint in enumerate(row['hints'], 1)
                ]
                changes['hints_added'] += 1
            solution = row['solution'].strip()
            existing_solution = TaskSolution.query.filter_by(task_id=task.task_id).one_or_none()
            if solution and existing_solution is None:
                db.session.add(TaskSolution(
                    task_id=task.task_id,
                    solution_text=solution + '\n\n[Источник решения: Решай](' + row['solution_url'] + ')',
                    source='import', needs_manual_review=True,
                ))
                changes['solutions_added'] += 1
            if changes:
                spec = dict(task.answer_spec or {})
                spec['enrichment_source'] = {'name': 'Решай', 'url': row['source_url'], 'solution_url': row['solution_url']}
                if changes['answers_added']:
                    spec['source_answer_verified'] = False
                    spec['provider_claims_answer_verified'] = bool(row.get('answer_verified'))
                    if not task.is_active:
                        task.ingest_status = 'needs_answer_review'
                task.answer_spec = spec
                review = TaskReview.query.filter_by(task_id=task.task_id).one_or_none()
                if review is None:
                    review = TaskReview(task_id=task.task_id, status='new')
                    db.session.add(review)
                note = f"Дополнено по совпадающему ID ФИПИ: {row['source_url']}. Нумерация источника не переносилась; независимая проверка ответа ещё не выполнена."
                if note not in (review.notes or ''):
                    review.notes = ((review.notes or '').rstrip() + '\n' + note).strip()
                counts.update(changes)
                counts['tasks_enriched'] += 1
            else:
                counts['unchanged'] += 1
            if apply:
                db.session.commit()
            else:
                db.session.rollback()
        except Exception:
            db.session.rollback()
            raise
    return dict(counts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--apply', action='store_true', help='Write empty fields; default is a rollback-only preview')
    args = parser.parse_args()
    rows = validate_records(json.loads(args.input.read_text(encoding='utf-8')))
    from app import create_app
    with create_app().app_context():
        print(json.dumps({'applied': args.apply, **enrich(rows, apply=args.apply)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
