"""Regression checks for the canonical V2 workspace and navigation surfaces."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _read_template(relative_path: str) -> str:
    return (PROJECT_ROOT / 'templates' / relative_path).read_text(encoding='utf-8')


def test_workspace_has_a_single_v2_entry_point():
    task_detail = _read_template('sandbox/task_detail.html')
    workspace = _read_template('task_workspace.html')

    assert '/sandbox/workspace' not in task_detail
    assert 'task_workspace.workspace_page' in task_detail
    assert 'id="tw-workspace-grid"' in workspace
    assert 'task-workspace/task-workspace.css' in workspace
    assert 'sandbox/layout_teacher.html' in workspace
    assert 'sandbox/layout_student.html' in workspace
    assert '{% extends "base.html" %}' not in workspace


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
        assert 'confirm(' not in content, relative_path
        assert 'alert(' not in content, relative_path
