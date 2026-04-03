#!/usr/bin/env python3
"""
Создать новый файл эталонного прототипа из шаблона.

Копирует _template_example.json в нужную ячейку и подставляет task_number, difficulty.

Запуск:
  python scripts/new_prototype.py --task 5 --difficulty medium [--name proto_001]
  python scripts/new_prototype.py -t 12 -d hard

По умолчанию имя файла: proto_001.json (или следующий свободный номер в каталоге).
"""
import os
import sys
import json
import argparse
import glob

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
PROTOTYPES_DIR = os.path.join(REPO_ROOT, 'data', 'reference_prototypes')
TEMPLATE_PATH = os.path.join(PROTOTYPES_DIR, '_template_example.json')

DIFFICULTY_LEVEL_MAP = {'easy': 1, 'medium': 2, 'hard': 3}


def next_available_name(dirpath: str, base: str = 'proto') -> str:
    """Возвращает proto_NNN.json с первым свободным NNN в каталоге."""
    existing = glob.glob(os.path.join(dirpath, f'{base}_*.json'))
    used = set()
    for p in existing:
        name = os.path.basename(p)
        try:
            num = int(name.replace(base + '_', '').replace('.json', ''))
            used.add(num)
        except ValueError:
            pass
    n = 1
    while n in used:
        n += 1
    return f'{base}_{n:03d}.json'


def main():
    parser = argparse.ArgumentParser(description='Создать новый прототип из шаблона')
    parser.add_argument('-t', '--task', type=int, required=True, metavar='N', help='Номер задания ЕГЭ (1–27)')
    parser.add_argument('-d', '--difficulty', choices=['easy', 'medium', 'hard'], required=True, help='Уровень сложности')
    parser.add_argument('-n', '--name', default=None, help='Имя файла (по умолчанию proto_001.json или следующий номер)')
    args = parser.parse_args()

    if not 1 <= args.task <= 27:
        print('Ошибка: --task должен быть от 1 до 27', file=sys.stderr)
        sys.exit(1)

    if not os.path.isfile(TEMPLATE_PATH):
        print(f'Ошибка: шаблон не найден: {TEMPLATE_PATH}', file=sys.stderr)
        sys.exit(1)

    task_dir = os.path.join(PROTOTYPES_DIR, f'task_{args.task:02d}', args.difficulty)
    os.makedirs(task_dir, exist_ok=True)

    if args.name:
        name = args.name if args.name.endswith('.json') else args.name + '.json'
    else:
        name = next_available_name(task_dir)

    out_path = os.path.join(task_dir, name)

    if os.path.isfile(out_path):
        print(f'Файл уже существует: {out_path}', file=sys.stderr)
        sys.exit(1)

    with open(TEMPLATE_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    data['task_number'] = args.task
    data['difficulty_level'] = DIFFICULTY_LEVEL_MAP[args.difficulty]
    data['difficulty_label'] = args.difficulty
    if '_comment' in data:
        del data['_comment']

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f'Создан: {os.path.relpath(out_path, REPO_ROOT)}')
    print('Отредактируй topic_code, topic_name, prototype.text, solution, answer, hint_ladder и т.д.')


if __name__ == '__main__':
    main()
