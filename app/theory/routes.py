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
from flask import make_response, render_template, request, redirect, url_for, flash, abort, jsonify, current_app, send_file
from markupsafe import Markup
from flask_login import login_required, current_user
from sqlalchemy import func, or_
from bs4 import BeautifulSoup
from bs4.element import Tag

from app.theory import theory_bp
from app import csrf
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
    TheoryCheckpointAttempt,
    StudentTheoryNote,
    TheoryStudyAssignment,
    TheoryFeedback,
    TheoryFeedbackHistory,
    moscow_now,
)
from app.auth.rbac_utils import has_permission

try:
    import pygments
    from pygments.lexers import PythonLexer
    from pygments.token import Token
    _HAS_PYGMENTS = True
except ImportError:
    _HAS_PYGMENTS = False

logger = logging.getLogger(__name__)


_CHECKPOINT_RE = re.compile(r'\[CHECKPOINT\s+((?:[^"\]]|"[^"]*")+)\]', re.IGNORECASE)
_CHECKPOINT_ATTR_RE = re.compile(r'(key|question|options|answer|explanation)="((?:[^"\\]|\\.)*)"', re.IGNORECASE)
_INTERACTIVE_RE = re.compile(r'\[INTERACTIVE\s+((?:[^"\]]|"[^"]*")+)\]', re.IGNORECASE)
_INTERACTIVE_ATTR_RE = re.compile(r'(type|key|prompt|answer|options|code|expected|placeholder|rows)="((?:[^"\\]|\\.)*)"', re.IGNORECASE)


def _parse_theory_checkpoints(content_value):
    """Read author-defined micro-checkpoints from a theory article.

    Format: [CHECKPOINT key="logic-1" question="..." options="A|B|C" answer="B" explanation="..."]
    The answer stays server-side; the client receives only question and options.
    """
    checkpoints = []
    for index, match in enumerate(_CHECKPOINT_RE.finditer(_strip_status_marker(content_value or ''))):
        attrs = {name.lower(): value.strip() for name, value in _CHECKPOINT_ATTR_RE.findall(match.group(1))}
        question = attrs.get('question', '')
        options = [item.strip() for item in attrs.get('options', '').split('|') if item.strip()]
        answer = attrs.get('answer', '')
        if not question or len(options) < 2 or answer not in options:
            continue
        checkpoints.append({
            'key': attrs.get('key') or f'checkpoint-{index + 1}',
            'question': question,
            'options': options,
            'answer': answer,
            'explanation': attrs.get('explanation', ''),
        })
    # Hands-on activities use the same persistence contract as checkpoints.
    for item in _parse_theory_interactives(content_value):
        options = [x.strip() for x in item.get('options', '').split('|') if x.strip()]
        if item['type'] == 'choice' and options:
            allowed = options
        else:
            allowed = [item['answer']]
        checkpoints.append({
            'key': item['key'],
            'question': item['prompt'],
            'options': allowed,
            'answer': item['answer'],
            'explanation': 'Результат лаборатории сохранён. При ошибке повторите действие и сравните его с разбором темы.',
        })
    return checkpoints


def _parse_theory_interactives(content_value):
    """Read hands-on activities embedded in a theory block.

    Interactive activities reuse the checkpoint persistence endpoint, so every
    successful activity is visible to the same progress/feedback pipeline.
    """
    items = []
    for index, match in enumerate(_INTERACTIVE_RE.finditer(_strip_status_marker(content_value or ''))):
        attrs = {name.lower(): value.strip() for name, value in _INTERACTIVE_ATTR_RE.findall(match.group(1))}
        kind = attrs.get('type', 'input').lower()
        if kind not in {
            'input', 'choice', 'order', 'table', 'code', 'boolean', 'multi', 'match',
            'classify', 'fill', 'slider', 'hotspot', 'sequence', 'trace', 'regex',
            'binary', 'formula', 'predict', 'debug', 'explain',
        }:
            continue
        key = attrs.get('key') or f'interactive-{index + 1}'
        answer = attrs.get('answer', '')
        if not attrs.get('prompt') or not answer:
            continue
        items.append({**attrs, 'type': kind, 'key': key, 'answer': answer})
    return items


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


def _resolve_student_block_from_payload(payload):
    """Resolve a published, available block from a client action payload.

    State rows are keyed by task number for backwards compatibility, but the
    browser never gets to choose an arbitrary course/topic pair any more.
    """
    try:
        block_id = int(payload.get('block_id'))
    except (TypeError, ValueError):
        return None, 'Не передан материал.'

    block = TheoryBlock.query.get(block_id)
    if not block:
        return None, 'Материал не найден.'
    if _extract_status(block.content) != 'published':
        return None, 'Материал ещё не опубликован.'

    student = Student.query.filter_by(user_id=current_user.id).first()
    if not student:
        return None, 'Ученик не найден.'
    if not _student_can_view_task_number(student.student_id, block.task_number, block.course_id):
        return None, 'Доступ к материалу закрыт.'
    return (student, block), None


def _get_scoped_students_for_theory_manager():
    """Return Student records visible to the current manager.

    RBAC scope stores *User.id* values, while theory state and assignment
    tables reference ``Students.student_id``. Keeping this conversion in one
    place prevents tutors from silently losing access to their own students.
    The numeric fallback supports legacy rows whose student and user ids were
    historically identical.
    """
    from app.auth.rbac_utils import get_user_scope

    scope = get_user_scope(current_user)
    if scope.get('can_see_all'):
        return Student.query.order_by(Student.name).all()
    visible_user_ids = [int(value) for value in (scope.get('student_ids') or [])]
    if not visible_user_ids:
        return []
    return Student.query.filter(
        or_(Student.user_id.in_(visible_user_ids), Student.student_id.in_(visible_user_ids))
    ).order_by(Student.name).all()


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

    # Support multiple learning levels (e.g. beginner / advanced)
    level_matches = list(re.finditer(r'\[LEVEL\s+name="([^"]+)"(?:\s+label="([^"]+)")?\](.*?)\[/LEVEL\]', text, flags=re.DOTALL | re.IGNORECASE))
    if level_matches:
        rendered_levels = []
        for idx, lm in enumerate(level_matches):
            lvl_name = (lm.group(1) or 'beginner').strip().lower()
            raw_label = (lm.group(2) or ('С нуля' if lvl_name == 'beginner' else 'С опытом')).strip()
            lvl_label = re.sub(r'^[^\w\s]+', '', raw_label).strip() or raw_label
            lvl_body = lm.group(3) or ''
            lvl_html = _render_theory_content_html(lvl_body)
            is_active = (idx == 0)
            rendered_levels.append(
                f'<div class="theory-level-pane {"is-active" if is_active else "hidden"}" '
                f'data-theory-level="{html.escape(lvl_name, quote=True)}" '
                f'data-level-label="{html.escape(lvl_label, quote=True)}">\n'
                f'{lvl_html}\n'
                f'</div>'
            )
        return Markup('\n'.join(rendered_levels))

    # Старые импортёры и JSON-пакеты иногда сохраняли перевод строки как два
    # символа ``\\n``. Нормализуем только явно сериализованный текст, чтобы не
    # повреждать настоящие escape-последовательности внутри [CODE].
    parts = re.split(r'(\[CODE\s+lang="[^"]+"\][\s\S]*?\[/CODE\])', text, flags=re.IGNORECASE)
    text = ''.join(part if re.match(r'^\[CODE\s+lang=', part, re.IGNORECASE) else part.replace('\\n', '\n') for part in parts)

    def _highlight_python_html(code_value):
        if not code_value:
            return ''
        if _HAS_PYGMENTS:
            try:
                tokens = pygments.lex(code_value, PythonLexer())
                out = []
                for ttype, val in tokens:
                    escaped_val = html.escape(val, quote=False)
                    if ttype in Token.Keyword:
                        out.append(f'<span data-hl="kw">{escaped_val}</span>')
                    elif ttype in Token.Name.Builtin or ttype in Token.Name.Function:
                        out.append(f'<span data-hl="fn">{escaped_val}</span>')
                    elif ttype in Token.Literal.String:
                        out.append(f'<span data-hl="str">{escaped_val}</span>')
                    elif ttype in Token.Literal.Number:
                        out.append(f'<span data-hl="num">{escaped_val}</span>')
                    elif ttype in Token.Comment:
                        out.append(f'<span data-hl="comment">{escaped_val}</span>')
                    elif ttype in Token.Operator:
                        out.append(f'<span data-hl="op">{escaped_val}</span>')
                    elif ttype in Token.Punctuation:
                        out.append(f'<span data-hl="punct">{escaped_val}</span>')
                    else:
                        out.append(escaped_val)
                return ''.join(out).rstrip('\n')
            except Exception:
                pass
        return html.escape(code_value)

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
            # Interactive declarations may contain pipe-separated options or
            # answers (for example ``options="A|B"``).  They are controls,
            # not author-written ASCII tables, and must reach the interactive
            # renderer unchanged.
            if stripped.upper().startswith(('[INTERACTIVE ', '[CHECKPOINT ')):
                return False
            if '|' not in stripped:
                return False
            if _is_separator_only(stripped):
                return False
            return True

        def _is_table_candidate_line(line):
            stripped = (line or '').strip()
            return _is_border_line(stripped) or _is_row_line(stripped) or _is_separator_only(stripped)

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

            if any(re.match(r'^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$', b) for b in block):
                out.extend(block)
                i = j
                continue

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
        
        lines = code_body.split('\n')
        line_numbers_html = ''.join(f'<div class="leading-6 h-6">{i+1}</div>' for i in range(len(lines)))
        
        is_parity = "n % 2 == 0" in code_body
        code_title = "Пример: проверка чётности числа" if is_parity else ("Пример кода" if lang == 'python' else f"Код ({lang})")
        
        py_icon = '''<svg class="w-4 h-4 shrink-0" viewBox="0 0 24 24" fill="none"><path d="M11.9 1.5c-3 0-5.4.6-5.4 2.8v2.3h5.6v.8H3.8C1.6 7.4 0 9.8 0 12.8c0 3.1 1.7 5.1 4.1 5.3v-2.5c0-1.6 1.4-2.8 3-2.8h5.3c1.7 0 3-1.3 3-3V4.3c0-2.3-2.4-2.8-3.5-2.8zm-2.4 1.7c.6 0 1.1.5 1.1 1.1s-.5 1.1-1.1 1.1c-.6 0-1.1-.5-1.1-1.1s.5-1.1 1.1-1.1z" fill="#387EB8"/><path d="M12.1 22.5c3 0 5.4-.6 5.4-2.8v-2.3h-5.6v-.8h8.3c2.2 0 3.8-2.4 3.8-5.4 0-3.1-1.7-5.1-4.1-5.3v2.5c0 1.6-1.4 2.8-3 2.8h-5.3c-1.7 0-3 1.3-3 3v5.5c0 2.3 2.4 2.8 3.5 2.8zm2.4-1.7c-.6 0-1.1-.5-1.1-1.1s.5-1.1 1.1-1.1c.6 0 1.1.5 1.1 1.1s-.5 1.1-1.1 1.1z" fill="#FFE052"/></svg>'''
        
        result_box = ''
        if is_parity:
            result_box = '''
            <div class="theory-result-box bg-[#ECFDF5] border-t border-emerald-100 p-3.5 sm:p-4 rounded-b-2xl flex flex-wrap items-center justify-between gap-3">
              <div class="flex items-center gap-3">
                <span class="inline-flex items-center gap-1.5 text-xs font-black text-emerald-800"><i class="ph-fill ph-play-circle text-base text-emerald-600"></i>Результат работы</span>
                <span class="inline-flex items-center gap-1 rounded-lg border border-emerald-200 bg-white px-2.5 py-1 text-xs font-bold text-slate-700 shadow-sm"><span class="text-slate-400 font-medium">Ввод:</span> 4</span>
                <span class="text-xs font-black text-slate-800"><span class="text-slate-500 font-semibold">Вывод:</span> Чётное</span>
              </div>
              <span class="inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-100/70 px-2.5 py-0.5 text-[11px] font-black text-emerald-700"><i class="ph-bold ph-check text-xs"></i>Пример выполнен</span>
            </div>
            '''
        
        return (
            f'<div class="theory-smart-code theory-embed-code my-5 rounded-2xl border border-slate-200 overflow-hidden bg-white shadow-sm" data-lang="{lang}">'
            f'<div class="px-4 py-2.5 border-b border-slate-200 bg-[#F8FAFC] flex items-center justify-between">'
            f'<div class="flex items-center gap-2 text-xs font-bold text-slate-700">{py_icon}<span>{code_title}</span></div>'
            f'<button type="button" class="theory-copy-btn inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1 text-xs font-bold text-slate-600 shadow-sm hover:bg-slate-50 transition cursor-pointer" onclick="theoryCopyCode(this)">'
            f'<i class="ph-bold ph-copy"></i><span>Скопировать</span></button>'
            f'</div>'
            f'<textarea class="theory-code-raw hidden">{html.escape(code_body)}</textarea>'
            f'<div class="flex p-4 bg-white text-xs sm:text-sm font-mono leading-6 overflow-x-auto">'
            f'<div class="select-none pr-3 text-right text-slate-400 border-r border-slate-200 mr-3 leading-6 shrink-0">{line_numbers_html}</div>'
            f'<pre class="theory-code-highlight m-0 p-0 text-slate-800 leading-6 font-mono overflow-x-auto flex-1">{highlighted}</pre>'
            f'</div>'
            f'{result_box}'
            f'</div>'
        )

    custom_blocks = []

    def _stash_custom_block(html_content):
        idx = len(custom_blocks)
        custom_blocks.append(html_content)
        return f"\n\n<!--THEORY_CUSTOM_BLOCK_{idx}-->\n\n"

    def _format_inline_text(txt):
        txt = (txt or '').replace(r'\*', '*')
        safe = html.escape(txt)
        code_placeholders = []

        def _stash_code(code_match):
            code_placeholders.append(code_match.group(1))
            return f'__THEORY_INLINE_CODE_{len(code_placeholders) - 1}__'

        safe = re.sub(r'`([^`]+)`', _stash_code, safe)
        safe = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', safe)
        safe = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<em>\1</em>', safe)

        for idx, code_text in enumerate(code_placeholders):
            code_literal = (code_text or '').replace('*', '&#42;')
            safe = safe.replace(
                f'__THEORY_INLINE_CODE_{idx}__',
                f'<code class="rounded bg-indigo-100/70 px-1.5 py-0.5 font-mono text-xs font-bold text-indigo-800">{code_literal}</code>'
            )

        safe = _render_math_in_html_fragment(safe)
        safe = re.sub(r'\s+([.,;:!?])', r'\1', safe)
        return safe

    def _format_callout_body(body):
        body = (body or '').replace('__THEORY_SPACER__', '\n').replace('THEORY_SPACER', '\n').strip()
        body = body.replace(r'\*', '*')

        lines = [line.strip() for line in body.split('\n') if line.strip()]
        is_numbered_steps = len(lines) >= 2 and all(re.match(r'^\d+\.\s+', line) for line in lines)
        if is_numbered_steps:
            step_items = []
            for line in lines:
                m = re.match(r'^(\d+)\.\s+(.*)$', line)
                if m:
                    num, txt = m.group(1), m.group(2)
                    step_items.append(
                        f'<div class="flex items-start gap-3 my-2">'
                        f'<span class="w-6 h-6 rounded-lg bg-indigo-100 text-indigo-700 font-black text-xs flex items-center justify-center shrink-0 mt-0.5 shadow-sm">{num}</span>'
                        f'<div class="text-xs sm:text-sm text-slate-700 leading-relaxed font-medium flex-1">{_format_inline_text(txt)}</div>'
                        f'</div>'
                    )
            return f'<div class="theory-steps space-y-2 my-2">{"".join(step_items)}</div>'

        rendered_lines = [_format_inline_text(line) for line in lines]
        return '<br>'.join(rendered_lines)

    def _remember_repl(match):
        body = match.group(1).strip()
        safe_body = _format_callout_body(body)
        html_card = (
            f'<div class="theory-callout-remember my-5 rounded-2xl border-2 border-indigo-200 bg-indigo-50/70 p-4 sm:p-5 shadow-sm flex items-start gap-3.5">'
            f'<div class="w-9 h-9 shrink-0 rounded-xl bg-indigo-600 text-white flex items-center justify-center shadow-sm mt-0.5">'
            f'<i class="ph-fill ph-target text-lg"></i></div>'
            f'<div class="flex-1">'
            f'<div class="text-xs font-black uppercase tracking-wider text-indigo-700 mb-0.5">Запомни</div>'
            f'<div class="text-xs sm:text-sm font-bold text-slate-900 leading-snug">{safe_body}</div>'
            f'</div>'
            f'</div>'
        )
        return _stash_custom_block(html_card)

    def _important_repl(match):
        title = (match.group(1) or 'Важно для экзамена').strip()
        body = match.group(2).strip()
        safe_body = _format_callout_body(body)
        html_card = (
            f'<div class="theory-callout-important my-6 rounded-2xl border-2 border-amber-300 bg-amber-50/80 p-4 sm:p-5 shadow-sm flex items-start gap-3.5">'
            f'<div class="w-9 h-9 shrink-0 rounded-xl bg-amber-500 text-white flex items-center justify-center shadow-sm mt-0.5">'
            f'<i class="ph-fill ph-warning text-lg"></i></div>'
            f'<div class="flex-1 min-w-0">'
            f'<div class="text-xs font-black uppercase tracking-wider text-amber-800 mb-1">{html.escape(title)}</div>'
            f'<div class="text-xs sm:text-sm text-slate-800 leading-relaxed font-medium">{safe_body}</div>'
            f'</div>'
            f'</div>'
        )
        return _stash_custom_block(html_card)

    def _note_repl(match):
        title = (match.group(1) or 'Заметка').strip()
        body = match.group(2).strip()
        safe_body = _format_callout_body(body)
        html_card = (
            f'<div class="theory-callout-note my-6 rounded-2xl border-2 border-indigo-200 bg-indigo-50/70 p-4 sm:p-5 shadow-sm flex items-start gap-3.5">'
            f'<div class="w-9 h-9 shrink-0 rounded-xl bg-indigo-600 text-white flex items-center justify-center shadow-sm mt-0.5">'
            f'<i class="ph-fill ph-note-pencil text-lg"></i></div>'
            f'<div class="flex-1 min-w-0">'
            f'<div class="text-xs font-black uppercase tracking-wider text-indigo-700 mb-1">{html.escape(title)}</div>'
            f'<div class="text-xs sm:text-sm text-slate-800 leading-relaxed font-medium">{safe_body}</div>'
            f'</div>'
            f'</div>'
        )
        return _stash_custom_block(html_card)

    def _warning_repl(match):
        title = (match.group(1) or 'Осторожно, частая ошибка!').strip()
        body = match.group(2).strip()
        safe_body = _format_callout_body(body)
        html_card = (
            f'<div class="theory-callout-warning my-6 rounded-2xl border-2 border-rose-200 bg-rose-50/70 p-4 sm:p-5 shadow-sm flex items-start gap-3.5">'
            f'<div class="w-9 h-9 shrink-0 rounded-xl bg-rose-500 text-white flex items-center justify-center shadow-sm mt-0.5">'
            f'<i class="ph-fill ph-shield-warning text-lg"></i></div>'
            f'<div class="flex-1 min-w-0">'
            f'<div class="text-xs font-black uppercase tracking-wider text-rose-800 mb-1">{html.escape(title)}</div>'
            f'<div class="text-xs sm:text-sm text-slate-800 leading-relaxed font-medium">{safe_body}</div>'
            f'</div>'
            f'</div>'
        )
        return _stash_custom_block(html_card)

    def _tip_repl(match):
        title = (match.group(1) or 'Лайфхак').strip()
        body = match.group(2).strip()
        safe_body = _format_callout_body(body)
        html_card = (
            f'<div class="theory-callout-tip my-6 rounded-2xl border-2 border-emerald-200 bg-emerald-50/70 p-4 sm:p-5 shadow-sm flex items-start gap-3.5">'
            f'<div class="w-9 h-9 shrink-0 rounded-xl bg-emerald-600 text-white flex items-center justify-center shadow-sm mt-0.5">'
            f'<i class="ph-fill ph-lightbulb text-lg"></i></div>'
            f'<div class="flex-1 min-w-0">'
            f'<div class="text-xs font-black uppercase tracking-wider text-emerald-800 mb-1">{html.escape(title)}</div>'
            f'<div class="text-xs sm:text-sm text-slate-800 leading-relaxed font-medium">{safe_body}</div>'
            f'</div>'
            f'</div>'
        )
        return _stash_custom_block(html_card)

    def _info_repl(match):
        title = match.group(1) or 'Обратите внимание'
        body = match.group(2).strip()
        safe_body = _format_callout_body(body)
        html_card = (
            f'<div class="theory-callout-info my-5 rounded-2xl border-2 border-sky-200 bg-sky-50/70 p-4 sm:p-5 shadow-sm flex items-start gap-3.5">'
            f'<div class="w-9 h-9 shrink-0 rounded-xl bg-sky-500 text-white flex items-center justify-center shadow-sm mt-0.5">'
            f'<i class="ph-fill ph-info text-lg"></i></div>'
            f'<div class="flex-1">'
            f'<div class="text-xs font-black uppercase tracking-wider text-sky-700 mb-0.5">{html.escape(title)}</div>'
            f'<div class="text-xs sm:text-sm text-slate-800 leading-relaxed font-medium">{safe_body}</div>'
            f'</div>'
            f'</div>'
        )
        return _stash_custom_block(html_card)

    def _try_repl(match):
        title = match.group(1) or 'Попробуйте мысленно'
        body = match.group(2).strip()
        safe_body = _format_callout_body(body)
        html_card = (
            f'<div class="theory-callout-try my-5 rounded-2xl border-2 border-purple-200 bg-purple-50/70 p-4 sm:p-5 shadow-sm flex items-start gap-3.5">'
            f'<div class="w-9 h-9 shrink-0 rounded-xl bg-purple-600 text-white flex items-center justify-center shadow-sm mt-0.5">'
            f'<i class="ph-fill ph-brain text-lg"></i></div>'
            f'<div class="flex-1">'
            f'<div class="text-xs font-black uppercase tracking-wider text-purple-700 mb-0.5">{html.escape(title)}</div>'
            f'<div class="text-xs sm:text-sm text-slate-800 leading-relaxed font-medium">{safe_body}</div>'
            f'</div>'
            f'</div>'
        )
        return _stash_custom_block(html_card)

    def _how_it_works_repl(match):
        speech = match.group(1) or 'Сначала понять — потом решать!'
        body = match.group(2).strip()
        safe_body = _format_callout_body(body)
        html_card = (
            f'<div class="theory-how-it-works my-6 rounded-2xl border-2 border-indigo-200 bg-gradient-to-br from-indigo-50/80 via-white to-indigo-50/40 p-5 sm:p-6 shadow-sm relative overflow-hidden">'
            f'<div class="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pb-4 border-b border-indigo-100">'
            f'  <div class="flex items-center gap-3">'
            f'    <div class="w-9 h-9 rounded-xl bg-indigo-600 text-white flex items-center justify-center shadow-sm">'
            f'      <i class="ph-fill ph-sparkle text-lg"></i>'
            f'    </div>'
            f'    <div>'
            f'      <div class="text-[11px] font-black uppercase tracking-wider text-indigo-600">Разбор принципа</div>'
            f'      <div class="text-base sm:text-lg font-black text-slate-900">Как это работает?</div>'
            f'    </div>'
            f'  </div>'
            f'  <div class="flex items-center gap-3 self-end sm:self-auto">'
            f'    <div class="relative bg-white border border-indigo-200 rounded-xl px-3 py-1.5 text-xs font-bold text-indigo-900 shadow-sm">'
            f'      <span>{html.escape(speech)}</span>'
            f'      <div class="absolute -bottom-1.5 right-6 w-3 h-3 bg-white border-b border-r border-indigo-200 rotate-45"></div>'
            f'    </div>'
            f'    <img src="/static/images/theory/ghost_study.png" alt="Boo" class="w-12 h-12 object-contain drop-shadow-sm">'
            f'  </div>'
            f'</div>'
            f'<div class="mt-4 text-xs sm:text-sm text-slate-700 leading-relaxed space-y-2">{safe_body}</div>'
            f'</div>'
        )
        return _stash_custom_block(html_card)

    def _data_types_repl(match):
        body = match.group(1) or ''
        type_matches = list(re.finditer(r'\[TYPE\s+([^\]]+)\]', body, flags=re.IGNORECASE))
        cards_html = []
        for tm in type_matches:
            attrs = {
                m.group(1).lower(): m.group(2).replace('\\"', '"')
                for m in re.finditer(r'(\w+)="((?:[^"\\]|\\.)*)"', tm.group(1))
            }
            name = attrs.get('name', 'type')
            label = attrs.get('label', '')
            desc = attrs.get('desc', '').replace('\\*', '*')
            code = attrs.get('code', '').replace('\\n', '\n').replace('\\*', '*')

            badge_classes = {
                'int': 'bg-indigo-100 text-indigo-800 border-indigo-200',
                'float': 'bg-emerald-100 text-emerald-800 border-emerald-200',
                'str': 'bg-amber-100 text-amber-800 border-amber-200',
                'bool': 'bg-rose-100 text-rose-800 border-rose-200',
                'list': 'bg-purple-100 text-purple-800 border-purple-200',
                'dict': 'bg-sky-100 text-sky-800 border-sky-200',
                'set': 'bg-teal-100 text-teal-800 border-teal-200',
            }.get(name.lower(), 'bg-slate-100 text-slate-800 border-slate-200')

            highlighted_code = _highlight_python_html(code)
            cards_html.append(
                f'<div class="rounded-xl border border-slate-200/90 bg-[#F8FAFC] p-4 flex flex-col justify-between hover:border-indigo-200 hover:bg-indigo-50/20 transition">'
                f'  <div>'
                f'    <div class="flex items-center justify-between mb-2.5">'
                f'      <span class="px-2.5 py-1 rounded-lg text-xs font-black font-mono border {badge_classes}">{html.escape(name)}</span>'
                f'      <span class="text-xs font-bold text-slate-500">{html.escape(label)}</span>'
                f'    </div>'
                f'    <p class="text-xs sm:text-sm text-slate-600 leading-relaxed mb-3">{html.escape(desc)}</p>'
                f'  </div>'
                f'  <div class="bg-white border border-slate-200/70 rounded-lg p-2.5 font-mono text-xs text-slate-800 whitespace-pre-wrap leading-relaxed">{highlighted_code}</div>'
                f'</div>'
            )
        grid_html = (
            f'<div class="grid grid-cols-1 sm:grid-cols-2 gap-4 my-6">'
            f'{"".join(cards_html)}'
            f'</div>'
        )
        return _stash_custom_block(grid_html)

    def _operations_repl(match):
        body = match.group(1) or ''
        op_matches = list(re.finditer(r'\[OP\s+([^\]]+)\]', body, flags=re.IGNORECASE))
        rows_html = []
        for om in op_matches:
            attrs = {
                m.group(1).lower(): m.group(2).replace('\\"', '"')
                for m in re.finditer(r'(\w+)="((?:[^"\\]|\\.)*)"', om.group(1))
            }
            sign = attrs.get('sign', '').replace('\\*', '*')
            name = attrs.get('name', '').replace('\\*', '*')
            example = attrs.get('example', '').replace('\\*', '*')
            result = attrs.get('result', '').replace('\\*', '*')
            note = attrs.get('note', '').replace('\\*', '*')

            rows_html.append(
                f'<tr class="hover:bg-slate-50/80 transition border-b border-slate-100">'
                f'  <td class="py-3 px-4 font-mono font-black text-sm text-indigo-700 whitespace-nowrap">'
                f'    <span class="px-2.5 py-1 rounded-lg bg-indigo-50 border border-indigo-200/80">{html.escape(sign)}</span>'
                f'  </td>'
                f'  <td class="py-3 px-4 font-bold text-slate-900 text-xs sm:text-sm">{html.escape(name)}</td>'
                f'  <td class="py-3 px-4 font-mono text-xs sm:text-sm text-slate-700 whitespace-nowrap">{html.escape(example)}</td>'
                f'  <td class="py-3 px-4 whitespace-nowrap">'
                f'    <span class="px-2 py-0.5 rounded-md bg-emerald-50 text-emerald-800 font-mono font-bold text-xs border border-emerald-200">{html.escape(result)}</span>'
                f'  </td>'
                f'  <td class="py-3 px-4 text-xs text-slate-500 font-medium leading-snug">{html.escape(note)}</td>'
                f'</tr>'
            )

        table_html = (
            f'<div class="theory-operators-wrap my-5 overflow-x-auto">'
            f'<table class="theory-table w-full text-left border-collapse text-xs sm:text-sm rounded-xl overflow-hidden border border-slate-200/80">'
            f'  <thead>'
            f'    <tr class="border-b border-slate-200 bg-[#F8FAFC] text-slate-600 font-black uppercase text-[11px] tracking-wider">'
            f'      <th class="py-3 px-4">Знак</th>'
            f'      <th class="py-3 px-4">Операция</th>'
            f'      <th class="py-3 px-4">Пример</th>'
            f'      <th class="py-3 px-4">Результат</th>'
            f'      <th class="py-3 px-4">Особенность для ЕГЭ</th>'
            f'    </tr>'
            f'  </thead>'
            f'  <tbody class="divide-y divide-slate-100 font-medium text-slate-700 bg-white">'
            f'    {"".join(rows_html)}'
            f'  </tbody>'
            f'</table>'
            f'</div>'
        )
        return _stash_custom_block(table_html)

    def _code_runner_repl(match):
        raw_attrs = match.group(1) or ''
        code_raw = _normalize_code_body_for_theory(match.group(2) or '').strip()
        attrs = {
            m.group(1).lower(): m.group(2).replace('\\"', '"')
            for m in re.finditer(r'(\w+)="((?:[^"\\]|\\.)*)"', raw_attrs)
        }
        title = attrs.get('title', 'Пример кода')
        input_val = attrs.get('input', '')
        output_val = attrs.get('output', '')
        lang = attrs.get('lang', 'python').lower()

        lines = code_raw.split('\n')
        line_numbers_html = ''.join(f'<div class="leading-6 h-6">{i+1}</div>' for i in range(len(lines)))
        highlighted_code = _highlight_python_html(code_raw) if lang == 'python' else html.escape(code_raw)

        input_badge = ''
        stdin_block = ''
        if input_val:
            input_badge = (
                f'<span class="inline-flex items-center gap-1 rounded-lg border border-emerald-200 bg-white px-2.5 py-1 text-xs font-bold text-slate-700 shadow-sm">'
                f'<span class="text-slate-400 font-medium">Ввод:</span> {html.escape(input_val)}</span>'
            )
            stdin_block = (
                f'<div class="theory-stdin-wrap px-4 py-2 bg-slate-50 border-b border-slate-100 flex items-center gap-2">'
                f'<span class="text-xs font-bold text-slate-500 shrink-0">Ввод (stdin):</span>'
                f'<input type="text" class="theory-stdin-input w-full bg-white border border-slate-200 rounded-lg px-2.5 py-1 text-xs font-mono text-slate-800 outline-none focus:border-indigo-400" value="{html.escape(input_val)}">'
                f'</div>'
            )

        output_badge = ''
        if output_val:
            output_badge = (
                f'<span class="text-xs font-black text-slate-800">'
                f'<span class="text-slate-500 font-semibold">Вывод:</span> {html.escape(output_val)}</span>'
            )

        runner_html = (
            f'<div class="theory-code-runner my-6 rounded-2xl border border-slate-200 overflow-hidden bg-white shadow-sm" data-lang="{lang}">'
            f'<div class="px-4 py-3 border-b border-slate-200 bg-[#F8FAFC] flex flex-wrap items-center justify-between gap-3">'
            f'  <div class="flex items-center gap-3">'
            f'    <div class="flex items-center gap-1.5">'
            f'      <span class="w-3 h-3 rounded-full bg-rose-400 inline-block"></span>'
            f'      <span class="w-3 h-3 rounded-full bg-amber-400 inline-block"></span>'
            f'      <span class="w-3 h-3 rounded-full bg-emerald-400 inline-block"></span>'
            f'    </div>'
            f'    <div class="flex items-center gap-2 text-xs font-bold text-slate-700">'
            f'      <span class="font-mono text-[11px] px-2 py-0.5 rounded bg-slate-200 text-slate-700 font-bold">Python</span>'
            f'      <span>{html.escape(title)}</span>'
            f'    </div>'
            f'  </div>'
            f'  <div class="flex items-center gap-2">'
            f'    <button type="button" class="theory-copy-btn inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs font-bold text-slate-600 shadow-sm hover:bg-slate-50 transition cursor-pointer" onclick="theoryCopyCode(this)">'
            f'      <i class="ph-bold ph-copy text-sm"></i><span>Скопировать</span>'
            f'    </button>'
            f'    <button type="button" class="theory-run-btn inline-flex items-center gap-1.5 rounded-xl border-b-2 border-emerald-700 bg-emerald-600 hover:bg-emerald-500 text-white px-3.5 py-1.5 text-xs font-black shadow-sm transition active:translate-y-0.5 cursor-pointer" onclick="theoryRunCode(this)">'
            f'      <i class="ph-bold ph-play text-sm"></i><span>Запустить</span>'
            f'    </button>'
            f'  </div>'
            f'</div>'
            f'<div class="theory-editor-wrap flex bg-white text-xs sm:text-sm font-mono border-b border-slate-100">'
            f'  <div class="theory-line-numbers select-none py-4 pr-3 pl-4 text-right text-slate-300 border-r border-slate-100 leading-6 shrink-0">{line_numbers_html}</div>'
            f'  <div class="relative flex-1 min-w-0">'
            f'    <pre data-code-highlight class="theory-editor-pre pointer-events-none m-0 p-4 font-mono text-xs sm:text-sm leading-6 overflow-x-auto whitespace-pre font-medium text-slate-800" aria-hidden="true"><code class="language-python">{highlighted_code}</code></pre>'
            f'    <textarea class="theory-code-input absolute inset-0 w-full h-full p-4 bg-transparent font-mono text-xs sm:text-sm leading-6 outline-none resize-none overflow-x-auto whitespace-pre text-transparent caret-slate-800 selection:bg-indigo-500/20" rows="{len(lines)}" spellcheck="false">{html.escape(code_raw)}</textarea>'
            f'  </div>'
            f'</div>'
            f'{stdin_block}'
            f'<div class="theory-result-box bg-[#ECFDF5] border-t border-emerald-100 p-3.5 sm:p-4 rounded-b-2xl flex flex-wrap items-center justify-between gap-3">'
            f'  <div class="flex items-center flex-wrap gap-2.5">'
            f'    <span class="inline-flex items-center gap-1.5 text-xs font-black text-emerald-800">'
            f'      <i class="ph-fill ph-play-circle text-base text-emerald-600"></i>Результат работы'
            f'    </span>'
            f'    {input_badge}'
            f'    {output_badge}'
            f'  </div>'
            f'  <span class="theory-status-badge inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-100/70 px-2.5 py-0.5 text-[11px] font-black text-emerald-700">'
            f'    <i class="ph-bold ph-check text-xs"></i>Пример готов'
            f'  </span>'
            f'  <div class="theory-live-output hidden w-full mt-2 rounded-xl bg-[#F8FAFC] border-2 border-slate-200 text-slate-800 font-mono text-xs p-3.5 whitespace-pre-wrap leading-relaxed shadow-inner"></div>'
            f'</div>'
            f'</div>'
        )
        return _stash_custom_block(runner_html)

    def _callout_repl(match):
        ctype = (match.group(1) or 'tip').strip().lower()
        body = (match.group(2) or '').strip()
        body = re.sub(r'^(ВНИМАНИЕ|ЛАЙФХАК|ОСТОРОЖНО)\s*:\s*', '', body, flags=re.IGNORECASE)
        safe_body = _format_callout_body(body)

        theme = {
            'attention': {'bg': '#FFFBEB', 'border': '#FDE68A', 'icon': 'ph-fill ph-warning-circle', 'icon_bg': '#FEF3C7', 'icon_color': '#D97706'},
            'warning': {'bg': '#FFFBEB', 'border': '#FDE68A', 'icon': 'ph-fill ph-lightbulb', 'icon_bg': '#FEF3C7', 'icon_color': '#D97706'},
            'tip': {'bg': '#EEF2FF', 'border': '#C7D2FE', 'icon': 'ph-fill ph-info', 'icon_bg': '#E0E7FF', 'icon_color': '#4F46E5'},
            'info': {'bg': '#EEF2FF', 'border': '#C7D2FE', 'icon': 'ph-fill ph-info', 'icon_bg': '#E0E7FF', 'icon_color': '#4F46E5'},
            'danger': {'bg': '#FEF2F2', 'border': '#FECACA', 'icon': 'ph-fill ph-shield-warning', 'icon_bg': '#FEE2E2', 'icon_color': '#DC2626'},
        }.get(ctype, {'bg': '#EEF2FF', 'border': '#C7D2FE', 'icon': 'ph-fill ph-info', 'icon_bg': '#E0E7FF', 'icon_color': '#4F46E5'})
        return (
            f'<div class="theory-callout theory-callout--{html.escape(ctype)} my-4 rounded-2xl p-4 sm:p-5 flex items-start gap-3.5 shadow-sm" style="background:{theme["bg"]};border:1.5px solid {theme["border"]};">'
            f'<div class="w-8 h-8 shrink-0 rounded-full flex items-center justify-center mt-0.5" style="background:{theme["icon_bg"]};color:{theme["icon_color"]};">'
            f'<i class="{theme["icon"]} text-lg"></i></div>'
            f'<div class="text-xs sm:text-sm leading-relaxed text-slate-800 font-medium flex-1">{safe_body}</div>'
            '</div>'
        )

    def _practice_repl(match):
        task_id = (match.group(1) or '').strip()
        return (
            '<div class="theory-practice-block my-6 rounded-2xl border-2 border-slate-200 bg-white p-5 sm:p-6 shadow-sm">'
            '<div class="inline-flex items-center gap-1.5 px-3 py-1 rounded-xl bg-indigo-50 text-indigo-700 text-xs font-black">'
            '<i class="ph-bold ph-lightning"></i>Интерактивный блок</div>'
            f'<div class="text-lg font-black text-slate-900 mt-2 mb-3">Практика · Задание ID: {task_id}</div>'
            f'<a href="/trainer?task_id={task_id}" class="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-black no-underline shadow-sm transition">Открыть в тренажёре</a>'
            '</div>'
        )

    def _format_inline_code_markup(raw_str):
        if not raw_str:
            return ''
        escaped = html.escape(raw_str)
        if '`' in raw_str:
            return re.sub(
                r'`([^`]+)`',
                r'<code class="language-python font-mono text-xs px-1.5 py-0.5 rounded bg-slate-100 text-indigo-900 border border-slate-200 whitespace-nowrap">\1</code>',
                escaped,
            )
        return escaped

    def _interactive_repl(match):
        attrs = {name.lower(): value.strip() for name, value in _INTERACTIVE_ATTR_RE.findall(match.group(1))}
        kind = attrs.get('type', 'input').lower()
        prompt_raw = attrs.get('prompt', 'Выполните мини-задачу.')
        prompt = _format_inline_code_markup(prompt_raw)
        key = html.escape(attrs.get('key', 'interactive-1'), quote=True)
        answer = html.escape(attrs.get('answer', ''), quote=True)
        placeholder = html.escape(attrs.get('placeholder', 'Введите ответ…'), quote=True)

        type_labels = {
            'choice': ('ph-bold ph-check-square-offset', 'Практика · Выбор ответа'),
            'boolean': ('ph-bold ph-check-square-offset', 'Практика · Верно / Неверно'),
            'input': ('ph-bold ph-textbox', 'Практика · Краткий ответ'),
            'match': ('ph-bold ph-arrows-left-right', 'Практика · Сопоставление'),
            'order': ('ph-bold ph-sort-ascending', 'Практика · Упорядочивание'),
            'sequence': ('ph-bold ph-sort-ascending', 'Практика · Упорядочивание'),
            'code': ('ph-bold ph-code', 'Практика · Код'),
        }
        icon, label = type_labels.get(kind, ('ph-bold ph-lightning', 'Практическое задание'))

        base = (
            f'<div class="theory-interactive theory-interactive-card my-6 rounded-2xl border-2 border-indigo-100 bg-white p-5 sm:p-6 shadow-sm" '
            f'data-interactive-key="{key}" data-interactive-type="{html.escape(kind, quote=True)}">'
            f'<div class="inline-flex items-center gap-1.5 px-3 py-1 rounded-xl bg-indigo-50 text-indigo-700 text-xs font-black">'
            f'<i class="{icon}"></i><span>{label}</span></div>'
            f'<h3 class="mt-3 text-base sm:text-lg font-black text-slate-900 leading-snug">{prompt}</h3>'
        )

        if kind == 'choice':
            options = [x.strip() for x in attrs.get('options', '').split('|') if x.strip()]
            controls = ''.join(
                f'<button type="button" data-interactive-option="{html.escape(option, quote=True)}" '
                f'class="option-btn w-full text-left p-3.5 rounded-xl border-2 border-slate-200 bg-[#F8FAFC] hover:border-indigo-300 hover:bg-indigo-50/40 transition font-bold text-xs sm:text-sm text-slate-700 flex items-center justify-between group">'
                f'<span>{_format_inline_code_markup(option)}</span>'
                f'<span class="radio-indicator w-5 h-5 rounded-full border-2 border-slate-300 group-hover:border-indigo-400 flex items-center justify-center shrink-0"></span>'
                f'</button>'
                for option in options
            )
            controls = f'<div class="mt-4 space-y-2.5">{controls}</div>'
        elif kind == 'hotspot':
            controls = '<div class="mt-4 grid max-w-xs grid-cols-3 gap-2" role="group" aria-label="Карта выбора клетки">' + ''.join(
                f'<button type="button" data-interactive-option="{i}" aria-label="Клетка {i}" class="option-btn rounded-xl border-2 border-slate-200 bg-[#F8FAFC] p-4 text-center text-sm font-black text-slate-700 shadow-sm hover:border-indigo-400 transition">{i}</button>' for i in range(1, 10)
            ) + '</div>'
        elif kind in {'order', 'sequence'}:
            options = [x.strip() for x in attrs.get('options', '').split('|') if x.strip()]
            controls = '<div class="theory-order-options mt-4 flex flex-wrap gap-2">' + ''.join(
                f'<button type="button" data-order-value="{html.escape(option, quote=True)}" class="rounded-xl border-2 border-slate-200 bg-[#F8FAFC] hover:border-indigo-400 px-3.5 py-2 text-xs font-black text-slate-700 shadow-sm transition cursor-pointer">{html.escape(option)}</button>'
                for option in options
            ) + '</div><p class="mt-2 text-xs font-bold text-slate-400">Нажимайте элементы по порядку формирования.</p>'
        elif kind in {'table', 'trace'}:
            try:
                rows = max(1, min(8, int(attrs.get('rows', '2') or 2)))
            except ValueError:
                rows = 2
            controls = '<div class="mt-4 grid max-w-xl grid-cols-2 gap-2.5">' + ''.join(
                f'<input data-table-cell="{i}" class="rounded-xl border-2 border-slate-200 bg-[#F8FAFC] px-3.5 py-2 text-sm font-bold text-slate-800 outline-none focus:border-indigo-500 focus:bg-white" placeholder="Значение {i + 1}">' for i in range(rows)
            ) + '</div>'
        elif kind == 'boolean':
            controls = (
                '<div class="mt-4 grid max-w-xl gap-2.5 sm:grid-cols-2" role="radiogroup" aria-label="Выберите ответ" data-interactive-boolean>'
                '<button type="button" data-interactive-option="true" role="radio" aria-checked="false" '
                'class="option-btn p-3.5 rounded-xl border-2 border-slate-200 bg-[#F8FAFC] hover:border-indigo-300 hover:bg-indigo-50/40 transition font-bold text-xs sm:text-sm text-slate-700 flex items-center justify-between group">'
                '<span>Да, утверждение верно</span><span class="radio-indicator w-5 h-5 rounded-full border-2 border-slate-300 group-hover:border-indigo-400 flex items-center justify-center shrink-0"></span></button>'
                '<button type="button" data-interactive-option="false" role="radio" aria-checked="false" '
                'class="option-btn p-3.5 rounded-xl border-2 border-slate-200 bg-[#F8FAFC] hover:border-indigo-300 hover:bg-indigo-50/40 transition font-bold text-xs sm:text-sm text-slate-700 flex items-center justify-between group">'
                '<span>Нет, утверждение неверно</span><span class="radio-indicator w-5 h-5 rounded-full border-2 border-slate-300 group-hover:border-indigo-400 flex items-center justify-center shrink-0"></span></button>'
                '</div>'
            )
        elif kind in {'code', 'debug'}:
            raw_code = attrs.get('code', 'print(42)').replace('\\*', '*')
            code = html.escape(raw_code)
            highlighted_code = _highlight_python_html(raw_code)
            code_lines = raw_code.split('\n')
            line_nums = ''.join(f'<div class="leading-6 h-6">{i+1}</div>' for i in range(len(code_lines)))
            controls = (
                f'<div class="theory-interactive-editor mt-4 rounded-2xl border-2 border-slate-200 bg-white overflow-hidden shadow-sm">'
                f'  <div class="px-3.5 py-2.5 border-b border-slate-200 bg-[#F8FAFC] flex items-center justify-between text-xs font-bold text-slate-600">'
                f'    <div class="flex items-center gap-2">'
                f'      <div class="flex items-center gap-1">'
                f'        <span class="w-2.5 h-2.5 rounded-full bg-rose-400 inline-block"></span>'
                f'        <span class="w-2.5 h-2.5 rounded-full bg-amber-400 inline-block"></span>'
                f'        <span class="w-2.5 h-2.5 rounded-full bg-emerald-400 inline-block"></span>'
                f'      </div>'
                f'      <span class="font-mono text-[11px] px-2 py-0.5 rounded bg-slate-200 text-slate-700 font-black">Python</span>'
                f'    </div>'
                f'    <span class="text-slate-400 text-[11px] font-bold">Редактор решения</span>'
                f'  </div>'
                f'  <div class="theory-editor-wrap flex text-xs sm:text-sm font-mono bg-white">'
                f'    <div class="theory-line-numbers select-none py-3.5 pr-2.5 pl-3.5 text-right text-slate-300 border-r border-slate-100 leading-6 shrink-0">{line_nums}</div>'
                f'    <div class="relative flex-1 min-w-0">'
                f'      <pre data-code-highlight class="theory-editor-pre pointer-events-none m-0 p-3.5 font-mono text-xs sm:text-sm leading-6 overflow-x-auto whitespace-pre font-medium text-slate-800" aria-hidden="true"><code class="language-python">{highlighted_code}</code></pre>'
                f'      <textarea data-interactive-code class="theory-code-input absolute inset-0 w-full h-full p-3.5 bg-transparent font-mono text-xs sm:text-sm leading-6 outline-none resize-none overflow-x-auto whitespace-pre text-transparent caret-slate-800 selection:bg-indigo-500/20" rows="{len(code_lines)}" spellcheck="false">{code}</textarea>'
                f'    </div>'
                f'  </div>'
                f'</div>'
            )
        elif kind == 'slider':
            controls = '<div class="mt-4 max-w-md"><input type="range" min="0" max="100" value="0" data-interactive-slider class="w-full accent-indigo-600"><output data-slider-output class="mt-2 block text-sm font-black text-indigo-700">0</output></div>'
        elif kind == 'match':
            controls = '<div class="mt-4 grid max-w-lg gap-2.5 sm:grid-cols-2"><input data-match-left class="rounded-xl border-2 border-slate-200 bg-[#F8FAFC] px-3.5 py-2.5 text-xs sm:text-sm font-bold text-slate-800 outline-none focus:border-indigo-500 focus:bg-white transition" placeholder="Термин / объект"><input data-match-right class="rounded-xl border-2 border-slate-200 bg-[#F8FAFC] px-3.5 py-2.5 text-xs sm:text-sm font-bold text-slate-800 outline-none focus:border-indigo-500 focus:bg-white transition" placeholder="Соответствие / значение"></div>'
        elif kind in {'multi', 'classify'}:
            options = [x.strip() for x in attrs.get('options', '').split('|') if x.strip()]
            controls = '<div class="mt-4 grid gap-2.5 sm:grid-cols-2">' + ''.join(
                f'<button type="button" data-interactive-option="{html.escape(option, quote=True)}" class="option-btn rounded-xl border-2 border-slate-200 bg-[#F8FAFC] p-3.5 text-left text-xs sm:text-sm font-bold text-slate-700 hover:border-indigo-300 transition">{html.escape(option)}</button>' for option in options
            ) + '</div><p class="mt-2 text-xs font-bold text-slate-400">Можно выбрать несколько вариантов.</p>'
        else: # input, fill, formula, predict, regex, binary, explain
            controls = (
                f'<div class="mt-4 flex flex-col sm:flex-row gap-2.5 max-w-md">'
                f'<input type="text" data-interactive-input class="flex-1 rounded-xl border-2 border-slate-200 bg-[#F8FAFC] px-4 py-2.5 text-xs sm:text-sm font-bold text-slate-800 placeholder-slate-400 outline-none focus:border-indigo-500 focus:bg-white transition" placeholder="{placeholder}">'
                f'</div>'
            )

        submit_class = 'hidden' if kind in {'choice', 'boolean'} else 'flex'
        submit = (
            f'<div class="mt-4 {submit_class} items-center gap-3">'
            f'<button type="button" data-action="interactive-submit" class="px-5 py-2.5 rounded-xl border-b-[3px] border-indigo-800 bg-indigo-600 hover:bg-indigo-700 text-xs font-black text-white shadow-sm transition active:translate-y-0.5 flex items-center gap-1.5"><i class="ph-bold ph-check"></i>Проверить</button>'
            f'</div>'
        )
        return base + controls + submit + '<div data-interactive-result class="mt-3 hidden rounded-xl p-3.5 text-xs sm:text-sm font-bold"></div></div>'

    checkpoint_items = _parse_theory_checkpoints(text)
    checkpoint_by_key = {item['key']: item for item in checkpoint_items}

    def _checkpoint_repl(match):
        attrs = {name.lower(): value.strip() for name, value in _CHECKPOINT_ATTR_RE.findall(match.group(1))}
        key = attrs.get('key')
        item = checkpoint_by_key.get(key)
        if not item:
            return ''
        options_html = ''.join(
            f'<button type="button" data-action="checkpoint-choice" data-checkpoint-key="{html.escape(item["key"], quote=True)}" data-answer="{html.escape(option, quote=True)}" '
            f'class="option-btn w-full text-left p-3.5 rounded-xl border-2 border-slate-200 bg-[#F8FAFC] hover:border-indigo-300 hover:bg-indigo-50/40 transition font-bold text-xs sm:text-sm text-slate-700 flex items-center justify-between group">'
            f'<span>{_format_inline_code_markup(option)}</span>'
            f'<span class="radio-indicator w-5 h-5 rounded-full border-2 border-slate-300 group-hover:border-indigo-400 flex items-center justify-center shrink-0"></span>'
            f'</button>'
            for option in item['options']
        )
        return (
            f'<div class="theory-checkpoint theory-interactive-card my-6 rounded-2xl border-2 border-indigo-100 bg-white p-5 sm:p-6 shadow-sm" '
            f'data-checkpoint-key="{html.escape(item["key"], quote=True)}">'
            f'<div class="inline-flex items-center gap-1.5 px-3 py-1 rounded-xl bg-indigo-50 text-indigo-700 text-xs font-black">'
            f'<i class="ph-fill ph-lightning"></i><span>Быстрая проверка</span></div>'
            f'<h3 class="mt-3 text-base sm:text-lg font-black text-slate-900 leading-snug">{_format_inline_code_markup(item["question"])}</h3>'
            f'<div class="mt-4 space-y-2.5">{options_html}</div>'
            f'<div data-checkpoint-result class="hidden mt-3 p-3.5 rounded-xl text-xs sm:text-sm font-bold"></div>'
            f'</div>'
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
        # Imported lessons often flatten numbered algorithm steps into one
        # physical line (`1. ... 2. ... 3. ...`). Restore list boundaries
        # before Markdown parses the document.
        normalized = re.sub(r'(?<!\n)\s+([1-9])\.\s+', r'\n\1. ', src or '')
        lines = normalized.split('\n')
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

        # ASCII quotes (avoid escaping attribute values like sign="*")
        src = re.sub(r'(?<![=a-zA-Z0-9_-])(["\'])((?:\*{1,})+)(\1)', _replace, src)
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
    # Старые и импортированные конспекты часто содержат названия разделов
    # отдельной строкой без Markdown-маркера. Превращаем только устойчивый
    # набор учебных заголовков в полноценную иерархию, чтобы они не слипались
    # в один длинный абзац и выглядели одинаково в V2-статье.
    _plain_heading_re = re.compile(
        r'(?m)^(?P<indent>\s*)(?P<title>'
        r'Что проверяет экзамен|Теория|Практика(?: прямо в материале)?|'
        r'Универсальный алгоритм решения|Типовые ошибки и самопроверка|'
        r'Микро-проверки|Итог темы|Лаборатория темы|Проверка именно этой темы|'
        r'Прототипы ЕГЭ 2026|Пошаговый алгоритм решения|Кодовый шаблон|'
        r'Типичные ошибки и диагностика'
        r')\s*$',
    )
    text = _plain_heading_re.sub(lambda m: f"{m.group('indent')}## {m.group('title')}", text)
    text = _preserve_blank_lines_outside_code_blocks(text)
    text = _render_ascii_tables_to_html(text)
    text = _escape_numeric_multiplication_stars(text)
    text = _escape_literal_asterisks_in_quotes(text)
    text = _render_math_in_html_fragment(text)
    # Convert star-list markers to dash-list markers before markdown parse
    # to reduce cases where raw "*" leaks into rendered text.
    text = re.sub(r'(?m)^\s*\*\s+', '- ', text)
    text = re.sub(r'\[GHOST_IMAGE(?:\s+name="([^"]*)")?\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r"\[CODE\s+lang=\"([^\"]+)\"\](.*?)\[/CODE\]", _code_repl, text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"\[CALLOUT\s+type=\"([^\"]+)\"\](.*?)\[/CALLOUT\]", _callout_repl, text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"\[REMEMBER\](.*?)\[/REMEMBER\]", _remember_repl, text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"\[IMPORTANT(?:\s+title=\"([^\"]*)\")?\](.*?)\[/IMPORTANT\]", _important_repl, text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"\[NOTE(?:\s+title=\"([^\"]*)\")?\](.*?)\[/NOTE\]", _note_repl, text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"\[WARNING(?:\s+title=\"([^\"]*)\")?\](.*?)\[/WARNING\]", _warning_repl, text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"\[TIP(?:\s+title=\"([^\"]*)\")?\](.*?)\[/TIP\]", _tip_repl, text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"\[INFO(?:\s+title=\"([^\"]*)\")?\](.*?)\[/INFO\]", _info_repl, text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"\[TRY(?:\s+title=\"([^\"]*)\")?\](.*?)\[/TRY\]", _try_repl, text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"\[HOW_IT_WORKS(?:\s+speech=\"([^\"]*)\")?\](.*?)\[/HOW_IT_WORKS\]", _how_it_works_repl, text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"\[DATA_TYPES\](.*?)\[/DATA_TYPES\]", _data_types_repl, text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"\[OPERATIONS\](.*?)\[/OPERATIONS\]", _operations_repl, text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"\[CODE_RUNNER(?:\s+([^\]]+))?\](.*?)\[/CODE_RUNNER\]", _code_runner_repl, text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"\[PRACTICE_TASK\s+id=\"([^\"]+)\"\]", _practice_repl, text, flags=re.IGNORECASE)
    text = _INTERACTIVE_RE.sub(_interactive_repl, text)
    text = _CHECKPOINT_RE.sub(_checkpoint_repl, text)
    
    # Ensure Markdown tables have clean blank lines before and after them, and no __THEORY_SPACER__
    text = re.sub(r'__THEORY_SPACER__\s*(\n\s*\|)', r'\1', text)
    text = re.sub(r'(\|\s*\n)\s*__THEORY_SPACER__', r'\1', text)
    text = re.sub(r'([^\n])\n(\s*\|.+?\n\s*\|[-:\s|]+)', r'\1\n\n\2', text)
    text = re.sub(r'(\|[^\n]+)\n([^\n|])', r'\1\n\n\2', text)
    
    try:
        from markdown import markdown as _md
        text = _md(text, extensions=['extra', 'tables', 'fenced_code'])
    except Exception:
        pass
    try:
        soup = BeautifulSoup(text, 'html.parser')
        # Imported legacy notes sometimes arrive as one paragraph with
        # newline-separated section labels. Split those labels after the
        # markdown pass as well, otherwise the browser shows them as plain
        # body text even though the source contains headings.
        heading_titles = {
            'Что проверяет экзамен', 'Теория', 'Практика прямо в материале',
            'Универсальный алгоритм решения', 'Типовые ошибки и самопроверка',
            'Микро-проверки', 'Итог темы', 'Лаборатория темы',
            'Проверка именно этой темы', 'Прототипы ЕГЭ 2026',
            'Пошаговый алгоритм решения', 'Кодовый шаблон',
            'Типичные ошибки и диагностика',
        }
        for paragraph in list(soup.find_all('p')):
            lines = [line.strip() for line in paragraph.get_text('\n').splitlines() if line.strip()]
            if len(lines) >= 2 and all(line[:1].isdigit() and '.' in line[:4] for line in lines):
                ordered = soup.new_tag('ol')
                for line in lines:
                    item = soup.new_tag('li')
                    item.string = re.sub(r'^\d+\.\s+', '', line)
                    ordered.append(item)
                paragraph.replace_with(ordered)
                continue
            if len(lines) <= 1 or not any(line in heading_titles for line in lines):
                continue
            replacement = []
            for line in lines:
                if line in heading_titles:
                    replacement.append(soup.new_tag('h2'))
                    replacement[-1].string = line
                else:
                    replacement.append(soup.new_tag('p'))
                    replacement[-1].string = line
            paragraph.replace_with(*replacement)
        # A number of imported lessons contain algorithm steps in one visual
        # paragraph (`1. ... 2. ... 3. ...`) even after newline normalisation.
        # Convert that form to a real ordered list as well, so the article is
        # scannable instead of rendering a wall of inline text.
        for paragraph in list(soup.find_all('p')):
            plain = paragraph.get_text(' ', strip=True)
            items = re.findall(r'(?:^|\s)(\d+)\.\s+(.+?)(?=\s+\d+\.\s+|$)', plain)
            if len(items) < 2:
                continue
            ordered = soup.new_tag('ol')
            for _, value in items:
                item = soup.new_tag('li')
                item.string = value.strip()
                ordered.append(item)
            paragraph.replace_with(ordered)
        # Imported notes often encode a list as one paragraph with dash
        # separators (`- first; - second; - third`). Render it as a real
        # unordered list and keep any explanatory tail as its own paragraph.
        for paragraph in list(soup.find_all('p')):
            if paragraph.find_parent(class_=['theory-interactive', 'theory-code-runner', 'theory-how-it-works']):
                continue
            plain = paragraph.get_text(' ', strip=True)
            if ';' not in plain:
                continue
            markers = list(re.finditer(r'(?:^|\s)[–—]\s+', plain))
            if len(markers) < 2:
                continue
            start = markers[0].start()
            prefix = plain[:start].strip()
            chunks = re.split(r'\s+[–—-]\s+', plain[start:].lstrip('–—- '))
            chunks = [chunk.strip(' ;') for chunk in chunks if chunk.strip(' ;')]
            if len(chunks) < 2:
                continue
            # A final sentence after the last semicolon is prose, not a list
            # item. Keep it outside the list when it has an explicit cue.
            tail = None
            for index, chunk in enumerate(chunks):
                if re.match(r'^(?:Перед отправкой|Важно|Проверьте|Итог)\b', chunk, re.I):
                    tail = ' '.join(chunks[index:])
                    chunks = chunks[:index]
                    break
            unordered = soup.new_tag('ul')
            for chunk in chunks:
                item = soup.new_tag('li')
                item.string = chunk
                unordered.append(item)
            replacement = []
            if prefix:
                lead = soup.new_tag('p')
                lead.string = prefix
                replacement.append(lead)
            replacement.append(unordered)
            if tail:
                trailing = soup.new_tag('p')
                trailing.string = tail
                replacement.append(trailing)
            paragraph.replace_with(*replacement)
        # Markdown emits empty paragraphs around imported block markers. They
        # create unexplained vertical gaps and make the article feel broken;
        # remove only truly empty nodes, preserving intentional spacers.
        for paragraph in list(soup.find_all('p')):
            if not paragraph.get_text(' ', strip=True) and not paragraph.find(['img', 'br']) and not paragraph.has_attr('data-interactive-result') and not paragraph.has_attr('data-checkpoint-result'):
                paragraph.decompose()
        # V2 article не зависит от Tailwind Typography: задаём явную иерархию
        # заголовков/текста, чтобы материал читался одинаково при CDN и offline.
        for tag_name, classes in {
            'h1': 'mt-2 mb-5 text-3xl sm:text-4xl font-black tracking-tight text-slate-950',
            'h2': 'mt-8 mb-3 text-2xl sm:text-3xl font-black tracking-tight text-slate-900',
            'h3': 'mt-6 mb-2 text-xl font-black text-slate-900',
            'p': 'my-3 text-base leading-8 text-slate-700',
            'ul': 'my-4 list-disc space-y-2 pl-6 text-base leading-7 text-slate-700',
            'ol': 'my-4 list-decimal space-y-2 pl-6 text-base leading-7 text-slate-700',
            'li': 'leading-7',
        }.items():
            for node in soup.find_all(tag_name):
                existing = node.get('class', [])
                node['class'] = existing + [item for item in classes.split() if item not in existing]
        # Keep the semantic heading tags clean; the article template provides
        # the same V2 typography locally and this avoids legacy snapshots
        # treating `<h2>` with utility classes as a different element.
        for heading in soup.find_all(['h1', 'h2', 'h3']):
            heading.attrs.pop('class', None)

        # A theory block is an educational flow, not a continuous Markdown
        # page.  Group every top-level h2 with its following material so the
        # template can display distinct readable stages: explanation, method,
        # laboratory and self-check.  This is deliberately content-agnostic:
        # authors keep editing normal Markdown while the learner sees the V2
        # lesson structure automatically.
        section_kinds = {
            'Что проверяет экзамен': 'goal',
            'Теория': 'concept',
            'Универсальный алгоритм решения': 'method',
            'Пошаговый алгоритм решения': 'method',
            'Практика прямо в материале': 'practice',
            'Лаборатория темы': 'practice',
            'Проверка именно этой темы': 'practice',
            'Типовые ошибки и самопроверка': 'warning',
            'Типичные ошибки и диагностика': 'warning',
            'Итог темы': 'summary',
            'Микро-проверки': 'check',
        }
        top_level_headings = [
            heading for heading in soup.find_all('h2')
            if heading.parent is soup
        ]
        for index, heading in enumerate(top_level_headings, start=1):
            title = heading.get_text(' ', strip=True)
            section = soup.new_tag('section')
            section_kind = section_kinds.get(title, 'concept')
            section['class'] = ['theory-section', f'theory-section--{section_kind}']
            section['data-section'] = str(index)
            marker = soup.new_tag('span')
            marker['class'] = ['theory-section-marker']
            marker.string = f'{index:02d}'
            heading.insert(0, marker)
            heading.wrap(section)
            sibling = section.next_sibling
            while sibling is not None:
                following = sibling.next_sibling
                if isinstance(sibling, Tag) and sibling.name == 'h2':
                    break
                section.append(sibling.extract())
                sibling = following

            first_paragraph = section.find('p', recursive=False)
            if first_paragraph and not first_paragraph.find_parent(class_='theory-interactive'):
                first_paragraph['class'] = list(first_paragraph.get('class', [])) + ['theory-section-lead']
            for ordered in section.find_all('ol', recursive=False):
                ordered['class'] = list(ordered.get('class', [])) + ['theory-steps']
            for unordered in section.find_all('ul', recursive=False):
                unordered['class'] = list(unordered.get('class', [])) + ['theory-checklist']
        for spacer in soup.select('.theory-spacer'):
            parent = spacer.parent
            if parent and parent.name == 'strong':
                parent.unwrap()
            spacer.decompose()
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
        # Serialize all DOM-level normalization back to the fragment. Without
        # this assignment BeautifulSoup fixes (headings, lists, classes and
        # resolved images) never reach the template.
        text = str(soup)
        def _ordered_html(match):
            body = re.sub(r'<br\s*/?>', '\n', match.group('body'), flags=re.IGNORECASE)
            plain = BeautifulSoup(body, 'html.parser').get_text(' ', strip=True)
            items = re.findall(r'(?:^|\s)(\d+)\.\s+(.*?)(?=\s+\d+\.\s+|$)', plain)
            if len(items) < 2:
                return match.group(0)
            return '<ol class="my-4 list-decimal space-y-2 pl-6 text-base leading-7 text-slate-700">' + ''.join(f'<li>{html.escape(value.strip())}</li>' for _, value in items) + '</ol>'
        text = re.sub(r'<p(?P<attrs>[^>]*)>\s*(?P<body>(?:\d+\.\s+.*?(?:\n|$)){2,})\s*</p>', _ordered_html, text, flags=re.DOTALL)
    except Exception:
        pass
    # Final safety net for imported algorithms: Markdown may keep a numbered
    # sequence inside a paragraph when the source has no blank line. Convert
    # that semantic sequence after all sanitization, including paragraphs with
    # utility-class attributes.
    def _final_ordered_list(match):
        values = []
        for line in match.group(2).splitlines():
            item = re.match(r'^\s*\d+\.\s+(.+?)\s*$', line)
            if item:
                values.append(item.group(1))
        if len(values) < 2:
            return match.group(0)
        return '<ol class="theory-ordered-list">' + ''.join(f'<li>{html.escape(value)}</li>' for value in values) + '</ol>'

    text = re.sub(
        r'<p([^>]*)>\s*((?:\d+\.\s+.*?(?:\n|$)){2,})\s*</p>',
        _final_ordered_list,
        text,
        flags=re.DOTALL,
    )
    text = text.replace('<p>__THEORY_SPACER__</p>', '<div class="theory-spacer"></div>')
    text = text.replace('__THEORY_SPACER__', '<div class="theory-spacer"></div>')
    text = text.replace('<p>THEORY_SPACER</p>', '<div class="theory-spacer"></div>')
    text = text.replace('THEORY_SPACER', '<div class="theory-spacer"></div>')
    # После markdown spacer мог оказаться внутри strong/em и повторно
    # появиться уже после основного прохода BeautifulSoup. Удаляем такие
    # пустые контейнеры финальным безопасным проходом.
    text = re.sub(
        r'<p>\s*<(?:strong|em)>\s*<div class="theory-spacer"></div>\s*</(?:strong|em)>\s*</p>',
        '',
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r'<(?:strong|em)>\s*<div class="theory-spacer"></div>\s*</(?:strong|em)>',
        '',
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r'<div class="theory-spacer"></div>', '', text, flags=re.IGNORECASE)
    for idx, block_html in enumerate(custom_blocks):
        text = text.replace(f"<!--THEORY_CUSTOM_BLOCK_{idx}-->", block_html)
        text = text.replace(f"<p>&lt;!--THEORY_CUSTOM_BLOCK_{idx}--&gt;</p>", block_html)
        text = text.replace(f"<p><!--THEORY_CUSTOM_BLOCK_{idx}--></p>", block_html)
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
    """Student dataset: groups + blocks + read/bookmark states + lock states."""
    groups, blocks_by_group = _get_course_groups_with_blocks(course_id)
    student = Student.query.filter_by(user_id=current_user.id).first() if current_user.is_student() else None

    teacher_locked_numbers = set()
    if student:
        access_rows = StudentTheoryAccess.query.filter_by(
            student_id=student.student_id,
            course_id=course_id,
        ).all()
        for r in access_rows:
            if not r.can_view:
                teacher_locked_numbers.add(r.task_number)

    state_by_number = {}
    if student:
        rows = StudentTheoryState.query.filter_by(student_id=student.student_id, course_id=course_id).all()
        for r in rows:
            state_by_number[r.task_number] = {
                'bookmarked': bool(r.is_bookmarked),
                'read': bool(r.is_read),
                'reading_progress': int(r.reading_progress or 0),
            }

    visible_groups = []
    for group in groups:
        group_items = blocks_by_group.get(group.id, [])
        items = []
        for idx, block in enumerate(group_items):
            is_teacher_locked = (block.task_number in teacher_locked_numbers) if student else False
            is_seq_locked = False
            lock_reason = ''
            if student and not is_teacher_locked:
                if idx > 0:
                    prev_b = group_items[idx - 1]
                    prev_st = state_by_number.get(prev_b.task_number, {})
                    prev_done = prev_st.get('read') or prev_st.get('reading_progress', 0) >= 100
                    if not prev_done:
                        is_seq_locked = True
                        lock_reason = f'Откроется после темы {idx}'

            if is_teacher_locked:
                block.is_locked = True
                block.lock_type = 'teacher'
                block.lock_reason = 'Заблокировано преподавателем'
            elif is_seq_locked:
                block.is_locked = True
                block.lock_type = 'sequence'
                block.lock_reason = lock_reason
            else:
                block.is_locked = False
                block.lock_type = None
                block.lock_reason = ''

            items.append(block)
        if items:
            visible_groups.append({'group': group, 'blocks': items})

    return visible_groups, state_by_number


def _build_catalog_context(course_id, selected_group_id=None):
    """Build one data-only view model for the live V2 theory catalogue."""
    visible_groups, state_by_number = _build_visible_with_state(course_id)
    course = Course.query.get(course_id)
    available_courses = Course.query.filter_by(is_active=True).all()
    all_blocks = [block for pack in visible_groups for block in pack['blocks']]
    student = Student.query.filter_by(user_id=current_user.id).first() if current_user.is_student() else None
    completed_count = sum(
        1 for block in all_blocks
        if state_by_number.get(block.task_number, {}).get('read')
        or state_by_number.get(block.task_number, {}).get('reading_progress', 0) >= 100
    )
    in_progress_count = sum(
        1 for block in all_blocks
        if 0 < state_by_number.get(block.task_number, {}).get('reading_progress', 0) < 100
    )
    saved_count = sum(1 for block in all_blocks if state_by_number.get(block.task_number, {}).get('bookmarked'))

    group_cards = []
    for pack in visible_groups:
        blocks = pack['blocks']
        completed = sum(
            1 for block in blocks
            if state_by_number.get(block.task_number, {}).get('read')
            or state_by_number.get(block.task_number, {}).get('reading_progress', 0) >= 100
        )
        next_block = next(
            (block for block in blocks if state_by_number.get(block.task_number, {}).get('reading_progress', 0) < 100),
            blocks[0] if blocks else None,
        )
        group_cards.append({
            'group': pack['group'],
            'blocks': blocks,
            'completed': completed,
            'progress': round(completed * 100 / len(blocks)) if blocks else 0,
            'next_block': next_block,
        })

    recommendations, assigned_materials = [], []
    if student:
        ranked = sorted(
            (block for block in all_blocks if state_by_number.get(block.task_number, {}).get('reading_progress', 0) < 100),
            key=lambda block: (
                0 if state_by_number.get(block.task_number, {}).get('reading_progress', 0) > 0 else 1,
                block.position,
                block.id,
            ),
        )
        recommendations = ranked[:3]
        assigned_materials = TheoryStudyAssignment.query.filter_by(
            student_id=student.student_id, status='assigned'
        ).join(TheoryBlock).filter(TheoryBlock.course_id == course_id).order_by(
            TheoryStudyAssignment.created_at.desc()
        ).all()

    avg_read_minutes = int(round(sum(b.read_minutes or 20 for b in all_blocks) / len(all_blocks))) if all_blocks else 25
    total_spent_minutes = sum(
        b.read_minutes or 20 for b in all_blocks
        if state_by_number.get(b.task_number, {}).get('read')
        or state_by_number.get(b.task_number, {}).get('reading_progress', 0) >= 100
    )
    spent_hours = total_spent_minutes // 60
    spent_mins = total_spent_minutes % 60

    return {
        'course': course,
        'course_id': course_id,
        'available_courses': available_courses,
        'visible_groups': visible_groups,
        'group_cards': group_cards,
        'all_blocks': all_blocks,
        'state_by_number': state_by_number,
        'selected_group_id': selected_group_id,
        'total_blocks': len(all_blocks),
        'completed_count': completed_count,
        'in_progress_count': in_progress_count,
        'saved_count': saved_count,
        'overall_progress': round(completed_count * 100 / len(all_blocks)) if all_blocks else 0,
        'avg_read_minutes': avg_read_minutes,
        'spent_hours': spent_hours,
        'spent_mins': spent_mins,
        'recommendations': recommendations,
        'assigned_materials': assigned_materials,
    }


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

    return render_template('sandbox/theory.html', **_build_catalog_context(course_id))


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

    context = _build_catalog_context(course_id, selected_group_id=group_id)
    selected_group_pack = next((x for x in context['visible_groups'] if x['group'].id == group_id), None)
    if not selected_group_pack:
        return redirect(url_for('theory.theory_index', course_id=course_id))

    # The V2 catalogue is the only live entry point.  Keep group URLs as a
    # useful deep link, but render them through the same canonical screen.
    return render_template('sandbox/theory.html', **context)


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


def _parse_theory_sections(content):
    text = _strip_status_marker(content or '').replace('\r\n', '\n').strip()
    text = re.sub(r'^#\s+[^\n]+\n*', '', text).strip()
    pattern = r'(?m)^##\s+([^\n]+)$'
    matches = list(re.finditer(pattern, text))
    if not matches:
        return [{
            'num': '01',
            'title': 'Материал темы',
            'html': _render_theory_content_html(text),
        }]
    sections = []
    preamble = text[:matches[0].start()].strip()
    if preamble:
        sections.append({
            'num': f'{len(sections)+1:02d}',
            'title': 'Введение',
            'html': _render_theory_content_html(preamble),
        })
    for i, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[i+1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        sections.append({
            'num': f'{len(sections)+1:02d}',
            'title': title,
            'html': _render_theory_content_html(body),
        })
    return sections


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
        if student:
            # 1. Teacher lock check
            access_row = StudentTheoryAccess.query.filter_by(
                student_id=student.student_id,
                course_id=course_id,
                task_number=task_number,
            ).first()
            if access_row and not access_row.can_view:
                flash('Эта тема заблокирована преподавателем.', 'warning')
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
                'reading_progress': int(st_row.reading_progress or 0),
                'last_position': int(st_row.last_position or 0),
            }
        feedback = TheoryFeedback.query.filter_by(
            student_id=student.student_id,
            course_id=course_id,
            task_number=task_number,
        ).first()
    note = StudentTheoryNote.query.filter_by(student_id=student.student_id, block_id=block.id).first() if student else None
    checkpoint_attempts = {}
    checkpoint_attempts_data = {}
    if student:
        attempts = TheoryCheckpointAttempt.query.filter_by(student_id=student.student_id, block_id=block.id).all()
        checkpoint_attempts = {item.checkpoint_key: item for item in attempts}
        checkpoint_attempts_data = {
            item.checkpoint_key: {
                'answer': item.selected_answer,
                'correct': bool(item.is_correct),
                'attempts': item.attempts_count,
            }
            for item in attempts
        }

    sections = _parse_theory_sections(block.content or '')

    prev_block = None
    next_block = None
    all_blocks_flat = []
    for grp in visible_groups:
        if isinstance(grp, dict):
            all_blocks_flat.extend(grp.get('blocks', []))
        elif hasattr(grp, 'blocks'):
            all_blocks_flat.extend(grp.blocks or [])
    for idx_b, item_b in enumerate(all_blocks_flat):
        if item_b.id == block.id:
            if idx_b > 0:
                prev_block = all_blocks_flat[idx_b - 1]
            if idx_b + 1 < len(all_blocks_flat):
                next_block = all_blocks_flat[idx_b + 1]
            break

    template_ctx = dict(
        block=block,
        course_id=course_id,
        visible_groups=visible_groups,
        prev_block=prev_block,
        next_block=next_block,
        back_to_url=url_for('theory.theory_index', course_id=course_id),
        active_page='theory',
        custom_html=custom_html,
        rendered_content_html=_render_theory_content_html(block.content or ''),
        sections=sections,
        note=note,
        checkpoint_attempts=checkpoint_attempts,
        checkpoint_attempts_data=checkpoint_attempts_data,
    )

    response = make_response(render_template(
        'sandbox/theory_article.html',
        state_by_number=state_by_number,
        state=state,
        feedback=feedback,
        **template_ctx,
    ))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


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
            checkpoint_stats=[],
            course_insights=[],
            scoped_students_count=0,
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
        if action == 'assign_material':
            block_id = request.form.get('block_id', type=int)
            student_id = request.form.get('student_id', type=int)
            message = (request.form.get('assignment_message') or '').strip()
            block = TheoryBlock.query.filter_by(id=block_id, course_id=course_id).first()
            if not block or _extract_status(block.content) != 'published':
                flash('Назначать можно только опубликованный материал.', 'warning')
                return redirect(url_for('theory.manage_list', course_id=course_id))
            scoped_students = _get_scoped_students_for_theory_manager()
            student = next((item for item in scoped_students if item.student_id == student_id), None)
            if not student:
                flash('У вас нет доступа к этому ученику.', 'danger')
                return redirect(url_for('theory.manage_list', course_id=course_id, block_id=block.id))
            assignment = TheoryStudyAssignment.query.filter_by(student_id=student.student_id, block_id=block.id).first()
            if not assignment:
                assignment = TheoryStudyAssignment(student_id=student.student_id, block_id=block.id, assigned_by_user_id=current_user.id)
                db.session.add(assignment)
            assignment.message = message or None
            assignment.status = 'assigned'
            assignment.completed_at = None
            db.session.commit()
            flash('Материал назначен ученику.', 'success')
            return redirect(url_for('theory.manage_list', course_id=course_id, group_id=block.group_id, block_id=block.id))

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

    scoped_students = _get_scoped_students_for_theory_manager()
    scoped_student_ids = [item.student_id for item in scoped_students]
    course_insights = []
    if scoped_student_ids:
        all_states = StudentTheoryState.query.filter(
            StudentTheoryState.course_id == course_id,
            StudentTheoryState.student_id.in_(scoped_student_ids),
        ).all()
        states_by_task = defaultdict(list)
        for state_item in all_states:
            states_by_task[state_item.task_number].append(state_item)
        attempts_by_block = defaultdict(list)
        for attempt in TheoryCheckpointAttempt.query.join(TheoryBlock).filter(
            TheoryBlock.course_id == course_id,
            TheoryCheckpointAttempt.student_id.in_(scoped_student_ids),
        ).all():
            attempts_by_block[attempt.block_id].append(attempt)
        for candidate in [block for entries in blocks_by_group.values() for block in entries if _extract_status(block.content) == 'published']:
            states = states_by_task.get(candidate.task_number, [])
            completed = sum(1 for state_item in states if state_item.is_read or int(state_item.reading_progress or 0) >= 100)
            completion_rate = int(round((completed / len(scoped_student_ids)) * 100)) if scoped_student_ids else 0
            attempts = attempts_by_block.get(candidate.id, [])
            correct_rate = int(round((sum(1 for item in attempts if item.is_correct) / len(attempts)) * 100)) if attempts else None
            risk = 'high' if completion_rate < 45 or (correct_rate is not None and correct_rate < 50) else 'medium' if completion_rate < 75 or (correct_rate is not None and correct_rate < 70) else 'low'
            if risk != 'low':
                course_insights.append({'block': candidate, 'completion_rate': completion_rate, 'correct_rate': correct_rate, 'risk': risk, 'not_started': max(0, len(scoped_student_ids) - completed)})
        course_insights.sort(key=lambda item: (0 if item['risk'] == 'high' else 1, item['completion_rate'], item['correct_rate'] if item['correct_rate'] is not None else 101))
        course_insights = course_insights[:6]

    student_stats = []
    comments_history = []
    checkpoint_stats = []
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
        checkpoints = _parse_theory_checkpoints(selected_block.content)
        attempts = TheoryCheckpointAttempt.query.filter_by(block_id=selected_block.id).all()
        attempts_by_key = defaultdict(list)
        for attempt in attempts:
            attempts_by_key[attempt.checkpoint_key].append(attempt)
        for checkpoint in checkpoints:
            rows = attempts_by_key.get(checkpoint['key'], [])
            correct = sum(1 for row in rows if row.is_correct)
            checkpoint_stats.append({
                'question': checkpoint['question'],
                'attempts': len(rows),
                'correct': correct,
                'success_rate': int(round((correct / len(rows)) * 100)) if rows else None,
            })

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
        checkpoint_stats=checkpoint_stats,
        course_insights=course_insights,
        scoped_students_count=len(scoped_student_ids),
        scoped_students=scoped_students,
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
        # Ученику разрешён только изолированный запуск кода из опубликованной
        # статьи; доступ к редактору теории и чужим материалам не расширяется.
        if not current_user.is_student():
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
    payload = request.get_json(silent=True) or {}
    resolved, error = _resolve_student_block_from_payload(payload)
    if error:
        return jsonify({'success': False, 'error': error}), 404
    student, block = resolved
    row = StudentTheoryState.query.filter_by(student_id=student.student_id, course_id=block.course_id, task_number=block.task_number).first()
    if not row:
        row = StudentTheoryState(student_id=student.student_id, course_id=block.course_id, task_number=block.task_number)
        db.session.add(row)
    row.is_read = True
    row.reading_progress = 100
    row.last_opened_at = moscow_now()
    TheoryStudyAssignment.query.filter_by(
        student_id=student.student_id,
        block_id=block.id,
        status='assigned',
    ).update({'status': 'completed', 'completed_at': moscow_now()})
    db.session.commit()
    try:
        from app.utils.gamification_service import reward_theory_reading
        reward_theory_reading(student)
    except Exception:
        pass
    return jsonify({'success': True})


@theory_bp.route('/theory/api/progress', methods=['POST'])
@csrf.exempt
def theory_api_progress():
    # Progress is a background autosave.  A cached article can outlive the
    # login session; in that case it must be a harmless no-op rather than a
    # red console error.  Authenticated students still go through the normal
    # ownership and persistence path below.
    if not current_user.is_authenticated:
        return jsonify({'success': True, 'progress': 0, 'preview': True})
    if not current_user.is_student():
        # Страница теории может открываться в режиме просмотра преподавателем
        # или создателем. Такой просмотр не должен порождать ошибки в консоли:
        # прогресс не сохраняем, но отвечаем успешным preview-результатом.
        return jsonify({'success': True, 'progress': 0, 'preview': True})
    resolved, error = _resolve_student_block_from_payload(request.get_json(silent=True) or {})
    if error:
        return jsonify({'success': False, 'error': error}), 404
    student, block = resolved
    payload = request.get_json(silent=True) or {}
    try:
        progress = max(0, min(100, int(payload.get('progress', 0))))
        position = max(0, int(payload.get('position', 0)))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Некорректный прогресс.'}), 400
    row = StudentTheoryState.query.filter_by(student_id=student.student_id, course_id=block.course_id, task_number=block.task_number).first()
    if not row:
        row = StudentTheoryState(student_id=student.student_id, course_id=block.course_id, task_number=block.task_number)
        db.session.add(row)
    row.reading_progress = max(int(row.reading_progress or 0), progress)
    row.last_position = position
    row.last_opened_at = moscow_now()
    if progress >= 95 or row.reading_progress >= 100:
        row.is_read = True
        row.reading_progress = 100
        TheoryStudyAssignment.query.filter_by(
            student_id=student.student_id,
            block_id=block.id,
            status='assigned',
        ).update({'status': 'completed', 'completed_at': moscow_now()})
    db.session.commit()

    if row.reading_progress >= 100:
        try:
            from app.utils.gamification_service import reward_theory_reading
            reward_theory_reading(student)
        except Exception:
            pass

    return jsonify({'success': True, 'progress': row.reading_progress})


@theory_bp.route('/theory/api/checkpoint', methods=['POST'])
@login_required
def theory_api_checkpoint():
    if not current_user.is_student():
        return jsonify({'success': False, 'error': 'Только для учеников'}), 403
    payload = request.get_json(silent=True) or {}
    resolved, error = _resolve_student_block_from_payload(payload)
    if error:
        return jsonify({'success': False, 'error': error}), 404
    student, block = resolved
    checkpoint_key = (payload.get('checkpoint_key') or '').strip()
    selected_answer = (payload.get('answer') or '').strip()
    checkpoint = next((item for item in _parse_theory_checkpoints(block.content) if item['key'] == checkpoint_key), None)
    interactive = next((item for item in _parse_theory_interactives(block.content) if item['key'] == checkpoint_key), None)
    if not checkpoint and not interactive:
        return jsonify({'success': False, 'error': 'Проверка не найдена.'}), 404
    kind = interactive['type'] if interactive else 'checkpoint'
    expected_answer = (interactive.get('answer') if interactive else checkpoint['answer']) or ''
    if kind in {'code', 'debug'}:
        # Code activities submit the actual program output; the expected value
        # remains server-side in the interactive marker.
        is_correct = selected_answer == (interactive.get('expected') or expected_answer).strip()
    elif kind in {'multi', 'classify'}:
        selected_set = {part.strip() for part in selected_answer.split('|') if part.strip()}
        expected_set = {part.strip() for part in expected_answer.split('|') if part.strip()}
        allowed_set = {part.strip() for part in interactive.get('options', '').split('|') if part.strip()}
        # A wrong or incomplete selection is a regular failed attempt, not a
        # missing resource. This lets the UI show feedback and allow retry.
        is_correct = bool(selected_set) and selected_set.issubset(allowed_set) and selected_set == expected_set
    elif kind in {'match'}:
        def _norm_m(s):
            if '=' in s:
                return '='.join(p.strip().lower() for p in s.split('=', 1))
            return s.strip().lower()
        is_correct = _norm_m(selected_answer) == _norm_m(expected_answer)
    elif kind in {'boolean'}:
        is_true_expected = expected_answer.strip().lower() in {'true', '1', 'да', 'yes'}
        is_true_selected = selected_answer.strip().lower() in {'true', '1', 'да', 'yes'}
        is_correct = (is_true_expected == is_true_selected)
    else:
        # Every known interactive format uses a canonical answer string. Keep
        # comparison server-side and return 200/false for a wrong value so the
        # student never sees a misleading 404 toast.
        is_correct = selected_answer.strip().lower() == expected_answer.strip().lower()
    attempt = TheoryCheckpointAttempt.query.filter_by(student_id=student.student_id, block_id=block.id, checkpoint_key=checkpoint_key).first()
    if not attempt:
        attempt = TheoryCheckpointAttempt(student_id=student.student_id, block_id=block.id, checkpoint_key=checkpoint_key, selected_answer=selected_answer, is_correct=is_correct)
        db.session.add(attempt)
    else:
        attempt.selected_answer = selected_answer
        attempt.is_correct = is_correct
        attempt.attempts_count = int(attempt.attempts_count or 0) + 1
        attempt.answered_at = moscow_now()
    db.session.commit()
    explanation = (checkpoint or {}).get('explanation') or (interactive or {}).get('explanation') or ''
    return jsonify({'success': True, 'correct': is_correct, 'explanation': explanation, 'attempts': attempt.attempts_count})


@theory_bp.route('/theory/api/note', methods=['POST'])
@login_required
def theory_api_note():
    if not current_user.is_student():
        return jsonify({'success': False, 'error': 'Только для учеников'}), 403
    payload = request.get_json(silent=True) or {}
    resolved, error = _resolve_student_block_from_payload(payload)
    if error:
        return jsonify({'success': False, 'error': error}), 404
    student, block = resolved
    content = (payload.get('content') or '').strip()
    if len(content) > 5000:
        return jsonify({'success': False, 'error': 'Заметка не может быть длиннее 5000 символов.'}), 400
    note = StudentTheoryNote.query.filter_by(student_id=student.student_id, block_id=block.id).first()
    if not note and content:
        note = StudentTheoryNote(student_id=student.student_id, block_id=block.id, content=content)
        db.session.add(note)
    elif note:
        note.content = content
    db.session.commit()
    return jsonify({'success': True, 'saved': bool(content)})


@theory_bp.route('/theory/api/bookmark', methods=['POST'])
@login_required
def theory_api_bookmark():
    if not current_user.is_student():
        return jsonify({'success': False, 'error': 'Только для учеников'}), 403
    payload = request.get_json(silent=True) or {}
    resolved, error = _resolve_student_block_from_payload(payload)
    if error:
        return jsonify({'success': False, 'error': error}), 404
    student, block = resolved
    value = bool(payload.get('value'))
    row = StudentTheoryState.query.filter_by(student_id=student.student_id, course_id=block.course_id, task_number=block.task_number).first()
    if not row:
        row = StudentTheoryState(student_id=student.student_id, course_id=block.course_id, task_number=block.task_number)
        db.session.add(row)
    row.is_bookmarked = value
    db.session.commit()
    return jsonify({'success': True, 'bookmarked': row.is_bookmarked})


@theory_bp.route('/theory/api/feedback', methods=['POST'])
@login_required
def theory_api_feedback():
    if not current_user.is_student():
        return jsonify({'success': False, 'error': 'Только для учеников'}), 403
    payload = request.get_json(silent=True) or {}
    resolved, error = _resolve_student_block_from_payload(payload)
    if error:
        return jsonify({'success': False, 'error': error}), 404
    student, block = resolved
    rating = payload.get('rating')
    comment = (payload.get('comment') or '').strip()
    if len(comment) > 2000:
        return jsonify({'success': False, 'error': 'Комментарий слишком длинный.'}), 400
    row = TheoryFeedback.query.filter_by(student_id=student.student_id, course_id=block.course_id, task_number=block.task_number).first()
    if not row:
        row = TheoryFeedback(student_id=student.student_id, user_id=current_user.id, course_id=block.course_id, task_number=block.task_number)
        db.session.add(row)
    try:
        row.rating = int(rating) if rating is not None else None
    except Exception:
        row.rating = None
    if row.rating is not None and row.rating not in range(1, 6):
        return jsonify({'success': False, 'error': 'Оценка должна быть от 1 до 5.'}), 400
    row.comment = comment or None
    # Upsert latest feedback snapshot per student/topic instead of creating duplicates.
    history_row = TheoryFeedbackHistory.query.filter_by(
        student_id=student.student_id,
        course_id=block.course_id,
        task_number=block.task_number,
    ).order_by(TheoryFeedbackHistory.id.desc()).first()
    if not history_row:
        history_row = TheoryFeedbackHistory(
            student_id=student.student_id,
            user_id=current_user.id,
            course_id=block.course_id,
            task_number=block.task_number,
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

    course = Course.query.get(course_id) if course_id else None
    students = _get_scoped_students_for_theory_manager()

    locked_counts = {}
    if students and course_id:
        s_ids = [s.student_id for s in students]
        rows = StudentTheoryAccess.query.filter(
            StudentTheoryAccess.course_id == course_id,
            StudentTheoryAccess.student_id.in_(s_ids),
            StudentTheoryAccess.can_view == False
        ).all()
        for r in rows:
            locked_counts[r.student_id] = locked_counts.get(r.student_id, 0) + 1

    total_blocks_count = TheoryBlock.query.filter_by(course_id=course_id).count()

    return render_template(
        'theory/theory_access_list.html',
        students=students,
        course=course,
        course_id=course_id,
        locked_counts=locked_counts,
        total_blocks_count=total_blocks_count,
        active_page='theory_manage',
    )


@theory_bp.route('/theory/manage/access/<int:student_id>', methods=['GET', 'POST'])
@login_required
def manage_access_student(student_id):
    """Включение/выключение просмотра теории по темам и номерам курса для ученика."""
    if not _can_manage_theory():
        flash('Недостаточно прав.', 'danger')
        return redirect(url_for('main.dashboard'))

    course_id = request.args.get('course_id', type=int) or request.form.get('course_id', type=int) or _get_default_course_id()
    if course_id is None:
        flash('Нет доступных курсов.', 'danger')
        return redirect(url_for('theory.manage_list'))

    course = Course.query.get(course_id) if course_id else None
    student = Student.query.get_or_404(student_id)
    if student.student_id not in {item.student_id for item in _get_scoped_students_for_theory_manager()}:
        flash('Нет доступа к этому ученику.', 'danger')
        return redirect(url_for('theory.manage_access_index', course_id=course_id))

    groups, blocks_by_group = _get_course_groups_with_blocks(course_id)
    all_blocks = TheoryBlock.query.filter_by(course_id=course_id).order_by(TheoryBlock.position, TheoryBlock.id).all()

    group_packs = []
    for g in groups:
        items = blocks_by_group.get(g.id, [])
        if items:
            group_packs.append({'group': g, 'blocks': items})

    ungrouped = [b for b in all_blocks if not b.group_id]
    if ungrouped:
        class _UngroupedHolder:
            id = 0
            name = 'Без модуля'
        group_packs.append({'group': _UngroupedHolder(), 'blocks': ungrouped})

    # All known task numbers (both from blocks and course templates)
    course_templates = _get_course_task_numbers(course_id)
    all_task_numbers = sorted({b.task_number for b in all_blocks} | set(course_templates))

    access_list = StudentTheoryAccess.query.filter_by(
        student_id=student_id,
        course_id=course_id,
    ).all()
    access_by_number = {a.task_number: a.can_view for a in access_list}

    if request.method == 'POST':
        bulk_action = request.form.get('bulk_action')
        if bulk_action == 'allow_all':
            StudentTheoryAccess.query.filter_by(
                student_id=student_id,
                course_id=course_id,
            ).delete()
            db.session.commit()
            flash(f'Все темы курса открыты для {student.name or "ученика"}.', 'success')
            return redirect(url_for('theory.manage_access_student', student_id=student_id, course_id=course_id))
        elif bulk_action == 'lock_all':
            for num in all_task_numbers:
                existing = StudentTheoryAccess.query.filter_by(
                    student_id=student_id,
                    course_id=course_id,
                    task_number=num,
                ).first()
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
            flash(f'Все темы курса заблокированы для {student.name or "ученика"}.', 'warning')
            return redirect(url_for('theory.manage_access_student', student_id=student_id, course_id=course_id))

        # Сохранение чекбоксов по номерам
        for num in all_task_numbers:
            key = f'allow_{num}'
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
        flash(f'Доступ к теории для {student.name or "ученика"} успешно обновлён.', 'success')
        return redirect(url_for('theory.manage_access_student', student_id=student_id, course_id=course_id))

    return render_template(
        'theory/theory_access_student.html',
        student=student,
        course=course,
        course_id=course_id,
        group_packs=group_packs,
        all_blocks=all_blocks,
        task_numbers=all_task_numbers,
        access_by_number=access_by_number,
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
    
    rendered_blocks = {
        block.id: _render_theory_content_html(block.content or '')
        for block in blocks
    }
    return render_template('sandbox/course_map.html', blocks=blocks, rendered_blocks=rendered_blocks, course_id=course_id)

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
