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


def test_workspace_provides_code_mode_answer_field_and_tactile_styling():
    workspace = _read_template('task_workspace.html')
    task_detail = _read_template('sandbox/task_detail.html')
    script = (PROJECT_ROOT / 'static' / 'task-workspace' / 'task-workspace.js').read_text(encoding='utf-8')
    css = (PROJECT_ROOT / 'static' / 'task-workspace' / 'task-workspace.css').read_text(encoding='utf-8')

    assert 'id="tw-code-answer-box"' in workspace
    assert 'id="tw-code-answer-input"' in workspace
    assert 'tw-code-answer-box' in workspace
    assert "document.getElementById('tw-code-answer-input')" in script
    assert 'codeAnswerInput' in script
    assert '.tw-code-answer-box' in css
    assert 'max-w-[1400px]' in workspace
    assert 'max-w-[1400px]' in task_detail
    # Check that 3D buttons do not cancel out their tactile borders with border-none
    for line in task_detail.splitlines():
        if 'border-b-[4px]' in line:
            assert 'border-none' not in line, f"Found border-none on 3D button: {line.strip()}"


def test_workspace_code_solution_syntax_highlighting_and_tactile_buttons():
    workspace = _read_template('task_workspace.html')
    script = (PROJECT_ROOT / 'static' / 'task-workspace' / 'task-workspace.js').read_text(encoding='utf-8')
    css = (PROJECT_ROOT / 'static' / 'task-workspace' / 'task-workspace.css').read_text(encoding='utf-8')

    # Code solution as answer elements
    assert 'tw-code-solution-panel' in workspace
    assert 'tw-btn-submit-code' in workspace
    assert 'tw-btn-insert-output' in workspace
    assert 'tw-code-standard-info' in workspace
    assert '#tw-btn-submit-code' in script
    assert '#tw-btn-insert-output' in script

    # Syntax highlighting: transparent textarea overlay over colored tw-highlight
    assert '-webkit-text-fill-color:transparent' in css or '-webkit-text-fill-color: transparent' in css
    assert 'tok-keyword' in css
    assert 'tok-builtin' in css
    assert 'tok-string' in css
    assert 'tok-number' in css
    assert 'tok-op' in css

    # BooStudy UI Canon: tactile 3D buttons and cards
    assert 'border-bottom:4px solid #312e81' in css or 'border-bottom: 4px solid #312e81' in css
    assert 'border-bottom:4px solid #94a3b8' in css or 'border-bottom: 4px solid #94a3b8' in css
    assert 'translateY(3px)' in css

    # Progress bar and non-colliding typography
    assert 'tw-bottom-progress-text' in workspace
    assert 'tw-progress-badge' in workspace
    assert '.tw-bottom-progress-text' in css
    assert '.tw-progress-badge' in css


def test_workspace_top_spacing_custom_select_and_multi_type_code_actions():
    workspace = _read_template('task_workspace.html')
    script = (PROJECT_ROOT / 'static' / 'task-workspace' / 'task-workspace.js').read_text(encoding='utf-8')
    css = (PROJECT_ROOT / 'static' / 'task-workspace' / 'task-workspace.css').read_text(encoding='utf-8')

    # Top spacing: .tw-shell has margin-top and is not glued to top: 0
    assert 'margin: 24px auto 36px' in css or 'margin:24px auto 36px' in css
    assert 'py-6' in workspace

    # Custom 3D selects for matching and BooStudy UI Canon style
    assert 'tw-custom-select' in workspace
    assert 'tw-custom-select-trigger' in workspace
    assert 'tw-custom-select-menu' in workspace
    assert '.tw-custom-select' in css
    assert '.tw-custom-select-trigger' in css
    assert '.tw-custom-select-menu' in css
    assert '.tw-custom-select' in script

    # Code solution actions available in long_answer and short_answer modes
    assert 'tw-code-answer-actions' in workspace
    assert 'tw-btn-append-code' in workspace
    assert '#tw-btn-append-code' in script
    assert '.tw-code-answer-actions' in css


def test_task_builder_blocks_and_code_mode_choice_matching():
    create_assignment = _read_template('sandbox/create_assignment.html')
    workspace = _read_template('task_workspace.html')
    css = (PROJECT_ROOT / 'static' / 'task-workspace' / 'task-workspace.css').read_text(encoding='utf-8')
    script = (PROJECT_ROOT / 'static' / 'task-workspace' / 'task-workspace.js').read_text(encoding='utf-8')

    # Task builder structure in create_assignment
    assert 'Конструктор заданий' in create_assignment
    assert 'Основные параметры' in create_assignment
    assert 'Условие задания' in create_assignment
    assert 'Файлы и материалы' in create_assignment
    assert 'Тип ответа и проверка' in create_assignment
    assert 'Подсказки и разбор' in create_assignment

    # 5 Answer types supported
    assert 'data-type="short_answer"' in create_assignment
    assert 'data-type="single_choice"' in create_assignment
    assert 'data-type="matching"' in create_assignment
    assert 'data-type="code"' in create_assignment
    assert 'data-type="long_answer"' in create_assignment

    # Interactive builder JS functions
    assert 'selectBuilderAnswerType' in create_assignment
    assert 'addBuilderChoiceOption' in create_assignment
    assert 'addBuilderMatchingOption' in create_assignment
    assert 'addBuilderMatchingPair' in create_assignment
    assert 'switchBuilderConditionTab' in create_assignment

    # Code mode choice and matching
    assert 'tw-choice-grid-code' in workspace
    assert 'tw-matching-list-code' in workspace
    assert '.tw-choice-grid-code' in css
    assert '.tw-matching-list-code' in css
    assert '.tw-choice-card-sm' in css
    assert '.tw-match-row-sm' in css

    # Synchronized radio and select bindings in task-workspace.js
    assert "document.querySelectorAll('[data-answer-renderer=\"single_choice\"]')" in script
    assert "document.querySelectorAll('[data-answer-renderer=\"matching\"]')" in script
    assert 'updateAllMatchingViews' in script
