#!/usr/bin/env python3
"""
Валидация эталонных прототипов из data/reference_prototypes/.

Проверяет:
  - JSON парсится без ошибок
  - Все обязательные поля из prototype_schema.json присутствуют
  - task_number 1–27, difficulty_level 1–10, difficulty_label in (easy, medium, hard)
  - prototype.text, input_format, answer_format; solution.steps; каждый step: step, explanation

Запуск:
  python scripts/validate_prototypes.py [--strict]
  --strict: считать предупреждения (например, пустой hint_ladder) ошибками

Выход: 0 — все файлы валидны, 1 — есть ошибки.
"""
import os
import sys
import json
import argparse
import glob

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
PROTOTYPES_DIR = os.path.join(REPO_ROOT, 'data', 'reference_prototypes')
SCHEMA_PATH = os.path.join(PROTOTYPES_DIR, 'prototype_schema.json')

REQUIRED_TOP = {'task_number', 'topic_code', 'topic_name', 'difficulty_level', 'difficulty_label', 'prototype', 'solution', 'answer'}
REQUIRED_PROTOTYPE = {'text', 'input_format', 'answer_format'}
REQUIRED_SOLUTION = {'steps'}
REQUIRED_STEP = {'step', 'explanation'}


def validate_one(proto: dict, path: str, strict: bool) -> list:
    """Возвращает список строк с ошибками (пустой — ок)."""
    errors = []

    for key in REQUIRED_TOP:
        if key not in proto:
            errors.append(f"{path}: отсутствует обязательное поле '{key}'")
    if errors:
        return errors  # дальше не проверяем без обязательных полей

    tn = proto.get('task_number')
    if not isinstance(tn, int) or tn < 1 or tn > 27:
        errors.append(f"{path}: task_number должен быть целым 1–27, получено: {tn!r}")

    dl = proto.get('difficulty_level')
    if not isinstance(dl, int) or dl < 1 or dl > 10:
        errors.append(f"{path}: difficulty_level должен быть целым 1–10, получено: {dl!r}")

    label = proto.get('difficulty_label')
    if label not in ('easy', 'medium', 'hard'):
        errors.append(f"{path}: difficulty_label должен быть easy|medium|hard, получено: {label!r}")

    # Соответствие label и level
    if dl is not None and label is not None:
        if (label == 'easy' and not (1 <= dl <= 3)) or (label == 'medium' and not (4 <= dl <= 7)) or (label == 'hard' and not (8 <= dl <= 10)):
            errors.append(f"{path}: difficulty_label '{label}' не соответствует difficulty_level {dl} (easy=1-3, medium=4-7, hard=8-10)")

    p = proto.get('prototype')
    if not isinstance(p, dict):
        errors.append(f"{path}: prototype должен быть объектом")
    else:
        for key in REQUIRED_PROTOTYPE:
            if key not in p:
                errors.append(f"{path}: prototype.{key} обязательно")
        if isinstance(p.get('text'), str) and not p['text'].strip():
            errors.append(f"{path}: prototype.text не должен быть пустым")

    sol = proto.get('solution')
    if not isinstance(sol, dict):
        errors.append(f"{path}: solution должен быть объектом")
    else:
        if 'steps' not in sol:
            errors.append(f"{path}: solution.steps обязательно")
        else:
            steps = sol['steps']
            if not isinstance(steps, list):
                errors.append(f"{path}: solution.steps должен быть массивом")
            else:
                for i, step in enumerate(steps):
                    if not isinstance(step, dict):
                        errors.append(f"{path}: solution.steps[{i}] должен быть объектом")
                    else:
                        for key in REQUIRED_STEP:
                            if key not in step:
                                errors.append(f"{path}: solution.steps[{i}].{key} обязательно")

    if not isinstance(proto.get('answer'), str):
        errors.append(f"{path}: answer должен быть строкой")

    if strict:
        if not proto.get('hint_ladder'):
            errors.append(f"{path}: в режиме --strict требуется непустой hint_ladder")

    return errors


def main():
    parser = argparse.ArgumentParser(description='Валидация эталонных прототипов')
    parser.add_argument('--strict', action='store_true', help='Считать отсутствие hint_ladder ошибкой')
    args = parser.parse_args()

    pattern = os.path.join(PROTOTYPES_DIR, '**', '*.json')
    files = [f for f in glob.glob(pattern, recursive=True)
             if os.path.basename(f) != 'prototype_schema.json' and not os.path.basename(f).startswith('_')]

    all_errors = []
    for filepath in sorted(files):
        rel = os.path.relpath(filepath, REPO_ROOT)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            all_errors.append(f"{rel}: ошибка JSON — {e}")
            continue
        errs = validate_one(data, rel, args.strict)
        all_errors.extend(errs)

    if all_errors:
        for e in all_errors:
            print(e)
        print(f"\nВсего ошибок: {len(all_errors)}")
        sys.exit(1)

    print(f"OK: проверено файлов {len(files)}, ошибок нет.")
    sys.exit(0)


if __name__ == '__main__':
    main()
