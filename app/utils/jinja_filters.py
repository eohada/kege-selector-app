"""
Jinja2 фильтры для шаблонов
"""
import html as html_lib
import json
import re
from urllib.parse import quote
from typing import Optional

from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

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


_KOMPEGE_ORIGIN = "https://kompege.ru"
# Корневые пути, которые относятся к этой платформе (остальные корневые src в заданиях — с kompege.ru).
_PLATFORM_MEDIA_PREFIXES = (
    "/static/",
    "/uploads/",
    "/attachments/",
    "/media/",
    "/internal/",
)


def _resolve_site_base(site_base: Optional[str]) -> str:
    if site_base is not None:
        return str(site_base).rstrip("/")
    try:
        return (request.url_root or "").rstrip("/")
    except RuntimeError:
        return ""


def _normalize_root_media_url(raw: str, site_base: str) -> str:
    """Абсолютный URL для src медиа: платформа vs kompege для корневых путей."""
    v = (raw or "").strip()
    if not v:
        return v
    if v.startswith("//"):
        return "https:" + v
    if not v.startswith("/") or v.startswith("//"):
        return v
    low = v.lower()
    for p in _PLATFORM_MEDIA_PREFIXES:
        if low.startswith(p.lower()):
            return (site_base + v) if site_base else v
    return _KOMPEGE_ORIGIN + v


def normalize_task_content_urls(html, site_base: Optional[str] = None):
    """
    Нормализует src у img/source/iframe/video в HTML задания:
    - //host/... → https://host/...
    - /static/, /uploads/, ... → корень текущего сайта (если известен)
    - прочие /... (типично /images/ с kompege) → https://kompege.ru/...
    """
    if not html or not isinstance(html, str):
        return html
    # Полноширинный обратный слэш U+FF3C — KaTeX не распознаёт как начало \\(, \\).
    html = html.replace("\uFF3C", "\\")
    sb = _resolve_site_base(site_base)
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all(["img", "source", "iframe", "video"]):
            if tag.get("src"):
                tag["src"] = _normalize_root_media_url(tag["src"], sb)
        return str(soup)
    except Exception:
        return html


def task_content_absolute_urls(html):
    """
    Обратная совместимость: раньше все src="/ подставлялись под сайт и ломали /images/ с kompege.
    Теперь делегирует normalize_task_content_urls.
    """
    return normalize_task_content_urls(html)


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
                # Если ссылка оборачивает изображение (частый кейс таблиц-картинок),
                # не удаляем саму картинку — только "снимаем" ссылку.
                if a_tag.find('img'):
                    a_tag.unwrap()
                else:
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
    'table': ['border', 'cellpadding', 'cellspacing', 'align', 'valign'],
    'tr': ['align', 'valign'],
    'td': ['colspan', 'rowspan', 'align', 'valign'],
    'th': ['colspan', 'rowspan', 'scope', 'align', 'valign'],
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
            protocols=['http', 'https', 'mailto', 'data'],
            strip=True,
        )
        return Markup(cleaned)
    except Exception:
        # Fallback без bleach: сохраняем HTML-структуру (p/table/img), но чистим опасные узлы/атрибуты.
        from markupsafe import Markup
        try:
            soup = BeautifulSoup(str(html), 'html.parser')
            for tag in soup.find_all(['script', 'style', 'iframe', 'object', 'embed']):
                tag.decompose()
            for tag in soup.find_all(True):
                attrs = dict(tag.attrs or {})
                for attr_name, attr_value in list(attrs.items()):
                    low_name = str(attr_name).lower()
                    if low_name.startswith('on'):
                        tag.attrs.pop(attr_name, None)
                        continue
                    if low_name in ('href', 'src', 'xlink:href'):
                        val = attr_value if isinstance(attr_value, str) else ' '.join(attr_value) if isinstance(attr_value, list) else str(attr_value)
                        if val.strip().lower().startswith('javascript:'):
                            tag.attrs.pop(attr_name, None)
            return Markup(str(soup))
        except Exception:
            # Крайний fallback: не ломаем страницу, отдаём исходник как safe-string.
            return Markup(str(html))


def normalize_task_plain_text_to_html(raw_text: Optional[str]) -> str:
    """
    Преобразует plain text условия в безопасный HTML с сохранением переносов строк.
    """
    text = (raw_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return '<div class="task-text"></div>'
    escaped = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    # Два и более перевода строки -> новый абзац. Одиночный перевод -> <br>.
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", escaped) if p.strip()]
    if not paragraphs:
        return '<div class="task-text"></div>'
    html_paragraphs = []
    for paragraph in paragraphs:
        html_paragraphs.append(f"<p>{paragraph.replace(chr(10), '<br>')}</p>")
    return '<div class="task-text">' + "".join(html_paragraphs) + "</div>"


_HTML_TAG_PATTERN = re.compile(r"<[a-zA-Z!?][^>]*>")
_AUTHOR_SIGNATURE_RE = re.compile(
    r'^\s*\(\s*'
    r'(?:'
    r'[А-ЯЁ]\.\s*(?:[А-ЯЁ]\.\s*)?[А-ЯЁ][а-яё-]+'
    r'|'
    r'[А-ЯЁ][а-яё-]+\s+[А-ЯЁ]\.?'
    r'|'
    r'[А-ЯЁ][а-яё-]+\s+[А-ЯЁ]\.\s*[А-ЯЁ]\.?'
    r')'
    r'\s*\)\s*',
    re.IGNORECASE,
)
_LEADING_PARENS_RE = re.compile(r'^\s*\(([^)]{1,120})\)\s*')
_LEADING_HTML_AUTHOR_RE = re.compile(
    r'^\s*\(\s*(?:<a\b[^>]*>\s*)?[А-ЯЁA-Z][^)]{0,80}(?:\s*</a>)?\s*\)\s*',
    re.IGNORECASE,
)
_FORCE_REMOVE_AUTHOR_RE = re.compile(
    r'\(\s*(?:<a\b[^>]*>\s*)?Иглин\s*К\.?(?:\s*</a>)?\s*\)\s*',
    re.IGNORECASE,
)
_FORCE_REMOVE_AUTHOR_SIMPLE_RE = re.compile(r'\(\s*Иглин\s*[КK]\.?\s*\)\s*', re.IGNORECASE)
_FORCE_REMOVE_KARPACHEV_RE = re.compile(
    r'\(\s*(?:<a\b[^>]*>\s*)?(?:И\.\s*)?Карпач[её]в(?:\s*</a>)?\s*\)\s*',
    re.IGNORECASE,
)
_FORCE_REMOVE_AUTHOR_NAMES_RE = re.compile(
    r'\(\s*(?:<a\b[^>]*>\s*)?'
    r'(?:'
    r'М\.\s*Рубцов[аы]|'
    r'С\.?\s*А\.?\s*Скопинцев[аы]|'
    r'А\.\s*Сражаев|'
    r'М\.?\s*В\.?\s*Кузнецов[аы]|'
    r'М\.\s*Ишимов|'
    r'А\.\s*Богданов|'
    r'А\.\s*Рогов|'
    r'Е\.\s*Джобс|'
    r'А\.\s*Калинин'
    r')'
    r'(?:\s*</a>)?\s*\)\s*',
    re.IGNORECASE,
)


def _looks_like_author_signature(text_inside_parens: str) -> bool:
    """
    Эвристика для legacy-подписей составителей:
    "И. Карпачев", "С.А. Скопинцева", "Иглин К." и т.п.
    """
    if not text_inside_parens:
        return False
    raw = str(text_inside_parens)
    # В source часто внутри скобок есть <a ...>И.О.Фамилия</a>.
    raw = re.sub(r"<[^>]+>", "", raw)
    normalized = ' '.join(raw.replace('\xa0', ' ').split())
    if not normalized:
        return False
    if not re.search(r'[А-ЯЁа-яё]', normalized):
        return False
    # Для подписи обычно характерны инициалы/точки и короткая длина.
    if ('.' in normalized and len(normalized) <= 48):
        return True
    # Фолбэк для "Фамилия И" / "Фамилия И И"
    if re.fullmatch(r'[А-ЯЁ][а-яё-]+\s+[А-ЯЁ](?:\s+[А-ЯЁ])?', normalized):
        return True
    return False


def _strip_leading_author_parenthesized(text: str) -> str:
    if not text:
        return text
    m = _LEADING_PARENS_RE.match(text)
    if not m:
        return text
    inside = m.group(1)
    if _looks_like_author_signature(inside):
        return text[m.end():]
    return text


def _split_row_cells(line: str) -> list[str]:
    line = (line or "").strip()
    if not line:
        return []
    if "\t" in line:
        cells = [c.strip() for c in line.split("\t")]
    elif "|" in line:
        cells = [c.strip() for c in line.split("|")]
    elif ";" in line:
        cells = [c.strip() for c in line.split(";")]
    else:
        cells = [c.strip() for c in re.split(r"\s{2,}", line)]
    return [c for c in cells if c]


def _looks_like_table_lines(lines: list[str]) -> tuple[bool, list[list[str]]]:
    rows: list[list[str]] = []
    for line in lines:
        cells = _split_row_cells(line)
        if len(cells) < 2:
            continue
        rows.append(cells)
    if len(rows) < 3:
        return False, []
    col_count = len(rows[0])
    if col_count < 2 or col_count > 12:
        return False, []
    if any(len(r) != col_count for r in rows):
        return False, []
    short_cell_ratio = 0.0
    total_cells = sum(len(r) for r in rows)
    if total_cells > 0:
        short_cells = sum(1 for r in rows for c in r if len(c) <= 20)
        short_cell_ratio = short_cells / total_cells
    if short_cell_ratio < 0.85:
        return False, []
    return True, rows


def convert_text_tables_to_html(html_content: Optional[str], task_number: Optional[int] = None) -> str:
    """
    Преобразует псевдотаблицы (строки с разделителями) в HTML-таблицы.
    Полезно для legacy-задач, где таблица хранится текстом.
    """
    if not html_content:
        return html_content or ""
    try:
        num = int(task_number) if task_number is not None else None
    except Exception:
        num = None
    if num not in {12, 18, 22}:
        return str(html_content)
    try:
        soup = BeautifulSoup(str(html_content), "html.parser")
        for block in soup.find_all(["p", "div"]):
            if not isinstance(block, Tag):
                continue
            if block.find(["table", "ul", "ol", "img", "iframe", "video", "pre", "code"]):
                continue
            text = block.get_text("\n", strip=True)
            if not text or "\n" not in text:
                continue
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            looks_like_table, rows = _looks_like_table_lines(lines)
            if not looks_like_table:
                continue
            table = soup.new_tag("table")
            tbody = soup.new_tag("tbody")
            table.append(tbody)
            for row in rows:
                tr = soup.new_tag("tr")
                for cell in row:
                    td = soup.new_tag("td")
                    td.string = cell
                    tr.append(td)
                tbody.append(tr)
            block.replace_with(table)
        return str(soup)
    except Exception:
        return str(html_content)


def _strip_author_signatures_from_html(decoded_html: str) -> str:
    """
    Удаляет подписи составителей в начале условий:
    (И. Карпачев), (С.А. Скопинцева), (Иглин К.) и подобные.
    """
    if not decoded_html:
        return decoded_html
    text_first = _FORCE_REMOVE_AUTHOR_RE.sub('', decoded_html)
    text_first = _FORCE_REMOVE_AUTHOR_SIMPLE_RE.sub('', text_first)
    text_first = _FORCE_REMOVE_KARPACHEV_RE.sub('', text_first)
    text_first = _FORCE_REMOVE_AUTHOR_NAMES_RE.sub('', text_first)
    text_first = _strip_leading_author_parenthesized(text_first)
    text_first = _AUTHOR_SIGNATURE_RE.sub('', text_first, count=1)
    try:
        soup = BeautifulSoup(text_first, 'html.parser')
        checked_blocks = 0
        for block in soup.find_all(['p', 'div', 'span']):
            if checked_blocks >= 6:
                break
            checked_blocks += 1
            inner = block.decode_contents() or ''
            if not inner.strip():
                continue
            stripped_inner = _FORCE_REMOVE_AUTHOR_RE.sub('', inner)
            stripped_inner = _FORCE_REMOVE_AUTHOR_SIMPLE_RE.sub('', stripped_inner)
            stripped_inner = _FORCE_REMOVE_KARPACHEV_RE.sub('', stripped_inner)
            stripped_inner = _FORCE_REMOVE_AUTHOR_NAMES_RE.sub('', stripped_inner)
            stripped_inner = _LEADING_HTML_AUTHOR_RE.sub('', stripped_inner, count=1)
            stripped_inner = _strip_leading_author_parenthesized(stripped_inner)
            stripped_inner = _AUTHOR_SIGNATURE_RE.sub('', stripped_inner, count=1)
            if stripped_inner != inner:
                block.clear()
                frag = BeautifulSoup(stripped_inner, 'html.parser')
                for child in list(frag.contents):
                    block.append(child)
        return str(soup)
    except Exception:
        return text_first


def prepare_task_content_html(raw_content: Optional[str]) -> str:
    """
    Подготавливает контент задания к рендеру:
    plain-text -> HTML с переносами, HTML -> без изменений.
    """
    text = (raw_content or '').strip()
    if not text:
        return '<div class="task-text"></div>'
    # Часть контента в legacy-хранилище бывает:
    # - HTML-escaped: &lt;table&gt;
    # - JSON-escaped: \"...\", \u003c...\u003e, \\n
    # - завёрнута в JSON-строку целиком.
    decoded = text
    # Попытка распаковать JSON-строку вида "\"<p>..</p>\""
    if len(decoded) >= 2 and decoded[0] == '"' and decoded[-1] == '"':
        try:
            loaded = json.loads(decoded)
            if isinstance(loaded, str) and loaded.strip():
                decoded = loaded.strip()
        except Exception:
            pass
    decoded = (
        decoded
        .replace("\\u003c", "<")
        .replace("\\u003e", ">")
        .replace("\\u0026", "&")
        .replace("\\/", "/")
    )
    # Важно: не ломаем LaTeX-команды вида \neg, \neq, \nu и т.п.
    # Декодируем escaped-newline только в позициях, похожих на реальные переносы.
    decoded = re.sub(r"\\r\\n(?=(?:\s*<)|\s|$)", "\n", decoded)
    decoded = re.sub(r"\\n(?=(?:\s*<)|\s|$)", "\n", decoded)
    # Исторически часть заданий хранится как HTML, но экранированный (&lt;table&gt;...).
    decoded = html_lib.unescape(decoded)
    decoded = _strip_author_signatures_from_html(decoded)
    if _HTML_TAG_PATTERN.search(decoded):
        return decoded
    return normalize_task_plain_text_to_html(decoded)


def _normalize_attachment_entry(item) -> Optional[dict]:
    if not item:
        return None
    if isinstance(item, str):
        item = {"url": item}
    if not isinstance(item, dict):
        return None

    path = str(item.get("path") or "").strip()
    raw_url = str(item.get("url") or item.get("href") or "").strip()
    name = str(item.get("name") or item.get("filename") or "").strip()

    if path:
        path = path.replace("\\", "/")
        fallback_name = path.split("/")[-1].split("?")[0]
        if not name:
            name = fallback_name or "file"
        download_url = path + (f"?download_name={name}" if name else "")
        return {
            "name": name,
            "path": path,
            "url": raw_url or path,
            "download_url": download_url,
            "source_url": raw_url or path,
            "is_local": True,
        }

    if not raw_url:
        return None
    if raw_url.startswith("//"):
        raw_url = "https:" + raw_url
    elif raw_url.startswith("/"):
        raw_url = "https://kompege.ru" + raw_url

    fallback_name = raw_url.split("/")[-1].split("?")[0]
    if not name:
        name = fallback_name or "file"

    download_url = raw_url
    if raw_url.startswith("https://kompege.ru/") or raw_url.startswith("http://kompege.ru/"):
        try:
            download_url = url_for("assignments.attached_proxy") + "?url=" + quote(raw_url, safe="")
        except Exception:
            download_url = raw_url

    return {
        "name": name,
        "url": raw_url,
        "download_url": str(download_url),
        "source_url": raw_url,
        "is_local": False,
    }


def normalize_task_attachments(value) -> list[dict]:
    """
    Унифицированный список вложений для рендера в шаблонах.
    """
    if not value:
        return []
    data = value
    if isinstance(value, str):
        try:
            data = json.loads(value)
        except Exception:
            return []
    if not isinstance(data, list):
        return []

    normalized = []
    for item in data:
        entry = _normalize_attachment_entry(item)
        if entry:
            normalized.append(entry)
    return normalized


def init_jinja_filters(app):
    """Инициализация Jinja2 фильтров"""
    app.jinja_env.filters['mask_contact'] = mask_contact_if_tutor
    app.jinja_env.filters['deduplicate_formulas'] = deduplicate_formulas
    app.jinja_env.filters['task_content_absolute_urls'] = task_content_absolute_urls
    app.jinja_env.filters['normalize_task_content_urls'] = normalize_task_content_urls
    app.jinja_env.filters['strip_attachment_links'] = strip_attachment_links
    app.jinja_env.filters['sanitize_html'] = sanitize_html
    app.jinja_env.filters['prepare_task_content_html'] = prepare_task_content_html
    app.jinja_env.filters['convert_text_tables_to_html'] = convert_text_tables_to_html
    app.jinja_env.filters['normalize_task_plain_text_to_html'] = normalize_task_plain_text_to_html
    app.jinja_env.filters['normalize_task_attachments'] = normalize_task_attachments
    app.jinja_env.globals["ui_icon"] = ui_icon
    app.jinja_env.globals["ui_icon_global"] = ui_icon
