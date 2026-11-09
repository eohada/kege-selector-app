"""Safe preparation and restoration of authored mathematics for theory HTML.

The existing theory renderer performs several regex and Markdown passes. Math
is replaced with inert source tokens before those passes, then restored as text
inside application-owned spans. KaTeX renders those spans in the browser.
"""
from __future__ import annotations

import html
import re
from typing import Dict, Tuple

import bleach


_SAFE_HTML_TAGS = {
    'a', 'abbr', 'b', 'blockquote', 'br', 'caption', 'code', 'dd', 'del',
    'details', 'div', 'dl', 'dt', 'em', 'figcaption', 'figure', 'h1', 'h2',
    'h3', 'h4', 'h5', 'h6', 'hr', 'i', 'img', 'li', 'ol', 'p', 'pre', 's',
    'small', 'span', 'strong', 'sub', 'summary', 'sup', 'table', 'tbody',
    'td', 'tfoot', 'th', 'thead', 'tr', 'u', 'ul',
}

_SAFE_HTML_ATTRIBUTES = {
    'a': {'href', 'title'},
    'img': {'src', 'alt', 'title', 'width', 'height'},
    'div': {'class'},
    'span': {'class'},
    'p': {'class'},
    'figure': {'class'},
    'table': {'class'},
    'ol': {'start'},
    'li': {'value'},
    'td': {'colspan', 'rowspan', 'align'},
    'th': {'colspan', 'rowspan', 'align'},
}

_EXCEL_REFERENCE = re.compile(r'\$?[A-Za-z]{1,3}\$?\d+(?::\$?[A-Za-z]{1,3}\$?\d+)?\Z')
_CODE_MARKER = re.compile(r'\[(?:CODE_RUNNER|CODE)\b', re.IGNORECASE)


def _is_escaped(text: str, index: int) -> bool:
    backslashes = 0
    index -= 1
    while index >= 0 and text[index] == '\\':
        backslashes += 1
        index -= 1
    return backslashes % 2 == 1


def _replace_code_regions(text: str) -> tuple[str, Dict[str, str]]:
    """Hide code regions while cleaning authored HTML and extracting math."""
    replacements: Dict[str, str] = {}
    output: list[str] = []
    cursor = 0
    token_id = 0

    def stash(start: int, end: int) -> None:
        nonlocal cursor, token_id
        token = f'BSTCODETOKEN{token_id:06d}X'
        output.append(text[cursor:start])
        replacements[token] = text[start:end]
        output.append(token)
        cursor = end
        token_id += 1

    length = len(text)
    index = 0
    while index < length:
        marker_start = re.match(r'\[(CODE_RUNNER|CODE)\b', text[index:], re.IGNORECASE)
        if marker_start:
            marker_name = marker_start.group(1).upper()
            marker = f'[/{marker_name}]'
            closing = text.lower().find(marker.lower(), index)
            if closing >= 0:
                stash(index, closing + len(marker))
                index = cursor
                continue

        line_start = text.rfind('\n', 0, index) + 1 == index
        if line_start and text.startswith(('```', '~~~'), index):
            fence_char = text[index]
            fence_len = 0
            while index + fence_len < length and text[index + fence_len] == fence_char:
                fence_len += 1
            if fence_len >= 3:
                closing_re = re.compile(rf'(?m)^ {{0,3}}{re.escape(fence_char)}{{{fence_len},}}[ \t]*$')
                closing = closing_re.search(text, index + fence_len)
                if closing:
                    stash(index, closing.end())
                    index = cursor
                    continue

        if text[index] == '`':
            run_len = 1
            while index + run_len < length and text[index + run_len] == '`':
                run_len += 1
            delimiter = '`' * run_len
            closing = text.find(delimiter, index + run_len)
            if closing >= 0:
                stash(index, closing + run_len)
                index = cursor
                continue

        index += 1

    output.append(text[cursor:])
    return ''.join(output), replacements


def _protect_math_regions(text: str) -> tuple[str, Dict[str, Tuple[str, bool]]]:
    """Replace supported math delimiters with inert tokens, without parsing TeX."""
    replacements: Dict[str, Tuple[str, bool]] = {}
    output: list[str] = []
    cursor = 0
    index = 0
    token_id = 0
    token_by_expression: Dict[Tuple[str, bool], str] = {}
    length = len(text)
    delimiters = (('$$', '$$', True), (r'\[', r'\]', True), (r'\(', r'\)', False), ('$','$',False))

    while index < length:
        opening = next((item for item in delimiters if text.startswith(item[0], index)), None)
        if opening is None or _is_escaped(text, index):
            index += 1
            continue
        left, right, display = opening
        if left == '$' and (text.startswith('$$', index) or index + 1 >= length or text[index + 1].isspace()):
            index += len(left)
            continue
        content_start = index + len(left)
        closing = text.find(right, content_start)
        while closing >= 0 and _is_escaped(text, closing):
            closing = text.find(right, closing + len(right))
        if closing < 0 or (not display and '\n' in text[content_start:closing]):
            index += len(left)
            continue
        source = text[content_start:closing]
        if not source.strip():
            index = closing + len(right)
            continue
        if left == '$' and _EXCEL_REFERENCE.fullmatch(source.strip()):
            index = closing + len(right)
            continue

        expression_key = (source, display)
        token = token_by_expression.get(expression_key)
        if token is None:
            token = f'BSTMATHTOKEN{token_id:06d}X'
            token_by_expression[expression_key] = token
            replacements[token] = expression_key
            token_id += 1
        output.append(text[cursor:index])
        output.append(token)
        cursor = closing + len(right)
        index = cursor

    output.append(text[cursor:])
    return ''.join(output), replacements


def prepare_theory_source(content: str) -> tuple[str, Dict[str, Tuple[str, bool]]]:
    """Protect code/math and sanitize authored HTML before Markdown parsing.

    Application-generated interactive markup and SVG visualizations are added
    after this function, so the sanitizer cannot remove their behavior.
    """
    protected_code, code_tokens = _replace_code_regions(content or '')
    protected_math, math_tokens = _protect_math_regions(protected_code)
    sanitized = bleach.clean(
        protected_math,
        tags=_SAFE_HTML_TAGS,
        attributes=_SAFE_HTML_ATTRIBUTES,
        protocols={'http', 'https', 'mailto'},
        strip=True,
        strip_comments=True,
    )
    for token, original in code_tokens.items():
        sanitized = sanitized.replace(token, original)
    return sanitized, math_tokens


def restore_theory_math(rendered_html: str, math_tokens: Dict[str, Tuple[str, bool]]) -> str:
    """Restore math as escaped source text in renderer-owned nodes."""
    result = str(rendered_html or '')
    tokens_pattern = re.compile('|'.join(re.escape(token) for token in sorted(math_tokens, key=len, reverse=True))) if math_tokens else None
    if not tokens_pattern:
        return result

    def restore(match: re.Match[str]) -> str:
        token = match.group(0)
        source, display = math_tokens[token]
        mode = 'display' if display else 'inline'
        start = match.start()
        in_tag = result.rfind('<', 0, start) > result.rfind('>', 0, start)
        if in_tag:
            delimiters = ('$$', '$$') if display else ('$', '$')
            return html.escape(f'{delimiters[0]}{source}{delimiters[1]}', quote=True)
        replacement = (
            f'<span class="theory-math-source" data-math-mode="{mode}" '
            f'role="math" aria-label="Математическая формула">{html.escape(source)}</span>'
        )
        return replacement

    return tokens_pattern.sub(restore, result)
