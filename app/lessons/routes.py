"""
Маршруты для управления уроками
"""
import logging
from flask import render_template, request, redirect, url_for, flash, jsonify, make_response, current_app  # current_app нужен для определения типа БД (Postgres)
from flask_login import login_required, current_user  # comment
from sqlalchemy import text  # text нужен для setval(pg_get_serial_sequence(...)) при сбитых sequences

from app.lessons import lessons_bp
from app.lessons.forms import LessonForm, ensure_introductory_without_homework
from app.lessons.utils import get_sorted_assignments, perform_auto_check, normalize_answer_value  # comment
from app.models import Lesson, LessonTask, Student, Tasks, db, moscow_now, MOSCOW_TZ, TOMSK_TZ
from core.audit_logger import audit_logger

logger = logging.getLogger(__name__)

@lessons_bp.route('/lesson/<int:lesson_id>/edit', methods=['GET', 'POST'])
@login_required
def lesson_edit(lesson_id):
    """Редактирование урока"""
    # Оптимизация: используем joinedload для избежания N+1 проблем
    lesson = Lesson.query.options(
        db.joinedload(Lesson.student),
        db.joinedload(Lesson.homework_tasks).joinedload(LessonTask.task)
    ).get_or_404(lesson_id)
    student = lesson.student
    form = LessonForm(obj=lesson)
    
    # При редактировании устанавливаем московский часовой пояс по умолчанию
    if request.method == 'GET':
        form.timezone.data = 'moscow'

    if form.validate_on_submit():
        ensure_introductory_without_homework(form)
        
        # Обрабатываем дату с учетом часового пояса
        lesson_date_local = form.lesson_date.data
        timezone = form.timezone.data
        
        # Преобразуем локальное время в нужный часовой пояс
        # Проверяем, что datetime naive (без timezone), иначе делаем его naive
        if lesson_date_local.tzinfo is not None:
            # Если уже есть timezone, убираем его и работаем с naive datetime
            lesson_date_local = lesson_date_local.replace(tzinfo=None)
        
        if timezone == 'tomsk':
            # Создаем timezone-aware datetime для томского времени
            lesson_date_local = lesson_date_local.replace(tzinfo=TOMSK_TZ)
            # Конвертируем в московское время для хранения в БД
            lesson_date_utc = lesson_date_local.astimezone(MOSCOW_TZ)
            logger.debug(f"Томское время: {lesson_date_local}, Московское время: {lesson_date_utc}")
        else:
            # Создаем timezone-aware datetime для московского времени
            lesson_date_local = lesson_date_local.replace(tzinfo=MOSCOW_TZ)
            lesson_date_utc = lesson_date_local
        
        # Убираем timezone перед сохранением в БД (SQLAlchemy сохранит как naive)
        # lesson_date в БД хранится как naive datetime в московском времени
        lesson_date_utc = lesson_date_utc.replace(tzinfo=None) if lesson_date_utc.tzinfo else lesson_date_utc
        
        lesson.lesson_type = form.lesson_type.data
        lesson.lesson_date = lesson_date_utc
        lesson.duration = form.duration.data
        lesson.status = form.status.data
        lesson.topic = form.topic.data
        lesson.notes = form.notes.data
        lesson.homework = form.homework.data
        lesson.homework_status = form.homework_status.data
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise
        
        # Логируем обновление урока
        audit_logger.log(
            action='update_lesson',
            entity='Lesson',
            entity_id=lesson_id,
            status='success',
            metadata={
                'student_id': lesson.student_id,
                'student_name': lesson.student.name if lesson.student else None,
                'lesson_type': lesson.lesson_type,
                'status': lesson.status
            }
        )
        
        flash(f'Урок обновлен!', 'success')
        return redirect(url_for('students.student_profile', student_id=student.student_id))

    homework_tasks = get_sorted_assignments(lesson, 'homework')
    classwork_tasks = get_sorted_assignments(lesson, 'classwork')

    return render_template('lesson_form.html', form=form, student=student, title='Редактировать урок',
                         is_new=False, lesson=lesson, homework_tasks=homework_tasks, classwork_tasks=classwork_tasks)

@lessons_bp.route('/lesson/<int:lesson_id>/view')
@login_required
def lesson_view(lesson_id):
    """Просмотр урока (редирект на редактирование)"""
    return redirect(url_for('lessons.lesson_edit', lesson_id=lesson_id))

@lessons_bp.route('/lesson/<int:lesson_id>/delete', methods=['POST'])
@login_required
def lesson_delete(lesson_id):
    """Удаление урока"""
    lesson = Lesson.query.get_or_404(lesson_id)
    student_id = lesson.student_id
    student_name = lesson.student.name if lesson.student else None
    
    db.session.delete(lesson)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise
    
    # Логируем удаление урока
    audit_logger.log(
        action='delete_lesson',
        entity='Lesson',
        entity_id=lesson_id,
        status='success',
        metadata={
            'student_id': student_id,
            'student_name': student_name,
            'lesson_type': lesson.lesson_type,
            'lesson_date': str(lesson.lesson_date)
        }
    )
    
    flash('Урок удален.', 'success')
    return redirect(url_for('students.student_profile', student_id=student_id))

@lessons_bp.route('/lesson/<int:lesson_id>/start', methods=['POST'])
@login_required
def lesson_start(lesson_id):
    """Начало урока"""
    lesson = Lesson.query.get_or_404(lesson_id)
    lesson.status = 'in_progress'
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise
    flash(f'Урок начат! Используй зеленую панель сверху для управления уроком.', 'success')
    return redirect(url_for('students.student_profile', student_id=lesson.student_id))

@lessons_bp.route('/lesson/<int:lesson_id>/complete', methods=['POST'])
@login_required
def lesson_complete(lesson_id):
    """Завершение урока"""
    lesson = Lesson.query.get_or_404(lesson_id)

    lesson.topic = request.form.get('topic', lesson.topic)
    lesson.notes = request.form.get('notes', lesson.notes)
    lesson.homework = request.form.get('homework', lesson.homework)
    lesson.status = 'completed'

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise
    flash(f'Урок завершен и данные сохранены!', 'success')
    return redirect(url_for('students.student_profile', student_id=lesson.student_id))

@lessons_bp.route('/lesson/<int:lesson_id>/homework-tasks')
@login_required
def lesson_homework_view(lesson_id):
    """Просмотр домашних заданий урока"""
    # Оптимизация: используем joinedload для избежания N+1 проблем
    lesson = Lesson.query.options(
        db.joinedload(Lesson.student),
        db.joinedload(Lesson.homework_tasks).joinedload(LessonTask.task)
    ).get_or_404(lesson_id)
    student = lesson.student
    homework_tasks = get_sorted_assignments(lesson, 'homework')  # comment
    is_student_view = current_user.is_student()  # comment
    is_parent_view = current_user.is_parent()  # comment
    is_read_only = False  # comment
    if is_parent_view:  # comment
        is_read_only = True  # comment
    elif is_student_view:  # comment
        is_read_only = all(t.submission_correct is not None for t in homework_tasks)  # comment
    return render_template('lesson_homework.html',
                           lesson=lesson,
                           student=student,
                           homework_tasks=homework_tasks,
                           assignment_type='homework',  # comment
                           is_student_view=is_student_view,  # comment
                           is_parent_view=is_parent_view,  # comment
                           is_read_only=is_read_only)  # comment

@lessons_bp.route('/lesson/<int:lesson_id>/classwork-tasks')
@login_required
def lesson_classwork_view(lesson_id):
    """Просмотр заданий классной работы"""
    # Оптимизация: используем joinedload для избежания N+1 проблем
    lesson = Lesson.query.options(
        db.joinedload(Lesson.student),
        db.joinedload(Lesson.homework_tasks).joinedload(LessonTask.task)
    ).get_or_404(lesson_id)
    student = lesson.student
    classwork_tasks = get_sorted_assignments(lesson, 'classwork')  # comment
    is_student_view = current_user.is_student()  # comment
    is_parent_view = current_user.is_parent()  # comment
    is_read_only = False  # comment
    if is_parent_view:  # comment
        is_read_only = True  # comment
    elif is_student_view:  # comment
        is_read_only = all(t.submission_correct is not None for t in classwork_tasks)  # comment
    return render_template('lesson_homework.html',
                           lesson=lesson,
                           student=student,
                           homework_tasks=classwork_tasks,
                           assignment_type='classwork',  # comment
                           is_student_view=is_student_view,  # comment
                           is_parent_view=is_parent_view,  # comment
                           is_read_only=is_read_only)  # comment

@lessons_bp.route('/lesson/<int:lesson_id>/exam-tasks')
@login_required
def lesson_exam_view(lesson_id):
    """Просмотр заданий проверочной работы"""
    # Оптимизация: используем joinedload для избежания N+1 проблем
    lesson = Lesson.query.options(
        db.joinedload(Lesson.student),
        db.joinedload(Lesson.homework_tasks).joinedload(LessonTask.task)
    ).get_or_404(lesson_id)
    student = lesson.student
    exam_tasks = get_sorted_assignments(lesson, 'exam')  # comment
    is_student_view = current_user.is_student()  # comment
    is_parent_view = current_user.is_parent()  # comment
    is_read_only = False  # comment
    if is_parent_view:  # comment
        is_read_only = True  # comment
    elif is_student_view:  # comment
        is_read_only = all(t.submission_correct is not None for t in exam_tasks)  # comment
    return render_template('lesson_homework.html',
                           lesson=lesson,
                           student=student,
                           homework_tasks=exam_tasks,
                           assignment_type='exam',  # comment
                           is_student_view=is_student_view,  # comment
                           is_parent_view=is_parent_view,  # comment
                           is_read_only=is_read_only)  # comment


def _get_current_lesson_student(lesson):  # comment
    """Проверяем, что текущий пользователь - ученик этого урока"""  # comment
    if not current_user.is_student():  # comment
        return None  # comment
    if not current_user.email:  # comment
        return None  # comment
    student = Student.query.filter_by(email=current_user.email).first()  # comment
    if not student:  # comment
        return None  # comment
    if student.student_id != lesson.student_id:  # comment
        return None  # comment
    return student  # comment


def _save_student_submissions(lesson, assignment_type):  # comment
    """Сохраняем ответы ученика без автопроверки"""  # comment
    tasks = get_sorted_assignments(lesson, assignment_type)  # comment
    for task in tasks:  # comment
        field_name = f'submission_{task.lesson_task_id}'  # comment
        if field_name in request.form:  # comment
            value = request.form.get(field_name, '').strip()  # comment
            task.student_submission = value if value else None  # comment
    return tasks  # comment


def _submit_student_submissions(lesson, assignment_type):  # comment
    """Фиксируем ответы ученика и запускаем авто-проверку"""  # comment
    tasks = get_sorted_assignments(lesson, assignment_type)  # comment
    for task in tasks:  # comment
        field_name = f'submission_{task.lesson_task_id}'  # comment
        value = request.form.get(field_name, '').strip()  # comment
        task.student_submission = value if value else None  # comment
        expected = (task.student_answer if task.student_answer else (task.task.answer if task.task and task.task.answer else '')) or ''  # comment
        if not expected:  # comment
            task.submission_correct = False  # comment
            continue  # comment
        if not value:  # comment
            task.submission_correct = False  # comment
            continue  # comment
        normalized_value = normalize_answer_value(value)  # comment
        normalized_expected = normalize_answer_value(expected)  # comment
        task.submission_correct = normalized_value == normalized_expected and normalized_expected != ''  # comment
    if assignment_type == 'homework':  # comment
        lesson.homework_status = 'assigned_done'  # comment
    return tasks  # comment


@lessons_bp.route('/lesson/<int:lesson_id>/homework-tasks/student-save', methods=['POST'])  # comment
@login_required  # comment
def lesson_homework_student_save(lesson_id):  # comment
    """Сохранение ответов ученика (ДЗ)"""  # comment
    lesson = Lesson.query.get_or_404(lesson_id)  # comment
    if not _get_current_lesson_student(lesson):  # comment
        flash('Доступ запрещен', 'danger')  # comment
        return redirect(url_for('lessons.lesson_homework_view', lesson_id=lesson_id))  # comment
    _save_student_submissions(lesson, 'homework')  # comment
    db.session.commit()  # comment
    flash('Ответы сохранены', 'success')  # comment
    return redirect(url_for('lessons.lesson_homework_view', lesson_id=lesson_id))  # comment


@lessons_bp.route('/lesson/<int:lesson_id>/classwork-tasks/student-save', methods=['POST'])  # comment
@login_required  # comment
def lesson_classwork_student_save(lesson_id):  # comment
    """Сохранение ответов ученика (КР)"""  # comment
    lesson = Lesson.query.get_or_404(lesson_id)  # comment
    if not _get_current_lesson_student(lesson):  # comment
        flash('Доступ запрещен', 'danger')  # comment
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment
    _save_student_submissions(lesson, 'classwork')  # comment
    db.session.commit()  # comment
    flash('Ответы сохранены', 'success')  # comment
    return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment


@lessons_bp.route('/lesson/<int:lesson_id>/exam-tasks/student-save', methods=['POST'])  # comment
@login_required  # comment
def lesson_exam_student_save(lesson_id):  # comment
    """Сохранение ответов ученика (Проверочная)"""  # comment
    lesson = Lesson.query.get_or_404(lesson_id)  # comment
    if not _get_current_lesson_student(lesson):  # comment
        flash('Доступ запрещен', 'danger')  # comment
        return redirect(url_for('lessons.lesson_exam_view', lesson_id=lesson_id))  # comment
    _save_student_submissions(lesson, 'exam')  # comment
    db.session.commit()  # comment
    flash('Ответы сохранены', 'success')  # comment
    return redirect(url_for('lessons.lesson_exam_view', lesson_id=lesson_id))  # comment


@lessons_bp.route('/lesson/<int:lesson_id>/homework-tasks/student-submit', methods=['POST'])  # comment
@login_required  # comment
def lesson_homework_student_submit(lesson_id):  # comment
    """Сдача работы учеником (ДЗ)"""  # comment
    lesson = Lesson.query.get_or_404(lesson_id)  # comment
    if not _get_current_lesson_student(lesson):  # comment
        flash('Доступ запрещен', 'danger')  # comment
        return redirect(url_for('lessons.lesson_homework_view', lesson_id=lesson_id))  # comment
    _submit_student_submissions(lesson, 'homework')  # comment
    db.session.commit()  # comment
    flash('Работа сдана', 'success')  # comment
    return redirect(url_for('lessons.lesson_homework_view', lesson_id=lesson_id))  # comment


@lessons_bp.route('/lesson/<int:lesson_id>/classwork-tasks/student-submit', methods=['POST'])  # comment
@login_required  # comment
def lesson_classwork_student_submit(lesson_id):  # comment
    """Сдача работы учеником (КР)"""  # comment
    lesson = Lesson.query.get_or_404(lesson_id)  # comment
    if not _get_current_lesson_student(lesson):  # comment
        flash('Доступ запрещен', 'danger')  # comment
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment
    _submit_student_submissions(lesson, 'classwork')  # comment
    db.session.commit()  # comment
    flash('Работа сдана', 'success')  # comment
    return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment


@lessons_bp.route('/lesson/<int:lesson_id>/exam-tasks/student-submit', methods=['POST'])  # comment
@login_required  # comment
def lesson_exam_student_submit(lesson_id):  # comment
    """Сдача работы учеником (Проверочная)"""  # comment
    lesson = Lesson.query.get_or_404(lesson_id)  # comment
    if not _get_current_lesson_student(lesson):  # comment
        flash('Доступ запрещен', 'danger')  # comment
        return redirect(url_for('lessons.lesson_exam_view', lesson_id=lesson_id))  # comment
    _submit_student_submissions(lesson, 'exam')  # comment
    db.session.commit()  # comment
    flash('Работа сдана', 'success')  # comment
    return redirect(url_for('lessons.lesson_exam_view', lesson_id=lesson_id))  # comment

@lessons_bp.route('/lesson/<int:lesson_id>/homework-tasks/save', methods=['POST'])
@login_required
def lesson_homework_save(lesson_id):
    """Сохранение домашнего задания"""
    if current_user.is_student() or current_user.is_parent():  # comment
        flash('Доступ запрещен', 'danger')  # comment
        return redirect(url_for('lessons.lesson_homework_view', lesson_id=lesson_id))  # comment
    lesson = Lesson.query.get_or_404(lesson_id)
    homework_tasks = [ht for ht in lesson.homework_assignments]

    for hw_task in homework_tasks:
        answer_key = f'answer_{hw_task.lesson_task_id}'
        if answer_key in request.form:
            submitted_answer = request.form.get(answer_key).strip()
            hw_task.student_answer = submitted_answer if submitted_answer else None

    percent_value = request.form.get('homework_result_percent', '').strip()
    if percent_value:
        try:
            percent_int = max(0, min(100, int(percent_value)))
            lesson.homework_result_percent = percent_int
        except ValueError:
            flash('Процент выполнения должен быть числом от 0 до 100', 'warning')
    else:
        lesson.homework_result_percent = None

    result_notes = request.form.get('homework_result_notes', '').strip()
    lesson.homework_result_notes = result_notes or None

    if lesson.lesson_type == 'introductory':
        lesson.homework_status = 'not_assigned'
    elif lesson.homework_result_percent is not None or lesson.homework_result_notes:
        lesson.homework_status = 'assigned_done'
    elif homework_tasks:
        lesson.homework_status = 'assigned_not_done'
    else:
        lesson.homework_status = 'not_assigned'

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise
    
    # Логируем сохранение домашнего задания
    audit_logger.log(
        action='save_homework',
        entity='Lesson',
        entity_id=lesson_id,
        status='success',
        metadata={
            'student_id': lesson.student_id,
            'student_name': lesson.student.name,
            'homework_status': lesson.homework_status,
            'homework_result_percent': lesson.homework_result_percent,
            'tasks_count': len(homework_tasks)
        }
    )
    
    flash('Данные по ДЗ сохранены!', 'success')
    return redirect(url_for('lessons.lesson_homework_view', lesson_id=lesson_id))


@lessons_bp.route('/lesson/<int:lesson_id>/task/<int:lesson_task_id>/set-status', methods=['POST'])
@login_required
def lesson_task_set_status(lesson_id, lesson_task_id):
    """Установка статуса задания (правильно/неправильно/не решено)"""
    if current_user.is_student() or current_user.is_parent():  # comment
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403  # comment
    lesson = Lesson.query.get_or_404(lesson_id)
    lesson_task = LessonTask.query.filter_by(
        lesson_task_id=lesson_task_id,
        lesson_id=lesson_id
    ).first_or_404()
    
    # Получаем статус из запроса
    status = request.json.get('status') if request.is_json else request.form.get('status')
    
    # Преобразуем строковый статус в Boolean или None
    if status == 'correct':
        lesson_task.submission_correct = True
    elif status == 'incorrect':
        lesson_task.submission_correct = False
    elif status == 'none' or status is None:
        lesson_task.submission_correct = None
    else:
        return jsonify({'success': False, 'error': 'Неверный статус'}), 400
    
    try:
        db.session.commit()
        
        audit_logger.log(
            action='set_task_status',
            entity='LessonTask',
            entity_id=lesson_task_id,
            status='success',
            metadata={
                'lesson_id': lesson_id,
                'student_id': lesson.student_id,
                'task_status': status,
                'task_number': lesson_task.task.task_number if lesson_task.task else None
            }
        )
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({
                'success': True,
                'status': status,
                'submission_correct': lesson_task.submission_correct
            })
        
        flash('Статус задания обновлен!', 'success')
        return redirect(url_for('lessons.lesson_homework_view', lesson_id=lesson_id))
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error setting task status: {e}", exc_info=True)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({'success': False, 'error': 'Ошибка при сохранении статуса'}), 500
        flash('Ошибка при сохранении статуса.', 'error')
        return redirect(url_for('lessons.lesson_homework_view', lesson_id=lesson_id))

@lessons_bp.route('/lesson/<int:lesson_id>/homework-auto-check', methods=['POST'])
@login_required
def lesson_homework_auto_check(lesson_id):
    """Автопроверка домашнего задания"""
    if current_user.is_student() or current_user.is_parent():  # comment
        flash('Доступ запрещен', 'danger')  # comment
        return redirect(url_for('lessons.lesson_homework_view', lesson_id=lesson_id))  # comment
    lesson = Lesson.query.get_or_404(lesson_id)
    result = perform_auto_check(lesson, 'homework')
    
    # Если это AJAX-запрос, возвращаем JSON
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        if isinstance(result[0], dict) and 'error' in result[0]:
            return jsonify({'success': False, 'error': result[0]['error'], 'category': result[0].get('category', 'error')}), 400
        if result[0] is None:
            return jsonify({'success': False, 'error': 'Ошибка при выполнении автопроверки'}), 400
        
        correct_count, incorrect_count, percent, total_tasks = result

        lesson.homework_result_percent = percent
        summary = f"Автопроверка {moscow_now().strftime('%d.%m.%Y %H:%M')}: {correct_count}/{total_tasks} верных ({percent}%)."
        if lesson.homework_result_notes:
            lesson.homework_result_notes = lesson.homework_result_notes + "\n" + summary
        else:
            lesson.homework_result_notes = summary

        if lesson.lesson_type == 'introductory' or total_tasks == 0:
            lesson.homework_status = 'not_assigned'
        else:
            lesson.homework_status = 'assigned_done' if correct_count == total_tasks else 'assigned_not_done'

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise
        
        audit_logger.log(
            action='auto_check_homework',
            entity='Lesson',
            entity_id=lesson_id,
            status='success',
            metadata={
                'student_id': lesson.student_id,
                'student_name': lesson.student.name,
                'correct_count': correct_count,
                'total_tasks': total_tasks,
                'percent': percent
            }
        )
        
        message = f'Автопроверка завершена: {correct_count}/{total_tasks} верных ({percent}%).'
        return jsonify({
            'success': True,
            'message': message,
            'correct_count': correct_count,
            'total_tasks': total_tasks,
            'percent': percent
        })
    
    # Обычный POST-запрос (fallback)
    if isinstance(result[0], dict) and 'error' in result[0]:
        flash(result[0]['error'], result[0].get('category', 'error'))
        return redirect(url_for('lessons.lesson_homework_view', lesson_id=lesson_id))
    
    if result[0] is None:
        return redirect(url_for('lessons.lesson_homework_view', lesson_id=lesson_id))
    
    correct_count, incorrect_count, percent, total_tasks = result

    lesson.homework_result_percent = percent
    summary = f"Автопроверка {moscow_now().strftime('%d.%m.%Y %H:%M')}: {correct_count}/{total_tasks} верных ({percent}%)."
    if lesson.homework_result_notes:
        lesson.homework_result_notes = lesson.homework_result_notes + "\n" + summary
    else:
        lesson.homework_result_notes = summary

    if lesson.lesson_type == 'introductory' or total_tasks == 0:
        lesson.homework_status = 'not_assigned'
    else:
        lesson.homework_status = 'assigned_done' if correct_count == total_tasks else 'assigned_not_done'

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise
    
    audit_logger.log(
        action='auto_check_homework',
        entity='Lesson',
        entity_id=lesson_id,
        status='success',
        metadata={
            'student_id': lesson.student_id,
            'student_name': lesson.student.name,
            'correct_count': correct_count,
            'total_tasks': total_tasks,
            'percent': percent
        }
    )
    
    flash(f'Автопроверка завершена: {correct_count}/{total_tasks} верных ({percent}%).', 'success')
    return redirect(url_for('lessons.lesson_homework_view', lesson_id=lesson_id))

@lessons_bp.route('/lesson/<int:lesson_id>/classwork-auto-check', methods=['POST'])
@login_required
def lesson_classwork_auto_check(lesson_id):
    """Автопроверка классной работы"""
    if current_user.is_student() or current_user.is_parent():  # comment
        flash('Доступ запрещен', 'danger')  # comment
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment
    lesson = Lesson.query.get_or_404(lesson_id)
    result = perform_auto_check(lesson, 'classwork')
    
    # Если это AJAX-запрос, возвращаем JSON
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        if result[0] is None:
            return jsonify({'success': False, 'error': 'Ошибка при выполнении автопроверки'}), 400
        
        correct_count, incorrect_count, percent, total_tasks = result
        
        summary = f"Автопроверка классной работы {moscow_now().strftime('%d.%m.%Y %H:%M')}: {correct_count}/{total_tasks} верных ({percent}%)."
        if lesson.notes:
            lesson.notes = lesson.notes + "\n" + summary
        else:
            lesson.notes = summary
        
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise
        
        audit_logger.log(
            action='auto_check_classwork',
            entity='Lesson',
            entity_id=lesson_id,
            status='success',
            metadata={
                'student_id': lesson.student_id,
                'student_name': lesson.student.name,
                'correct_count': correct_count,
                'total_tasks': total_tasks,
                'percent': percent
            }
        )
        
        message = f'Автопроверка завершена: {correct_count}/{total_tasks} верных ({percent}%).'
        return jsonify({
            'success': True,
            'message': message,
            'correct_count': correct_count,
            'total_tasks': total_tasks,
            'percent': percent
        })
    
    # Обычный POST-запрос (fallback)
    if isinstance(result[0], dict) and 'error' in result[0]:
        flash(result[0]['error'], result[0].get('category', 'error'))
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))
    
    if result[0] is None:
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))
    
    correct_count, incorrect_count, percent, total_tasks = result
    
    summary = f"Автопроверка классной работы {moscow_now().strftime('%d.%m.%Y %H:%M')}: {correct_count}/{total_tasks} верных ({percent}%)."
    if lesson.notes:
        lesson.notes = lesson.notes + "\n" + summary
    else:
        lesson.notes = summary
    
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise
    
    audit_logger.log(
        action='auto_check_classwork',
        entity='Lesson',
        entity_id=lesson_id,
        status='success',
        metadata={
            'student_id': lesson.student_id,
            'student_name': lesson.student.name,
            'correct_count': correct_count,
            'total_tasks': total_tasks,
            'percent': percent
        }
    )
    
    flash(f'Автопроверка завершена: {correct_count}/{total_tasks} верных ({percent}%).', 'success')
    return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))

@lessons_bp.route('/lesson/<int:lesson_id>/exam-auto-check', methods=['POST'])
@login_required
def lesson_exam_auto_check(lesson_id):
    """Автопроверка проверочной работы"""
    if current_user.is_student() or current_user.is_parent():  # comment
        flash('Доступ запрещен', 'danger')  # comment
        return redirect(url_for('lessons.lesson_exam_view', lesson_id=lesson_id))  # comment
    lesson = Lesson.query.get_or_404(lesson_id)
    result = perform_auto_check(lesson, 'exam')
    
    # Если это AJAX-запрос, возвращаем JSON
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        if result[0] is None:
            return jsonify({'success': False, 'error': 'Ошибка при выполнении автопроверки'}), 400
        
        correct_count, incorrect_count, percent, total_tasks = result
        
        summary = f"Автопроверка проверочной {moscow_now().strftime('%d.%m.%Y %H:%M')}: {correct_count}/{total_tasks} верных ({percent}%). Вес ×2."
        if lesson.notes:
            lesson.notes = lesson.notes + "\n" + summary
        else:
            lesson.notes = summary
        
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise
        
        audit_logger.log(
            action='auto_check_exam',
            entity='Lesson',
            entity_id=lesson_id,
            status='success',
            metadata={
                'student_id': lesson.student_id,
                'student_name': lesson.student.name,
                'correct_count': correct_count,
                'total_tasks': total_tasks,
                'percent': percent,
                'weight': 2
            }
        )
        
        message = f'Автопроверка завершена: {correct_count}/{total_tasks} верных ({percent}%). Учтено с весом ×2.'
        return jsonify({
            'success': True,
            'message': message,
            'correct_count': correct_count,
            'total_tasks': total_tasks,
            'percent': percent
        })
    
    # Обычный POST-запрос (fallback)
    if isinstance(result[0], dict) and 'error' in result[0]:
        flash(result[0]['error'], result[0].get('category', 'error'))
        return redirect(url_for('lessons.lesson_exam_view', lesson_id=lesson_id))
    
    if result[0] is None:
        return redirect(url_for('lessons.lesson_exam_view', lesson_id=lesson_id))
    
    correct_count, incorrect_count, percent, total_tasks = result
    
    summary = f"Автопроверка проверочной {moscow_now().strftime('%d.%m.%Y %H:%M')}: {correct_count}/{total_tasks} верных ({percent}%). Вес ×2."
    if lesson.notes:
        lesson.notes = lesson.notes + "\n" + summary
    else:
        lesson.notes = summary
    
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise
    
    audit_logger.log(
        action='auto_check_exam',
        entity='Lesson',
        entity_id=lesson_id,
        status='success',
        metadata={
            'student_id': lesson.student_id,
            'student_name': lesson.student.name,
            'correct_count': correct_count,
            'total_tasks': total_tasks,
            'percent': percent,
            'weight': 2
        }
    )
    
    flash(f'Автопроверка завершена: {correct_count}/{total_tasks} верных ({percent}%). Учтено с весом ×2.', 'success')
    return redirect(url_for('lessons.lesson_exam_view', lesson_id=lesson_id))

@lessons_bp.route('/lesson/<int:lesson_id>/homework-tasks/<int:lesson_task_id>/delete', methods=['POST'])
@login_required
def lesson_homework_delete_task(lesson_id, lesson_task_id):
    """Удаление задания из урока"""
    if current_user.is_student() or current_user.is_parent():  # comment
        flash('Доступ запрещен', 'danger')  # comment
        return redirect(url_for('lessons.lesson_homework_view', lesson_id=lesson_id))  # comment
    lesson = Lesson.query.get_or_404(lesson_id)
    lesson_task = LessonTask.query.get_or_404(lesson_task_id)
    assignment_type = request.args.get('assignment_type', 'homework')

    if lesson_task.lesson_id != lesson_id:
        flash('Ошибка: задание не принадлежит этому уроку', 'danger')
        return redirect(url_for('lessons.lesson_homework_view', lesson_id=lesson_id))

    task_id = lesson_task.task_id
    
    db.session.delete(lesson_task)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise
    
    audit_logger.log(
        action='delete_homework_task',
        entity='LessonTask',
        entity_id=lesson_task_id,
        status='success',
        metadata={
            'lesson_id': lesson_id,
            'task_id': task_id,
            'assignment_type': assignment_type,
            'student_id': lesson.student_id,
            'student_name': lesson.student.name if lesson.student else None
        }
    )
    
    flash('Задание удалено', 'success')

    if assignment_type == 'classwork':
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))
    return redirect(url_for('lessons.lesson_homework_view', lesson_id=lesson_id))

@lessons_bp.route('/lesson/<int:lesson_id>/homework-not-assigned', methods=['POST'])
@login_required
def lesson_homework_not_assigned(lesson_id):
    """Отметка домашнего задания как не заданного"""
    if current_user.is_student() or current_user.is_parent():  # comment
        flash('Доступ запрещен', 'danger')  # comment
        return redirect(url_for('lessons.lesson_homework_view', lesson_id=lesson_id))  # comment
    lesson = Lesson.query.get_or_404(lesson_id)
    for hw_task in lesson.homework_assignments:
        db.session.delete(hw_task)
    lesson.homework_status = 'not_assigned'
    lesson.homework = None
    lesson.homework_result_percent = None
    lesson.homework_result_notes = None
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise
    flash('Домашнее задание отмечено как «не задано».', 'info')
    return redirect(url_for('students.student_profile', student_id=lesson.student_id))

@lessons_bp.route('/lesson/<int:lesson_id>/homework-export-md')
@login_required
def lesson_homework_export_md(lesson_id):
    """Экспорт домашнего задания в Markdown"""
    if current_user.is_student() or current_user.is_parent():  # comment
        flash('Доступ запрещен', 'danger')  # comment
        return redirect(url_for('lessons.lesson_homework_view', lesson_id=lesson_id))  # comment
    from app.lessons.export import lesson_export_md
    return lesson_export_md(lesson_id, 'homework')

@lessons_bp.route('/lesson/<int:lesson_id>/classwork-export-md')
@login_required
def lesson_classwork_export_md(lesson_id):
    """Экспорт классной работы в Markdown"""
    if current_user.is_student() or current_user.is_parent():  # comment
        flash('Доступ запрещен', 'danger')  # comment
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment
    from app.lessons.export import lesson_export_md
    return lesson_export_md(lesson_id, 'classwork')

@lessons_bp.route('/lesson/<int:lesson_id>/exam-export-md')
@login_required
def lesson_exam_export_md(lesson_id):
    """Экспорт проверочной работы в Markdown"""
    if current_user.is_student() or current_user.is_parent():  # comment
        flash('Доступ запрещен', 'danger')  # comment
        return redirect(url_for('lessons.lesson_exam_view', lesson_id=lesson_id))  # comment
    from app.lessons.export import lesson_export_md
    return lesson_export_md(lesson_id, 'exam')

@lessons_bp.route('/lesson/<int:lesson_id>/manual-create', methods=['GET', 'POST'])
@login_required
def lesson_manual_create(lesson_id):
    """Ручное создание заданий"""
    if current_user.is_student() or current_user.is_parent():  # comment
        flash('Доступ запрещен.', 'danger')  # comment
        return redirect(url_for('main.dashboard'))  # comment
        
    lesson = Lesson.query.get_or_404(lesson_id)
    assignment_type = request.args.get('type', 'homework')
    
    if request.method == 'POST':
        try:
            data = request.get_json()
            tasks_data = data.get('tasks', [])

            # Фикс для PostgreSQL: если sequence у Tasks.task_id сбит, ручное создание заданий падает на duplicate key
            try:  # Пытаемся выровнять sequence превентивно (без падения, если не Postgres)
                db_url = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')  # Берём URI базы
                is_pg = ('postgresql' in db_url) or ('postgres' in db_url)  # Проверяем, что это Postgres
                if is_pg:  # Выполняем только для Postgres
                    db.session.execute(text('SELECT setval(pg_get_serial_sequence(\'"Tasks"\', \'task_id\'), COALESCE((SELECT MAX("task_id") FROM "Tasks"), 0), true)'))  # Выравниваем sequence Tasks.task_id
                    db.session.commit()  # Коммитим фиксацию sequence
            except Exception:  # Если не удалось/не нужно — продолжаем без блокировки
                db.session.rollback()  # Откатываем на всякий случай
            
            count = 0
            for task_data in tasks_data:
                # Create Task
                new_task = Tasks(
                    task_number=int(task_data.get('number', 1)),
                    content_html=f'<div class="task-text">{task_data.get("content", "")}</div>',
                    answer=task_data.get('answer', ''),
                    site_task_id=None, # Indicates manual
                    source_url=None
                )
                db.session.add(new_task)
                db.session.flush() # Get task_id
                
                # Link to Lesson
                lesson_task = LessonTask(
                    lesson_id=lesson.lesson_id,
                    task_id=new_task.task_id,
                    assignment_type=assignment_type
                )
                db.session.add(lesson_task)
                count += 1
                
            db.session.commit()
            
            audit_logger.log(
                action='create_manual_tasks',
                entity='Lesson',
                entity_id=lesson_id,
                status='success',
                metadata={
                    'count': count,
                    'assignment_type': assignment_type
                }
            )
            
            return jsonify({'success': True, 'count': count})
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating manual tasks: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    return render_template('lesson_manual_create.html', lesson=lesson, assignment_type=assignment_type)
