from types import SimpleNamespace

import app.task_workspace.service as workspace_service
from app.task_workspace.service import WorkspaceContext
from app.task_bank.answer_safety import (
    ANSWER_EXPOSURE_NOTICE,
    answer_appears_in_labeled_example,
    student_safe_content_html,
)


def test_blocks_example_that_repeats_complete_expected_answer():
    content = (
        "<p>Формат ответа (пример формата: "
        "S-A-T;S-B-C-T;5).</p>"
    )
    assert answer_appears_in_labeled_example(content, "S-A-T;S-B-C-T;5")


def test_does_not_treat_unrelated_numeric_example_as_answer_leak():
    content = "<p>Пример формата: S-A-T;S-B-C-T;20.</p>"
    assert not answer_appears_in_labeled_example(content, "5")


def test_does_not_match_answer_outside_labeled_example():
    content = "<p>Стоимость оптимального маршрута равна 5.</p>"
    assert not answer_appears_in_labeled_example(content, "5")


def test_allows_neutral_format_example():
    content = "<p>Пример формата: S-A-T;S-B-C-T;стоимость.</p>"
    assert not answer_appears_in_labeled_example(content, "S-A-T;S-B-C-T;5")


def test_student_payload_withholds_contaminated_condition_until_review():
    content = "<p>Пример формата: A-B;5.</p>"
    safe_content, blocked = student_safe_content_html(
        content, "A-B;5", allow_review_details=False
    )
    assert blocked
    assert safe_content == ANSWER_EXPOSURE_NOTICE
    assert "A-B;5" not in safe_content

    reviewed_content, reviewed_blocked = student_safe_content_html(
        content, "A-B;5", allow_review_details=True
    )
    assert not reviewed_blocked
    assert reviewed_content == content


def test_workspace_payload_blocks_student_and_preserves_teacher_review(monkeypatch):
    monkeypatch.setattr(workspace_service, "load_workspace_trace_payload", lambda _ctx: None)
    monkeypatch.setattr(workspace_service, "load_workspace_versions_payload", lambda _ctx: [])
    monkeypatch.setattr(workspace_service, "load_workspace_multi_file_state", lambda _ctx: {})
    monkeypatch.setattr(workspace_service, "load_workspace_state_payload", lambda _ctx: {})
    task = SimpleNamespace(
        task_id=44,
        answer="A-B;5",
        answer_spec={
            "type": "single_choice",
            "options": [{"value": "1", "label": "Маршрут 1"}],
            "correct_value": "A-B;5",
        },
        starter_code="",
        hints=[],
        attached_files=None,
        bank_category="exam",
        max_score=1,
        content_html="<p>Пример формата: A-B;5.</p>",
        source_url=None,
        task_number=9913,
        title="Synthetic graph exercise",
        difficulty_label="medium",
    )
    student_context = WorkspaceContext(
        context_type="submission_task",
        context_id=1,
        task_id=44,
        task=task,
        title="Homework",
        subtitle="Synthetic student",
        source_label="Synthetic",
        correct_answer="A-B;5",
    )
    student_payload = student_context.as_payload()
    assert student_payload["task_content_blocked"] is True
    assert "A-B;5" not in student_payload["content_html"]
    assert student_payload["correct_answer"] == ""
    assert student_payload["answer_spec"]["options"] == [{"value": "1", "label": "Маршрут 1"}]
    assert student_payload["answer_spec"].get("correct_value") is None
    assert "A-B;5" not in str(student_payload)

    teacher_payload = WorkspaceContext(
        context_type="submission_task",
        context_id=1,
        task_id=44,
        task=task,
        title="Homework",
        subtitle="Synthetic student",
        source_label="Synthetic",
        can_review=True,
        correct_answer="A-B;5",
    ).as_payload()
    assert teacher_payload["task_content_blocked"] is False
    assert "A-B;5" in teacher_payload["content_html"]
    assert teacher_payload["correct_answer"] == "A-B;5"
