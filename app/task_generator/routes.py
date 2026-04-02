"""
Маршруты генератора заданий (универсальный — ЕГЭ / ОГЭ)
"""
import json
import logging
import os
import re
import uuid
from flask import render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import or_, func, text, delete
from sqlalchemy.orm import joinedload

from app.task_generator import task_generator_bp
from app.task_generator.forms import TaskSelectionForm, ResetForm, TaskSearchForm
from app.models import (
    Lesson,
    Tasks,
    LessonTask,
    StudentTaskSeen,
    UsageHistory,
    db,
    TaskTemplate,
    TemplateTask,
    Course,
    CourseTaskTemplate,
    TaskSolution,
    SkippedTasks,
    BlacklistTasks,
    TaskReview,
    AssignmentTask,
    TrainerSession,
    TrainerLlmLog,
    AnalyticsEvent,
    task_topics,
)
from app.auth.rbac_utils import has_permission
from core.selector_logic import (
    get_unique_tasks, record_usage, record_skipped, record_blacklist,
    reset_history, reset_skipped, reset_blacklist,
    get_accepted_tasks, get_skipped_tasks, get_next_unique_task
)
from core.audit_logger import audit_logger
from app.notifications.service import enqueue_assignment_notification

logger = logging.getLogger(__name__)

base_dir = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
db_path = os.path.join(base_dir, 'data', 'keg_tasks.db')


def _task_generator_page_url(
    *,
    lesson_id=None,
    assignment_type='homework',
    template_id=None,
    exam_course_id=None,
    recipient_ids=None,
    bank_page=1,
    bank_per_page=25,
    bank_course_id=None,
    bank_task_number=None,
    bank_task_id=None,
    bank_only_manual=False,
    bank_open=False,
):
    """Единая точка сборки URL страницы генератора (поток + банк в одном месте)."""
    kwargs = {'assignment_type': assignment_type or 'homework'}
    if lesson_id is not None:
        kwargs['lesson_id'] = lesson_id
    if template_id is not None:
        kwargs['template_id'] = template_id
    if exam_course_id is not None:
        kwargs['exam_course_id'] = exam_course_id
    if recipient_ids:
        kwargs['recipient_ids'] = ','.join(str(x) for x in recipient_ids)
    kwargs['bank_page'] = max(1, int(bank_page or 1))
    if bank_per_page and int(bank_per_page) != 25:
        kwargs['bank_per_page'] = int(bank_per_page)
    if bank_course_id is not None:
        kwargs['bank_course_id'] = int(bank_course_id)
    if bank_task_number is not None:
        kwargs['bank_task_number'] = int(bank_task_number)
    if bank_task_id is not None:
        kwargs['bank_task_id'] = int(bank_task_id)
    if bank_only_manual:
        kwargs['bank_only_manual'] = 1
    if bank_open:
        kwargs['bank_open'] = 1
        kwargs['gen_tab'] = 'bank'
    return url_for('task_generator.task_generator', **kwargs)


def _require_task_generator_access() -> None:
    """
    Генератор — инструмент управления банком заданий.
    Должен быть недоступен ученикам/родителям (и всем без права task.manage).
    """
    try:
        if current_user and current_user.is_authenticated and has_permission(current_user, 'task.manage'):
            return
    except Exception:
        pass
    from flask import abort
    abort(403)


@task_generator_bp.route('/task-generator', methods=['GET', 'POST'])
@task_generator_bp.route('/task-generator/<int:lesson_id>', methods=['GET', 'POST'])
@login_required
def task_generator(lesson_id=None):
    """Генератор заданий (ЕГЭ / ОГЭ)"""
    _require_task_generator_access()
    lesson = None
    student = None
    if lesson_id is None:
        lesson_id = request.args.get('lesson_id', type=int)
    
    assignment_type = request.args.get('assignment_type') or request.form.get('assignment_type') or 'homework'
    assignment_type = assignment_type if assignment_type in ['homework', 'classwork', 'exam'] else 'homework'
    template_id = request.args.get('template_id', type=int)  # Получаем template_id из запроса
    seed_task_id = request.args.get('seed_task_id', type=int)
    seed_task = None
    
    if not lesson_id and assignment_type == 'classwork':
        assignment_type = 'homework'
    
    if lesson_id:
        lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)
        student = lesson.student

    exam_course_id = request.args.get('exam_course_id', type=int) or request.form.get('exam_course_id', type=int)
    if not exam_course_id:
        default_course = Course.query.filter_by(is_active=True).first()
        exam_course_id = default_course.id if default_course else None

    selection_form = TaskSelectionForm()
    reset_form = ResetForm()
    search_form = TaskSearchForm()

    try:
        if exam_course_id:
            templates = CourseTaskTemplate.query.filter_by(course_id=exam_course_id).order_by(CourseTaskTemplate.task_number).all()
            template_numbers = {t.task_number for t in templates}
            available_types = (
                db.session.query(Tasks.task_number).distinct()
                .filter(Tasks.course_id == exam_course_id)
                .order_by(Tasks.task_number).all()
            )
            choices = [(t[0], f'Задание {t[0]}') for t in available_types]
            missing = sorted(template_numbers - {t[0] for t in available_types})
            choices += [(n, f'Задание {n} (не загружено)') for n in missing]
            choices.sort(key=lambda x: x[0])
        else:
            available_types = db.session.query(Tasks.task_number).distinct().order_by(Tasks.task_number).all()
            choices = [(t[0], f'Задание {t[0]}') for t in available_types]

        if not choices:
            flash('База данных пуста! Запустите парсер для заполнения.', 'warning')
            choices = [(i, f'Задание {i} (не загружено)') for i in range(1, 28)]

        selection_form.task_type.choices = choices
        reset_form.task_type_reset.choices = [('all', 'Всех заданий')] + choices

    except Exception as e:
        flash(f'Ошибка загрузки типов заданий: {str(e)}', 'danger')
        choices = [(i, f'Задание {i}') for i in range(1, 28)]
        selection_form.task_type.choices = choices
        reset_form.task_type_reset.choices = [('all', 'Всех заданий')] + choices

    if seed_task_id:
        try:
            seed_task = Tasks.query.filter_by(task_id=seed_task_id).first()
            if seed_task:
                selection_form.task_type.data = seed_task.task_number
        except Exception as e:
            logger.warning(f"Не удалось загрузить seed_task_id={seed_task_id}: {e}")
            seed_task = None


    if reset_form.reset_submit.data and reset_form.validate_on_submit():
        task_type_to_reset = reset_form.task_type_reset.data
        reset_type = reset_form.reset_type.data

        task_type_int = None if task_type_to_reset == 'all' else int(task_type_to_reset)

        if reset_type == 'accepted':
            reset_history(task_type=task_type_int)
            audit_logger.log(
                action='reset_history',
                entity='Task',
                entity_id=None,
                status='success',
                metadata={'task_type': task_type_int}
            )
            flash('История принятых заданий сброшена.', 'success')
        elif reset_type == 'skipped':
            reset_skipped(task_type=task_type_int)
            audit_logger.log(
                action='reset_skipped',
                entity='Task',
                entity_id=None,
                status='success',
                metadata={'task_type': task_type_int}
            )
            flash('История пропущенных заданий сброшена.', 'success')
        elif reset_type == 'blacklist':
            reset_blacklist(task_type=task_type_int)
            audit_logger.log(
                action='reset_blacklist',
                entity='Task',
                entity_id=None,
                status='success',
                metadata={'task_type': task_type_int}
            )
            flash('Черный список очищен.', 'success')
        elif reset_type == 'all':
            reset_history(task_type=task_type_int)
            reset_skipped(task_type=task_type_int)
            reset_blacklist(task_type=task_type_int)
            audit_logger.log(
                action='reset_all_history',
                entity='Task',
                entity_id=None,
                status='success',
                metadata={'task_type': task_type_int}
            )
            flash('Вся история сброшена.', 'success')

        return redirect(url_for('task_generator.task_generator', lesson_id=lesson_id, assignment_type=assignment_type) if lesson_id else url_for('task_generator.task_generator', assignment_type=assignment_type))
    
    if search_form.search_submit.data and search_form.validate_on_submit():
        if not lesson_id:
            try:
                lesson_id_from_form = request.form.get('lesson_id')
                lesson_id = int(lesson_id_from_form) if lesson_id_from_form not in (None, '', False) else None
            except Exception:
                lesson_id = None
        task_id_str = search_form.task_id.data.strip()
        try:
            task_id_int = int(task_id_str)
            logger.info(f"Поиск задания с ID: {task_id_str}")
            
            task = Tasks.query.filter(Tasks.site_task_id == task_id_str).first()
            found_by_site_task_id = bool(task)
            
            if not task:
                task = Tasks.query.filter_by(task_id=task_id_int).first()
            
            if task:
                added_to_lesson = False
                added_to_template = False
                added_to_history = False

                if lesson_id:
                    lesson = Lesson.query.get(lesson_id)
                    if not lesson:
                        flash('Урок не найден.', 'danger')
                        return redirect(url_for('task_generator.task_generator', assignment_type=assignment_type))

                    try:
                        added_to_lesson = _attach_task_to_lesson(task.task_id, lesson, assignment_type)
                        if template_id:
                            added_to_template = _attach_task_to_template(task.task_id, template_id)

                        if added_to_lesson and lesson.student:
                            atype = (assignment_type or 'homework').strip().lower()
                            link_url = url_for(
                                'lessons.lesson_homework_view' if atype == 'homework' else (
                                    'lessons.lesson_classwork_view' if atype == 'classwork' else 'lessons.lesson_exam_view'
                                ),
                                lesson_id=lesson.lesson_id
                            )
                            enqueue_assignment_notification(
                                lesson=lesson,
                                assignment_type=atype,
                                task_ids=[task.task_id],
                                link_url=link_url,
                            )

                        db.session.commit()
                    except Exception as e:
                        db.session.rollback()
                        logger.error(f"Ошибка при добавлении задания по ID: {e}", exc_info=True)
                        flash('Ошибка при добавлении задания в урок.', 'danger')
                        return redirect(url_for('task_generator.task_generator', lesson_id=lesson_id, assignment_type=assignment_type))

                elif template_id:
                    try:
                        added_to_template = _attach_task_to_template(task.task_id, template_id)
                        db.session.commit()
                    except Exception as e:
                        db.session.rollback()
                        logger.error(f"Ошибка при добавлении задания в шаблон: {e}", exc_info=True)
                        flash('Ошибка при добавлении задания в шаблон.', 'danger')
                        return redirect(url_for('task_generator.task_generator', assignment_type=assignment_type, template_id=template_id))
                else:
                    try:
                        record_usage([task.task_id])
                        added_to_history = True
                    except Exception as e:
                        logger.error(f"Ошибка при добавлении задания в историю принятых: {e}", exc_info=True)
                        flash('Ошибка при сохранении задания.', 'danger')
                        return redirect(url_for('task_generator.task_generator', assignment_type=assignment_type))

                audit_logger.log(
                    action='search_and_add_task',
                    entity='Task',
                    entity_id=task.task_id,
                    status='success',
                    metadata={
                        'search_id': task_id_str,
                        'found_task_id': task.task_id,
                        'site_task_id': task.site_task_id,
                        'task_number': task.task_number,
                        'lesson_id': lesson_id,
                        'assignment_type': assignment_type,
                        'added_to_lesson': added_to_lesson,
                        'added_to_template': added_to_template,
                        'added_to_history': added_to_history,
                    }
                )
                redirect_url_params = {
                    'assignment_type': assignment_type,
                    'seed_task_id': task.task_id,
                }
                if lesson_id:
                    redirect_url_params['lesson_id'] = lesson_id
                if template_id:
                    redirect_url_params['template_id'] = template_id

                if lesson_id:
                    if added_to_lesson:
                        if added_to_template:
                            flash(f'Задание #{task.task_id} добавлено в урок и в шаблон. Номер задания: {task.task_number}.', 'success')
                        else:
                            flash(f'Задание #{task.task_id} добавлено в урок. Номер задания: {task.task_number}.', 'success')
                    else:
                        flash(f'Задание #{task.task_id} уже есть в уроке. Номер задания: {task.task_number}.', 'warning')
                else:
                    if added_to_template:
                        flash(f'Задание #{task.task_id} добавлено в шаблон. Номер задания: {task.task_number}.', 'success')
                    elif added_to_history:
                        flash(f'Задание #{task.task_id} добавлено в принятые. Номер задания: {task.task_number}.', 'success')
                    else:
                        flash(f'Задание #{task.task_id} добавлено в поток. Дальше можно продолжать по номеру {task.task_number}.', 'success')
                return redirect(url_for('task_generator.task_generator', **redirect_url_params))
            else:
                flash(f'Задание с ID {task_id_str} не найдено в базе данных.', 'warning')
        except ValueError:
            flash('Некорректный ID задания. Введите число (например, 23715, 3348).', 'danger')
        except Exception as e:
            logger.error(f"Ошибка при поиске задания {task_id_str}: {e}", exc_info=True)
            flash(f'Ошибка при поиске задания: {str(e)}', 'danger')
            audit_logger.log(
                action='search_and_add_task',
                entity='Task',
                entity_id=None,
                status='error',
                metadata={
                    'task_id': task_id_str,
                    'error': str(e)
                }
            )
    
    recipient_ids = []
    raw_sids = request.args.get('student_ids') or request.args.get('recipient_ids')
    if raw_sids:
        try:
            recipient_ids = [int(x.strip()) for x in str(raw_sids).split(',') if x.strip() and x.strip().isdigit()]
        except (TypeError, ValueError):
            recipient_ids = []

    all_courses = Course.query.filter_by(is_active=True).order_by(Course.title).all()
    active_course = Course.query.get(exam_course_id) if exam_course_id else None

    course_task_numbers = {}
    try:
        for c in all_courses:
            course_task_numbers[c.id] = [
                t.task_number
                for t in CourseTaskTemplate.query.filter_by(course_id=c.id)
                .order_by(CourseTaskTemplate.task_number).all()
            ]
    except Exception as e:
        logger.warning(f'course_task_numbers for generator: {e}')
        course_task_numbers = {}

    bank_page = max(1, request.args.get('bank_page', type=int) or 1)
    bank_per_page = min(100, max(10, request.args.get('bank_per_page', type=int) or 25))
    bank_filter_course_id = request.args.get('bank_course_id', type=int)
    bank_filter_task_number = request.args.get('bank_task_number', type=int)
    bank_filter_task_id = request.args.get('bank_task_id', type=int)
    bank_only_manual = request.args.get('bank_only_manual', type=int) == 1
    bank_open = request.args.get('bank_open', type=int) == 1
    bank_panel_open = bank_open or bool(
        bank_filter_course_id or bank_filter_task_number or bank_filter_task_id or bank_only_manual or bank_page > 1
    )
    gen_tab_arg = (request.args.get('gen_tab') or '').strip().lower()
    if gen_tab_arg in ('stream', 'manual', 'bank'):
        initial_gen_tab = gen_tab_arg
    else:
        initial_gen_tab = 'bank' if bank_panel_open else 'stream'

    bank_tasks = []
    bank_total = 0
    bank_pagination = []
    try:
        bq = Tasks.query.options(
            joinedload(Tasks.course),
            joinedload(Tasks.task_solution),
        )
        if bank_filter_course_id:
            bq = bq.filter(Tasks.course_id == bank_filter_course_id)
        if bank_filter_task_number:
            bq = bq.filter(Tasks.task_number == bank_filter_task_number)
        if bank_filter_task_id:
            bq = bq.filter(Tasks.task_id == bank_filter_task_id)
        if bank_only_manual:
            bq = bq.filter(Tasks.bank_origin == 'manual')
        bq = bq.order_by(Tasks.task_id.desc())
        bank_total = bq.count()
        bank_tasks = bq.offset((bank_page - 1) * bank_per_page).limit(bank_per_page).all()
        bank_pages_total = max(1, (bank_total + bank_per_page - 1) // bank_per_page)
        for p in range(1, bank_pages_total + 1):
            bank_pagination.append({
                'page': p,
                'url': _task_generator_page_url(
                    lesson_id=lesson_id,
                    assignment_type=assignment_type,
                    template_id=template_id,
                    exam_course_id=exam_course_id,
                    recipient_ids=recipient_ids,
                    bank_page=p,
                    bank_per_page=bank_per_page,
                    bank_course_id=bank_filter_course_id,
                    bank_task_number=bank_filter_task_number,
                    bank_task_id=bank_filter_task_id,
                    bank_only_manual=bank_only_manual,
                    bank_open=True,
                ),
                'current': p == bank_page,
            })
    except Exception as e:
        logger.warning(f'bank panel query failed (schema?): {e}')
        bank_tasks = []
        bank_total = 0
        bank_pagination = []

    return render_template('task_generator.html',
                           selection_form=selection_form,
                           reset_form=reset_form,
                           search_form=search_form,
                           lesson=lesson,
                           student=student,
                           lesson_id=lesson_id,
                           assignment_type=assignment_type,
                           template_id=template_id,
                           seed_task=seed_task,
                           seed_task_payload=_task_to_payload(seed_task) if seed_task else None,
                           generator_recipient_ids=recipient_ids,
                           exam_course_id=exam_course_id,
                           all_courses=all_courses,
                           active_course=active_course,
                           course_task_numbers=course_task_numbers,
                           bank_tasks=bank_tasks,
                           bank_total=bank_total,
                           bank_page=bank_page,
                           bank_per_page=bank_per_page,
                           bank_filter_course_id=bank_filter_course_id,
                           bank_filter_task_number=bank_filter_task_number,
                           bank_filter_task_id=bank_filter_task_id,
                           bank_only_manual=bank_only_manual,
                           bank_panel_open=bank_panel_open,
                           bank_pagination=bank_pagination,
                           initial_gen_tab=initial_gen_tab)


def _lesson_tag(lesson_id: int, assignment_type: str) -> str:
    return f"lesson:{lesson_id}:{assignment_type}"


def _get_triplet_task_ids(task: Tasks):
    """Для заданий 19–21 с task_group_id возвращает [task_id_19, task_id_20, task_id_21] по порядку."""
    if not task or not getattr(task, 'task_group_id', None):
        return None
    try:
        trio = Tasks.query.filter(
            Tasks.task_group_id == task.task_group_id,
            Tasks.task_number.in_([19, 20, 21])
        ).order_by(Tasks.task_number).all()
        if len(trio) != 3:
            return None
        return [t.task_id for t in trio]
    except Exception:
        return None


def _purge_task_dependencies(task_id: int) -> None:
    """
    Удаляет/отвязывает все ссылки на задание перед удалением строки Tasks.
    Вызывать внутри одной транзакции с последующим db.session.delete(task).
    """
    db.session.execute(delete(task_topics).where(task_topics.c.task_id == task_id))
    UsageHistory.query.filter_by(task_fk=task_id).delete(synchronize_session=False)
    SkippedTasks.query.filter_by(task_fk=task_id).delete(synchronize_session=False)
    BlacklistTasks.query.filter_by(task_fk=task_id).delete(synchronize_session=False)
    for lt in LessonTask.query.filter_by(task_id=task_id).all():
        db.session.delete(lt)
    TemplateTask.query.filter_by(task_id=task_id).delete(synchronize_session=False)
    for at in AssignmentTask.query.filter_by(task_id=task_id).all():
        db.session.delete(at)
    TaskReview.query.filter_by(task_id=task_id).delete(synchronize_session=False)
    TaskSolution.query.filter_by(task_id=task_id).delete(synchronize_session=False)
    StudentTaskSeen.query.filter_by(task_id=task_id).delete(synchronize_session=False)
    TrainerSession.query.filter_by(task_id=task_id).update(
        {'task_id': None}, synchronize_session=False
    )
    TrainerLlmLog.query.filter_by(task_id=task_id).update(
        {'task_id': None}, synchronize_session=False
    )
    AnalyticsEvent.query.filter_by(task_id=task_id).update(
        {'task_id': None}, synchronize_session=False
    )


def _task_to_payload(task: Tasks):
    if not task:
        return None
    payload = {
        'task_id': task.task_id,
        'task_number': task.task_number,
        'site_task_id': task.site_task_id,
        'source_url': task.source_url,
        'content_html': task.content_html,
        'answer': task.answer,
        'attached_files': task.attached_files,
        'bank_origin': task.bank_origin,
        'starter_code': task.starter_code,
    }
    triplet_ids = _get_triplet_task_ids(task)
    if triplet_ids:
        payload['is_triplet_19_21'] = True
        payload['triplet_task_ids'] = triplet_ids
        try:
            trio_tasks = Tasks.query.filter(Tasks.task_id.in_(triplet_ids)).order_by(Tasks.task_number).all()
            payload['triplet_answers'] = [t.answer or '' for t in trio_tasks]
        except Exception:
            payload['triplet_answers'] = [task.answer or '', '', '']
    return payload


def _attach_task_to_template(task_id: int, template_id: int | None) -> bool:
    """Добавить задачу в шаблон, если ее там нет."""
    if not template_id:
        return False
    template = TaskTemplate.query.get(template_id)
    if not template:
        return False
    existing = TemplateTask.query.filter_by(template_id=template_id, task_id=task_id).first()
    if existing:
        return False
    max_order = db.session.query(db.func.max(TemplateTask.order)).filter_by(template_id=template_id).scalar() or 0
    db.session.add(TemplateTask(template_id=template_id, task_id=task_id, order=max_order + 1))
    return True


def _attach_task_to_lesson(task_id: int, lesson: Lesson, assignment_type: str) -> bool:
    """Добавить задачу в урок, если ее там нет."""
    if not lesson:
        return False
    existing = LessonTask.query.filter_by(lesson_id=lesson.lesson_id, task_id=task_id).first()
    if existing:
        return False
    db.session.add(LessonTask(lesson_id=lesson.lesson_id, task_id=task_id, assignment_type=assignment_type))
    try:
        if lesson.student_id:
            db.session.add(StudentTaskSeen(student_id=lesson.student_id, task_id=task_id, source=f'lesson:{assignment_type}'))
    except Exception:
        pass
    if assignment_type == 'homework':
        lesson.homework_status = 'assigned_not_done' if lesson.lesson_type != 'introductory' else 'not_assigned'
        lesson.homework_result_percent = None
        lesson.homework_result_notes = None
    return True


@task_generator_bp.route('/task-generator/stream/start', methods=['POST'])
@login_required
def generator_stream_start():
    """Старт нового 'по одному заданию' потока."""
    _require_task_generator_access()
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'Некорректный формат запроса'}), 400

    try:
        task_type = int(data.get('task_type'))
    except Exception:
        return jsonify({'success': False, 'error': 'task_type обязателен'}), 400

    lesson_id = data.get('lesson_id')
    template_id = data.get('template_id')
    assignment_type = (data.get('assignment_type') or 'homework').strip()
    use_skipped = bool(data.get('use_skipped', False))

    try:
        exam_course_id = int(data.get('exam_course_id')) if data.get('exam_course_id') else None
    except (TypeError, ValueError):
        exam_course_id = None

    if assignment_type not in ['homework', 'classwork', 'exam']:
        assignment_type = 'homework'

    try:
        lesson_id = int(lesson_id) if lesson_id not in (None, '', False) else None
    except Exception:
        lesson_id = None

    try:
        template_id = int(template_id) if template_id not in (None, '', False) else None
    except Exception:
        template_id = None

    student_id = None
    if lesson_id:
        lesson = Lesson.query.options(db.joinedload(Lesson.student)).get(lesson_id)
        student_id = lesson.student_id if lesson else None

    recipient_ids = None
    raw_rids = data.get('recipient_ids') or data.get('recipientIds')
    if isinstance(raw_rids, list):
        try:
            recipient_ids = [int(x) for x in raw_rids if x is not None]
        except (TypeError, ValueError):
            recipient_ids = None

    tag = _lesson_tag(lesson_id, assignment_type) if lesson_id else None
    task = get_next_unique_task(task_type, use_skipped=use_skipped, student_id=student_id, lesson_tag=tag, recipient_ids=recipient_ids, course_id=exam_course_id)

    audit_logger.log(
        action='generator_stream_start',
        entity='Generator',
        entity_id=lesson_id,
        status='success' if task else 'warning',
        metadata={
            'task_type': task_type,
            'assignment_type': assignment_type,
            'lesson_id': lesson_id,
            'template_id': template_id,
            'use_skipped': use_skipped,
            'exam_course_id': exam_course_id,
            'has_task': bool(task),
        }
    )

    if not task:
        return jsonify({'success': True, 'done': True, 'task': None}), 200

    return jsonify({'success': True, 'done': False, 'task': _task_to_payload(task)}), 200


@task_generator_bp.route('/task-generator/stream/act', methods=['POST'])
@login_required
def generator_stream_act():
    """Совершить действие над текущим заданием и получить следующее."""
    _require_task_generator_access()
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'Некорректный формат запроса'}), 400

    action = (data.get('action') or '').strip()
    if action not in ('accept', 'skip', 'blacklist'):
        return jsonify({'success': False, 'error': 'Неизвестное действие'}), 400

    try:
        task_id = int(data.get('task_id'))
        task_type = int(data.get('task_type'))
    except Exception:
        return jsonify({'success': False, 'error': 'task_id и task_type обязательны'}), 400

    lesson_id = data.get('lesson_id')
    template_id = data.get('template_id')
    assignment_type = (data.get('assignment_type') or 'homework').strip()
    use_skipped = bool(data.get('use_skipped', False))

    try:
        stream_exam_course_id = int(data.get('exam_course_id')) if data.get('exam_course_id') else None
    except (TypeError, ValueError):
        stream_exam_course_id = None

    if assignment_type not in ['homework', 'classwork', 'exam']:
        assignment_type = 'homework'

    try:
        lesson_id = int(lesson_id) if lesson_id not in (None, '', False) else None
    except Exception:
        lesson_id = None

    try:
        template_id = int(template_id) if template_id not in (None, '', False) else None
    except Exception:
        template_id = None

    # Для заданий 19–21 тройкой: при действии используем все три task_id
    task_ids_for_action = [task_id]
    try:
        task_obj = Tasks.query.get(task_id)
        if task_obj:
            triplet_ids = _get_triplet_task_ids(task_obj)
            if triplet_ids:
                task_ids_for_action = triplet_ids
    except Exception:
        pass

    message = None
    try:
        if action == 'accept':
            if template_id:
                template = TaskTemplate.query.get(template_id)
                if not template:
                    return jsonify({'success': False, 'error': 'Шаблон не найден'}), 404
                max_order = db.session.query(db.func.max(TemplateTask.order)).filter_by(template_id=template_id).scalar() or 0
                for tid in task_ids_for_action:
                    existing = TemplateTask.query.filter_by(template_id=template_id, task_id=tid).first()
                    if not existing:
                        db.session.add(TemplateTask(template_id=template_id, task_id=tid, order=max_order + 1))
                        max_order += 1
                db.session.commit()

            if lesson_id:
                lesson = Lesson.query.get(lesson_id)
                if not lesson:
                    return jsonify({'success': False, 'error': 'Урок не найден'}), 404
                added_task_ids = []
                for tid in task_ids_for_action:
                    existing = LessonTask.query.filter_by(lesson_id=lesson_id, task_id=tid).first()
                    if not existing:
                        db.session.add(LessonTask(lesson_id=lesson_id, task_id=tid, assignment_type=assignment_type))
                        try:
                            if lesson.student_id:
                                db.session.add(StudentTaskSeen(student_id=lesson.student_id, task_id=tid, source=f'lesson:{assignment_type}'))
                        except Exception:
                            pass
                        added_task_ids.append(tid)
                if assignment_type == 'homework':
                    lesson.homework_status = 'assigned_not_done' if lesson.lesson_type != 'introductory' else 'not_assigned'
                    lesson.homework_result_percent = None
                    lesson.homework_result_notes = None

                if added_task_ids and lesson.student:
                    atype = (assignment_type or 'homework').strip().lower()
                    link_url = url_for(
                        'lessons.lesson_homework_view' if atype == 'homework' else (
                            'lessons.lesson_classwork_view' if atype == 'classwork' else 'lessons.lesson_exam_view'
                        ),
                        lesson_id=lesson.lesson_id
                    )
                    enqueue_assignment_notification(
                        lesson=lesson,
                        assignment_type=atype,
                        task_ids=added_task_ids,
                        link_url=link_url,
                    )

                db.session.commit()
                if added_task_ids:
                    try:
                        from app.lessons.lesson_socket import emit_lesson_tasks_updated
                        emit_lesson_tasks_updated(lesson_id, assignment_type or 'homework')
                    except Exception:
                        pass
                message = f"{'Задание' if len(added_task_ids) == 1 else 'Задания'} добавлено в урок." if added_task_ids else 'Задания уже в уроке.'
            else:
                record_usage(task_ids_for_action)
                message = 'Задание принято.' if len(task_ids_for_action) == 1 else 'Тройка заданий 19–21 принята.'

        elif action == 'skip':
            if lesson_id:
                record_skipped(task_ids_for_action, session_tag=_lesson_tag(lesson_id, assignment_type))
                message = 'Задание пропущено для этого урока.' if len(task_ids_for_action) == 1 else 'Тройка 19–21 пропущена для этого урока.'
            else:
                record_skipped(task_ids_for_action, session_tag=None)
                message = 'Задание пропущено.' if len(task_ids_for_action) == 1 else 'Тройка 19–21 пропущена.'

        elif action == 'blacklist':
            reason = (data.get('reason') or 'Добавлено пользователем').strip()[:500]
            record_blacklist(task_ids_for_action, reason=reason)
            message = 'Задание добавлено в чёрный список.' if len(task_ids_for_action) == 1 else 'Тройка 19–21 добавлена в чёрный список.'

    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(
            action='generator_stream_act',
            entity='Task',
            error=str(e),
            metadata={
                'task_id': task_id,
                'task_type': task_type,
                'lesson_id': lesson_id,
                'template_id': template_id,
                'assignment_type': assignment_type,
                'action_taken': action,
            }
        )
        return jsonify({'success': False, 'error': str(e)}), 500

    audit_logger.log(
        action=f'generator_stream_{action}',
        entity='Task',
        entity_id=task_id,
        status='success',
        metadata={
            'task_type': task_type,
            'lesson_id': lesson_id,
            'template_id': template_id,
            'assignment_type': assignment_type,
            'use_skipped': use_skipped,
        }
    )

    student_id = None
    if lesson_id:
        lesson = Lesson.query.options(db.joinedload(Lesson.student)).get(lesson_id)
        student_id = lesson.student_id if lesson else None

    recipient_ids = None
    raw_rids = data.get('recipient_ids') or data.get('recipientIds')
    if isinstance(raw_rids, list):
        try:
            recipient_ids = [int(x) for x in raw_rids if x is not None]
        except (TypeError, ValueError):
            recipient_ids = None

    tag = _lesson_tag(lesson_id, assignment_type) if lesson_id else None
    next_task = get_next_unique_task(task_type, use_skipped=use_skipped, student_id=student_id, lesson_tag=tag, recipient_ids=recipient_ids, course_id=stream_exam_course_id)

    return jsonify({
        'success': True,
        'message': message,
        'done': not bool(next_task),
        'task': _task_to_payload(next_task),
    }), 200


def _normalize_manual_content_html(raw: str) -> str:
    text = (raw or '').strip()
    if not text:
        return '<div class="task-text"></div>'
    if re.search(r'<[a-zA-Z!?][^>]*>', text):
        return text
    escape = (
        text.replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
    )
    return f'<div class="task-text">{escape}</div>'


def _parse_hints_payload(raw):
    if raw is None:
        return None
    if isinstance(raw, (list, dict)):
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        try:
            return json.loads(s)
        except Exception:
            return None
    return None


def _parse_difficulty_level(raw):
    if raw is None or raw == '':
        return None
    try:
        d = int(raw)
        if 1 <= d <= 10:
            return d
    except (TypeError, ValueError):
        pass
    return None


def _attached_files_list(task: Tasks) -> list:
    if not task.attached_files:
        return []
    try:
        data = json.loads(task.attached_files) if isinstance(task.attached_files, str) else task.attached_files
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _attached_files_append(task: Tasks, entry: dict) -> None:
    items = _attached_files_list(task)
    items.append(entry)
    task.attached_files = json.dumps(items, ensure_ascii=False)


def _fix_tasks_pk_sequence():
    """Выравнивание sequence Tasks.task_id в PostgreSQL после ручных вставок."""
    try:
        db_url = current_app.config.get('SQLALCHEMY_DATABASE_URI', '') or ''
        is_pg = ('postgresql' in db_url) or ('postgres' in db_url)
        if is_pg:
            db.session.execute(text(
                'SELECT setval(pg_get_serial_sequence(\'"Tasks"\', \'task_id\'), '
                'COALESCE((SELECT MAX("task_id") FROM "Tasks"), 0), true)'
            ))
            db.session.commit()
    except Exception:
        db.session.rollback()


@task_generator_bp.route('/task-generator/upload-image', methods=['POST'])
@login_required
def task_generator_upload_image():
    """Картинка для вставки в условие (возвращает URL под /static/...)."""
    _require_task_generator_access()
    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'success': False, 'error': 'Файл не выбран'}), 400
    try:
        from app.uploads.service import save_uploaded_file
        static_root = current_app.static_folder or os.path.join(current_app.root_path, 'static')
        upload_folder = os.path.join(static_root, 'uploads', 'task_bank', str(current_user.id))
        _orig, abs_path, _size = save_uploaded_file(
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
        logger.exception('task_generator_upload_image failed')
        return jsonify({'success': False, 'error': 'Ошибка загрузки'}), 500


@task_generator_bp.route('/task-generator/bank/<int:task_id>/attach', methods=['POST'])
@login_required
def task_generator_bank_attach(task_id: int):
    """Прикрепить файл к уже созданной задаче банка."""
    _require_task_generator_access()
    task = Tasks.query.get(task_id)
    if not task:
        return jsonify({'success': False, 'error': 'Задание не найдено'}), 404
    if (task.bank_origin or '').strip() != 'manual':
        return jsonify({'success': False, 'error': 'Вложения таким способом только для задач, созданных вручную в банке'}), 400
    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'success': False, 'error': 'Файл не выбран'}), 400
    try:
        from app.uploads.service import save_uploaded_file
        static_root = current_app.static_folder or os.path.join(current_app.root_path, 'static')
        upload_folder = os.path.join(static_root, 'uploads', 'task_bank', str(current_user.id), str(task_id))
        orig_name, abs_path, _size = save_uploaded_file(
            file=file,
            base_folder=upload_folder,
            allowed_exts={
                'pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'txt', 'doc', 'docx',
                'xls', 'xlsx', 'zip', 'rar', '7z', 'py', 'csv',
            },
            max_bytes=30 * 1024 * 1024,
        )
        rel = os.path.relpath(abs_path, static_root).replace('\\', '/')
        url = url_for('static', filename=rel)
        _attached_files_append(task, {'name': orig_name, 'url': url})
        db.session.commit()
        return jsonify({'success': True, 'name': orig_name, 'url': url})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        logger.exception('task_generator_bank_attach failed')
        return jsonify({'success': False, 'error': str(e)}), 500


@task_generator_bp.route('/task-generator/bank/create', methods=['POST'])
@login_required
def task_generator_bank_create():
    """Создать задание в банке вручную (JSON)."""
    _require_task_generator_access()
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'Ожидается JSON'}), 400

    try:
        course_id = int(data.get('exam_course_id') or data.get('course_id'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'exam_course_id обязателен'}), 400

    course = Course.query.filter_by(id=course_id, is_active=True).first()
    if not course:
        return jsonify({'success': False, 'error': 'Программа не найдена или неактивна'}), 404

    try:
        task_number = int(data.get('task_number'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'task_number обязателен'}), 400

    valid_numbers = {t.task_number for t in CourseTaskTemplate.query.filter_by(course_id=course_id).all()}
    if valid_numbers and task_number not in valid_numbers:
        return jsonify({'success': False, 'error': f'Номер {task_number} не входит в спецификацию выбранной программы'}), 400

    content_html = _normalize_manual_content_html(data.get('content_html') or data.get('content') or '')
    answer = (data.get('answer') or '').strip() or None
    solution_text = (data.get('solution') or '').strip()
    starter_code = (data.get('starter_code') or '').strip() or None
    difficulty_level = _parse_difficulty_level(data.get('difficulty_level'))
    hints = _parse_hints_payload(data.get('hints'))

    site_task_id = f'manual:{uuid.uuid4()}'

    _fix_tasks_pk_sequence()

    try:
        task = Tasks(
            course_id=course_id,
            task_number=task_number,
            site_task_id=site_task_id,
            source_url=None,
            content_html=content_html,
            answer=answer,
            attached_files=None,
            bank_origin='manual',
            starter_code=starter_code,
            difficulty_level=difficulty_level,
            hints=hints,
        )
        db.session.add(task)
        db.session.flush()

        if solution_text:
            sol = TaskSolution.query.filter_by(task_id=task.task_id).first()
            if sol:
                sol.solution_text = solution_text
                sol.source = 'manual'
                sol.needs_manual_review = False
            else:
                db.session.add(TaskSolution(
                    task_id=task.task_id,
                    solution_text=solution_text,
                    source='manual',
                    needs_manual_review=False,
                ))

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.exception('task_generator_bank_create failed')
        return jsonify({'success': False, 'error': str(e)}), 500

    audit_logger.log(
        action='bank_create_manual_task',
        entity='Task',
        entity_id=task.task_id,
        status='success',
        metadata={'course_id': course_id, 'task_number': task_number, 'site_task_id': site_task_id},
    )

    return jsonify({
        'success': True,
        'task_id': task.task_id,
        'task': _task_to_payload(task),
    }), 201


@task_generator_bp.route('/task-generator/bank/<int:task_id>/save', methods=['POST'])
@login_required
def task_generator_bank_save(task_id: int):
    """Обновить ответ и/или уровень сложности записи в банке (для преподавателей с task.manage)."""
    _require_task_generator_access()
    task = Tasks.query.get(task_id)
    if not task:
        return jsonify({'success': False, 'error': 'Задание не найдено'}), 404

    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'Ожидается JSON'}), 400

    if 'answer' not in data and 'difficulty_level' not in data:
        return jsonify({'success': False, 'error': 'Передайте поля answer и/или difficulty_level'}), 400

    try:
        if 'answer' in data:
            raw_ans = data.get('answer')
            if raw_ans is None:
                task.answer = None
            else:
                task.answer = str(raw_ans).strip() or None

        if 'difficulty_level' in data:
            raw_d = data.get('difficulty_level')
            if raw_d is None or raw_d == '':
                task.difficulty_level = None
            else:
                try:
                    d = int(raw_d)
                except (TypeError, ValueError):
                    return jsonify({'success': False, 'error': 'Сложность: целое число 1–10 или пусто'}), 400
                if not (1 <= d <= 10):
                    return jsonify({'success': False, 'error': 'Сложность от 1 до 10'}), 400
                task.difficulty_level = d

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.exception('task_generator_bank_save failed')
        return jsonify({'success': False, 'error': str(e)}), 500

    audit_logger.log(
        action='bank_update_task',
        entity='Task',
        entity_id=task.task_id,
        status='success',
        metadata={'updated': [k for k in ('answer', 'difficulty_level') if k in data]},
    )
    return jsonify({
        'success': True,
        'task_id': task.task_id,
        'answer': task.answer,
        'difficulty_level': task.difficulty_level,
    })


@task_generator_bp.route('/task-generator/bank/<int:task_id>/delete', methods=['POST'])
@login_required
def task_generator_bank_delete(task_id: int):
    """Полное удаление задания из таблицы Tasks (с очисткой зависимостей)."""
    _require_task_generator_access()
    data = request.get_json(silent=True) or {}
    try:
        confirm = int(data.get('confirm_task_id'))
    except (TypeError, ValueError):
        confirm = None
    if confirm != task_id:
        return jsonify({
            'success': False,
            'error': 'Подтвердите удаление: в теле запроса укажите confirm_task_id, совпадающий с ID в URL.',
        }), 400

    task = Tasks.query.get(task_id)
    if not task:
        return jsonify({'success': False, 'error': 'Задание не найдено'}), 404

    try:
        _purge_task_dependencies(task_id)
        db.session.delete(task)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.exception('task_generator_bank_delete failed')
        return jsonify({
            'success': False,
            'error': str(e) or 'Не удалось удалить задание (возможны связи в БД).',
        }), 500

    audit_logger.log(
        action='bank_delete_task',
        entity='Task',
        entity_id=task_id,
        status='success',
        metadata={},
    )
    return jsonify({'success': True, 'task_id': task_id})


@task_generator_bp.route('/task-generator/bank', methods=['GET'])
@login_required
def task_generator_bank():
    """Старый URL: переносим на страницу генератора с блоком банка (без отдельной страницы)."""
    _require_task_generator_access()
    rd = {'bank_open': 1}
    if request.args.get('course_id') not in (None, ''):
        try:
            rd['bank_course_id'] = int(request.args.get('course_id'))
        except (TypeError, ValueError):
            pass
    if request.args.get('task_number') not in (None, ''):
        try:
            rd['bank_task_number'] = int(request.args.get('task_number'))
        except (TypeError, ValueError):
            pass
    for _tid_key in ('bank_task_id', 'task_id'):
        if request.args.get(_tid_key) not in (None, ''):
            try:
                rd['bank_task_id'] = int(request.args.get(_tid_key))
                break
            except (TypeError, ValueError):
                pass
    if request.args.get('page') not in (None, ''):
        try:
            rd['bank_page'] = int(request.args.get('page'))
        except (TypeError, ValueError):
            pass
    if request.args.get('per_page') not in (None, ''):
        try:
            rd['bank_per_page'] = int(request.args.get('per_page'))
        except (TypeError, ValueError):
            pass
    if request.args.get('only_manual'):
        rd['bank_only_manual'] = 1
    return redirect(url_for('task_generator.task_generator', **rd))


@task_generator_bp.route('/results')
@login_required
def generate_results():
    """Legacy URL (generator era). Kept as alias to /assignments/generator/results."""
    return redirect(url_for('assignments.assignments_generator_results', **request.args))

@task_generator_bp.route('/action', methods=['POST'])
@login_required
def task_action():
    """Действия с заданиями (принять, пропустить, в черный список)"""
    _require_task_generator_access()
    try:
        data = request.get_json(silent=True) or {}  # Безопасно парсим JSON (не падаем на пустом/битом теле)
        if not isinstance(data, dict):  # Проверяем, что пришёл объект
            return jsonify({'success': False, 'error': 'Некорректный формат запроса'}), 400  # Возвращаем 400 вместо 500
        logger.info(f"📥 Получен запрос task_action: {data}")
        
        action = data.get('action')
        task_ids = data.get('task_ids', [])  # Сырые ID заданий (могут прийти строками)
        lesson_id = data.get('lesson_id')  # Сырой ID урока (может прийти строкой)
        template_id = data.get('template_id')  # Получаем template_id из запроса

        if lesson_id is not None and lesson_id != '':  # Если lesson_id вообще передали
            try:
                lesson_id = int(lesson_id)  # Приводим к int
            except (ValueError, TypeError):
                logger.warning(f"⚠️ Некорректный lesson_id: {lesson_id}, тип: {type(lesson_id)}")  # Логируем проблему
                lesson_id = None  # Сбрасываем lesson_id, чтобы ветки работали корректно
        else:
            lesson_id = None  # Явно нормализуем пустые значения в None

        normalized_task_ids = []  # Сюда соберём только валидные int
        for raw_id in (task_ids or []):  # Проходим по входному списку (или пустому)
            try:
                normalized_task_ids.append(int(raw_id))  # Приводим к int (поддерживает строки "123")
            except (ValueError, TypeError):
                logger.warning(f"⚠️ Пропускаем некорректный task_id: {raw_id}, тип: {type(raw_id)}")  # Логируем мусор
        task_ids = normalized_task_ids  # Подменяем список на нормализованный
        
        if template_id is not None:
            try:
                template_id = int(template_id)
            except (ValueError, TypeError):
                logger.warning(f"⚠️ Некорректный template_id: {template_id}, тип: {type(template_id)}")
                template_id = None
        
        logger.info(f"📋 Параметры запроса: action={action}, task_ids={task_ids}, lesson_id={lesson_id}, template_id={template_id} (тип: {type(template_id)})")

        if not action or not task_ids:
            logger.error(f"❌ Неверные параметры: action={action}, task_ids={task_ids}")
            return jsonify({'success': False, 'error': 'Неверные параметры'}), 400

        assignment_type = data.get('assignment_type', 'homework')
        assignment_type = assignment_type if assignment_type in ['homework', 'classwork', 'exam'] else 'homework'
        logger.info(f"📝 Тип задания: {assignment_type}")

        if action == 'accept':
            if template_id:
                logger.info(f"🎯 Принятие заданий с template_id={template_id}, task_ids={task_ids}")
                try:
                    from app.models import TaskTemplate, TemplateTask
                    
                    template = TaskTemplate.query.get(template_id)
                    if not template:
                        logger.error(f"❌ Шаблон {template_id} не найден")
                        return jsonify({'success': False, 'error': 'Шаблон не найден'}), 404
                    
                    logger.info(f"✅ Шаблон найден: {template.name} (ID: {template_id})")
                    
                    max_order = db.session.query(db.func.max(TemplateTask.order)).filter_by(template_id=template_id).scalar() or 0
                    logger.info(f"📊 Текущий максимальный порядок в шаблоне: {max_order}")
                    
                    added_to_template = 0
                    skipped_tasks = []
                    for task_id in task_ids:
                        existing = TemplateTask.query.filter_by(template_id=template_id, task_id=task_id).first()
                        if not existing:
                            max_order += 1
                            template_task = TemplateTask(
                                template_id=template_id,
                                task_id=task_id,
                                order=max_order
                            )
                            db.session.add(template_task)
                            added_to_template += 1
                            logger.info(f"➕ Добавлено задание {task_id} в шаблон {template_id} с порядком {max_order}")
                        else:
                            skipped_tasks.append(task_id)
                            logger.info(f"⏭️ Задание {task_id} уже есть в шаблоне {template_id}, пропускаем")
                    
                    if added_to_template > 0:
                        db.session.commit()
                        logger.info(f"✅ Успешно добавлено {added_to_template} заданий в шаблон {template_id}")
                        
                        saved_count = TemplateTask.query.filter_by(template_id=template_id).count()
                        logger.info(f"🔍 Проверка: в шаблоне {template_id} теперь {saved_count} заданий")
                        
                        if skipped_tasks:
                            logger.info(f"⏭️ Пропущено заданий (уже были в шаблоне): {skipped_tasks}")
                    else:
                        logger.info(f"ℹ️ Все задания уже были в шаблоне {template_id}")
                except Exception as e:
                    db.session.rollback()
                    logger.error(f"❌ Ошибка при добавлении заданий в шаблон {template_id}: {e}", exc_info=True)
                    return jsonify({'success': False, 'error': f'Ошибка при добавлении заданий в шаблон: {str(e)}'}), 500
            else:
                logger.info(f"ℹ️ Принятие заданий без template_id, task_ids={task_ids}")
            
            if lesson_id:
                lesson = Lesson.query.get(lesson_id)
                if not lesson:
                    return jsonify({'success': False, 'error': 'Урок не найден'}), 404

                added_count = 0
                added_task_ids = []
                for task_id in task_ids:
                    existing = LessonTask.query.filter_by(lesson_id=lesson_id, task_id=task_id).first()
                    if not existing:
                        lesson_task = LessonTask(lesson_id=lesson_id, task_id=task_id, assignment_type=assignment_type)
                        db.session.add(lesson_task)
                        added_count += 1
                        added_task_ids.append(task_id)
                        try:
                            if lesson.student_id:
                                db.session.add(StudentTaskSeen(student_id=lesson.student_id, task_id=task_id, source=f'lesson:{assignment_type}'))
                        except Exception:
                            pass
                if assignment_type == 'homework':
                    lesson.homework_status = 'assigned_not_done' if lesson.lesson_type != 'introductory' else 'not_assigned'
                    lesson.homework_result_percent = None
                    lesson.homework_result_notes = None
                if added_count > 0 and lesson.student:
                    atype = (assignment_type or 'homework').strip().lower()
                    link_url = url_for(
                        'lessons.lesson_homework_view' if atype == 'homework' else (
                            'lessons.lesson_classwork_view' if atype == 'classwork' else 'lessons.lesson_exam_view'
                        ),
                        lesson_id=lesson.lesson_id
                    )
                    enqueue_assignment_notification(
                        lesson=lesson,
                        assignment_type=atype,
                        task_ids=added_task_ids,
                        link_url=link_url,
                    )

                try:
                    db.session.commit()
                    try:
                        from app.lessons.lesson_socket import emit_lesson_tasks_updated
                        emit_lesson_tasks_updated(lesson_id, assignment_type or 'homework')
                    except Exception:
                        pass
                    audit_logger.log(
                        action='accept_tasks',
                        entity='Lesson',
                        entity_id=lesson_id,
                        status='success',
                        metadata={
                            'task_ids': task_ids,
                            'task_count': len(task_ids),
                            'assignment_type': assignment_type,
                            'student_id': lesson.student_id,
                            'student_name': lesson.student.name if lesson.student else None
                        }
                    )
                except Exception as e:
                    db.session.rollback()
                    audit_logger.log_error(
                        action='accept_tasks',
                        entity='Lesson',
                        entity_id=lesson_id,
                        error=str(e)
                    )
                    return jsonify({'success': False, 'error': f'Ошибка при сохранении: {str(e)}'}), 500

                if template_id:
                    message = f'{len(task_ids)} заданий добавлено в домашнее задание и в шаблон.'
                elif assignment_type == 'classwork':
                    message = f'{len(task_ids)} заданий добавлено в классную работу.'
                else:
                    message = f'{len(task_ids)} заданий добавлено в домашнее задание.'
            else:
                try:
                    record_usage(task_ids)
                    
                    audit_logger.log(
                        action='accept_tasks',
                        entity='Task',
                        entity_id=None,
                        status='success',
                        metadata={
                            'task_ids': task_ids,
                            'task_count': len(task_ids)
                        }
                    )
                except Exception as e:
                    audit_logger.log_error(
                        action='accept_tasks',
                        entity='Task',
                        error=str(e)
                    )
                    return jsonify({'success': False, 'error': f'Ошибка при записи: {str(e)}'}), 500
                message = f'{len(task_ids)} заданий принято.'
        elif action == 'skip':
            if lesson_id:
                lesson = Lesson.query.options(db.joinedload(Lesson.student)).get(lesson_id)
                audit_logger.log(
                    action='skip_tasks',
                    entity='Lesson',
                    entity_id=lesson_id,
                    status='success',
                    metadata={
                        'task_ids': task_ids,
                        'task_count': len(task_ids),
                        'assignment_type': assignment_type,
                        'student_id': lesson.student_id if lesson else None
                    }
                )
                if assignment_type == 'classwork':
                    message = f'{len(task_ids)} заданий пропущено в режиме классной работы.'
                else:
                    message = f'{len(task_ids)} заданий пропущено (только для этого урока).'
            else:
                record_skipped(task_ids)
                audit_logger.log(
                    action='skip_tasks',
                    entity='Task',
                    entity_id=None,
                    status='success',
                    metadata={
                        'task_ids': task_ids,
                        'task_count': len(task_ids)
                    }
                )
                message = f'{len(task_ids)} заданий пропущено.'
        elif action == 'blacklist':
            reason = data.get('reason', 'Добавлено пользователем')
            record_blacklist(task_ids, reason=reason)
            audit_logger.log(
                action='blacklist_tasks',
                entity='Task',
                entity_id=None,
                status='success',
                metadata={
                    'task_ids': task_ids,
                    'task_count': len(task_ids),
                    'reason': reason
                }
            )
            message = f'{len(task_ids)} заданий добавлено в черный список.'
        else:
            return jsonify({'success': False, 'error': 'Неизвестное действие'}), 400

        response_data = {'success': True, 'message': message}
        if template_id:
            response_data['template_id'] = template_id
            try:
                template = TaskTemplate.query.get(template_id)
                if template:
                    response_data['template_name'] = template.name
            except Exception as e:
                logger.warning(f"Не удалось получить информацию о шаблоне {template_id}: {e}")
        
        return jsonify(response_data)

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@task_generator_bp.route('/accepted')
@login_required
def show_accepted():
    """
    Legacy URL (generator era). Kept as alias.
    Новая точка входа: /assignments/accepted
    """
    task_type = request.args.get('task_type', type=int, default=None)
    assignment_type = (request.args.get('assignment_type') or 'homework').strip().lower()
    create = (request.args.get('create') or '').strip()
    return redirect(url_for('assignments.assignments_accepted', task_type=task_type, assignment_type=assignment_type, create=create))

@task_generator_bp.route('/accepted/clear', methods=['POST'])
@login_required
def clear_accepted():
    """Очистить принятые задания (UsageHistory)."""
    _require_task_generator_access()

    raw = (request.form.get('task_type') or '').strip()
    assignment_type = (request.form.get('assignment_type') or 'homework').strip().lower()
    task_type = None
    if raw:
        try:
            task_type = int(raw)
        except Exception:
            task_type = None

    deleted_count = None
    try:
        q = UsageHistory.query
        if task_type:
            q = q.join(Tasks, Tasks.task_id == UsageHistory.task_fk).filter(Tasks.task_number == task_type)
        deleted_count = q.count()
    except Exception:
        deleted_count = None

    try:
        reset_history(task_type=task_type)
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        flash(f'Не удалось очистить принятые задания: {e}', 'danger')
        return redirect(url_for('assignments.assignments_accepted', assignment_type=assignment_type, task_type=task_type))

    try:
        audit_logger.log(
            action='accepted_clear',
            entity='Task',
            entity_id=None,
            status='success',
            metadata={'task_type': task_type, 'deleted_count': deleted_count},
        )
    except Exception:
        pass

    if task_type:
        flash('Принятые задания этого типа очищены.', 'success')
    else:
        flash('Все принятые задания очищены.', 'success')

    return redirect(url_for('assignments.assignments_accepted', assignment_type=assignment_type, task_type=task_type))

@task_generator_bp.route('/skipped')
@login_required
def show_skipped():
    """Legacy URL (generator era). Kept as alias to /assignments/skipped."""
    task_type = request.args.get('task_type', type=int, default=None)
    return redirect(url_for('assignments.assignments_skipped', task_type=task_type))
