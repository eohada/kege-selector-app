#!/usr/bin/env python3
"""Создаёт во всех папках task_01..task_27 / easy|medium|hard по одному JSON-заглушке с уникальным именем: task_NN_easy.json, task_NN_medium.json, task_NN_hard.json."""
import os
import json
import glob

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
PROTOTYPES_DIR = os.path.join(REPO_ROOT, 'data', 'reference_prototypes')

DIFFICULTY = [
    ('easy', 2),
    ('medium', 5),
    ('hard', 9),
]


def stub(task_number: int, difficulty_label: str, difficulty_level: int) -> dict:
    return {
        "task_number": task_number,
        "topic_code": "",
        "topic_name": "",
        "difficulty_level": difficulty_level,
        "difficulty_label": difficulty_label,
        "prototype": {
            "text": "(заполните текст задания)",
            "input_format": "",
            "answer_format": "",
            "attached_files": [],
            "images": []
        },
        "solution": {
            "steps": [
                {"step": 1, "explanation": ""}
            ],
            "alternative_methods": [],
            "common_mistakes": [],
            "time_estimate_sec": None,
            "variants": []
        },
        "answer": "",
        "hint_ladder": [],
        "tags": [],
        "source": "",
        "meta": {}
    }


def main():
    # Удаляем старые заглушки proto_001.json, если остались
    for old in glob.glob(os.path.join(PROTOTYPES_DIR, '**', 'proto_001.json'), recursive=True):
        try:
            os.remove(old)
        except OSError:
            pass

    count = 0
    for task in range(1, 28):
        for label, level in DIFFICULTY:
            dirpath = os.path.join(PROTOTYPES_DIR, f'task_{task:02d}', label)
            if not os.path.isdir(dirpath):
                os.makedirs(dirpath, exist_ok=True)
            filename = f'task_{task:02d}_{label}.json'
            filepath = os.path.join(dirpath, filename)
            data = stub(task, label, level)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            count += 1
    print(f'Создано {count} файлов (task_NN_easy|medium|hard.json)')


if __name__ == '__main__':
    main()
