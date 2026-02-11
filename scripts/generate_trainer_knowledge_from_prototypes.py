#!/usr/bin/env python3
"""
Генерация trainer_knowledge/tasks/by_number/*.json из reference_prototypes.

Читает data/reference_prototypes/task_NN/<easy|medium|hard>/*.json, извлекает
hint_ladder и common_mistakes, конвертирует в формат trainer_knowledge и сохраняет
в trainer_knowledge/tasks/by_number/N.json.

Приоритет при нескольких уровнях: easy → medium → hard (первый с hint_ladder).

Запуск:
  python scripts/generate_trainer_knowledge_from_prototypes.py [--dry-run] [--force]
"""
from __future__ import annotations

import json
import os
import re
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
PROTOTYPES_DIR = os.path.join(REPO_ROOT, 'data', 'reference_prototypes')
OUTPUT_DIR = os.path.join(REPO_ROOT, 'trainer_knowledge', 'tasks', 'by_number')

DIFF_ORDER = ('easy', 'medium', 'hard')
TASK_PATTERN = re.compile(r'^task_(\d+)$')


def _collect_prototypes() -> dict[int, list[tuple[str, dict]]]:
    """Собирает прототипы по task_number. Возвращает {1: [('easy', data), ...], ...}."""
    result: dict[int, list[tuple[str, dict]]] = {}

    for name in sorted(os.listdir(PROTOTYPES_DIR)):
        m = TASK_PATTERN.match(name)
        if not m:
            continue
        task_num = int(m.group(1))
        task_dir = os.path.join(PROTOTYPES_DIR, name)
        if not os.path.isdir(task_dir):
            continue

        for diff in DIFF_ORDER:
            diff_dir = os.path.join(task_dir, diff)
            if not os.path.isdir(diff_dir):
                continue
            for fn in os.listdir(diff_dir):
                if not fn.endswith('.json') or fn.startswith('_'):
                    continue
                path = os.path.join(diff_dir, fn)
                if not os.path.isfile(path):
                    continue
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        if task_num not in result:
                            result[task_num] = []
                        result[task_num].append((diff, data))
                except Exception:
                    pass

    return result


def _pick_best(protos: list[tuple[str, dict]]) -> dict | None:
    """Выбирает первый прототип с непустым hint_ladder (приоритет: easy → medium → hard)."""
    def order_key(item: tuple[str, dict]) -> int:
        d, _ = item
        return DIFF_ORDER.index(d) if d in DIFF_ORDER else 999

    for _, data in sorted(protos, key=order_key):
        ladder = data.get('hint_ladder')
        if isinstance(ladder, list) and ladder:
            return data
    return None


def _convert_hint_ladder(proto: dict) -> list[dict]:
    """Конвертирует hint_ladder: text → hint."""
    ladder = proto.get('hint_ladder') or []
    out = []
    for it in ladder:
        if not isinstance(it, dict):
            continue
        level = it.get('level')
        text = (it.get('text') or it.get('hint') or '').strip()
        if not text or level is None:
            continue
        out.append({'level': int(level), 'hint': text})
    return out


def _solution_to_markdown(proto: dict) -> str:
    """Конвертирует solution из эталона в читаемый Markdown."""
    solution = proto.get('solution')
    if not isinstance(solution, dict):
        return ''
    steps = solution.get('steps') or []
    if not steps:
        return ''
    parts = []
    for s in steps:
        step_num = s.get('step', '?')
        explanation = (s.get('explanation') or '').strip()
        if not explanation:
            continue
        part = f"**Шаг {step_num}.** {explanation}"
        if s.get('code'):
            part += f"\n\n```python\n{s['code'].strip()}\n```"
        if s.get('formula'):
            part += f"\n\nФормула: {s['formula']}"
        parts.append(part)
    if not parts:
        return ''
    main = '\n\n'.join(parts)
    variants = solution.get('variants') or []
    if variants:
        main += '\n\n---\n\n**Альтернативные решения:**\n\n'
        for v in variants:
            if not isinstance(v, dict):
                continue
            name = (v.get('name') or 'Вариант').strip()
            v_steps = v.get('steps') or []
            v_lines = [f"*{name}*:"]
            for vs in v_steps:
                ex = (vs.get('explanation') or '').strip()
                if ex:
                    v_lines.append(f"- {ex}")
            main += '\n'.join(v_lines) + '\n\n'
    answer = proto.get('answer', '')
    if answer:
        main += f"\n\n**Ответ:** {answer}"
    return main.strip()


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Генерация trainer_knowledge из эталонов')
    parser.add_argument('--dry-run', action='store_true', help='Не записывать файлы')
    parser.add_argument('--force', action='store_true', help='Перезаписать существующие. По умолчанию 19, 20, 21 не трогаем (ручные).')
    args = parser.parse_args()

    if not os.path.isdir(PROTOTYPES_DIR):
        print(f'Каталог эталонов не найден: {PROTOTYPES_DIR}', file=sys.stderr)
        return 1

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    collected = _collect_prototypes()
    created = 0
    skipped = 0
    skipped_existing = 0
    no_hints = []

    for task_num in sorted(collected.keys()):
        protos = collected[task_num]
        best = _pick_best(protos)
        if not best:
            no_hints.append(task_num)
            continue

        ladder = _convert_hint_ladder(best)
        if not ladder:
            no_hints.append(task_num)
            continue

        common_mistakes = best.get('common_mistakes')
        if not isinstance(common_mistakes, list) or not common_mistakes:
            solution = best.get('solution') or {}
            common_mistakes = (solution.get('common_mistakes') or []) if isinstance(solution, dict) else []
        if not isinstance(common_mistakes, list):
            common_mistakes = []
        common_mistakes = [str(x).strip() for x in common_mistakes if x][:10]

        topic = (best.get('topic_name') or best.get('topic_code') or '').strip()
        title = f'Задание {task_num}' + (f': {topic}' if topic else '')

        reference_solution = _solution_to_markdown(best)

        out = {
            'task_id': 0,
            'task_number': task_num,
            'language': 'python',
            'title': title,
            'common_mistakes': common_mistakes,
            'hint_ladder': ladder,
            'reference_solution': reference_solution,
            'tests': [],
        }

        # 19, 20, 21 — ручные файлы (делители/простые/63), не генерируем из эталонов
        if task_num in (19, 20, 21):
            skipped_existing += 1
            continue

        out_path = os.path.join(OUTPUT_DIR, f'{task_num}.json')
        if os.path.exists(out_path) and not args.force:
            skipped_existing += 1
            continue

        if not args.dry_run:
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
            created += 1
        else:
            print(f'[dry-run] would write {out_path} ({len(ladder)} hints)')
            created += 1

    print(f'Создано/обновлено: {created}')
    if skipped_existing:
        print(f'Пропущено (уже есть, используй --force): {skipped_existing}')
    if no_hints:
        print(f'Без hint_ladder: {no_hints}')
    if args.dry_run:
        print('(dry-run: файлы не записаны)')

    return 0


if __name__ == '__main__':
    sys.exit(main())
