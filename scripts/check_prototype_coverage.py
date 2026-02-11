#!/usr/bin/env python3
"""
Проверка покрытия эталонных прототипов: по каждому заданию 1–27 должен быть хотя бы один прототип.

Запуск:
  python scripts/check_prototype_coverage.py [--fail-on-gap]
  --fail-on-gap: выйти с кодом 1, если хотя бы один тип заданий не покрыт (для CI)

Выводит таблицу: задание | easy | medium | hard | всего
"""
import os
import sys
import json
import argparse
import glob
from collections import defaultdict

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
PROTOTYPES_DIR = os.path.join(REPO_ROOT, 'data', 'reference_prototypes')


def main():
    parser = argparse.ArgumentParser(description='Проверка покрытия прототипов по заданиям 1–27')
    parser.add_argument('--fail-on-gap', action='store_true', help='Выход с кодом 1 при отсутствии прототипа по любому заданию')
    args = parser.parse_args()

    pattern = os.path.join(PROTOTYPES_DIR, '**', '*.json')
    files = [f for f in glob.glob(pattern, recursive=True)
             if os.path.basename(f) != 'prototype_schema.json' and not os.path.basename(f).startswith('_')]

    coverage = defaultdict(lambda: {'easy': 0, 'medium': 0, 'hard': 0})

    for filepath in files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue
        label = data.get('difficulty_label') or 'medium'
        # Серия 19–21: один файл покрывает все номера из series_task_numbers
        task_numbers = data.get('series_task_numbers')
        if isinstance(task_numbers, list) and len(task_numbers) > 0:
            task_numbers = [t for t in task_numbers if isinstance(t, int) and 1 <= t <= 27]
        else:
            tn = data.get('task_number')
            task_numbers = [tn] if isinstance(tn, int) and 1 <= tn <= 27 else []
        for tn in task_numbers:
            if label not in coverage[tn]:
                coverage[tn][label] = 0
            coverage[tn][label] += 1

    print('Задание |  Easy | Medium |  Hard | Всего')
    print('--------|-------|--------|-------|------')

    gaps = []
    for tn in range(1, 28):
        c = coverage[tn]
        total = c['easy'] + c['medium'] + c['hard']
        if total == 0:
            gaps.append(tn)
        print(f"     #{tn:<2} | {c['easy']:>5} | {c['medium']:>6} | {c['hard']:>5} | {total:>5}")

    total_all = sum(coverage[tn]['easy'] + coverage[tn]['medium'] + coverage[tn]['hard'] for tn in range(1, 28))
    print('--------|-------|--------|-------|------')
    print(f"  Итого |       |        |       | {total_all:>5}")
    print()

    if gaps:
        print(f"Нет прототипов по заданиям: {', '.join(f'#{n}' for n in gaps)}")
        if args.fail_on_gap:
            sys.exit(1)
    else:
        print('Покрытие: по каждому заданию 1–27 есть хотя бы один прототип.')
    sys.exit(0)


if __name__ == '__main__':
    main()
