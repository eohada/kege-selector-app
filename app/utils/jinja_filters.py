"""
Jinja2 фильтры для шаблонов
"""
import re
from bs4 import BeautifulSoup

from app.auth.rbac_utils import mask_contact_info
from flask_login import current_user


def _deduplicate_latex_blocks(html: str) -> str:
    """Удаляет подряд идущие одинаковые блоки $...$ и $$...$$ (убирает дубликат и текст между ними)."""
    if not html or not html.strip():
        return html
    for pattern, delimiter in [
        (re.compile(r'\$\$([^$]+?)\$\$'), '$$'),
        (re.compile(r'\$([^$]+?)\$'), '$'),
    ]:
        matches = list(pattern.finditer(html))
        to_remove = []
        for i in range(len(matches) - 1):
            c1 = matches[i].group(1).strip()
            c2 = matches[i + 1].group(1).strip()
            if c1 == c2:
                to_remove.append((matches[i].end(), matches[i + 1].end()))
        for start, end in reversed(to_remove):
            html = html[:start] + ' ' + html[end:]
    return html


def _remove_duplicate_formula_text_after_katex(soup: BeautifulSoup) -> None:
    """Удаляет дублирующий текст формулы, идущий сразу после элемента .katex."""
    for katex in soup.find_all('span', class_=lambda c: c and 'katex' in (c if isinstance(c, str) else ' '.join(c))):
        n = katex.next_sibling
        if n is None:
            continue
        text = None
        if hasattr(n, 'string') and getattr(n, 'string', None) is not None:
            text = (n.string or '').strip()
        elif getattr(n, 'name', None) and n.name and getattr(n, 'get_text', None):
            text = n.get_text(strip=True) if hasattr(n, 'get_text') else ''
        if not text or len(text) > 300:
            continue
        if '=' not in text:
            continue
        formula_like = any(s in text for s in ('¬', '≡', '∧', '∨', '^', ' v ', '\\lor', '\\land', '\\neg', '\\equiv'))
        if formula_like or ('(' in text and ')' in text and len(text) < 120):
            if hasattr(n, 'replace_with'):
                n.replace_with('')
            elif hasattr(n, 'decompose'):
                n.decompose()


def deduplicate_formulas(html):
    """
    Убирает дублирование формул в HTML заданий: одинаковые подряд идущие $...$ / $$...$$
    и дублирующий текст после уже отрендеренных .katex (чтобы формулы не отображались дважды).
    """
    if not html:
        return html
    try:
        html = _deduplicate_latex_blocks(html)
        soup = BeautifulSoup(html, 'html.parser')
        _remove_duplicate_formula_text_after_katex(soup)
        return str(soup)
    except Exception:
        return html


def mask_contact_if_tutor(value):
    """
    Маскирует контактную информацию, если текущий пользователь - тьютор.
    Используется в шаблонах для защиты приватности учеников.
    
    Args:
        value: Контактная информация (телефон, email)
        
    Returns:
        Замаскированная или оригинальная информация в зависимости от роли
    """
    if not value:
        return value
    
    if current_user.is_authenticated and current_user.is_tutor():
        return mask_contact_info(value)
    
    return value


def init_jinja_filters(app):
    """Инициализация Jinja2 фильтров"""
    app.jinja_env.filters['mask_contact'] = mask_contact_if_tutor
    app.jinja_env.filters['deduplicate_formulas'] = deduplicate_formulas
