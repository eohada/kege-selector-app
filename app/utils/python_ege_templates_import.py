"""Идемпотентный импорт библиотеки работ для курса Python для ЕГЭ."""
from __future__ import annotations

import hashlib
import html
import json
import shutil
from pathlib import Path
from typing import Any

from core.db_models import Course, TaskSolution, TaskTemplate, Tasks, TemplateTask
from app.utils.python_ege_curriculum_import import (
    COURSE_SLUG,
    _student_content,
    _teacher_solution,
    source_key,
)


TEMPLATE_LIBRARY_KEY = "python-ege-template-library"
PDF_FILENAME = "Python_osnovy_domashnyaya_rabota.pdf"


def default_package_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "task_banks" / "python_ege_templates.json"


def default_pdf_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "task_attachments" / PDF_FILENAME


def load_templates_package(path: str | Path | None = None) -> dict[str, Any]:
    package_path = Path(path) if path else default_package_path()
    if not package_path.is_file():
        raise FileNotFoundError(f"Не найден пакет шаблонов: {package_path}")
    data = json.loads(package_path.read_text(encoding="utf-8"))
    validate_templates_package(data)
    return data


def validate_templates_package(data: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        raise ValueError("Пакет шаблонов должен быть JSON-объектом")
    tasks = data.get("tasks") or []
    templates = data.get("templates") or []
    if len(tasks) != 555 or len(templates) != 150:
        raise ValueError("Ожидаются 555 заданий и 150 шаблонов")
    task_ids = [task.get("id") for task in tasks]
    template_ids = [template.get("id") for template in templates]
    if len(task_ids) != len(set(task_ids)) or not all(task_ids):
        raise ValueError("В пакете повторяются идентификаторы заданий")
    if len(template_ids) != len(set(template_ids)) or not all(template_ids):
        raise ValueError("В пакете повторяются идентификаторы шаблонов")
    if len([task for task in tasks if str(task.get("id")).startswith("PY-ORIGINAL-DZ-")]) != 15:
        raise ValueError("В пакете должны быть 15 заданий исходной домашней работы")
    if len({template.get("folder_path") for template in templates}) != 6:
        raise ValueError("В пакете должны быть шесть логических папок")
    known_task_ids = set(task_ids)
    for template in templates:
        ordered = sorted(template.get("tasks") or [], key=lambda item: item.get("position", 0))
        positions = [item.get("position") for item in ordered]
        if positions != list(range(1, len(ordered) + 1)):
            raise ValueError(f"Шаблон {template.get('id')} содержит неверный порядок карточек")
        if len({item.get("task_id") for item in ordered}) != len(ordered):
            raise ValueError(f"Шаблон {template.get('id')} содержит дубли карточек")
        if any(item.get("task_id") not in known_task_ids for item in ordered):
            raise ValueError(f"Шаблон {template.get('id')} ссылается на отсутствующую карточку")


def _manual_grading(task: dict[str, Any]) -> bool:
    mode = ((task.get("teacher") or {}).get("grading") or {}).get("mode")
    return mode in {"manual", "code_tests_and_method", "code_tests_and_explanation"}


def _template_type(category: str) -> str:
    return {
        "lesson": "classwork",
        "module_check": "exam",
    }.get(category or "", "homework")


def _estimated_time(template: dict[str, Any]) -> int:
    raw = template.get("estimated_student_work_minutes") or {}
    if isinstance(raw, dict):
        low = raw.get("min")
        high = raw.get("max")
        if isinstance(low, int) and isinstance(high, int):
            return max(1, round((low + high) / 2))
    minutes = template.get("session_minutes")
    return int(minutes) if isinstance(minutes, int) and minutes > 0 else 45


def _template_description(template: dict[str, Any]) -> str:
    description = str(template.get("description") or "").strip()
    instructions = str(template.get("student_instructions") or "").strip()
    optional = [item["task_id"] for item in template.get("tasks") or [] if not item.get("required", True)]
    parts = [part for part in (description, instructions) if part]
    if optional:
        parts.append(
            "Необязательные задания: " + ", ".join(optional) +
            ". Открывайте их после основной самостоятельной работы."
        )
    return "\n\n".join(parts)


def _copy_pdf(pdf_path: Path, target_root: Path, task_id: int) -> dict[str, str]:
    if not pdf_path.is_file():
        raise FileNotFoundError(f"Не найден PDF исходной домашней работы: {pdf_path}")
    destination = target_root / str(task_id) / PDF_FILENAME
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists() or hashlib.sha256(destination.read_bytes()).digest() != hashlib.sha256(pdf_path.read_bytes()).digest():
        shutil.copyfile(pdf_path, destination)
    return {
        "name": PDF_FILENAME,
        "path": f"/attachments/task/{task_id}/{PDF_FILENAME}",
        "role": "student_handout",
    }


def import_templates_package(
    data: dict[str, Any],
    db,
    *,
    pdf_path: str | Path | None = None,
    attachment_root: str | Path | None = None,
    dry_run: bool = False,
) -> dict[str, int | str]:
    """Обновляет 540 карточек и создаёт 15 новых, затем 150 черновиков."""
    validate_templates_package(data)
    course = Course.query.filter_by(slug=COURSE_SLUG).first()
    if not course:
        raise ValueError("Сначала импортируйте основной курс Python для ЕГЭ")

    all_tasks = {task["id"]: task for task in data["tasks"]}
    solutions = {solution["id"]: solution for solution in data.get("solutions") or []}
    originals = {task_id: task for task_id, task in all_tasks.items() if task_id.startswith("PY-ORIGINAL-DZ-")}
    existing = {task.source_prototype: task for task in Tasks.query.filter(
        Tasks.source_prototype.in_([source_key(task_id) for task_id in all_tasks])
    ).all()}
    missing_existing = [task_id for task_id in all_tasks if not task_id.startswith("PY-ORIGINAL-DZ-") and source_key(task_id) not in existing]
    if missing_existing:
        raise ValueError(f"Не найдены ранее импортированные задания: {', '.join(missing_existing[:5])}")

    tasks_updated = tasks_created = 0
    task_records: dict[str, Tasks] = {}
    for order, (task_id, task) in enumerate(all_tasks.items(), 1):
        manual = _manual_grading(task)
        grading = ((task.get("teacher") or {}).get("grading") or {})
        values = {
            "course_id": course.id,
            "content_html": _student_content(task),
            "answer": None if manual else str((task.get("teacher") or {}).get("answer") or ""),
            "difficulty_level": max(1, min(3, int(task.get("difficulty") or 2))),
            "bank_origin": "imported",
            "starter_code": str((task.get("student") or {}).get("code") or "") or None,
            "source_prototype": source_key(task_id),
            "source_url": f"curriculum://{task_id}",
            "max_score": max(1, int(grading.get("max_points") or 1)),
            "is_active": True,
            "hints": (task.get("student") or {}).get("hints") or [],
        }
        record = existing.get(source_key(task_id))
        if record:
            if not dry_run:
                for field, value in values.items():
                    setattr(record, field, value)
            tasks_updated += 1
        else:
            if not dry_run:
                original_number = int(task_id.rsplit("-", 1)[-1]) if task_id.startswith("PY-ORIGINAL-DZ-") else order
                record = Tasks(task_number=2000 + original_number, **values)
                db.session.add(record)
                db.session.flush()
            tasks_created += 1
        if record:
            task_records[task_id] = record
            solution = TaskSolution.query.filter_by(task_id=record.task_id).first()
            solution_text = _teacher_solution(task, solutions)
            if solution:
                if not dry_run:
                    solution.solution_text = solution_text
                    solution.source = "manual"
                    solution.needs_manual_review = manual
            elif not dry_run:
                db.session.add(TaskSolution(
                    task_id=record.task_id,
                    solution_text=solution_text,
                    source="manual",
                    needs_manual_review=manual,
                ))

    pdf_attachment = None
    if not dry_run:
        first_original = task_records["PY-ORIGINAL-DZ-01"]
        pdf_attachment = _copy_pdf(
            Path(pdf_path) if pdf_path else default_pdf_path(),
            Path(attachment_root) if attachment_root else Path(__file__).resolve().parents[2] / "uploads" / "task_attachments",
            first_original.task_id,
        )
        first_original.attached_files = json.dumps([pdf_attachment], ensure_ascii=False)

    templates_created = templates_updated = 0
    for template_data in data["templates"]:
        template = TaskTemplate.query.filter_by(external_key=template_data["id"]).first()
        values = {
            "name": template_data["title"],
            "description": _template_description(template_data),
            "template_type": _template_type(template_data.get("category") or ""),
            "category": "Python для ЕГЭ",
            "course_id": course.id,
            "estimated_time": _estimated_time(template_data),
            "is_active": True,
            "external_key": template_data["id"],
            "folder_path": template_data.get("folder_path"),
            "is_draft": True,
            "is_featured": bool(template_data.get("featured")),
            "settings_json": template_data.get("assignment_defaults") or {},
            "sections_json": {
                "sections": template_data.get("sections") or [],
                "task_requirements": template_data.get("tasks") or [],
                "reflection_prompt": template_data.get("reflection_prompt") or "",
            },
            "attachments_json": [pdf_attachment] if template_data["id"] == "TPL-PY-START-DZ" and pdf_attachment else [],
        }
        if template:
            if not dry_run:
                for field, value in values.items():
                    setattr(template, field, value)
            templates_updated += 1
        else:
            if not dry_run:
                template = TaskTemplate(created_by=None, **values)
                db.session.add(template)
                db.session.flush()
            templates_created += 1
        if not dry_run and template:
            TemplateTask.query.filter_by(template_id=template.template_id).delete()
            for item in sorted(template_data.get("tasks") or [], key=lambda value: value["position"]):
                db.session.add(TemplateTask(
                    template_id=template.template_id,
                    task_id=task_records[item["task_id"]].task_id,
                    order=item["position"],
                ))

    if not dry_run:
        db.session.commit()
    return {
        "course_slug": COURSE_SLUG,
        "tasks_updated": tasks_updated,
        "tasks_created": tasks_created,
        "templates_updated": templates_updated,
        "templates_created": templates_created,
        "templates_total": len(data["templates"]),
        "original_tasks_total": len(originals),
    }


def import_templates_file(path: str | Path | None, db, **kwargs) -> dict[str, int | str]:
    return import_templates_package(load_templates_package(path), db, **kwargs)
