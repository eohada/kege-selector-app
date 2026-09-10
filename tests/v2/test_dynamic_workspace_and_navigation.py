"""Regression checks for the canonical V2 workspace and navigation surfaces."""

from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _read_template(relative_path: str) -> str:
    return (PROJECT_ROOT / 'templates' / relative_path).read_text(encoding='utf-8')


def test_workspace_has_a_single_v2_entry_point():
    task_detail = _read_template('sandbox/task_detail.html')
    workspace = _read_template('task_workspace.html')

    assert '/sandbox/workspace' not in task_detail
    assert 'task_workspace.workspace_page' in task_detail
    assert 'id="tw-code-workspace-grid"' in workspace
    assert 'id="tw-standard-workspace-grid"' in workspace
    assert 'task-workspace/task-workspace.css' in workspace
    assert 'sandbox/layout_teacher.html' in workspace
    assert 'sandbox/layout_student.html' in workspace
    assert '{% extends "base.html" %}' not in workspace
    assert "canvas_overlay.html" not in workspace
    assert 'workspace.next_task' in workspace


def test_active_workspace_templates_do_not_call_legacy_workspace_apis():
    for relative_path in (
        'sandbox/task_detail.html',
        'task_workspace.html',
        'sandbox/assignment_detail.html',
    ):
        content = _read_template(relative_path)
        assert '/sandbox/workspace' not in content, relative_path
        assert '/sandbox/api/workspace/' not in content, relative_path
        assert '/sandbox/api/task_detail/' not in content, relative_path


def test_active_workspace_templates_do_not_use_browser_blocking_dialogs():
    for relative_path in (
        'sandbox/task_detail.html',
        'task_workspace.html',
        'sandbox/assignment_detail.html',
    ):
        content = _read_template(relative_path)
        assert not re.search(r'(?<![\w.])confirm\s*\(', content), relative_path
        assert not re.search(r'(?<![\w.])alert\s*\(', content), relative_path


def test_workspace_declares_universal_standard_and_code_modes():
    workspace = _read_template('task_workspace.html')
    script = (PROJECT_ROOT / 'static' / 'task-workspace' / 'task-workspace.js').read_text(encoding='utf-8')

    assert 'data-workspace-mode-switch' in workspace
    assert 'data-workspace-mode="answer"' in workspace
    assert 'data-workspace-mode="code"' in workspace
    assert 'tw-standard-grid' in workspace
    assert 'data-answer-renderer="single_choice"' in workspace
    assert 'data-answer-renderer="matching"' in workspace
    assert 'workspace.hints' in workspace
    assert 'workspace.attachments' in workspace
    assert 'answer: answer ? answer.value' in script
    assert 'bindStandardAnswerRenderer' in script
    assert 'applyWorkspaceMode' in script
    assert 'workspace_modes' in script
