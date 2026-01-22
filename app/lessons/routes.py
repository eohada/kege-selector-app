"""
Маршруты для управления уроками
"""
import logging
import os
import json
from werkzeug.utils import secure_filename
from app.uploads.service import save_uploaded_file
from flask import render_template, request, redirect, url_for, flash, jsonify, make_response, current_app  # current_app нужен для определения типа БД (Postgres)
from flask_login import login_required, current_user  # comment
from sqlalchemy import text, or_  # text нужен для setval(pg_get_serial_sequence(...)) при сбитых sequences
from sqlalchemy.exc import OperationalError, ProgrammingError
from app.utils.db_migrations import ensure_schema_columns
from app.auth.rbac_utils import check_access, get_user_scope

from app.lessons import lessons_bp
from app.lessons.forms import LessonForm, ensure_introductory_without_homework
from app.lessons.utils import get_sorted_assignments, perform_auto_check, normalize_answer_value  # comment
from app.models import Lesson, LessonTask, LessonTaskAttempt, LessonMessage, Student, Tasks, LessonTaskTeacherComment, User, LessonMaterialLink, MaterialAsset, GradebookEntry, Assignment, Submission, db, moscow_now, MOSCOW_TZ, TOMSK_TZ
from sqlalchemy.orm.attributes import flag_modified
from core.audit_logger import audit_logger
from app.notifications.service import notify_student_and_parents
from app.models import FamilyTie  # для доступа родителя к диалогам

logger = logging.getLogger(__name__)

def _record_lesson_task_attempt(lesson_task: LessonTask) -> None:
    """Записываем попытку сдачи (снимок) для LessonTask."""
    if not lesson_task:
        return
    try:
        last_no = (
            db.session.query(db.func.max(LessonTaskAttempt.attempt_no))
            .filter(LessonTaskAttempt.lesson_task_id == lesson_task.lesson_task_id)
            .scalar()
        )
        next_no = int(last_no or 0) + 1
    except Exception:
        next_no = 1

    attempt = LessonTaskAttempt(
        lesson_task_id=lesson_task.lesson_task_id,
        attempt_no=next_no,
        student_submission=lesson_task.student_submission,
        submission_files=lesson_task.submission_files,
        submission_correct=lesson_task.submission_correct,
        status=(lesson_task.status or 'submitted'),
    )
    db.session.add(attempt)

def _upsert_gradebook_from_lesson_review(lesson: Lesson, assignment_type: str, payload: dict, actor_user_id: int | None = None) -> None:
    """
    Создаём/обновляем запись журнала по итогу проверки урока (классная комната).
    Создаём только если итоговый статус = graded.
    """
    if not lesson:
        return
    if (payload.get('status') or '').strip().lower() != 'graded':
        return

    # Upsert по (student_id, kind=lesson, lesson_id, category)
    entry = GradebookEntry.query.filter_by(
        student_id=lesson.student_id,
        kind='lesson',
        lesson_id=lesson.lesson_id,
        category=(assignment_type or '').strip().lower() or None,
    ).first()

    title = lesson.topic or 'Урок'
    if assignment_type:
        title = f"{title} · {assignment_type}"

    if not entry:
        entry = GradebookEntry(
            student_id=lesson.student_id,
            kind='lesson',
            lesson_id=lesson.lesson_id,
            category=(assignment_type or '').strip().lower() or None,
            created_by_user_id=actor_user_id,
            title=title,
        )
        db.session.add(entry)

    entry.title = title
    entry.comment = (payload.get('notes') or '').strip() or None
    entry.score = payload.get('score', None)
    entry.max_score = payload.get('max_score', None)
    entry.grade_text = (payload.get('grade_text') or '').strip() or None
    entry.weight = payload.get('weight', 1) or 1


def _resolve_accessible_student_ids(scope: dict) -> list[int]:
    """
    Приводим data-scope к Student.student_id (потому что Lesson.student_id указывает на Students.student_id).
    В Enrollment/FamilyTie у нас хранятся User.id ученика, поэтому маппим через email,
    а также держим fallback для окружений, где Student.student_id совпадает с User.id.
    """
    if not scope or scope.get('can_see_all'):
        return []

    user_ids = scope.get('student_ids') or []
    if not user_ids:
        return []

    student_ids: list[int] = []

    try:
        student_users = User.query.filter(User.id.in_(user_ids)).all()
        emails = [u.email for u in student_users if u and u.email]
        if emails:
            students_by_email = Student.query.filter(Student.email.in_(emails)).all()
            student_ids.extend([s.student_id for s in students_by_email if s])
    except Exception as e:
        logger.warning(f"Failed to map scope user_ids->student_ids via email: {e}")

    # Fallback: если в окружении Student.student_id == User.id
    try:
        students_by_id = Student.query.filter(Student.student_id.in_(user_ids)).all()
        student_ids.extend([s.student_id for s in students_by_id if s])
    except Exception as e:
        logger.warning(f"Failed to map scope user_ids->student_ids via id fallback: {e}")

    # unique, stable order
    seen = set()
    out: list[int] = []
    for sid in student_ids:
        if sid not in seen:
            seen.add(sid)
            out.append(sid)
    return out

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
    
    # При редактировании правильно заполняем дату и часовой пояс
    if request.method == 'GET':
        # Определяем часовой пояс пользователя
        user_tz = 'moscow'
        if current_user.profile and current_user.profile.timezone:
            if 'tomsk' in current_user.profile.timezone.lower() or 'Asia/Tomsk' in current_user.profile.timezone:
                user_tz = 'tomsk'
        
        form.timezone.data = user_tz
        
        # Конвертируем lesson_date из БД (naive в московском времени) в локальное время для формы
        if lesson.lesson_date:
            # lesson_date в БД хранится как naive datetime в московском времени
            lesson_date_msk = lesson.lesson_date.replace(tzinfo=MOSCOW_TZ) if lesson.lesson_date.tzinfo is None else lesson.lesson_date
            
            # Конвертируем в часовой пояс пользователя
            if user_tz == 'tomsk':
                lesson_date_local = lesson_date_msk.astimezone(TOMSK_TZ)
            else:
                lesson_date_local = lesson_date_msk
            
            # Убираем timezone для DateTimeLocalField (он ожидает naive datetime)
            form.lesson_date.data = lesson_date_local.replace(tzinfo=None)

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
    # Удаление урока должно быть недоступно ученику/родителю.
    # Для тьютора разрешаем, если есть хотя бы права управления уроками/расписанием
    # (т.к. `lesson.delete` может быть не включён в RolePermission/DEFAULT_ROLE_PERMISSIONS).
    try:
        if current_user.is_student() or current_user.is_parent():
            from flask import abort
            abort(403)
    except Exception:
        from flask import abort
        abort(403)

    try:
        can_delete = bool(
            (current_user.is_admin() or current_user.is_creator())
            or has_permission(current_user, 'tools.schedule')
            or has_permission(current_user, 'lesson.edit')
            or has_permission(current_user, 'lesson.create')
        )
    except Exception:
        can_delete = False

    if not can_delete:
        from flask import abort
        abort(403)

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
    from app.schedule.routes import _parse_local_datetime
    
    lesson = Lesson.query.get_or_404(lesson_id)

    # Обновление темы
    lesson.topic = request.form.get('topic', lesson.topic)
    lesson.notes = request.form.get('notes', lesson.notes)
    lesson.homework = request.form.get('homework', lesson.homework)
    
    # Обновление времени урока, если указано
    lesson_date_str = request.form.get('lesson_date', '').strip()
    lesson_time_str = request.form.get('lesson_time', '').strip()
    if lesson_date_str and lesson_time_str:
        try:
            # Определяем часовой пояс пользователя
            user_tz = 'moscow'
            if current_user.profile and current_user.profile.timezone:
                if 'tomsk' in current_user.profile.timezone.lower() or 'Asia/Tomsk' in current_user.profile.timezone:
                    user_tz = 'tomsk'
            
            new_lesson_date = _parse_local_datetime(lesson_date_str, lesson_time_str, user_tz)
            lesson.lesson_date = new_lesson_date
        except Exception as e:
            logger.warning(f"Ошибка при обновлении времени урока {lesson_id}: {e}")
    
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
    
    # --- AUTO-FIX FOR SCHEMA ISSUES ---
    # Try to load lesson. If it fails due to missing columns, run migration and retry.
    lesson = None
    max_retries = 2
    for attempt in range(max_retries):
        try:
            # Оптимизация: используем joinedload для избежания N+1 проблем
            lesson = Lesson.query.options(
                db.joinedload(Lesson.student),
                db.joinedload(Lesson.homework_tasks).joinedload(LessonTask.task)
            ).get_or_404(lesson_id)
            break # Success
        except (OperationalError, ProgrammingError) as e:
            db.session.rollback()
            if attempt < max_retries - 1 and ('column' in str(e).lower() or 'does not exist' in str(e).lower()):
                logger.warning(f"Database schema issue detected in lesson_homework_view ({e}). Attempting auto-fix...")
                try:
                    ensure_schema_columns(current_app)
                    logger.info("Schema fix applied. Retrying query...")
                    continue
                except Exception as fix_err:
                    logger.error(f"Failed to auto-fix schema: {fix_err}")
                    raise e # Re-raise original error if fix fails
            else:
                raise e # Re-raise if not a schema issue or retries exhausted
    # ----------------------------------

    student = lesson.student
    # Контент-блоки (конструктор): приводим к list для шаблона
    content_blocks = []
    try:
        cb = lesson.content_blocks
        if isinstance(cb, str):
            cb = json.loads(cb)
        if isinstance(cb, list):
            content_blocks = cb
    except Exception:
        content_blocks = []
    homework_tasks = get_sorted_assignments(lesson, 'homework')  # comment
    # Материалы из библиотеки, прикрепленные к уроку
    library_materials = []
    try:
        links = LessonMaterialLink.query.filter_by(lesson_id=lesson.lesson_id).options(
            db.joinedload(LessonMaterialLink.asset)
        ).order_by(LessonMaterialLink.order_index.asc(), LessonMaterialLink.link_id.asc()).all()
        for link in links:
            if not link.asset or not link.asset.is_active:
                continue
            a = link.asset
            library_materials.append({
                'link_id': link.link_id,
                'asset_id': a.asset_id,
                'name': a.title,
                'url': a.file_url,
                'type': (a.file_name.split('.')[-1].lower() if a.file_name and '.' in a.file_name else 'file'),
                'source': 'library'
            })
    except Exception as e:
        logger.warning(f"Failed to load library materials for lesson {lesson_id}: {e}")
    is_student_view = current_user.is_student()  # comment
    is_parent_view = current_user.is_parent()  # comment
    is_read_only = False  # comment
    if is_parent_view:  # comment
        is_read_only = True  # comment
    elif is_student_view:  # comment
        # Если есть задачи "на доработку" — разрешаем редактирование/пересдачу даже после общей финализации.
        finalized = _is_submission_finalized(lesson, homework_tasks)  # comment
        has_returned = any((t.status or '').lower() == 'returned' for t in (homework_tasks or []))  # comment
        is_read_only = bool(finalized and (not has_returned))  # comment
    viewer_timezone = 'Europe/Moscow'  # comment
    try:  # comment
        if current_user and getattr(current_user, 'profile', None) and current_user.profile.timezone:  # comment
            viewer_timezone = current_user.profile.timezone  # comment
    except Exception:  # comment
        viewer_timezone = 'Europe/Moscow'  # comment
    return render_template('lesson_homework.html',
                           lesson=lesson,
                           student=student,
                           homework_tasks=homework_tasks,
                           assignment_type='homework',  # comment
                           is_student_view=is_student_view,  # comment
                           is_parent_view=is_parent_view,  # comment
                           is_read_only=is_read_only,  # comment
                           viewer_timezone=viewer_timezone,  # comment
                           review_summary=(lesson.review_summaries or {}).get('homework', {}),  # comment
                           library_materials=library_materials,  # comment
                           content_blocks=content_blocks)  # comment

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
    content_blocks = []
    try:
        cb = lesson.content_blocks
        if isinstance(cb, str):
            cb = json.loads(cb)
        if isinstance(cb, list):
            content_blocks = cb
    except Exception:
        content_blocks = []
    classwork_tasks = get_sorted_assignments(lesson, 'classwork')  # comment
    library_materials = []
    try:
        links = LessonMaterialLink.query.filter_by(lesson_id=lesson.lesson_id).options(
            db.joinedload(LessonMaterialLink.asset)
        ).order_by(LessonMaterialLink.order_index.asc(), LessonMaterialLink.link_id.asc()).all()
        for link in links:
            if not link.asset or not link.asset.is_active:
                continue
            a = link.asset
            library_materials.append({
                'link_id': link.link_id,
                'asset_id': a.asset_id,
                'name': a.title,
                'url': a.file_url,
                'type': (a.file_name.split('.')[-1].lower() if a.file_name and '.' in a.file_name else 'file'),
                'source': 'library'
            })
    except Exception as e:
        logger.warning(f"Failed to load library materials for lesson {lesson_id}: {e}")
    is_student_view = current_user.is_student()  # comment
    is_parent_view = current_user.is_parent()  # comment
    is_read_only = False  # comment
    if is_parent_view:  # comment
        is_read_only = True  # comment
    elif is_student_view:  # comment
        finalized = _is_submission_finalized(lesson, classwork_tasks)  # comment
        has_returned = any((t.status or '').lower() == 'returned' for t in (classwork_tasks or []))  # comment
        is_read_only = bool(finalized and (not has_returned))  # comment
    viewer_timezone = 'Europe/Moscow'  # comment
    try:  # comment
        if current_user and getattr(current_user, 'profile', None) and current_user.profile.timezone:  # comment
            viewer_timezone = current_user.profile.timezone  # comment
    except Exception:  # comment
        viewer_timezone = 'Europe/Moscow'  # comment
    return render_template('lesson_homework.html',
                           lesson=lesson,
                           student=student,
                           homework_tasks=classwork_tasks,
                           assignment_type='classwork',  # comment
                           is_student_view=is_student_view,  # comment
                           is_parent_view=is_parent_view,  # comment
                           is_read_only=is_read_only,  # comment
                           viewer_timezone=viewer_timezone,  # comment
                           review_summary=(lesson.review_summaries or {}).get('classwork', {}),  # comment
                           library_materials=library_materials,  # comment
                           content_blocks=content_blocks)  # comment

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
    content_blocks = []
    try:
        cb = lesson.content_blocks
        if isinstance(cb, str):
            cb = json.loads(cb)
        if isinstance(cb, list):
            content_blocks = cb
    except Exception:
        content_blocks = []
    exam_tasks = get_sorted_assignments(lesson, 'exam')  # comment
    library_materials = []
    try:
        links = LessonMaterialLink.query.filter_by(lesson_id=lesson.lesson_id).options(
            db.joinedload(LessonMaterialLink.asset)
        ).order_by(LessonMaterialLink.order_index.asc(), LessonMaterialLink.link_id.asc()).all()
        for link in links:
            if not link.asset or not link.asset.is_active:
                continue
            a = link.asset
            library_materials.append({
                'link_id': link.link_id,
                'asset_id': a.asset_id,
                'name': a.title,
                'url': a.file_url,
                'type': (a.file_name.split('.')[-1].lower() if a.file_name and '.' in a.file_name else 'file'),
                'source': 'library'
            })
    except Exception as e:
        logger.warning(f"Failed to load library materials for lesson {lesson_id}: {e}")
    is_student_view = current_user.is_student()  # comment
    is_parent_view = current_user.is_parent()  # comment
    is_read_only = False  # comment
    if is_parent_view:  # comment
        is_read_only = True  # comment
    elif is_student_view:  # comment
        finalized = _is_submission_finalized(lesson, exam_tasks)  # comment
        has_returned = any((t.status or '').lower() == 'returned' for t in (exam_tasks or []))  # comment
        is_read_only = bool(finalized and (not has_returned))  # comment
    viewer_timezone = 'Europe/Moscow'  # comment
    try:  # comment
        if current_user and getattr(current_user, 'profile', None) and current_user.profile.timezone:  # comment
            viewer_timezone = current_user.profile.timezone  # comment
    except Exception:  # comment
        viewer_timezone = 'Europe/Moscow'  # comment
    return render_template('lesson_homework.html',
                           lesson=lesson,
                           student=student,
                           homework_tasks=exam_tasks,
                           assignment_type='exam',  # comment
                           is_student_view=is_student_view,  # comment
                           is_parent_view=is_parent_view,  # comment
                           is_read_only=is_read_only,  # comment
                           viewer_timezone=viewer_timezone,  # comment
                           review_summary=(lesson.review_summaries or {}).get('exam', {}),  # comment
                           library_materials=library_materials,  # comment
                           content_blocks=content_blocks)  # comment


@lessons_bp.route('/lesson/<int:lesson_id>/review-summary/<assignment_type>', methods=['POST'])
@login_required
@check_access('assignment.grade')
def lesson_review_summary_save(lesson_id: int, assignment_type: str):
    """Сохранение итогов проверки по уроку (для конкретного типа работ)."""
    assignment_type = (assignment_type or '').strip().lower()
    if assignment_type not in {'homework', 'classwork', 'exam'}:
        return jsonify({'success': False, 'error': 'Некорректный тип'}), 400

    lesson = Lesson.query.options(
        db.joinedload(Lesson.student),
        db.joinedload(Lesson.homework_tasks).joinedload(LessonTask.attempts),
    ).get_or_404(lesson_id)

    # RBAC: проверяем доступ к ученику урока
    scope = get_user_scope(current_user)
    if not scope.get('can_see_all'):
        accessible_student_ids = _resolve_accessible_student_ids(scope)
        if lesson.student_id not in accessible_student_ids:
            return jsonify({'success': False, 'error': 'Forbidden'}), 403

    data = request.get_json(silent=True) or {}
    percent = data.get('percent', None)
    notes = (data.get('notes') or '').strip()
    summary_status = (data.get('status') or '').strip().lower()
    score = data.get('score', None)
    max_score = data.get('max_score', None)
    grade_text = (data.get('grade_text') or '').strip()
    weight = data.get('weight', None)

    if percent is not None:
        try:
            percent = int(percent)
        except Exception:
            return jsonify({'success': False, 'error': 'percent должен быть числом'}), 400
        if percent < 0 or percent > 100:
            return jsonify({'success': False, 'error': 'percent должен быть 0..100'}), 400

    if summary_status and summary_status not in {'graded', 'returned', 'submitted'}:
        return jsonify({'success': False, 'error': 'Некорректный статус'}), 400

    if score is not None:
        try:
            score = int(score)
        except Exception:
            return jsonify({'success': False, 'error': 'score должен быть числом'}), 400
        if score < 0:
            return jsonify({'success': False, 'error': 'score должен быть >= 0'}), 400

    if max_score is not None:
        try:
            max_score = int(max_score)
        except Exception:
            return jsonify({'success': False, 'error': 'max_score должен быть числом'}), 400
        if max_score < 0:
            return jsonify({'success': False, 'error': 'max_score должен быть >= 0'}), 400
        if score is not None and max_score and score > max_score:
            return jsonify({'success': False, 'error': 'score не может быть больше max_score'}), 400

    if weight is not None:
        try:
            weight = int(weight)
        except Exception:
            return jsonify({'success': False, 'error': 'weight должен быть числом'}), 400
        if weight < 1 or weight > 10:
            return jsonify({'success': False, 'error': 'weight должен быть 1..10'}), 400

    summaries = lesson.review_summaries or {}
    if not isinstance(summaries, dict):
        summaries = {}

    payload = {
        'percent': percent,
        'notes': notes,
        'status': summary_status or None,
        'score': score,
        'max_score': max_score,
        'grade_text': grade_text or None,
        'weight': weight,
        'updated_at': moscow_now().isoformat()
    }
    summaries[assignment_type] = payload
    lesson.review_summaries = summaries

    # Важно: очередь "Проверка" работает по LessonTask.status.
    # Если учитель сохранил итог (graded/returned), то логично массово обновить статусы задач,
    # иначе в "Проверке" визуально ничего не меняется.
    try:
        if payload.get('status') in ('graded', 'returned'):
            q = LessonTask.query.filter(LessonTask.lesson_id == lesson.lesson_id)
            if assignment_type == 'homework':
                q = q.filter((LessonTask.assignment_type == 'homework') | (LessonTask.assignment_type.is_(None)))
            else:
                q = q.filter(LessonTask.assignment_type == assignment_type)

            if payload.get('status') == 'graded':
                # Отмечаем сданные/возвращённые как проверенные
                q = q.filter(LessonTask.status.in_(['submitted', 'returned']))
                q.update({'status': 'graded'}, synchronize_session=False)
            elif payload.get('status') == 'returned':
                # Возвращаем сданные на доработку
                q = q.filter(LessonTask.status.in_(['submitted']))
                q.update({'status': 'returned'}, synchronize_session=False)
    except Exception as e:
        logger.warning(f"Could not bulk update LessonTask statuses from review summary: {e}")

    # Авто-журнал: создаём/обновляем запись только если итог = graded
    try:
        _upsert_gradebook_from_lesson_review(lesson, assignment_type, payload, actor_user_id=current_user.id)
    except Exception as e:
        logger.warning(f"Could not upsert gradebook entry from lesson review: {e}")

    # Уведомление ученику/родителю при значимом статусе
    try:
        st = lesson.student
        if st and payload.get('status') in ('graded', 'returned'):
            if payload.get('status') == 'graded':
                title = 'Итог по уроку сохранён'
                kind = 'lesson_review_graded'
            else:
                title = 'Урок возвращён на доработку'
                kind = 'lesson_review_returned'
            notify_student_and_parents(
                st,
                kind=kind,
                title=title,
                body=(payload.get('notes') or '').strip() or None,
                link_url=url_for('lessons.lesson_homework_view', lesson_id=lesson.lesson_id),
                meta={'lesson_id': lesson.lesson_id, 'assignment_type': assignment_type, 'status': payload.get('status')},
            )
    except Exception as e:
        logger.warning(f"Failed to notify student about lesson review summary: {e}")

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to save review summary: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Ошибка сохранения'}), 500

    return jsonify({'success': True, 'summary': summaries[assignment_type]})


@lessons_bp.route('/reviews/queue')
@login_required
@check_access('assignment.grade')
def review_queue():
    """
    Единый журнал проверок преподавателя:
    - задачи в классной комнате (LessonTask)
    - работы новой системы (Submission/Assignment)
    Показывает очередь "что проверить" с фильтрами.
    """
    # Параметры фильтров
    status = (request.args.get('status') or 'submitted').strip().lower()
    source = (request.args.get('source') or 'all').strip().lower()  # all|lessons|assignments
    assignment_type = (request.args.get('assignment_type') or '').strip().lower()  # homework|classwork|exam
    student_query = (request.args.get('student') or '').strip()

    allowed_statuses = {'submitted', 'returned', 'graded', 'pending'}
    if status not in allowed_statuses:
        status = 'submitted'

    if source not in {'all', 'lessons', 'assignments'}:
        source = 'all'

    allowed_types = {'homework', 'classwork', 'exam'}
    if assignment_type and assignment_type not in allowed_types:
        assignment_type = ''

    scope = get_user_scope(current_user)
    accessible_student_ids = None
    if not scope.get('can_see_all'):
        accessible_student_ids = _resolve_accessible_student_ids(scope) or []

    # Счётчики для фильтра статуса (в пределах текущих фильтров type/student/source)
    status_counts_lessons = {'submitted': 0, 'returned': 0, 'graded': 0, 'pending': 0}
    status_counts_assignments = {'submitted': 0, 'returned': 0, 'graded': 0, 'pending': 0}

    try:
        ql = LessonTask.query.join(Lesson, Lesson.lesson_id == LessonTask.lesson_id).join(Student, Student.student_id == Lesson.student_id)
        if assignment_type:
            ql = ql.filter((LessonTask.assignment_type == assignment_type) | (LessonTask.assignment_type.is_(None) if assignment_type == 'homework' else False))
        if student_query:
            ql = ql.filter(Student.name.ilike(f'%{student_query}%'))
        if accessible_student_ids is not None:
            if not accessible_student_ids:
                ql = ql.filter(False)
            else:
                ql = ql.filter(Lesson.student_id.in_(accessible_student_ids))
        rows = ql.with_entities(LessonTask.status, db.func.count(LessonTask.lesson_task_id)).group_by(LessonTask.status).all()
        for st, cnt in rows:
            key = (st or '').strip().lower()
            if key in status_counts_lessons:
                status_counts_lessons[key] = int(cnt or 0)
    except Exception:
        pass

    try:
        qs0 = Submission.query.join(Student, Student.student_id == Submission.student_id).join(Assignment, Assignment.assignment_id == Submission.assignment_id)
        if assignment_type:
            qs0 = qs0.filter(Assignment.assignment_type == assignment_type)
        if student_query:
            qs0 = qs0.filter(Student.name.ilike(f'%{student_query}%'))
        if not scope.get('can_see_all'):
            qs0 = qs0.filter(Assignment.created_by_id == current_user.id)
            if accessible_student_ids is not None:
                if not accessible_student_ids:
                    qs0 = qs0.filter(False)
                else:
                    qs0 = qs0.filter(Submission.student_id.in_(accessible_student_ids))
        rows2 = qs0.with_entities(Submission.status, db.func.count(Submission.submission_id)).group_by(Submission.status).all()
        raw = { (s or '').upper(): int(c or 0) for s, c in rows2 }
        status_counts_assignments['submitted'] = raw.get('SUBMITTED', 0) + raw.get('LATE', 0)
        status_counts_assignments['returned'] = raw.get('RETURNED', 0)
        status_counts_assignments['graded'] = raw.get('GRADED', 0)
        status_counts_assignments['pending'] = raw.get('ASSIGNED', 0) + raw.get('IN_PROGRESS', 0)
    except Exception:
        pass

    if source == 'lessons':
        status_counts = status_counts_lessons
    elif source == 'assignments':
        status_counts = status_counts_assignments
    else:
        status_counts = {
            k: int(status_counts_lessons.get(k, 0)) + int(status_counts_assignments.get(k, 0))
            for k in ['submitted', 'returned', 'graded', 'pending']
        }

    lesson_cards = []
    if source in {'all', 'lessons'}:
        q = LessonTask.query.options(
            db.joinedload(LessonTask.lesson).joinedload(Lesson.student),
            db.joinedload(LessonTask.task),
        ).join(Lesson, Lesson.lesson_id == LessonTask.lesson_id).join(Student, Student.student_id == Lesson.student_id)

        q = q.filter(LessonTask.status == status)
        if assignment_type:
            q = q.filter((LessonTask.assignment_type == assignment_type) | (LessonTask.assignment_type.is_(None) if assignment_type == 'homework' else False))

        if student_query:
            q = q.filter(Student.name.ilike(f'%{student_query}%'))

        if accessible_student_ids is not None:
            if not accessible_student_ids:
                q = q.filter(False)
            else:
                q = q.filter(Lesson.student_id.in_(accessible_student_ids))

        by_lesson = {}
        tasks = q.order_by(Lesson.lesson_date.desc(), LessonTask.lesson_task_id.asc()).all()
        for lt in tasks:
            if not lt.lesson:
                continue
            lid = lt.lesson.lesson_id
            if lid not in by_lesson:
                by_lesson[lid] = {
                    'lesson': lt.lesson,
                    'student': lt.lesson.student,
                    'tasks': [],
                    '_seen_task_ids': set(),
                }
            # safety: не допускаем дублей задач в одной карточке (на случай странных JOIN/данных)
            try:
                tid = int(getattr(lt, 'lesson_task_id', 0) or 0)
            except Exception:
                tid = 0
            if tid and tid in by_lesson[lid]['_seen_task_ids']:
                continue
            if tid:
                by_lesson[lid]['_seen_task_ids'].add(tid)
            by_lesson[lid]['tasks'].append(lt)

        # сохраняем порядок по дате урока
        for item in by_lesson.values():
            # чистим служебное поле
            try:
                item.pop('_seen_task_ids', None)
            except Exception:
                pass
            lesson_cards.append(item)
        lesson_cards.sort(key=lambda x: (x['lesson'].lesson_date or moscow_now()), reverse=True)

    assignment_cards = []
    if source in {'all', 'assignments'}:
        # mapping фильтра статуса с UI -> Submission.status
        status_map = {
            'submitted': ['SUBMITTED', 'LATE'],
            'returned': ['RETURNED'],
            'graded': ['GRADED'],
            'pending': ['ASSIGNED', 'IN_PROGRESS'],
        }
        statuses = status_map.get(status, ['SUBMITTED', 'LATE'])

        qs = Submission.query.options(
            db.joinedload(Submission.assignment),
            db.joinedload(Submission.student),
        ).join(Student, Student.student_id == Submission.student_id).join(Assignment, Assignment.assignment_id == Submission.assignment_id)

        qs = qs.filter(Submission.status.in_(statuses))
        if assignment_type:
            qs = qs.filter(Assignment.assignment_type == assignment_type)
        if student_query:
            qs = qs.filter(or_(
                Student.name.ilike(f'%{student_query}%'),
                Assignment.title.ilike(f'%{student_query}%'),
            ))

        # доступ в assignments.submission_grade_view дополнительно ограничен created_by_id
        if not scope.get('can_see_all'):
            qs = qs.filter(Assignment.created_by_id == current_user.id)
            if accessible_student_ids is not None:
                if not accessible_student_ids:
                    qs = qs.filter(False)
                else:
                    qs = qs.filter(Submission.student_id.in_(accessible_student_ids))

        now_local = moscow_now()

        def _sub_key(s: Submission):
            # приоритет: просрочено по дедлайну > LATE > время сдачи/обновления
            try:
                deadline = s.assignment.deadline if (s and s.assignment) else None
            except Exception:
                deadline = None
            overdue_flag = 1 if (deadline and now_local > deadline and (s.status or '').upper() in ['SUBMITTED', 'LATE']) else 0
            late_flag = 1 if (s.status or '').upper() == 'LATE' else 0
            dt = (s.submitted_at or s.updated_at or s.assigned_at or now_local)
            return (overdue_flag, late_flag, dt)

        by_assignment = {}
        subs = qs.order_by(Submission.submitted_at.desc().nullslast(), Submission.assigned_at.desc()).limit(400).all()
        for sub in subs:
            a = sub.assignment
            if not a:
                continue
            aid = a.assignment_id
            if aid not in by_assignment:
                by_assignment[aid] = {
                    'assignment': a,
                    'submissions': [],
                    '_sort_key': _sub_key(sub),
                }
            by_assignment[aid]['submissions'].append(sub)
            # обновляем sort_key по самой свежей сдаче
            if _sub_key(sub) > by_assignment[aid]['_sort_key']:
                by_assignment[aid]['_sort_key'] = _sub_key(sub)

        assignment_cards = list(by_assignment.values())
        assignment_cards.sort(key=lambda x: x.get('_sort_key') or (0, 0, now_local), reverse=True)
        # чистим служебное поле
        for c in assignment_cards:
            c.pop('_sort_key', None)

    return render_template(
        'review_queue.html',
        lesson_cards=lesson_cards,
        assignment_cards=assignment_cards,
        status=status,
        source=source,
        assignment_type=assignment_type,
        student_query=student_query,
        status_counts=status_counts,
    )


@lessons_bp.route('/reviews/lesson/<int:lesson_id>/bulk', methods=['POST'])
@login_required
@check_access('assignment.grade')
def review_bulk_update_lesson(lesson_id: int):
    """
    Быстрые массовые действия по уроку: отметить все сданные задачи как проверенные или вернуть на доработку.
    """
    action = (request.form.get('action') or '').strip().lower()
    assignment_type = (request.form.get('assignment_type') or '').strip().lower()
    status_filter = (request.form.get('status') or 'submitted').strip().lower()
    student_query = (request.form.get('student') or '').strip()

    if action not in {'mark_graded', 'mark_returned'}:
        flash('Некорректное действие.', 'danger')
        return redirect(url_for('lessons.review_queue', status=status_filter, assignment_type=assignment_type, student=student_query))

    lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)

    # RBAC: проверяем доступ к ученику урока
    scope = get_user_scope(current_user)
    if not scope.get('can_see_all'):
        accessible_student_ids = _resolve_accessible_student_ids(scope)
        if lesson.student_id not in accessible_student_ids:
            return make_response('Forbidden', 403)

    q = LessonTask.query.filter(LessonTask.lesson_id == lesson_id, LessonTask.status == 'submitted')
    if assignment_type in {'homework', 'classwork', 'exam'}:
        q = q.filter(LessonTask.assignment_type == assignment_type)

    tasks = q.all()
    if not tasks:
        flash('Нет сданных задач для массового действия.', 'info')
        return redirect(url_for('lessons.review_queue', status=status_filter, assignment_type=assignment_type, student=student_query))

    new_status = 'graded' if action == 'mark_graded' else 'returned'
    for lt in tasks:
        lt.status = new_status
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Bulk update failed for lesson {lesson_id}: {e}", exc_info=True)
        flash('Ошибка при массовом обновлении статуса.', 'danger')
        return redirect(url_for('lessons.review_queue', status=status_filter, assignment_type=assignment_type, student=student_query))

    if new_status == 'graded':
        flash('Отмечено как «Проверено».', 'success')
    else:
        flash('Отмечено как «На доработку».', 'success')
    return redirect(url_for('lessons.review_queue', status=status_filter, assignment_type=assignment_type, student=student_query))


@lessons_bp.route('/lesson/<int:lesson_id>/task/<int:lesson_task_id>/teacher-comment/add', methods=['POST'])  # comment
@login_required  # comment
def lesson_task_teacher_comment_add(lesson_id, lesson_task_id):  # comment
    """Добавить комментарий преподавателя (мульти-комментарии)"""  # comment
    if current_user.is_student() or current_user.is_parent():  # comment
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403  # comment
    lesson_task = LessonTask.query.filter_by(lesson_id=lesson_id, lesson_task_id=lesson_task_id).first_or_404()  # comment
    data = request.get_json(silent=True) or {}  # comment
    body = (data.get('body') or '').strip()  # comment
    if not body:  # comment
        return jsonify({'success': False, 'error': 'Пустой комментарий'}), 400  # comment
    comment = LessonTaskTeacherComment(lesson_task_id=lesson_task.lesson_task_id, author_user_id=getattr(current_user, 'id', None), body=body)  # comment
    db.session.add(comment)  # comment
    # Для обратной совместимости держим последний комментарий в поле teacher_comment
    lesson_task.teacher_comment = body  # comment
    try:  # comment
        db.session.commit()  # comment
    except Exception as e:  # comment
        db.session.rollback()  # comment
        logger.error(f"Failed to add teacher comment: {e}", exc_info=True)  # comment
        return jsonify({'success': False, 'error': 'Ошибка сохранения'}), 500  # comment
    tz = 'Europe/Moscow'  # comment
    try:  # comment
        if getattr(current_user, 'profile', None) and current_user.profile.timezone:  # comment
            tz = current_user.profile.timezone  # comment
    except Exception:  # comment
        tz = 'Europe/Moscow'  # comment
    # format_dt_tz фильтр доступен в шаблонах; здесь отдаем ISO и сырой текст, отображение делаем на клиенте
    return jsonify({  # comment
        'success': True,  # comment
        'comment': {  # comment
            'comment_id': comment.comment_id,  # comment
            'body': comment.body,  # comment
            'created_at': comment.created_at.isoformat() if comment.created_at else None,  # comment
            'timezone': tz,  # comment
        }  # comment
    })  # comment


@lessons_bp.route('/lesson/teacher-comment/<int:comment_id>/update', methods=['POST'])  # comment
@login_required  # comment
def lesson_task_teacher_comment_update(comment_id):  # comment
    """Редактировать комментарий преподавателя (только автор)."""  # comment
    if current_user.is_student() or current_user.is_parent():  # comment
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403  # comment
    comment = LessonTaskTeacherComment.query.filter_by(comment_id=comment_id).first_or_404()  # comment
    if comment.author_user_id and getattr(current_user, 'id', None) != comment.author_user_id:  # comment
        return jsonify({'success': False, 'error': 'Можно редактировать только свои комментарии'}), 403  # comment
    data = request.get_json(silent=True) or {}  # comment
    body = (data.get('body') or '').strip()  # comment
    if not body:  # comment
        return jsonify({'success': False, 'error': 'Пустой комментарий'}), 400  # comment
    comment.body = body  # comment
    # sync last comment to LessonTask.teacher_comment if this comment is latest
    try:  # comment
        lesson_task = LessonTask.query.filter_by(lesson_task_id=comment.lesson_task_id).first()  # comment
        if lesson_task:  # comment
            latest = LessonTaskTeacherComment.query.filter_by(lesson_task_id=lesson_task.lesson_task_id).order_by(LessonTaskTeacherComment.created_at.asc(), LessonTaskTeacherComment.comment_id.asc()).all()  # comment
            if latest and latest[-1].comment_id == comment.comment_id:  # comment
                lesson_task.teacher_comment = body  # comment
        db.session.commit()  # comment
    except Exception as e:  # comment
        db.session.rollback()  # comment
        logger.error(f"Failed to update teacher comment: {e}", exc_info=True)  # comment
        return jsonify({'success': False, 'error': 'Ошибка сохранения'}), 500  # comment
    return jsonify({'success': True, 'comment_id': comment.comment_id, 'body': comment.body})  # comment


@lessons_bp.route('/lesson/teacher-comment/<int:comment_id>/delete', methods=['POST'])  # comment
@login_required  # comment
def lesson_task_teacher_comment_delete(comment_id):  # comment
    """Удалить комментарий преподавателя (только автор)."""  # comment
    if current_user.is_student() or current_user.is_parent():  # comment
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403  # comment
    comment = LessonTaskTeacherComment.query.filter_by(comment_id=comment_id).first_or_404()  # comment
    if comment.author_user_id and getattr(current_user, 'id', None) != comment.author_user_id:  # comment
        return jsonify({'success': False, 'error': 'Можно удалять только свои комментарии'}), 403  # comment
    lesson_task_id = comment.lesson_task_id  # comment
    try:  # comment
        db.session.delete(comment)  # comment
        db.session.commit()  # comment
    except Exception as e:  # comment
        db.session.rollback()  # comment
        logger.error(f"Failed to delete teacher comment: {e}", exc_info=True)  # comment
        return jsonify({'success': False, 'error': 'Ошибка удаления'}), 500  # comment
    # Re-sync latest to LessonTask.teacher_comment
    try:  # comment
        lesson_task = LessonTask.query.filter_by(lesson_task_id=lesson_task_id).first()  # comment
        if lesson_task:  # comment
            remaining = LessonTaskTeacherComment.query.filter_by(lesson_task_id=lesson_task_id).order_by(LessonTaskTeacherComment.created_at.asc(), LessonTaskTeacherComment.comment_id.asc()).all()  # comment
            lesson_task.teacher_comment = (remaining[-1].body if remaining else None)  # comment
            db.session.commit()  # comment
    except Exception:  # comment
        db.session.rollback()  # comment
    return jsonify({'success': True})  # comment


@lessons_bp.route('/lesson/<int:lesson_id>/tasks/bulk-update', methods=['POST'])  # comment
@login_required  # comment
def lesson_tasks_bulk_update(lesson_id):  # comment
    """Массовое обновление статусов/проверки задач урока (преподаватель)."""  # comment
    if current_user.is_student() or current_user.is_parent():  # comment
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403  # comment
    data = request.get_json(silent=True) or {}  # comment
    task_ids = data.get('task_ids') or []  # comment
    status = (data.get('status') or '').strip().lower()  # comment
    submission_correct = data.get('submission_correct', 'unset')  # comment
    if not isinstance(task_ids, list) or not task_ids:  # comment
        return jsonify({'success': False, 'error': 'Нет выбранных заданий'}), 400  # comment
    if status and status not in ('pending', 'submitted', 'graded', 'returned'):  # comment
        return jsonify({'success': False, 'error': 'Неверный статус'}), 400  # comment
    tasks = LessonTask.query.filter(LessonTask.lesson_id == lesson_id, LessonTask.lesson_task_id.in_(task_ids)).all()  # comment
    if not tasks:  # comment
        return jsonify({'success': False, 'error': 'Задания не найдены'}), 404  # comment
    for t in tasks:  # comment
        if status:  # comment
            t.status = status  # comment
        if submission_correct != 'unset':  # comment
            # допускаем true/false/null
            if submission_correct in (True, False, None):  # comment
                t.submission_correct = submission_correct  # comment
    try:  # comment
        db.session.commit()  # comment
    except Exception as e:  # comment
        db.session.rollback()  # comment
        logger.error(f"Failed bulk update: {e}", exc_info=True)  # comment
        return jsonify({'success': False, 'error': 'Ошибка сохранения'}), 500  # comment
    return jsonify({  # comment
        'success': True,  # comment
        'updated': [  # comment
            {  # comment
                'lesson_task_id': t.lesson_task_id,  # comment
                'status': (t.status or 'pending'),  # comment
                'submission_correct': t.submission_correct,  # comment
            } for t in tasks  # comment
        ]  # comment
    })  # comment


def _get_current_lesson_student(lesson):  # comment
    """Проверяем, что текущий пользователь - ученик этого урока"""  # comment
    if not current_user.is_student():  # comment
        return None  # comment
    # В некоторых окружениях email может быть пустым, а логин хранится в username
    ident = (current_user.email or current_user.username or '').strip()
    if not ident:  # comment
        return None  # comment
    student = Student.query.filter(db.func.lower(Student.email) == ident.lower()).first()  # comment
    if not student:  # comment
        return None  # comment
    if student.student_id != lesson.student_id:  # comment
        return None  # comment
    return student  # comment


def _is_submission_finalized(lesson, tasks):  # comment
    """После сдачи (submitted/graded) — финализация: редактирование запрещено, кроме задач со статусом returned."""  # comment
    if tasks and any((t.status or '').lower() in ('submitted', 'graded') for t in tasks):  # comment
        return True  # comment
    # Fallback для старых данных, где status еще не проставлялся
    return getattr(lesson, 'homework_status', None) == 'assigned_done'  # comment


def _is_task_editable_for_student(lesson, tasks, task):  # comment
    """Редактирование учеником: либо работа не финализирована, либо конкретная задача возвращена на доработку."""  # comment
    if (task.status or '').lower() == 'returned':  # comment
        return True  # comment
    return not _is_submission_finalized(lesson, tasks)  # comment


def _save_student_submissions(lesson, assignment_type):  # comment
    """Сохраняем ответы ученика (черновик). НЕ считаем автопроверку и не выставляем submission_correct."""  # comment
    tasks = get_sorted_assignments(lesson, assignment_type)  # comment
    is_finalized = _is_submission_finalized(lesson, tasks)  # comment
    for task in tasks:  # comment
        field_name = f'submission_{task.lesson_task_id}'  # comment
        # Если работа уже сдана — разрешаем правки только по возвращенным задачам
        if is_finalized and (task.status or '').lower() != 'returned':  # comment
            continue  # comment
        if field_name in request.form:  # comment
            value = request.form.get(field_name, '').strip()  # comment
            task.student_submission = value if value else None  # comment
    return tasks  # comment


def _submit_student_submissions(lesson, assignment_type):  # comment
    """Фиксируем ответы ученика и запускаем авто-проверку"""  # comment
    tasks = get_sorted_assignments(lesson, assignment_type)  # comment
    is_finalized = _is_submission_finalized(lesson, tasks)  # comment
    for task in tasks:  # comment
        # После сдачи повторно "сдаем" только возвращенные задачи
        if is_finalized and (task.status or '').lower() != 'returned':  # comment
            continue  # comment
        field_name = f'submission_{task.lesson_task_id}'  # comment
        value = request.form.get(field_name, '').strip()  # comment
        task.student_submission = value if value else None  # comment
        expected = (task.student_answer if task.student_answer else (task.task.answer if task.task and task.task.answer else '')) or ''  # comment
        if not expected:  # comment
            task.submission_correct = False  # comment
            task.status = 'submitted'  # comment
            continue  # comment
        if not value:  # comment
            task.submission_correct = False  # comment
            task.status = 'submitted'  # comment
            continue  # comment
        normalized_value = normalize_answer_value(value)  # comment
        normalized_expected = normalize_answer_value(expected)  # comment
        task.submission_correct = normalized_value == normalized_expected and normalized_expected != ''  # comment
        task.status = 'submitted'  # comment
        # Сохраняем попытку сдачи (история)
        try:
            _record_lesson_task_attempt(task)
        except Exception as e:
            logger.warning(f"Could not record LessonTaskAttempt for {task.lesson_task_id}: {e}")
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
    tasks = get_sorted_assignments(lesson, 'homework')  # comment
    if _is_submission_finalized(lesson, tasks) and not any((t.status or '').lower() == 'returned' for t in tasks):  # comment
        flash('Работа уже сдана. Изменения заблокированы.', 'warning')  # comment
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
    tasks = get_sorted_assignments(lesson, 'classwork')  # comment
    if _is_submission_finalized(lesson, tasks) and not any((t.status or '').lower() == 'returned' for t in tasks):  # comment
        flash('Работа уже сдана. Изменения заблокированы.', 'warning')  # comment
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
    tasks = get_sorted_assignments(lesson, 'exam')  # comment
    if _is_submission_finalized(lesson, tasks) and not any((t.status or '').lower() == 'returned' for t in tasks):  # comment
        flash('Работа уже сдана. Изменения заблокированы.', 'warning')  # comment
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
    tasks = get_sorted_assignments(lesson, 'homework')  # comment
    if _is_submission_finalized(lesson, tasks) and not any((t.status or '').lower() == 'returned' for t in tasks):  # comment
        flash('Работа уже сдана. Повторная сдача заблокирована.', 'warning')  # comment
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
    tasks = get_sorted_assignments(lesson, 'classwork')  # comment
    if _is_submission_finalized(lesson, tasks) and not any((t.status or '').lower() == 'returned' for t in tasks):  # comment
        flash('Работа уже сдана. Повторная сдача заблокирована.', 'warning')  # comment
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
    tasks = get_sorted_assignments(lesson, 'exam')  # comment
    if _is_submission_finalized(lesson, tasks) and not any((t.status or '').lower() == 'returned' for t in tasks):  # comment
        flash('Работа уже сдана. Повторная сдача заблокирована.', 'warning')  # comment
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

    if 'homework_result_percent' in request.form:  # comment
        percent_value = request.form.get('homework_result_percent', '').strip()  # comment
        if percent_value:  # comment
            try:  # comment
                percent_int = max(0, min(100, int(percent_value)))  # comment
                lesson.homework_result_percent = percent_int  # comment
            except ValueError:  # comment
                flash('Процент выполнения должен быть числом от 0 до 100', 'warning')  # comment
        else:  # comment
            lesson.homework_result_percent = None  # comment

    if 'homework_result_notes' in request.form:  # comment
        result_notes = request.form.get('homework_result_notes', '').strip()  # comment
        lesson.homework_result_notes = result_notes or None  # comment

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


@lessons_bp.route('/lesson/<int:lesson_id>/classwork-tasks/save', methods=['POST'])  # comment
@login_required  # comment
def lesson_classwork_save(lesson_id):  # comment
    """Сохранение ключей/комментариев для классной работы (преподаватель)"""  # comment
    if current_user.is_student() or current_user.is_parent():  # comment
        flash('Доступ запрещен', 'danger')  # comment
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment
    lesson = Lesson.query.get_or_404(lesson_id)  # comment
    tasks = get_sorted_assignments(lesson, 'classwork')  # comment
    for t in tasks:  # comment
        answer_key = f'answer_{t.lesson_task_id}'  # comment
        if answer_key in request.form:  # comment
            v = request.form.get(answer_key, '').strip()  # comment
            t.student_answer = v or None  # comment
        comment_key = f'teacher_comment_{t.lesson_task_id}'  # comment
        if comment_key in request.form:  # comment
            c = request.form.get(comment_key, '').strip()  # comment
            t.teacher_comment = c or None  # comment
        status_key = f'status_{t.lesson_task_id}'  # comment
        if status_key in request.form:  # comment
            s = (request.form.get(status_key, '') or '').strip().lower()  # comment
            if s in ('pending', 'submitted', 'graded', 'returned'):  # comment
                t.status = s  # comment
    try:  # comment
        db.session.commit()  # comment
    except Exception:  # comment
        db.session.rollback()  # comment
        raise  # comment
    flash('Данные сохранены!', 'success')  # comment
    return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment


@lessons_bp.route('/lesson/<int:lesson_id>/exam-tasks/save', methods=['POST'])  # comment
@login_required  # comment
def lesson_exam_save(lesson_id):  # comment
    """Сохранение ключей/комментариев для проверочной (преподаватель)"""  # comment
    if current_user.is_student() or current_user.is_parent():  # comment
        flash('Доступ запрещен', 'danger')  # comment
        return redirect(url_for('lessons.lesson_exam_view', lesson_id=lesson_id))  # comment
    lesson = Lesson.query.get_or_404(lesson_id)  # comment
    tasks = get_sorted_assignments(lesson, 'exam')  # comment
    for t in tasks:  # comment
        answer_key = f'answer_{t.lesson_task_id}'  # comment
        if answer_key in request.form:  # comment
            v = request.form.get(answer_key, '').strip()  # comment
            t.student_answer = v or None  # comment
        comment_key = f'teacher_comment_{t.lesson_task_id}'  # comment
        if comment_key in request.form:  # comment
            c = request.form.get(comment_key, '').strip()  # comment
            t.teacher_comment = c or None  # comment
        status_key = f'status_{t.lesson_task_id}'  # comment
        if status_key in request.form:  # comment
            s = (request.form.get(status_key, '') or '').strip().lower()  # comment
            if s in ('pending', 'submitted', 'graded', 'returned'):  # comment
                t.status = s  # comment
    try:  # comment
        db.session.commit()  # comment
    except Exception:  # comment
        db.session.rollback()  # comment
        raise  # comment
    flash('Данные сохранены!', 'success')  # comment
    return redirect(url_for('lessons.lesson_exam_view', lesson_id=lesson_id))  # comment


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


@lessons_bp.route('/lesson/<int:lesson_id>/task/<int:lesson_task_id>/teacher-feedback/save', methods=['POST'])  # comment
@login_required  # comment
def lesson_task_teacher_feedback_save(lesson_id, lesson_task_id):  # comment
    """Сохранение преподавательской проверки (комментарий/статус/ключ/оценка)"""  # comment
    if current_user.is_student() or current_user.is_parent():  # comment
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403  # comment
    lesson_task = LessonTask.query.filter_by(lesson_id=lesson_id, lesson_task_id=lesson_task_id).first_or_404()  # comment
    data = request.get_json(silent=True) or {}  # comment
    teacher_comment = (data.get('teacher_comment') or '').strip()  # comment
    answer_key = (data.get('answer_key') or '').strip()  # comment
    status = (data.get('status') or '').strip().lower()  # comment
    if 'answer_key' in data:  # comment
        lesson_task.student_answer = answer_key or None  # comment
    lesson_task.teacher_comment = teacher_comment or None  # comment
    if status in ('pending', 'submitted', 'graded', 'returned'):  # comment
        lesson_task.status = status  # comment
    if 'submission_correct' in data:  # comment
        lesson_task.submission_correct = data.get('submission_correct', None)  # comment
    try:  # comment
        db.session.commit()  # comment
    except Exception as e:  # comment
        db.session.rollback()  # comment
        logger.error(f"Failed to save teacher feedback: {e}", exc_info=True)  # comment
        return jsonify({'success': False, 'error': 'Ошибка сохранения'}), 500  # comment

    # Уведомление ученику/родителю при смене статуса на graded/returned
    try:
        if lesson_task.lesson and lesson_task.lesson.student and status in ('graded', 'returned'):
            if status == 'graded':
                title = 'Задание проверено'
                kind = 'lesson_task_graded'
            else:
                title = 'Задание возвращено на доработку'
                kind = 'lesson_task_returned'
            notify_student_and_parents(
                lesson_task.lesson.student,
                kind=kind,
                title=title,
                body=(teacher_comment or '').strip() or None,
                link_url=url_for('lessons.lesson_homework_view', lesson_id=lesson_id) + f"#task-{lesson_task.lesson_task_id}",
                meta={'lesson_id': lesson_id, 'lesson_task_id': lesson_task.lesson_task_id, 'status': status},
            )
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.warning(f"Failed to notify about lesson task status change: {e}")
    return jsonify({  # comment
        'success': True,  # comment
        'lesson_task_id': lesson_task.lesson_task_id,  # comment
        'status': (lesson_task.status or 'pending'),  # comment
        'teacher_comment': lesson_task.teacher_comment or '',  # comment
        'answer_key': lesson_task.student_answer or '',  # comment
        'submission_correct': lesson_task.submission_correct,  # comment
    })  # comment


@lessons_bp.route('/lesson/<int:lesson_id>/messages')
@login_required
def lesson_messages_list(lesson_id: int):
    lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)

    # Доступ: студент урока, родитель студента, или преподаватель с доступом к ученику
    scope = get_user_scope(current_user)
    if not scope.get('can_see_all'):
        if current_user.is_student():
            if not _get_current_lesson_student(lesson):
                return jsonify({'success': False, 'error': 'Forbidden'}), 403
        elif current_user.is_parent():
            ties = FamilyTie.query.filter_by(parent_id=current_user.id, is_confirmed=True).all()
            child_user_ids = [t.student_id for t in ties]
            # fallback: в некоторых окружениях Student.student_id == User.id ученика
            allowed_students = Student.query.filter(Student.student_id.in_(child_user_ids)).all()
            if lesson.student_id not in [s.student_id for s in allowed_students]:
                return jsonify({'success': False, 'error': 'Forbidden'}), 403
        else:
            accessible_student_ids = _resolve_accessible_student_ids(scope)
            if lesson.student_id not in accessible_student_ids:
                return jsonify({'success': False, 'error': 'Forbidden'}), 403

    msgs = (
        LessonMessage.query
        .filter_by(lesson_id=lesson.lesson_id)
        .order_by(LessonMessage.created_at.asc(), LessonMessage.message_id.asc())
        .limit(300)
        .all()
    )
    return jsonify({
        'success': True,
        'messages': [
            {
                'id': m.message_id,
                'author_user_id': m.author_user_id,
                'body': m.body,
                'created_at': m.created_at.isoformat() if m.created_at else None,
            }
            for m in msgs
        ]
    })


@lessons_bp.route('/lesson/<int:lesson_id>/messages/send', methods=['POST'])
@login_required
def lesson_messages_send(lesson_id: int):
    lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)
    if current_user.is_parent():
        return jsonify({'success': False, 'error': 'Родитель не может писать в диалог.'}), 403

    data = request.get_json(silent=True) if request.is_json else None
    body = (data.get('body') if isinstance(data, dict) else None) if request.is_json else request.form.get('body')
    body = (body or '').strip()
    if not body:
        return jsonify({'success': False, 'error': 'Пустое сообщение'}), 400
    if len(body) > 4000:
        return jsonify({'success': False, 'error': 'Слишком длинное сообщение'}), 400

    if current_user.is_student():
        if not _get_current_lesson_student(lesson):
            return jsonify({'success': False, 'error': 'Forbidden'}), 403
    else:
        scope = get_user_scope(current_user)
        if not scope.get('can_see_all'):
            accessible_student_ids = _resolve_accessible_student_ids(scope)
            if lesson.student_id not in accessible_student_ids:
                return jsonify({'success': False, 'error': 'Forbidden'}), 403

    # Дедуп: если пользователь много раз нажал "Отправить" (лаг/двойной клик),
    # не плодим одинаковые сообщения.
    # Окно маленькое, чтобы не мешать реальному повтору.
    try:
        from datetime import timedelta
        now_dt = moscow_now().replace(tzinfo=None)
        cutoff = now_dt - timedelta(seconds=4)
        prev = (
            LessonMessage.query
            .filter(
                LessonMessage.lesson_id == lesson.lesson_id,
                LessonMessage.author_user_id == current_user.id,
                LessonMessage.body == body,
                LessonMessage.created_at >= cutoff,
            )
            .order_by(LessonMessage.created_at.desc(), LessonMessage.message_id.desc())
            .first()
        )
        if prev:
            return jsonify({'success': True, 'message_id': prev.message_id, 'deduped': True})
    except Exception:
        pass

    msg = LessonMessage(lesson_id=lesson.lesson_id, author_user_id=current_user.id, body=body)
    db.session.add(msg)

    # Уведомление ученику/родителям, если пишет преподаватель
    try:
        if not current_user.is_student():
            notify_student_and_parents(
                lesson.student,
                kind='lesson_message',
                title='Новое сообщение по уроку',
                body=body,
                link_url=url_for('lessons.lesson_homework_view', lesson_id=lesson.lesson_id) + '#tab=chat',
                meta={'lesson_id': lesson.lesson_id},
            )
    except Exception as e:
        logger.warning(f"Failed to enqueue notification for lesson message: {e}")

    db.session.commit()

    try:
        audit_logger.log(
            action='lesson_message_send',
            entity='Lesson',
            entity_id=lesson.lesson_id,
            status='success',
            metadata={
                'message_id': msg.message_id,
                'author_user_id': current_user.id,
                'student_id': lesson.student_id,
                'body_len': len(body),
            },
        )
    except Exception:
        pass
    return jsonify({'success': True, 'message_id': msg.message_id})

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
    lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)
    scope = get_user_scope(current_user)
    if not scope.get('can_see_all'):
        accessible_student_ids = _resolve_accessible_student_ids(scope)
        if lesson.student_id not in accessible_student_ids:
            flash('Доступ запрещен', 'danger')
            return redirect(url_for('main.dashboard'))
    from app.lessons.export import lesson_export_md
    return lesson_export_md(lesson_id, 'homework')

@lessons_bp.route('/lesson/<int:lesson_id>/classwork-export-md')
@login_required
def lesson_classwork_export_md(lesson_id):
    """Экспорт классной работы в Markdown"""
    if current_user.is_student() or current_user.is_parent():  # comment
        flash('Доступ запрещен', 'danger')  # comment
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment
    lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)
    scope = get_user_scope(current_user)
    if not scope.get('can_see_all'):
        accessible_student_ids = _resolve_accessible_student_ids(scope)
        if lesson.student_id not in accessible_student_ids:
            flash('Доступ запрещен', 'danger')
            return redirect(url_for('main.dashboard'))
    from app.lessons.export import lesson_export_md
    return lesson_export_md(lesson_id, 'classwork')

@lessons_bp.route('/lesson/<int:lesson_id>/exam-export-md')
@login_required
def lesson_exam_export_md(lesson_id):
    """Экспорт проверочной работы в Markdown"""
    if current_user.is_student() or current_user.is_parent():  # comment
        flash('Доступ запрещен', 'danger')  # comment
        return redirect(url_for('lessons.lesson_exam_view', lesson_id=lesson_id))  # comment
    lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)
    scope = get_user_scope(current_user)
    if not scope.get('can_see_all'):
        accessible_student_ids = _resolve_accessible_student_ids(scope)
        if lesson.student_id not in accessible_student_ids:
            flash('Доступ запрещен', 'danger')
            return redirect(url_for('main.dashboard'))
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

@lessons_bp.route('/lesson/<int:lesson_id>/content/save', methods=['POST'])
@login_required
def lesson_content_save(lesson_id):
    """Сохранение контента урока (теории)"""
    if current_user.is_student() or current_user.is_parent():
         return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    
    lesson = Lesson.query.get_or_404(lesson_id)
    data = request.get_json()
    if data and 'content' in data:
        lesson.content = data['content']
        db.session.commit()
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'No content provided'}), 400


@lessons_bp.route('/lesson/<int:lesson_id>/content-blocks/save', methods=['POST'])
@login_required
def lesson_content_blocks_save(lesson_id):
    """Сохранение контента урока (конструктор блоков)."""
    if current_user.is_student() or current_user.is_parent():
         return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    lesson = Lesson.query.get_or_404(lesson_id)
    data = request.get_json(silent=True) or {}
    blocks = data.get('blocks', None)
    if not isinstance(blocks, list):
        return jsonify({'success': False, 'error': 'blocks must be a list'}), 400

    # sanitize structure
    cleaned = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        t = (b.get('type') or '').strip().lower()
        if t not in {'paragraph', 'callout', 'image', 'divider'}:
            continue
        item = {'type': t}
        if t == 'paragraph':
            item['text'] = (b.get('text') or '').strip()
        elif t == 'callout':
            item['title'] = (b.get('title') or '').strip()
            item['text'] = (b.get('text') or '').strip()
            item['tone'] = (b.get('tone') or 'info').strip().lower()
            if item['tone'] not in {'info', 'success', 'warning', 'danger'}:
                item['tone'] = 'info'
        elif t == 'image':
            item['url'] = (b.get('url') or '').strip()
            item['caption'] = (b.get('caption') or '').strip()
        elif t == 'divider':
            item['style'] = (b.get('style') or 'line').strip().lower()
            if item['style'] not in {'line', 'space'}:
                item['style'] = 'line'
        cleaned.append(item)

    lesson.content_blocks = cleaned
    flag_modified(lesson, "content_blocks")
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to save content blocks: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Ошибка сохранения'}), 500
    return jsonify({'success': True, 'count': len(cleaned)})

@lessons_bp.route('/lesson/<int:lesson_id>/student-notes/save', methods=['POST'])
@login_required
def lesson_student_notes_save(lesson_id):
    """Сохранение заметок ученика"""
    lesson = Lesson.query.get_or_404(lesson_id)
    # Здесь можно добавить проверку прав доступа
    
    data = request.get_json()
    if data and 'notes' in data:
        lesson.student_notes = data['notes']
        db.session.commit()
        try:
            audit_logger.log(
                action='lesson_student_notes_save',
                entity='Lesson',
                entity_id=lesson.lesson_id,
                status='success',
                metadata={
                    'student_id': lesson.student_id,
                    'notes_len': len((data.get('notes') or '')),
                },
            )
        except Exception:
            pass
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'No notes provided'}), 400

@lessons_bp.route('/lesson/<int:lesson_id>/upload', methods=['POST'])
@login_required
def lesson_upload_material(lesson_id):
    if current_user.is_student() or current_user.is_parent():
         return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    
    lesson = Lesson.query.get_or_404(lesson_id)
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No selected file'}), 400
        
    if file:
        # Create folder: static/uploads/lessons/<lesson_id>/
        upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'lessons', str(lesson_id))
        try:
            filename, file_path, _size = save_uploaded_file(
                file=file,
                base_folder=upload_folder,
                allowed_exts={'pdf', 'png', 'jpg', 'jpeg', 'webp', 'doc', 'docx', 'ppt', 'pptx', 'xlsx', 'xls', 'txt'},
                max_bytes=20 * 1024 * 1024,
            )
        except Exception as e:
            return jsonify({'success': False, 'error': f'Не удалось загрузить файл: {e}'}), 400
        
        # Update JSON materials
        materials = lesson.materials or []
        # Ensure it's a list
        if isinstance(materials, str):
            try:
                materials = json.loads(materials)
            except:
                materials = []
        
        stored_name = os.path.basename(file_path)
        new_material = {
            'name': filename,
            'url': url_for('uploads.lesson_file', lesson_id=lesson_id, stored_name=stored_name),
            'type': filename.split('.')[-1].lower() if '.' in filename else 'file',
            'storage_path': f"static/uploads/lessons/{lesson_id}/{stored_name}",
        }
        materials.append(new_material)
        lesson.materials = materials 
        
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(lesson, "materials")
        
        db.session.commit()
        return jsonify({'success': True, 'material': new_material})
        
    return jsonify({'success': False, 'error': 'Unknown error'}), 500

@lessons_bp.route('/lesson/<int:lesson_id>/material/delete', methods=['POST'])
@login_required
def lesson_delete_material(lesson_id):
    if current_user.is_student() or current_user.is_parent():
         return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
         
    lesson = Lesson.query.get_or_404(lesson_id)
    data = request.get_json()
    url_to_delete = data.get('url')
    
    if not url_to_delete:
        return jsonify({'success': False, 'error': 'No URL provided'}), 400
        
    materials = lesson.materials or []
    if isinstance(materials, str):
            try:
                materials = json.loads(materials)
            except:
                materials = []
                
    new_materials = [m for m in materials if m.get('url') != url_to_delete]
    
    if len(new_materials) != len(materials):
        lesson.materials = new_materials
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(lesson, "materials")
        db.session.commit()
        
        try:
             # Удаляем файл физически
             # Удаляем файл физически (берём последнюю часть URL, поддерживаем и /static/ и /files/)
             filename = (url_to_delete.split('?')[0] or '').split('/')[-1]
             file_path = os.path.join(current_app.root_path, 'static', 'uploads', 'lessons', str(lesson_id), secure_filename(filename))
             if os.path.exists(file_path):
                 os.remove(file_path)
        except Exception as e:
            logger.warning(f"Failed to delete file {url_to_delete}: {e}")

        return jsonify({'success': True})
    
    return jsonify({'success': False, 'error': 'Material not found'}), 404
