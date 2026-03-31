"""
Маршруты теории по заданиям ЕГЭ: просмотр для учеников, CRUD для тьютора.
Поддержка мульти-курсовой архитектуры: номера заданий берутся из CourseTaskTemplate.
"""
import logging
import os
import re
import subprocess
from flask import render_template, request, redirect, url_for, flash, abort, jsonify, current_app
from markupsafe import Markup
from flask_login import login_required, current_user

from app.theory import theory_bp
from app.models import (
    db,
    TheoryBlock,
    StudentTheoryAccess,
    Student,
    User,
    Course,
    CourseTaskTemplate,
    StudentCourseEnrollment,
    StudentTheoryState,
    TheoryFeedback,
    moscow_now,
)
from app.auth.rbac_utils import has_permission

logger = logging.getLogger(__name__)


def _strip_status_marker(content_value):
    text = (content_value or '').strip()
    if text.startswith('<!--status:published-->'):
        return text[len('<!--status:published-->'):].lstrip()
    if text.startswith('<!--status:draft-->'):
        return text[len('<!--status:draft-->'):].lstrip()
    return text


def _render_theory_content_html(content_value):
    """Render block-based theory markers to safe-ish HTML fragments."""
    text = _strip_status_marker(content_value or '')

    def _code_repl(match):
        lang = (match.group(1) or 'python').strip().lower()
        code_body = (match.group(2) or '').strip()
        return (
            '<div class="theory-smart-code my-6 rounded-2xl border border-slate-700 overflow-hidden bg-slate-900" '
            f'data-lang="{lang}">'
            '<div class="px-4 py-2.5 border-b border-slate-700 bg-slate-800/80 flex items-center justify-between">'
            f'<span class="text-xs font-bold text-slate-300 uppercase">{lang}</span>'
            '<div class="flex items-center gap-2">'
            '<input type="text" class="theory-code-args bg-slate-900 border border-slate-600 rounded-md px-2 py-1 text-[11px] text-slate-200" '
            'placeholder="Аргументы / stdin">'
            '<button type="button" class="theory-run-btn px-2.5 py-1 text-xs font-bold text-white bg-green-600 hover:bg-green-500 rounded-md">Run</button>'
            '</div>'
            '</div>'
            f'<textarea class="theory-code-input w-full min-h-[120px] bg-slate-950 text-slate-200 font-mono text-xs p-4 border-none outline-none">{code_body}</textarea>'
            '<pre class="theory-code-output hidden m-0 p-4 bg-black text-green-300 text-xs font-mono border-t border-slate-700"></pre>'
            '</div>'
        )

    def _callout_repl(match):
        ctype = (match.group(1) or 'tip').strip().lower()
        body = (match.group(2) or '').strip()
        theme = {
            'attention': ('orange', 'Внимание'),
            'tip': ('cyan', 'Лайфхак'),
            'danger': ('red', 'Осторожно'),
        }.get(ctype, ('cyan', 'Заметка'))
        color, title = theme
        return (
            f'<div class="my-5 rounded-2xl border border-{color}-200 bg-{color}-50 px-5 py-4">'
            f'<div class="text-xs font-extrabold uppercase tracking-widest text-{color}-600 mb-1">{title}</div>'
            f'<div class="text-sm font-medium text-slate-700">{body}</div>'
            '</div>'
        )

    def _practice_repl(match):
        task_id = (match.group(1) or '').strip()
        return (
            '<div class="my-6 rounded-2xl border-2 border-slate-200 bg-white p-5">'
            '<div class="text-[10px] font-extrabold uppercase tracking-widest text-slate-400 mb-2">Интерактивный блок</div>'
            f'<div class="text-sm font-bold text-slate-800 mb-3">Практика · ID: {task_id}</div>'
            '<button type="button" class="px-3 py-2 rounded-lg bg-slate-100 border border-slate-200 text-sm font-bold text-slate-700">Открыть в тренажере</button>'
            '</div>'
        )

    text = re.sub(r"\[CODE\s+lang=\"([^\"]+)\"\](.*?)\[/CODE\]", _code_repl, text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"\[CALLOUT\s+type=\"([^\"]+)\"\](.*?)\[/CALLOUT\]", _callout_repl, text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"\[PRACTICE_TASK\s+id=\"([^\"]+)\"\]", _practice_repl, text, flags=re.IGNORECASE)
    text = re.sub(r"\$\$(.+?)\$\$", lambda m: f'<div class="my-4 text-center text-xl font-serif text-slate-800">{m.group(1)}</div>', text, flags=re.DOTALL)
    try:
        from markdown import markdown as _md
        text = _md(text, extensions=['extra', 'tables', 'fenced_code'])
    except Exception:
        pass
    return Markup(text)


def _get_course_task_numbers(course_id):
    """
    Возвращает отсортированный список номеров заданий для курса из CourseTaskTemplate.
    """
    if course_id is None:
        return []
    templates = CourseTaskTemplate.query.filter_by(course_id=course_id).all()
    return sorted({t.task_number for t in templates})


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
    task_numbers = _get_course_task_numbers(course_id)
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


# --- Просмотр для учеников (и тьюторов) ---

@theory_bp.route('/theory')
@login_required
def theory_index():
    """Список теории по заданиям: только те номера, по которым есть блок и доступ разрешён."""
    if not has_permission(current_user, 'theory.view'):
        flash('У вас нет доступа к разделу «Теория».', 'warning')
        return redirect(url_for('main.dashboard'))

    course_id = request.args.get('course_id', type=int) or _get_default_course_id()
    if course_id is None:
        flash('Нет доступных курсов. Обратитесь к администратору.', 'warning')
        return render_template(
            'theory/theory_index.html',
            visible=[],
            course_id=None,
            active_page='theory',
        )

    task_numbers = _get_course_task_numbers(course_id)
    blocks = TheoryBlock.query.filter(
        (TheoryBlock.course_id == course_id) | (TheoryBlock.course_id.is_(None))
    ).order_by(TheoryBlock.task_number).all()
    block_by_number = {b.task_number: b for b in blocks}

    # Для ученика — фильтруем по StudentTheoryAccess
    allowed_numbers = set(task_numbers)
    if current_user.is_student():
        student = Student.query.filter_by(user_id=current_user.id).first()
        if student:
            allowed_numbers = _get_allowed_task_numbers_for_student(student.student_id, course_id)
        else:
            allowed_numbers = set()

    # Показываем только номера, по которым есть блок и доступ
    visible = [
        (num, block_by_number.get(num))
        for num in task_numbers
        if num in allowed_numbers and num in block_by_number
    ]

    return render_template(
        'theory/theory_index.html',
        visible=visible,
        course_id=course_id,
        active_page='theory',
    )


@theory_bp.route('/theory/<int:task_number>')
@login_required
def theory_view(task_number):
    """Просмотр одного блока теории по номеру задания."""
    if not has_permission(current_user, 'theory.view'):
        flash('У вас нет доступа к разделу «Теория».', 'warning')
        return redirect(url_for('main.dashboard'))

    course_id = request.args.get('course_id', type=int) or _get_default_course_id()
    if course_id is None:
        flash('Нет доступных курсов.', 'warning')
        return redirect(url_for('main.dashboard'))

    task_numbers = _get_course_task_numbers(course_id)
    if task_number not in task_numbers:
        abort(404)

    if current_user.is_student():
        student = Student.query.filter_by(user_id=current_user.id).first()
        if student and not _student_can_view_task_number(student.student_id, task_number, course_id):
            flash('Просмотр теории по этому заданию для вас закрыт.', 'warning')
            return redirect(url_for('theory.theory_index', course_id=course_id))

    block = TheoryBlock.query.filter(
        ((TheoryBlock.course_id == course_id) | (TheoryBlock.course_id.is_(None))),
        TheoryBlock.task_number == task_number,
    ).first()
    if not block:
        flash('Теория по заданию {} ещё не добавлена.'.format(task_number), 'info')
        return redirect(url_for('theory.theory_index', course_id=course_id))

    custom_html = None
    try:
        project_root = os.path.dirname(current_app.root_path)
        theory_root = os.path.join(project_root, 'theory')
        filename = f"n{task_number}.html"
        candidate = os.path.join(theory_root, filename)
        if os.path.exists(candidate):
            with open(candidate, 'r', encoding='utf-8') as f:
                raw = f.read()
            # allow the file to contain Jinja placeholders (e.g. {{ task_number }})
            from flask import render_template_string
            custom_html = render_template_string(raw, task_number=task_number)
    except Exception:
        logger.exception("Failed to load custom theory HTML for task_number=%s", task_number)

    return render_template(
        'theory/theory_view.html',
        block=block,
        course_id=course_id,
        active_page='theory',
        custom_html=custom_html,
        rendered_content_html=_render_theory_content_html(block.content or ''),
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


@theory_bp.route('/theory/manage', methods=['GET', 'POST'])
@login_required
def manage_list():
    """Рабочее пространство теории: сетка + блочный редактор."""
    if not _can_manage_theory():
        flash('Недостаточно прав для управления теорией.', 'danger')
        return redirect(url_for('main.dashboard'))

    course_id = request.args.get('course_id', type=int) or _get_default_course_id()
    if course_id is None:
        flash('Нет доступных курсов. Создайте курс в настройках.', 'warning')
        return render_template(
            'theory/theory_manage_list.html',
            slots=[],
            course_id=None,
            active_page='theory_manage',
        )

    task_numbers = _get_course_task_numbers(course_id)
    blocks = TheoryBlock.query.filter(
        (TheoryBlock.course_id == course_id) | (TheoryBlock.course_id.is_(None))
    ).order_by(TheoryBlock.task_number).all()
    block_by_number = {b.task_number: b for b in blocks}
    slots = [(num, block_by_number.get(num)) for num in task_numbers]

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

    if request.method == 'POST':
        task_number = request.form.get('task_number', type=int)
        title = (request.form.get('title') or '').strip()
        content = (request.form.get('content') or '').strip()
        status = (request.form.get('editor_status') or 'draft').strip().lower()
        if status not in ('draft', 'published'):
            status = 'draft'

        if task_number is None or task_number not in task_numbers:
            flash('Выберите корректный номер задания.', 'danger')
            return redirect(url_for('theory.manage_list', course_id=course_id))

        block = block_by_number.get(task_number)
        content_with_status = _with_status_prefix(content, status)
        default_title = f'Задание {task_number}'

        if block:
            block.title = title or default_title
            block.content = content_with_status
            block.author_id = current_user.id
        else:
            block = TheoryBlock(
                course_id=course_id,
                task_number=task_number,
                title=title or default_title,
                content=content_with_status,
                author_id=current_user.id,
            )
            db.session.add(block)

        db.session.commit()
        flash('Теория сохранена.' if status == 'draft' else 'Теория опубликована.', 'success')
        return redirect(url_for('theory.manage_list', course_id=course_id, task_number=task_number))

    selected_task_number = request.args.get('task_number', type=int)
    if selected_task_number not in task_numbers:
        selected_task_number = task_numbers[0] if task_numbers else None
    selected_block = block_by_number.get(selected_task_number) if selected_task_number is not None else None

    grid_states = []
    existing_count = 0
    published_count = 0
    for num in task_numbers:
        b = block_by_number.get(num)
        if b is None:
            grid_states.append({'task_number': num, 'state': 'empty'})
            continue
        existing_count += 1
        state = _extract_status(b.content)
        if state == 'published':
            published_count += 1
        grid_states.append({'task_number': num, 'state': state})

    from app.models import Course as ExamCourse
    course = ExamCourse.query.get(course_id) if course_id else None

    return render_template(
        'theory/theory_manage_list.html',
        slots=slots,
        grid_states=grid_states,
        selected_task_number=selected_task_number,
        selected_block=selected_block,
        completion_percent=(int(round((existing_count / len(task_numbers)) * 100)) if task_numbers else 0),
        published_count=published_count,
        course_id=course_id,
        course=course,
        task_numbers=task_numbers,
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
        static_root = current_app.static_folder or os.path.join(current_app.root_path, 'static')
        upload_folder = os.path.join(static_root, 'uploads', 'theory', str(current_user.id))
        orig, abs_path, _size = save_uploaded_file(
            file=file,
            base_folder=upload_folder,
            allowed_exts={'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'},
            max_bytes=15 * 1024 * 1024,
        )
        rel = os.path.relpath(abs_path, static_root).replace('\\', '/')
        url = url_for('static', filename=rel)
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
        static_root = current_app.static_folder or os.path.join(current_app.root_path, 'static')
        upload_folder = os.path.join(static_root, 'uploads', 'theory_pdfs', str(current_user.id))
        orig, abs_path, _size = save_uploaded_file(
            file=file,
            base_folder=upload_folder,
            allowed_exts={'pdf'},
            max_bytes=30 * 1024 * 1024,
        )
        rel = os.path.relpath(abs_path, static_root).replace('\\', '/')
        url = url_for('static', filename=rel)
        return jsonify({'success': True, 'url': url, 'name': orig})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception:
        logger.exception('Theory PDF upload failed')
        return jsonify({'success': False, 'error': 'Ошибка загрузки PDF'}), 500


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

    task_numbers = _get_course_task_numbers(course_id)
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
    course_id = block.course_id or _get_default_course_id()
    db.session.delete(block)
    db.session.commit()
    flash('Блок теории по заданию {} удалён.'.format(num), 'success')
    return redirect(url_for('theory.manage_list', course_id=course_id))


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


@theory_bp.route('/theory/api/run-code', methods=['POST'])
@login_required
def theory_api_run_code():
    if not (has_permission(current_user, 'theory.view') or _can_manage_theory()):
        return jsonify({'success': False, 'error': 'Нет доступа'}), 403
    payload = request.get_json(silent=True) or {}
    lang = (payload.get('lang') or 'python').strip().lower()
    code = (payload.get('code') or '').strip()
    args = (payload.get('args') or '').strip()
    if not code:
        return jsonify({'success': False, 'error': 'Пустой код'}), 400
    if lang != 'python':
        return jsonify({'success': False, 'error': 'Пока поддержан только Python'}), 400
    try:
        proc = subprocess.run(
            ['python', '-c', code],
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
