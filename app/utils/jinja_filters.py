"""
Jinja2 фильтры для шаблонов
"""
import re
from bs4 import BeautifulSoup

from app.auth.rbac_utils import mask_contact_info
from flask import url_for, request
from flask_login import current_user
from markupsafe import Markup, escape


def ui_icon(key, size="sm", title=None, decorative=True, extra_class=""):
    """
    Render a Lucide SVG icon inline.
    Usage in Jinja: {{ ui_icon('nav.students', 'md') }}
    """
    from app.utils.icons import get_icon_svg_inner

    size = str(size or "sm")
    if size not in ("sm", "md", "lg"):
        size = "sm"

    svg_class = f"ui-icon ui-icon--{size}"
    if extra_class:
        svg_class = f"{svg_class} {extra_class}"

    inner = get_icon_svg_inner(str(key or ""))

    wrapper_aria = ' aria-hidden="true"' if decorative else ""
    aria_attr = ' aria-hidden="true"' if decorative else ""
    role_attr = "" if decorative else ' role="img"'
    label_attr = ""
    if (not decorative) and title:
        label_attr = f' aria-label="{escape(str(title))}"'

    if inner:
        html = (
            f'<span class="ui-icon-slot ui-icon-slot--{escape(size)}"'
            f"{wrapper_aria}>"
            f'<svg class="{escape(svg_class)}" viewBox="0 0 24 24" fill="none" '
            f'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'
            f"{aria_attr}{role_attr}{label_attr} focusable=\"false\">"
            f"{inner}"
            f"</svg>"
            f"</span>"
        )
    else:
        sprite_href = url_for("static", filename="icons/sprite.svg") + f"#{escape(str(key or '').replace('.', '-'))}"
        html = (
            f'<span class="ui-icon-slot ui-icon-slot--{escape(size)}" '
            f'data-asset-key="{escape(str(key or ""))}"'
            f"{wrapper_aria}>"
            f'<svg class="{escape(svg_class)}"{aria_attr}{role_attr}{label_attr} focusable="false">'
            f'<use href="{escape(sprite_href)}"></use>'
            f"</svg>"
            f"</span>"
        )
    return Markup(html)


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


# Паттерн: текст формулы-дубликата без степеней (цифры склеены: 144^26 → 14426)
_MANGLED_FORMULA_PATTERN = re.compile(
    r'^\s*[\d\s·⋅\+−\-]+\s*$'
)


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
        # Удалить дубликат в виде «склеенных» чисел (6·144^26 → 486·14426+11·1275−48)
        if 15 <= len(text) <= 250 and _MANGLED_FORMULA_PATTERN.match(text):
            if hasattr(n, 'replace_with'):
                n.replace_with('')
            elif hasattr(n, 'decompose'):
                n.decompose()
            continue
        if '=' not in text:
            continue
        formula_like = any(s in text for s in ('¬', '≡', '∧', '∨', '^', ' v ', '\\lor', '\\land', '\\neg', '\\equiv'))
        if formula_like or ('(' in text and ')' in text and len(text) < 120):
            if hasattr(n, 'replace_with'):
                n.replace_with('')
            elif hasattr(n, 'decompose'):
                n.decompose()


def _remove_duplicate_plain_formula_in_text(soup: BeautifulSoup) -> None:
    """Удаляет в текстовых узлах повтор формулы в виде склеенных чисел (144^26 и следом 14426)."""
    for text_node in soup.find_all(string=True):
        if text_node.parent and text_node.parent.name in ('script', 'style'):
            continue
        text = (text_node.string or '')
        stripped = text.strip()
        if len(stripped) < 25 or len(stripped) > 500:
            continue
        # Ищем с конца подстроку, похожую на дубликат (только цифры, ·, +, −)
        for sep in ('  ', ' ', '−', '\n'):
            idx = stripped.rfind(sep)
            if idx < 10:
                continue
            tail = stripped[idx:].strip()
            if 15 <= len(tail) <= 220 and _MANGLED_FORMULA_PATTERN.match(tail):
                before = stripped[:idx].rstrip()
                if len(before) >= 10 and re.search(r'[·⋅\d]', before[-15:]):
                    try:
                        text_node.replace_with(before)
                    except Exception:
                        pass
                break


def deduplicate_formulas(html):
    """
    Убирает дублирование формул в HTML заданий: одинаковые подряд идущие $...$ / $$...$$,
    дублирующий текст после .katex и склеенные копии формул (144^26 → 14426).
    """
    if not html:
        return html
    try:
        html = _deduplicate_latex_blocks(html)
        soup = BeautifulSoup(html, 'html.parser')
        _remove_duplicate_formula_text_after_katex(soup)
        _remove_duplicate_plain_formula_in_text(soup)
        return str(soup)
    except Exception:
        return html


def task_content_absolute_urls(html):
    """
    Делает относительные src изображений в контенте задания абсолютными,
    чтобы картинки не пропадали при открытии с разных путей (например /submissions/123).
    """
    if not html or not isinstance(html, str):
        return html
    try:
        base = (request.url_root or '').rstrip('/')
        if not base:
            return html
        # src="/path" -> src="https://site/path"
        html = re.sub(r'\bsrc=["\']/(?!\/)', f'src="{base}/', html)
        return html
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


def strip_attachment_links(html):
    """
    Убирает из HTML контента задания ссылки на вложения (файлы),
    чтобы не дублировать их с отдельным блоком attached_files.
    Удаляет <a> ведущие на kompege.ru/…/files/, /uploads/, .txt, .py, .csv и т.п.
    """
    if not html or not isinstance(html, str):
        return html
    try:
        soup = BeautifulSoup(html, 'html.parser')
        file_ext_re = re.compile(r'\.(txt|py|csv|xlsx?|docx?|pdf|zip|rar|7z|dat|json|xml)(\?|$)', re.I)
        file_path_re = re.compile(r'(/files/|/uploads/|/media/|/attached/)', re.I)
        changed = False
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            if file_ext_re.search(href) or file_path_re.search(href):
                parent = a_tag.parent
                a_tag.decompose()
                if parent and parent.name in ('p', 'div', 'span', 'li') and not parent.get_text(strip=True):
                    parent.decompose()
                changed = True
        return str(soup) if changed else html
    except Exception:
        return html


_BLEACH_ALLOWED_TAGS = [
    'p', 'br', 'b', 'i', 'u', 'em', 'strong', 'sub', 'sup', 'small',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'ul', 'ol', 'li', 'dl', 'dt', 'dd',
    'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td', 'caption', 'colgroup', 'col',
    'a', 'img', 'figure', 'figcaption',
    'pre', 'code', 'blockquote', 'hr',
    'span', 'div', 'section', 'article',
    'math', 'semantics', 'mrow', 'mi', 'mn', 'mo', 'msup', 'msub',
    'mfrac', 'mroot', 'msqrt', 'munder', 'mover', 'mtable', 'mtr', 'mtd',
    'annotation',
    'svg', 'path', 'line', 'circle', 'rect', 'g', 'use', 'defs', 'symbol',
]

_BLEACH_ALLOWED_ATTRS = {
    '*': ['class', 'id', 'style', 'data-*', 'role', 'aria-label', 'aria-hidden', 'title', 'dir', 'lang'],
    'a': ['href', 'target', 'rel', 'download'],
    'img': ['src', 'alt', 'width', 'height', 'loading'],
    'td': ['colspan', 'rowspan'],
    'th': ['colspan', 'rowspan', 'scope'],
    'col': ['span'],
    'colgroup': ['span'],
    'svg': ['viewBox', 'width', 'height', 'fill', 'xmlns'],
    'path': ['d', 'fill', 'stroke', 'stroke-width'],
    'line': ['x1', 'y1', 'x2', 'y2', 'stroke'],
    'circle': ['cx', 'cy', 'r', 'fill', 'stroke'],
    'rect': ['x', 'y', 'width', 'height', 'rx', 'ry', 'fill', 'stroke'],
    'use': ['href', 'xlink:href'],
    'annotation': ['encoding'],
}


def sanitize_html(html):
    """
    Пропускает HTML через bleach с белым списком тегов/атрибутов,
    затем помечает результат как safe для Jinja2.
    """
    if not html:
        return ''
    try:
        import bleach
        from markupsafe import Markup
        cleaned = bleach.clean(
            str(html),
            tags=_BLEACH_ALLOWED_TAGS,
            attributes=_BLEACH_ALLOWED_ATTRS,
            strip=True,
        )
        return Markup(cleaned)
    except Exception:
        from markupsafe import Markup, escape
        return Markup(escape(str(html)))


def init_jinja_filters(app):
    """Инициализация Jinja2 фильтров"""
    app.jinja_env.filters['mask_contact'] = mask_contact_if_tutor
    app.jinja_env.filters['deduplicate_formulas'] = deduplicate_formulas
    app.jinja_env.filters['task_content_absolute_urls'] = task_content_absolute_urls
    app.jinja_env.filters['strip_attachment_links'] = strip_attachment_links
    app.jinja_env.filters['sanitize_html'] = sanitize_html
    app.jinja_env.globals["ui_icon"] = ui_icon
    app.jinja_env.globals["ui_icon_global"] = ui_icon
