"""
Маршруты для управления студентами
"""
import json
import logging  # Логирование для отладки и прод-логов
from flask import render_template, request, redirect, url_for, flash, jsonify, current_app  # current_app нужен для определения типа БД (Postgres)
from flask_login import login_required
from sqlalchemy import text  # text нужен для выполнения SQL setval(pg_get_serial_sequence(...)) при сбитых sequences
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.students import students_bp
from app.students.forms import StudentForm, normalize_school_class
from app.students.utils import get_sorted_assignments
from app.students.stats_service import StatsService
from app.lessons.forms import LessonForm, ensure_introductory_without_homework
from app.models import Student, StudentTaskStatistics, Lesson, LessonTask, db, moscow_now, MOSCOW_TZ, TOMSK_TZ, Submission, Assignment
from app.models import User, FamilyTie
from app.utils.student_id_manager import assign_platform_id_if_needed
from core.audit_logger import audit_logger
from flask_login import current_user
from app.utils.db_migrations import ensure_schema_columns

logger = logging.getLogger(__name__)

@students_bp.route('/students')
@login_required
def students_list():
    """Список всех студентов (активных и архивных)"""
    active_students = Student.query.filter_by(is_active=True).order_by(Student.name).all()
    archived_students = Student.query.filter_by(is_active=False).order_by(Student.name).all()
    return render_template('students_list.html',
                         active_students=active_students,
                         archived_students=archived_students)

@students_bp.route('/student/new', methods=['GET', 'POST'])
@login_required
def student_new():
    """Создание нового студента"""
    form = StudentForm()

    if form.validate_on_submit():
        try:
            platform_id = form.platform_id.data.strip() if form.platform_id.data else None
            if platform_id:
                existing_student = Student.query.filter_by(platform_id=platform_id).first()
                if existing_student:
                    flash(f'Ученик с ID "{platform_id}" уже существует! (Ученик: {existing_student.name})', 'error')
                    return redirect(url_for('students.student_new'))

            school_class_value = normalize_school_class(form.school_class.data)
            goal_text_value = form.goal_text.data.strip() if (form.goal_text.data and form.goal_text.data.strip()) else None
            programming_language_value = form.programming_language.data.strip() if (form.programming_language.data and form.programming_language.data.strip()) else None
            
            student = Student(
                name=form.name.data,
                platform_id=platform_id,
                target_score=form.target_score.data,
                deadline=form.deadline.data,
                diagnostic_level=form.diagnostic_level.data,
                preferences=form.preferences.data,
                strengths=form.strengths.data,
                weaknesses=form.weaknesses.data,
                overall_rating=form.overall_rating.data,
                description=form.description.data,
                notes=form.notes.data,
                category=form.category.data if form.category.data else None,
                school_class=school_class_value,
                goal_text=goal_text_value,
                programming_language=programming_language_value
            )
            
            # Автоматически присваиваем трехзначный идентификатор, если не указан
            if not platform_id:
                assign_platform_id_if_needed(student)
            
            db.session.add(student)
            db.session.commit()
            
            # Логируем создание ученика
            try:
                audit_logger.log(
                    action='create_student',
                    status='success',
                    metadata={
                        'name': student.name,
                        'platform_id': student.platform_id,
                        'category': student.category,
                        'school_class': student.school_class,
                        'goal_text': student.goal_text,
                        'programming_language': student.programming_language
                    }
                )
            except Exception as log_err:
                logger.warning(f"Ошибка при логировании создания ученика: {log_err}")
            
            flash(f'Ученик {student.name} успешно добавлен!', 'success')
            return redirect(url_for('main.dashboard'))
        except Exception as e:
            db.session.rollback()
            logger.error(f'Ошибка при добавлении ученика: {e}', exc_info=True)
            
            # Логируем ошибку
            try:
                audit_logger.log_error(
                    action='create_student',
                    entity='Student',
                    error=str(e),
                    metadata={'form_data': {k: str(v) for k, v in form.data.items() if k != 'csrf_token'}}
                )
            except Exception as log_error:
                logger.error(f'Ошибка при логировании: {log_error}')
            
            flash(f'Ошибка при добавлении ученика: {str(e)}', 'error')
            return redirect(url_for('students.student_new'))

    # Логируем попытку отправки формы для отладки, если это POST запрос
    if request.method == 'POST' and not form.validate_on_submit():
        logger.warning(f'Ошибки валидации формы при создании ученика: {form.errors}')

    return render_template('student_form.html', form=form, title='Добавить ученика', is_new=True)

@students_bp.route('/student/<int:student_id>')
@login_required
def student_profile(student_id):
    """Профиль студента с уроками"""
    try:
        from app.auth.rbac_utils import get_user_scope
        
        # КРИТИЧЕСКАЯ ОПТИМИЗАЦИЯ: загружаем уроки отдельным запросом с joinedload для homework_tasks
        try:
            student = Student.query.get_or_404(student_id)
        except Exception as e:
            logger.error(f"Error loading student {student_id}: {e}", exc_info=True)
            flash('Ошибка при загрузке профиля ученика.', 'danger')
            return redirect(url_for('main.dashboard'))
        
        # Проверка доступа через data scoping
        try:
            # Ученику всегда разрешаем смотреть СВОЙ профиль (по email), даже если scope пустой/не настроен
            if current_user.is_student():
                me_email = (current_user.email or '').strip().lower()
                st_email = (student.email or '').strip().lower() if student.email else ''
                if me_email and st_email and me_email == st_email:
                    scope = {'can_see_all': False, 'student_ids': [current_user.id]}
                else:
                    scope = get_user_scope(current_user)
            else:
                scope = get_user_scope(current_user)
            if not scope['can_see_all']:
                # Проверяем, есть ли доступ к этому ученику
                if student.email:
                    try:
                        student_user = User.query.filter_by(email=student.email, role='student').first()
                        if student_user:
                            if student_user.id not in scope['student_ids']:
                                flash('У вас нет доступа к этому ученику.', 'danger')
                                return redirect(url_for('main.dashboard'))
                    except Exception as e:
                        logger.warning(f"Error checking student access via email: {e}")
                        # Если не можем проверить через email, проверяем через scope
                        if not scope['student_ids']:
                            flash('У вас нет доступа к этому ученику.', 'danger')
                            return redirect(url_for('main.dashboard'))
                else:
                    # Если у Student нет email, проверяем через Enrollment/FamilyTie напрямую
                    # Но это сложнее, пока просто блокируем
                    if not scope['student_ids']:
                        flash('У вас нет доступа к этому ученику.', 'danger')
                        return redirect(url_for('main.dashboard'))
        except Exception as e:
            logger.error(f"Error checking access scope: {e}", exc_info=True)
            # Если не можем проверить доступ, блокируем
            flash('Ошибка при проверке доступа.', 'danger')
            return redirect(url_for('main.dashboard'))
        
        now = moscow_now()
        
        # Загружаем активные задания (новая система LMS)
        active_submissions = []
        try:
            active_submissions = Submission.query.filter(
                Submission.student_id == student_id,
                Submission.status.in_(['ASSIGNED', 'IN_PROGRESS', 'RETURNED'])
            ).options(
                db.joinedload(Submission.assignment)
            ).order_by(Submission.assigned_at.desc()).all()
        except Exception as e:
            logger.error(f"Error loading active submissions: {e}")
        
        # Загружаем уроки с предзагрузкой homework_tasks и task для каждого homework_task
        # Robust fetch with retry for missing columns
        all_lessons = []
        max_retries = 2
        for attempt in range(max_retries):
            try:
                all_lessons = Lesson.query.filter_by(student_id=student_id).options(
                    db.joinedload(Lesson.homework_tasks).joinedload(LessonTask.task)
                ).order_by(Lesson.lesson_date.desc()).all()
                break # Success
            except (OperationalError, ProgrammingError) as e:
                db.session.rollback()
                if attempt < max_retries - 1 and ('column' in str(e).lower() or 'does not exist' in str(e).lower()):
                    logger.warning(f"Database schema issue detected ({e}). Attempting auto-fix...")
                    try:
                        ensure_schema_columns(current_app)
                        logger.info("Schema fix applied. Retrying query...")
                        continue
                    except Exception as fix_err:
                        logger.error(f"Failed to auto-fix schema: {fix_err}")
                        all_lessons = []
                        break
                else:
                    logger.error(f"Error loading lessons for student {student_id} (attempt {attempt+1}): {e}", exc_info=True)
                    all_lessons = []
                    break
        
        # Разделяем уроки на категории для "Актуальные уроки"
        try:
            completed_lessons = [l for l in all_lessons if l.status == 'completed']
            planned_lessons = [l for l in all_lessons if l.status == 'planned']
            in_progress_lesson = next((l for l in all_lessons if l.status == 'in_progress'), None)
            
            # Последний проведённый урок (самый недавний completed)
            last_completed = completed_lessons[0] if completed_lessons else None
            
            # Два ближайших запланированных урока (самые ранние по дате)
            try:
                upcoming_lessons = sorted(planned_lessons, key=lambda x: x.lesson_date if x.lesson_date else now)[:2]
            except Exception as e:
                logger.warning(f"Error sorting planned lessons: {e}")
                upcoming_lessons = planned_lessons[:2] if planned_lessons else []
            
            # Все уроки отображаются в общем списке (ключевые дублируются сверху для удобства)
            other_lessons = all_lessons
        except Exception as e:
            logger.error(f"Error processing lessons: {e}", exc_info=True)
            completed_lessons = []
            planned_lessons = []
            in_progress_lesson = None
            last_completed = None
            upcoming_lessons = []
            other_lessons = all_lessons
        
        # Находим User ученика (для аватарки и связей)
        student_user_obj = None
        if student.email:
            student_user_obj = User.query.filter_by(email=student.email, role='student').first()

        # Загружаем информацию о родителях (для тьюторов)
        parents_info = []
        try:
            # Безопасная проверка ролей с использованием hasattr
            can_see_parents = False
            if current_user.is_authenticated:
                if hasattr(current_user, 'is_tutor') and current_user.is_tutor():
                    can_see_parents = True
                elif hasattr(current_user, 'is_admin') and current_user.is_admin():
                    can_see_parents = True
                elif hasattr(current_user, 'is_creator') and current_user.is_creator():
                    can_see_parents = True
            
            if can_see_parents and student_user_obj:
                try:
                    # Получаем всех родителей этого ученика
                    family_ties = FamilyTie.query.filter_by(
                        student_id=student_user_obj.id,
                        is_confirmed=True
                    ).all()
                    
                    for tie in family_ties:
                        try:
                            parent_user = User.query.get(tie.parent_id)
                            if parent_user:
                                # Безопасно получаем профиль
                                from app.models import UserProfile
                                parent_profile = UserProfile.query.filter_by(user_id=parent_user.id).first()
                                
                                if parent_profile:
                                    name = f"{parent_profile.first_name or ''} {parent_profile.last_name or ''}".strip()
                                    if not name:
                                        name = parent_user.username
                                    
                                    parents_info.append({
                                        'name': name,
                                        'phone': parent_profile.phone,
                                        'telegram_id': parent_profile.telegram_id,
                                        'access_level': tie.access_level
                                    })
                        except Exception as e:
                            logger.error(f"Ошибка при загрузке родителя {tie.parent_id}: {e}", exc_info=True)
                            continue
                except Exception as e:
                    logger.error(f"Ошибка при загрузке информации о родителях: {e}", exc_info=True)
                    # Не блокируем отображение профиля, просто не показываем родителей
        except Exception as e:
            logger.error(f"Ошибка при проверке доступа к информации о родителях: {e}", exc_info=True)
            # Продолжаем без информации о родителях
        
        return render_template('student_profile.html', 
                               student=student, 
                               student_user=student_user_obj,
                               active_submissions=active_submissions,
                               lessons=all_lessons,
                               last_completed=last_completed,
                               upcoming_lessons=upcoming_lessons,
                               in_progress_lesson=in_progress_lesson,
                               other_lessons=other_lessons,
                               parents_info=parents_info)
    except Exception as e:
        logger.error(f"Critical error in student_profile: {e}", exc_info=True)
        flash('Произошла ошибка при загрузке профиля ученика.', 'danger')
        return redirect(url_for('main.dashboard'))

@students_bp.route('/student/<int:student_id>/statistics')
@login_required
def student_statistics(student_id):
    """Редирект на единую страницу статистики"""
    return redirect(url_for('students.student_analytics', student_id=student_id))
    
    # Загружаем все уроки с заданиями
    lessons = Lesson.query.filter_by(student_id=student_id).options(
        db.joinedload(Lesson.homework_tasks).joinedload(LessonTask.task)
    ).all()
    
    # Собираем статистику по номерам заданий
    task_stats = {}
    
    # Сначала собираем автоматическую статистику (из LessonTask)
    for lesson in lessons:
        # Обрабатываем все типы заданий
        for assignment_type in ['homework', 'classwork', 'exam']:
            assignments = get_sorted_assignments(lesson, assignment_type)
            weight = 2 if assignment_type == 'exam' else 1
            
            for lt in assignments:
                if not lt.task or not lt.task.task_number:
                    continue
                
                task_num = lt.task.task_number
                
                if task_num not in task_stats:
                    task_stats[task_num] = {
                        'auto_correct': 0, 
                        'auto_total': 0,
                        'manual_correct': 0, 
                        'manual_incorrect': 0,
                        'correct': 0,
                        'total': 0
                    }
                
                # Учитываем только задания с проверенными ответами
                if lt.submission_correct is not None:
                    task_stats[task_num]['auto_total'] += weight
                    if lt.submission_correct:
                        task_stats[task_num]['auto_correct'] += weight
    
    # Загружаем ручные изменения статистики
    manual_stats = StudentTaskStatistics.query.filter_by(student_id=student_id).all()
    manual_stats_dict = {stat.task_number: stat for stat in manual_stats}
    
    logger.info(f"Автоматическая статистика для ученика {student_id}: {[(k, v['auto_correct'], v['auto_total']) for k, v in task_stats.items()]}")
    logger.info(f"Ручные изменения для ученика {student_id}: {[(s.task_number, s.manual_correct, s.manual_incorrect) for s in manual_stats]}")
    
    # Применяем ручные изменения к статистике
    # Сначала применяем к существующим заданиям
    for task_num in list(task_stats.keys()):
        if task_num in manual_stats_dict:
            manual_stat = manual_stats_dict[task_num]
            task_stats[task_num]['manual_correct'] = manual_stat.manual_correct
            task_stats[task_num]['manual_incorrect'] = manual_stat.manual_incorrect
        
        # Рассчитываем итоговые значения: автоматические + ручные
        task_stats[task_num]['correct'] = task_stats[task_num]['auto_correct'] + task_stats[task_num]['manual_correct']
        task_stats[task_num]['total'] = task_stats[task_num]['auto_total'] + task_stats[task_num]['manual_correct'] + task_stats[task_num]['manual_incorrect']
    
    # Добавляем задания, для которых есть только ручные изменения (без автоматической статистики)
    for task_num, manual_stat in manual_stats_dict.items():
        if task_num not in task_stats:
            # Создаем запись только с ручными изменениями
            task_stats[task_num] = {
                'auto_correct': 0,
                'auto_total': 0,
                'correct': manual_stat.manual_correct,
                'total': manual_stat.manual_correct + manual_stat.manual_incorrect,
                'manual_correct': manual_stat.manual_correct,
                'manual_incorrect': manual_stat.manual_incorrect
            }
    
    logger.info(f"Итоговая статистика для ученика {student_id}: {[(k, v['correct'], v['total']) for k, v in task_stats.items()]}")
    
    # Вычисляем проценты и формируем данные для диаграммы
    chart_data = []
    for task_num in sorted(task_stats.keys()):
        stats = task_stats[task_num]
        if stats['total'] > 0:
            percent = round((stats['correct'] / stats['total']) * 100, 1)
            # Определяем цвет: красный (0-40%), желтый (40-80%), зеленый (80-100%)
            if percent < 40:
                color = '#ef4444'  # красный
            elif percent < 80:
                color = '#eab308'  # желтый
            else:
                color = '#22c55e'  # зеленый
            
            chart_data.append({
                'task_number': task_num,
                'percent': percent,
                'correct': stats['correct'],
                'total': stats['total'],
                'color': color,
                'manual_correct': stats.get('manual_correct', 0),
                'manual_incorrect': stats.get('manual_incorrect', 0)
            })
    
    return render_template('student_statistics.html', 
                         student=student, 
                         chart_data=chart_data)

@students_bp.route('/student/<int:student_id>/statistics/update', methods=['POST'])
@login_required
def update_statistics(student_id):
    """API endpoint для обновления ручной статистики с поддержкой разных режимов редактирования"""
    try:
        logger.info(f"Получен запрос на обновление статистики для ученика {student_id}")
        
        student = Student.query.get_or_404(student_id)
        data = request.get_json()
        
        logger.info(f"Данные запроса: {data}")
        
        if not data or 'task_number' not in data:
            logger.warning("Не указан номер задания в запросе")
            return jsonify({'success': False, 'error': 'Не указан номер задания'}), 400
        
        task_number = int(data['task_number'])
        # Режим редактирования: 'add' (добавить), 'set' (установить), 'subtract' (вычесть)
        edit_mode = data.get('mode', 'add').lower()
        
        if edit_mode not in ['add', 'set', 'subtract']:
            return jsonify({'success': False, 'error': 'Некорректный режим редактирования. Используйте: add, set или subtract'}), 400
        
        # Получаем значения
        manual_correct_value = int(data.get('manual_correct', 0))
        manual_incorrect_value = int(data.get('manual_incorrect', 0))
        
        # Проверяем, что значения неотрицательные (для режимов add и subtract)
        if edit_mode in ['add', 'subtract']:
            if manual_correct_value < 0 or manual_incorrect_value < 0:
                return jsonify({'success': False, 'error': 'Значения должны быть неотрицательными'}), 400
        
        # Ищем существующую запись или создаем новую
        stat = StudentTaskStatistics.query.filter_by(
            student_id=student_id,
            task_number=task_number
        ).first()
        
        old_correct = stat.manual_correct if stat else 0
        old_incorrect = stat.manual_incorrect if stat else 0
        
        if stat:
            # Применяем изменения в зависимости от режима
            if edit_mode == 'add':
                stat.manual_correct += manual_correct_value
                stat.manual_incorrect += manual_incorrect_value
            elif edit_mode == 'set':
                stat.manual_correct = manual_correct_value
                stat.manual_incorrect = manual_incorrect_value
            elif edit_mode == 'subtract':
                stat.manual_correct = max(0, stat.manual_correct - manual_correct_value)
                stat.manual_incorrect = max(0, stat.manual_incorrect - manual_incorrect_value)
            
            stat.updated_at = moscow_now()
            logger.info(f"Обновлена запись (режим {edit_mode}): task_number={task_number}, было: correct={old_correct}, incorrect={old_incorrect}, стало: correct={stat.manual_correct}, incorrect={stat.manual_incorrect}")
        else:
            # Создаем новую запись
            if edit_mode == 'set':
                stat = StudentTaskStatistics(
                    student_id=student_id,
                    task_number=task_number,
                    manual_correct=manual_correct_value,
                    manual_incorrect=manual_incorrect_value
                )
            else:  # add или subtract
                stat = StudentTaskStatistics(
                    student_id=student_id,
                    task_number=task_number,
                    manual_correct=max(0, manual_correct_value if edit_mode == 'add' else -manual_correct_value),
                    manual_incorrect=max(0, manual_incorrect_value if edit_mode == 'add' else -manual_incorrect_value)
                )
            db.session.add(stat)
            logger.info(f"Создана новая запись (режим {edit_mode}): task_number={task_number}, correct={stat.manual_correct}, incorrect={stat.manual_incorrect}")
        
        db.session.commit()
        
        # Принудительно обновляем объект из базы данных для проверки
        db.session.refresh(stat)
        
        logger.info(f"Статистика успешно обновлена: student_id={student_id}, task_number={task_number}, режим={edit_mode}")
        
        # Логируем изменение
        try:
            audit_logger.log(
                action='update_statistics',
                entity='StudentTaskStatistics',
                entity_id=stat.stat_id,
                status='success',
                metadata={
                    'student_id': student_id,
                    'student_name': student.name,
                    'task_number': task_number,
                    'edit_mode': edit_mode,
                    'manual_correct_old': old_correct,
                    'manual_incorrect_old': old_incorrect,
                    'manual_correct_new': stat.manual_correct,
                    'manual_incorrect_new': stat.manual_incorrect
                }
            )
        except Exception as log_err:
            logger.warning(f"Ошибка при логировании: {log_err}")
        
        response_data = {
            'success': True,
            'message': 'Статистика обновлена',
            'stat_id': stat.stat_id,
            'manual_correct': stat.manual_correct,
            'manual_incorrect': stat.manual_incorrect
        }
        
        logger.info(f"Отправка ответа: {response_data}")
        return jsonify(response_data), 200
        
    except ValueError as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Некорректные данные: {str(e)}'}), 400
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при обновлении статистики: {e}', exc_info=True)
        audit_logger.log_error(
            action='update_statistics',
            entity='StudentTaskStatistics',
            error=str(e)
        )
        return jsonify({'success': False, 'error': str(e)}), 500

@students_bp.route('/student/<int:student_id>/statistics/reset', methods=['POST'])
@login_required
def reset_statistics(student_id):
    """API endpoint для сброса ручных изменений статистики"""
    try:
        student = Student.query.get_or_404(student_id)
        data = request.get_json()
        
        task_number = data.get('task_number')
        
        if task_number:
            # Сброс для конкретного задания
            stat = StudentTaskStatistics.query.filter_by(
                student_id=student_id,
                task_number=task_number
            ).first()
            
            if stat:
                db.session.delete(stat)
                db.session.commit()
                logger.info(f"Сброшена статистика для задания {task_number} ученика {student_id}")
                return jsonify({'success': True, 'message': 'Статистика сброшена'}), 200
            else:
                return jsonify({'success': False, 'error': 'Запись не найдена'}), 404
        else:
            # Сброс всех ручных изменений для ученика
            stats = StudentTaskStatistics.query.filter_by(student_id=student_id).all()
            count = len(stats)
            for stat in stats:
                db.session.delete(stat)
            db.session.commit()
            logger.info(f"Сброшена вся статистика для ученика {student_id} ({count} записей)")
            return jsonify({'success': True, 'message': f'Сброшено {count} записей статистики'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при сбросе статистики: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@students_bp.route('/student/<int:student_id>/analytics')
@login_required
def student_analytics(student_id):
    """Единая страница статистики и аналитики ученика с табами"""
    from app.auth.rbac_utils import get_user_scope
    
    student = Student.query.get_or_404(student_id)
    
    # Проверка доступа через data scoping
    scope = get_user_scope(current_user)
    if not scope['can_see_all']:
        # Проверяем, есть ли доступ к этому ученику
        if student.email:
            student_user = User.query.filter_by(email=student.email, role='student').first()
            if student_user:
                if student_user.id not in scope['student_ids']:
                    flash('У вас нет доступа к статистике этого ученика.', 'danger')
                    return redirect(url_for('main.dashboard'))
        else:
            if not scope['student_ids']:
                flash('У вас нет доступа к статистике этого ученика.', 'danger')
                return redirect(url_for('main.dashboard'))
    
    # Инициализируем сервис статистики
    stats = StatsService(student_id)
    
    # Собираем данные для графиков (Навыки)
    gpa_data = stats.get_gpa_trend(period_days=90)
    skill_data = stats.get_skills_map()
    metrics = stats.get_summary_metrics()
    problem_topics = stats.get_problem_topics(threshold=60)
    gpa_by_type = stats.get_gpa_by_type()
    
    # Собираем данные для графиков (Дисциплина)
    attendance_data = stats.get_attendance_pie()
    attendance_heatmap = stats.get_attendance_heatmap(weeks=52)
    punctuality = stats.get_submission_punctuality()
    
    # Загружаем статистику по заданиям для вкладки "Навыки"
    lessons = Lesson.query.filter_by(student_id=student_id).options(
        db.joinedload(Lesson.homework_tasks).joinedload(LessonTask.task)
    ).all()
    
    task_stats = {}
    for lesson in lessons:
        for assignment_type in ['homework', 'classwork', 'exam']:
            assignments = get_sorted_assignments(lesson, assignment_type)
            weight = 2 if assignment_type == 'exam' else 1
            
            for lt in assignments:
                if not lt.task or not lt.task.task_number:
                    continue
                
                task_num = lt.task.task_number
                
                if task_num not in task_stats:
                    task_stats[task_num] = {
                        'auto_correct': 0, 
                        'auto_total': 0,
                        'manual_correct': 0, 
                        'manual_incorrect': 0,
                        'correct': 0,
                        'total': 0
                    }
                
                # Учитываем все задания, даже без проверки
                # Если есть проверка - учитываем результат
                if lt.submission_correct is not None:
                    task_stats[task_num]['auto_total'] += weight
                    if lt.submission_correct:
                        task_stats[task_num]['auto_correct'] += weight
                # Если проверки нет, но задание есть - считаем как невыполненное для статистики
                # Но не добавляем в auto_total, чтобы не искажать процент
    
    # Загружаем ручные изменения статистики
    manual_stats = StudentTaskStatistics.query.filter_by(student_id=student_id).all()
    for ms in manual_stats:
        if ms.task_number in task_stats:
            task_stats[ms.task_number]['manual_correct'] = ms.manual_correct or 0
            task_stats[ms.task_number]['manual_incorrect'] = ms.manual_incorrect or 0
            task_stats[ms.task_number]['correct'] = task_stats[ms.task_number]['auto_correct'] + ms.manual_correct - (ms.manual_incorrect or 0)
            task_stats[ms.task_number]['total'] = task_stats[ms.task_number]['auto_total'] + ms.manual_correct + (ms.manual_incorrect or 0)
        else:
            task_stats[ms.task_number] = {
                'auto_correct': 0,
                'auto_total': 0,
                'manual_correct': ms.manual_correct or 0,
                'manual_incorrect': ms.manual_incorrect or 0,
                'correct': ms.manual_correct - (ms.manual_incorrect or 0),
                'total': (ms.manual_correct or 0) + (ms.manual_incorrect or 0)
            }
    
    # Показываем все задания, по которым есть данные (с проверкой или ручными изменениями)
    chart_data = []
    for task_num in sorted(task_stats.keys()):
        stats_data = task_stats[task_num]
        # Учитываем задания с проверкой (auto_total > 0) или с ручными изменениями
        if stats_data['auto_total'] > 0 or stats_data.get('manual_correct', 0) > 0 or stats_data.get('manual_incorrect', 0) > 0:
            # Вычисляем итоговые значения
            total = stats_data['auto_total'] + stats_data.get('manual_correct', 0) + stats_data.get('manual_incorrect', 0)
            correct = stats_data['auto_correct'] + stats_data.get('manual_correct', 0) - stats_data.get('manual_incorrect', 0)
            
            if total > 0:
                percent = round((correct / total) * 100, 1)
                # Ограничиваем процент снизу нулем для корректного отображения
                if percent < 0:
                    percent = 0
            else:
                percent = 0
            
            if percent < 40:
                color = '#ef4444'
            elif percent < 80:
                color = '#eab308'
            else:
                color = '#22c55e'
            
            chart_data.append({
                'task_number': task_num,
                'percent': percent,
                'correct': correct,
                'total': total,
                'color': color,
                'auto_correct': stats_data.get('auto_correct', 0),
                'auto_total': stats_data.get('auto_total', 0),
                'manual_correct': stats_data.get('manual_correct', 0),
                'manual_incorrect': stats_data.get('manual_incorrect', 0)
            })
    
    # Сериализуем данные для передачи в JavaScript через Jinja
    charts_context = {
        'trend_dates': json.dumps(gpa_data['dates'], ensure_ascii=False),
        'trend_scores': json.dumps(gpa_data['scores']),
        'skill_labels': json.dumps(skill_data['labels'], ensure_ascii=False),
        'skill_values': json.dumps(skill_data['values']),
        'attendance_labels': json.dumps(attendance_data['labels'], ensure_ascii=False),
        'attendance_values': json.dumps(attendance_data['values']),
        'heatmap_dates': json.dumps(attendance_heatmap['dates'], ensure_ascii=False),
        'heatmap_values': json.dumps(attendance_heatmap['values']),
        'heatmap_statuses': json.dumps(attendance_heatmap['statuses'], ensure_ascii=False)
    }
    
    return render_template('student_stats_unified.html',
                         student=student,
                         charts=charts_context,
                         metrics=metrics,
                         gpa_by_type=gpa_by_type,
                         problem_topics=problem_topics,
                         chart_data=chart_data,
                         punctuality=punctuality)

@students_bp.route('/student/<int:student_id>/edit', methods=['GET', 'POST'])
@login_required
def student_edit(student_id):
    """Редактирование студента"""
    student = Student.query.get_or_404(student_id)
    form = StudentForm(obj=student)
    form._student_id = student_id
    if request.method == 'GET':
        form.school_class.data = student.school_class if student.school_class else 0

    if form.validate_on_submit():
        try:
            platform_id = form.platform_id.data.strip() if form.platform_id.data else None
            if platform_id:
                existing_student = Student.query.filter_by(platform_id=platform_id).first()
                if existing_student and existing_student.student_id != student_id:
                    flash(f'Ученик с ID "{platform_id}" уже существует! (Ученик: {existing_student.name})', 'error')
                    return render_template('student_form.html', form=form, title='Редактировать ученика',
                                         is_new=False, student=student)

            student.name = form.name.data
            student.platform_id = platform_id
            student.target_score = form.target_score.data
            student.deadline = form.deadline.data
            student.diagnostic_level = form.diagnostic_level.data
            student.preferences = form.preferences.data
            student.strengths = form.strengths.data
            student.weaknesses = form.weaknesses.data
            student.overall_rating = form.overall_rating.data
            student.description = form.description.data
            student.notes = form.notes.data
            student.category = form.category.data if form.category.data else None
            student.school_class = normalize_school_class(form.school_class.data)
            student.goal_text = form.goal_text.data.strip() if form.goal_text.data else None
            student.programming_language = form.programming_language.data.strip() if form.programming_language.data else None
            db.session.commit()
            
            # Логируем обновление ученика
            audit_logger.log(
                action='update_student',
                entity='Student',
                entity_id=student_id,
                status='success',
                metadata={
                    'name': student.name,
                    'platform_id': student.platform_id,
                    'category': student.category,
                    'school_class': student.school_class,
                    'goal_text': student.goal_text,
                    'programming_language': student.programming_language
                }
            )
            
            flash(f'Данные ученика {student.name} обновлены!', 'success')
            return redirect(url_for('students.student_profile', student_id=student.student_id))
        except Exception as e:
            db.session.rollback()
            logger.error(f'Ошибка при обновлении ученика {student_id}: {e}')
            
            # Логируем ошибку
            audit_logger.log_error(
                action='update_student',
                entity='Student',
                entity_id=student_id,
                error=str(e)
            )
            
            flash(f'Ошибка при обновлении данных: {str(e)}', 'error')

    return render_template('student_form.html', form=form, title='Редактировать ученика',
                         is_new=False, student=student)

@students_bp.route('/student/<int:student_id>/delete', methods=['POST'])
@login_required
def student_delete(student_id):
    """Удаление студента"""
    try:
        student = Student.query.get_or_404(student_id)
        name = student.name
        platform_id = student.platform_id
        category = student.category
        
        db.session.delete(student)
        db.session.commit()
        
        # Логируем удаление ученика
        audit_logger.log(
            action='delete_student',
            entity='Student',
            entity_id=student_id,
            status='success',
            metadata={
                'name': name,
                'platform_id': platform_id,
                'category': category
            }
        )
        
        flash(f'Ученик {name} удален из системы.', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при удалении ученика {student_id}: {e}')
        
        # Логируем ошибку
        audit_logger.log_error(
            action='delete_student',
            entity='Student',
            entity_id=student_id,
            error=str(e)
        )
        
        flash(f'Ошибка при удалении ученика: {str(e)}', 'error')
    return redirect(url_for('main.dashboard'))

@students_bp.route('/student/<int:student_id>/archive', methods=['POST'])
@login_required
def student_archive(student_id):
    """Архивирование/восстановление студента"""
    student = Student.query.get_or_404(student_id)
    student.is_active = not student.is_active
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise

    if student.is_active:
        flash(f'Ученик {student.name} восстановлен из архива.', 'success')
    else:
        flash(f'Ученик {student.name} перемещен в архив.', 'success')

    return redirect(url_for('main.dashboard'))

@students_bp.route('/student/<int:student_id>/lesson/new', methods=['GET', 'POST'])
@login_required
def lesson_new(student_id):
    """Создание нового урока для студента"""
    if current_user.is_student():
        flash('Ученики не могут создавать уроки.', 'danger')
        return redirect(url_for('students.student_profile', student_id=student_id))
    
    student = Student.query.get_or_404(student_id)
    form = LessonForm()
    course_module_id = request.args.get('course_module_id', type=int)
    return_to = (request.args.get('return_to') or '').strip().lower()

    # Если пришёл course_module_id — проверяем, что модуль действительно относится к этому ученику
    if course_module_id:
        try:
            from app.models import CourseModule, Course
            module = CourseModule.query.filter_by(module_id=course_module_id).first()
            if not module:
                flash('Модуль курса не найден. Урок будет создан без привязки к модулю.', 'warning')
                course_module_id = None
            else:
                course = Course.query.filter_by(course_id=module.course_id).first()
                if not course or course.student_id != student.student_id:
                    flash('Модуль курса не относится к этому ученику. Урок будет создан без привязки к модулю.', 'warning')
                    course_module_id = None
        except Exception:
            course_module_id = None

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
        
        lesson = Lesson(
            student_id=student_id,
            course_module_id=course_module_id,
            lesson_type=form.lesson_type.data,
            lesson_date=lesson_date_utc,
            duration=form.duration.data,
            status=form.status.data,
            topic=form.topic.data,
            notes=form.notes.data,
            homework=form.homework.data,
            homework_status=form.homework_status.data
        )
        db.session.add(lesson)
        try:  # Пытаемся сохранить урок обычным способом
            db.session.commit()  # Коммитим вставку урока
        except Exception as e:  # Если упали (часто из‑за сбитого sequence lesson_id)
            db.session.rollback()  # Откатываем транзакцию перед повтором
            msg = str(e)  # Превращаем ошибку в строку для распознавания
            is_unique = ('psycopg2.errors.UniqueViolation' in msg) or ('duplicate key value violates unique constraint' in msg)  # Признак UniqueViolation на Postgres
            is_lesson_pk = ('Lessons_pkey' in msg) or ('lesson_id' in msg)  # Признак, что упали именно на PK уроков
            db_url = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')  # Берём строку подключения
            is_pg = ('postgresql' in db_url) or ('postgres' in db_url)  # Определяем, что это PostgreSQL
            if is_pg and is_unique and is_lesson_pk:  # Если это именно сбитый sequence у Lessons
                try:  # Пытаемся починить sequence и повторить commit один раз
                    db.session.execute(text('SELECT setval(pg_get_serial_sequence(\'"Lessons"\', \'lesson_id\'), COALESCE((SELECT MAX("lesson_id") FROM "Lessons"), 0), true)'))  # Выравниваем sequence по MAX(lesson_id)
                    db.session.commit()  # Коммитим фиксацию sequence
                    db.session.add(lesson)  # Повторно добавляем объект урока в сессию
                    db.session.commit()  # Повторяем вставку урока
                except Exception as e2:  # Если не удалось починить/повторить
                    db.session.rollback()  # Откатываем
                    raise  # Пробрасываем реальную ошибку дальше
            else:  # Если это не sequence‑проблема — не маскируем её
                raise  # Пробрасываем реальную ошибку дальше
        
        # Логируем создание урока
        audit_logger.log(
            action='create_lesson',
            entity='Lesson',
            entity_id=lesson.lesson_id,
            status='success',
            metadata={
                'student_id': student_id,
                'student_name': student.name,
                'lesson_type': lesson.lesson_type,
                'lesson_date': str(lesson.lesson_date),
                'status': lesson.status
            }
        )
        
        flash(f'Урок добавлен для ученика {student.name}!', 'success')
        next_action = request.form.get('next', '').strip()  # Куда перейти сразу после создания (ДЗ/КР/Проверочная)
        if next_action == 'homework':  # Домашнее задание
            return redirect(url_for('lessons.lesson_homework_view', lesson_id=lesson.lesson_id, open_create=1))  # Открываем страницу ДЗ и автозапуск модалки
        if next_action == 'classwork':  # Классная работа
            return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson.lesson_id, open_create=1))  # Открываем страницу КР и автозапуск модалки
        if next_action == 'exam':  # Проверочная работа
            return redirect(url_for('lessons.lesson_exam_view', lesson_id=lesson.lesson_id, open_create=1))  # Открываем страницу проверочной и автозапуск модалки
        if return_to == 'course' and course_module_id:
            try:
                from app.models import CourseModule
                module = CourseModule.query.filter_by(module_id=course_module_id).first()
                if module:
                    return redirect(url_for('courses.course_view', course_id=module.course_id, _anchor=f'module-{course_module_id}'))
            except Exception:
                pass
        return redirect(url_for('students.student_profile', student_id=student_id))  # Дефолт: возвращаемся в профиль

    return render_template('lesson_form.html', form=form, student=student, title='Добавить урок', is_new=True)

@students_bp.route('/student/<int:student_id>/lesson-mode')
@login_required
def lesson_mode(student_id):
    """Режим урока для студента"""
    student = Student.query.get_or_404(student_id)
    now = moscow_now()
    
    # Загружаем все уроки одним запросом
    all_lessons = Lesson.query.filter_by(student_id=student_id).order_by(Lesson.lesson_date.desc()).all()
    lessons = all_lessons
    
    # Находим текущий и ближайший урок из уже загруженных данных
    current_lesson = next((l for l in all_lessons if l.status == 'in_progress'), None)
    planned_lessons = [l for l in all_lessons if l.status == 'planned' and l.lesson_date and l.lesson_date >= now]
    upcoming_lesson = sorted(planned_lessons, key=lambda x: x.lesson_date)[0] if planned_lessons else None

    return render_template('lesson_mode.html',
                         student=student,
                         lessons=lessons,
                         current_lesson=current_lesson,
                         upcoming_lesson=upcoming_lesson)

@students_bp.route('/student/<int:student_id>/start-lesson', methods=['POST'])
@login_required
def student_start_lesson(student_id):
    """Начало урока для студента"""
    student = Student.query.get_or_404(student_id)
    now = moscow_now()

    # Оптимизация: один запрос вместо двух
    active_lesson = Lesson.query.filter_by(student_id=student_id, status='in_progress').first()
    if active_lesson:
        flash('Урок уже идет!', 'info')
        return redirect(url_for('students.student_profile', student_id=student_id))

    # Оптимизация: используем limit(1) для лучшей производительности
    upcoming_lesson = Lesson.query.filter(
        Lesson.student_id == student_id,
        Lesson.status == 'planned',
        Lesson.lesson_date >= now
    ).order_by(Lesson.lesson_date).limit(1).first()

    if upcoming_lesson:
        upcoming_lesson.status = 'in_progress'
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise
        flash(f'Урок начат!', 'success')
    else:
        new_lesson = Lesson(
            student_id=student_id,
            lesson_type='regular',
            lesson_date=moscow_now(),
            duration=60,
            status='in_progress',
            topic='Занятие'
        )
        db.session.add(new_lesson)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise
        flash(f'Новый урок создан и начат!', 'success')

    return redirect(url_for('students.student_profile', student_id=student_id))
