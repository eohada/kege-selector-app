"""
Маршруты теории по заданиям ЕГЭ: просмотр для учеников, CRUD для тьютора.
"""
import logging
from flask import render_template, request, redirect, url_for, flash, abort
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
        block.title = (request.form.get('title') or '').strip() or None
        block.content = (request.form.get('content') or '').strip() or None
        db.session.commit()
        flash('Теория по заданию {} сохранена.'.format(block.task_number), 'success')
        return redirect(url_for('theory.manage_list'))

    return render_template(
        'theory/theory_form.html',
        block=block,
        task_number=block.task_number,
        title=block.title or '',
        content=block.content or '',
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
