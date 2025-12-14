"""
Маршруты генератора КЕГЭ
"""
import logging
import os
from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required

from app.kege_generator import kege_generator_bp
from app.kege_generator.forms import TaskSelectionForm, ResetForm, TaskSearchForm
from app.models import Lesson, Tasks, LessonTask, db
from app.models import TaskTemplate, TemplateTask
from core.selector_logic import (
    get_unique_tasks, record_usage, record_skipped, record_blacklist,
    reset_history, reset_skipped, reset_blacklist,
    get_accepted_tasks, get_skipped_tasks
)
from core.audit_logger import audit_logger

logger = logging.getLogger(__name__)

# Базовая директория проекта
base_dir = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
db_path = os.path.join(base_dir, 'data', 'keg_tasks.db')

@kege_generator_bp.route('/kege-generator', methods=['GET', 'POST'])
@kege_generator_bp.route('/kege-generator/<int:lesson_id>', methods=['GET', 'POST'])
@login_required
def kege_generator(lesson_id=None):
    """Генератор заданий КЕГЭ"""
    lesson = None
    student = None
    # Получаем lesson_id из query-параметров, если не передан в пути
    if lesson_id is None:
        lesson_id = request.args.get('lesson_id', type=int)
        assignment_type = request.args.get('assignment_type') or request.form.get('assignment_type') or 'homework'
        assignment_type = assignment_type if assignment_type in ['homework', 'classwork', 'exam'] else 'homework'
        template_id = request.args.get('template_id', type=int)  # Получаем template_id из запроса
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

    if selection_form.submit.data and selection_form.validate_on_submit():
        task_type = selection_form.task_type.data
        limit_count = selection_form.limit_count.data
        use_skipped = selection_form.use_skipped.data
        
        audit_logger.log(
            action='request_task_generation',
            entity='Generator',
            entity_id=lesson_id,
            status='success',
            metadata={
                'task_type': task_type,
                'limit_count': limit_count,
                'use_skipped': use_skipped,
                'assignment_type': assignment_type,
                'student_id': lesson.student_id if lesson_id and lesson else None,
                'student_name': lesson.student.name if lesson_id and lesson else None
            }
        )

        if lesson_id:
            redirect_params = {'task_type': task_type, 'limit_count': limit_count, 'use_skipped': use_skipped, 'lesson_id': lesson_id, 'assignment_type': assignment_type}
            if template_id:
                redirect_params['template_id'] = template_id
            return redirect(url_for('kege_generator.generate_results', **redirect_params))
        else:
            redirect_params = {'task_type': task_type, 'limit_count': limit_count, 'use_skipped': use_skipped, 'assignment_type': assignment_type}
            if template_id:
                redirect_params['template_id'] = template_id
            return redirect(url_for('kege_generator.generate_results', **redirect_params))

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
                        'assignment_type': assignment_type
                    }
                )
                redirect_url_params = {
                    'task_type': task.task_number,
                    'limit_count': 1,
                    'use_skipped': False,
                    'assignment_type': assignment_type,
                    'search_task_id': task.task_id
                }
                if lesson_id:
                    redirect_url_params['lesson_id'] = lesson_id
                if template_id:
                    redirect_url_params['template_id'] = template_id
                
                return redirect(url_for('kege_generator.generate_results', **redirect_url_params))
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
                           template_id=template_id)

@kege_generator_bp.route('/results')
@login_required
def generate_results():
    """Результаты генерации заданий"""
    try:
        task_type = request.args.get('task_type', type=int)
        limit_count = request.args.get('limit_count', type=int)
        use_skipped = request.args.get('use_skipped', 'false').lower() == 'true'
        lesson_id = request.args.get('lesson_id', type=int)
        assignment_type = request.args.get('assignment_type', default='homework')
        search_task_id = request.args.get('search_task_id', type=int)
        template_id = request.args.get('template_id', type=int)  # Получаем template_id из запроса
        
        # Валидация assignment_type
        if assignment_type not in ['homework', 'classwork', 'exam']:
            assignment_type = 'homework'
            logger.warning(f"Некорректный assignment_type, установлен 'homework'")
        
        # Валидация обязательных параметров
        if not task_type or not limit_count:
            logger.error(f"Отсутствуют обязательные параметры: task_type={task_type}, limit_count={limit_count}")
            flash('Не указаны тип задания или количество заданий.', 'danger')
            if lesson_id:
                return redirect(url_for('kege_generator.kege_generator', lesson_id=lesson_id, assignment_type=assignment_type))
            return redirect(url_for('kege_generator.kege_generator', assignment_type=assignment_type))
        
        logger.info(f"generate_results вызван с параметрами: task_type={task_type}, limit_count={limit_count}, search_task_id={search_task_id}, lesson_id={lesson_id}, assignment_type={assignment_type}, template_id={template_id}")
    except Exception as e:
        logger.error(f"Ошибка при получении параметров запроса: {e}", exc_info=True)
        flash('Неверные параметры запроса.', 'danger')
        # Получаем assignment_type из запроса для редиректа
        assignment_type = request.args.get('assignment_type', 'homework')
        if lesson_id:
            return redirect(url_for('kege_generator.kege_generator', lesson_id=lesson_id, assignment_type=assignment_type))
        return redirect(url_for('kege_generator.kege_generator', assignment_type=assignment_type))

    lesson = None
    student = None
    student_id = None
    if lesson_id:
        try:
            lesson = Lesson.query.get_or_404(lesson_id)
            if lesson:
                student = lesson.student
                if student:
                    student_id = student.student_id
        except Exception as e:
            logger.error(f"Error getting lesson {lesson_id}: {e}")
            flash('Ошибка при получении урока', 'error')
            return redirect(url_for('kege_generator.kege_generator', assignment_type=assignment_type))

    try:
        if search_task_id:
            task = Tasks.query.filter_by(task_id=search_task_id).first()
            if task:
                tasks = [task]
                task_type = task.task_number
            else:
                logger.error(f"✗ Задание с search_task_id={search_task_id} не найдено в базе данных!")
                flash(f'Задание с ID {search_task_id} не найдено.', 'warning')
                tasks = []
        else:
            tasks = get_unique_tasks(task_type, limit_count, use_skipped=use_skipped, student_id=student_id)
    except Exception as e:
        logger.error(f"Error getting unique tasks: {e}", exc_info=True)
        flash(f'Ошибка при генерации заданий: {str(e)}', 'error')
        if lesson_id:
            return redirect(url_for('kege_generator.kege_generator', lesson_id=lesson_id, assignment_type=assignment_type))
        return redirect(url_for('kege_generator.kege_generator', assignment_type=assignment_type))
    
    try:
        audit_logger.log(
            action='generate_tasks',
            entity='Generator',
            entity_id=lesson_id,
            status='success' if tasks else 'warning',
            metadata={
                'task_type': task_type,
                'limit_count': limit_count,
                'use_skipped': use_skipped,
                'tasks_generated': len(tasks) if tasks else 0,
                'assignment_type': assignment_type,
                'student_id': student_id,
                'student_name': student.name if student and hasattr(student, 'name') else None
            }
        )
    except Exception as e:
        logger.error(f"Error logging task generation: {e}", exc_info=True)

    if not tasks:
        if use_skipped:
            flash(f'Задания типа {task_type} закончились! Все доступные задания (включая пропущенные) были использованы.', 'warning')
        else:
            flash(f'Задания типа {task_type} закончились! Попробуйте включить пропущенные задания или сбросьте историю.', 'warning')
        # Сохраняем assignment_type при редиректе
        if lesson_id:
            return redirect(url_for('kege_generator.kege_generator', lesson_id=lesson_id, assignment_type=assignment_type))
        return redirect(url_for('kege_generator.kege_generator', assignment_type=assignment_type))

    return render_template('results.html',
                           tasks=tasks,
                           task_type=task_type,
                           lesson=lesson,
                           student=student,
                           lesson_id=lesson_id,
                           assignment_type=assignment_type,
                           template_id=template_id)

@kege_generator_bp.route('/action', methods=['POST'])
@login_required
def task_action():
    """Действия с заданиями (принять, пропустить, в черный список)"""
    try:
        data = request.get_json()
        logger.info(f"📥 Получен запрос task_action: {data}")
        
        action = data.get('action')
        task_ids = data.get('task_ids', [])
        lesson_id = data.get('lesson_id')
        template_id = data.get('template_id')  # Получаем template_id из запроса
        
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

                for task_id in task_ids:
                    existing = LessonTask.query.filter_by(lesson_id=lesson_id, task_id=task_id).first()
                    if not existing:
                        lesson_task = LessonTask(lesson_id=lesson_id, task_id=task_id, assignment_type=assignment_type)
                        db.session.add(lesson_task)
                if assignment_type == 'homework':
                    lesson.homework_status = 'assigned_not_done' if lesson.lesson_type != 'introductory' else 'not_assigned'
                    lesson.homework_result_percent = None
                    lesson.homework_result_notes = None
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
    """Показать принятые задания"""
    try:
        task_type = request.args.get('task_type', type=int, default=None)

        accepted_tasks = get_accepted_tasks(task_type=task_type)

        if not accepted_tasks:
            message = f'Нет принятых заданий типа {task_type}.' if task_type else 'Нет принятых заданий.'
            flash(message, 'info')
            return redirect(url_for('kege_generator.kege_generator'))

        return render_template('accepted.html', tasks=accepted_tasks, task_type=task_type)

    except Exception as e:
        flash(f'Ошибка: {e}', 'danger')
        return redirect(url_for('kege_generator.kege_generator'))

@kege_generator_bp.route('/skipped')
@login_required
def show_skipped():
    """Показать пропущенные задания"""
    try:
        task_type = request.args.get('task_type', type=int, default=None)

        skipped_tasks = get_skipped_tasks(task_type=task_type)

        if not skipped_tasks:
            message = f'Нет пропущенных заданий типа {task_type}.' if task_type else 'Нет пропущенных заданий.'
            flash(message, 'info')
            return redirect(url_for('kege_generator.kege_generator'))

        return render_template('skipped.html', tasks=skipped_tasks, task_type=task_type)

    except Exception as e:
        flash(f'Ошибка: {e}', 'danger')
        return redirect(url_for('kege_generator.kege_generator'))
