import pytest
from app.utils.jinja_filters import clean_task_condition, normalize_task_logic_operators, prepare_task_content_html

def test_normalize_task_logic_operators():
    text = "((x \\/ y) /\\ (w -> z))"
    norm = normalize_task_logic_operators(text)
    assert norm == "((x ∨ y) ∧ (w → z))"
    assert "\\/" not in norm
    assert "/\\" not in norm

def test_clean_task_condition_author_bracket():
    html = "<p><strong>(Д. Бахтиев)</strong> Логическая функция задается выражением...</p>"
    cleaned = clean_task_condition(html)
    assert "(Д. Бахтиев)" not in cleaned
    assert "Логическая функция задается выражением..." in cleaned

def test_clean_task_condition_author_link():
    html = '<p class="MsoNormal"><a href="https://t.me/egeinf_maxim"><strong>(М. Попков)</strong></a> На вход алгоритма подается число...</p>'
    cleaned = clean_task_condition(html)
    assert "М. Попков" not in cleaned
    assert "https://t.me/egeinf_maxim" not in cleaned
    assert "На вход алгоритма подается число..." in cleaned

def test_clean_task_condition_square_bracket():
    html = '<p>[Л. Шастин] На рисунке схема дорог...</p>'
    cleaned = clean_task_condition(html)
    assert "Л. Шастин" not in cleaned
    assert "На рисунке схема дорог..." in cleaned

def test_prepare_task_content_html_does_not_break_disjunction():
    raw = '<p>(x \\/ y) /\\ (w -> z)</p>'
    prepared = prepare_task_content_html(raw)
    assert "∨" in prepared
    assert "∧" in prepared
    assert "→" in prepared
    assert "\\/" not in prepared
    assert "/\\" not in prepared

def test_clean_task_condition_complex_author_and_operators():
    raw = '<p class="MsoNormal"><strong>(Д. Бахтиев)</strong> Логическая функция задается выражением (x \\/ y) /\\ ¬(w -&gt; z)...</p>'
    cleaned = clean_task_condition(raw)
    assert "Д. Бахтиев" not in cleaned
    assert "∨" in cleaned
    assert "∧" in cleaned
    assert "→" in cleaned
    assert "\\/" not in cleaned
    assert "-&gt;" not in cleaned

