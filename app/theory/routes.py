"""
Маршруты теории по заданиям ЕГЭ: просмотр для учеников, CRUD для тьютора.
Поддержка мульти-курсовой архитектуры: номера заданий берутся из CourseTaskTemplate.
"""
import logging
import os
import re
import subprocess
import html
import mimetypes
from collections import defaultdict
from flask import render_template, request, redirect, url_for, flash, abort, jsonify, current_app, send_file
from markupsafe import Markup
from flask_login import login_required, current_user
from sqlalchemy import func
from bs4 import BeautifulSoup
from bs4.element import Tag

from app.theory import theory_bp
from app.models import (
    db,
    TheoryBlock,
    TheoryGroup,
    StudentTheoryAccess,
    Student,
    User,
    Course,
    CourseTaskTemplate,
    StudentCourseEnrollment,
    StudentTheoryState,
    TheoryFeedback,
    TheoryFeedbackHistory,
    moscow_now,
)
from app.auth.rbac_utils import has_permission

logger = logging.getLogger(__name__)


def _theory_normalize_stdin_for_run(s):
    """Each answer for input() must end with \\n so stdin.readline() does not block until timeout."""
    if s is None:
        return ''
    t = str(s).replace('\r\n', '\n')
    if not t.strip():
        return ''
    if not t.endswith('\n'):
        t += '\n'
    return t


def _theory_wrap_python_for_stdio_transcript(code: str) -> str:
    """
    Patch builtins.input so prompts, typed answers (from stdin), and the next prints
    appear as a readable console transcript (subprocess does not echo stdin to stdout).
    """
    return (
        "import sys as _th_sys, builtins as _th_builtins\n"
        "def _th_input(_th_p=''):\n"
        "    if _th_p:\n"
        "        print(_th_p, end='', flush=True)\n"
        "    _th_ln = _th_sys.stdin.readline()\n"
        "    if _th_ln == '':\n"
        "        raise EOFError('EOF when reading a line')\n"
        "    _th_ln = _th_ln.rstrip('\\r\\n')\n"
        "    print(_th_ln, flush=True)\n"
        "    return _th_ln\n"
        "_th_builtins.input = _th_input\n"
        f"exec(compile({code!r}, '<theory>', 'exec'))\n"
    )


def _strip_status_marker(content_value):
    text = (content_value or '').strip()
    if text.startswith('<!--status:published-->'):
        return text[len('<!--status:published-->'):].lstrip()
    if text.startswith('<!--status:draft-->'):
        return text[len('<!--status:draft-->'):].lstrip()
    return text


def _render_theory_content_html(content_value):
    """Render block-based theory markers to safe-ish HTML fragments."""
    text = _strip_status_marker(content_value or '').replace('\r\n', '\n')

    def _highlight_python_html(code_value):
        escaped = html.escape(code_value or '')
        escaped = re.sub(r'(\"[^\"]*\"|\'[^\']*\')', r'<span data-hl="str">\1</span>', escaped)
        escaped = re.sub(r'\b(\d+)\b', r'<span data-hl="num">\1</span>', escaped)
        escaped = re.sub(
            r'\b(for|in|if|else|elif|while|def|return|import|from|as|try|except|finally|with|class|pass|break|continue|and|or|not|True|False|None|print|range)\b',
            r'<span data-hl="kw">\1</span>',
            escaped,
        )
        return escaped

    def _format_inline_math_html(expr):
        """
        Best-effort server-side math formatting for $...$ fragments.
        Keeps display stable even if client-side KaTeX auto-render fails.
        """
        src = html.unescape((expr or '').strip())
        src = src.replace('\\cdot', '·')
        src = src.replace('\\times', '×')
        src = src.replace('\\ge', '≥')
        src = src.replace('\\le', '≤')

        out = html.escape(src)
        # x_{abc} / x_a
        out = re.sub(r'_\{([^{}]+)\}', r'<sub>\1</sub>', out)
        out = re.sub(r'_([A-Za-zА-Яа-я0-9]+)', r'<sub>\1</sub>', out)
        # x^{abc} / x^a
        out = re.sub(r'\^\{([^{}]+)\}', r'<sup>\1</sup>', out)
        out = re.sub(r'\^([A-Za-zА-Яа-я0-9]+)', r'<sup>\1</sup>', out)
        return out

    def _render_math_in_html_fragment(fragment):
        if not fragment:
            return fragment

        def _looks_like_excel_ref(expr):
            token = (expr or '').strip()
            # Examples to ignore as "not math":
            # $A1$, $A1:$F1$, $AA10$, $AA10:$BC200
            return bool(re.fullmatch(r'\$?[A-Za-z]{1,3}\$?\d+(?::\$?[A-Za-z]{1,3}\$?\d+)?', token))

        def _render_math_in_plain_text(chunk):
            # Block math first
            chunk = re.sub(
                r'\$\$([\s\S]+?)\$\$',
                lambda m: f'<div class="theory-inline-math">{_format_inline_math_html(m.group(1))}</div>',
                chunk,
            )
            # Inline math:
            # - no escaped opening dollar
            # - closing dollar must NOT be followed by word char
            #   (prevents Excel ranges like $A1:$F1 from being split as $A1:$)
            chunk = re.sub(
                r'(?<!\\)\$([^\n$][^$]*?)\$(?![A-Za-z0-9_])',
                lambda m: (
                    m.group(0)
                    if _looks_like_excel_ref(m.group(1))
                    else f'<span class="theory-inline-math">{_format_inline_math_html(m.group(1))}</span>'
                ),
                chunk,
            )
            return chunk

        # Never render math inside inline code `...`.
        parts = re.split(r'(`[^`]*`)', fragment)
        rendered = []
        for part in parts:
            if not part:
                continue
            if len(part) >= 2 and part.startswith('`') and part.endswith('`'):
                rendered.append(part)
            else:
                rendered.append(_render_math_in_plain_text(part))
        return ''.join(rendered)

    def _render_ascii_tables_to_html(src):
        """
        Convert plain-text ASCII tables to HTML tables before markdown parse.
        Supports rows like "| a | b |" and borders like "+---+---+".
        """
        if not src:
            return src

        def _is_border_line(line):
            stripped = (line or '').strip()
            if not stripped:
                return False
            return bool(re.match(r'^[\+\-\=\|\:\s]{4,}$', stripped)) and '+' in stripped

        def _is_separator_only(line):
            stripped = (line or '').strip()
            if not stripped:
                return False
            return bool(re.match(r'^[\+\-\=\|\:\s]{4,}$', stripped))

        def _is_row_line(line):
            stripped = (line or '').strip()
            if not stripped:
                return False
            if '|' not in stripped:
                return False
            if _is_separator_only(stripped):
                return False
            return True

        def _is_table_candidate_line(line):
            stripped = (line or '').strip()
            return _is_border_line(stripped) or _is_row_line(stripped)

        def _split_cells(row_line):
            parts = [p.strip() for p in row_line.strip().split('|')]
            if parts and parts[0] == '':
                parts = parts[1:]
            if parts and parts[-1] == '':
                parts = parts[:-1]
            return parts

        lines = (src or '').split('\n')
        out = []
        i = 0
        n = len(lines)
        while i < n:
            line = lines[i]
            if not _is_table_candidate_line(line):
                out.append(line)
                i += 1
                continue

            j = i
            block = []
            while j < n:
                cur = lines[j]
                if (not cur.strip()) or (not _is_table_candidate_line(cur)):
                    break
                block.append(cur)
                j += 1

            row_lines = [b for b in block if _is_row_line(b)]
            if len(row_lines) < 2:
                out.extend(block)
                i = j
                continue

            rows = [_split_cells(r) for r in row_lines]
            max_cols = max((len(r) for r in rows), default=0)
            if max_cols < 2:
                out.extend(block)
                i = j
                continue

            normalized_rows = []
            for r in rows:
                rr = list(r)
                if len(rr) < max_cols:
                    rr.extend([''] * (max_cols - len(rr)))
                normalized_rows.append(rr)

            header = normalized_rows[0]
            body = normalized_rows[1:]
            table_html = [
                '<div class="theory-table-wrap my-6 overflow-x-auto">',
                '<table class="theory-table min-w-full border-collapse text-sm">',
                '<thead><tr>',
            ]
            for cell in header:
                table_html.append(f'<th class="px-3 py-2 border border-slate-300 bg-slate-50 text-left font-extrabold text-slate-800">{html.escape(cell)}</th>')
            table_html.append('</tr></thead><tbody>')
            for row in body:
                table_html.append('<tr>')
                for cell in row:
                    table_html.append(f'<td class="px-3 py-2 border border-slate-300 align-top text-slate-700">{html.escape(cell)}</td>')
                table_html.append('</tr>')
            table_html.append('</tbody></table></div>')
            out.append(''.join(table_html))
            i = j

        return '\n'.join(out)

    def _escape_numeric_multiplication_stars(src):
        """
        Preserve multiplication signs in numeric expressions like 0*512.
        Without escaping, markdown can treat such stars as emphasis markers.
        """
        if not src:
            return src
        # 12*34 -> 12\*34
        src = re.sub(r'(?<=\d)\*(?=\d)', r'\\*', src)
        # (*) and (*?) -> (\*) and (\*?)
        src = re.sub(r'(?<=\()\*(?=\))', r'\\*', src)
        src = re.sub(r'(?<=\()\*(?=\?)', r'\\*', src)
        return src

    def _normalize_code_body_for_theory(raw):
        """Strip spacer markers leaked into legacy CODE bodies (they must stay real newlines only)."""
        s = raw or ''
        s = s.replace('__THEORY_SPACER__', '\n')
        s = re.sub(
            r'<div\b[^>]*\bclass="[^"]*theory-spacer[^"]*"[^>]*>\s*</div>',
            '\n',
            s,
            flags=re.IGNORECASE,
        )
        return s

    def _code_repl(match):
        lang = (match.group(1) or 'python').strip().lower()
        code_body = _normalize_code_body_for_theory(match.group(2) or '').strip()
        highlighted = _highlight_python_html(code_body) if lang == 'python' else html.escape(code_body)
        return (
            '<div class="theory-smart-code theory-embed-code my-8 rounded-[24px] border border-slate-200 overflow-hidden bg-white shadow-sm" '
            f'data-lang="{lang}">'
            '<div class="px-4 py-2.5 border-b border-slate-200 bg-slate-50 flex items-center justify-between">'
            '<div class="flex items-center gap-2.5">'
            '<div class="w-2.5 h-2.5 rounded-full" style="background:#F87171;border:1px solid #EF4444;"></div>'
            '<div class="w-2.5 h-2.5 rounded-full" style="background:#F59E0B;border:1px solid #D97706;"></div>'
            '<div class="w-2.5 h-2.5 rounded-full" style="background:#4ADE80;border:1px solid #22C55E;"></div>'
            f'<span class="text-[10px] font-mono font-bold text-slate-500 uppercase ml-1">{lang}</span></div>'
            '<div class="flex items-start gap-2 flex-1 justify-end min-w-0">'
            '<textarea class="theory-code-args bg-white border border-slate-300 rounded-md px-2 py-1 text-[11px] text-slate-700 font-mono min-w-[180px] max-w-[min(340px,48vw)] min-h-[2.75rem] max-h-28 resize-y leading-snug" rows="2" wrap="off" '
            'title="Одна строка — один ответ для очередного input(). Пустые строки между ответами не ставьте." '
            'placeholder="Ответ 1 для 1-го input()&#10;Ответ 2 для 2-го input()"></textarea>'
            '<button type="button" class="theory-run-btn self-center shrink-0 px-2.5 py-1 text-xs font-bold rounded-md shadow-sm focus:outline-none" style="color:#FFFFFF;background:#15803D;border:1px solid #14532D;">Run</button>'
            '</div>'
            '</div>'
            f'<textarea class="theory-code-input hidden">{html.escape(code_body)}</textarea>'
            f'<pre class="theory-code-highlight m-0 px-5 py-4 bg-white text-slate-800 text-[14px] font-mono leading-relaxed overflow-x-auto">{highlighted}</pre>'
            '<pre class="theory-code-output hidden m-0 p-4 bg-slate-50 text-slate-700 text-xs font-mono border-t border-slate-200"></pre>'
            '</div>'
        )

    def _callout_repl(match):
        ctype = (match.group(1) or 'tip').strip().lower()
        body = (match.group(2) or '').strip()
        body = re.sub(r'^(ВНИМАНИЕ|ЛАЙФХАК|ОСТОРОЖНО)\s*:\s*', '', body, flags=re.IGNORECASE)
        body = _escape_numeric_multiplication_stars(body)
        # Inline markdown parity with teacher preview (bold/italic/code),
        # but keep it safe for direct HTML rendering.
        safe_body = html.escape(body)

        # Protect inline code from bold/italic regexes so regex symbols like "*", "+", ".*"
        # are rendered literally and are not consumed as Markdown emphasis markers.
        code_placeholders = []

        def _stash_code(code_match):
            code_placeholders.append(code_match.group(1))
            return f'__THEORY_INLINE_CODE_{len(code_placeholders) - 1}__'

        safe_body = re.sub(r'`([^`]+)`', _stash_code, safe_body)
        safe_body = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', safe_body)
        safe_body = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<em>\1</em>', safe_body)

        for idx, code_text in enumerate(code_placeholders):
            code_literal = (code_text or '').replace('*', '&#42;')
            safe_body = safe_body.replace(f'__THEORY_INLINE_CODE_{idx}__', f'<code>{code_literal}</code>')

        safe_body = _render_math_in_html_fragment(safe_body)
        safe_body = safe_body.replace('\n', '<br>')
        theme = {
            'attention': {'title': 'Внимание', 'bg': '#FFF7ED', 'border': '#FED7AA', 'icon': 'ph-fill ph-warning-circle', 'icon_bg': '#FFFFFF', 'icon_color': '#EA580C'},
            'tip': {'title': 'Лайфхак', 'bg': '#ECFEFF', 'border': '#A5F3FC', 'icon': 'ph-fill ph-lightbulb', 'icon_bg': '#FFFFFF', 'icon_color': '#06B6D4'},
            'danger': {'title': 'Осторожно', 'bg': '#FEF2F2', 'border': '#FECACA', 'icon': 'ph-fill ph-shield-warning', 'icon_bg': '#FFFFFF', 'icon_color': '#DC2626'},
        }.get(ctype, {'title': 'Заметка', 'bg': '#ECFEFF', 'border': '#A5F3FC', 'icon': 'ph-fill ph-info', 'icon_bg': '#FFFFFF', 'icon_color': '#0891B2'})
        return (
            f'<div class="theory-callout theory-callout--{html.escape(ctype)} my-8 rounded-[24px] p-6 flex gap-4 shadow-sm" style="background:{theme["bg"]};border:1px solid {theme["border"]};">'
            f'<div class="w-10 h-10 shrink-0 rounded-full flex items-center justify-center shadow-sm" style="background:{theme["icon_bg"]};color:{theme["icon_color"]};border:1px solid {theme["border"]};">'
            f'<i class="{theme["icon"]} text-xl"></i></div>'
            f'<div><h4 class="font-black text-2xl leading-snug text-slate-900 mb-1">{theme["title"]}</h4>'
            f'<p class="text-sm leading-relaxed font-extrabold text-slate-800">{safe_body}</p></div>'
            '</div>'
        )

    def _practice_repl(match):
        task_id = (match.group(1) or '').strip()
        return (
            '<div class="theory-practice-block my-8 rounded-[24px] border border-slate-200 bg-white p-6 shadow-sm">'
            '<div class="text-[10px] font-extrabold uppercase tracking-widest text-slate-400 mb-2">Интерактивный блок</div>'
            f'<div class="text-2xl font-black text-slate-900 mb-3">Практика · ID: {task_id}</div>'
            '<button type="button" class="px-4 py-2.5 rounded-xl bg-slate-50 border border-slate-200 text-sm font-bold text-slate-700 hover:bg-slate-100 transition-colors">Открыть в тренажере</button>'
            '</div>'
        )

    def _preserve_blank_lines(src):
        # Convert each extra blank line into explicit spacer markers before markdown.
        return re.sub(
            r"\n{2,}",
            lambda m: "\n" + ("__THEORY_SPACER__\n" * (len(m.group(0)) - 1)),
            src,
        )

    def _normalize_markdown_lists(src):
        """
        Help Python-Markdown recognize list blocks even when author
        writes list right after plain text line without an empty line.
        """
        lines = (src or '').split('\n')
        out = []
        prev_was_list = False
        list_item_re = re.compile(r'^\s*(?:[-*+]\s+|\d+\.\s+)')
        for line in lines:
            is_list = bool(list_item_re.match(line or ''))
            if is_list and out:
                prev = out[-1]
                if prev.strip() and not prev_was_list:
                    out.append('')
            out.append(line)
            prev_was_list = is_list
        return '\n'.join(out)

    def _escape_literal_asterisks_in_quotes(src):
        """
        Keep star tokens visible in plain explanations like '"*"' / '"**"'
        instead of letting Markdown treat them as emphasis markers.
        """
        if not src:
            return src

        def _replace(match):
            token = match.group(2) or ''
            escaped_token = token.replace('*', r'\*')
            return '{}{}{}'.format(match.group(1), escaped_token, match.group(3))

        # ASCII quotes
        src = re.sub(r'(["\'])((?:\*{1,})+)(\1)', _replace, src)
        # Common Russian typography quotes
        src = re.sub(r'(«)((?:\*{1,})+)(»)', _replace, src)
        src = re.sub(r'(“)((?:\*{1,})+)(”)', _replace, src)
        return src

    _CODE_BLOCK_RE = re.compile(
        r'\[CODE\s+lang="([^"]+)"\](.*?)\[/CODE\]',
        re.DOTALL | re.IGNORECASE,
    )

    def _preserve_blank_lines_outside_code_blocks(src):
        """Do not insert __THEORY_SPACER__ inside [CODE]…[/CODE] — it would leak into the student editor."""
        parts = []
        pos = 0
        for m in _CODE_BLOCK_RE.finditer(src):
            parts.append(_preserve_blank_lines(src[pos : m.start()]))
            parts.append(m.group(0))
            pos = m.end()
        parts.append(_preserve_blank_lines(src[pos:]))
        return ''.join(parts)

    text = _normalize_markdown_lists(text)
    text = _preserve_blank_lines_outside_code_blocks(text)
    text = _render_ascii_tables_to_html(text)
    text = _escape_numeric_multiplication_stars(text)
    text = _escape_literal_asterisks_in_quotes(text)
    text = _render_math_in_html_fragment(text)
    # Convert star-list markers to dash-list markers before markdown parse
    # to reduce cases where raw "*" leaks into rendered text.
    text = re.sub(r'(?m)^\s*\*\s+', '- ', text)
    text = re.sub(r"\[CODE\s+lang=\"([^\"]+)\"\](.*?)\[/CODE\]", _code_repl, text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"\[CALLOUT\s+type=\"([^\"]+)\"\](.*?)\[/CALLOUT\]", _callout_repl, text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"\[PRACTICE_TASK\s+id=\"([^\"]+)\"\]", _practice_repl, text, flags=re.IGNORECASE)
    try:
        from markdown import markdown as _md
        text = _md(text, extensions=['extra', 'tables', 'fenced_code'])
    except Exception:
        pass
    try:
        soup = BeautifulSoup(text, 'html.parser')
        for img in soup.find_all('img'):
            if not isinstance(img, Tag):
                continue
            src = (img.get('src') or '').strip()
            if not src:
                continue
            if re.match(r'(?i)^(?:https?:)?//|^data:|^/static/|^/theory/uploads/', src):
                continue
            if not re.fullmatch(r'(?i)[\w.\-/() %]+\.(?:png|jpe?g|gif|webp|bmp|svg)(?:[?#].*)?', src):
                continue
            resolved = _resolve_theory_uploaded_asset_by_name(src)
            if not resolved:
                continue
            try:
                storage_root = current_app.config.get('THEORY_UPLOAD_ROOT')
                if storage_root and os.path.abspath(resolved).startswith(os.path.abspath(storage_root)):
                    url = url_for('theory.theory_uploaded_file', rel_path=os.path.relpath(resolved, os.path.abspath(storage_root)).replace('\\', '/'))
                else:
                    static_root = current_app.static_folder or os.path.join(current_app.root_path, 'static')
                    url = url_for('static', filename=os.path.relpath(resolved, static_root).replace('\\', '/'))
            except Exception:
                continue
            img['src'] = url
            img['loading'] = img.get('loading') or 'lazy'
            if not img.get('style'):
                img['style'] = 'max-width: min(100%, 920px); height: auto; border-radius: 16px; border: 1px solid rgba(148,163,184,.35); display:block; margin: .35rem 0;'

        for block in soup.find_all(['p', 'div']):
            if not isinstance(block, Tag):
                continue
            inner = (block.get_text(' ', strip=True) or '').strip()
            if not inner:
                continue
            if not re.fullmatch(r'(?i)[\w.\-/() ]+\.(?:png|jpe?g|gif|webp|bmp|svg)', inner):
                continue
            resolved = _resolve_theory_uploaded_asset_by_name(inner)
            if not resolved:
                continue
            try:
                storage_root = current_app.config.get('THEORY_UPLOAD_ROOT')
                if storage_root and os.path.abspath(resolved).startswith(os.path.abspath(storage_root)):
                    url = url_for('theory.theory_uploaded_file', rel_path=os.path.relpath(resolved, os.path.abspath(storage_root)).replace('\\', '/'))
                else:
                    static_root = current_app.static_folder or os.path.join(current_app.root_path, 'static')
                    url = url_for('static', filename=os.path.relpath(resolved, static_root).replace('\\', '/'))
            except Exception:
                continue
            img = soup.new_tag('img')
            img['src'] = url
            img['alt'] = os.path.basename(inner)
            img['loading'] = 'lazy'
            img['style'] = 'max-width: min(100%, 920px); height: auto; border-radius: 16px; border: 1px solid rgba(148,163,184,.35); display:block; margin: .35rem 0;'
            block.replace_with(img)
    except Exception:
        pass
    text = text.replace('<p>__THEORY_SPACER__</p>', '<div class="theory-spacer"></div>')
    text = text.replace('__THEORY_SPACER__', '<div class="theory-spacer"></div>')
    text = text.replace('<p>THEORY_SPACER</p>', '<div class="theory-spacer"></div>')
    text = text.replace('THEORY_SPACER', '<div class="theory-spacer"></div>')
    return Markup(text)


def _get_course_task_numbers(course_id):
    """
    Возвращает отсортированный список номеров заданий для курса из CourseTaskTemplate.
    """
    if course_id is None:
        return []
    templates = CourseTaskTemplate.query.filter_by(course_id=course_id).all()
    return sorted({t.task_number for t in templates})


def _extract_status(content_value):
    text = (content_value or '').strip()
    if text.startswith('<!--status:published-->'):
        return 'published'
    if text.startswith('<!--status:draft-->'):
        return 'draft'
    if text:
        return 'published'
    return 'draft'


def _with_status_prefix(content_value, status_value):
    body = (content_value or '').strip()
    if body.startswith('<!--status:published-->'):
        body = body[len('<!--status:published-->'):].lstrip()
    elif body.startswith('<!--status:draft-->'):
        body = body[len('<!--status:draft-->'):].lstrip()
    marker = '<!--status:published-->' if status_value == 'published' else '<!--status:draft-->'
    return f'{marker}\n{body}'.strip()


def _get_default_course_id():
    """Возвращает id первого активного курса (fallback при отсутствии course_id в запросе)."""
    course = Course.query.filter_by(is_active=True).order_by(Course.id).first()
    return course.id if course else None


def _get_allowed_task_numbers_for_student(student_id, course_id):
    """
    Для ученика: номера заданий, по которым разрешён просмотр теории в рамках курса.
    Если записи в StudentTheoryAccess нет — доступ разрешён.
    can_view=False — запретить.
    """
    task_numbers = [x.task_number for x in TheoryBlock.query.filter_by(course_id=course_id).order_by(TheoryBlock.position, TheoryBlock.id).all()]
    if not student_id:
        return set(task_numbers)
    rows = StudentTheoryAccess.query.filter_by(
        student_id=student_id,
        course_id=course_id,
    ).all()
    allowed = set(task_numbers)
    for r in rows:
        if not r.can_view:
            allowed.discard(r.task_number)
        else:
            allowed.add(r.task_number)
    return allowed


def _student_can_view_task_number(student_id, task_number, course_id):
    """Проверка: может ли ученик смотреть теорию по заданию task_number в рамках курса."""
    return task_number in _get_allowed_task_numbers_for_student(student_id, course_id)


def _ensure_default_group(course_id):
    group = TheoryGroup.query.filter_by(course_id=course_id, name='Общая группа').first()
    if group:
        return group
    group = TheoryGroup(
        course_id=course_id,
        name='Общая группа',
        description='Группа по умолчанию',
        position=0,
        created_by=current_user.id if current_user.is_authenticated else None,
    )
    db.session.add(group)
    db.session.flush()
    return group


def _get_course_groups_with_blocks(course_id):
    groups = TheoryGroup.query.filter_by(course_id=course_id).order_by(TheoryGroup.position, TheoryGroup.id).all()
    if not groups:
        _ensure_default_group(course_id)
        db.session.commit()
        groups = TheoryGroup.query.filter_by(course_id=course_id).order_by(TheoryGroup.position, TheoryGroup.id).all()
    blocks = TheoryBlock.query.filter_by(course_id=course_id).order_by(TheoryBlock.position, TheoryBlock.id).all()
    blocks_by_group = defaultdict(list)
    for block in blocks:
        if not block.group_id and groups:
            block.group_id = groups[0].id
        if block.group_id:
            blocks_by_group[block.group_id].append(block)
    return groups, blocks_by_group


def _build_visible_with_state(course_id):
    """Student dataset: groups + blocks + read/bookmark states."""
    groups, blocks_by_group = _get_course_groups_with_blocks(course_id)
    student = Student.query.filter_by(user_id=current_user.id).first() if current_user.is_student() else None
    allowed_numbers = None
    if student:
        allowed_numbers = _get_allowed_task_numbers_for_student(student.student_id, course_id)

    visible_groups = []
    for group in groups:
        items = []
        for block in blocks_by_group.get(group.id, []):
            if allowed_numbers is not None and block.task_number not in allowed_numbers:
                continue
            items.append(block)
        visible_groups.append({'group': group, 'blocks': items})

    state_by_number = {}
    if student:
        rows = StudentTheoryState.query.filter_by(student_id=student.student_id, course_id=course_id).all()
        for r in rows:
            state_by_number[r.task_number] = {
                'bookmarked': bool(r.is_bookmarked),
                'read': bool(r.is_read),
            }
    return visible_groups, state_by_number


# --- Просмотр для учеников (и тьюторов) ---

@theory_bp.route('/theory')
@login_required
def theory_index():
    if not has_permission(current_user, 'theory.view'):
        flash('У вас нет доступа к теории.', 'warning')
        return redirect(url_for('main.dashboard'))

    course_id = request.args.get('course_id', type=int) or _get_default_course_id()
    if course_id is None:
        flash('Нет доступных курсов.', 'warning')
        return redirect(url_for('main.dashboard'))

    visible_groups, state_by_number = _build_visible_with_state(course_id)
    return render_template('sandbox/theory.html',
                           visible_groups=visible_groups,
                           state_by_number=state_by_number,
                           course_id=course_id)


@theory_bp.route('/theory/group/<int:group_id>')
@login_required
def theory_group_view(group_id):
    if not has_permission(current_user, 'theory.view'):
        flash('У вас нет доступа к разделу «Теория».', 'warning')
        return redirect(url_for('main.dashboard'))

    course_id = request.args.get('course_id', type=int) or _get_default_course_id()
    if course_id is None:
        flash('Нет доступных курсов.', 'warning')
        return redirect(url_for('main.dashboard'))

    visible_groups, state_by_number = _build_visible_with_state(course_id)
    selected_group_pack = next((x for x in visible_groups if x['group'].id == group_id), None)
    if not selected_group_pack:
        return redirect(url_for('theory.theory_index', course_id=course_id))

    return render_template(
        'theory/theory_shell.html',
        visible_groups=visible_groups,
        selected_group=selected_group_pack['group'],
        selected_group_blocks=selected_group_pack['blocks'],
        state_by_number=state_by_number,
        course_id=course_id,
        active_page='theory',
        initial_view='topics',
    )


@theory_bp.route('/theory/<int:task_number>')
@login_required
def theory_view(task_number):
    """Совместимость со старым URL: redirect в view по block_id."""
    if not has_permission(current_user, 'theory.view'):
        flash('У вас нет доступа к разделу «Теория».', 'warning')
        return redirect(url_for('main.dashboard'))

    course_id = request.args.get('course_id', type=int) or _get_default_course_id()
    if course_id is None:
        flash('Нет доступных курсов.', 'warning')
        return redirect(url_for('main.dashboard'))

    block = TheoryBlock.query.filter(
        TheoryBlock.course_id == course_id,
        TheoryBlock.task_number == task_number,
    ).first()
    if not block:
        flash('Теория по заданию {} ещё не добавлена.'.format(task_number), 'info')
        return redirect(url_for('theory.theory_index', course_id=course_id))
    return redirect(url_for('theory.theory_view_block', block_id=block.id, course_id=course_id))


@theory_bp.route('/theory/topic/<int:block_id>')
@login_required
def theory_view_block(block_id):
    """Просмотр одного блока теории по block_id."""
    if not has_permission(current_user, 'theory.view'):
        flash('У вас нет доступа к разделу «Теория».', 'warning')
        return redirect(url_for('main.dashboard'))

    course_id = request.args.get('course_id', type=int) or _get_default_course_id()
    if course_id is None:
        flash('Нет доступных курсов.', 'warning')
        return redirect(url_for('main.dashboard'))

    block = TheoryBlock.query.filter_by(id=block_id, course_id=course_id).first_or_404()
    task_number = block.task_number

    student = None
    if current_user.is_student():
        student = Student.query.filter_by(user_id=current_user.id).first()
        if student and not _student_can_view_task_number(student.student_id, task_number, course_id):
            flash('Просмотр теории по этому разделу для вас закрыт.', 'warning')
            return redirect(url_for('theory.theory_index', course_id=course_id))

    # IMPORTANT:
    # Source of truth for student theory is TheoryBlock.content
    # created in teacher workspace. We intentionally do not inject
    # legacy /theory/n*.html here to avoid duplicated layouts/nav.
    custom_html = None

    visible_groups, state_by_number = _build_visible_with_state(course_id)
    feedback = None
    state = None
    if student:
        st_row = StudentTheoryState.query.filter_by(
            student_id=student.student_id,
            course_id=course_id,
            task_number=task_number,
        ).first()
        if st_row:
            state = {
                'bookmarked': bool(st_row.is_bookmarked),
                'read': bool(st_row.is_read),
            }
        feedback = TheoryFeedback.query.filter_by(
            student_id=student.student_id,
            course_id=course_id,
            task_number=task_number,
        ).first()

    template_ctx = dict(
        block=block,
        course_id=course_id,
        visible_groups=visible_groups,
        back_to_url=url_for('theory.theory_group_view', group_id=block.group_id, course_id=course_id) if block.group_id else url_for('theory.theory_index', course_id=course_id),
        active_page='theory',
        custom_html=custom_html,
        rendered_content_html=_render_theory_content_html(block.content or ''),
    )

    if request.args.get('fragment') == '1' and request.headers.get('HX-Request') == 'true':
        return render_template(
            'theory/_article.html',
            initial_block=block,
            initial_state=state,
            initial_feedback=feedback,
            initial_custom_html=custom_html,
            **template_ctx,
        )

    return render_template(
        'theory/theory_shell.html',
        state_by_number=state_by_number,
        initial_block=block,
        initial_state=state,
        initial_feedback=feedback,
        initial_custom_html=custom_html,
        initial_view='article',
        **template_ctx,
    )


# --- Управление для тьютора/админа ---

def _can_manage_theory():
    if not current_user.is_authenticated:
        return False
    # Creator must always have full access to theory workspace,
    # even if granular RBAC mapping is missing for this permission.
    if current_user.is_creator() or current_user.is_tutor() or current_user.is_admin():
        return True
    return bool(has_permission(current_user, 'theory.manage'))


def _resolve_theory_storage(subfolder: str):
    """
    Resolve storage folder for theory uploads.
    If THEORY_UPLOAD_ROOT is set, use persistent folder outside static.
    Otherwise fallback to static/uploads/theory_* (legacy behavior).
    """
    persistent_root = current_app.config.get('THEORY_UPLOAD_ROOT')
    if persistent_root:
        base_root = os.path.abspath(persistent_root)
        base_folder = os.path.join(base_root, subfolder)
        os.makedirs(base_folder, exist_ok=True)
        return {
            'persistent': True,
            'base_root': base_root,
            'base_folder': base_folder,
        }

    static_root = current_app.static_folder or os.path.join(current_app.root_path, 'static')
    base_folder = os.path.join(static_root, 'uploads', subfolder)
    os.makedirs(base_folder, exist_ok=True)
    return {
        'persistent': False,
        'base_root': static_root,
        'base_folder': base_folder,
    }


def _build_theory_public_url(abs_path: str, base_root: str, persistent: bool):
    rel = os.path.relpath(abs_path, base_root).replace('\\', '/')
    if persistent:
        # Served via auth-protected route from persistent volume.
        return url_for('theory.theory_uploaded_file', rel_path=rel)
    return url_for('static', filename=rel)


def _resolve_theory_uploaded_asset_by_name(file_name: str) -> str | None:
    raw_name = (file_name or '').strip().strip('"\'')
    raw_name = raw_name.split('?', 1)[0].split('#', 1)[0]
    base_name = os.path.basename(raw_name)
    if not base_name:
        return None

    roots = []
    persistent_root = current_app.config.get('THEORY_UPLOAD_ROOT')
    if persistent_root:
        roots.append(os.path.abspath(persistent_root))
    static_root = current_app.static_folder or os.path.join(current_app.root_path, 'static')
    upload_subfolders = ('theory', 'theory_files', 'theory_images')
    roots.extend([
        os.path.join(static_root, 'uploads', subfolder)
        for subfolder in upload_subfolders
    ])
    roots.extend([
        os.path.join(current_app.root_path, 'static', 'uploads', subfolder)
        for subfolder in upload_subfolders
    ])
    roots.extend([
        os.path.join(current_app.root_path, 'uploads', subfolder)
        for subfolder in upload_subfolders
    ])

    allowed_exts = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg')
    stem, ext = os.path.splitext(base_name)
    search_names = [base_name]
    if ext.lower() not in allowed_exts:
        search_names.extend([stem + candidate_ext for candidate_ext in allowed_exts])

    for root in roots:
        if not root:
            continue
        root_abs = os.path.abspath(root)
        if not os.path.isdir(root_abs):
            continue
        if raw_name and raw_name != base_name:
            candidate_path = os.path.join(root_abs, raw_name.replace('\\', '/').lstrip('/'))
            if os.path.isfile(candidate_path):
                return candidate_path
        for candidate_name in search_names:
            candidate_path = os.path.join(root_abs, candidate_name)
            if os.path.isfile(candidate_path):
                return candidate_path
        for dirpath, _dirnames, filenames in os.walk(root_abs):
            if base_name in filenames:
                return os.path.join(dirpath, base_name)
            if ext.lower() not in allowed_exts:
                for candidate_name in search_names[1:]:
                    if candidate_name in filenames:
                        return os.path.join(dirpath, candidate_name)
    return None


@theory_bp.route('/theory/manage', methods=['GET', 'POST'])
@login_required
def manage_list():
    """Рабочее пространство теории: группы, темы и редактор."""
    if not _can_manage_theory():
        flash('Недостаточно прав для управления теорией.', 'danger')
        return redirect(url_for('main.dashboard'))

    course_id = request.args.get('course_id', type=int) or _get_default_course_id()
    if course_id is None:
        flash('Нет доступных курсов. Создайте курс в настройках.', 'warning')
        return render_template(
            'theory/theory_manage_list.html',
            groups=[],
            blocks_by_group={},
            selected_group=None,
            selected_block=None,
            selected_group_id=None,
            selected_block_id=None,
            completion_percent=0,
            published_count=0,
            total_count=0,
            student_stats=[],
            comments_history=[],
            course_id=None,
            active_page='theory_manage',
        )

    groups, blocks_by_group = _get_course_groups_with_blocks(course_id)
    if not groups:
        _ensure_default_group(course_id)
        db.session.commit()
        groups, blocks_by_group = _get_course_groups_with_blocks(course_id)

    if request.method == 'POST':
        action = (request.form.get('action') or '').strip()
        legacy_task_number = request.form.get('task_number', type=int)
        if not action and legacy_task_number is not None:
            action = 'save_block'
        if not action:
            action = 'save_block'
        if action == 'create_group':
            name = (request.form.get('group_name') or '').strip()
            description = (request.form.get('group_description') or '').strip()
            if not name:
                flash('Название группы обязательно.', 'danger')
                return redirect(url_for('theory.manage_list', course_id=course_id))
            position = (db.session.query(func.coalesce(func.max(TheoryGroup.position), 0)).filter_by(course_id=course_id).scalar() or 0) + 1
            db.session.add(TheoryGroup(course_id=course_id, name=name, description=description or None, position=position, created_by=current_user.id))
            db.session.commit()
            flash('Группа создана.', 'success')
            return redirect(url_for('theory.manage_list', course_id=course_id))
        if action == 'delete_group':
            group_id = request.form.get('group_id', type=int)
            group = TheoryGroup.query.filter_by(id=group_id, course_id=course_id).first()
            if not group:
                flash('Группа не найдена.', 'danger')
                return redirect(url_for('theory.manage_list', course_id=course_id))
            fallback = TheoryGroup.query.filter(TheoryGroup.course_id == course_id, TheoryGroup.id != group.id).order_by(TheoryGroup.position, TheoryGroup.id).first()
            if fallback is None:
                fallback = TheoryGroup(course_id=course_id, name='Общая группа', description='Группа по умолчанию', position=0, created_by=current_user.id)
                db.session.add(fallback)
                db.session.flush()
            TheoryBlock.query.filter_by(course_id=course_id, group_id=group.id).update({'group_id': fallback.id})
            db.session.delete(group)
            db.session.commit()
            flash('Группа удалена.', 'success')
            return redirect(url_for('theory.manage_list', course_id=course_id, group_id=fallback.id))
        if action == 'rename_group':
            group_id = request.form.get('group_id', type=int)
            new_name = (request.form.get('group_name') or '').strip()
            new_description = (request.form.get('group_description') or '').strip()
            group = TheoryGroup.query.filter_by(id=group_id, course_id=course_id).first()
            if not group:
                flash('Группа не найдена.', 'danger')
                return redirect(url_for('theory.manage_list', course_id=course_id))
            if not new_name:
                flash('Введите название группы.', 'warning')
                return redirect(url_for('theory.manage_list', course_id=course_id, group_id=group.id))
            duplicate = TheoryGroup.query.filter(
                TheoryGroup.course_id == course_id,
                TheoryGroup.name == new_name,
                TheoryGroup.id != group.id,
            ).first()
            if duplicate:
                flash('Группа с таким названием уже существует.', 'warning')
                return redirect(url_for('theory.manage_list', course_id=course_id, group_id=group.id))
            group.name = new_name
            group.description = new_description or None
            db.session.commit()
            flash('Группа обновлена.', 'success')
            return redirect(url_for('theory.manage_list', course_id=course_id, group_id=group.id))
        if action == 'create_block':
            group_id = request.form.get('group_id', type=int)
            group = TheoryGroup.query.filter_by(id=group_id, course_id=course_id).first()
            if not group:
                flash('Выберите корректную группу.', 'danger')
                return redirect(url_for('theory.manage_list', course_id=course_id))
            next_task = (db.session.query(func.coalesce(func.max(TheoryBlock.task_number), 0)).filter_by(course_id=course_id).scalar() or 0) + 1
            next_pos = (db.session.query(func.coalesce(func.max(TheoryBlock.position), 0)).filter_by(course_id=course_id, group_id=group.id).scalar() or 0) + 1
            block = TheoryBlock(
                course_id=course_id,
                group_id=group.id,
                task_number=next_task,
                title=f'Тема {next_pos}',
                description='Краткое описание темы',
                read_minutes=5,
                content='<!--status:draft-->\n',
                position=next_pos,
                author_id=current_user.id,
            )
            db.session.add(block)
            db.session.commit()
            flash('Теоретическая карточка создана.', 'success')
            return redirect(url_for('theory.manage_list', course_id=course_id, group_id=group.id, block_id=block.id))

        block_id = request.form.get('block_id', type=int)
        task_number = request.form.get('task_number', type=int)
        title = (request.form.get('title') or '').strip()
        description = (request.form.get('description') or '').strip()
        read_minutes_raw = request.form.get('read_minutes', type=int)
        content = (request.form.get('content') or '').strip()
        status = (request.form.get('editor_status') or 'draft').strip().lower()
        group_id = request.form.get('group_id', type=int)
        if status not in ('draft', 'published'):
            status = 'draft'
        group = TheoryGroup.query.filter_by(id=group_id, course_id=course_id).first()
        if not group and groups:
            group = groups[0]
        if not group:
            flash('Выберите корректную группу.', 'danger')
            return redirect(url_for('theory.manage_list', course_id=course_id))
        block = TheoryBlock.query.filter_by(id=block_id, course_id=course_id).first() if block_id else None
        if not block and task_number is not None:
            # Защита от "перекрестного" сохранения между группами:
            # fallback по task_number допускаем только в рамках выбранной группы.
            block = TheoryBlock.query.filter_by(course_id=course_id, group_id=group.id, task_number=task_number).first()
        content_with_status = _with_status_prefix(content, status)
        if not block:
            next_task = (db.session.query(func.coalesce(func.max(TheoryBlock.task_number), 0)).filter_by(course_id=course_id).scalar() or 0) + 1
            next_pos = (db.session.query(func.coalesce(func.max(TheoryBlock.position), 0)).filter_by(course_id=course_id, group_id=group.id).scalar() or 0) + 1
            block = TheoryBlock(course_id=course_id, group_id=group.id, task_number=next_task, position=next_pos, author_id=current_user.id)
            db.session.add(block)
        elif task_number is not None:
            block.task_number = task_number

        block.group_id = group.id
        local_number = block.position or 1
        block.title = title or f'Тема {local_number}'
        block.description = description or None
        block.read_minutes = max(1, min(180, int(read_minutes_raw or block.read_minutes or 5)))
        block.content = content_with_status
        block.author_id = current_user.id

        db.session.commit()
        flash('Теория сохранена.' if status == 'draft' else 'Теория опубликована.', 'success')
        return redirect(
            url_for(
                'theory.manage_list',
                course_id=course_id,
                group_id=block.group_id,
                block_id=block.id,
            )
        )

    selected_group_id = request.args.get('group_id', type=int)
    selected_block_id = request.args.get('block_id', type=int)
    selected_task_number = request.args.get('task_number', type=int)
    selected_group = next((g for g in groups if g.id == selected_group_id), None) if selected_group_id else (groups[0] if groups else None)
    group_blocks = blocks_by_group.get(selected_group.id, []) if selected_group else []
    selected_block = None
    if selected_block_id:
        selected_block = next((b for b in group_blocks if b.id == selected_block_id), None)
    if selected_block is None and selected_task_number is not None and selected_group:
        selected_block = next((b for b in group_blocks if b.task_number == selected_task_number), None)
    if selected_block is None:
        selected_block = group_blocks[0] if group_blocks else None
    if selected_block and (selected_group is None or selected_group.id != selected_block.group_id):
        selected_group = next((g for g in groups if g.id == selected_block.group_id), selected_group)
    selected_task_number = selected_block.task_number if selected_block else None
    selected_display_number = (selected_block.position if selected_block and selected_block.position else None)
    selected_block_status = _extract_status(selected_block.content) if selected_block else 'draft'

    # Для панели преподавателя показываем карточки только выбранной группы,
    # чтобы теории не дублировались визуально между группами.
    current_group_blocks = blocks_by_group.get(selected_group.id, []) if selected_group else []
    grid_states = [
        {
            'block_id': b.id,
            'task_number': b.task_number,  # тех. номер, используется в аналитике/истории
            'display_number': (b.position or idx),  # локальная нумерация в группе
            'state': _extract_status(b.content),
        }
        for idx, b in enumerate(current_group_blocks, start=1)
    ]
    task_numbers = [b.task_number for b in current_group_blocks]
    slots = [(b.task_number, b) for b in current_group_blocks]

    total_count = sum(len(v) for v in blocks_by_group.values())
    published_count = sum(1 for items in blocks_by_group.values() for b in items if _extract_status(b.content) == 'published')
    completion_percent = int(round((published_count / total_count) * 100)) if total_count else 0

    student_stats = []
    comments_history = []
    if selected_block:
        student_states = StudentTheoryState.query.filter_by(course_id=course_id, task_number=selected_block.task_number).all()
        feedback_rows = TheoryFeedback.query.filter_by(course_id=course_id, task_number=selected_block.task_number).all()
        feedback_by_student = {r.student_id: r for r in feedback_rows}
        students = Student.query.filter(Student.student_id.in_([s.student_id for s in student_states] + [f.student_id for f in feedback_rows])).all()
        student_map = {s.student_id: s for s in students}
        involved_ids = sorted(set(list(feedback_by_student.keys()) + [s.student_id for s in student_states]))
        for sid in involved_ids:
            st_row = next((x for x in student_states if x.student_id == sid), None)
            fb = feedback_by_student.get(sid)
            student_stats.append({
                'student': student_map.get(sid),
                'is_read': bool(st_row.is_read) if st_row else False,
                'rating': fb.rating if fb else None,
                'comment': fb.comment if fb else None,
                'updated_at': (fb.updated_at if fb else (st_row.updated_at if st_row else None)),
            })
        # Show only the latest feedback snapshot per student in teacher panel.
        history_rows = TheoryFeedbackHistory.query.filter_by(
            course_id=course_id,
            task_number=selected_block.task_number,
        ).order_by(TheoryFeedbackHistory.created_at.desc()).all()
        latest_by_student = {}
        for row in history_rows:
            if row.student_id not in latest_by_student:
                latest_by_student[row.student_id] = row
        comments_history = sorted(
            latest_by_student.values(),
            key=lambda x: x.created_at or moscow_now(),
            reverse=True,
        )[:100]

    from app.models import Course as ExamCourse
    course = ExamCourse.query.get(course_id) if course_id else None

    return render_template(
        'theory/theory_manage_list.html',
        groups=groups,
        blocks_by_group=blocks_by_group,
        selected_group=selected_group,
        selected_block=selected_block,
        selected_block_status=selected_block_status,
        selected_task_number=selected_task_number,
        selected_display_number=selected_display_number,
        grid_states=grid_states,
        task_numbers=task_numbers,
        slots=slots,
        selected_group_id=(selected_group.id if selected_group else None),
        selected_block_id=(selected_block.id if selected_block else None),
        completion_percent=completion_percent,
        published_count=published_count,
        total_count=total_count,
        student_stats=student_stats,
        comments_history=comments_history,
        course_id=course_id,
        course=course,
        active_page='theory_manage',
    )


@theory_bp.route('/theory/upload-image', methods=['POST'])
@login_required
def upload_image():
    """Загрузка изображения для вставки в блок теории. Возвращает URL для вставки в Markdown."""
    if not _can_manage_theory():
        return jsonify({'success': False, 'error': 'Нет прав'}), 403

    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'success': False, 'error': 'Файл не выбран'}), 400

    try:
        from app.uploads.service import save_uploaded_file
        storage = _resolve_theory_storage('theory')
        upload_folder = os.path.join(storage['base_folder'], str(current_user.id))
        orig, abs_path, _size = save_uploaded_file(
            file=file,
            base_folder=upload_folder,
            allowed_exts={'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'},
            max_bytes=15 * 1024 * 1024,
        )
        url = _build_theory_public_url(abs_path, storage['base_root'], storage['persistent'])
        return jsonify({'success': True, 'url': url})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.exception('Theory image upload failed')
        return jsonify({'success': False, 'error': 'Ошибка загрузки'}), 500


@theory_bp.route('/theory/upload-pdf', methods=['POST'])
@login_required
def upload_pdf():
    """Загрузка PDF для вставки в блок теории. Возвращает URL для вставки в Markdown/HTML."""
    if not _can_manage_theory():
        return jsonify({'success': False, 'error': 'Нет прав'}), 403

    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'success': False, 'error': 'Файл не выбран'}), 400

    try:
        from app.uploads.service import save_uploaded_file
        storage = _resolve_theory_storage('theory_pdfs')
        upload_folder = os.path.join(storage['base_folder'], str(current_user.id))
        orig, abs_path, _size = save_uploaded_file(
            file=file,
            base_folder=upload_folder,
            allowed_exts={'pdf'},
            max_bytes=30 * 1024 * 1024,
        )
        url = _build_theory_public_url(abs_path, storage['base_root'], storage['persistent'])
        return jsonify({'success': True, 'url': url, 'name': orig})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception:
        logger.exception('Theory PDF upload failed')
        return jsonify({'success': False, 'error': 'Ошибка загрузки PDF'}), 500


@theory_bp.route('/theory/upload-file', methods=['POST'])
@login_required
def upload_file():
    """Загрузка вложений для теории (документы/архивы/таблицы и т.п.)."""
    if not _can_manage_theory():
        return jsonify({'success': False, 'error': 'Нет прав'}), 403

    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'success': False, 'error': 'Файл не выбран'}), 400

    try:
        from app.uploads.service import save_uploaded_file
        storage = _resolve_theory_storage('theory_files')
        upload_folder = os.path.join(storage['base_folder'], str(current_user.id))
        orig, abs_path, _size = save_uploaded_file(
            file=file,
            base_folder=upload_folder,
            allowed_exts={
                'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
                'txt', 'rtf', 'csv', 'zip', 'rar', '7z', 'odt', 'ods', 'odp',
            },
            max_bytes=40 * 1024 * 1024,
        )
        url = _build_theory_public_url(abs_path, storage['base_root'], storage['persistent'])
        return jsonify({'success': True, 'url': url, 'name': orig})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception:
        logger.exception('Theory file upload failed')
        return jsonify({'success': False, 'error': 'Ошибка загрузки файла'}), 500


@theory_bp.route('/theory/uploads/<path:rel_path>', methods=['GET'])
@login_required
def theory_uploaded_file(rel_path):
    """
    Serve theory uploads from persistent storage root.
    Access is allowed for users who can view or manage theory.
    """
    if not (has_permission(current_user, 'theory.view') or _can_manage_theory()):
        abort(403)

    persistent_root = current_app.config.get('THEORY_UPLOAD_ROOT')
    if not persistent_root:
        abort(404)

    safe_rel = (rel_path or '').replace('\\', '/').lstrip('/')
    abs_root = os.path.abspath(persistent_root)
    abs_path = os.path.abspath(os.path.join(abs_root, safe_rel))
    if not abs_path.startswith(abs_root):
        abort(404)
    if not os.path.isfile(abs_path):
        abort(404)

    guessed_mime, _ = mimetypes.guess_type(abs_path)
    return send_file(abs_path, mimetype=(guessed_mime or 'application/octet-stream'), as_attachment=False)


@theory_bp.route('/theory/manage/new', methods=['GET', 'POST'])
@login_required
def manage_new():
    """Создание нового блока теории (выбор номера задания)."""
    if not _can_manage_theory():
        flash('Недостаточно прав.', 'danger')
        return redirect(url_for('main.dashboard'))

    course_id = request.args.get('course_id', type=int) or request.form.get('course_id', type=int) or _get_default_course_id()
    if course_id is None:
        flash('Нет доступных курсов. Создайте курс в настройках.', 'danger')
        return redirect(url_for('theory.manage_list'))

    task_numbers = [x.task_number for x in TheoryBlock.query.filter_by(course_id=course_id).all()]
    existing_blocks = TheoryBlock.query.filter(
        (TheoryBlock.course_id == course_id) | (TheoryBlock.course_id.is_(None))
    ).all()
    existing_numbers = {b.task_number for b in existing_blocks}
    free_numbers = [n for n in task_numbers if n not in existing_numbers]

    if request.method == 'POST':
        logger.info('[theory/manage/new] POST: content_type=%s, form.keys=%s', request.content_type, list(request.form.keys()))
        raw_content = request.form.get('content')
        logger.info('[theory/manage/new] content: present=%s, type=%s, len=%s, preview=%s',
                    raw_content is not None, type(raw_content).__name__, len(raw_content) if raw_content else 0,
                    (raw_content[:120] + '...') if raw_content and len(raw_content) > 120 else (raw_content or ''))

        task_number = request.form.get('task_number', type=int)
        title = (request.form.get('title') or '').strip() or None
        content = (request.form.get('content') or '').strip() or None

        pdf_path = None
        pdf_file = request.files.get('pdf_file')
        if pdf_file and pdf_file.filename:
            try:
                from app.uploads.service import save_uploaded_file
                static_root = current_app.static_folder or os.path.join(current_app.root_path, 'static')
                upload_folder = os.path.join(static_root, 'uploads', 'theory_pdfs', str(current_user.id))
                _orig, abs_path, _size = save_uploaded_file(
                    file=pdf_file,
                    base_folder=upload_folder,
                    allowed_exts={'pdf'},
                    max_bytes=30 * 1024 * 1024,
                )
                rel = os.path.relpath(abs_path, static_root).replace('\\', '/')
                pdf_path = rel
            except ValueError as e:
                flash(f'Ошибка загрузки PDF: {e}', 'danger')
                return render_template(
                    'theory/theory_form.html',
                    task_number=task_number,
                    title=title,
                    content=content,
                    free_numbers=free_numbers,
                    course_id=course_id,
                    is_new=True,
                )

        if task_number is None or task_number not in task_numbers:
            flash('Выберите номер задания из списка для курса.', 'danger')
            return render_template(
                'theory/theory_form.html',
                task_number=task_number,
                title=title,
                content=content,
                free_numbers=free_numbers,
                course_id=course_id,
                is_new=True,
            )

        if TheoryBlock.query.filter_by(course_id=course_id, task_number=task_number).first():
            flash('Теория по заданию {} уже существует. Редактируйте её в списке.'.format(task_number), 'warning')
            return redirect(url_for('theory.manage_list', course_id=course_id))

        block = TheoryBlock(
            course_id=course_id,
            task_number=task_number,
            title=title or 'Задание {}'.format(task_number),
            content=content,
            pdf_path=pdf_path,
            author_id=current_user.id,
        )
        db.session.add(block)
        db.session.commit()
        logger.info('[theory/manage/new] saved block_id=%s, course_id=%s, content_len=%s', block.id, course_id, len(block.content or ''))
        flash('Блок теории по заданию {} создан.'.format(task_number), 'success')
        return redirect(url_for('theory.manage_list', course_id=course_id))

    task_number_prefill = request.args.get('task_number', type=int)
    if task_number_prefill and task_number_prefill in task_numbers and task_number_prefill in free_numbers:
        pass
    else:
        task_number_prefill = None

    return render_template(
        'theory/theory_form.html',
        task_number=task_number_prefill,
        title='',
        content='',
        free_numbers=free_numbers,
        course_id=course_id,
        is_new=True,
        active_page='theory_manage',
    )


@theory_bp.route('/theory/manage/<int:block_id>/edit', methods=['GET', 'POST'])
@login_required
def manage_edit(block_id):
    """Редактирование блока теории."""
    if not _can_manage_theory():
        flash('Недостаточно прав.', 'danger')
        return redirect(url_for('main.dashboard'))

    block = TheoryBlock.query.get_or_404(block_id)
    course_id = block.course_id or _get_default_course_id()

    if request.method == 'POST':
        logger.info('[theory/manage/edit] POST block_id=%s, content_type=%s, form.keys=%s', block_id, request.content_type, list(request.form.keys()))
        raw_content = request.form.get('content')
        logger.info('[theory/manage/edit] content: present=%s, len=%s, preview=%s',
                    raw_content is not None, len(raw_content) if raw_content else 0,
                    (raw_content[:120] + '...') if raw_content and len(raw_content) > 120 else (raw_content or ''))

        block.title = (request.form.get('title') or '').strip() or None
        block.content = (request.form.get('content') or '').strip() or None

        pdf_file = request.files.get('pdf_file')
        remove_pdf = request.form.get('remove_pdf') == 'on'
        if pdf_file and pdf_file.filename:
            try:
                from app.uploads.service import save_uploaded_file
                static_root = current_app.static_folder or os.path.join(current_app.root_path, 'static')
                upload_folder = os.path.join(static_root, 'uploads', 'theory_pdfs', str(current_user.id))
                _orig, abs_path, _size = save_uploaded_file(
                    file=pdf_file,
                    base_folder=upload_folder,
                    allowed_exts={'pdf'},
                    max_bytes=30 * 1024 * 1024,
                )
                rel = os.path.relpath(abs_path, static_root).replace('\\', '/')
                block.pdf_path = rel
            except ValueError as e:
                flash(f'Ошибка загрузки PDF: {e}', 'danger')
                return render_template(
                    'theory/theory_form.html',
                    block=block,
                    task_number=block.task_number,
                    title=block.title or '',
                    content=block.content or '',
                    free_numbers=[],
                    course_id=course_id,
                    is_new=False,
                    active_page='theory_manage',
                )
        elif remove_pdf:
            block.pdf_path = None

        db.session.commit()
        logger.info('[theory/manage/edit] saved block_id=%s, content_len=%s', block_id, len(block.content or ''))
        flash('Теория по заданию {} сохранена.'.format(block.task_number), 'success')
        return redirect(url_for('theory.manage_list', course_id=course_id))

    content_for_template = block.content or ''
    logger.info('[theory/manage/edit] GET block_id=%s, content_len=%s, preview=%s', block_id, len(content_for_template), (content_for_template[:80] + '...') if len(content_for_template) > 80 else content_for_template)
    return render_template(
        'theory/theory_form.html',
        block=block,
        task_number=block.task_number,
        title=block.title or '',
        content=content_for_template,
        free_numbers=[],
        course_id=course_id,
        is_new=False,
        active_page='theory_manage',
    )


@theory_bp.route('/theory/manage/<int:block_id>/delete', methods=['POST'])
@login_required
def manage_delete(block_id):
    """Удаление блока теории."""
    if not _can_manage_theory():
        flash('Недостаточно прав.', 'danger')
        return redirect(url_for('main.dashboard'))

    block = TheoryBlock.query.get_or_404(block_id)
    num = block.task_number
    group_id = block.group_id
    course_id = block.course_id or _get_default_course_id()
    db.session.delete(block)
    db.session.commit()
    flash('Блок теории по заданию {} удалён.'.format(num), 'success')
    return redirect(url_for('theory.manage_list', course_id=course_id, group_id=group_id))


@theory_bp.route('/theory/manage/preview', methods=['POST'])
@login_required
def theory_manage_preview():
    if not _can_manage_theory():
        return jsonify({'success': False, 'error': 'Недостаточно прав'}), 403
    payload = request.get_json(silent=True) or {}
    content = (payload.get('content') or '').strip()
    title = (payload.get('title') or 'Предпросмотр').strip()
    html = (
        f'<article class="prose-article"><h1 class="text-3xl font-black text-slate-900 mb-4">{title}</h1>'
        f'{_render_theory_content_html(content)}</article>'
    )
    return jsonify({'success': True, 'html': html})


@theory_bp.route('/theory/manage/stats', methods=['GET'])
@login_required
def theory_manage_stats():
    if not _can_manage_theory():
        return jsonify({'success': False, 'error': 'Недостаточно прав'}), 403
    course_id = request.args.get('course_id', type=int) or _get_default_course_id()
    if course_id is None:
        return jsonify({'success': False, 'error': 'Курс не найден'}), 404
    block_id = request.args.get('block_id', type=int)
    block = TheoryBlock.query.filter_by(id=block_id, course_id=course_id).first()
    if not block:
        return jsonify({'success': False, 'error': 'Тема не найдена'}), 404
    states = StudentTheoryState.query.filter_by(course_id=course_id, task_number=block.task_number).all()
    feedback_rows = TheoryFeedback.query.filter_by(course_id=course_id, task_number=block.task_number).all()
    ratings = [x.rating for x in feedback_rows if x.rating is not None]
    payload = {
        'success': True,
        'topic': {
            'id': block.id,
            'title': block.title or f'Тема {block.task_number}',
            'task_number': block.task_number,
            'read_count': sum(1 for s in states if s.is_read),
            'feedback_count': len(feedback_rows),
            'avg_rating': round(sum(ratings) / len(ratings), 2) if ratings else None,
        },
    }
    return jsonify(payload)


@theory_bp.route('/theory/api/run-code', methods=['POST'])
@login_required
def theory_api_run_code():
    if not (has_permission(current_user, 'theory.view') or _can_manage_theory()):
        return jsonify({'success': False, 'error': 'Нет доступа'}), 403
    payload = request.get_json(silent=True) or {}
    lang = (payload.get('lang') or 'python').strip().lower()
    code = (payload.get('code') or '')
    if not code.strip():
        return jsonify({'success': False, 'error': 'Пустой код'}), 400
    if lang != 'python':
        return jsonify({'success': False, 'error': 'Пока поддержан только Python'}), 400
    args = _theory_normalize_stdin_for_run(payload.get('args'))
    script = _theory_wrap_python_for_stdio_transcript(code)
    try:
        proc = subprocess.run(
            ['python', '-c', script],
            input=args,
            text=True,
            capture_output=True,
            timeout=3,
            check=False,
        )
        out = (proc.stdout or '') + (('\n' + proc.stderr) if proc.stderr else '')
        return jsonify({'success': True, 'output': out.strip() or '[пустой вывод]'})
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'Время выполнения превышено (3s)'}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@theory_bp.route('/theory/api/read', methods=['POST'])
@login_required
def theory_api_read():
    if not current_user.is_student():
        return jsonify({'success': True})
    student = Student.query.filter_by(user_id=current_user.id).first()
    if not student:
        return jsonify({'success': False, 'error': 'Учeник не найден'}), 404
    payload = request.get_json(silent=True) or {}
    try:
        task_number = int(payload.get('task_number'))
    except Exception:
        task_number = None
    course_id = payload.get('course_id')
    if not task_number:
        return jsonify({'success': False, 'error': 'task_number required'}), 400
    row = StudentTheoryState.query.filter_by(student_id=student.student_id, course_id=course_id, task_number=task_number).first()
    if not row:
        row = StudentTheoryState(student_id=student.student_id, course_id=course_id, task_number=task_number)
        db.session.add(row)
    row.is_read = True
    row.last_opened_at = moscow_now()
    db.session.commit()
    return jsonify({'success': True})


@theory_bp.route('/theory/api/bookmark', methods=['POST'])
@login_required
def theory_api_bookmark():
    if not current_user.is_student():
        return jsonify({'success': False, 'error': 'Только для учеников'}), 403
    student = Student.query.filter_by(user_id=current_user.id).first()
    if not student:
        return jsonify({'success': False, 'error': 'Учeник не найден'}), 404
    payload = request.get_json(silent=True) or {}
    try:
        task_number = int(payload.get('task_number'))
    except Exception:
        task_number = None
    course_id = payload.get('course_id')
    value = bool(payload.get('value'))
    if not task_number:
        return jsonify({'success': False, 'error': 'task_number required'}), 400
    row = StudentTheoryState.query.filter_by(student_id=student.student_id, course_id=course_id, task_number=task_number).first()
    if not row:
        row = StudentTheoryState(student_id=student.student_id, course_id=course_id, task_number=task_number)
        db.session.add(row)
    row.is_bookmarked = value
    db.session.commit()
    return jsonify({'success': True, 'bookmarked': row.is_bookmarked})


@theory_bp.route('/theory/api/feedback', methods=['POST'])
@login_required
def theory_api_feedback():
    if not current_user.is_student():
        return jsonify({'success': False, 'error': 'Только для учеников'}), 403
    student = Student.query.filter_by(user_id=current_user.id).first()
    if not student:
        return jsonify({'success': False, 'error': 'Учeник не найден'}), 404
    payload = request.get_json(silent=True) or {}
    try:
        task_number = int(payload.get('task_number'))
    except Exception:
        task_number = None
    course_id = payload.get('course_id')
    rating = payload.get('rating')
    comment = (payload.get('comment') or '').strip()
    if not task_number:
        return jsonify({'success': False, 'error': 'task_number required'}), 400
    row = TheoryFeedback.query.filter_by(student_id=student.student_id, course_id=course_id, task_number=task_number).first()
    if not row:
        row = TheoryFeedback(student_id=student.student_id, user_id=current_user.id, course_id=course_id, task_number=task_number)
        db.session.add(row)
    try:
        row.rating = int(rating) if rating is not None else None
    except Exception:
        row.rating = None
    row.comment = comment or None
    # Upsert latest feedback snapshot per student/topic instead of creating duplicates.
    history_row = TheoryFeedbackHistory.query.filter_by(
        student_id=student.student_id,
        course_id=course_id,
        task_number=task_number,
    ).order_by(TheoryFeedbackHistory.id.desc()).first()
    if not history_row:
        history_row = TheoryFeedbackHistory(
            student_id=student.student_id,
            user_id=current_user.id,
            course_id=course_id,
            task_number=task_number,
        )
        db.session.add(history_row)
    history_row.user_id = current_user.id
    history_row.rating = row.rating
    history_row.comment = row.comment
    history_row.created_at = moscow_now()
    db.session.commit()
    return jsonify({'success': True})


# --- Управление доступом учеников (запрет/разрешение по номерам) ---

@theory_bp.route('/theory/manage/access')
@login_required
def manage_access_index():
    """Список учеников для настройки доступа к теории по номерам."""
    if not _can_manage_theory():
        flash('Недостаточно прав.', 'danger')
        return redirect(url_for('main.dashboard'))

    course_id = request.args.get('course_id', type=int) or _get_default_course_id()
    if course_id is None:
        flash('Нет доступных курсов.', 'warning')
        return redirect(url_for('theory.manage_list'))

    from app.auth.rbac_utils import get_user_scope
    scope = get_user_scope(current_user)
    if scope.get('can_see_all'):
        students = Student.query.order_by(Student.name).all()
    else:
        sid_list = scope.get('student_ids') or []
        if not sid_list:
            students = []
        else:
            students = Student.query.filter(Student.student_id.in_(sid_list)).order_by(Student.name).all()

    return render_template(
        'theory/theory_access_list.html',
        students=students,
        course_id=course_id,
        active_page='theory_manage',
    )


@theory_bp.route('/theory/manage/access/<int:student_id>', methods=['GET', 'POST'])
@login_required
def manage_access_student(student_id):
    """Включение/выключение просмотра теории по каждому номеру задания для ученика."""
    if not _can_manage_theory():
        flash('Недостаточно прав.', 'danger')
        return redirect(url_for('main.dashboard'))

    course_id = request.args.get('course_id', type=int) or request.form.get('course_id', type=int) or _get_default_course_id()
    if course_id is None:
        flash('Нет доступных курсов.', 'danger')
        return redirect(url_for('theory.manage_list'))

    from app.auth.rbac_utils import get_user_scope
    student = Student.query.get_or_404(student_id)
    scope = get_user_scope(current_user)
    if not scope.get('can_see_all'):
        sid_list = scope.get('student_ids') or []
        if student.student_id not in sid_list:
            flash('Нет доступа к этому ученику.', 'danger')
            return redirect(url_for('theory.manage_access_index', course_id=course_id))

    task_numbers = _get_course_task_numbers(course_id)
    # Текущие правила: task_number -> can_view (для данного курса)
    access_list = StudentTheoryAccess.query.filter_by(
        student_id=student_id,
        course_id=course_id,
    ).all()
    access_by_number = {a.task_number: a.can_view for a in access_list}

    if request.method == 'POST':
        # Чекбокс "разрешён" = on. Снят = запретить. Храним только запреты; при разрешении запись удаляем.
        for num in task_numbers:
            key = 'allow_{}'.format(num)
            can_view = request.form.get(key) == 'on'
            existing = StudentTheoryAccess.query.filter_by(
                student_id=student_id,
                course_id=course_id,
                task_number=num,
            ).first()
            if can_view:
                if existing:
                    db.session.delete(existing)
            else:
                if existing:
                    existing.can_view = False
                    existing.updated_at = moscow_now()
                else:
                    db.session.add(StudentTheoryAccess(
                        student_id=student_id,
                        course_id=course_id,
                        task_number=num,
                        can_view=False,
                    ))
        db.session.commit()
        flash('Доступ к теории для {} сохранён.'.format(student.name or 'ученика'), 'success')
        return redirect(url_for('theory.manage_access_student', student_id=student_id, course_id=course_id))

    return render_template(
        'theory/theory_access_student.html',
        student=student,
        task_numbers=task_numbers,
        access_by_number=access_by_number,
        course_id=course_id,
        active_page='theory_manage',
    )


@theory_bp.route('/theory/course-map')
@login_required
def theory_course_map():
    if not _can_manage_theory():
        abort(403)
    course_id = request.args.get('course_id', type=int) or _get_default_course_id()
    
    from core.db_models import CourseTimelineBlock
    blocks = CourseTimelineBlock.query.filter_by(course_id=course_id).order_by(CourseTimelineBlock.lesson_number.asc()).all()
    
    return render_template('sandbox/course_map.html', blocks=blocks, course_id=course_id)

@theory_bp.route('/theory/api/upload-map-archive', methods=['POST'])
@login_required
def upload_map_archive():
    if not _can_manage_theory():
        return jsonify({'success': False, 'error': 'Нет прав'}), 403
        
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'Нет файла'}), 400
        
    file = request.files['file']
    if not file.filename.endswith('.zip'):
        return jsonify({'success': False, 'error': 'Нужен ZIP-архив'}), 400
        
    course_id = request.form.get('course_id', type=int) or _get_default_course_id()
    
    from core.db_models import CourseTimelineBlock
    
    storage_info = _resolve_theory_storage('pdfs')
    upload_folder = storage_info['base_folder']
    
    import zipfile
    import re
    import io
    from uuid import uuid4
    from pypdf import PdfReader
    
    processed_count = 0
    files_to_save = []
    
    try:
        with zipfile.ZipFile(file, 'r', metadata_encoding='cp866') as z:
            for info in z.infolist():
                if info.filename.endswith('.pdf'):
                    pdf_data = z.read(info)
                    safe_name = f"timeline_{course_id}_{uuid4().hex[:8]}.pdf"
                    save_path = os.path.join(upload_folder, safe_name)
                    
                    pdf_db_url = _build_theory_public_url(save_path, storage_info['base_root'], storage_info['persistent'])
                    if not pdf_db_url:
                        # fallback if persistent is false
                        rel_path = os.path.relpath(save_path, current_app.root_path).replace('\\', '/')
                        pdf_db_url = f"/{rel_path}"
                    
                    # Извлекаем текст из PDF в памяти, не сохраняя на диск, чтобы не триггерить рестарт Flask
                    reader = PdfReader(io.BytesIO(pdf_data))
                    text = ''
                    for page in reader.pages:
                        extracted = page.extract_text()
                        if extracted:
                            text += extracted + '\n'
                            
                    # Ищем уроки по паттерну "Урок X. Название"
                    lessons = re.findall(r'Урок\.?\s*(\d+)\.\s*(.*?)(?=\nУрок|\Z)', text, re.DOTALL)
                    
                    if not lessons:
                        # Fallback: парсим из имени файла
                        filename = info.filename
                        match = re.search(r'(?:№|Блок|Урок)\.?\s*(\d+)[\.\s-]+(.*?)\.pdf$', filename, re.IGNORECASE)
                        if match:
                            lessons = [(match.group(1), match.group(2).strip())]
                            
                    parsed_lessons = []
                    for num, title in lessons:
                        lines = title.split('\n')
                        parsed_lessons.append({
                            'num': int(num),
                            'title': lines[0].strip(),
                            'content': '\n'.join(lines[1:]).strip()
                        })
                        
                    # Распределяем общее описание с конца (если оно относится к блоку уроков)
                    for i in range(len(parsed_lessons) - 2, -1, -1):
                        if not parsed_lessons[i]['content'] and parsed_lessons[i+1]['content']:
                            parsed_lessons[i]['content'] = parsed_lessons[i+1]['content']
                            
                    for pl in parsed_lessons:
                        lesson_number = pl['num']
                        clean_title = pl['title']
                        lesson_content = pl['content']
                        
                        block = CourseTimelineBlock.query.filter_by(course_id=course_id, lesson_number=lesson_number).first()
                        if not block:
                            block = CourseTimelineBlock(
                                course_id=course_id,
                                lesson_number=lesson_number,
                                title=clean_title,
                                pdf_path=pdf_db_url,
                                content=lesson_content
                            )
                            db.session.add(block)
                        else:
                            block.pdf_path = pdf_db_url
                            if clean_title:
                                block.title = clean_title
                            block.content = lesson_content
                                
                        processed_count += 1
                        
                    # Откладываем сохранение файла на самый конец
                    if lessons:
                        files_to_save.append((save_path, pdf_data))
                        
        db.session.commit()
        
        # Сохраняем все файлы разом в самом конце. Это нужно, чтобы Flask auto-reloader (watchdog) 
        # не успел перезагрузить сервер до отправки ответа, обрывая соединение.
        for path, data in files_to_save:
            with open(path, 'wb') as f_out:
                f_out.write(data)
                
        return jsonify({'success': True, 'processed': processed_count})
        
    except Exception as e:
        current_app.logger.error(f"Error parsing map archive: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500