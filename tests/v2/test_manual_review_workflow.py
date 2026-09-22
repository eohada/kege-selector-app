import pytest
from pathlib import Path
from unittest.mock import MagicMock

from app.task_workspace.service import _is_task_manual_review
from app.assignments.routes import _is_assignment_task_manual_review

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def test_is_task_manual_review_detection():
    # 1. requires_manual_grading attribute on assignment_task
    at_mock = MagicMock()
    at_mock.requires_manual_grading = True
    task_mock = MagicMock()
    task_mock.task_type = 'short_answer'
    task_mock.template = None
    assert _is_task_manual_review(at_mock, task_mock) is True
    assert _is_assignment_task_manual_review(at_mock) is True

    # 2. code task_type
    at_mock.requires_manual_grading = False
    task_mock.task_type = 'code'
    assert _is_task_manual_review(at_mock, task_mock) is True

    # 3. long_answer task_type
    task_mock.task_type = 'long_answer'
    assert _is_task_manual_review(at_mock, task_mock) is True

    # 4. Standard auto-graded short answer
    task_mock.task_type = 'short_answer'
    assert _is_task_manual_review(at_mock, task_mock) is False


def test_manual_review_css_statuses():
    css = (PROJECT_ROOT / 'static' / 'task-workspace' / 'task-workspace.css').read_text(encoding='utf-8')

    # Ensure tactile 3D stepper status styles exist
    assert '.status-pending_review' in css
    assert '#fefce8' in css  # yellow bg
    assert '.status-correct' in css
    assert '#f0fdf4' in css  # green bg
    assert '.status-wrong' in css
    assert '#fef2f2' in css  # red bg
    assert '.status-partial' in css
    assert '#fffbeb' in css  # amber/yellow bg


def test_templates_support_4_state_stepper_and_answer_hiding():
    workspace_html = (PROJECT_ROOT / 'templates' / 'task_workspace.html').read_text(encoding='utf-8')
    task_detail_html = (PROJECT_ROOT / 'templates' / 'sandbox' / 'task_detail.html').read_text(encoding='utf-8')

    # Stepper in task_workspace.html uses status class and proper icons
    assert 'status-{{ nav_item.nav_status }}' in workspace_html
    assert 'ph-clock' in workspace_html
    assert 'ph-circle-half' in workspace_html
    assert 'ph-check' in workspace_html
    assert 'ph-x' in workspace_html

    # task_detail.html uses 4-color stepper tabs and hides correct answer if not reviewed
    assert 'tab-btn-' in task_detail_html
    assert 'ph-circle-half' in task_detail_html
    assert '{% if t.correct_answer %}' in task_detail_html
    assert 'Ответ отправлен на проверку преподавателю' in task_detail_html


def test_safe_answer_hint_hidden_from_student_until_reviewed():
    from app.task_workspace.service import WorkspaceContext
    from core.db_models import Tasks

    fake_task = Tasks(task_id=999, answer="secret_answer", starter_code="print(1)")

    # 1. Student before review -> answer MUST be hidden ("")
    ctx_student = WorkspaceContext(
        context_type="submission_task",
        context_id=1,
        task_id=999,
        task=fake_task,
        title="Task 999",
        subtitle="",
        source_label="",
        assignment_title="Assignment",
        return_url="/",
        student_id=10,
        student_user_id=20,
        can_edit=True,
        can_review=False,
        is_reviewed=False,
        is_manual=True,
    )
    payload_student = ctx_student.as_payload()
    assert payload_student["answer_hint"] == ""

    # 2. Student after review -> answer is visible
    ctx_reviewed = WorkspaceContext(
        context_type="submission_task",
        context_id=1,
        task_id=999,
        task=fake_task,
        title="Task 999",
        subtitle="",
        source_label="",
        assignment_title="Assignment",
        return_url="/",
        student_id=10,
        student_user_id=20,
        can_edit=False,
        can_review=False,
        is_reviewed=True,
        is_manual=True,
    )
    payload_reviewed = ctx_reviewed.as_payload()
    assert payload_reviewed["answer_hint"] == "secret_answer"

    # 3. Teacher -> answer is visible even if not reviewed
    ctx_teacher = WorkspaceContext(
        context_type="submission_task",
        context_id=1,
        task_id=999,
        task=fake_task,
        title="Task 999",
        subtitle="",
        source_label="",
        assignment_title="Assignment",
        return_url="/",
        student_id=10,
        student_user_id=20,
        can_edit=False,
        can_review=True,
        is_reviewed=False,
        is_manual=True,
    )
    payload_teacher = ctx_teacher.as_payload()
    assert payload_teacher["answer_hint"] == "secret_answer"

