"""Импорт полного авторского курса Python для ЕГЭ из поставляемого архива."""
from __future__ import annotations

import html
import json
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Any

from core.db_models import Course, CourseTaskTemplate, LessonRoomTemplate, TaskSolution, Tasks


PACKAGE_NAME = "python_ege_bank.json"
PACKAGE_SOURCE = "author/python-ege-curriculum"
COURSE_SLUG = "python-ege-zero-to-algorithms"


def default_archive_path() -> Path:
    return Path(__file__).resolve().parents[2] / "python_ege_complete.zip"


def load_curriculum_package(path: str | Path | None = None) -> dict[str, Any]:
    """Читает JSON из неизменяемого авторского архива без распаковки на диск."""
    archive_path = Path(path) if path else default_archive_path()
    if not archive_path.is_file():
        raise FileNotFoundError(f"Не найден архив учебного пакета: {archive_path}")
    with zipfile.ZipFile(archive_path) as archive:
        try:
            raw = archive.read(PACKAGE_NAME)
        except KeyError as exc:
            raise ValueError(f"В архиве нет {PACKAGE_NAME}") from exc
    data = json.loads(raw.decode("utf-8"))
    validate_curriculum_package(data)
    return data


def validate_curriculum_package(data: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        raise ValueError("Учебный пакет должен быть JSON-объектом")
    for key in ("course", "modules", "lessons", "tasks", "solutions"):
        if not data.get(key):
            raise ValueError(f"В учебном пакете отсутствует {key}")
    tasks = data["tasks"]
    lessons = data["lessons"]
    task_ids = {task.get("id") for task in tasks}
    lesson_ids = {lesson.get("id") for lesson in lessons}
    if len(tasks) != len(task_ids) or None in task_ids:
        raise ValueError("В учебном пакете повторяются идентификаторы заданий")
    if len(lessons) != len(lesson_ids) or None in lesson_ids:
        raise ValueError("В учебном пакете повторяются идентификаторы уроков")
    if any(task.get("lesson_id") not in lesson_ids for task in tasks):
        raise ValueError("У части заданий отсутствует связанный урок")


def source_key(task_id: str) -> str:
    return f"{PACKAGE_SOURCE}/{task_id}"


def lesson_template_key(lesson_id: str) -> str:
    return f"{PACKAGE_SOURCE}/lesson/{lesson_id}"


def _difficulty(value: Any) -> int:
    try:
        return max(1, min(3, int(value)))
    except (TypeError, ValueError):
        return 2


def _text(value: Any) -> str:
    return str(value or "").strip()


def _student_content(task: dict[str, Any]) -> str:
    student = task.get("student") or {}
    parts = [f"<p>{html.escape(_text(student.get('statement')))}</p>"]
    code = _text(student.get("code"))
    if code:
        parts.append(f'<pre><code class="language-python">{html.escape(code)}</code></pre>')
    stdin = _text(student.get("stdin"))
    if stdin:
        parts.append(f"<p><strong>Входные данные:</strong></p><pre><code>{html.escape(stdin)}</code></pre>")
    sample_tests = student.get("sample_tests") or []
    public_samples = [sample for sample in sample_tests if sample.get("visibility") == "public"]
    if public_samples:
        parts.append("<p><strong>Примеры для самопроверки:</strong></p><ul>")
        for sample in public_samples:
            stdin_value = html.escape(_text(sample.get("stdin")) or "—")
            stdout_value = html.escape(_text(sample.get("stdout")) or "—")
            parts.append(f"<li>ввод: <code>{stdin_value}</code>; ожидаемый вывод: <code>{stdout_value}</code></li>")
        parts.append("</ul>")
    hints = [hint for hint in (student.get("hints") or []) if _text(hint)]
    if hints:
        parts.append("<details><summary>Подсказка</summary><p>" + html.escape(hints[0]) + "</p></details>")
    return "".join(parts)


def _teacher_solution(task: dict[str, Any], solutions: dict[str, dict[str, Any]]) -> str:
    teacher = task.get("teacher") or {}
    parts = []
    answer = _text(teacher.get("answer"))
    if answer:
        parts.append(f"Правильный ответ:\n{answer}")
    explanation = _text(teacher.get("explanation"))
    if explanation:
        parts.append(f"Разбор:\n{explanation}")
    solution = solutions.get(_text(teacher.get("solution_id")))
    if solution:
        code = _text(solution.get("code"))
        if code:
            parts.append(f"Эталонный код ({solution.get('language') or 'python3'}):\n{code}")
        tests = solution.get("tests") or []
        if tests:
            parts.append("Проверки:\n" + "\n".join(
                f"- {test.get('purpose') or test.get('id')}: ввод {test.get('stdin') or '—'}, вывод {test.get('stdout') or '—'}"
                for test in tests
            ))
    rubric = (teacher.get("grading") or {}).get("rubric") or []
    if rubric:
        parts.append("Критерии:\n" + "\n".join(
            f"- {item.get('points', 0)} б.: {item.get('criterion') or ''}" for item in rubric
        ))
    return "\n\n".join(parts) or "Эталон и критерии проверки не указаны."


def _lesson_markdown(lesson: dict[str, Any], tasks_by_id: dict[str, dict[str, Any]]) -> str:
    outcomes = [f"- {item}" for item in lesson.get("outcomes") or [] if _text(item)]
    blocks = [f"# {lesson.get('title') or lesson.get('id')}"]
    if outcomes:
        blocks.extend(["## Результат урока", *outcomes])
    theory = _text(lesson.get("theory"))
    if theory:
        blocks.extend(["## Коротко о теме", theory])
    scenario = lesson.get("scenario") or []
    if scenario:
        blocks.append("## Ход занятия")
        for step in scenario:
            blocks.append(f"- {step.get('start_minute', 0):02d}–{step.get('end_minute', 0):02d} мин: {step.get('title') or 'Этап'}")
    task_ids = lesson.get("task_ids") or []
    if task_ids:
        blocks.append("## Задания урока")
        for task_id in task_ids:
            task = tasks_by_id.get(task_id) or {}
            blocks.append(f"- {task.get('title') or task_id}")
    return "\n\n".join(blocks)


@lru_cache(maxsize=1)
def curriculum_metadata() -> dict[str, dict[str, str]]:
    """Метки полной программы для поиска и фильтров V2-банка."""
    data = load_curriculum_package()
    modules = {module["id"]: module for module in data["modules"]}
    lessons = {lesson["id"]: lesson for lesson in data["lessons"]}
    metadata: dict[str, dict[str, str]] = {}
    for task in data["tasks"]:
        lesson = lessons[task["lesson_id"]]
        module = modules[lesson["module_id"]]
        metadata[source_key(task["id"])] = {
            "title": _text(task.get("title")) or task["id"],
            "module": _text(module.get("title")) or "Python для ЕГЭ",
            "lesson": _text(lesson.get("title")),
            "type": _text(task.get("type_label")),
        }
    return metadata


def import_curriculum_package(data: dict[str, Any], db, *, dry_run: bool = False) -> dict[str, int | str]:
    """Создаёт/обновляет 540 задач и 60 общих шаблонов уроков без дублей."""
    validate_curriculum_package(data)
    course_info = data["course"]
    course = Course.query.filter_by(slug=COURSE_SLUG).first()
    if not course:
        course = Course(title=course_info["title"], slug=COURSE_SLUG, is_active=True)
        db.session.add(course)
        db.session.flush()
    else:
        course.title = course_info["title"]
        course.is_active = True

    solutions = {solution["id"]: solution for solution in data["solutions"]}
    modules = {module["id"]: module for module in data["modules"]}
    lessons = {lesson["id"]: lesson for lesson in data["lessons"]}
    tasks_by_id = {task["id"]: task for task in data["tasks"]}
    task_ids_by_source: dict[str, int] = {}
    created = updated = 0

    for order, task in enumerate(data["tasks"], 1):
        lesson = lessons[task["lesson_id"]]
        module = modules[lesson["module_id"]]
        grading = (task.get("teacher") or {}).get("grading") or {}
        # Платформа умеет сверить короткую строку, но не должна выдавать
        # ссылку на эталонный файл как «правильный ответ» к программе.
        # Программы и отладка остаются на проверке преподавателя, а эталонный
        # код и тесты сохраняются в TaskSolution.
        manual = grading.get("mode") in {
            "manual",
            "code_tests_and_method",
            "code_tests_and_explanation",
        }
        source = source_key(task["id"])
        values = {
            "course_id": course.id,
            "task_number": order,
            "content_html": _student_content(task),
            "answer": None if manual else _text((task.get("teacher") or {}).get("answer")),
            "difficulty_level": _difficulty(task.get("difficulty")),
            "bank_origin": "imported",
            "starter_code": _text((task.get("student") or {}).get("code")) or None,
            "source_prototype": source,
            "source_url": f"curriculum://{task['id']}",
            "max_score": max(1, int(grading.get("max_points") or 1)),
            "is_active": True,
            "hints": (task.get("student") or {}).get("hints") or [],
        }
        record = Tasks.query.filter_by(source_prototype=source).first()
        if record:
            if not dry_run:
                for name, value in values.items():
                    setattr(record, name, value)
            updated += 1
        else:
            if not dry_run:
                record = Tasks(**values)
                db.session.add(record)
                db.session.flush()
            created += 1
        if record:
            task_ids_by_source[task["id"]] = record.task_id
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

        template = CourseTaskTemplate.query.filter_by(course_id=course.id, task_number=order).first()
        if not template and not dry_run:
            db.session.add(CourseTaskTemplate(
                course_id=course.id,
                task_number=order,
                max_primary_score=max(1, int(grading.get("max_points") or 1)),
                requires_manual_review=manual,
                description=f"{module.get('title')}: {task.get('title')}",
            ))

    templates_created = templates_updated = 0
    for lesson in data["lessons"]:
        payload = {
            "content": _lesson_markdown(lesson, tasks_by_id),
            "content_blocks": [],
            "materials": [],
            "course_slug": COURSE_SLUG,
            "course_title": course.title,
            "external_lesson_id": lesson["id"],
            "lesson_order": lesson.get("order"),
            "duration_minutes": lesson.get("duration_minutes") or 60,
            "task_ids": [task_ids_by_source[task_id] for task_id in lesson.get("task_ids") or [] if task_id in task_ids_by_source],
            "assignment_tasks": {
                "classwork": [task_ids_by_source[task_id] for task_id in lesson.get("in_class_task_ids") or [] if task_id in task_ids_by_source],
                "homework": [task_ids_by_source[task_id] for task_id in (
                    list(lesson.get("homework_task_ids") or []) + list(lesson.get("extension_task_ids") or [])
                ) if task_id in task_ids_by_source],
            },
            "scenario": lesson.get("scenario") or [],
            "teacher_note": lesson.get("teacher_note") or "",
            "mastery_rule": lesson.get("mastery_rule") or {},
        }
        description = f"Урок {lesson.get('order')} из 60 · {lesson.get('duration_minutes') or 60} минут · {len(payload['task_ids'])} заданий"
        template = next((item for item in LessonRoomTemplate.query.filter_by(is_active=True).all()
                         if (item.payload or {}).get("course_slug") == COURSE_SLUG
                         and (item.payload or {}).get("external_lesson_id") == lesson["id"]), None)
        if template:
            if not dry_run:
                template.title = lesson.get("title") or lesson["id"]
                template.description = description
                template.payload = payload
                template.visibility = "shared"
                template.is_active = True
            templates_updated += 1
        else:
            if not dry_run:
                db.session.add(LessonRoomTemplate(
                    created_by_user_id=None,
                    title=lesson.get("title") or lesson["id"],
                    description=description,
                    payload=payload,
                    visibility="shared",
                    is_active=True,
                ))
            templates_created += 1

    if not dry_run:
        db.session.commit()
    return {
        "course_slug": COURSE_SLUG,
        "tasks_created": created,
        "tasks_updated": updated,
        "templates_created": templates_created,
        "templates_updated": templates_updated,
        "total_tasks": len(data["tasks"]),
        "total_lessons": len(data["lessons"]),
    }


def import_curriculum_archive(path: str | Path | None, db, *, dry_run: bool = False) -> dict[str, int | str]:
    return import_curriculum_package(load_curriculum_package(path), db, dry_run=dry_run)
