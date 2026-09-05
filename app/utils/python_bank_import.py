"""Идемпотентный импорт авторского банка Python для ЕГЭ."""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from core.db_models import Course, CourseTaskTemplate, Tasks, TaskSolution


def _key(package_slug: str, item: dict, variant_index: int) -> str:
    raw = f"{package_slug}:{item.get('id') or item.get('task_number')}:{variant_index}"
    return f"author/python-ege/{hashlib.sha1(raw.encode()).hexdigest()[:20]}"


@lru_cache(maxsize=1)
def foundations_metadata():
    """Resolve thematic labels for existing imports without rewriting student tasks."""
    path = Path(__file__).resolve().parents[2] / 'data/task_banks/python_foundations.json'
    with path.open(encoding='utf-8') as handle:
        package = json.load(handle)
    return {_key(package['slug'], item, index): {
        'title': item['title'], 'module': item['module']
    } for index, item in enumerate(package['tasks'], 1)}


def validate_package(data: dict) -> list[str]:
    errors = []
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        return ["schema_version должен быть равен 1"]
    if not data.get("slug") or not data.get("title"):
        errors.append("нужны slug и title")
    items = data.get("tasks")
    if not isinstance(items, list) or not items:
        errors.append("tasks должен быть непустым списком")
        return errors
    for i, item in enumerate(items, 1):
        if not isinstance(item, dict):
            errors.append(f"tasks[{i}] не является объектом")
            continue
        if not isinstance(item.get("task_number"), int) or not 1 <= item["task_number"] <= 27:
            errors.append(f"tasks[{i}].task_number вне диапазона 1..27")
        variants = item.get("variants") or [item]
        for j, variant in enumerate(variants, 1):
            for field in ("content_html", "answer", "solution"):
                if not str(variant.get(field) or "").strip():
                    errors.append(f"tasks[{i}].variants[{j}].{field} пуст")
    return errors


def import_package(data: dict, db, *, dry_run=False) -> dict:
    errors = validate_package(data)
    if errors:
        raise ValueError("; ".join(errors))
    slug = data["slug"]
    course = Course.query.filter_by(slug=slug).first()
    if not course:
        course = Course(title=data["title"], slug=slug, is_active=True)
        db.session.add(course)
        db.session.flush()
    for number in range(1, 28):
        template = CourseTaskTemplate.query.filter_by(course_id=course.id, task_number=number).first()
        if not template:
            db.session.add(CourseTaskTemplate(course_id=course.id, task_number=number, max_primary_score=1, description="Python для ЕГЭ"))
    created = updated = 0
    for item in data["tasks"]:
        for variant_index, variant in enumerate(item.get("variants") or [item], 1):
            source = _key(slug, item, variant_index)
            task = Tasks.query.filter_by(source_prototype=source).first()
            values = dict(course_id=course.id, task_number=item["task_number"], content_html=variant["content_html"], answer=str(variant["answer"]),
                          difficulty_level=int(variant.get("difficulty_level", item.get("difficulty_level", 2))), bank_origin="imported",
                          starter_code=variant.get("starter_code"), max_score=int(variant.get("max_score", 1)), source_prototype=source, is_active=True)
            if task:
                if not dry_run:
                    for key, value in values.items(): setattr(task, key, value)
                    solution = TaskSolution.query.filter_by(task_id=task.task_id).first()
                    if solution:
                        solution.solution_text = variant["solution"]
                        solution.source = "manual"
                updated += 1
            else:
                if not dry_run:
                    task = Tasks(**values)
                    db.session.add(task)
                    db.session.flush()
                    db.session.add(TaskSolution(task_id=task.task_id, solution_text=variant["solution"], source="manual", needs_manual_review=False))
                created += 1
    if not dry_run:
        db.session.commit()
    return {"course_slug": slug, "created": created, "updated": updated, "total": created + updated}


def import_package_file(path: str | Path, db, *, dry_run=False) -> dict:
    with Path(path).open("r", encoding="utf-8") as handle:
        return import_package(json.load(handle), db, dry_run=dry_run)


def import_foundations_package(data: dict, db, *, dry_run=False) -> dict:
    """Импорт тематического банка без экзаменационной нумерации."""
    tasks = data.get("tasks") or []
    if len(tasks) < 160 or len({item.get("module") for item in tasks}) < 16:
        raise ValueError("тематический банк должен содержать минимум 160 заданий и 16 модулей")
    course = Course.query.filter_by(slug=data["slug"]).first()
    if not course:
        course = Course(title=data["title"], slug=data["slug"], is_active=True)
        db.session.add(course)
        db.session.flush()
    created = updated = 0
    for index, item in enumerate(tasks, 1):
        source = _key(data["slug"], item, index)
        task = Tasks.query.filter_by(source_prototype=source).first()
        values = dict(course_id=course.id, task_number=1000 + index, content_html=item["content_html"], answer=str(item["answer"]),
                      difficulty_level={"базовый": 1, "средний": 2, "продвинутый": 3}.get(item.get("level"), 2),
                      bank_origin="imported", starter_code=item.get("starter_code"), source_prototype=source, max_score=1, is_active=True)
        if task:
            if not dry_run:
                for key, value in values.items(): setattr(task, key, value)
                solution = TaskSolution.query.filter_by(task_id=task.task_id).first()
                if solution:
                    solution.solution_text = item["solution"]
            updated += 1
        else:
            if not dry_run:
                task = Tasks(**values)
                db.session.add(task)
                db.session.flush()
                db.session.add(TaskSolution(task_id=task.task_id, solution_text=item["solution"], source="manual"))
            created += 1
    if not dry_run:
        db.session.commit()
    return {"course_slug": data["slug"], "created": created, "updated": updated, "total": created + updated}
