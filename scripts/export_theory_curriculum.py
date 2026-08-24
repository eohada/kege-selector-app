"""Export theory blocks from a course to a portable JSON package."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.models import Course, TheoryBlock
from app.theory.curriculum import export_curriculum


def main() -> int:
    parser = argparse.ArgumentParser(description="Экспорт теории курса")
    parser.add_argument("--course-id", type=int, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    app = create_app()
    with app.app_context():
        course = Course.query.get(args.course_id)
        if not course:
            parser.error(f"Курс {args.course_id} не найден")
        blocks = TheoryBlock.query.filter_by(course_id=course.id).order_by(TheoryBlock.position, TheoryBlock.task_number).all()
        groups: dict[int | None, dict] = {}
        for block in blocks:
            key = block.group_id
            group = groups.setdefault(key, {"key": f"group_{key or 'ungrouped'}", "name": block.group.name if block.group else "Без группы", "description": block.group.description if block.group else "", "blocks": []})
            content = block.content or ""
            if content.startswith("<!--status:"):
                content = content.split("\n", 1)[1] if "\n" in content else ""
            group["blocks"].append({"task_number": block.task_number, "title": block.title or f"Тема №{block.task_number}", "description": block.description or "", "read_minutes": block.read_minutes or 5, "content": content})
        package = {"schema_version": 1, "course_key": course.slug, "title": course.title, "description": "Экспорт теоретических блоков BooStudy", "generated_at": None, "groups": list(groups.values())}
        export_curriculum(package, args.output)
    # Используем ASCII-стрелку: серверные терминалы часто работают в cp1251.
    print(f"Экспортировано блоков: {len(blocks)} -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
