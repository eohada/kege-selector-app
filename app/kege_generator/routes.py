"""
Маршруты генератора КЕГЭ
"""
import logging
import os
from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from sqlalchemy import or_, func

from app.kege_generator import kege_generator_bp
from app.kege_generator.forms import TaskSelectionForm, ResetForm, TaskSearchForm
from app.models import Lesson, Tasks, LessonTask, StudentTaskSeen, UsageHistory, db
from app.models import TaskTemplate, TemplateTask
from app.auth.rbac_utils import has_permission
from core.selector_logic import (
    get_unique_tasks, record_usage, record_skipped, record_blacklist,
    reset_history, reset_skipped, reset_blacklist,
    get_accepted_tasks, get_skipped_tasks, get_next_unique_task
)
from core.audit_logger import audit_logger
from app.notifications.service import enqueue_assignment_notification

logger = logging.getLogger(__name__)

# Базовая директория проекта
base_dir = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
db_path = os.path.join(base_dir, 'data', 'keg_tasks.db')


def _require_kege_generator_access() -> None:
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


@kege_generator_bp.route('/kege-generator', methods=['GET', 'POST'])
@kege_generator_bp.route('/kege-generator/<int:lesson_id>', methods=['GET', 'POST'])
@login_required
def kege_generator(lesson_id=None):
    """Генератор заданий КЕГЭ"""
    _require_kege_generator_access()
    lesson = None
    student = None
    # Получаем lesson_id из query-параметров, если не передан в пути
    if lesson_id is None:
        lesson_id = request.args.get('lesson_id', type=int)
    
    # Получаем assignment_type и template_id из запроса (всегда, независимо от lesson_id)
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

    selection_form = TaskSelectionForm()
    reset_form = ResetForm()
    search_form = TaskSearchForm()

    try:
        available_types = db.session.query(Tasks.task_number).distinct().order_by(Tasks.task_number).all()
        choices = [(t[0], f'Задание {t[0]}') for t in available_types]

        if not choices:
            flash('База данных пуста! Запустите парсер для заполнения: python scraper/playwright_parser.py', 'warning')
            choices = [(i, f'Задание {i} (не загружено)') for i in range(1, 28)]

        selection_form.task_type.choices = choices
        reset_form.task_type_reset.choices = [('all', 'Всех заданий')] + choices

    except Exception as e:
        flash(f'Ошибка! База данных ({db_path}) не найдена или пуста. Запустите парсер (scraper) для ее заполнения. Ошибка: {str(e)}', 'danger')
        choices = [(i, f'Задание {i} (не загружено)') for i in range(1, 28)]
        selection_form.task_type.choices = choices
        reset_form.task_type_reset.choices = [('all', 'Всех заданий')] + choices

    if seed_task_id:
        try:
            seed_task = Tasks.query.filter_by(task_id=seed_task_id).first()
            if seed_task:
                # Предвыбираем номер задания в селекте
                selection_form.task_type.data = seed_task.task_number
        except Exception as e:
            logger.warning(f"Не удалось загрузить seed_task_id={seed_task_id}: {e}")
            seed_task = None

    # Новый UX: генератор работает в одном окне и выдаёт задания по одному через JSON API.
    # Старый режим подборки оставлен в /results (можно использовать прямым URL).

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

        return redirect(url_for('kege_generator.kege_generator', lesson_id=lesson_id, assignment_type=assignment_type) if lesson_id else url_for('kege_generator.kege_generator', assignment_type=assignment_type))
    
    # Обработчик поиска задания по уникальному ID
    if search_form.search_submit.data and search_form.validate_on_submit():
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

                if lesson_id:
                    lesson = Lesson.query.get(lesson_id)
                    if not lesson:
                        flash('Урок не найден.', 'danger')
                        return redirect(url_for('kege_generator.kege_generator', assignment_type=assignment_type))

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
                        return redirect(url_for('kege_generator.kege_generator', lesson_id=lesson_id, assignment_type=assignment_type))

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
                    flash(f'Задание #{task.task_id} добавлено в поток. Дальше можно продолжать по номеру {task.task_number}.', 'success')
                return redirect(url_for('kege_generator.kege_generator', **redirect_url_params))
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
    
    return render_template('kege_generator.html',
                           selection_form=selection_form,
                           reset_form=reset_form,
                           search_form=search_form,
                           lesson=lesson,
                           student=student,
                           lesson_id=lesson_id,
                           assignment_type=assignment_type,
                           template_id=template_id,
                           seed_task=seed_task,
                           seed_task_payload=_task_to_payload(seed_task) if seed_task else None)


def _lesson_tag(lesson_id: int, assignment_type: str) -> str:
    return f"lesson:{lesson_id}:{assignment_type}"


def _task_to_payload(task: Tasks):
    if not task:
        return None
    return {
        'task_id': task.task_id,
        'task_number': task.task_number,
        'site_task_id': task.site_task_id,
        'source_url': task.source_url,
        'content_html': task.content_html,
        'answer': task.answer,
        'attached_files': task.attached_files,
    }


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


@kege_generator_bp.route('/kege-generator/stream/start', methods=['POST'])
@login_required
def generator_stream_start():
    """Старт нового 'по одному заданию' потока."""
    _require_kege_generator_access()
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

    tag = _lesson_tag(lesson_id, assignment_type) if lesson_id else None
    task = get_next_unique_task(task_type, use_skipped=use_skipped, student_id=student_id, lesson_tag=tag)

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
            'has_task': bool(task),
        }
    )

    if not task:
        return jsonify({'success': True, 'done': True, 'task': None}), 200

    return jsonify({'success': True, 'done': False, 'task': _task_to_payload(task)}), 200


@kege_generator_bp.route('/kege-generator/stream/act', methods=['POST'])
@login_required
def generator_stream_act():
    """Совершить действие над текущим заданием и получить следующее."""
    _require_kege_generator_access()
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

    # 1) Выполняем действие
    message = None
    try:
        if action == 'accept':
            # Сначала — в шаблон (если есть), как и в старом режиме
            if template_id:
                template = TaskTemplate.query.get(template_id)
                if not template:
                    return jsonify({'success': False, 'error': 'Шаблон не найден'}), 404
                max_order = db.session.query(db.func.max(TemplateTask.order)).filter_by(template_id=template_id).scalar() or 0
                existing = TemplateTask.query.filter_by(template_id=template_id, task_id=task_id).first()
                if not existing:
                    db.session.add(TemplateTask(template_id=template_id, task_id=task_id, order=max_order + 1))
                    db.session.commit()

            if lesson_id:
                lesson = Lesson.query.get(lesson_id)
                if not lesson:
                    return jsonify({'success': False, 'error': 'Урок не найден'}), 404
                existing = LessonTask.query.filter_by(lesson_id=lesson_id, task_id=task_id).first()
                added_count = 0
                added_task_ids = []
                if not existing:
                    db.session.add(LessonTask(lesson_id=lesson_id, task_id=task_id, assignment_type=assignment_type))
                    # record global anti-repeat (best-effort)
                    try:
                        if lesson.student_id:
                            db.session.add(StudentTaskSeen(student_id=lesson.student_id, task_id=task_id, source=f'lesson:{assignment_type}'))
                    except Exception:
                        pass
                    added_count = 1
                    added_task_ids = [task_id]
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

                db.session.commit()
                message = 'Задание добавлено в урок.'
            else:
                record_usage([task_id])
                message = 'Задание принято.'

        elif action == 'skip':
            if lesson_id:
                record_skipped([task_id], session_tag=_lesson_tag(lesson_id, assignment_type))
                message = 'Задание пропущено для этого урока.'
            else:
                record_skipped([task_id], session_tag=None)
                message = 'Задание пропущено.'

        elif action == 'blacklist':
            reason = (data.get('reason') or 'Добавлено пользователем').strip()[:500]
            record_blacklist([task_id], reason=reason)
            message = 'Задание добавлено в чёрный список.'

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

    # 2) Выдаём следующее
    student_id = None
    if lesson_id:
        lesson = Lesson.query.options(db.joinedload(Lesson.student)).get(lesson_id)
        student_id = lesson.student_id if lesson else None

    tag = _lesson_tag(lesson_id, assignment_type) if lesson_id else None
    next_task = get_next_unique_task(task_type, use_skipped=use_skipped, student_id=student_id, lesson_tag=tag)

    return jsonify({
        'success': True,
        'message': message,
        'done': not bool(next_task),
        'task': _task_to_payload(next_task),
    }), 200

@kege_generator_bp.route('/results')
@login_required
def generate_results():
    """Legacy URL (generator era). Kept as alias to /assignments/generator/results."""
    return redirect(url_for('assignments.assignments_generator_results', **request.args))

@kege_generator_bp.route('/action', methods=['POST'])
@login_required
def task_action():
    """Действия с заданиями (принять, пропустить, в черный список)"""
    _require_kege_generator_access()
    try:
        data = request.get_json(silent=True) or {}  # Безопасно парсим JSON (не падаем на пустом/битом теле)
        if not isinstance(data, dict):  # Проверяем, что пришёл объект
            return jsonify({'success': False, 'error': 'Некорректный формат запроса'}), 400  # Возвращаем 400 вместо 500
        logger.info(f"📥 Получен запрос task_action: {data}")
        
        action = data.get('action')
        task_ids = data.get('task_ids', [])  # Сырые ID заданий (могут прийти строками)
        lesson_id = data.get('lesson_id')  # Сырой ID урока (может прийти строкой)
        template_id = data.get('template_id')  # Получаем template_id из запроса

        # Нормализуем lesson_id в int, чтобы не ловить типовые ошибки БД (integer vs text)
        if lesson_id is not None and lesson_id != '':  # Если lesson_id вообще передали
            try:
                lesson_id = int(lesson_id)  # Приводим к int
            except (ValueError, TypeError):
                logger.warning(f"⚠️ Некорректный lesson_id: {lesson_id}, тип: {type(lesson_id)}")  # Логируем проблему
                lesson_id = None  # Сбрасываем lesson_id, чтобы ветки работали корректно
        else:
            lesson_id = None  # Явно нормализуем пустые значения в None

        # Нормализуем task_ids в список int, чтобы не ловить типовые ошибки БД (integer vs text)
        normalized_task_ids = []  # Сюда соберём только валидные int
        for raw_id in (task_ids or []):  # Проходим по входному списку (или пустому)
            try:
                normalized_task_ids.append(int(raw_id))  # Приводим к int (поддерживает строки "123")
            except (ValueError, TypeError):
                logger.warning(f"⚠️ Пропускаем некорректный task_id: {raw_id}, тип: {type(raw_id)}")  # Логируем мусор
        task_ids = normalized_task_ids  # Подменяем список на нормализованный
        
        # Преобразуем template_id в int, если он передан
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
            # Если есть template_id, добавляем задания в шаблон ПЕРЕД добавлением в урок
            if template_id:
                logger.info(f"🎯 Принятие заданий с template_id={template_id}, task_ids={task_ids}")
                try:
                    from app.models import TaskTemplate, TemplateTask
                    
                    template = TaskTemplate.query.get(template_id)
                    if not template:
                        logger.error(f"❌ Шаблон {template_id} не найден")
                        return jsonify({'success': False, 'error': 'Шаблон не найден'}), 404
                    
                    logger.info(f"✅ Шаблон найден: {template.name} (ID: {template_id})")
                    
                    # Получаем текущий максимальный порядок в шаблоне
                    max_order = db.session.query(db.func.max(TemplateTask.order)).filter_by(template_id=template_id).scalar() or 0
                    logger.info(f"📊 Текущий максимальный порядок в шаблоне: {max_order}")
                    
                    added_to_template = 0
                    skipped_tasks = []
                    for task_id in task_ids:
                        # Проверяем, нет ли уже этого задания в шаблоне
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
                        # Коммитим изменения в шаблон отдельно
                        db.session.commit()
                        logger.info(f"✅ Успешно добавлено {added_to_template} заданий в шаблон {template_id}")
                        
                        # Проверяем, что задания действительно сохранились
                        saved_count = TemplateTask.query.filter_by(template_id=template_id).count()
                        logger.info(f"🔍 Проверка: в шаблоне {template_id} теперь {saved_count} заданий")
                        
                        if skipped_tasks:
                            logger.info(f"⏭️ Пропущено заданий (уже были в шаблоне): {skipped_tasks}")
                    else:
                        logger.info(f"ℹ️ Все задания уже были в шаблоне {template_id}")
                except Exception as e:
                    db.session.rollback()
                    logger.error(f"❌ Ошибка при добавлении заданий в шаблон {template_id}: {e}", exc_info=True)
                    # Возвращаем ошибку, чтобы пользователь знал о проблеме
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
                        # record global anti-repeat (best-effort)
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
                    # Если есть template_id, сообщаем об этом
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

        # Если есть template_id, добавляем информацию о шаблоне в ответ
        response_data = {'success': True, 'message': message}
        if template_id:
            response_data['template_id'] = template_id
            # Получаем информацию о шаблоне для сообщения
            try:
                template = TaskTemplate.query.get(template_id)
                if template:
                    response_data['template_name'] = template.name
            except Exception as e:
                logger.warning(f"Не удалось получить информацию о шаблоне {template_id}: {e}")
        
        return jsonify(response_data)

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@kege_generator_bp.route('/accepted')
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

@kege_generator_bp.route('/accepted/clear', methods=['POST'])
@login_required
def clear_accepted():
    """Очистить принятые задания (UsageHistory)."""
    _require_kege_generator_access()

    raw = (request.form.get('task_type') or '').strip()
    assignment_type = (request.form.get('assignment_type') or 'homework').strip().lower()
    task_type = None
    if raw:
        try:
            task_type = int(raw)
        except Exception:
            task_type = None

    # Считаем сколько было (best-effort), чтобы дать полезный feedback
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

@kege_generator_bp.route('/skipped')
@login_required
def show_skipped():
    """Legacy URL (generator era). Kept as alias to /assignments/skipped."""
    task_type = request.args.get('task_type', type=int, default=None)
    return redirect(url_for('assignments.assignments_skipped', task_type=task_type))
