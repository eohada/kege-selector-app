"""
Маршруты для управления студентами
"""
import json
import logging  # Логирование для отладки и прод-логов
from flask import render_template, request, redirect, url_for, flash, jsonify, current_app  # current_app нужен для определения типа БД (Postgres)
from flask_login import login_required
from sqlalchemy import text, or_, func  # text нужен для выполнения SQL setval(pg_get_serial_sequence(...)) при сбитых sequences
from sqlalchemy.exc import OperationalError, ProgrammingError
from datetime import datetime
import csv
import io
from flask import Response

from app.students import students_bp
from app.students.forms import StudentForm, normalize_school_class
from app.students.utils import get_sorted_assignments
from app.students.stats_service import StatsService
from app.lessons.forms import LessonForm, ensure_introductory_without_homework
from app.models import (
    Student,
    StudentTaskStatistics,
    StudentLearningPlanItem,
    GradebookEntry,
    Topic,
    Lesson,
    LessonTask,
    Course,
    CourseModule,
    db,
    moscow_now,
    MOSCOW_TZ,
    TOMSK_TZ,
    Submission,
    Assignment,
)
from app.models import User, FamilyTie
from app.utils.student_id_manager import assign_platform_id_if_needed
from core.audit_logger import audit_logger
from flask_login import current_user
from app.utils.db_migrations import ensure_schema_columns
from app.auth.rbac_utils import get_user_scope, has_permission
from app.utils.subscription_access import get_effective_access_for_user

logger = logging.getLogger(__name__)

def _get_student_user_for_scope(student: Student) -> User | None:
    """Пытаемся сопоставить Student с User (для data-scope)."""
    if not student:
        return None
    if getattr(student, 'email', None):
        u = User.query.filter_by(email=student.email).first()
        if u:
            return u
    try:
        u = User.query.get(student.student_id)
        if u and u.role == 'student':
            return u
    except Exception:
        pass
    return None


def _can_access_student(student: Student) -> bool:
    """
    Унифицированная проверка доступа к ученику:
    - admin/creator: всё
    - student: только себя (email или fallback student_id==User.id)
    - tutor/parent: через data scope (Enrollment/FamilyTie)
    """
    if not current_user.is_authenticated:
        return False

    if current_user.is_creator() or current_user.is_admin():
        return True

    if current_user.is_student():
        me_email = (current_user.email or '').strip().lower()
        st_email = (student.email or '').strip().lower() if student.email else ''
        if me_email and st_email and st_email == me_email:
            return True
        # Fallback допустим только если у Student нет email (иначе возможны коллизии User.id vs Student.student_id)
        if (not st_email) and student.student_id == current_user.id:
            return True
        return False

    scope = get_user_scope(current_user)
    if scope.get('can_see_all'):
        return True

    st_user = _get_student_user_for_scope(student)
    if st_user and st_user.id in (scope.get('student_ids') or []):
        return True

    # Fallback: иногда student_id совпадает с user.id в scope.
    return student.student_id in (scope.get('student_ids') or [])


def _guard_student_access(student_id: int) -> Student:
    student = Student.query.get_or_404(student_id)
    if not _can_access_student(student):
        from flask import abort
        abort(403)
    return student


def _parse_datetime_local(value: str | None):
    """Парсим значение из input[type=datetime-local]. Храним как naive (обычно MSK)."""
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        # Ожидаем "YYYY-MM-DDTHH:MM" (или с секундами)
        return datetime.fromisoformat(value)
    except Exception:
        return None

@students_bp.route('/students')
@login_required
def students_list():
    """Список всех студентов (активных и архивных)"""
    scope = get_user_scope(current_user)

    base_q = Student.query
    if scope.get('can_see_all'):
        active_students = base_q.filter_by(is_active=True).order_by(Student.name).all()
        archived_students = base_q.filter_by(is_active=False).order_by(Student.name).all()
    else:
        allowed_user_ids = list(dict.fromkeys(scope.get('student_ids') or []))
        if not allowed_user_ids:
            active_students = []
            archived_students = []
        else:
            # FamilyTie/Enrollment оперируют Users.id, а Student — отдельная таблица.
            # Маппим доступных student-user → (id/email) и подтягиваем Student по student_id и/или email.
            student_users = (
                User.query
                .filter(User.id.in_(allowed_user_ids), User.role == 'student')
                .all()
            )
            allowed_emails = []
            for u in student_users:
                em = (u.email or '').strip().lower()
                if em:
                    allowed_emails.append(em)

            allowed_emails = list(dict.fromkeys(allowed_emails))

            if allowed_emails:
                scoped_q = base_q.filter(
                    or_(
                        Student.student_id.in_(allowed_user_ids),
                        func.lower(Student.email).in_(allowed_emails)
                    )
                )
            else:
                scoped_q = base_q.filter(Student.student_id.in_(allowed_user_ids))

            active_students = scoped_q.filter(Student.is_active.is_(True)).order_by(Student.name).all()
            archived_students = scoped_q.filter(Student.is_active.is_(False)).order_by(Student.name).all()

    return render_template('students_list.html',
                         active_students=active_students,
                         archived_students=archived_students)

@students_bp.route('/student/new', methods=['GET', 'POST'])
@login_required
def student_new():
    """Создание нового студента"""
    # Создание ученика — функция админа/создателя (не доступна тьютору/ученику/родителю).
    if not (current_user.is_admin() or current_user.is_creator()):
        from flask import abort
        abort(403)

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

        # UX fix: студент всегда должен попадать в СВОЙ профиль.
        # Если в URL подставили Users.id вместо Students.student_id — редиректим на реальный student_id по email.
        if current_user.is_student():
            try:
                my_email = (current_user.email or '').strip().lower()
                if my_email:
                    me_student = Student.query.filter(func.lower(Student.email) == my_email).first()
                    if me_student and me_student.student_id != student_id:
                        return redirect(url_for('students.student_profile', student_id=me_student.student_id))
            except Exception:
                pass
        
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
        student_subscription = None
        try:
            if student_user_obj:
                student_subscription = get_effective_access_for_user(student_user_obj.id)
        except Exception:
            student_subscription = None

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
                               student_subscription=student_subscription,
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


@students_bp.route('/student/<int:student_id>/plan')
@login_required
def student_learning_plan(student_id: int):
    """Учебный план/траектория ученика (просмотр для ученика/родителя, редактирование для преподавателя)."""
    student = _guard_student_access(student_id)
    if not has_permission(current_user, 'plan.view'):
        from flask import abort
        abort(403)

    # QA/UX: тьютор должен иметь полный функционал траектории даже если RolePermission не заполнены.
    is_teacher_actor = (not current_user.is_student()) and (not current_user.is_parent())
    is_tutor_actor = bool(getattr(current_user, 'is_tutor', None) and current_user.is_tutor())
    can_edit = is_teacher_actor and (has_permission(current_user, 'plan.edit') or is_tutor_actor)

    items = StudentLearningPlanItem.query.filter_by(student_id=student.student_id).order_by(
        StudentLearningPlanItem.priority.desc(),
        StudentLearningPlanItem.due_date.asc(),
        StudentLearningPlanItem.item_id.desc(),
    ).all()

    # Справочники для селектов (только для редактирования, чтобы не делать лишнего)
    topics = []
    modules = []
    if can_edit:
        topics = Topic.query.order_by(Topic.name.asc()).all()
        modules = (
            CourseModule.query.join(Course, CourseModule.course_id == Course.course_id)
            .filter(Course.student_id == student.student_id)
            .order_by(CourseModule.order_index.asc(), CourseModule.module_id.asc())
            .all()
        )

    status_counts = {'planned': 0, 'in_progress': 0, 'done': 0, 'failed': 0}
    for it in items:
        key = (it.status or 'planned').strip().lower()
        if key not in status_counts:
            key = 'planned'
        status_counts[key] += 1

    return render_template(
        'student_learning_plan.html',
        student=student,
        items=items,
        topics=topics,
        modules=modules,
        can_edit=can_edit,
        status_counts=status_counts,
    )


@students_bp.route('/student/<int:student_id>/plan/items/create', methods=['POST'])
@login_required
def student_learning_plan_item_create(student_id: int):
    student = _guard_student_access(student_id)
    is_tutor_actor = bool(getattr(current_user, 'is_tutor', None) and current_user.is_tutor())
    if current_user.is_student() or current_user.is_parent() or (not (has_permission(current_user, 'plan.edit') or is_tutor_actor)):
        from flask import abort
        abort(403)

    title = (request.form.get('title') or '').strip()
    if not title:
        flash('Название пункта траектории обязательно.', 'danger')
        return redirect(url_for('students.student_learning_plan', student_id=student.student_id))

    status = (request.form.get('status') or 'planned').strip().lower()
    if status not in {'planned', 'in_progress', 'done', 'failed'}:
        status = 'planned'

    due_date = _parse_datetime_local(request.form.get('due_date'))
    priority = request.form.get('priority', type=int) or 0
    notes = (request.form.get('notes') or '').strip() or None
    topic_id = request.form.get('topic_id', type=int)
    course_module_id = request.form.get('course_module_id', type=int)

    item = StudentLearningPlanItem(
        student_id=student.student_id,
        title=title,
        status=status,
        due_date=due_date,
        priority=priority,
        notes=notes,
        topic_id=topic_id or None,
        course_module_id=course_module_id or None,
        created_by_user_id=current_user.id,
    )
    db.session.add(item)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='plan_item_create', entity='StudentLearningPlanItem', error=str(e))
        flash('Не удалось добавить пункт траектории.', 'danger')
        return redirect(url_for('students.student_learning_plan', student_id=student.student_id))

    try:
        audit_logger.log(
            action='plan_item_create',
            entity='StudentLearningPlanItem',
            entity_id=item.item_id,
            status='success',
            metadata={
                'student_id': student.student_id,
                'title': item.title,
                'status': item.status,
                'due_date': item.due_date.isoformat() if item.due_date else None,
                'priority': item.priority,
            },
        )
    except Exception:
        pass
    flash('Пункт траектории добавлен.', 'success')
    return redirect(url_for('students.student_learning_plan', student_id=student.student_id))


@students_bp.route('/student/<int:student_id>/plan/items/<int:item_id>/update', methods=['POST'])
@login_required
def student_learning_plan_item_update(student_id: int, item_id: int):
    student = _guard_student_access(student_id)
    is_tutor_actor = bool(getattr(current_user, 'is_tutor', None) and current_user.is_tutor())
    if current_user.is_student() or current_user.is_parent() or (not (has_permission(current_user, 'plan.edit') or is_tutor_actor)):
        from flask import abort
        abort(403)

    item = StudentLearningPlanItem.query.filter_by(item_id=item_id, student_id=student.student_id).first_or_404()

    title = (request.form.get('title') or '').strip()
    if not title:
        flash('Название пункта траектории обязательно.', 'danger')
        return redirect(url_for('students.student_learning_plan', student_id=student.student_id))

    status = (request.form.get('status') or 'planned').strip().lower()
    if status not in {'planned', 'in_progress', 'done', 'failed'}:
        status = 'planned'

    item.title = title
    item.status = status
    item.due_date = _parse_datetime_local(request.form.get('due_date'))
    item.priority = request.form.get('priority', type=int) or 0
    item.notes = (request.form.get('notes') or '').strip() or None
    item.topic_id = request.form.get('topic_id', type=int) or None
    item.course_module_id = request.form.get('course_module_id', type=int) or None

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='plan_item_update', entity='StudentLearningPlanItem', entity_id=item.item_id, error=str(e))
        flash('Не удалось обновить пункт траектории.', 'danger')
        return redirect(url_for('students.student_learning_plan', student_id=student.student_id))

    try:
        audit_logger.log(
            action='plan_item_update',
            entity='StudentLearningPlanItem',
            entity_id=item.item_id,
            status='success',
            metadata={
                'student_id': student.student_id,
                'title': item.title,
                'status': item.status,
                'due_date': item.due_date.isoformat() if item.due_date else None,
                'priority': item.priority,
            },
        )
    except Exception:
        pass
    flash('Пункт траектории обновлён.', 'success')
    return redirect(url_for('students.student_learning_plan', student_id=student.student_id))


@students_bp.route('/student/<int:student_id>/plan/items/<int:item_id>/delete', methods=['POST'])
@login_required
def student_learning_plan_item_delete(student_id: int, item_id: int):
    student = _guard_student_access(student_id)
    is_tutor_actor = bool(getattr(current_user, 'is_tutor', None) and current_user.is_tutor())
    if current_user.is_student() or current_user.is_parent() or (not (has_permission(current_user, 'plan.edit') or is_tutor_actor)):
        from flask import abort
        abort(403)

    item = StudentLearningPlanItem.query.filter_by(item_id=item_id, student_id=student.student_id).first_or_404()
    meta = {'student_id': student.student_id, 'title': item.title, 'status': item.status}
    db.session.delete(item)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='plan_item_delete', entity='StudentLearningPlanItem', entity_id=item_id, error=str(e))
        flash('Не удалось удалить пункт траектории.', 'danger')
        return redirect(url_for('students.student_learning_plan', student_id=student.student_id))

    try:
        audit_logger.log(
            action='plan_item_delete',
            entity='StudentLearningPlanItem',
            entity_id=item_id,
            status='success',
            metadata=meta,
        )
    except Exception:
        pass
    flash('Пункт траектории удалён.', 'success')
    return redirect(url_for('students.student_learning_plan', student_id=student.student_id))


@students_bp.route('/student/<int:student_id>/gradebook')
@login_required
def student_gradebook(student_id: int):
    """Единый журнал оценок: ученик/родитель смотрят, преподаватель редактирует."""
    student = _guard_student_access(student_id)
    if not has_permission(current_user, 'gradebook.view'):
        from flask import abort
        abort(403)

    # QA/UX: тьютор должен иметь доступ к журналу (редактирование/добавление), даже если RolePermission не заполнены.
    is_teacher_actor = (not current_user.is_student()) and (not current_user.is_parent())
    is_tutor_actor = bool(getattr(current_user, 'is_tutor', None) and current_user.is_tutor())
    can_edit = is_teacher_actor and (has_permission(current_user, 'gradebook.edit') or is_tutor_actor)

    # Ручные/явные записи журнала
    entries = GradebookEntry.query.filter_by(student_id=student.student_id).order_by(
        GradebookEntry.created_at.desc(),
        GradebookEntry.entry_id.desc(),
    ).all()

    # Справочник уроков и работ — только преподавателю, чтобы можно было быстро привязывать записи.
    lessons = []
    submissions = []
    if can_edit:
        lessons = Lesson.query.filter_by(student_id=student.student_id).order_by(Lesson.lesson_date.desc()).all()
        submissions = (
            Submission.query.filter_by(student_id=student.student_id)
            .options(db.joinedload(Submission.assignment))
            .order_by(Submission.assigned_at.desc())
            .all()
        )

    return render_template(
        'student_gradebook.html',
        student=student,
        entries=entries,
        can_edit=can_edit,
        lessons=lessons,
        submissions=submissions,
    )


@students_bp.route('/student/<int:student_id>/gradebook/create', methods=['POST'])
@login_required
def student_gradebook_create(student_id: int):
    student = _guard_student_access(student_id)
    is_tutor_actor = bool(getattr(current_user, 'is_tutor', None) and current_user.is_tutor())
    if current_user.is_student() or current_user.is_parent() or (not (has_permission(current_user, 'gradebook.edit') or is_tutor_actor)):
        from flask import abort
        abort(403)

    kind = (request.form.get('kind') or 'manual').strip().lower()
    if kind not in {'manual', 'lesson', 'assignment'}:
        kind = 'manual'

    title = (request.form.get('title') or '').strip()
    category = (request.form.get('category') or '').strip().lower() or None
    comment = (request.form.get('comment') or '').strip() or None
    score = request.form.get('score', type=int)
    max_score = request.form.get('max_score', type=int)
    grade_text = (request.form.get('grade_text') or '').strip() or None
    weight = request.form.get('weight', type=int) or 1

    lesson_id = request.form.get('lesson_id', type=int) if kind == 'lesson' else None
    submission_id = request.form.get('submission_id', type=int) if kind == 'assignment' else None

    if not title:
        # Автозаголовок для lesson/assignment
        if kind == 'lesson' and lesson_id:
            l = Lesson.query.filter_by(lesson_id=lesson_id, student_id=student.student_id).first()
            title = (l.topic or 'Урок') if l else 'Урок'
        elif kind == 'assignment' and submission_id:
            s = Submission.query.filter_by(submission_id=submission_id, student_id=student.student_id).first()
            title = (s.assignment.title if (s and s.assignment) else 'Работа') if s else 'Работа'

    if not title:
        flash('Название записи обязательно.', 'danger')
        return redirect(url_for('students.student_gradebook', student_id=student.student_id))

    entry = GradebookEntry(
        student_id=student.student_id,
        kind=kind,
        category=category,
        title=title,
        comment=comment,
        score=score,
        max_score=max_score,
        grade_text=grade_text,
        weight=weight,
        lesson_id=lesson_id,
        submission_id=submission_id,
        created_by_user_id=current_user.id,
    )
    db.session.add(entry)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='gradebook_create', entity='GradebookEntry', error=str(e))
        flash('Не удалось добавить запись в журнал.', 'danger')
        return redirect(url_for('students.student_gradebook', student_id=student.student_id))

    try:
        audit_logger.log(
            action='gradebook_create',
            entity='GradebookEntry',
            entity_id=entry.entry_id,
            status='success',
            metadata={
                'student_id': student.student_id,
                'kind': entry.kind,
                'category': entry.category,
                'title': entry.title,
                'score': entry.score,
                'max_score': entry.max_score,
                'grade_text': entry.grade_text,
                'weight': entry.weight,
                'lesson_id': entry.lesson_id,
                'submission_id': entry.submission_id,
            },
        )
    except Exception:
        pass
    flash('Запись добавлена.', 'success')
    return redirect(url_for('students.student_gradebook', student_id=student.student_id))


@students_bp.route('/student/<int:student_id>/gradebook/<int:entry_id>/update', methods=['POST'])
@login_required
def student_gradebook_update(student_id: int, entry_id: int):
    student = _guard_student_access(student_id)
    is_tutor_actor = bool(getattr(current_user, 'is_tutor', None) and current_user.is_tutor())
    if current_user.is_student() or current_user.is_parent() or (not (has_permission(current_user, 'gradebook.edit') or is_tutor_actor)):
        from flask import abort
        abort(403)

    entry = GradebookEntry.query.filter_by(entry_id=entry_id, student_id=student.student_id).first_or_404()

    title = (request.form.get('title') or '').strip()
    if not title:
        flash('Название записи обязательно.', 'danger')
        return redirect(url_for('students.student_gradebook', student_id=student.student_id))

    entry.title = title
    entry.category = (request.form.get('category') or '').strip().lower() or None
    entry.comment = (request.form.get('comment') or '').strip() or None
    entry.score = request.form.get('score', type=int)
    entry.max_score = request.form.get('max_score', type=int)
    entry.grade_text = (request.form.get('grade_text') or '').strip() or None
    entry.weight = request.form.get('weight', type=int) or 1

    # Для lesson/assignment можно менять привязку, но строго в рамках ученика.
    if (entry.kind or '').lower() == 'lesson':
        lesson_id = request.form.get('lesson_id', type=int)
        if lesson_id:
            l = Lesson.query.filter_by(lesson_id=lesson_id, student_id=student.student_id).first()
            entry.lesson_id = l.lesson_id if l else None
        else:
            entry.lesson_id = None
    if (entry.kind or '').lower() == 'assignment':
        submission_id = request.form.get('submission_id', type=int)
        if submission_id:
            s = Submission.query.filter_by(submission_id=submission_id, student_id=student.student_id).first()
            entry.submission_id = s.submission_id if s else None
        else:
            entry.submission_id = None

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='gradebook_update', entity='GradebookEntry', entity_id=entry.entry_id, error=str(e))
        flash('Не удалось обновить запись в журнале.', 'danger')
        return redirect(url_for('students.student_gradebook', student_id=student.student_id))

    try:
        audit_logger.log(
            action='gradebook_update',
            entity='GradebookEntry',
            entity_id=entry.entry_id,
            status='success',
            metadata={
                'student_id': student.student_id,
                'kind': entry.kind,
                'category': entry.category,
                'title': entry.title,
                'score': entry.score,
                'max_score': entry.max_score,
                'grade_text': entry.grade_text,
                'weight': entry.weight,
                'lesson_id': entry.lesson_id,
                'submission_id': entry.submission_id,
            },
        )
    except Exception:
        pass
    flash('Запись обновлена.', 'success')
    return redirect(url_for('students.student_gradebook', student_id=student.student_id))


@students_bp.route('/student/<int:student_id>/gradebook/<int:entry_id>/delete', methods=['POST'])
@login_required
def student_gradebook_delete(student_id: int, entry_id: int):
    student = _guard_student_access(student_id)
    is_tutor_actor = bool(getattr(current_user, 'is_tutor', None) and current_user.is_tutor())
    if current_user.is_student() or current_user.is_parent() or (not (has_permission(current_user, 'gradebook.edit') or is_tutor_actor)):
        from flask import abort
        abort(403)

    entry = GradebookEntry.query.filter_by(entry_id=entry_id, student_id=student.student_id).first_or_404()
    meta = {
        'student_id': student.student_id,
        'kind': entry.kind,
        'category': entry.category,
        'title': entry.title,
        'score': entry.score,
        'max_score': entry.max_score,
        'grade_text': entry.grade_text,
        'weight': entry.weight,
        'lesson_id': entry.lesson_id,
        'submission_id': entry.submission_id,
    }
    db.session.delete(entry)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='gradebook_delete', entity='GradebookEntry', entity_id=entry_id, error=str(e))
        flash('Не удалось удалить запись из журнала.', 'danger')
        return redirect(url_for('students.student_gradebook', student_id=student.student_id))

    try:
        audit_logger.log(
            action='gradebook_delete',
            entity='GradebookEntry',
            entity_id=entry_id,
            status='success',
            metadata=meta,
        )
    except Exception:
        pass
    flash('Запись удалена.', 'success')
    return redirect(url_for('students.student_gradebook', student_id=student.student_id))


@students_bp.route('/student/<int:student_id>/gradebook.csv')
@login_required
def student_gradebook_export_csv(student_id: int):
    """Экспорт журнала ученика в CSV."""
    student = _guard_student_access(student_id)
    if not has_permission(current_user, 'gradebook.view'):
        from flask import abort
        abort(403)

    entries = GradebookEntry.query.filter_by(student_id=student.student_id).order_by(
        GradebookEntry.created_at.asc(),
        GradebookEntry.entry_id.asc(),
    ).all()

    try:
        audit_logger.log(
            action='export_gradebook_csv',
            entity='Student',
            entity_id=student.student_id,
            status='success',
            metadata={'entries_count': len(entries)},
        )
    except Exception:
        pass

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['created_at', 'kind', 'category', 'title', 'score', 'max_score', 'grade_text', 'weight', 'comment'])
    for e in entries:
        w.writerow([
            e.created_at.isoformat() if e.created_at else '',
            e.kind or '',
            e.category or '',
            e.title or '',
            '' if e.score is None else e.score,
            '' if e.max_score is None else e.max_score,
            e.grade_text or '',
            e.weight if e.weight is not None else '',
            (e.comment or '').replace('\r', '').replace('\n', ' ').strip(),
        ])

    csv_bytes = buf.getvalue().encode('utf-8-sig')
    filename = f'gradebook-student-{student.student_id}.csv'
    return Response(
        csv_bytes,
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )


@students_bp.route('/student/<int:student_id>/gradebook.pdf')
@login_required
def student_gradebook_export_pdf(student_id: int):
    """Экспорт журнала ученика в PDF (через Playwright)."""
    student = _guard_student_access(student_id)
    if not has_permission(current_user, 'gradebook.view'):
        from flask import abort
        abort(403)

    entries = GradebookEntry.query.filter_by(student_id=student.student_id).order_by(
        GradebookEntry.created_at.asc(),
        GradebookEntry.entry_id.asc(),
    ).all()

    html = render_template('student_gradebook_print.html', student=student, entries=entries)
    filename = f'gradebook-student-{student.student_id}.pdf'

    try:
        from app.utils.pdf_export import html_to_pdf_bytes
        pdf_bytes = html_to_pdf_bytes(html)
    except Exception as e:
        logger.warning(f"PDF export not available, fallback to HTML: {e}")
        # fallback: printable HTML
        return Response(
            html,
            mimetype='text/html; charset=utf-8',
            headers={'Content-Disposition': f'inline; filename="{filename}.html"'}
        )

    try:
        audit_logger.log(
            action='export_gradebook_pdf',
            entity='Student',
            entity_id=student.student_id,
            status='success',
            metadata={'entries_count': len(entries)},
        )
    except Exception:
        pass

    return Response(
        pdf_bytes,
        mimetype='application/pdf',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )


@students_bp.route('/student/<int:student_id>/diagnostics')
@login_required
def student_diagnostics(student_id: int):
    """Диагностика ученика: слабые темы + сохранённые контрольные точки."""
    student = _guard_student_access(student_id)
    # QA/UX: тьютор должен видеть диагностику и сохранять контрольные точки по требованиям QA,
    # даже если RolePermission не заполнены.
    is_tutor_actor = bool(getattr(current_user, 'is_tutor', None) and current_user.is_tutor())
    if not ((has_permission(current_user, 'plan.view') and has_permission(current_user, 'diagnostics.view')) or is_tutor_actor):
        from flask import abort
        abort(403)

    from app.students.stats_service import StatsService
    from app.models import StudentDiagnosticCheckpoint

    stats = None
    metrics = {}
    problem_topics = []
    problem_tasks = []
    coverage = {'scored_items': 0, 'scored_with_topics': 0, 'unique_topics': 0}
    try:
        stats = StatsService(student.student_id)
        metrics = stats.get_summary_metrics()
        problem_topics = stats.get_problem_topics(threshold=60)
        # Fallback: если topics пустые/не заполнены, покажем слабые места по номерам заданий
        try:
            problem_tasks = stats.get_problem_task_numbers(threshold=60, min_attempts=3)
        except Exception:
            problem_tasks = []

        # Диагностическое покрытие: сколько вообще есть проверенных попыток и есть ли темы
        try:
            total = 0
            with_topics = 0
            uniq_topics = set()
            for _is_correct, _ratio, _weight, topics in stats._iter_scored_items():
                total += 1
                if topics:
                    with_topics += 1
                    for t in topics:
                        try:
                            name = getattr(t, 'name', None) or (t.get('name') if isinstance(t, dict) else None)
                        except Exception:
                            name = None
                        if name:
                            uniq_topics.add(str(name))
            coverage = {'scored_items': int(total), 'scored_with_topics': int(with_topics), 'unique_topics': int(len(uniq_topics))}
        except Exception:
            coverage = {'scored_items': 0, 'scored_with_topics': 0, 'unique_topics': 0}
    except Exception as e:
        logger.warning(f"Failed to compute diagnostics for student {student.student_id}: {e}")
        metrics = {}
        problem_topics = []
        problem_tasks = []
        coverage = {'scored_items': 0, 'scored_with_topics': 0, 'unique_topics': 0}

    checkpoints = []
    try:
        checkpoints = StudentDiagnosticCheckpoint.query.filter_by(student_id=student.student_id).order_by(
            StudentDiagnosticCheckpoint.created_at.desc(),
            StudentDiagnosticCheckpoint.checkpoint_id.desc(),
        ).limit(50).all()
    except Exception:
        checkpoints = []

    can_save = (not current_user.is_student()) and (not current_user.is_parent()) and (has_permission(current_user, 'diagnostics.checkpoints') or is_tutor_actor)

    # простые рекомендации MVP: топ-3 слабых темы → "сделать 2 урока + 10 задач"
    recommendations = []
    try:
        for t in problem_topics[:3]:
            recommendations.append({
                'topic': getattr(t, 'name', None) or (t.get('name') if isinstance(t, dict) else None),
                'plan': '2 урока по теме + 10 задач (с разбором ошибок)',
            })
    except Exception:
        recommendations = []

    return render_template(
        'student_diagnostics.html',
        student=student,
        metrics=metrics,
        problem_topics=problem_topics,
        problem_tasks=problem_tasks,
        coverage=coverage,
        recommendations=recommendations,
        checkpoints=checkpoints,
        can_save=can_save,
    )


@students_bp.route('/student/<int:student_id>/diagnostics/checkpoints/create', methods=['POST'])
@login_required
def student_diagnostics_checkpoint_create(student_id: int):
    """Сохранить контрольную точку диагностики (учитель/админ)."""
    student = _guard_student_access(student_id)
    is_tutor_actor = bool(getattr(current_user, 'is_tutor', None) and current_user.is_tutor())
    if current_user.is_student() or current_user.is_parent() or (not (has_permission(current_user, 'diagnostics.checkpoints') or is_tutor_actor)):
        from flask import abort
        abort(403)

    from app.students.stats_service import StatsService
    from app.models import StudentDiagnosticCheckpoint

    kind = (request.form.get('kind') or 'checkpoint').strip().lower()
    if kind not in {'baseline', 'checkpoint'}:
        kind = 'checkpoint'
    note = (request.form.get('note') or '').strip() or None

    metrics = None
    problem_topics = None
    recommendations = None
    try:
        stats = StatsService(student.student_id)
        metrics = stats.get_summary_metrics()
        problem_topics = stats.get_problem_topics(threshold=60)[:10]
        recs = []
        for t in problem_topics[:3]:
            name = getattr(t, 'name', None) or (t.get('name') if isinstance(t, dict) else None)
            if name:
                recs.append({'topic': name, 'plan': '2 урока по теме + 10 задач (с разбором ошибок)'})
        recommendations = recs
    except Exception as e:
        logger.warning(f"Failed to compute diagnostics snapshot for student {student.student_id}: {e}")

    cp = StudentDiagnosticCheckpoint(
        student_id=student.student_id,
        created_by_user_id=current_user.id,
        kind=kind,
        note=note,
        metrics=metrics,
        problem_topics=problem_topics,
        recommendations=recommendations,
    )
    db.session.add(cp)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='diagnostics_checkpoint_create', entity='StudentDiagnosticCheckpoint', error=str(e))
        flash('Не удалось сохранить контрольную точку.', 'danger')
        return redirect(url_for('students.student_diagnostics', student_id=student.student_id))

    try:
        audit_logger.log(action='diagnostics_checkpoint_create', entity='StudentDiagnosticCheckpoint', entity_id=cp.checkpoint_id, status='success', metadata={'student_id': student.student_id, 'kind': kind})
    except Exception:
        pass

    flash('Контрольная точка сохранена.', 'success')
    return redirect(url_for('students.student_diagnostics', student_id=student.student_id))


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
    if current_user.is_student() or current_user.is_parent():
        flash('У вас недостаточно прав для создания уроков.', 'danger')
        return redirect(url_for('students.student_profile', student_id=student_id))

    if not has_permission(current_user, 'lesson.create'):
        flash('У вас недостаточно прав для создания уроков.', 'danger')
        return redirect(url_for('students.student_profile', student_id=student_id))

    # RBAC/Data-scope: тьютор видит только своих учеников, родитель/ученик — только себя/детей
    student = _guard_student_access(student_id)
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
