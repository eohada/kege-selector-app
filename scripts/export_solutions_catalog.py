#!/usr/bin/env python3
"""
Экспорт эталонных решений в читаемый каталог Markdown.

Создаёт data/reference_solutions/ с файлами:
  - index.md — оглавление по заданиям
  - task_01.md … task_27.md — решения по каждому номеру (easy/medium/hard)

Для просмотра, анализа и обучения модели.
"""
from __future__ import annotations

import json
import os
import re
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
PROTOTYPES_DIR = os.path.join(REPO_ROOT, 'data', 'reference_prototypes')
OUTPUT_DIR = os.path.join(REPO_ROOT, 'data', 'reference_solutions')
TASK_PATTERN = re.compile(r'^task_(\d+)$')
DIFF_ORDER = ('easy', 'medium', 'hard')


def _strip_html(s: str) -> str:
    if not s:
        return ''
    return re.sub(r'<[^>]+>', ' ', s).strip()


def _solution_to_markdown(proto: dict) -> str:
    """Конвертирует solution в Markdown."""
    solution = proto.get('solution')
    if not isinstance(solution, dict):
        return ''
    steps = solution.get('steps') or []
    parts = []
    for s in steps:
        step_num = s.get('step', '?')
        explanation = (s.get('explanation') or '').strip()
        if not explanation:
            continue
        part = f"### Шаг {step_num}\n\n{explanation}"
        if s.get('code'):
            part += f"\n\n```python\n{s['code'].strip()}\n```"
        if s.get('formula'):
            part += f"\n\n*Формула:* {s['formula']}"
        parts.append(part)
    if not parts:
        return ''
    main = '\n\n'.join(parts)
    variants = solution.get('variants') or []
    if variants:
        main += '\n\n---\n\n### Альтернативные решения\n\n'
        for v in variants:
            if not isinstance(v, dict):
                continue
            name = (v.get('name') or 'Вариант').strip()
            v_steps = v.get('steps') or []
            main += f"**{name}:**\n\n"
            for i, vs in enumerate(v_steps, 1):
                ex = (vs.get('explanation') or '').strip()
                if ex:
                    main += f"{i}. {ex}\n\n"
    answer = proto.get('answer', '')
    if answer:
        main += f"**Ответ:** `{answer}`"
    return main.strip()


def _collect_prototypes() -> dict[int, list[tuple[str, dict]]]:
    """Собирает прототипы по task_number."""
    result = {}
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
                    if isinstance(data, dict) and data.get('solution'):
                        if task_num not in result:
                            result[task_num] = []
                        result[task_num].append((diff, data))
                except Exception:
                    pass
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Экспорт решений в каталог Markdown')
    parser.add_argument('--output-dir', default=OUTPUT_DIR, help='Каталог вывода')
    parser.add_argument('--dry-run', action='store_true', help='Не записывать файлы')
    args = parser.parse_args()

    if not os.path.isdir(PROTOTYPES_DIR):
        print(f'Каталог не найден: {PROTOTYPES_DIR}', file=sys.stderr)
        return 1

    os.makedirs(args.output_dir, exist_ok=True)

    collected = _collect_prototypes()
    index_lines = ['# Каталог эталонных решений\n\n', '| № | Файл | Уровни |\n', '|---|-------|--------|\n']

    for task_num in sorted(collected.keys()):
        protos = collected[task_num]
        # Сортируем: easy, medium, hard
        protos_sorted = sorted(protos, key=lambda x: DIFF_ORDER.index(x[0]) if x[0] in DIFF_ORDER else 99)

        md_parts = [f'# Задание {task_num}\n\n']
        levels = []

        for diff, proto in protos_sorted:
            topic = (proto.get('topic_name') or proto.get('topic_code') or '').strip()
            levels.append(diff)
            text = proto.get('prototype', {}).get('text', '')
            md_parts.append(f'## {diff.capitalize()}\n\n')
            if topic:
                md_parts.append(f'*Тема: {topic}*\n\n')
            md_parts.append('### Условие\n\n')
            md_parts.append(_strip_html(text) + '\n\n')
            md_parts.append('### Решение\n\n')
            md_parts.append(_solution_to_markdown(proto) + '\n\n---\n\n')

        index_lines.append(f'| {task_num} | [task_{task_num:02d}.md](task_{task_num:02d}.md) | {", ".join(levels)} |\n')

        out_path = os.path.join(args.output_dir, f'task_{task_num:02d}.md')
        if not args.dry_run:
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(''.join(md_parts))

    index_path = os.path.join(args.output_dir, 'index.md')
    if not args.dry_run:
        with open(index_path, 'w', encoding='utf-8') as f:
            f.writelines(index_lines)

    print(f'[OK] Экспорт в {args.output_dir}')
    print(f'  Заданий: {len(collected)}')
    print(f'  index.md, task_01.md … task_27.md')
    if args.dry_run:
        print('  (dry-run: файлы не записаны)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
