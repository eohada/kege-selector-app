"""
Маршруты теории по заданиям ЕГЭ: просмотр для учеников, CRUD для тьютора.
"""
import logging
import os
from flask import render_template, request, redirect, url_for, flash, abort, jsonify, current_app
from flask_login import login_required, current_user

from app.theory import theory_bp
from app.models import (
    db,
    TheoryBlock,
    StudentTheoryAccess,
    Student,
    User,
    moscow_now,
)
from app.auth.rbac_utils import has_permission, check_access

logger = logging.getLogger(__name__)

# Номера заданий ЕГЭ по информатике (1–27)
THEORY_TASK_NUMBERS = list(range(1, 28))


def _get_allowed_task_numbers_for_student(student_id):
    """
    Для ученика: номера заданий, по которым разрешён просмотр теории.
    Если записи в StudentTheoryAccess нет — доступ разрешён.
    can_view=False — запретить.
    """
    if not student_id:
        return set(THEORY_TASK_NUMBERS)
    rows = StudentTheoryAccess.query.filter_by(student_id=student_id).all()
    allowed = set(THEORY_TASK_NUMBERS)
    for r in rows:
        if not r.can_view:
            allowed.discard(r.task_number)
        else:
            allowed.add(r.task_number)
    return allowed


def _student_can_view_task_number(student_id, task_number):
    """Проверка: может ли ученик смотреть теорию по заданию task_number."""
    return task_number in _get_allowed_task_numbers_for_student(student_id)


# --- Просмотр для учеников (и тьюторов) ---

@theory_bp.route('/theory')
@login_required
def theory_index():
    """Список теории по заданиям: только те номера, по которым есть блок и доступ разрешён."""
    if not has_permission(current_user, 'theory.view'):
        flash('У вас нет доступа к разделу «Теория».', 'warning')
        return redirect(url_for('main.dashboard'))

    blocks = TheoryBlock.query.order_by(TheoryBlock.task_number).all()
    block_by_number = {b.task_number: b for b in blocks}

    # Для ученика — фильтруем по StudentTheoryAccess
    allowed_numbers = set(THEORY_TASK_NUMBERS)
    if current_user.is_student():
        student = Student.query.filter_by(user_id=current_user.id).first()
        if student:
            allowed_numbers = _get_allowed_task_numbers_for_student(student.student_id)
        else:
            allowed_numbers = set()

    # Показываем только номера, по которым есть блок и доступ
    visible = [
        (num, block_by_number.get(num))
        for num in THEORY_TASK_NUMBERS
        if num in allowed_numbers and num in block_by_number
    ]

    return render_template(
        'theory/theory_index.html',
        visible=visible,
        active_page='theory',
    )


@theory_bp.route('/theory/<int:task_number>')
@login_required
def theory_view(task_number):
    """Просмотр одного блока теории по номеру задания."""
    if not has_permission(current_user, 'theory.view'):
        flash('У вас нет доступа к разделу «Теория».', 'warning')
        return redirect(url_for('main.dashboard'))

    if task_number not in THEORY_TASK_NUMBERS:
        abort(404)

    if current_user.is_student():
        student = Student.query.filter_by(user_id=current_user.id).first()
        if student and not _student_can_view_task_number(student.student_id, task_number):
            flash('Просмотр теории по этому заданию для вас закрыт.', 'warning')
            return redirect(url_for('theory.theory_index'))

    block = TheoryBlock.query.filter_by(task_number=task_number).first()
    if not block:
        flash('Теория по заданию {} ещё не добавлена.'.format(task_number), 'info')
        return redirect(url_for('theory.theory_index'))

    return render_template(
        'theory/theory_view.html',
        block=block,
        active_page='theory',
    )


# --- Управление для тьютора/админа ---

def _can_manage_theory():
    if not current_user.is_authenticated:
        return False
    return bool(has_permission(current_user, 'theory.manage'))


@theory_bp.route('/theory/manage')
@login_required
def manage_list():
    """Список всех блоков теории для редактирования."""
    if not _can_manage_theory():
        flash('Недостаточно прав для управления теорией.', 'danger')
        return redirect(url_for('main.dashboard'))

    blocks = TheoryBlock.query.order_by(TheoryBlock.task_number).all()
    block_by_number = {b.task_number: b for b in blocks}
    # Все номера 1–27: есть блок или пустой слот
    slots = [(num, block_by_number.get(num)) for num in THEORY_TASK_NUMBERS]

    return render_template(
        'theory/theory_manage_list.html',
        slots=slots,
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


@theory_bp.route('/theory/manage/new', methods=['GET', 'POST'])
@login_required
def manage_new():
    """Создание нового блока теории (выбор номера задания)."""
    if not _can_manage_theory():
        flash('Недостаточно прав.', 'danger')
        return redirect(url_for('main.dashboard'))

    existing_numbers = {b.task_number for b in TheoryBlock.query.all()}
    free_numbers = [n for n in THEORY_TASK_NUMBERS if n not in existing_numbers]

    if request.method == 'POST':
        logger.info('[theory/manage/new] POST: content_type=%s, form.keys=%s', request.content_type, list(request.form.keys()))
        raw_content = request.form.get('content')
        logger.info('[theory/manage/new] content: present=%s, type=%s, len=%s, preview=%s',
                    raw_content is not None, type(raw_content).__name__, len(raw_content) if raw_content else 0,
                    (raw_content[:120] + '...') if raw_content and len(raw_content) > 120 else (raw_content or ''))

        task_number = request.form.get('task_number', type=int)
        title = (request.form.get('title') or '').strip() or None
        content = (request.form.get('content') or '').strip() or None

        if task_number is None or task_number not in THEORY_TASK_NUMBERS:
            flash('Выберите номер задания от 1 до 27.', 'danger')
            return render_template('theory/theory_form.html', task_number=task_number, title=title, content=content, free_numbers=free_numbers, is_new=True)

        if TheoryBlock.query.filter_by(task_number=task_number).first():
            flash('Теория по заданию {} уже существует. Редактируйте её в списке.'.format(task_number), 'warning')
            return redirect(url_for('theory.manage_list'))

        block = TheoryBlock(
            task_number=task_number,
            title=title or 'Задание {}'.format(task_number),
            content=content,
            author_id=current_user.id,
        )
        db.session.add(block)
        db.session.commit()
        logger.info('[theory/manage/new] saved block_id=%s, content_len=%s', block.id, len(block.content or ''))
        flash('Блок теории по заданию {} создан.'.format(task_number), 'success')
        return redirect(url_for('theory.manage_list'))

    task_number_prefill = request.args.get('task_number', type=int)
    if task_number_prefill and task_number_prefill in THEORY_TASK_NUMBERS and task_number_prefill in free_numbers:
        pass
    else:
        task_number_prefill = None

    return render_template(
        'theory/theory_form.html',
        task_number=task_number_prefill,
        title='',
        content='',
        free_numbers=free_numbers,
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

    if request.method == 'POST':
        logger.info('[theory/manage/edit] POST block_id=%s, content_type=%s, form.keys=%s', block_id, request.content_type, list(request.form.keys()))
        raw_content = request.form.get('content')
        logger.info('[theory/manage/edit] content: present=%s, len=%s, preview=%s',
                    raw_content is not None, len(raw_content) if raw_content else 0,
                    (raw_content[:120] + '...') if raw_content and len(raw_content) > 120 else (raw_content or ''))

        block.title = (request.form.get('title') or '').strip() or None
        block.content = (request.form.get('content') or '').strip() or None
        db.session.commit()
        logger.info('[theory/manage/edit] saved block_id=%s, content_len=%s', block_id, len(block.content or ''))
        flash('Теория по заданию {} сохранена.'.format(block.task_number), 'success')
        return redirect(url_for('theory.manage_list'))

    content_for_template = block.content or ''
    logger.info('[theory/manage/edit] GET block_id=%s, content_len=%s, preview=%s', block_id, len(content_for_template), (content_for_template[:80] + '...') if len(content_for_template) > 80 else content_for_template)
    return render_template(
        'theory/theory_form.html',
        block=block,
        task_number=block.task_number,
        title=block.title or '',
        content=content_for_template,
        free_numbers=[],
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
    db.session.delete(block)
    db.session.commit()
    flash('Блок теории по заданию {} удалён.'.format(num), 'success')
    return redirect(url_for('theory.manage_list'))


# --- Управление доступом учеников (запрет/разрешение по номерам) ---

@theory_bp.route('/theory/manage/access')
@login_required
def manage_access_index():
    """Список учеников для настройки доступа к теории по номерам."""
    if not _can_manage_theory():
        flash('Недостаточно прав.', 'danger')
        return redirect(url_for('main.dashboard'))

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
        active_page='theory_manage',
    )


@theory_bp.route('/theory/manage/access/<int:student_id>', methods=['GET', 'POST'])
@login_required
def manage_access_student(student_id):
    """Включение/выключение просмотра теории по каждому номеру задания для ученика."""
    if not _can_manage_theory():
        flash('Недостаточно прав.', 'danger')
        return redirect(url_for('main.dashboard'))

    from app.auth.rbac_utils import get_user_scope
    student = Student.query.get_or_404(student_id)
    scope = get_user_scope(current_user)
    if not scope.get('can_see_all'):
        sid_list = scope.get('student_ids') or []
        if student.student_id not in sid_list:
            flash('Нет доступа к этому ученику.', 'danger')
            return redirect(url_for('theory.manage_access_index'))

    # Текущие правила: task_number -> can_view
    access_list = StudentTheoryAccess.query.filter_by(student_id=student_id).all()
    access_by_number = {a.task_number: a.can_view for a in access_list}

    if request.method == 'POST':
        # Чекбокс "разрешён" = on. Снят = запретить. Храним только запреты; при разрешении запись удаляем.
        for num in THEORY_TASK_NUMBERS:
            key = 'allow_{}'.format(num)
            can_view = request.form.get(key) == 'on'
            existing = StudentTheoryAccess.query.filter_by(student_id=student_id, task_number=num).first()
            if can_view:
                if existing:
                    db.session.delete(existing)
            else:
                if existing:
                    existing.can_view = False
                    existing.updated_at = moscow_now()
                else:
                    db.session.add(StudentTheoryAccess(student_id=student_id, task_number=num, can_view=False))
        db.session.commit()
        flash('Доступ к теории для {} сохранён.'.format(student.name or 'ученика'), 'success')
        return redirect(url_for('theory.manage_access_student', student_id=student_id))

    return render_template(
        'theory/theory_access_student.html',
        student=student,
        task_numbers=THEORY_TASK_NUMBERS,
        access_by_number=access_by_number,
        active_page='theory_manage',
    )
