#!/usr/bin/env python3
"""
Проверка полноты контента эталонных прототипов (Фаза 1).

Выводит отчёт: у каких файлов не заполнены или слабо заполнены:
  - hint_ladder (лестница подсказок)
  - solution.common_mistakes (типовые ошибки)
  - solution.steps (эталонное решение — хотя бы 2 шага)

Запуск:
  python scripts/check_prototype_content_readiness.py [--json]
  --json: вывести результат в виде JSON (список путей с полями missing_hints, missing_mistakes, few_steps)
"""
import os
import sys
import json
import argparse
import glob
from pathlib import Path

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
PROTOTYPES_DIR = os.path.join(REPO_ROOT, 'data', 'reference_prototypes')


def check_one(path: str, data: dict) -> dict:
    """Возвращает словарь с флагами: missing_hints, missing_mistakes, few_steps."""
    rel = os.path.relpath(path, PROTOTYPES_DIR).replace('\\', '/')
    out = {'path': rel, 'missing_hints': False, 'missing_mistakes': False, 'few_steps': False}

    hint_ladder = data.get('hint_ladder')
    if not isinstance(hint_ladder, list) or len(hint_ladder) < 2:
        out['missing_hints'] = True

    sol = data.get('solution')
    if isinstance(sol, dict):
        steps = sol.get('steps')
        if not isinstance(steps, list) or len(steps) < 2:
            out['few_steps'] = True
        mistakes = sol.get('common_mistakes')
        if not isinstance(mistakes, list) or len(mistakes) == 0:
            out['missing_mistakes'] = True
    else:
        out['few_steps'] = True

    return out


def main():
    parser = argparse.ArgumentParser(description='Проверка полноты контента прототипов (Фаза 1)')
    parser.add_argument('--json', action='store_true', help='Вывод в JSON')
    args = parser.parse_args()

    pattern = os.path.join(PROTOTYPES_DIR, '**', '*.json')
    files = [
        f for f in glob.glob(pattern, recursive=True)
        if os.path.basename(f) != 'prototype_schema.json' and not os.path.basename(f).startswith('_')
    ]

    results = []
    for filepath in sorted(files):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue
        r = check_one(filepath, data)
        if r['missing_hints'] or r['missing_mistakes'] or r['few_steps']:
            results.append(r)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0

    if not results:
        print('Все проверенные прототипы имеют заполненные подсказки, типовые ошибки и не менее 2 шагов решения.')
        return 0

    print('Прототипы с неполным контентом (ревизия для Фазы 1):')
    print()
    missing_hints = [r['path'] for r in results if r['missing_hints']]
    missing_mistakes = [r['path'] for r in results if r['missing_mistakes']]
    few_steps = [r['path'] for r in results if r['few_steps']]

    if missing_hints:
        print(f'  Нет/короткая лестница подсказок (hint_ladder < 2): {len(missing_hints)}')
        for p in missing_hints[:20]:
            print(f'    - {p}')
        if len(missing_hints) > 20:
            print(f'    ... и ещё {len(missing_hints) - 20}')
        print()
    if missing_mistakes:
        print(f'  Нет типовых ошибок (common_mistakes): {len(missing_mistakes)}')
        for p in missing_mistakes[:20]:
            print(f'    - {p}')
        if len(missing_mistakes) > 20:
            print(f'    ... и ещё {len(missing_mistakes) - 20}')
        print()
    if few_steps:
        print(f'  Мало шагов решения (solution.steps < 2): {len(few_steps)}')
        for p in few_steps[:20]:
            print(f'    - {p}')
        if len(few_steps) > 20:
            print(f'    ... и ещё {len(few_steps) - 20}')
        print()

    print(f'Всего файлов с замечаниями: {len(results)} из {len(files)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
