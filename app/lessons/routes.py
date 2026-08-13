from app.services.daily_service import DailyService
"""
Маршруты для управления уроками
"""
import logging
import os
import json
import uuid
from datetime import timezone as dt_timezone
from math import ceil
from werkzeug.utils import secure_filename
from app.uploads.service import save_uploaded_file
from flask import abort
from flask import render_template, request, redirect, url_for, flash, jsonify, make_response, current_app  # current_app нужен для определения типа БД (Postgres)
from flask_login import login_required, current_user  # comment
from sqlalchemy import text, or_  # text нужен для setval(pg_get_serial_sequence(...)) при сбитых sequences
from sqlalchemy.exc import OperationalError, ProgrammingError
from app.utils.db_migrations import ensure_schema_columns
from app.auth.rbac_utils import check_access, get_user_scope, has_permission

from app.lessons import lessons_bp
from app.lessons.forms import LessonForm, ensure_introductory_without_homework
from app.lessons.utils import get_sorted_assignments, get_assignment_blocks, perform_auto_check, normalize_answer_value  # comment
from app.models import Lesson, LessonTask, LessonTaskAttempt, LessonMessage, Student, Tasks, TaskSolution, LessonTaskTeacherComment, User, LessonMaterialLink, MaterialAsset, GradebookEntry, Assignment, Submission, LessonWhiteboard, MiroUserToken, Course, TheoryBlock, db, moscow_now, MOSCOW_TZ, TOMSK_TZ
from sqlalchemy.orm.attributes import flag_modified
from core.audit_logger import audit_logger
from app.notifications.service import notify_student_and_parents, enqueue_assignment_notification
from app.models import FamilyTie  # для доступа родителя к диалогам
from app.utils.relationship_scope import can_user_access_student
from app.utils.course_tasks import get_task_numbers
from app.utils.lesson_time import parse_local_lesson_datetime, lesson_storage_to_local

logger = logging.getLogger(__name__)


def _lesson_material_root(lesson_id: int) -> str:
    configured_root = (current_app.config.get('LESSON_UPLOAD_ROOT') or '').strip()
    # В production и sandbox /app/uploads подключён как persistent volume.
    base_root = configured_root or os.path.join(os.path.dirname(current_app.root_path), 'uploads', 'lessons')
    return os.path.join(base_root, str(int(lesson_id)))

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


def _lesson_balance_units(duration_minutes: int | None) -> int:
    try:
        duration = int(duration_minutes or 60)
    except Exception:
        duration = 60
    return max(1, ceil(duration / 60))

def _upsert_gradebook_from_lesson_review(lesson: Lesson, assignment_type: str, payload: dict, actor_user_id: int | None = None) -> None:
    """
    Создаём/обновляем запись журнала по итогу проверки урока (классная комната).
    Создаём только если итоговый статус = graded.
    """
    if not lesson:
        return
    if (payload.get('status') or '').strip().lower() != 'graded':
        return

    entry = GradebookEntry.query.filter_by(
        student_id=lesson.student_id,
        kind='lesson',
        lesson_id=lesson.lesson_id,
        category=(assignment_type or '').strip().lower() or None,
    ).first()

    title = lesson.topic or 'Урок'
    if assignment_type:
        at = (assignment_type or '').strip().lower()
        label_map = {'homework': 'ДЗ', 'classwork': 'КР', 'exam': 'Проверочная'}
        title = f"{title} · {label_map.get(at, at)}"

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
    В Enrollment/FamilyTie хранятся User.id ученика; маппим по user_id и fallback student_id==user.id.
    """
    if not scope or scope.get('can_see_all'):
        return []

    user_ids = scope.get('student_ids') or []
    if not user_ids:
        return []

    student_ids: list[int] = []

    try:
        by_user_id = Student.query.filter(Student.user_id.in_(user_ids)).all()
        student_ids.extend([s.student_id for s in by_user_id if s])
    except Exception as e:
        logger.warning(f"Failed to map scope user_ids->student_ids via user_id: {e}")
    try:
        students_by_id = Student.query.filter(Student.student_id.in_(user_ids)).all()
        student_ids.extend([s.student_id for s in students_by_id if s])
    except Exception as e:
        logger.warning(f"Failed to map scope user_ids->student_ids via id fallback: {e}")

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
    lesson = Lesson.query.options(
        db.joinedload(Lesson.student),
        db.joinedload(Lesson.homework_tasks).joinedload(LessonTask.task)
    ).get_or_404(lesson_id)
    student = lesson.student
    if current_user.is_student() or current_user.is_parent():
        from flask import abort
        abort(403)
    if not current_user.is_admin() and not current_user.is_creator():
        if not can_user_access_student(current_user, student_user_id=student.user_id):
            from flask import abort
            abort(403)
    form = LessonForm(obj=lesson)
    
    if request.method == 'GET':
        user_tz = 'moscow'
        if current_user.profile and current_user.profile.timezone:
            if 'tomsk' in current_user.profile.timezone.lower() or 'Asia/Tomsk' in current_user.profile.timezone:
                user_tz = 'tomsk'
        
        form.timezone.data = user_tz
        
        if lesson.lesson_date:
            lesson_date_local = lesson_storage_to_local(lesson.lesson_date, user_tz)
            form.lesson_date.data = lesson_date_local.replace(tzinfo=None) if lesson_date_local else None

    if form.validate_on_submit():
        ensure_introductory_without_homework(form)
        
        lesson_date_local = form.lesson_date.data
        timezone = form.timezone.data
        
        if lesson_date_local.tzinfo is not None:
            lesson_date_local = lesson_date_local.replace(tzinfo=None)
        lesson.lesson_date = parse_local_lesson_datetime(
            lesson_date_local.strftime('%Y-%m-%d'),
            lesson_date_local.strftime('%H:%M'),
            timezone,
        )
        
        lesson.lesson_type = form.lesson_type.data
        lesson.duration = form.duration.data
        lesson.status = form.status.data
        lesson.topic = form.topic.data
        lesson.notes = form.notes.data
        lesson.homework = form.homework.data
        lesson.homework_status = form.homework_status.data
        lesson.student_late = bool(getattr(form, 'student_late', None) and form.student_late.data)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise
        
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
    """Вход в страницу занятия (классная комната)."""
    mode = (request.args.get('mode') or '').strip().lower()
    if mode == 'edit':
        return redirect(url_for('lessons.lesson_edit', lesson_id=lesson_id))
    return lesson_classwork_view(lesson_id)


@lessons_bp.route('/lesson/<int:lesson_id>/classroom')
@login_required
def lesson_classroom_view(lesson_id):
    """Алиас для входа в классную комнату урока."""
    return lesson_classwork_view(lesson_id)

@lessons_bp.route('/lesson/<int:lesson_id>/delete', methods=['POST'])
@login_required
def lesson_delete(lesson_id):
    """Удаление урока"""
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
    """Начало урока: фиксируем started_at, опционально отмечаем опоздание."""
    from core.db_models import moscow_now
    lesson = Lesson.query.get_or_404(lesson_id)
    lesson.status = 'in_progress'
    now = moscow_now()
    lesson.started_at = now.replace(tzinfo=None)
    mark_late = request.form.get('student_late') in ('1', 'true', 'on', 'yes')
    if mark_late:
        lesson.student_late = True
    elif lesson.lesson_date:
        try:
            from datetime import timedelta
            ld = lesson.lesson_date
            if getattr(ld, 'tzinfo', None) is None:
                ld_utc = ld.replace(tzinfo=MOSCOW_TZ).astimezone(dt_timezone.utc)
            else:
                ld_utc = ld.astimezone(dt_timezone.utc)
            if now > ld_utc + timedelta(minutes=15):
                lesson.student_late = True
            else:
                lesson.student_late = False
        except Exception:
            pass
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise
    try:
        from app.telegram.notifications import notify_lesson_started_for_lesson
        notify_lesson_started_for_lesson(int(lesson.lesson_id), actor_user_id=current_user.id)
    except Exception:
        logger.warning('notify_lesson_started_for_lesson after lesson_start failed', exc_info=True)
    flash(f'Урок начат! Используй зеленую панель сверху для управления уроком.', 'success')
    return redirect(url_for('students.student_profile', student_id=lesson.student_id))

@lessons_bp.route('/lesson/<int:lesson_id>/complete', methods=['POST'])
@login_required
def lesson_complete(lesson_id):
    """Завершение урока"""
    from app.schedule.routes import _parse_local_datetime
    
    lesson = Lesson.query.get_or_404(lesson_id)

    lesson.topic = request.form.get('topic', lesson.topic)
    lesson.notes = request.form.get('notes', lesson.notes)
    lesson.homework = request.form.get('homework', lesson.homework)
    if 'student_late' in request.form:
        lesson.student_late = request.form.get('student_late') in ('1', 'true', 'on', 'yes')
    
    lesson_date_str = request.form.get('lesson_date', '').strip()
    lesson_time_str = request.form.get('lesson_time', '').strip()
    if lesson_date_str and lesson_time_str:
        try:
            user_tz = 'moscow'
            if current_user.profile and current_user.profile.timezone:
                if 'tomsk' in current_user.profile.timezone.lower() or 'Asia/Tomsk' in current_user.profile.timezone:
                    user_tz = 'tomsk'
            
            new_lesson_date = parse_local_lesson_datetime(lesson_date_str, lesson_time_str, user_tz)
            lesson.lesson_date = new_lesson_date
        except Exception as e:
            logger.warning(f"Ошибка при обновлении времени урока {lesson_id}: {e}")
    
    lesson.status = 'completed'

    try:
        if lesson.student and lesson.student.user_id:
            from app.models import UserSubscription
            active_sub = UserSubscription.query.filter_by(
                user_id=lesson.student.user_id,
                status='active'
            ).order_by(UserSubscription.ends_at.desc().nullslast()).first()
            balance_notice = None
            if active_sub and active_sub.lessons_remaining is not None and active_sub.lessons_remaining > 0:
                before = active_sub.lessons_remaining
                spent = _lesson_balance_units(lesson.duration)
                active_sub.lessons_remaining = max(0, active_sub.lessons_remaining - spent)
                logger.info(
                    f"Decreased lessons_remaining for user {lesson.student.user_id}: "
                    f"{before} -> {active_sub.lessons_remaining} (spent={spent})"
                )
                balance_notice = (before, active_sub.lessons_remaining, f'Списание после завершения урока #{lesson.lesson_id}')
    except Exception as e:
        logger.warning(f"Could not decrease lessons_remaining for lesson {lesson_id}: {e}")

    try:
        db.session.commit()
        if 'balance_notice' in locals() and balance_notice and lesson.student and lesson.student.user_id:
            try:
                from app.telegram.notifications import notify_lesson_balance_changed
                before, after, reason = balance_notice
                notify_lesson_balance_changed(
                    student_user_id=int(lesson.student.user_id),
                    before=before,
                    after=after,
                    reason=reason,
                    source='lesson',
                )
            except Exception:
                    logger.warning('Could not notify lesson balance change after commit for lesson %s', lesson_id, exc_info=True)
        try:
            from app.telegram.notifications import notify_lesson_finished_for_teacher
            notify_lesson_finished_for_teacher(
                lesson_id=int(lesson.lesson_id),
                teacher_user_id=int(current_user.id) if current_user and getattr(current_user, 'id', None) else None,
            )
        except Exception:
            logger.warning('Could not notify teacher about homework note for lesson %s', lesson_id, exc_info=True)
    except Exception as e:
        db.session.rollback()
        raise
    flash(f'Урок завершен и данные сохранены!', 'success')
    return redirect(url_for('students.student_profile', student_id=lesson.student_id))

def auto_complete_overdue_lessons():
    """Завершает уроки со статусом in_progress, когда прошла их длительность."""
    from core.db_models import moscow_now
    from datetime import timedelta
    now = moscow_now()
    now_naive = now.replace(tzinfo=None) if getattr(now, 'tzinfo', None) else now
    q = Lesson.query.filter(
        Lesson.status == 'in_progress',
        Lesson.started_at.isnot(None)
    )
    count = 0
    for lesson in q.all():
        try:
            st = lesson.started_at
            if getattr(st, 'tzinfo', None):
                st_naive = st.astimezone(MOSCOW_TZ).replace(tzinfo=None)
            else:
                st_naive = st
            if st_naive is None:
                continue
            threshold = st_naive + timedelta(minutes=int(lesson.duration or 60))
            if now_naive < threshold:
                continue
            lesson.status = 'completed'
            balance_notice = None
            if lesson.student and lesson.student.user_id:
                from app.models import UserSubscription
                active_sub = UserSubscription.query.filter_by(
                    user_id=lesson.student.user_id,
                    status='active'
                ).order_by(UserSubscription.ends_at.desc().nullslast()).first()
                if active_sub and active_sub.lessons_remaining is not None and active_sub.lessons_remaining > 0:
                    before = active_sub.lessons_remaining
                    spent = _lesson_balance_units(lesson.duration)
                    active_sub.lessons_remaining = max(0, active_sub.lessons_remaining - spent)
                    logger.info(
                        f"Auto-completed lesson {lesson.lesson_id}, decreased lessons_remaining for user {lesson.student.user_id}: "
                        f"{before} -> {active_sub.lessons_remaining} (spent={spent})"
                    )
                    balance_notice = (before, active_sub.lessons_remaining, f'Списание после авто-завершения урока #{lesson.lesson_id}')
            db.session.commit()
            if balance_notice and lesson.student and lesson.student.user_id:
                try:
                    from app.telegram.notifications import notify_lesson_balance_changed
                    before, after, reason = balance_notice
                    notify_lesson_balance_changed(
                        student_user_id=int(lesson.student.user_id),
                        before=before,
                        after=after,
                        reason=reason,
                        source='lesson',
                    )
                except Exception:
                    logger.warning('Could not notify auto-complete lesson balance change for lesson %s', lesson.lesson_id, exc_info=True)
            try:
                from app.telegram.notifications import notify_lesson_finished_for_teacher
                notify_lesson_finished_for_teacher(lesson_id=int(lesson.lesson_id))
            except Exception:
                logger.warning('Could not notify teacher about auto-complete homework note for lesson %s', lesson.lesson_id, exc_info=True)
            count += 1
        except Exception as e:
            db.session.rollback()
            logger.warning(f"Auto-complete lesson {lesson.lesson_id} failed: {e}")
    return count


@lessons_bp.route('/lesson/<int:lesson_id>/homework-tasks')
@login_required
def lesson_homework_view(lesson_id):
    """Домашние задания выдаются через раздел «Задания». Редирект на создание работы по уроку."""
    return redirect(url_for(
        'assignments.assignment_create',
        source='lesson',
        lesson_id=lesson_id,
        assignment_type='homework',
    ))

@lessons_bp.route('/api/lesson_room/check_task', methods=['POST'])
@login_required
def check_lesson_room_task_api():
    """API автопроверки ответа для интерактивной комнаты урока."""
    data = request.get_json(silent=True) or {}
    lesson_id = data.get('lesson_id')
    task_order = data.get('task_id')
    answer = (data.get('answer') or '').strip()

    if not lesson_id:
        return jsonify({'ok': False, 'error': 'Параметр lesson_id не указан'}), 400

    lesson = Lesson.query.get(lesson_id)
    if not lesson:
        return jsonify({'ok': False, 'error': 'Урок не найден'}), 404

    classwork_tasks = get_sorted_assignments(lesson, 'classwork')
    target_task = None
    if task_order and isinstance(task_order, int) and 1 <= task_order <= len(classwork_tasks):
        target_task = classwork_tasks[task_order - 1]
    elif classwork_tasks:
        target_task = classwork_tasks[0]

    if not target_task:
        return jsonify({'ok': False, 'error': 'В комнате нет задания для проверки.'}), 409

    expected = (getattr(target_task, 'student_answer', None) or (target_task.task.answer if target_task.task else '')) or ''
    target_task.student_submission = answer

    if expected:
        norm_sub = normalize_answer_value(answer)
        norm_exp = normalize_answer_value(expected)
        is_correct = (norm_sub == norm_exp) and bool(norm_exp)
    else:
        is_correct = True

    target_task.submission_correct = is_correct
    target_task.status = 'submitted'
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error saving task check answer: {e}")

    return jsonify({
        'ok': True,
        'is_correct': is_correct,
        'message': 'Ответ верный 🎉' if is_correct else 'Неверно, попробуйте еще раз'
    })


def _lesson_studio_is_teacher() -> bool:
    from flask import session
    if not current_user or not current_user.is_authenticated:
        return False
    active_role = session.get('sandbox_role') or session.get('role') or getattr(current_user, 'role', '')
    if active_role == 'student':
        return False
    return bool(
        active_role in {'teacher', 'tutor', 'admin', 'creator'} or
        current_user.is_admin() or
        current_user.is_creator() or
        getattr(current_user, 'role', '') in {'teacher', 'tutor'}
    )


def _lesson_studio_access(lesson: Lesson) -> None:
    student = lesson.student
    allowed = can_user_access_student(current_user, student_user_id=getattr(student, 'user_id', None), student_platform_id=getattr(student, 'platform_id', None))
    if not allowed and current_user.is_student():
        allowed = bool(_get_current_lesson_student(lesson))
    if not allowed and not (current_user.is_admin() or current_user.is_creator()):
        abort(403)


def _default_lesson_studio_state(lesson: Lesson) -> dict:
    duration_minutes = max(15, int(getattr(lesson, 'duration', 60) or 60))
    preparation_minutes = max(5, round(duration_minutes * 0.15))
    reflection_minutes = max(5, round(duration_minutes * 0.15))
    practice_minutes = max(5, duration_minutes - preparation_minutes - reflection_minutes)
    return {
        'phase': 'preparation', 'active_task_id': None, 'active_pane': 'work', 'follow_student': False,
        'timer': {'mode': 'phase', 'seconds': preparation_minutes * 60, 'running': False, 'updated_at': None},
        'phase_timers': {
            'preparation': preparation_minutes * 60,
            'practice': practice_minutes * 60,
            'reflection': reflection_minutes * 60,
        },
        'phase_durations': {
            'preparation': preparation_minutes * 60,
            'practice': practice_minutes * 60,
            'reflection': reflection_minutes * 60,
        },
        'agenda': [
            {'id': 'warmup', 'title': 'Старт и цель урока', 'done': False},
            {'id': 'practice', 'title': 'Практика и разбор задач', 'done': False},
            {'id': 'reflection', 'title': 'Рефлексия и план до следующего урока', 'done': False},
        ],
        'student_signal': None, 'teacher_private_note': '',
        'student_checkpoint': {'understanding': None, 'blocker': '', 'submitted_at': None},
        'guidance': {'next_step': '', 'hints': [], 'updated_at': None},
        'board': {'strokes': [], 'revision': 0, 'updated_at': None},
        'outcome': {'completed': [], 'repeat': [], 'homework': '', 'published': False},
    }


def _lesson_studio_state(lesson: Lesson) -> dict:
    state = _default_lesson_studio_state(lesson)
    review_summaries = getattr(lesson, 'review_summaries', None) or {}
    stored = review_summaries.get('_studio') if isinstance(review_summaries, dict) else None
    if isinstance(stored, dict):
        state.update({key: value for key, value in stored.items() if key in state})
        if not isinstance(stored.get('phase_durations'), dict):
            state['phase_durations'] = dict(state['phase_timers'])
        # Состояния, созданные до появления отдельных таймеров этапов, не должны
        # продолжать показывать один общий таймер на весь урок.
        if not isinstance(stored.get('phase_timers'), dict):
            state['timer'] = {
                'mode': 'phase',
                'seconds': state['phase_timers'].get(state.get('phase'), state['phase_timers']['preparation']),
                'running': False,
                'updated_at': None,
            }
    return state


def _lesson_studio_state_for_viewer(state: dict, *, is_teacher: bool) -> dict:
    """Never serialize the teacher's private context into a student response."""
    visible = dict(state or {})
    if not is_teacher:
        visible.pop('teacher_private_note', None)
    return visible


def _lesson_studio_course_id(lesson: Lesson) -> int | None:
    """Определяет курс урока без доверия параметрам браузера.

    У старых уроков exam_course_id может быть пустым. В этом случае Studio
    использует активный курс платформы — так же, как основной раздел теории.
    """
    if getattr(lesson, 'exam_course_id', None):
        return int(lesson.exam_course_id)
    active_course = Course.query.filter_by(is_active=True).order_by(Course.id).first()
    return active_course.id if active_course else None


def _save_lesson_studio_state(lesson: Lesson, state: dict) -> None:
    summaries = dict(getattr(lesson, 'review_summaries', None) or {})
    summaries['_studio'] = state
    lesson.review_summaries = summaries
    flag_modified(lesson, 'review_summaries')
    db.session.commit()
    from app.lessons.lesson_socket import emit_lesson_studio_updated
    emit_lesson_studio_updated(lesson.lesson_id, _lesson_studio_state_for_viewer(state, is_teacher=False))


@lessons_bp.route('/lesson/<int:lesson_id>/studio/state')
@login_required
def lesson_studio_state_get(lesson_id: int):
    lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)
    _lesson_studio_access(lesson)
    is_teacher = _lesson_studio_is_teacher()
    return jsonify({'success': True, 'state': _lesson_studio_state_for_viewer(_lesson_studio_state(lesson), is_teacher=is_teacher), 'is_teacher': is_teacher})


@lessons_bp.route('/lesson/<int:lesson_id>/studio/state', methods=['POST'])
@login_required
def lesson_studio_state_save(lesson_id: int):
    lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)
    _lesson_studio_access(lesson)
    if not _lesson_studio_is_teacher():
        return jsonify({'success': False, 'error': 'Управлять сценарием урока может только преподаватель'}), 403
    payload = request.get_json(silent=True) or {}
    state = _lesson_studio_state(lesson)
    for key in ('phase', 'active_task_id', 'active_theory_block_id', 'active_pane', 'follow_student', 'timer', 'phase_timers', 'phase_durations', 'agenda', 'teacher_private_note', 'guidance', 'outcome'):
        if key in payload:
            state[key] = payload[key]
    guidance = state.get('guidance')
    phase_timers = state.get('phase_timers')
    phase_durations = state.get('phase_durations')
    if not isinstance(state.get('timer'), dict) or not isinstance(state.get('agenda'), list) or len(state['agenda']) > 30:
        return jsonify({'success': False, 'error': 'Некорректное состояние урока'}), 400
    if not isinstance(guidance, dict):
        return jsonify({'success': False, 'error': 'Некорректные подсказки преподавателя'}), 400
    if state.get('phase') not in {'preparation', 'practice', 'reflection'}:
        return jsonify({'success': False, 'error': 'Некорректный этап урока'}), 400
    if state.get('active_pane') not in {'control', 'work', 'board', 'meeting', 'materials', 'theory', 'scenario', 'outcome'} or not isinstance(state.get('follow_student'), bool):
        return jsonify({'success': False, 'error': 'Некорректная синхронизация интерфейса'}), 400
    theory_block_id = state.get('active_theory_block_id')
    if theory_block_id is not None:
        try:
            theory_block_id = int(theory_block_id)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'Некорректный материал теории'}), 400
        lesson_course_id = _lesson_studio_course_id(lesson)
        if not lesson_course_id or not TheoryBlock.query.filter_by(id=theory_block_id, course_id=lesson_course_id).first():
            return jsonify({'success': False, 'error': 'Материал теории не относится к курсу урока'}), 400
        state['active_theory_block_id'] = theory_block_id
    if not isinstance(phase_timers, dict) or not isinstance(phase_durations, dict):
        return jsonify({'success': False, 'error': 'Некорректные таймеры этапов'}), 400
    normalized_phase_timers, normalized_phase_durations = {}, {}
    for phase in ('preparation', 'practice', 'reflection'):
        try:
            seconds = int(phase_timers.get(phase))
            duration_seconds = int(phase_durations.get(phase))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'Некорректные таймеры этапов'}), 400
        if not 0 <= seconds <= 4 * 60 * 60 or not 60 <= duration_seconds <= 4 * 60 * 60:
            return jsonify({'success': False, 'error': 'Таймер этапа должен быть от 1 минуты до 4 часов'}), 400
        normalized_phase_timers[phase] = seconds
        normalized_phase_durations[phase] = duration_seconds
    state['phase_timers'] = normalized_phase_timers
    state['phase_durations'] = normalized_phase_durations
    timer = state['timer']
    try:
        timer_seconds = int(timer.get('seconds'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Некорректное значение таймера'}), 400
    if not 0 <= timer_seconds <= 4 * 60 * 60 or not isinstance(timer.get('running'), bool):
        return jsonify({'success': False, 'error': 'Некорректное состояние таймера'}), 400
    state['timer'] = {
        'mode': 'phase',
        'seconds': timer_seconds,
        'running': timer.get('running', False),
        'updated_at': moscow_now().isoformat(),
        'completed_at': timer.get('completed_at') if timer_seconds == 0 else None,
    }
    next_step = str(guidance.get('next_step') or '').strip()
    hints = guidance.get('hints') or []
    if not isinstance(hints, list) or len(next_step) > 2_000 or len(hints) > 10:
        return jsonify({'success': False, 'error': 'Некорректные подсказки преподавателя'}), 400
    state['guidance'] = {
        'next_step': next_step,
        'hints': [str(hint).strip() for hint in hints if str(hint).strip()][:10],
        'updated_at': moscow_now().isoformat(),
    }
    _save_lesson_studio_state(lesson, state)
    return jsonify({'success': True, 'state': _lesson_studio_state_for_viewer(state, is_teacher=_lesson_studio_is_teacher())})


def _normalize_lesson_board_stroke(raw_stroke: object) -> dict | None:
    if not isinstance(raw_stroke, dict):
        return None
    tool = str(raw_stroke.get('tool') or 'pen').strip().lower()
    if tool not in {'pen', 'eraser', 'line', 'rectangle', 'ellipse', 'text', 'image'}:
        return None
    raw_points = raw_stroke.get('points')
    minimum_points = 1 if tool in {'text', 'image'} else 2
    if not isinstance(raw_points, list) or not minimum_points <= len(raw_points) <= 350:
        return None
    points = []
    for raw_point in raw_points:
        if not isinstance(raw_point, dict):
            return None
        try:
            x, y = float(raw_point.get('x')), float(raw_point.get('y'))
        except (TypeError, ValueError):
            return None
        if not -1000000 <= x <= 1000000 or not -1000000 <= y <= 1000000:
            return None
        points.append({'x': round(x, 5), 'y': round(y, 5)})
    color = str(raw_stroke.get('color') or '#312E81').lower()
    if color not in {'#312e81', '#0f172a', '#dc2626', '#2563eb', '#059669', '#ea580c'}:
        color = '#312e81'
    try:
        width = int(raw_stroke.get('width', 4))
    except (TypeError, ValueError):
        width = 4
    stroke = {'tool': tool, 'points': points, 'color': color, 'width': max(1, min(width, 48))}
    if tool == 'text':
        text_value = str(raw_stroke.get('text') or '').strip()
        if not text_value or len(text_value) > 500:
            return None
        stroke['text'] = text_value
    if tool == 'image':
        image_url = str(raw_stroke.get('url') or '').strip()
        if not image_url.startswith('/files/lessons/'):
            return None
        try:
            image_width = float(raw_stroke.get('image_width', .25))
            image_height = float(raw_stroke.get('image_height', .25))
        except (TypeError, ValueError):
            return None
        stroke.update({'url': image_url, 'image_width': image_width, 'image_height': image_height})
    return stroke


@lessons_bp.route('/lesson/<int:lesson_id>/studio/board', methods=['POST'])
@login_required
def lesson_studio_board_update(lesson_id: int):
    """Append or clear a shared drawing stroke for the individual lesson board."""
    lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)
    _lesson_studio_access(lesson)
    payload = request.get_json(silent=True) or {}
    action = str(payload.get('action') or 'append').strip().lower()
    state = _lesson_studio_state(lesson)
    board = state.get('board') if isinstance(state.get('board'), dict) else {'strokes': [], 'revision': 0}
    strokes = board.get('strokes') if isinstance(board.get('strokes'), list) else []
    if action == 'clear':
        if not _lesson_studio_is_teacher():
            return jsonify({'success': False, 'error': 'Очищать доску может только преподаватель'}), 403
        strokes = []
    elif action == 'rewrite':
        if not _lesson_studio_is_teacher() and state.get('follow_student'):
            return jsonify({'success': False, 'error': 'Нет прав'}), 403
        new_strokes = payload.get('strokes', [])
        if isinstance(new_strokes, list):
            strokes = []
            for s in new_strokes:
                ns = _normalize_lesson_board_stroke(s)
                if ns: strokes.append(ns)
    elif action == 'undo':
        if len(strokes) > 0:
            strokes.pop()
    elif action == 'append':
        stroke = _normalize_lesson_board_stroke(payload.get('stroke'))
        if not stroke:
            return jsonify({'success': False, 'error': 'Некорректный штрих доски'}), 400
        stroke['author'] = 'teacher' if _lesson_studio_is_teacher() else 'student'
        strokes = [*strokes[-399:], stroke]
    else:
        return jsonify({'success': False, 'error': 'Неизвестное действие доски'}), 400
    try:
        revision = int(board.get('revision') or 0) + 1
    except (TypeError, ValueError):
        revision = 1
    state['board'] = {'strokes': strokes, 'revision': revision, 'updated_at': moscow_now().isoformat()}
    _save_lesson_studio_state(lesson, state)
    return jsonify({'success': True, 'board': state['board']})


@lessons_bp.route('/lesson/<int:lesson_id>/studio/board/image', methods=['POST'])
@login_required
def lesson_studio_board_image(lesson_id: int):
    """Store a board image as a lesson material, then let the board reference only that local URL."""
    lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)
    _lesson_studio_access(lesson)
    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'success': False, 'error': 'Выберите изображение'}), 400
    try:
        filename, file_path, _size = save_uploaded_file(
            file=file,
            base_folder=_lesson_material_root(lesson_id),
            allowed_exts={'png', 'jpg', 'jpeg', 'webp', 'gif'},
            max_bytes=8 * 1024 * 1024,
        )
    except Exception as exc:
        return jsonify({'success': False, 'error': f'Не удалось загрузить изображение: {exc}'}), 400
    stored_name = os.path.basename(file_path)
    return jsonify({'success': True, 'name': filename, 'url': url_for('uploads.lesson_file', lesson_id=lesson_id, stored_name=stored_name)})


@lessons_bp.route('/lesson/<int:lesson_id>/studio/pointer', methods=['POST'])
@login_required
def lesson_studio_pointer(lesson_id: int):
    """Broadcast an ephemeral cursor/laser signal; it is deliberately never stored in lesson history."""
    lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)
    _lesson_studio_access(lesson)
    payload = request.get_json(silent=True) or {}
    kind = str(payload.get('kind') or 'cursor').strip().lower()
    if kind not in {'cursor', 'laser'}:
        return jsonify({'success': False, 'error': 'Неизвестный указатель'}), 400
    try:
        x, y = float(payload.get('x')), float(payload.get('y'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Некорректная позиция указателя'}), 400
    if not 0 <= x <= 1 or not 0 <= y <= 1:
        return jsonify({'success': False, 'error': 'Некорректная позиция указателя'}), 400
    from app.lessons.lesson_socket import emit_lesson_studio_pointer
    emit_lesson_studio_pointer(lesson_id, {
        'kind': kind, 'x': round(x, 5), 'y': round(y, 5),
        'author': 'teacher' if _lesson_studio_is_teacher() else 'student',
        'name': current_user.username or ('Преподаватель' if _lesson_studio_is_teacher() else 'Ученик'),
    })
    return jsonify({'success': True})


@lessons_bp.route('/lesson/<int:lesson_id>/studio/signal', methods=['POST'])
@login_required
def lesson_studio_signal(lesson_id: int):
    lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)
    _lesson_studio_access(lesson)
    if not current_user.is_student() or not _get_current_lesson_student(lesson):
        return jsonify({'success': False, 'error': 'Сигнал доступен только ученику этого урока'}), 403
    signal = (request.get_json(silent=True) or {}).get('signal')
    if signal not in {'need_hint', 'need_pause', 'ready', None}:
        return jsonify({'success': False, 'error': 'Неизвестный сигнал'}), 400
    state = _lesson_studio_state(lesson)
    state['student_signal'] = signal
    _save_lesson_studio_state(lesson, state)
    return jsonify({'success': True, 'state': _lesson_studio_state_for_viewer(state, is_teacher=False)})


@lessons_bp.route('/lesson/<int:lesson_id>/studio/checkpoint', methods=['POST'])
@login_required
def lesson_studio_checkpoint(lesson_id: int):
    """Save a short individual self-assessment without turning the lesson into a chat."""
    lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)
    _lesson_studio_access(lesson)
    if not current_user.is_student() or not _get_current_lesson_student(lesson):
        return jsonify({'success': False, 'error': 'Самооценка доступна только ученику этого урока'}), 403
    payload = request.get_json(silent=True) or {}
    understanding = payload.get('understanding')
    try:
        understanding = int(understanding)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Выберите уровень понимания'}), 400
    if understanding not in {1, 2, 3, 4, 5}:
        return jsonify({'success': False, 'error': 'Уровень понимания должен быть от 1 до 5'}), 400
    blocker = str(payload.get('blocker') or '').strip()
    if len(blocker) > 1_000:
        return jsonify({'success': False, 'error': 'Комментарий слишком длинный'}), 400
    state = _lesson_studio_state(lesson)
    state['student_checkpoint'] = {
        'understanding': understanding,
        'blocker': blocker,
        'submitted_at': moscow_now().isoformat(),
    }
    _save_lesson_studio_state(lesson, state)
    return jsonify({'success': True, 'state': _lesson_studio_state_for_viewer(state, is_teacher=False)})


@lessons_bp.route('/lesson/<int:lesson_id>/studio/finish', methods=['POST'])
@login_required
def lesson_studio_finish(lesson_id: int):
    lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)
    _lesson_studio_access(lesson)
    if not _lesson_studio_is_teacher():
        return jsonify({'success': False, 'error': 'Завершить урок может только преподаватель'}), 403
    payload = request.get_json(silent=True) or {}
    state = _lesson_studio_state(lesson)
    outcome = payload.get('outcome') if isinstance(payload.get('outcome'), dict) else state.get('outcome') or {}
    state['outcome'] = {
        'completed': [str(item).strip() for item in (outcome.get('completed') or []) if str(item).strip()][:30],
        'repeat': [str(item).strip() for item in (outcome.get('repeat') or []) if str(item).strip()][:30],
        'homework': str(outcome.get('homework') or '').strip()[:10_000],
        'published': True,
    }
    state['phase'] = 'reflection'
    timer = state.get('timer') if isinstance(state.get('timer'), dict) else {}
    timer['running'] = False
    state['timer'] = timer
    lesson.status = 'completed'
    lesson.homework = state['outcome']['homework'] or lesson.homework
    outcome_text = '\n'.join(
        part for part in (
            'Итог индивидуального урока:',
            ('Освоено: ' + '; '.join(state['outcome']['completed'])) if state['outcome']['completed'] else '',
            ('Повторить: ' + '; '.join(state['outcome']['repeat'])) if state['outcome']['repeat'] else '',
            ('Домашнее задание: ' + state['outcome']['homework']) if state['outcome']['homework'] else '',
        ) if part
    )
    if outcome_text and outcome_text not in (lesson.notes or ''):
        lesson.notes = ((lesson.notes or '').rstrip() + '\n\n' + outcome_text).strip()
    try:
        _save_lesson_studio_state(lesson, state)
    except Exception as exc:
        db.session.rollback()
        logger.exception('Unable to finish lesson studio')
        return jsonify({'success': False, 'error': 'Не удалось сохранить итог урока'}), 500
    try:
        notify_student_and_parents(
            lesson.student,
            kind='lesson_completed',
            title='Урок завершён: доступен итог',
            body=outcome_text or None,
            link_url=url_for('lessons.lesson_interactive_room', lesson_id=lesson.lesson_id),
            meta={'lesson_id': lesson.lesson_id, 'studio_outcome': True},
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.warning('Unable to send lesson studio outcome notification', exc_info=True)

    # Награждение ученика за успешное прохождение урока (XP, стрик, достижения)
    try:
        from app.utils.gamification_service import reward_lesson_completion
        reward_lesson_completion(lesson.student)
    except Exception:
        logger.warning('Unable to award gamification rewards for lesson completion', exc_info=True)

    return jsonify({'success': True, 'state': _lesson_studio_state_for_viewer(state, is_teacher=True), 'status': lesson.status})


@lessons_bp.route('/lesson/<int:lesson_id>/studio/student-notes', methods=['POST'])
@login_required
def lesson_studio_student_notes_save(lesson_id: int):
    lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)
    _lesson_studio_access(lesson)
    if not current_user.is_student() or not _get_current_lesson_student(lesson):
        return jsonify({'success': False, 'error': 'Личные заметки доступны только ученику урока'}), 403
    notes = ((request.get_json(silent=True) or {}).get('notes') or '').strip()
    if len(notes) > 20000:
        return jsonify({'success': False, 'error': 'Заметка слишком длинная'}), 400
    lesson.student_notes = notes
    db.session.commit()
    return jsonify({'success': True, 'notes': notes})


@lessons_bp.route('/sandbox/lesson_room/<int:lesson_id>')
@lessons_bp.route('/lesson/<int:lesson_id>/room')
@login_required
def lesson_interactive_room(lesson_id: int):
    """Интерактивная комната урока (Bento Studio Room)"""
    lesson = Lesson.query.options(
        db.joinedload(Lesson.student),
        db.joinedload(Lesson.homework_tasks).joinedload(LessonTask.task),
    ).get_or_404(lesson_id)

    student = lesson.student
    can_access = can_user_access_student(
        current_user,
        student_user_id=getattr(student, 'user_id', None),
        student_platform_id=getattr(student, 'platform_id', None),
    )
    if not can_access and current_user.is_student():
        try:
            can_access = int(current_user.id) == int(getattr(student, 'user_id', None) or getattr(student, 'student_id', None))
        except Exception:
            can_access = False
    if not can_access and not (current_user.is_admin() or current_user.is_creator()):
        from flask import abort
        abort(403)

    classwork_tasks = get_sorted_assignments(lesson, 'classwork')
    is_studio_teacher = _lesson_studio_is_teacher()
    studio_state = _lesson_studio_state_for_viewer(_lesson_studio_state(lesson), is_teacher=is_studio_teacher)
    tasks_json = json.dumps([
        {
            'lesson_task_id': t.lesson_task_id,
            'task_id': t.task_id,
            'title': f'Задание №{t.task.task_number} (№{idx + 1})' if t.task else f'Задание #{idx + 1}',
            'description': t.task.content_html if t.task else 'Условие задачи...',
            'answer': t.student_answer or (t.task.answer if t.task else ''),
            'student_submission': t.student_submission or '',
            'teacher_comment': t.teacher_comment or '',
            'submission_correct': t.submission_correct,
            'status': t.status or 'pending',
            'order': idx + 1
        } for idx, t in enumerate(classwork_tasks or [])
    ], ensure_ascii=False) if classwork_tasks else '[]'

    summary_text = lesson.notes or ''
    video_url = getattr(lesson, 'video_url', None) or ''
    timecodes = getattr(lesson, 'timecodes', None) or []

    tutor_user = User.query.get(student.tutor_id) if (student and getattr(student, 'tutor_id', None)) else None
    teacher_name = tutor_user.username if tutor_user else (current_user.username if current_user else 'Преподаватель КЕГЭ')
    teacher_avatar = f"https://api.dicebear.com/7.x/avataaars/svg?seed={teacher_name}&backgroundColor=fef3c7"
    is_live = (lesson.status == 'in_progress')
    try:
        can_open_task_generator = bool(
            is_studio_teacher and (
                current_user.is_admin()
                or current_user.is_creator()
                or has_permission(current_user, 'task.manage')
            )
        )
    except Exception:
        can_open_task_generator = False
    # У урока курс хранится в exam_course_id. Не берём course_id из URL или
    # клиентского состояния: это исключает открытие чужого материала.
    lesson_course_id = _lesson_studio_course_id(lesson)
    theory_blocks = (
        TheoryBlock.query.filter_by(course_id=lesson_course_id)
        .order_by(TheoryBlock.position, TheoryBlock.id)
        .all()
        if lesson_course_id else []
    )
    theory_items = [
        {'id': item.id, 'title': item.title or f'Тема {item.task_number}', 'task_number': item.task_number,
         'url': url_for('theory.theory_view_block', block_id=item.id, course_id=lesson_course_id)}
        for item in theory_blocks if (item.content or '').strip() and not (item.content or '').lstrip().startswith('<!--status:draft-->')
    ]

    return render_template(
        'sandbox/lesson_room.html',
        lesson=lesson,
        lesson_id=lesson.lesson_id,
        student=student,
        classwork_tasks=classwork_tasks,
        tasks_json=tasks_json,
        summary_text=summary_text,
        video_url=video_url,
        timecodes=timecodes,
        teacher_name=teacher_name,
        teacher_avatar=teacher_avatar,
        is_live=is_live,
        studio_state=studio_state,
        is_studio_teacher=is_studio_teacher,
        can_open_task_generator=can_open_task_generator,
        theory_items=theory_items,
        active_page='lesson_room'
    )


@lessons_bp.route('/lesson/<int:lesson_id>/classwork-tasks')
@login_required
def lesson_classwork_view(lesson_id):
    """Просмотр заданий классной работы"""
    lesson = Lesson.query.options(
        db.joinedload(Lesson.student),
        db.joinedload(Lesson.homework_tasks).joinedload(LessonTask.task),
        db.joinedload(Lesson.homework_tasks).joinedload(LessonTask.attempts),
    ).get_or_404(lesson_id)
    student = lesson.student
    stud = Student.query.filter_by(user_id=current_user.id).first() if (current_user and current_user.is_authenticated) else None
    student_user_id = getattr(student, 'user_id', None)
    student_platform_id = getattr(student, 'student_id', None)
    can_access = can_user_access_student(
        current_user,
        student_user_id=student_user_id,
        student_platform_id=student_platform_id,
    )
    if not can_access and current_user.is_student():
        try:
            if student_user_id and int(current_user.id) == int(student_user_id):
                can_access = True
            elif stud and student_platform_id and int(stud.student_id) == int(student_platform_id):
                can_access = True
        except Exception:
            can_access = False
    if not can_access:
        from flask import abort
        abort(403)

    classwork_tasks = get_sorted_assignments(lesson, 'classwork')

    if current_user.is_student():
        try:
            from core.db_models import Assignment, Submission, AssignmentTask
            from datetime import timedelta, datetime
            assign = Assignment.query.filter_by(lesson_id=lesson_id, is_active=True).first()
            if not assign:
                assign = Assignment(
                    title=f"Классная работа: {lesson.topic or 'Урок ' + str(lesson_id)}",
                    assignment_type='classwork',
                    deadline=(lesson.lesson_date + timedelta(days=7)) if lesson.lesson_date else (datetime.utcnow() + timedelta(days=7)),
                    created_by_id=getattr(student, 'tutor_id', None) or getattr(lesson, 'created_by_id', None) or current_user.id,
                    lesson_id=lesson_id,
                    is_active=True
                )
                db.session.add(assign)
                db.session.flush()
                for idx, lt in enumerate(classwork_tasks or []):
                    if lt.task_id:
                        at = AssignmentTask(
                            assignment_id=assign.assignment_id,
                            task_id=lt.task_id,
                            order_index=idx + 1,
                            max_score=getattr(lt, 'max_score', 1) or 1
                        )
                        db.session.add(at)
                db.session.commit()

            sub = Submission.query.filter_by(assignment_id=assign.assignment_id, student_id=student.student_id).first()
            if not sub:
                sub = Submission(
                    assignment_id=assign.assignment_id,
                    student_id=student.student_id,
                    status='ASSIGNED'
                )
                db.session.add(sub)
                db.session.commit()

            return redirect(url_for('assignments.submission_view', submission_id=sub.submission_id))
        except Exception as e:
            logger.warning(f"Failed to auto-redirect student to submission for lesson {lesson_id}: {e}")
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
        is_read_only = not any(_is_task_editable_for_student(lesson, classwork_tasks, t) for t in (classwork_tasks or []))
    viewer_timezone = 'Europe/Moscow'  # comment
    try:  # comment
        if current_user and getattr(current_user, 'profile', None) and current_user.profile.timezone:  # comment
            viewer_timezone = current_user.profile.timezone  # comment
    except Exception:  # comment
        viewer_timezone = 'Europe/Moscow'  # comment
    homework_task_blocks = get_assignment_blocks(lesson, 'classwork')
    return render_template('lesson_homework.html',
                           lesson=lesson,
                           student=student,
                           homework_tasks=classwork_tasks,
                           homework_task_blocks=homework_task_blocks,
                           assignment_type='classwork',  # comment
                           is_student_view=is_student_view,  # comment
                           is_parent_view=is_parent_view,  # comment
                           is_read_only=is_read_only,  # comment
                           attempts_default=_get_lesson_attempts_default(lesson, 'classwork'),
                           allow_task_submit=_is_task_submit_enabled(lesson, 'classwork'),
                           viewer_timezone=viewer_timezone,  # comment
                           review_summary=(getattr(lesson, 'review_summaries', None) or {}).get('classwork', {}),  # comment
                           library_materials=library_materials,  # comment
                           content_blocks=content_blocks)  # comment

@lessons_bp.route('/lesson/<int:lesson_id>/exam-tasks')
@login_required
def lesson_exam_view(lesson_id):
    """Проверочные работы выдаются через раздел «Задания». Редирект на создание работы по уроку."""
    return redirect(url_for(
        'assignments.assignment_create',
        source='lesson',
        lesson_id=lesson_id,
        assignment_type='exam',
    ))


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

    try:
        if payload.get('status') in ('graded', 'returned'):
            q = LessonTask.query.filter(LessonTask.lesson_id == lesson.lesson_id)
            if assignment_type == 'homework':
                q = q.filter((LessonTask.assignment_type == 'homework') | (LessonTask.assignment_type.is_(None)))
            else:
                q = q.filter(LessonTask.assignment_type == assignment_type)

            if payload.get('status') == 'graded':
                q = q.filter(LessonTask.status.in_(['submitted', 'returned']))
                q.update({'status': 'graded'}, synchronize_session=False)
            elif payload.get('status') == 'returned':
                q = q.filter(LessonTask.status.in_(['submitted']))
                q.update({'status': 'returned'}, synchronize_session=False)
    except Exception as e:
        logger.warning(f"Could not bulk update LessonTask statuses from review summary: {e}")

    try:
        _upsert_gradebook_from_lesson_review(lesson, assignment_type, payload, actor_user_id=current_user.id)
    except Exception as e:
        logger.warning(f"Could not upsert gradebook entry from lesson review: {e}")

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
                link_url=url_for('lessons.lesson_classwork_view', lesson_id=lesson.lesson_id),
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
    status = (request.args.get('status') or 'submitted').strip().lower()
    source = (request.args.get('source') or 'all').strip().lower()  # all|lessons|assignments
    assignment_type = (request.args.get('assignment_type') or '').strip().lower()  # homework|classwork|exam
    student_query = (request.args.get('student') or '').strip()
    lesson_id = request.args.get('lesson_id', type=int)
    assignment_id = request.args.get('assignment_id', type=int)

    try:
        lesson_id = int(lesson_id) if lesson_id else None
    except Exception:
        lesson_id = None
    try:
        assignment_id = int(assignment_id) if assignment_id else None
    except Exception:
        assignment_id = None

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

    status_counts_lessons = {'submitted': 0, 'returned': 0, 'graded': 0, 'pending': 0}
    status_counts_assignments = {'submitted': 0, 'returned': 0, 'graded': 0, 'pending': 0}

    try:
        ql = LessonTask.query.join(Lesson, Lesson.lesson_id == LessonTask.lesson_id).join(Student, Student.student_id == Lesson.student_id)
        if lesson_id:
            ql = ql.filter(Lesson.lesson_id == int(lesson_id))
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
        if assignment_id:
            qs0 = qs0.filter(Assignment.assignment_id == int(assignment_id))
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
        status_counts_assignments['submitted'] = raw.get('SUBMITTED', 0) + raw.get('NEEDS_MANUAL_REVIEW', 0)
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

    # Tab counts (for active status)
    tab_counts = {'all': 0, 'homework': 0, 'classwork': 0, 'exam': 0}
    if source in {'all', 'lessons'}:
        try:
            ql_tab = LessonTask.query.join(Lesson, Lesson.lesson_id == LessonTask.lesson_id).join(Student, Student.student_id == Lesson.student_id)
            ql_tab = ql_tab.filter(LessonTask.status == status)
            if lesson_id:
                ql_tab = ql_tab.filter(Lesson.lesson_id == int(lesson_id))
            if student_query:
                ql_tab = ql_tab.filter(Student.name.ilike(f'%{student_query}%'))
            if accessible_student_ids is not None:
                if not accessible_student_ids:
                    ql_tab = ql_tab.filter(False)
                else:
                    ql_tab = ql_tab.filter(Lesson.student_id.in_(accessible_student_ids))
            
            rows_l = ql_tab.with_entities(LessonTask.assignment_type, db.func.count(LessonTask.lesson_task_id)).group_by(LessonTask.assignment_type).all()
            for atype, cnt in rows_l:
                cnt_val = int(cnt or 0)
                at_key = (atype or '').strip().lower()
                if not at_key or at_key == 'homework':
                    tab_counts['homework'] += cnt_val
                elif at_key == 'classwork':
                    tab_counts['classwork'] += cnt_val
                elif at_key == 'exam':
                    tab_counts['exam'] += cnt_val
                tab_counts['all'] += cnt_val
        except Exception as e:
            logger.error(f"Error querying LessonTask tab counts: {e}")

    if source in {'all', 'assignments'}:
        try:
            qs_tab = Submission.query.join(Student, Student.student_id == Submission.student_id).join(Assignment, Assignment.assignment_id == Submission.assignment_id)
            status_map = {
                'submitted': ['SUBMITTED', 'NEEDS_MANUAL_REVIEW'],
                'returned': ['RETURNED'],
                'graded': ['GRADED'],
                'pending': ['ASSIGNED', 'IN_PROGRESS'],
            }
            statuses = status_map.get(status, ['SUBMITTED', 'NEEDS_MANUAL_REVIEW'])
            qs_tab = qs_tab.filter(Submission.status.in_(statuses))
            if assignment_id:
                qs_tab = qs_tab.filter(Assignment.assignment_id == int(assignment_id))
            if student_query:
                qs_tab = qs_tab.filter(or_(
                    Student.name.ilike(f'%{student_query}%'),
                    Assignment.title.ilike(f'%{student_query}%'),
                ))
            if not scope.get('can_see_all'):
                qs_tab = qs_tab.filter(Assignment.created_by_id == current_user.id)
                if accessible_student_ids is not None:
                    if not accessible_student_ids:
                        qs_tab = qs_tab.filter(False)
                    else:
                        qs_tab = qs_tab.filter(Submission.student_id.in_(accessible_student_ids))
            
            rows_a = qs_tab.with_entities(Assignment.assignment_type, db.func.count(Submission.submission_id)).group_by(Assignment.assignment_type).all()
            for atype, cnt in rows_a:
                cnt_val = int(cnt or 0)
                at_key = (atype or '').strip().lower()
                if at_key in ['homework', 'classwork', 'exam']:
                    tab_counts[at_key] += cnt_val
                else:
                    tab_counts['homework'] += cnt_val
                tab_counts['all'] += cnt_val
        except Exception as e:
            logger.error(f"Error querying Submission tab counts: {e}")

    lesson_cards = []
    if source in {'all', 'lessons'}:
        q = LessonTask.query.options(
            db.joinedload(LessonTask.lesson).joinedload(Lesson.student),
            db.joinedload(LessonTask.task),
        ).join(Lesson, Lesson.lesson_id == LessonTask.lesson_id).join(Student, Student.student_id == Lesson.student_id)

        q = q.filter(LessonTask.status == status)
        if lesson_id:
            q = q.filter(Lesson.lesson_id == int(lesson_id))
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
            try:
                tid = int(getattr(lt, 'lesson_task_id', 0) or 0)
            except Exception:
                tid = 0
            if tid and tid in by_lesson[lid]['_seen_task_ids']:
                continue
            if tid:
                by_lesson[lid]['_seen_task_ids'].add(tid)
            by_lesson[lid]['tasks'].append(lt)

        for item in by_lesson.values():
            try:
                item.pop('_seen_task_ids', None)
            except Exception:
                pass
            lesson_cards.append(item)
        lesson_cards.sort(key=lambda x: (x['lesson'].lesson_date or moscow_now()), reverse=True)

    assignment_cards = []
    if source in {'all', 'assignments'}:
        status_map = {
            'submitted': ['SUBMITTED', 'NEEDS_MANUAL_REVIEW'],
            'returned': ['RETURNED'],
            'graded': ['GRADED'],
            'pending': ['ASSIGNED', 'IN_PROGRESS'],
        }
        statuses = status_map.get(status, ['SUBMITTED', 'NEEDS_MANUAL_REVIEW'])

        qs = Submission.query.options(
            db.joinedload(Submission.assignment),
            db.joinedload(Submission.student),
        ).join(Student, Student.student_id == Submission.student_id).join(Assignment, Assignment.assignment_id == Submission.assignment_id)

        qs = qs.filter(Submission.status.in_(statuses))
        if assignment_id:
            qs = qs.filter(Assignment.assignment_id == int(assignment_id))
        if assignment_type:
            qs = qs.filter(Assignment.assignment_type == assignment_type)
        if student_query:
            qs = qs.filter(or_(
                Student.name.ilike(f'%{student_query}%'),
                Assignment.title.ilike(f'%{student_query}%'),
            ))

        if not scope.get('can_see_all'):
            qs = qs.filter(Assignment.created_by_id == current_user.id)
            if accessible_student_ids is not None:
                if not accessible_student_ids:
                    qs = qs.filter(False)
                else:
                    qs = qs.filter(Submission.student_id.in_(accessible_student_ids))

        now_local = moscow_now()

        def _sub_key(s: Submission):
            try:
                deadline = s.assignment.deadline if (s and s.assignment) else None
            except Exception:
                deadline = None
            if deadline is not None and getattr(deadline, 'tzinfo', None) is None:
                deadline = deadline.replace(tzinfo=MOSCOW_TZ)
            overdue_flag = 1 if (deadline and now_local > deadline and (s.status or '').upper() in ['SUBMITTED', 'NEEDS_MANUAL_REVIEW']) else 0
            late_flag = 1 if getattr(s, 'is_late', False) else 0
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
            if _sub_key(sub) > by_assignment[aid]['_sort_key']:
                by_assignment[aid]['_sort_key'] = _sub_key(sub)

        assignment_cards = list(by_assignment.values())
        assignment_cards.sort(key=lambda x: x.get('_sort_key') or (0, 0, now_local), reverse=True)
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
        tab_counts=tab_counts,
        lesson_id=lesson_id,
        assignment_id=assignment_id,
    )


@lessons_bp.route('/tutor/reviews')
@login_required
@check_access('assignment.grade')
def tutor_manual_reviews():
    """
    Панель ручной проверки: все сдачи со статусом NEEDS_MANUAL_REVIEW.
    Фильтр по курсу (course_id) — опционально.
    """
    course_id = request.args.get('course_id', type=int)
    scope = get_user_scope(current_user)
    accessible_student_ids = None
    if not scope.get('can_see_all'):
        accessible_student_ids = _resolve_accessible_student_ids(scope) or []

    q = (
        Submission.query
        .options(
            db.joinedload(Submission.assignment).joinedload(Assignment.exam_course),
            db.joinedload(Submission.student),
        )
        .join(Student, Student.student_id == Submission.student_id)
        .join(Assignment, Assignment.assignment_id == Submission.assignment_id)
        .filter(Submission.status == 'NEEDS_MANUAL_REVIEW')
    )

    if course_id:
        q = q.filter(Assignment.exam_course_id == course_id)

    if not scope.get('can_see_all'):
        q = q.filter(Assignment.created_by_id == current_user.id)
        if accessible_student_ids is not None:
            if not accessible_student_ids:
                q = q.filter(False)
            else:
                q = q.filter(Submission.student_id.in_(accessible_student_ids))

    submissions = q.order_by(Submission.submitted_at.desc().nullslast(), Submission.assigned_at.desc()).limit(500).all()

    courses = Course.query.filter(Course.is_active == True).order_by(Course.title).all()

    return render_template(
        'tutor_reviews.html',
        submissions=submissions,
        courses=courses,
        course_id=course_id,
        active_page='tutor_reviews',
    )


@lessons_bp.route('/reviews/lesson-task/<int:lesson_task_id>')
@login_required
@check_access('assignment.grade')
def review_lesson_task(lesson_task_id: int):
    """
    Единый экран проверки конкретной задачи урока (LessonTask),
    чтобы проверка не была размазана по страницам урока.
    """
    if current_user.is_student() or current_user.is_parent():
        return make_response('Forbidden', 403)

    lt = (
        LessonTask.query.options(
            db.joinedload(LessonTask.lesson).joinedload(Lesson.student),
            db.joinedload(LessonTask.task),
            db.joinedload(LessonTask.teacher_comments),
        )
        .filter(LessonTask.lesson_task_id == lesson_task_id)
        .first_or_404()
    )
    lesson = lt.lesson
    if not lesson:
        return make_response('Not found', 404)

    scope = get_user_scope(current_user)
    if not scope.get('can_see_all'):
        accessible_student_ids = _resolve_accessible_student_ids(scope)
        if lesson.student_id not in (accessible_student_ids or []):
            return make_response('Forbidden', 403)

    a_type = (lt.assignment_type or 'homework').strip().lower()
    if a_type not in {'homework', 'classwork', 'exam'}:
        a_type = 'homework'

    back_status = (lt.status or 'submitted').strip().lower()
    if back_status not in {'submitted', 'returned', 'graded', 'pending'}:
        back_status = 'submitted'

    return render_template(
        'lesson_task_review.html',
        active_page='review_queue',
        lesson=lesson,
        student=lesson.student,
        lesson_task=lt,
        assignment_type=a_type,
        back_queue_url=url_for(
            'lessons.review_queue',
            source='lessons',
            lesson_id=lesson.lesson_id,
            assignment_type=a_type,
            status=back_status,
        ),
        back_lesson_url=(
            url_for('lessons.lesson_classwork_view', lesson_id=lesson.lesson_id)
            if a_type == 'exam'
            else (
                url_for('lessons.lesson_classwork_view', lesson_id=lesson.lesson_id)
                if a_type == 'classwork'
                else url_for('lessons.lesson_classwork_view', lesson_id=lesson.lesson_id)
            )
        ),
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

    if status_filter != 'submitted':
        flash('Массовые действия доступны только в статусе «Сдано».', 'warning')
        return redirect(url_for('lessons.review_queue', status=status_filter, assignment_type=assignment_type, student=student_query))

    lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)

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
    lesson_task.teacher_comment = body  # comment
    try:  # comment
        db.session.commit()  # comment
    except Exception as e:  # comment
        db.session.rollback()  # comment
        logger.error(f"Failed to add teacher comment: {e}", exc_info=True)  # comment
        return jsonify({'success': False, 'error': 'Ошибка сохранения'}), 500  # comment
    try:  # comment
        if getattr(lesson_task, 'lesson', None) and lesson_task.lesson.student and lesson_task.lesson.student.user_id:  # comment
            notify_student_and_parents(  # comment
                lesson_task.lesson.student,  # comment
                kind='lesson_comment',  # comment
                title='Новый комментарий к заданию урока',  # comment
                body=body,  # comment
                link_url=url_for('lessons.lesson_homework_view', lesson_id=lesson_id) + f'#task-{lesson_task.lesson_task_id}',  # comment
                meta={'lesson_id': lesson_id, 'lesson_task_id': lesson_task.lesson_task_id},  # comment
            )  # comment
    except Exception as notify_err:  # comment
        logger.warning('Failed to notify lesson task comment: %s', notify_err, exc_info=True)  # comment
    tz = 'Europe/Moscow'  # comment
    try:  # comment
        if getattr(current_user, 'profile', None) and current_user.profile.timezone:  # comment
            tz = current_user.profile.timezone  # comment
    except Exception:  # comment
        tz = 'Europe/Moscow'  # comment
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
    student = Student.query.filter_by(user_id=current_user.id).first()
    if not student:
        try:
            student = Student.query.filter(Student.student_id == int(current_user.id)).first()
        except Exception:
            student = None
    if not student:
        return None  # comment
    if student.user_id is None:
        try:
            student.user_id = current_user.id
            db.session.commit()
        except Exception:
            db.session.rollback()
    if student.student_id != lesson.student_id:  # comment
        return None  # comment
    return student  # comment


def _is_submission_finalized(lesson, tasks):  # comment
    """Финализация работы: редактировать уже нечего (все задачи заблокированы по попыткам/статусу)."""  # comment
    if not tasks:
        return getattr(lesson, 'homework_status', None) == 'assigned_done'  # comment
    return not any(_is_task_editable_for_student(lesson, tasks, t) for t in tasks)  # comment


def _is_task_editable_for_student(lesson, tasks, task):  # comment
    """Редактирование учеником конкретной задачи с учётом лимита попыток."""  # comment
    status = (task.status or '').lower()
    if status == 'graded':
        return False
    try:
        used = len(task.attempts or [])
    except Exception:
        used = 0
    try:
        max_attempts = int(task.get_effective_max_attempts())
    except Exception:
        max_attempts = 1
    return used < max(1, max_attempts)


def _get_lesson_attempts_attr_names(assignment_type: str):
    at = (assignment_type or 'homework').strip().lower()
    max_attr = {
        'homework': 'homework_max_attempts_default',
        'classwork': 'classwork_max_attempts_default',
        'exam': 'exam_max_attempts_default',
    }.get(at, 'homework_max_attempts_default')
    toggle_attr = {
        'homework': 'allow_task_submit_homework',
        'classwork': 'allow_task_submit_classwork',
        'exam': 'allow_task_submit_exam',
    }.get(at, 'allow_task_submit_homework')
    return max_attr, toggle_attr


def _get_lesson_attempts_default(lesson, assignment_type: str) -> int:
    max_attr, _ = _get_lesson_attempts_attr_names(assignment_type)
    try:
        v = getattr(lesson, max_attr, None)
        if v is not None and int(v) > 0:
            return int(v)
    except Exception:
        pass
    return 1


def _is_task_submit_enabled(lesson, assignment_type: str) -> bool:
    _, toggle_attr = _get_lesson_attempts_attr_names(assignment_type)
    return bool(getattr(lesson, toggle_attr, False))


def _apply_attempts_settings_from_form(lesson, tasks, assignment_type: str) -> None:
    max_attr, toggle_attr = _get_lesson_attempts_attr_names(assignment_type)

    if 'max_attempts_default' in request.form:
        raw = (request.form.get('max_attempts_default') or '').strip()
        if raw == '':
            setattr(lesson, max_attr, None)
        else:
            try:
                n = int(raw)
                if 1 <= n <= 20:
                    setattr(lesson, max_attr, n)
            except (ValueError, TypeError):
                pass

    setattr(
        lesson,
        toggle_attr,
        str(request.form.get('allow_task_submit', '')).strip().lower() in ('1', 'true', 'on', 'yes')
    )

    for t in tasks:
        key = f'max_attempts_{t.lesson_task_id}'
        if key not in request.form:
            continue
        raw = (request.form.get(key) or '').strip()
        if raw == '':
            t.max_attempts = None
            continue
        try:
            n = int(raw)
            if 1 <= n <= 20:
                t.max_attempts = n
        except (ValueError, TypeError):
            pass


def _save_student_submissions(lesson, assignment_type):  # comment
    """Сохраняем ответы ученика (черновик). НЕ считаем автопроверку и не выставляем submission_correct."""  # comment
    tasks = get_sorted_assignments(lesson, assignment_type)  # comment
    for task in tasks:  # comment
        field_name = f'submission_{task.lesson_task_id}'  # comment
        if not _is_task_editable_for_student(lesson, tasks, task):  # comment
            continue  # comment
        if field_name in request.form:  # comment
            value = request.form.get(field_name, '').strip()  # comment
            task.student_submission = value if value else None  # comment
        time_key = f'time_spent_{task.lesson_task_id}'  # comment
        if time_key in request.form:  # comment
            try:  # comment
                sec = int(request.form.get(time_key, 0) or 0)
                if 0 <= sec <= 86400:  # comment
                    task.time_spent_sec = sec  # comment
            except (ValueError, TypeError):  # comment
                pass  # comment
    return tasks  # comment


def _submit_student_submissions(lesson, assignment_type):  # comment
    """Фиксируем ответы ученика и запускаем авто-проверку"""  # comment
    tasks = get_sorted_assignments(lesson, assignment_type)  # comment
    submitted_count = 0
    for task in tasks:  # comment
        if not _is_task_editable_for_student(lesson, tasks, task):  # comment
            continue  # comment
        field_name = f'submission_{task.lesson_task_id}'  # comment
        value = request.form.get(field_name, '').strip()  # comment
        task.student_submission = value if value else None  # comment
        expected = (task.student_answer if task.student_answer else (task.task.answer if task.task and task.task.answer else '')) or ''  # comment
        if not expected:  # comment
            task.submission_correct = False  # comment
            task.status = 'submitted'  # comment
            submitted_count += 1  # comment — считаем как сданное, чтобы не показывать «Нет доступных заданий»
            continue  # comment
        if not value:  # comment
            task.submission_correct = False  # comment
            task.status = 'submitted'  # comment
            submitted_count += 1  # comment
            continue  # comment
        normalized_value = normalize_answer_value(value)  # comment
        normalized_expected = normalize_answer_value(expected)  # comment
        task.submission_correct = normalized_value == normalized_expected and normalized_expected != ''  # comment
        task.status = 'submitted'  # comment
        time_key = f'time_spent_{task.lesson_task_id}'  # comment
        if time_key in request.form:  # comment
            try:  # comment
                sec = int(request.form.get(time_key, 0) or 0)
                if 0 <= sec <= 86400:  # comment
                    task.time_spent_sec = sec  # comment
            except (ValueError, TypeError):  # comment
                pass  # comment
        try:
            _record_lesson_task_attempt(task)
        except Exception as e:
            logger.warning(f"Could not record LessonTaskAttempt for {task.lesson_task_id}: {e}")
        submitted_count += 1  # comment
    if assignment_type == 'homework':  # comment
        lesson.homework_status = 'assigned_done'  # comment
    return tasks, submitted_count  # comment


@lessons_bp.route('/lesson/<int:lesson_id>/homework-tasks/student-save', methods=['POST'])  # comment
@login_required  # comment
def lesson_homework_student_save(lesson_id):  # comment
    """Сохранение ответов ученика (ДЗ)"""  # comment
    lesson = Lesson.query.get_or_404(lesson_id)  # comment
    if not _get_current_lesson_student(lesson):  # comment
        flash('Доступ запрещен', 'danger')  # comment
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment
    tasks = get_sorted_assignments(lesson, 'homework')  # comment
    if not any(_is_task_editable_for_student(lesson, tasks, t) for t in tasks):
        flash('Работа уже сдана. Изменения заблокированы.', 'warning')  # comment
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment
    _save_student_submissions(lesson, 'homework')  # comment
    db.session.commit()  # comment
    flash('Ответы сохранены', 'success')  # comment
    return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment


@lessons_bp.route('/lesson/<int:lesson_id>/classwork-tasks/student-save', methods=['POST'])  # comment
@login_required  # comment
def lesson_classwork_student_save(lesson_id):  # comment
    """Сохранение ответов ученика (КР)"""  # comment
    lesson = Lesson.query.get_or_404(lesson_id)  # comment
    if not _get_current_lesson_student(lesson):  # comment
        flash('Доступ запрещен', 'danger')  # comment
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment
    tasks = get_sorted_assignments(lesson, 'classwork')  # comment
    if not any(_is_task_editable_for_student(lesson, tasks, t) for t in tasks):
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
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment
    tasks = get_sorted_assignments(lesson, 'exam')  # comment
    if not any(_is_task_editable_for_student(lesson, tasks, t) for t in tasks):
        flash('Работа уже сдана. Изменения заблокированы.', 'warning')  # comment
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment
    _save_student_submissions(lesson, 'exam')  # comment
    db.session.commit()  # comment
    flash('Ответы сохранены', 'success')  # comment
    return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment


@lessons_bp.route('/lesson/<int:lesson_id>/homework-tasks/student-submit', methods=['POST'])  # comment
@login_required  # comment
def lesson_homework_student_submit(lesson_id):  # comment
    """Сдача работы учеником (ДЗ)"""  # comment
    lesson = Lesson.query.get_or_404(lesson_id)  # comment
    if not _get_current_lesson_student(lesson):  # comment
        flash('Доступ запрещен', 'danger')  # comment
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment
    tasks = get_sorted_assignments(lesson, 'homework')  # comment
    if not any(_is_task_editable_for_student(lesson, tasks, t) for t in tasks):
        flash('Работа уже сдана. Повторная сдача заблокирована.', 'warning')  # comment
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment
    _, submitted_count = _submit_student_submissions(lesson, 'homework')  # comment
    if submitted_count <= 0:
        flash('Нет доступных заданий для сдачи.', 'warning')
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))
    db.session.commit()  # comment
    flash('Работа сдана', 'success')  # comment
    return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment


@lessons_bp.route('/lesson/<int:lesson_id>/classwork-tasks/student-submit', methods=['POST'])  # comment
@login_required  # comment
def lesson_classwork_student_submit(lesson_id):  # comment
    """Сдача работы учеником (КР)"""  # comment
    lesson = Lesson.query.get_or_404(lesson_id)  # comment
    if not _get_current_lesson_student(lesson):  # comment
        flash('Доступ запрещен', 'danger')  # comment
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment
    tasks = get_sorted_assignments(lesson, 'classwork')  # comment
    if not any(_is_task_editable_for_student(lesson, tasks, t) for t in tasks):
        flash('Работа уже сдана. Повторная сдача заблокирована.', 'warning')  # comment
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment
    _, submitted_count = _submit_student_submissions(lesson, 'classwork')  # comment
    if submitted_count <= 0:
        flash('Нет доступных заданий для сдачи.', 'warning')
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))
    db.session.commit()  # comment
    from app.lessons.lesson_socket import emit_lesson_tasks_updated
    emit_lesson_tasks_updated(lesson_id, 'classwork')
    flash('Работа сдана', 'success')  # comment
    return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment


@lessons_bp.route('/lesson/<int:lesson_id>/exam-tasks/student-submit', methods=['POST'])  # comment
@login_required  # comment
def lesson_exam_student_submit(lesson_id):  # comment
    """Сдача работы учеником (Проверочная)"""  # comment
    lesson = Lesson.query.get_or_404(lesson_id)  # comment
    if not _get_current_lesson_student(lesson):  # comment
        flash('Доступ запрещен', 'danger')  # comment
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment
    tasks = get_sorted_assignments(lesson, 'exam')  # comment
    if not any(_is_task_editable_for_student(lesson, tasks, t) for t in tasks):
        flash('Работа уже сдана. Повторная сдача заблокирована.', 'warning')  # comment
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment
    _, submitted_count = _submit_student_submissions(lesson, 'exam')  # comment
    if submitted_count <= 0:
        flash('Нет доступных заданий для сдачи.', 'warning')
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))
    db.session.commit()  # comment
    flash('Работа сдана', 'success')  # comment
    return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment


def _assignment_view_route_name(assignment_type: str) -> str:
    """В комнате урока остаётся только классная работа; ДЗ и проверочная — через Задания."""
    at = (assignment_type or 'classwork').strip().lower()
    return 'lessons.lesson_classwork_view'


@lessons_bp.route('/lesson/<int:lesson_id>/task/<int:lesson_task_id>/student-submit', methods=['POST'])
@login_required
def lesson_task_student_submit(lesson_id, lesson_task_id):
    """Сдача конкретного задания учеником (опциональный режим per-task submit)."""
    lesson = Lesson.query.options(
        db.joinedload(Lesson.homework_tasks).joinedload(LessonTask.attempts)
    ).get_or_404(lesson_id)
    if not _get_current_lesson_student(lesson):
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))

    lesson_task = LessonTask.query.filter_by(lesson_id=lesson_id, lesson_task_id=lesson_task_id).first_or_404()
    assignment_type = (lesson_task.assignment_type or 'homework').strip().lower()
    back_route = _assignment_view_route_name(assignment_type)

    if not _is_task_submit_enabled(lesson, assignment_type):
        flash('Сдача по заданиям отключена преподавателем.', 'warning')
        return redirect(url_for(back_route, lesson_id=lesson_id) + f"#task-{lesson_task_id}")

    tasks = get_sorted_assignments(lesson, assignment_type)
    if not _is_task_editable_for_student(lesson, tasks, lesson_task):
        flash('Лимит попыток для этого задания исчерпан.', 'warning')
        return redirect(url_for(back_route, lesson_id=lesson_id) + f"#task-{lesson_task_id}")

    field_name = f'submission_{lesson_task.lesson_task_id}'
    value = (request.form.get(field_name, '') or '').strip()
    lesson_task.student_submission = value if value else None
    expected = (lesson_task.student_answer if lesson_task.student_answer else (lesson_task.task.answer if lesson_task.task and lesson_task.task.answer else '')) or ''

    if not expected or not value:
        lesson_task.submission_correct = False
    else:
        lesson_task.submission_correct = normalize_answer_value(value) == normalize_answer_value(expected) and normalize_answer_value(expected) != ''
    lesson_task.status = 'submitted'

    time_key = f'time_spent_{lesson_task.lesson_task_id}'
    if time_key in request.form:
        try:
            sec = int(request.form.get(time_key, 0) or 0)
            if 0 <= sec <= 86400:
                lesson_task.time_spent_sec = sec
        except (ValueError, TypeError):
            pass

    try:
        _record_lesson_task_attempt(lesson_task)
    except Exception as e:
        logger.warning(f"Could not record LessonTaskAttempt for {lesson_task.lesson_task_id}: {e}")

    if assignment_type == 'homework':
        lesson.homework_status = 'assigned_done'

    db.session.commit()
    from app.lessons.lesson_socket import emit_lesson_tasks_updated
    emit_lesson_tasks_updated(lesson_id, assignment_type)
    flash('Задание сдано', 'success')
    return redirect(url_for(back_route, lesson_id=lesson_id) + f"#task-{lesson_task_id}")

@lessons_bp.route('/lesson/<int:lesson_id>/homework-tasks/save', methods=['POST'])
@login_required
def lesson_homework_save(lesson_id):
    """Сохранение домашнего задания"""
    if current_user.is_student() or current_user.is_parent():  # comment
        flash('Доступ запрещен', 'danger')  # comment
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment
    lesson = Lesson.query.get_or_404(lesson_id)
    homework_tasks = [ht for ht in lesson.homework_assignments]

    for hw_task in homework_tasks:
        answer_key = f'answer_{hw_task.lesson_task_id}'
        if answer_key in request.form:
            submitted_answer = request.form.get(answer_key).strip()
            hw_task.student_answer = submitted_answer if submitted_answer else None
        diff_key = f'difficulty_level_{hw_task.lesson_task_id}'
        if diff_key in request.form:
            v = request.form.get(diff_key, '').strip()
            if v == '':
                hw_task.difficulty_level = None
            else:
                try:
                    n = int(v)
                    if 1 <= n <= 3:
                        hw_task.difficulty_level = n
                except ValueError:
                    pass
    _apply_attempts_settings_from_form(lesson, homework_tasks, 'homework')

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

    prev_status = lesson.homework_status
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

    if lesson.student and prev_status != 'assigned_not_done' and lesson.homework_status == 'assigned_not_done' and homework_tasks:
        task_ids = [t.task_id for t in homework_tasks]
        enqueue_assignment_notification(
            lesson=lesson,
            assignment_type='homework',
            task_ids=task_ids,
            link_url=url_for('lessons.lesson_homework_view', lesson_id=lesson.lesson_id),
        )
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.warning(f"Could not commit pending assignment notification (homework_save): {e}")
    
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
    from app.lessons.lesson_socket import emit_lesson_tasks_updated
    emit_lesson_tasks_updated(lesson_id, 'homework')
    return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))


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
        diff_key = f'difficulty_level_{t.lesson_task_id}'  # comment
        if diff_key in request.form:  # comment
            v = request.form.get(diff_key, '').strip()  # comment
            if v == '':  # comment
                t.difficulty_level = None  # comment
            else:  # comment
                try:  # comment
                    n = int(v)  # comment
                    if 1 <= n <= 3:  # comment
                        t.difficulty_level = n  # comment
                except ValueError:  # comment
                    pass  # comment
    _apply_attempts_settings_from_form(lesson, tasks, 'classwork')
    try:  # comment
        db.session.commit()  # comment
        from app.lessons.lesson_socket import emit_lesson_tasks_updated
        emit_lesson_tasks_updated(lesson_id, 'classwork')
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
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment
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
        diff_key = f'difficulty_level_{t.lesson_task_id}'  # comment
        if diff_key in request.form:  # comment
            v = request.form.get(diff_key, '').strip()  # comment
            if v == '':  # comment
                t.difficulty_level = None  # comment
            else:  # comment
                try:  # comment
                    n = int(v)  # comment
                    if 1 <= n <= 3:  # comment
                        t.difficulty_level = n  # comment
                except ValueError:  # comment
                    pass  # comment
    _apply_attempts_settings_from_form(lesson, tasks, 'exam')
    try:  # comment
        db.session.commit()  # comment
    except Exception:  # comment
        db.session.rollback()  # comment
        raise  # comment
    flash('Данные сохранены!', 'success')  # comment
    from app.lessons.lesson_socket import emit_lesson_tasks_updated
    emit_lesson_tasks_updated(lesson_id, 'exam')
    return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment


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
    
    status = request.json.get('status') if request.is_json else request.form.get('status')
    
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
        from app.lessons.lesson_socket import emit_lesson_tasks_updated
        emit_lesson_tasks_updated(lesson_id, lesson_task.assignment_type or 'classwork')
        
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
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error setting task status: {e}", exc_info=True)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({'success': False, 'error': 'Ошибка при сохранении статуса'}), 500
        flash('Ошибка при сохранении статуса.', 'error')
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))


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
    if 'difficulty_level' in data:  # comment
        v = data.get('difficulty_level')
        if isinstance(v, str) and v.strip() == '':
            lesson_task.difficulty_level = None
        elif v is None:
            lesson_task.difficulty_level = None
        elif isinstance(v, (int, float)) and 1 <= int(v) <= 3:
            lesson_task.difficulty_level = int(v)
    try:  # comment
        db.session.commit()  # comment
        from app.lessons.lesson_socket import emit_lesson_tasks_updated
        emit_lesson_tasks_updated(lesson_id, lesson_task.assignment_type or 'classwork')
    except Exception as e:  # comment
        db.session.rollback()  # comment
        logger.error(f"Failed to save teacher feedback: {e}", exc_info=True)  # comment
        return jsonify({'success': False, 'error': 'Ошибка сохранения'}), 500  # comment

    if status == 'graded' and lesson_task.task_id:
        try:
            student = getattr(lesson_task.lesson, 'student', None) if lesson_task.lesson else None
            user_id = getattr(student, 'user_id', None) if student else None
            if user_id:
                from app.analytics import AnalyticsEngine
                AnalyticsEngine.process_submission(
                    user_id=int(user_id),
                    task_id=lesson_task.task_id,
                    is_correct=bool(lesson_task.submission_correct) if lesson_task.submission_correct is not None else False,
                    time_spent_sec=lesson_task.time_spent_sec,
                    difficulty_level_override=lesson_task.difficulty_level,
                    attempt_no=max(1, len(getattr(lesson_task, 'attempts', []) or [])),
                    mode='homework_manual',
                )
                db.session.commit()
        except Exception as anal_err:
            logger.warning("Analytics process_submission (lesson_task graded) failed: %s", anal_err)
            db.session.rollback()

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
                link_url=url_for('lessons.lesson_classwork_view', lesson_id=lesson_id) + f"#task-{lesson_task.lesson_task_id}",
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
        'difficulty_level': lesson_task.difficulty_level,  # comment
    })  # comment


@lessons_bp.route('/lesson/<int:lesson_id>/messages')
@login_required
def lesson_messages_list(lesson_id: int):
    lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)

    scope = get_user_scope(current_user)
    if not scope.get('can_see_all'):
        if current_user.is_student():
            if not _get_current_lesson_student(lesson):
                return jsonify({'success': False, 'error': 'Forbidden'}), 403
        elif current_user.is_parent():
            if not can_user_access_student(current_user, student_platform_id=lesson.student_id):
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

    try:
        if not current_user.is_student():
            notify_student_and_parents(
                lesson.student,
                kind='lesson_comment',
                title='Новый комментарий по уроку',
                body=body,
                link_url=url_for('lessons.lesson_interactive_room', lesson_id=lesson.lesson_id),
                meta={'lesson_id': lesson.lesson_id},
            )
    except Exception as e:
        logger.warning(f"Failed to enqueue notification for lesson message: {e}")

    db.session.commit()

    try:
        from app.lessons.lesson_socket import emit_lesson_message_new
        created_at = getattr(msg, 'created_at', None)
        emit_lesson_message_new(lesson.lesson_id, {
            'id': msg.message_id,
            'author_user_id': current_user.id,
            'body': body,
            'created_at': created_at.isoformat() if created_at else None,
        })
    except Exception as e:
        logger.warning("emit_lesson_message_new: %s", e)

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
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment
    lesson = Lesson.query.get_or_404(lesson_id)
    result = perform_auto_check(lesson, 'homework')
    
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
    
    if isinstance(result[0], dict) and 'error' in result[0]:
        flash(result[0]['error'], result[0].get('category', 'error'))
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))
    
    if result[0] is None:
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))
    
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
    return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))

@lessons_bp.route('/lesson/<int:lesson_id>/classwork-auto-check', methods=['POST'])
@login_required
def lesson_classwork_auto_check(lesson_id):
    """Автопроверка классной работы"""
    if current_user.is_student() or current_user.is_parent():  # comment
        flash('Доступ запрещен', 'danger')  # comment
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment
    lesson = Lesson.query.get_or_404(lesson_id)
    result = perform_auto_check(lesson, 'classwork')
    
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
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment
    lesson = Lesson.query.get_or_404(lesson_id)
    result = perform_auto_check(lesson, 'exam')
    
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
    
    if isinstance(result[0], dict) and 'error' in result[0]:
        flash(result[0]['error'], result[0].get('category', 'error'))
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))
    
    if result[0] is None:
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))
    
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
    return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))

@lessons_bp.route('/lesson/<int:lesson_id>/homework-tasks/<int:lesson_task_id>/delete', methods=['POST'])
@login_required
def lesson_homework_delete_task(lesson_id, lesson_task_id):
    """Удаление задания из урока"""
    if current_user.is_student() or current_user.is_parent():  # comment
        flash('Доступ запрещен', 'danger')  # comment
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment
    lesson = Lesson.query.get_or_404(lesson_id)
    lesson_task = LessonTask.query.get_or_404(lesson_task_id)
    assignment_type = request.args.get('assignment_type', 'homework')

    if lesson_task.lesson_id != lesson_id:
        flash('Ошибка: задание не принадлежит этому уроку', 'danger')
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))

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

    from app.lessons.lesson_socket import emit_lesson_tasks_updated
    emit_lesson_tasks_updated(lesson_id, assignment_type or 'homework')

    if assignment_type == 'classwork':
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))
    return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))

@lessons_bp.route('/lesson/<int:lesson_id>/homework-not-assigned', methods=['POST'])
@login_required
def lesson_homework_not_assigned(lesson_id):
    """Отметка домашнего задания как не заданного"""
    if current_user.is_student() or current_user.is_parent():  # comment
        flash('Доступ запрещен', 'danger')  # comment
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment
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
    from app.lessons.lesson_socket import emit_lesson_tasks_updated
    emit_lesson_tasks_updated(lesson_id, 'homework')
    flash('Домашнее задание отмечено как «не задано».', 'info')
    return redirect(url_for('students.student_profile', student_id=lesson.student_id))

@lessons_bp.route('/lesson/<int:lesson_id>/homework-export-md')
@login_required
def lesson_homework_export_md(lesson_id):
    """Экспорт домашнего задания в Markdown"""
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
        return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id))  # comment
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

            try:  # Пытаемся выровнять sequence превентивно (без падения, если не Postgres)
                db_url = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')  # Берём URI базы
                is_pg = ('postgresql' in db_url) or ('postgres' in db_url)  # Проверяем, что это Postgres
                if is_pg:  # Выполняем только для Postgres
                    db.session.execute(text('SELECT setval(pg_get_serial_sequence(\'"Tasks"\', \'task_id\'), COALESCE((SELECT MAX("task_id") FROM "Tasks"), 0), true)'))  # Выравниваем sequence Tasks.task_id
                    db.session.commit()  # Коммитим фиксацию sequence
            except Exception:  # Если не удалось/не нужно — продолжаем без блокировки
                db.session.rollback()  # Откатываем на всякий случай
            
            count = 0
            created_task_ids = []
            for task_data in tasks_data:
                course_id = lesson.exam_course_id
                raw_cid = task_data.get('course_id') or task_data.get('exam_course_id')
                if raw_cid not in (None, ''):
                    try:
                        course_id = int(raw_cid)
                    except (TypeError, ValueError):
                        pass
                starter = (task_data.get('starter_code') or '').strip() or None
                sol_text = (task_data.get('solution') or '').strip()
                new_task = Tasks(
                    course_id=course_id,
                    task_number=int(task_data.get('number', 1)),
                    content_html=f'<div class="task-text">{task_data.get("content", "")}</div>',
                    answer=task_data.get('answer', '') or '',
                    site_task_id=f'manual:{uuid.uuid4()}',
                    source_url=None,
                    bank_origin='manual',
                    starter_code=starter,
                )
                db.session.add(new_task)
                db.session.flush()
                if sol_text:
                    db.session.add(TaskSolution(
                        task_id=new_task.task_id,
                        solution_text=sol_text,
                        source='manual',
                        needs_manual_review=False,
                    ))
                created_task_ids.append(new_task.task_id)

                lesson_task = LessonTask(
                    lesson_id=lesson.lesson_id,
                    task_id=new_task.task_id,
                    assignment_type=assignment_type
                )
                db.session.add(lesson_task)
                count += 1
                
            db.session.commit()

            if count > 0 and lesson.student:
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
                    task_ids=created_task_ids,
                    link_url=link_url,
                )
                try:
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    logger.warning(f"Could not commit pending assignment notification (manual tasks): {e}")
            
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
            
            if count > 0:
                from app.lessons.lesson_socket import emit_lesson_tasks_updated
                emit_lesson_tasks_updated(lesson.lesson_id, assignment_type or 'homework')

            return jsonify({'success': True, 'count': count})
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating manual tasks: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    return render_template('lesson_manual_create.html', lesson=lesson, assignment_type=assignment_type, task_numbers=get_task_numbers(None))

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
    lesson = Lesson.query.get_or_404(lesson_id)
    _lesson_studio_access(lesson)
    if not _lesson_studio_is_teacher():
         return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No selected file'}), 400
        
    if file:
        upload_folder = _lesson_material_root(lesson_id)
        try:
            filename, file_path, _size = save_uploaded_file(
                file=file,
                base_folder=upload_folder,
                allowed_exts={'pdf', 'png', 'jpg', 'jpeg', 'webp', 'doc', 'docx', 'ppt', 'pptx', 'xlsx', 'xls', 'txt'},
                max_bytes=20 * 1024 * 1024,
            )
        except Exception as e:
            return jsonify({'success': False, 'error': f'Не удалось загрузить файл: {e}'}), 400
        
        materials = lesson.materials or []
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
            'storage_path': os.path.join('lessons', str(lesson_id), stored_name),
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
    lesson = Lesson.query.get_or_404(lesson_id)
    _lesson_studio_access(lesson)
    if not _lesson_studio_is_teacher():
         return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
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
             filename = (url_to_delete.split('?')[0] or '').split('/')[-1]
             file_path = os.path.join(_lesson_material_root(lesson_id), secure_filename(filename))
             if not os.path.exists(file_path):
                 file_path = os.path.join(current_app.root_path, 'static', 'uploads', 'lessons', str(lesson_id), secure_filename(filename))
             if os.path.exists(file_path):
                 os.remove(file_path)
        except Exception as e:
            logger.warning(f"Failed to delete file {url_to_delete}: {e}")

        return jsonify({'success': True})
    
    return jsonify({'success': False, 'error': 'Material not found'}), 404



@lessons_bp.route('/lesson/<int:lesson_id>/whiteboard', methods=['GET'])
@login_required
def lesson_whiteboard_info(lesson_id):
    """Получить информацию о доске урока."""
    try:
        lesson = Lesson.query.get_or_404(lesson_id)
        
        try:
            whiteboard = lesson.whiteboard
        except Exception as e:
            logger.warning(f"Whiteboard relationship error, trying to create table: {e}")
            try:
                from sqlalchemy import inspect
                inspector = inspect(db.engine)
                table_names = inspector.get_table_names()
                if 'LessonWhiteboards' not in table_names and 'lessonwhiteboards' not in table_names:
                    LessonWhiteboard.__table__.create(db.engine)
                    logger.info("LessonWhiteboards table created on-demand")
            except Exception as create_err:
                logger.warning(f"Could not create LessonWhiteboards table: {create_err}")
            
            return jsonify({
                'success': True,
                'exists': False,
                'whiteboard': None,
                'note': 'Whiteboard feature initializing'
            })
        
        if not whiteboard:
            return jsonify({
                'success': True,
                'exists': False,
                'whiteboard': None
            })
        
        return jsonify({
            'success': True,
            'exists': True,
            'whiteboard': {
                'id': whiteboard.id,
                'miro_board_id': whiteboard.miro_board_id,
                'miro_board_url': whiteboard.miro_board_url,
                'miro_view_link': whiteboard.miro_view_link,
                'board_name': whiteboard.board_name,
                'is_active': whiteboard.is_active,
                'allow_student_edit': whiteboard.allow_student_edit,
                'created_at': whiteboard.created_at.isoformat() if whiteboard.created_at else None
            }
        })
    except Exception as e:
        logger.error(f"Error in lesson_whiteboard_info: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@lessons_bp.route('/lesson/<int:lesson_id>/whiteboard/create', methods=['POST'])
@login_required
def lesson_whiteboard_create(lesson_id):
    """Создать новую доску Miro для урока."""
    if current_user.is_student() or current_user.is_parent():
        return jsonify({'success': False, 'error': 'Только преподаватель может создать доску'}), 403
    
    lesson = Lesson.query.get_or_404(lesson_id)
    
    if lesson.whiteboard:
        return jsonify({
            'success': False, 
            'error': 'Доска уже существует',
            'whiteboard': {
                'miro_board_id': lesson.whiteboard.miro_board_id,
                'miro_board_url': lesson.whiteboard.miro_board_url
            }
        }), 400
    
    from datetime import datetime, timedelta
    miro_token = MiroUserToken.query.filter_by(user_id=current_user.id).first()
    if not miro_token or not miro_token.access_token:
        auth_url = url_for('miro_oauth_authorize', lesson_id=lesson_id, _external=True)
        return jsonify({
            'success': False,
            'error': 'Сначала подключите Miro. Нажмите «Подключить Miro» на этой странице.',
            'auth_required': True,
            'auth_url': auth_url
        }), 400
    now = datetime.utcnow()
    if miro_token.expires_at is not None and miro_token.expires_at <= (now - timedelta(seconds=60)):
        return jsonify({
            'success': False,
            'error': 'Сессия Miro истекла. Подключите Miro заново.',
            'auth_required': True,
            'auth_url': url_for('miro_oauth_authorize', lesson_id=lesson_id, _external=True)
        }), 400
    
    try:
        from app.lessons.miro_service import get_miro_service, MiroAPIError
        
        miro = get_miro_service(access_token=miro_token.access_token)
        
        student = lesson.student
        board_name = f"Урок: {lesson.topic or 'Без темы'}"
        if student:
            board_name = f"{student.name} - {board_name}"
        
        board_data = miro.create_board(
            name=board_name,
            description=f"Интерактивная доска для урока #{lesson_id}"
        )
        
        whiteboard = LessonWhiteboard(
            lesson_id=lesson_id,
            miro_board_id=board_data.get('id'),
            miro_board_url=board_data.get('viewLink'),
            miro_view_link=board_data.get('viewLink'),
            board_name=board_name,
            is_active=True,
            allow_student_edit=True
        )
        
        db.session.add(whiteboard)
        db.session.commit()
        
        audit_logger.log(
            action='whiteboard_created',
            entity='Lesson',
            entity_id=lesson_id,
            status='success',
            metadata={'miro_board_id': whiteboard.miro_board_id}
        )
        
        return jsonify({
            'success': True,
            'whiteboard': {
                'id': whiteboard.id,
                'miro_board_id': whiteboard.miro_board_id,
                'miro_board_url': whiteboard.miro_board_url,
                'miro_view_link': whiteboard.miro_view_link,
                'board_name': whiteboard.board_name,
                'embed_url': f"https://miro.com/app/live-embed/{whiteboard.miro_board_id}/?moveToViewport=-1000,-1000,2000,2000&embedAutoplay=false"
            }
        })
        
    except MiroAPIError as e:
        logger.error(f"Miro API error creating board: {e}")
        return jsonify({'success': False, 'error': f'Ошибка Miro API: {e.message}'}), 500
    except Exception as e:
        logger.error(f"Error creating whiteboard: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@lessons_bp.route('/lesson/<int:lesson_id>/whiteboard/settings', methods=['POST'])
@login_required
def lesson_whiteboard_settings(lesson_id):
    """Обновить настройки доски."""
    if current_user.is_student() or current_user.is_parent():
        return jsonify({'success': False, 'error': 'Доступ запрещён'}), 403
    
    lesson = Lesson.query.get_or_404(lesson_id)
    
    
    whiteboard = lesson.whiteboard
    if not whiteboard:
        return jsonify({'success': False, 'error': 'Доска не найдена'}), 404
    
    data = request.get_json() or {}
    
    if 'is_active' in data:
        whiteboard.is_active = bool(data['is_active'])
    
    if 'allow_student_edit' in data:
        whiteboard.allow_student_edit = bool(data['allow_student_edit'])
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'whiteboard': {
            'is_active': whiteboard.is_active,
            'allow_student_edit': whiteboard.allow_student_edit
        }
    })


@lessons_bp.route('/lesson/<int:lesson_id>/whiteboard/delete', methods=['POST'])
@login_required
def lesson_whiteboard_delete(lesson_id):
    """Удалить доску (отвязать от урока, доска в Miro остаётся)."""
    if current_user.is_student() or current_user.is_parent():
        return jsonify({'success': False, 'error': 'Доступ запрещён'}), 403
    
    lesson = Lesson.query.get_or_404(lesson_id)
    
    
    whiteboard = lesson.whiteboard
    if not whiteboard:
        return jsonify({'success': False, 'error': 'Доска не найдена'}), 404
    
    miro_board_id = whiteboard.miro_board_id
    
    db.session.delete(whiteboard)
    db.session.commit()
    
    audit_logger.log(
        action='whiteboard_deleted',
        entity='Lesson',
        entity_id=lesson_id,
        status='success',
        metadata={'miro_board_id': miro_board_id}
    )
    
    return jsonify({'success': True})


@lessons_bp.route('/lesson/<int:lesson_id>/whiteboard/invite', methods=['POST'])
@login_required
def lesson_whiteboard_invite(lesson_id):
    """Пригласить ученика на доску (identifier для Miro)."""
    if current_user.is_student() or current_user.is_parent():
        return jsonify({'success': False, 'error': 'Доступ запрещён'}), 403
    
    lesson = Lesson.query.get_or_404(lesson_id)
    
    
    whiteboard = lesson.whiteboard
    if not whiteboard:
        return jsonify({'success': False, 'error': 'Доска не найдена'}), 404
    
    data = request.get_json() or {}
    email = data.get('email') or data.get('identifier')
    if not email and lesson.student and getattr(lesson.student, 'user', None) and lesson.student.user:
        email = (lesson.student.user.username or '') + '@platform'
    if not email:
        return jsonify({'success': False, 'error': 'Укажите идентификатор для приглашения (identifier)'}), 400

    from datetime import datetime, timedelta
    miro_token = MiroUserToken.query.filter_by(user_id=current_user.id).first()
    if not miro_token or not miro_token.access_token:
        return jsonify({
            'success': False,
            'error': 'Сначала подключите Miro по кнопке «Подключить Miro».',
            'auth_required': True,
            'auth_url': url_for('miro_oauth_authorize', lesson_id=lesson_id, _external=True)
        }), 400
    now = datetime.utcnow()
    if miro_token.expires_at is not None and miro_token.expires_at <= (now - timedelta(seconds=60)):
        return jsonify({
            'success': False,
            'error': 'Сессия Miro истекла. Подключите Miro заново.',
            'auth_required': True,
            'auth_url': url_for('miro_oauth_authorize', lesson_id=lesson_id, _external=True)
        }), 400
    
    try:
        from app.lessons.miro_service import get_miro_service, MiroAPIError
        
        miro = get_miro_service(access_token=miro_token.access_token)
        
        role = "editor" if whiteboard.allow_student_edit else "viewer"
        
        result = miro.share_board(
            board_id=whiteboard.miro_board_id,
            email=email,
            role=role,
            message=f"Приглашение на интерактивную доску урока: {lesson.topic or 'Урок'}"
        )
        
        return jsonify({
            'success': True,
            'message': f'Приглашение отправлено',
            'role': role
        })
        
    except MiroAPIError as e:
        logger.error(f"Miro API error inviting user: {e}")
        return jsonify({'success': False, 'error': f'Ошибка Miro API: {e.message}'}), 500
    except Exception as e:
        logger.error(f"Error inviting to whiteboard: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@lessons_bp.route('/lesson/<int:lesson_id>/whiteboard/embed-url', methods=['GET'])
@login_required
def lesson_whiteboard_embed_url(lesson_id):
    """Получить URL для встраивания доски."""
    lesson = Lesson.query.get_or_404(lesson_id)
    
    
    whiteboard = lesson.whiteboard
    if not whiteboard:
        return jsonify({'success': False, 'error': 'Доска не найдена'}), 404
    
    is_teacher = not (current_user.is_student() or current_user.is_parent())
    is_active = whiteboard.is_active
    can_edit = whiteboard.allow_student_edit or is_teacher
    
    board_id = whiteboard.miro_board_id
    
    if is_teacher or (is_active and can_edit):
        embed_url = f"https://miro.com/app/live-embed/{board_id}/?moveToViewport=-1000,-1000,2000,2000&embedAutoplay=false"
        mode = "edit"
    else:
        embed_url = f"https://miro.com/app/live-embed/{board_id}/?moveToViewport=-1000,-1000,2000,2000&embedAutoplay=false"
        mode = "view"
    
    miro_authorized = False
    try:
        from app.models import MiroUserToken
        from datetime import datetime
        miro_token = MiroUserToken.query.filter_by(user_id=current_user.id).first()
        if miro_token and miro_token.access_token:
            if miro_token.expires_at is None or miro_token.expires_at > datetime.utcnow():
                miro_authorized = True
    except Exception as e:
        logger.warning(f"Could not check Miro auth status: {e}")
    
    return jsonify({
        'success': True,
        'embed_url': embed_url,
        'board_url': whiteboard.miro_board_url or f"https://miro.com/app/board/{board_id}/",
        'mode': mode,
        'is_active': is_active,
        'can_edit': can_edit,
        'miro_authorized': miro_authorized
    })


@lessons_bp.route('/lesson/<int:lesson_id>/whiteboard/miro-auth-status', methods=['GET'])
@login_required
def lesson_whiteboard_miro_auth_status(lesson_id):
    """Проверить статус Miro авторизации пользователя."""
    try:
        from app.models import MiroUserToken
        from datetime import datetime
        
        miro_token = MiroUserToken.query.filter_by(user_id=current_user.id).first()
        
        if not miro_token or not miro_token.access_token:
            return jsonify({
                'success': True,
                'authorized': False,
                'auth_url': url_for('miro_oauth_authorize', lesson_id=lesson_id, _external=True)
            })
        
        if miro_token.expires_at and miro_token.expires_at <= datetime.utcnow():
            return jsonify({
                'success': True,
                'authorized': False,
                'expired': True,
                'auth_url': url_for('miro_oauth_authorize', lesson_id=lesson_id, _external=True)
            })
        
        return jsonify({
            'success': True,
            'authorized': True,
            'miro_user_id': miro_token.miro_user_id
        })
        
    except Exception as e:
        logger.error(f"Error checking Miro auth status: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500



@lessons_bp.route('/lesson/<int:lesson_id>/videocall/room', methods=['POST'])
@login_required
def lesson_videocall_create_room(lesson_id):
    """Legacy redirect for videocall POST to V2 Studio Daily join."""
    return redirect(url_for('lessons.lesson_studio_daily_join', lesson_id=lesson_id), code=307)


@lessons_bp.route('/lesson/<int:lesson_id>/videocall/room', methods=['GET'])
@login_required
def lesson_videocall_get_room(lesson_id):
    """Legacy redirect for videocall GET to V2 Studio room."""
    return redirect(url_for('lessons.lesson_interactive_room', lesson_id=lesson_id), code=302)

@lessons_bp.route('/lesson/<int:lesson_id>/studio/daily/join', methods=['POST'])
@login_required
def lesson_studio_daily_join(lesson_id: int):
    lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)
    _lesson_studio_access(lesson)
    
    is_teacher = _lesson_studio_is_teacher()
    user_name = getattr(current_user, 'display_name', None) or current_user.username
    room_name = f"lesson-{lesson_id}"
    
    try:
        room_url = DailyService.get_or_create_room(room_name)
        token = DailyService.create_meeting_token(room_name, user_name, is_teacher)
        return jsonify({'success': True, 'room_url': room_url, 'token': token})
    except ValueError as e:
        logger.warning(f"Daily.co configuration error for lesson {lesson_id}: {e}")
        return jsonify({'success': False, 'error': 'Видеосервер не настроен или недоступен'}), 503
    except Exception as e:
        logger.error(f"Daily.co integration error for lesson {lesson_id}: {e}")
        return jsonify({'success': False, 'error': 'Не удалось подключиться к видеосерверу'}), 500
