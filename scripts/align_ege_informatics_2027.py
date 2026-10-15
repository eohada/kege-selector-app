"""Align existing Informatics bank positions with the published 2027 KIM draft."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

NETWORK = re.compile(r'маск\w*\s+сет|ip[\s-]*адрес|tcp\s*/\s*ip|подсет', re.I)
GRAPH = re.compile(r'граф|вершин|р[её]бер|кратчайш\w*\s+пут|ориентированн', re.I)
EXECUTOR = re.compile(r'исполнител|траектор|последовательност\w*\s+(?:команд|заклинан|преобразован)|(?:сколько\s+существует|количество)\s+(?:различных\s+)?программ', re.I)


def destination(task) -> tuple[str, int | None]:
    text = BeautifulSoup(task.content_html or '', 'html.parser').get_text(' ', strip=True)
    if task.task_number == 10:
        return ('keep_network', 10) if NETWORK.search(text) else ('retire_word', None)
    if task.task_number == 13:
        if NETWORK.search(text):
            return 'network_to_10', 10
        if EXECUTOR.search(text):
            return 'keep_executor', 13
        return 'review_13', None
    if task.task_number == 23:
        if GRAPH.search(text) and not EXECUTOR.search(text):
            return 'keep_graph', 23
        if EXECUTOR.search(text) or 'заклинан' in text.lower():
            return 'executor_to_13', 13
        return 'review_23', None
    raise ValueError(f'Unexpected task number {task.task_number}')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup-path', type=Path)
    args = parser.parse_args()

    from app import create_app
    from core.db_models import Course, Tasks, db

    with create_app().app_context():
        course = Course.query.filter_by(slug='ege_informatics').one()
        tasks = Tasks.query.filter(Tasks.course_id == course.id, Tasks.task_number.in_((10, 13, 23))).order_by(Tasks.task_id).all()
        decisions = [(task, *destination(task)) for task in tasks]
        counts = Counter(action for _, action, _ in decisions)
        unresolved = [(task.task_id, action) for task, action, _ in decisions if action.startswith('review_')]
        print(json.dumps({'scanned': len(tasks), 'actions': counts, 'unresolved': unresolved}, ensure_ascii=False, default=dict))
        if not args.apply:
            return
        if unresolved:
            raise SystemExit('Unclassified tasks found; no changes applied')
        if args.backup_path is None:
            parser.error('--apply requires --backup-path')

        snapshot = [
            {
                'task_id': task.task_id,
                'task_number': task.task_number,
                'source_task_number': task.source_task_number,
                'exam_year': task.exam_year,
                'is_active': task.is_active,
                'prototype_status': task.prototype_status,
                'ingest_status': task.ingest_status,
            }
            for task, _, _ in decisions
        ]
        args.backup_path.parent.mkdir(parents=True, exist_ok=True)
        with args.backup_path.open('x', encoding='utf-8') as backup:
            json.dump(snapshot, backup, ensure_ascii=False, indent=2)

        for task, action, target in decisions:
            if task.source_task_number is None:
                task.source_task_number = task.task_number
            if action == 'retire_word':
                task.is_active = False
                task.prototype_status = 'practice_only'
                task.ingest_status = 'retired_2027'
            else:
                task.task_number = target
                if task.exam_year is None:
                    task.exam_year = 2027
                if task.prototype_status == 'unreviewed':
                    task.prototype_status = 'real'
        db.session.commit()
        print(json.dumps({'applied': True, 'scanned': len(tasks), 'actions': counts}, ensure_ascii=False, default=dict))


if __name__ == '__main__':
    main()
