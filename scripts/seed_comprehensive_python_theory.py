# -*- coding: utf-8 -*-
"""
Master seed script for comprehensive 8-module, 33-topic Python theory curriculum.
Replaces legacy 8-topic stub with 33 detailed, visual, exam-oriented articles:
- Updates data/theory/ege_informatics_curriculum.json
- Updates database tables TheoryGroup and TheoryBlock across all courses
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.theory_data.mod1_basics import MOD1_TOPICS
from scripts.theory_data.mod2_io_arith import MOD2_TOPICS
from scripts.theory_data.mod3_conditions import MOD3_TOPICS
from scripts.theory_data.mod4_loops import MOD4_TOPICS
from scripts.theory_data.mod5_strings import MOD5_TOPICS
from scripts.theory_data.mod6_lists import MOD6_TOPICS
from scripts.theory_data.mod7_functions import MOD7_TOPICS

MODULES_DEF = [
    {
        "key": "py_basics_types",
        "name": "Программирование: Основы и типы данных",
        "description": "Первая программа print(), переменные, базовая арифметика (+, -, *, **), три вида деления (/, //, %) и базовые типы данных.",
        "topics": MOD1_TOPICS,
    },
    {
        "key": "py_io_arithmetic",
        "name": "Программирование: Ввод, вывод и логика",
        "description": "Консольный ввод input(), параметры вывода print(), f-строки, операторы сравнения и функции min, max, sum, len.",
        "topics": MOD2_TOPICS,
    },
    {
        "key": "py_conditions",
        "name": "Программирование: Условные конструкции и логика",
        "description": "Ветвление if-elif-else, логические связки and/or/not, таблицы истинности и шаблоны условий в ЕГЭ.",
        "topics": MOD3_TOPICS,
    },
    {
        "key": "py_loops",
        "name": "Программирование: Циклы и переборные алгоритмы",
        "description": "Циклы for и while, range(), управление break/continue, разбор чисел на цифры и вложенный перебор.",
        "topics": MOD4_TOPICS,
    },
    {
        "key": "py_strings",
        "name": "Программирование: Строки и методы текста",
        "description": "Индексация и срезы [start:stop:step], методы count, find, replace (для задания 12) и обработка строк.",
        "topics": MOD5_TOPICS,
    },
    {
        "key": "py_lists",
        "name": "Программирование: Списки (массивы) и методы коллекций",
        "description": "Списки, методы append/pop/sort, генераторы списков, map() и жадные алгоритмы для задания 26.",
        "topics": MOD6_TOPICS,
    },
    {
        "key": "py_functions",
        "name": "Программирование: Функции и подпрограммы",
        "description": "Синтаксис def, возврат return, функции-предикаты для проверки делителей в задании 25 и область видимости.",
        "topics": MOD7_TOPICS,
    },
]

# Flat dictionary of all 30 topics
ALL_30_TOPICS = {}
for m in MODULES_DEF:
    ALL_30_TOPICS.update(m["topics"])
ALL_33_TOPICS = ALL_30_TOPICS


def update_curriculum_json(json_path: Path):
    if not json_path.exists():
        print(f"Skipping {json_path} (does not exist)")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Separate programming groups from exam task groups (tasks 1..27)
    existing_groups = data.get("groups", [])
    non_programming_groups = []
    for g in existing_groups:
        g_name = (g.get("name") or "").lower()
        g_key = (g.get("key") or "").lower()
        if any(marker in g_name or marker in g_key for marker in ("программ", "python", "intro_programming", "group_2")):
            continue
        non_programming_groups.append(g)

    # Build the 8 new programming groups
    new_programming_groups = []
    for m in MODULES_DEF:
        blocks = []
        for tn, info in sorted(m["topics"].items()):
            blocks.append({
                "task_number": tn,
                "title": info["title"],
                "description": info.get("description", ""),
                "read_minutes": info.get("read_minutes", 20),
                "content": info["content"].strip(),
            })
        new_programming_groups.append({
            "key": m["key"],
            "name": m["name"],
            "description": m["description"],
            "blocks": blocks,
        })

    # Put new programming groups at the start, followed by non-programming groups
    data["groups"] = new_programming_groups + non_programming_groups

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Successfully updated {json_path} with 7 programming groups and 30 topics.")


def update_database():
    from app import create_app, db
    from app.models import Course, TheoryGroup, TheoryBlock

    app = create_app()
    with app.app_context():
        courses = Course.query.filter(
            Course.slug.in_(["programming"])
        ).all()
        print(f"Updating database for {len(courses)} courses...")

        for course in courses:
            print(f"--- Processing course: {course.title} (ID {course.id}) ---")

            if course.slug == "programming":
                # Ensure exam topics 1-27 never leak into pure programming course
                exam_blocks = TheoryBlock.query.filter_by(course_id=course.id).filter(TheoryBlock.task_number <= 27).all()
                for eb in exam_blocks:
                    db.session.delete(eb)
                exam_group = TheoryGroup.query.filter_by(course_id=course.id, name="Теория по заданиям ЕГЭ №1–27").first()
                if exam_group:
                    db.session.delete(exam_group)
                db.session.flush()

            # Remove or clean up legacy programming groups
            legacy_groups = TheoryGroup.query.filter(
                TheoryGroup.course_id == course.id
            ).filter(
                (TheoryGroup.name.ilike("%введение в программ%")) |
                (TheoryGroup.name.ilike("%программирование на python%")) |
                (TheoryGroup.name == "Программирование на Python") |
                (TheoryGroup.name == "Программирование: Файлы и потоки данных")
            ).all()

            for lg in legacy_groups:
                for b in lg.blocks:
                    db.session.delete(b)
                db.session.delete(lg)

            # Explicitly delete removed blocks 131-133 (Files module)
            stale_blocks = TheoryBlock.query.filter(
                TheoryBlock.course_id == course.id,
                TheoryBlock.task_number.in_([131, 132, 133]),
            ).all()
            for sb in stale_blocks:
                db.session.delete(sb)

            db.session.flush()

            # Create the 8 modern groups and 33 blocks
            for g_pos, m in enumerate(MODULES_DEF, start=1):
                group = TheoryGroup.query.filter_by(
                    course_id=course.id,
                    name=m["name"],
                ).first()
                if not group:
                    group = TheoryGroup(
                        course_id=course.id,
                        name=m["name"],
                        description=m["description"],
                        position=g_pos,
                    )
                    db.session.add(group)
                    db.session.flush()
                else:
                    group.description = m["description"]
                    group.position = g_pos

                for b_pos, (tn, info) in enumerate(sorted(m["topics"].items()), start=1):
                    block = TheoryBlock.query.filter_by(
                        course_id=course.id,
                        task_number=tn,
                    ).first()

                    if not block:
                        block = TheoryBlock(
                            course_id=course.id,
                            group_id=group.id,
                            task_number=tn,
                            title=info["title"],
                            read_minutes=info["read_minutes"],
                            content=info["content"].strip(),
                            position=b_pos,
                        )
                        db.session.add(block)
                    else:
                        block.group_id = group.id
                        block.title = info["title"]
                        block.read_minutes = info["read_minutes"]
                        block.content = info["content"].strip()
                        block.position = b_pos

            db.session.commit()
            print(f"Course ID {course.id}: 7 groups and 30 topics committed.")

        print("Database sync complete!")


def main():
    json1 = ROOT / "data" / "theory" / "ege_informatics_curriculum.json"
    json2 = ROOT / "data" / "theory" / "ege_informatics_curriculum_roundtrip.json"

    update_curriculum_json(json1)
    update_curriculum_json(json2)
    update_database()
    print("Seed process finished successfully!")


if __name__ == "__main__":
    main()
