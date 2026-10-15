"""Classify exact-ID FIPI math cards against the official 2027 profile KIM plan."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TASK_DESCRIPTIONS = {
    1: 'Планиметрия', 2: 'Векторы', 3: 'Стереометрия',
    4: 'Вероятность события', 5: 'Сложные вероятности',
    6: 'Случайная величина', 7: 'Уравнения', 8: 'Преобразование выражений',
    9: 'Производная и исследование функций', 10: 'Прикладная задача',
    11: 'Текстовая задача', 12: 'Графики функций',
    13: 'Финансовая математика', 14: 'Уравнение с развёрнутым ответом',
    15: 'Стереометрическая задача', 16: 'Неравенство',
    17: 'Моделирование и оптимизация', 18: 'Планиметрическая задача',
    19: 'Задача с параметром', 20: 'Числа и их свойства',
}
PRIMARY_SCORE = {**{number: 1 for number in range(1, 14)}, 14: 2, 15: 3, 16: 2, 17: 2, 18: 3, 19: 4, 20: 4}
CLASSIFIABLE = set(range(1, 6)) | set(range(7, 13)) | set(range(14, 21))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup-path', type=Path)
    args = parser.parse_args()
    rows = json.loads(args.input.read_text(encoding='utf-8'))

    from app import create_app
    from core.db_models import Course, CourseTaskTemplate, Tasks, db

    with create_app().app_context():
        course = Course.query.filter_by(slug='ege_math_profile').one()
        by_key = {task.source_key: task for task in Tasks.query.filter_by(course_id=course.id).all()}
        decisions = []
        counts = Counter()
        for row in rows:
            task = by_key.get(row.get('target_source_key'))
            if task is None:
                counts['missing_task'] += 1
                continue
            qid = parse_qs(urlsplit(task.source_url or '').query).get('qid', [''])[0].upper()
            if qid != str(row.get('reshai_id') or '').upper():
                raise ValueError(f'FIPI ID mismatch for task {task.task_id}')
            number = row.get('task_number')
            answer_type = row.get('answer_type')
            expected_type = 'short_answer' if isinstance(number, int) and number <= 13 else 'long_answer'
            if number not in CLASSIFIABLE or answer_type != expected_type:
                counts['unclassified'] += 1
                continue
            if number <= 13:
                ready = bool((task.answer or '').strip() and row.get('answer_verified'))
            else:
                ready = bool((row.get('solution') or '').strip())
            decisions.append((task, row, ready))
            counts['classified'] += 1
            counts['ready' if ready else 'needs_review'] += 1
            counts[f'number_{number}'] += 1

        print(json.dumps({'exam': 'ege_math_profile', 'rows': len(rows), 'counts': counts}, ensure_ascii=False, default=dict))
        if not args.apply:
            return
        if args.backup_path is None:
            parser.error('--apply requires --backup-path')
        snapshot = {
            'tasks': [
                {'task_id': task.task_id, 'task_number': task.task_number, 'source_task_number': task.source_task_number,
                 'exam_year': task.exam_year, 'is_active': task.is_active, 'ingest_status': task.ingest_status,
                 'prototype_status': task.prototype_status, 'difficulty_level': task.difficulty_level,
                 'max_score': task.max_score, 'answer_spec': task.answer_spec}
                for task, _, _ in decisions
            ],
            'templates': [
                {'id': template.id, 'task_number': template.task_number, 'max_primary_score': template.max_primary_score,
                 'requires_manual_review': template.requires_manual_review, 'description': template.description}
                for template in CourseTaskTemplate.query.filter_by(course_id=course.id).all()
            ],
        }
        args.backup_path.parent.mkdir(parents=True, exist_ok=True)
        with args.backup_path.open('x', encoding='utf-8') as backup:
            json.dump(snapshot, backup, ensure_ascii=False, indent=2)

        for number, description in TASK_DESCRIPTIONS.items():
            template = CourseTaskTemplate.query.filter_by(course_id=course.id, task_number=number).one_or_none()
            if template is None:
                template = CourseTaskTemplate(course_id=course.id, task_number=number)
                db.session.add(template)
            template.max_primary_score = PRIMARY_SCORE[number]
            template.requires_manual_review = number >= 14
            template.description = description

        for task, row, ready in decisions:
            number = row['task_number']
            task.task_number = number
            task.source_task_number = number
            task.exam_year = 2027
            task.prototype_status = 'real'
            task.difficulty_level = 1 if number in {1, 2, 3, 4, 7, 8} else (3 if number in {19, 20} else 2)
            task.max_score = PRIMARY_SCORE[number]
            spec = dict(task.answer_spec or {})
            spec['type'] = row['answer_type']
            task.answer_spec = spec
            task.is_active = ready
            task.ingest_status = 'ready' if ready else ('needs_answer_review' if task.answer else 'needs_answer')
        db.session.commit()
        print(json.dumps({'applied': True, 'counts': counts}, ensure_ascii=False, default=dict))


if __name__ == '__main__':
    main()
