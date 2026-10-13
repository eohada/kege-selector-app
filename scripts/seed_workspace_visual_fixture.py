"""Create an isolated six-type Task Workspace assignment for visual review.

Run with ``python scripts/seed_workspace_visual_fixture.py`` against the local
database. Repeated runs restore the visual baseline for the unfinished tasks.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app, db
from app.runtime_state import delete as clear_runtime_state
from core.db_models import Answer, Assignment, AssignmentTask, CodeWorkspaceVersion, Student, Submission, Tasks, User, utc_now


TITLE = "UI стенд · все типы ответов"
STUDENT_USERNAME = "demo_student_2"

TASKS = [
    {
        "type": "code",
        "score": 2,
        "content": """<h2>Исправь программу</h2>
<p>Программа должна вывести сумму цифр двузначного числа. Найди ошибку и запиши правильное решение.</p>
<details open><summary>Пример</summary><div class="tw-fixture-example"><div><b>Входные данные:</b><strong>47</strong></div><div><b>Вывод:</b><strong>11</strong></div></div></details>
<details><summary>Исходный код с ошибкой</summary><pre><code>n = int(input())\nprint(n // 10 + n // 10)</code></pre></details>""",
        "answer": "",
        "starter_code": "n = int(input())\nprint(n // 10 + n // 10)\n",
        "spec": {"type": "code", "workspace_modes": ["answer", "code", "canvas"], "default_workspace_mode": "code"},
        "hints": [
            {"title": "Подсказка 1", "text": "Для единиц используй остаток от деления на 10."},
            {"title": "Замечания", "text": "Проверь результат на нескольких двузначных числах."},
        ],
    },
    {
        "type": "single_choice",
        "score": 1,
        "content": """<h2>Какое выражение вернёт True?</h2>
<p>Выберите выражение, которое при выполнении в Python будет иметь значение True.</p>
<details open><summary>Пример</summary><div class="tw-fixture-example"><div><b>Выражение:</b><strong>3 &gt; 1</strong></div><div><b>Результат:</b><strong>True</strong></div></div></details>
<details><summary>Исходный код с ошибкой</summary><pre><code>print(5 &lt; 3)</code></pre></details>""",
        "answer": "B",
        "spec": {
            "type": "single_choice",
            "prompt": "Выберите один вариант",
            "options": [
                {"value": "A", "label": "5 < 3"},
                {"value": "B", "label": "10 == 10"},
                {"value": "C", "label": "len(\"python\") == 5"},
                {"value": "D", "label": "not (4 > 7) and False"},
            ],
            "workspace_modes": ["answer", "code", "canvas"],
        },
        "hints": [
            {"title": "Подсказка 1", "text": "Вспомни, как работают операторы сравнения."},
            {"title": "Замечания", "text": "Проверь каждое выражение отдельно в интерпретаторе Python."},
        ],
    },
    {
        "type": "multiple_choice",
        "score": 2,
        "content": """<h2>Выбери верные утверждения</h2>
<p>Отметь все выражения Python, результатом которых будет True.</p>
<details open><summary>Пример</summary><p><strong>4 &gt; 2</strong> возвращает True.</p></details>""",
        "answer": json.dumps(["A", "C"], ensure_ascii=False),
        "spec": {
            "type": "multiple_choice",
            "prompt": "Можно выбрать несколько вариантов.",
            "options": [
                {"value": "A", "label": "7 > 3"},
                {"value": "B", "label": "2 * 3 == 5"},
                {"value": "C", "label": "len(\"python\") == 6"},
                {"value": "D", "label": "9 < 4"},
            ],
            "workspace_modes": ["answer", "code", "canvas"],
        },
        "hints": [{"title": "Подсказка 1", "text": "Проверь каждое выражение отдельно."}],
    },
    {
        "type": "short_answer",
        "score": 2,
        "content": """<h2>Сумма цифр числа</h2>
<p>Вводится целое число от 10 до 99. Выведи сумму его цифр.</p>
<p>Ниже приведена программа, в которой допущена ошибка. Исправь её и объясни, в чём заключалась ошибка. Другие варианты решения также принимаются.</p>
<details open><summary>Пример</summary><div class="tw-fixture-example"><div><b>Входные данные:</b><strong>47</strong></div><div><b>Вывод:</b><strong>11</strong></div></div></details>
<details><summary>Исходный код с ошибкой</summary><pre><code>n = int(input())\nprint(n // 10 + n // 10)</code></pre></details>""",
        "answer": "11",
        "starter_code": "# Сумма цифр числа\nn = int(input())\na = n // 10  # первая цифра\nb = n % 10   # вторая цифра\nprint(a + b)\n",
        "spec": {
            "type": "short_answer",
            "prompt": "Введите целое число, например: 11",
            "placeholder": "Введите ответ...",
            "workspace_modes": ["answer", "code", "canvas"],
            "default_workspace_mode": "answer",
        },
        "hints": [
            {"title": "Подсказка 1", "text": "Вспомни операторы целочисленного деления и остатка."},
            {"title": "Замечания", "text": "Решение будет проверяться на нескольких тестах."},
        ],
    },
    {
        "type": "matching",
        "score": 2,
        "content": """<h2>Установи соответствие между оператором Python и его результатом</h2>
<p class="tw-fixture-match-intro">Соедини каждый оператор Python с тем результатом, который будет получен при его выполнении.<br>Все выражения независимы друг от друга.</p>
<details open><summary>Пример</summary><div class="tw-fixture-example tw-fixture-example--stack"><div><b>Оператор:</b><strong>2 + 3</strong></div><div><b>Результат:</b><strong>5</strong></div></div></details>
<details><summary>Исходный код с ошибкой</summary><pre><code>print(7 + 3 * 2)</code></pre></details>""",
        "answer": json.dumps({"1": "A", "2": "C", "3": "B", "4": "D"}, ensure_ascii=False),
        "spec": {
            "type": "matching",
            "pairs": [
                {"key": "1", "left": "7 + 3 * 2"},
                {"key": "2", "left": "20 // 3"},
                {"key": "3", "left": "5 ** 2"},
                {"key": "4", "left": "len(\"python\")"},
            ],
            "options": [
                {"value": "A", "label": "13"},
                {"value": "B", "label": "25"},
                {"value": "C", "label": "6"},
                {"value": "D", "label": "6 символов"},
            ],
            "workspace_modes": ["answer", "code", "canvas"],
        },
        "hints": [
            {"title": "Подсказка 1", "text": "Сначала выполнится умножение, затем сложение."},
            {"title": "Замечания", "text": "Каждый результат используется в одной паре."},
        ],
    },
    {
        "type": "long_answer",
        "score": 3,
        "content": """<h2>Объясни решение</h2>
<p>Опиши словами, как программа получает сумму цифр двузначного числа. Укажи роль операторов <code>//</code> и <code>%</code>.</p>
<details open><summary>Пример</summary><p>Для числа 47 результат равен 11.</p></details>""",
        "answer": "",
        "spec": {
            "type": "long_answer",
            "prompt": "Напиши развёрнутое объяснение решения.",
            "placeholder": "Напишите объяснение...",
            "workspace_modes": ["answer", "code", "canvas"],
        },
        "hints": [{"title": "Подсказка 1", "text": "Раздели число на десятки и единицы."}],
    },
]


def main() -> None:
    logging.disable(logging.CRITICAL)
    app = create_app()
    with app.app_context():
        user = User.query.filter_by(username=STUDENT_USERNAME).first()
        if user is None:
            raise RuntimeError(f"Ученик {STUDENT_USERNAME} не найден")
        student = Student.query.filter_by(user_id=user.id).first()
        if student is None:
            raise RuntimeError(f"Профиль ученика {STUDENT_USERNAME} не найден")

        existing = Assignment.query.filter_by(title=TITLE).first()
        if existing is not None:
            existing.attempts_per_task = True
            submission = Submission.query.filter_by(
                assignment_id=existing.assignment_id, student_id=student.student_id
            ).first()
            if submission is None:
                raise RuntimeError("Тестовая работа существует без сдачи ученика")
            existing_tasks = sorted(existing.tasks, key=lambda item: item.order_index)
            if len(existing_tasks) != len(TASKS):
                raise RuntimeError("В тестовой работе неожиданное количество задач")
            for assignment_task, fixture in zip(existing_tasks, TASKS):
                assignment_task.task.content_html = fixture["content"]
                assignment_task.task.answer_spec = fixture["spec"]
                assignment_task.task.hints = fixture["hints"]
            for assignment_task in existing_tasks[4:]:
                Answer.query.filter_by(
                    submission_id=submission.submission_id,
                    assignment_task_id=assignment_task.assignment_task_id,
                ).delete()
                CodeWorkspaceVersion.query.filter_by(
                    context_type="submission_task",
                    context_id=submission.submission_id,
                    task_id=assignment_task.task_id,
                    student_id=student.student_id,
                ).delete()
                clear_runtime_state(
                    f"workspace:snapshot:submission_task:{submission.submission_id}:"
                    f"{assignment_task.task_id}:{student.user_id}:{assignment_task.assignment_task_id}"
                )
            selected_choice = Answer.query.filter_by(
                submission_id=submission.submission_id,
                assignment_task_id=existing_tasks[1].assignment_task_id,
            ).first()
            if selected_choice is not None:
                selected_choice.score = None
                selected_choice.is_correct = None
                selected_choice.reviewed_at = None
            db.session.commit()
            print(json.dumps({
                "assignment_id": existing.assignment_id,
                "submission_id": submission.submission_id,
                "task_ids": [item.assignment_task_id for item in existing_tasks],
            }, ensure_ascii=False))
            return

        source_submission = (
            Submission.query.filter_by(student_id=student.student_id)
            .order_by(Submission.submission_id.desc())
            .first()
        )
        if source_submission is None or source_submission.assignment is None:
            raise RuntimeError("Не найдена исходная работа для выбора преподавателя и курса")
        source_assignment = source_submission.assignment
        now = utc_now()
        assignment = Assignment(
            title=TITLE,
            description="Изолированная работа для проверки шести интерфейсов ответа.",
            assignment_type="homework",
            deadline=now + timedelta(days=14),
            hide_before_start=False,
            allow_separate_submission=True,
            attempts_per_task=True,
            max_attempts_default=3,
            created_by_id=source_assignment.created_by_id,
            exam_course_id=source_assignment.exam_course_id,
            is_active=True,
        )
        db.session.add(assignment)
        db.session.flush()

        assignment_tasks = []
        for index, item in enumerate(TASKS):
            task = Tasks(
                course_id=source_assignment.exam_course_id,
                task_number=index + 1,
                content_html=item["content"],
                answer=item["answer"],
                starter_code=item.get("starter_code"),
                answer_spec=item["spec"],
                hints=item["hints"],
                created_by_id=source_assignment.created_by_id,
                bank_origin="manual",
                site_task_id=f"workspace-visual-fixture-{index + 1}-{item['type']}",
                max_score=item["score"],
                is_active=True,
            )
            db.session.add(task)
            db.session.flush()
            assignment_task = AssignmentTask(
                assignment_id=assignment.assignment_id,
                task_id=task.task_id,
                order_index=index,
                max_score=item["score"],
                requires_manual_grading=item["type"] in {"code", "long_answer"},
            )
            db.session.add(assignment_task)
            db.session.flush()
            assignment_tasks.append(assignment_task)

        submission = Submission(
            assignment_id=assignment.assignment_id,
            student_id=student.student_id,
            status="IN_PROGRESS",
            assigned_at=now,
            started_at=now,
            max_score=sum(item["score"] for item in TASKS),
        )
        db.session.add(submission)
        db.session.flush()

        seeded_answers = [
            {"student_code": "n = int(input())\nprint(n // 10 + n % 10)\n", "score": 2, "is_correct": True, "reviewed_at": now},
            {"value": "B"},
            {"value": json.dumps(["A", "C"]), "score": 2, "is_correct": True, "reviewed_at": now},
            {"student_code": TASKS[3]["starter_code"]},
        ]
        for assignment_task, answer_values in zip(assignment_tasks, seeded_answers):
            db.session.add(Answer(
                submission_id=submission.submission_id,
                assignment_task_id=assignment_task.assignment_task_id,
                max_score=assignment_task.max_score,
                **answer_values,
            ))

        db.session.commit()
        print(json.dumps({
            "assignment_id": assignment.assignment_id,
            "submission_id": submission.submission_id,
            "task_ids": [item.assignment_task_id for item in assignment_tasks],
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
