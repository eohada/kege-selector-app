# -*- coding: utf-8 -*-
"""
Script to apply rich 2-level Python theory (tasks 101-108) across:
1. data/theory/ege_informatics_curriculum.json
2. data/theory/ege_informatics_curriculum_roundtrip.json
3. Database TheoryBlock table across all courses
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.python_theory_content_p1 import PYTHON_THEORY_P1
from scripts.python_theory_content_p2 import PYTHON_THEORY_P2
from app.theory.curriculum import INTRO_INTERACTIVE_MARKERS
from app import create_app, db
from app.models import Course, TheoryBlock

RAW_THEORY = {**PYTHON_THEORY_P1, **PYTHON_THEORY_P2}

TITLES = {
    101: "Переменные и типы",
    102: "Ввод, вывод и отладка",
    103: "Условия",
    104: "Циклы",
    105: "Функции",
    106: "Строки и списки",
    107: "Проверка программ",
    108: "Файлы и данные",
}

READ_MINUTES = {
    101: 18,
    102: 20,
    103: 20,
    104: 22,
    105: 22,
    106: 25,
    107: 20,
    108: 22,
}

def _inject_markers(tn, beg_part, markers):
    if tn == 101:
        # m0: py101-read, m1: py101-code, m2: py101-output
        p = beg_part.find('[/CODE_RUNNER]') + len('[/CODE_RUNNER]')
        beg_part = beg_part[:p] + f"\n\n{markers[1]}\n\n" + beg_part[p:]
        target = 'а не число 30.'
        p = beg_part.find(target) + len(target)
        beg_part = beg_part[:p] + f"\n\n{markers[0]}\n\n" + beg_part[p:]
        p = beg_part.find('[/HOW_IT_WORKS]') + len('[/HOW_IT_WORKS]')
        beg_part = beg_part[:p] + f"\n\n{markers[2]}\n\n" + beg_part[p:]
    elif tn == 102:
        # m0: py102-read, m1: py102-output, m2: py102-code
        p = beg_part.find('[/HOW_IT_WORKS]') + len('[/HOW_IT_WORKS]')
        beg_part = beg_part[:p] + f"\n\n{markers[0]}\n\n" + beg_part[p:]
        p = beg_part.find('[/CODE_RUNNER]') + len('[/CODE_RUNNER]')
        beg_part = beg_part[:p] + f"\n\n{markers[1]}\n\n" + beg_part[p:]
        p = beg_part.find('## Микро-проверки')
        beg_part = beg_part[:p] + f"{markers[2]}\n\n" + beg_part[p:]
    elif tn == 103:
        # m0: py103-read, m1: py103-boolean, m2: py103-output
        target = 'print("Число отрицательное или ноль")\n```'
        p = beg_part.find(target) + len(target)
        beg_part = beg_part[:p] + f"\n\n{markers[1]}\n\n" + beg_part[p:]
        p = beg_part.find('[/IMPORTANT]') + len('[/IMPORTANT]')
        beg_part = beg_part[:p] + f"\n\n{markers[0]}\n\n" + beg_part[p:]
        p = beg_part.find('[/CODE_RUNNER]') + len('[/CODE_RUNNER]')
        beg_part = beg_part[:p] + f"\n\n{markers[2]}\n\n" + beg_part[p:]
    elif tn == 104:
        # m0: py104-read, m1: py104-output, m2: py104-code
        target = 'range(1, n + 1)'
        p = beg_part.find(target) + len(target)
        # find the end of line
        p = beg_part.find('\n', p)
        beg_part = beg_part[:p] + f"\n\n{markers[0]}\n\n" + beg_part[p:]
        p = beg_part.find('[/CODE_RUNNER]') + len('[/CODE_RUNNER]')
        beg_part = beg_part[:p] + f"\n\n{markers[1]}\n\n" + beg_part[p:]
        target = 'переходит к следующей.'
        p = beg_part.find(target) + len(target)
        beg_part = beg_part[:p] + f"\n\n{markers[2]}\n\n" + beg_part[p:]
    elif tn == 105:
        # m0: py105-read, m1: py105-output, m2: py105-code
        target = 'print(result)   # Напечатает 25\n```'
        p = beg_part.find(target) + len(target)
        beg_part = beg_part[:p] + f"\n\n{markers[1]}\n\n" + beg_part[p:]
        p = beg_part.find('[/IMPORTANT]') + len('[/IMPORTANT]')
        beg_part = beg_part[:p] + f"\n\n{markers[0]}\n\n" + beg_part[p:]
        p = beg_part.find('[/CODE_RUNNER]') + len('[/CODE_RUNNER]')
        beg_part = beg_part[:p] + f"\n\n{markers[2]}\n\n" + beg_part[p:]
    elif tn == 106:
        # m0: py106-read, m1: py106-output, m2: py106-code
        p = beg_part.find('[/IMPORTANT]') + len('[/IMPORTANT]')
        beg_part = beg_part[:p] + f"\n\n{markers[0]}\n\n" + beg_part[p:]
        p = beg_part.find('[/CODE_RUNNER]') + len('[/CODE_RUNNER]')
        beg_part = beg_part[:p] + f"\n\n{markers[1]}\n\n" + beg_part[p:]
        target = 'длина, минимум, максимум, сумма.'
        p = beg_part.find(target) + len(target)
        beg_part = beg_part[:p] + f"\n\n{markers[2]}\n\n" + beg_part[p:]
    elif tn == 107:
        # m0: py107-read, m1: py107-choice, m2: py107-output
        target = 'ключ к высокому баллу.'
        p = beg_part.find(target) + len(target)
        beg_part = beg_part[:p] + f"\n\n{markers[1]}\n\n" + beg_part[p:]
        target = 'при проверке `a < b`?'
        p = beg_part.find(target) + len(target)
        beg_part = beg_part[:p] + f"\n\n{markers[0]}\n\n" + beg_part[p:]
        p = beg_part.find('[/CODE_RUNNER]') + len('[/CODE_RUNNER]')
        beg_part = beg_part[:p] + f"\n\n{markers[2]}\n\n" + beg_part[p:]
    elif tn == 108:
        # m0: py108-read, m1: py108-output, m2: py108-code
        target = 'файл ГАРАНТИРОВАННО закроется сам!\n```'
        p = beg_part.find(target) + len(target)
        beg_part = beg_part[:p] + f"\n\n{markers[1]}\n\n" + beg_part[p:]
        target = 'numbers = [int(line) for line in f]\n```'
        p = beg_part.find(target) + len(target)
        beg_part = beg_part[:p] + f"\n\n{markers[0]}\n\n" + beg_part[p:]
        p = beg_part.find('[/CODE_RUNNER]') + len('[/CODE_RUNNER]')
        beg_part = beg_part[:p] + f"\n\n{markers[2]}\n\n" + beg_part[p:]
    return beg_part

def format_final_theory():
    final_theory = {}
    for tn in range(101, 109):
        content = RAW_THEORY[tn]
        markers = INTRO_INTERACTIVE_MARKERS[tn]
        content = re.sub(r'\[GHOST_IMAGE(?:\s+name="[^"]*")?\]\s*', '', content)
        content = re.sub(r'\[INTERACTIVE\s+[^\]]+\]\s*', '', content)
        content = content.replace("## Проверь себя", "## Микро-проверки")
        content = content.replace("## Экзаменационные проверки", "## Микро-проверки")

        beg_idx = content.find('[LEVEL name="beginner"')
        adv_idx = content.find('[LEVEL name="advanced"')
        beg_part = content[beg_idx:adv_idx]

        new_beg = _inject_markers(tn, beg_part, markers)
        final_content = content[:beg_idx] + new_beg + content[adv_idx:]
        final_theory[tn] = final_content
    return final_theory

ALL_THEORY = format_final_theory()

def update_json_file(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    updated_count = 0
    for group in data.get("groups", []):
        if group.get("key") in ("intro_programming", "group_2") or "Введение" in (group.get("name") or ""):
            for block in group.get("blocks", []):
                tn = block.get("task_number")
                if tn in ALL_THEORY:
                    block["content"] = ALL_THEORY[tn]
                    block["title"] = TITLES[tn]
                    block["read_minutes"] = READ_MINUTES[tn]
                    updated_count += 1

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Updated {updated_count} blocks in {file_path}")

def update_database(app):
    with app.app_context():
        courses = Course.query.all()
        print(f"Updating DB across {len(courses)} courses...")
        total_updated = 0
        for course in courses:
            for tn, content in ALL_THEORY.items():
                blocks = TheoryBlock.query.filter_by(course_id=course.id, task_number=tn).all()
                for b in blocks:
                    b.content = content
                    b.title = TITLES[tn]
                    b.read_minutes = READ_MINUTES[tn]
                    total_updated += 1
        db.session.commit()
        print(f"Updated {total_updated} TheoryBlock records in database.")

def main():
    json_path1 = ROOT / "data" / "theory" / "ege_informatics_curriculum.json"
    json_path2 = ROOT / "data" / "theory" / "ege_informatics_curriculum_roundtrip.json"

    update_json_file(json_path1)
    if json_path2.exists():
        update_json_file(json_path2)

    app = create_app()
    update_database(app)
    print("All Python theory blocks successfully applied!")

if __name__ == "__main__":
    main()
