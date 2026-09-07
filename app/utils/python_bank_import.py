"""Идемпотентный импорт авторского банка Python для ЕГЭ."""
from __future__ import annotations

import hashlib
import html
import json
from functools import lru_cache
from pathlib import Path

from core.db_models import Course, CourseTaskTemplate, Tasks, TaskSolution


_FOUNDATION_ACTIVITY_TITLES = (
    'Проверка результата', 'Разбор выражения', 'Трассировка программы',
    'Изменение данных', 'Поиск закономерности', 'Мини-задача',
    'Пограничный случай', 'Практика', 'Самопроверка', 'Закрепление',
)

_FOUNDATION_PROMPTS = (
    'Определите, что выведет программа.',
    'Выполните код по шагам и запишите результат.',
    'Не запуская программу, укажите вывод.',
    'Проследите изменение данных и укажите ответ.',
    'Найдите значение, которое напечатает программа.',
    'Решите короткую задачу по фрагменту кода.',
    'Проверьте программу на заданных данных.',
    'Вычислите результат выполнения программы.',
    'Запишите точный вывод программы.',
    'Закрепите тему: определите результат кода.',
)


def _foundation_variant_number(item: dict) -> int:
    """Номер упражнения внутри темы из стабильного ID пакета ``N.1`` … ``N.10``."""
    try:
        return max(1, min(10, int(str(item.get('id') or '').rsplit('.', 1)[-1])))
    except (TypeError, ValueError):
        return 1


def _foundation_code(module: str, n: int) -> tuple[str, str]:
    """Возвращает самостоятельный код и точный вывод для упражнения темы.

    Старый пакет содержал десять словесных вариантов одного и того же кода.
    Здесь номер упражнения меняет и данные, и выполняемое действие, поэтому
    повторный импорт безопасно обновляет уже созданные записи без смены ID.
    """
    if module == 'Переменные и типы данных':
        code = f"whole = {n * 7}\nratio = {n} + 0.75\nprint(type(whole).__name__, int(ratio))"
        return code, f'int {n}'
    if module == 'Ввод и вывод':
        code = f"raw = '{n + 4} {n * 3}'\na, b = map(int, raw.split())\nprint(a + b)"
        return code, str(n * 4 + 4)
    if module == 'Арифметика и логика':
        a, b = n + 11, n % 4 + 2
        code = f"a = {a}\nb = {b}\nprint(a * b - a // b)"
        return code, str(a * b - a // b)
    if module == 'Условия':
        value = n * 5 - 12
        answer = 'положительное' if value > 0 else ('нулевое' if value == 0 else 'отрицательное')
        code = f"value = {value}\nif value > 0:\n    print('положительное')\nelif value == 0:\n    print('нулевое')\nelse:\n    print('отрицательное')"
        return code, answer
    if module == 'Циклы':
        stop = n + 4
        code = f"total = 0\nfor number in range(1, {stop}):\n    total += number\nprint(total)"
        return code, str((stop - 1) * stop // 2)
    if module == 'Строки':
        text = 'алгоритмика'
        start = n % 5
        code = f"text = '{text}'\nprint(text[{start}:{start + 4}][::-1])"
        return code, text[start:start + 4][::-1]
    if module == 'Списки и срезы':
        values = list(range(n, n + 6))
        result = values[:2] + values[-2:]
        code = f"values = {values}\npart = values[:2] + values[-2:]\nprint(sum(part))"
        return code, str(sum(result))
    if module == 'Словари, множества, кортежи':
        code = f"data = {{'a': {n}, 'b': {n + 3}, 'c': {n % 4}}}\nkeys = set(data) - {{'c'}}\nprint(sum(data[key] for key in keys))"
        return code, str(n * 2 + 3)
    if module == 'Функции':
        factor, value = n + 1, n + 2
        code = f"def transform(value):\n    return value * {factor} - 1\n\nprint(transform({value}))"
        return code, str(value * factor - 1)
    if module == 'Рекурсия':
        depth = n % 5 + 3
        code = f"def count_down(value):\n    if value == 0:\n        return 0\n    return value + count_down(value - 1)\n\nprint(count_down({depth}))"
        return code, str(depth * (depth + 1) // 2)
    if module == 'Файлы':
        values = [n + 2, n * 2, n + 5, n % 4 + 1]
        text = '\\n'.join(map(str, values))
        file_text = repr(text)
        code = f"from io import StringIO\nfile = StringIO({file_text})\nnumbers = [int(line) for line in file]\nprint(max(numbers) - min(numbers))"
        return code, str(max(values) - min(values))
    if module == 'Исключения':
        divisor = n - 5
        code = f"try:\n    print(20 // {divisor})\nexcept ZeroDivisionError:\n    print('деление на ноль')"
        return code, 'деление на ноль' if divisor == 0 else str(20 // divisor)
    if module == 'Сортировка и поиск':
        values = [n + 7, n % 5, n + 2, n + 4, n % 3 + 1]
        ordered = sorted(values)
        code = f"numbers = {values}\nnumbers.sort()\nprint(numbers[2])"
        return code, str(ordered[2])
    if module == 'Матрицы':
        matrix = [[n, n + 1, n + 2], [n + 3, n + 4, n + 5], [n + 6, n + 7, n + 8]]
        code = f"matrix = {matrix}\nprint(sum(matrix[i][i] for i in range(3)))"
        return code, str(matrix[0][0] + matrix[1][1] + matrix[2][2])
    if module == 'Алгоритмы и оптимизация':
        values = [n + 2, n * 2 + 1, n + 5, n % 4 + 8, n + 3]
        answer = max(values[i] + values[i + 1] for i in range(len(values) - 1))
        code = f"values = {values}\nbest = max(values[i] + values[i + 1] for i in range(len(values) - 1))\nprint(best)"
        return code, str(answer)

    text = 'a' * (n % 4 + 2) + 'b' * (n % 3 + 1) + 'c' * (n % 5 + 1)
    answer = max(text.count(char) for char in set(text))
    code = f"text = '{text}'\nprint(max(text.count(char) for char in set(text)))"
    return code, str(answer)


def foundation_payload(item: dict) -> dict:
    """Строит содержимое тематического задания с оформленным блоком кода."""
    n = _foundation_variant_number(item)
    module = str(item.get('module') or 'Практические мини-задачи')
    code, answer = _foundation_code(module, n)
    level = 'базовый' if n <= 3 else ('средний' if n <= 7 else 'продвинутый')
    title = f'{_FOUNDATION_ACTIVITY_TITLES[n - 1]}: {module}'
    content_html = (
        f'<p>{_FOUNDATION_PROMPTS[n - 1]}</p>'
        f'<pre><code>{html.escape(code)}</code></pre>'
        '<p>Ответ запишите точно, включая регистр и знаки препинания, если они есть.</p>'
    )
    payload = dict(item)
    payload.update({
        'title': title,
        'level': level,
        'content_html': content_html,
        'answer': answer,
        'solution': code,
        'starter_code': f'# {module}\n{code}',
    })
    return payload


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
        'title': foundation_payload(item)['title'], 'module': item['module']
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
        payload = foundation_payload(item)
        values = dict(course_id=course.id, task_number=1000 + index, content_html=payload["content_html"], answer=str(payload["answer"]),
                      difficulty_level={"базовый": 1, "средний": 2, "продвинутый": 3}.get(payload.get("level"), 2),
                      bank_origin="imported", starter_code=payload.get("starter_code"), source_prototype=source, max_score=1, is_active=True)
        if task:
            if not dry_run:
                for key, value in values.items(): setattr(task, key, value)
                solution = TaskSolution.query.filter_by(task_id=task.task_id).first()
                if solution:
                    solution.solution_text = payload["solution"]
            updated += 1
        else:
            if not dry_run:
                task = Tasks(**values)
                db.session.add(task)
                db.session.flush()
                db.session.add(TaskSolution(task_id=task.task_id, solution_text=payload["solution"], source="manual"))
            created += 1
    if not dry_run:
        db.session.commit()
    return {"course_slug": data["slug"], "created": created, "updated": updated, "total": created + updated}
