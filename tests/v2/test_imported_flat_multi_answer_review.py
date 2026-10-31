from types import SimpleNamespace

from app.assignments import routes


def _grade(monkeypatch, *, task, student_answer, correct_answer):
    monkeypatch.setattr(routes, '_effective_correct_answer', lambda _assignment_task: correct_answer)
    monkeypatch.setattr(routes, '_get_task_template', lambda _task: None)
    assignment_task = SimpleNamespace(task=task, max_score=3)
    answer = SimpleNamespace(value=student_answer)
    return routes.auto_grade_answer(answer, assignment_task)


def test_imported_flat_multi_value_key_with_row_instructions_requires_manual_review(monkeypatch):
    task = SimpleNamespace(
        bank_origin='imported',
        answer_spec={'type': 'short_answer'},
        content_html='<p>В первой строке укажите количество, во второй строке — сумму.</p>',
    )

    assert _grade(
        monkeypatch,
        task=task,
        student_answer='597 432408 352',
        correct_answer='597 432408 352',
    ) == (None, None)


def test_imported_flat_key_without_structured_output_requirement_keeps_scalar_grading(monkeypatch):
    task = SimpleNamespace(
        bank_origin='imported',
        answer_spec={'type': 'short_answer'},
        content_html='<p>Вычислите значение выражения.</p>',
    )

    assert _grade(
        monkeypatch,
        task=task,
        student_answer='597 432408 352',
        correct_answer='597 432408 352',
    ) == (True, 3)


def test_non_imported_tasks_are_not_routed_to_manual_review_by_import_guard(monkeypatch):
    task = SimpleNamespace(
        bank_origin=None,
        answer_spec={'type': 'short_answer'},
        content_html='<p>В первой строке укажите количество, во второй строке — сумму.</p>',
    )

    assert _grade(
        monkeypatch,
        task=task,
        student_answer='597 432408 352',
        correct_answer='597 432408 352',
    ) == (True, 3)
