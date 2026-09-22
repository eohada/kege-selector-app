import re
from pathlib import Path
from app.utils.jinja_filters import normalize_task_plain_text_to_html, prepare_task_content_html
from app.task_generator.routes import _normalize_manual_content_html

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def test_plain_text_auto_detects_python_code():
    raw_text = (
        "Дана последовательность целых чисел. Все элементы являются натуральными числами, не превышающими 10**9.\n"
        "x = 1000000000000000000\n"
        "count = 0\n"
        "while x > 0:\n"
        "    x //= 2\n"
        "    if x % 10 == 2:\n"
        "        count += 1\n"
        "print(count)\n"
        "В качестве ответа укажите число."
    )
    html = normalize_task_plain_text_to_html(raw_text)
    assert '<pre><code class="language-python">' in html
    assert 'x = 1000000000000000000' in html
    assert 'while x &gt; 0:' in html
    assert 'count += 1' in html
    assert 'print(count)' in html
    assert '10**9' in html
    assert 'В качестве ответа укажите число.' in html


def test_markdown_code_fences_and_inline():
    raw = (
        "Условие задачи:\n"
        "```python\n"
        "f = open('17.txt')\n"
        "a = [int(x) for x in f]\n"
        "print(max(a))\n"
        "```\n"
        "Используйте функцию `len(a)` и **сохраните** результат."
    )
    html = normalize_task_plain_text_to_html(raw)
    assert '<pre><code class="language-python">' in html
    assert "f = open('17.txt')" in html
    assert "<code>len(a)</code>" in html
    assert "<strong>сохраните</strong>" in html


def test_prepare_task_content_html_reformats_legacy_p_br_code():
    legacy_html = (
        '<div class="task-text">'
        '<p>Дана последовательность целых чисел.<br>'
        'x = 1000000000000000000<br>'
        'count = 0<br>'
        'while x &gt; 0:<br>'
        '    x //= 2<br>'
        '    if x % 10 == 2:<br>'
        '        count += 1<br>'
        'print(count)<br>'
        'В качестве ответа укажите число.</p>'
        '</div>'
    )
    result = prepare_task_content_html(legacy_html)
    assert '<pre><code class="language-python">' in result
    assert 'x = 1000000000000000000' in result
    assert 'while x &gt; 0:' in result
    assert '<p>Дана последовательность целых чисел.</p>' in result
    assert '<p>В качестве ответа укажите число.</p>' in result


def test_normalize_manual_content_html_integration():
    raw = "def solve(n):\n    return n * 2\n\nprint(solve(5))"
    res = _normalize_manual_content_html(raw)
    assert '<pre><code class="language-python">' in res
    assert 'def solve(n):' in res


def test_task_workspace_locked_answer_and_redirect_ui():
    workspace_html = (PROJECT_ROOT / 'templates' / 'task_workspace.html').read_text(encoding='utf-8')
    css = (PROJECT_ROOT / 'static' / 'task-workspace' / 'task-workspace.css').read_text(encoding='utf-8')

    # Locked answer input for code tasks
    assert 'tw-locked-answer-wrapper' in workspace_html
    assert 'tw-locked-answer-field' in workspace_html
    assert 'tw-locked-answer-icon' in workspace_html
    assert 'tw-locked-answer-pill' in workspace_html
    assert '.tw-locked-answer-field' in css

    # Tactile redirect card with arrow to code tab
    assert 'tw-code-redirect-card' in workspace_html
    assert 'tw-btn-goto-code' in workspace_html
    assert 'tw-btn-goto-arrow' in workspace_html
    assert '.tw-code-redirect-card' in css
    assert '.tw-btn-goto-code' in css
    assert '.tw-btn-goto-arrow' in css

    # Ensure raw ugly placeholder text '# Решение пока не написано' in pre is removed from answer card
    assert '# Решение пока не написано' not in workspace_html
