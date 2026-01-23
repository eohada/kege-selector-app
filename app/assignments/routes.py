"""
Маршруты для системы заданий и сдачи работ
"""
import logging
from datetime import datetime, timedelta
from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import and_, or_, func, case
from sqlalchemy.orm import joinedload

from app.assignments import assignments_bp
from app.models import (
    db, Assignment, AssignmentTask, Submission, Answer,
    Student, User, Tasks, Lesson, LessonTask, Enrollment, GradebookEntry, SubmissionAttempt, RubricTemplate,
    TaskTemplate, TemplateTask
)
from app.students.utils import get_sorted_assignments
from core.db_models import SubmissionComment
from app.auth.rbac_utils import check_access, get_user_scope, has_permission
from core.db_models import moscow_now
from core.audit_logger import audit_logger
from app.notifications.service import notify_student_and_parents
from core.selector_logic import get_accepted_tasks, get_skipped_tasks, get_unique_tasks, reset_history, reset_skipped

logger = logging.getLogger(__name__)

def _normalize_assignment_type(value: str | None) -> str:
    v = (value or '').strip().lower()
    if v in {'homework', 'classwork', 'exam', 'test'}:
        return v
    return ''


def _assignment_type_label_short(value: str | None) -> str:
    v = _normalize_assignment_type(value)
    return {
        'homework': 'ДЗ',
        'classwork': 'КР',
        'exam': 'Проверочная',
        'test': 'Тест',
    }.get(v, v or '—')


def _assignment_type_label_long(value: str | None) -> str:
    v = _normalize_assignment_type(value)
    return {
        'homework': 'Домашняя работа',
        'classwork': 'Классная работа',
        'exam': 'Проверочная работа',
        'test': 'Тест',
    }.get(v, v or 'Работа')


def _now_naive_msk() -> datetime:
    now = moscow_now()
    try:
        return now.astimezone(moscow_now().tzinfo).replace(tzinfo=None)  # type: ignore[attr-defined]
    except Exception:
        try:
            return now.replace(tzinfo=None)  # type: ignore[call-arg]
        except Exception:
            return datetime.now()


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value or 0)
    except Exception:
        return default


def _can_manage_all_rubrics() -> bool:
    try:
        return bool(getattr(current_user, 'is_creator', None) and current_user.is_creator()) or bool(getattr(current_user, 'is_admin', None) and current_user.is_admin())
    except Exception:
        return False

@assignments_bp.route('/assignments/<int:assignment_id>/reviews/bulk', methods=['POST'])
@login_required
@check_access('assignment.grade')
def assignment_review_bulk_update(assignment_id: int):
    """
    Массовые действия по сдачам конкретной работы (Submission).
    Сейчас используем в "Журнале проверок": быстро вернуть все сданные работы на доработку.
    """
    if current_user.is_student() or current_user.is_parent():  # comment
        return redirect(url_for('main.dashboard'))  # comment

    action = (request.form.get('action') or '').strip().lower()
    status_filter = (request.form.get('status') or 'submitted').strip().lower()
    source = (request.form.get('source') or 'all').strip().lower()
    assignment_type = (request.form.get('assignment_type') or '').strip().lower()
    student_query = (request.form.get('student') or '').strip()

    if action not in {'mark_returned', 'mark_graded'}:
        flash('Некорректное действие.', 'danger')
        return redirect(url_for('lessons.review_queue', status=status_filter, source=source, assignment_type=assignment_type, student=student_query))

    # QA: массовые действия доступны только из статуса "Сдано",
    # иначе в списках "на доработку/проверено" это вводит в заблуждение.
    if status_filter != 'submitted':
        flash('Массовые действия доступны только в статусе «Сдано».', 'warning')
        return redirect(url_for('lessons.review_queue', status=status_filter, source=source, assignment_type=assignment_type, student=student_query))

    assignment = Assignment.query.get_or_404(assignment_id)

    scope = get_user_scope(current_user)
    if not scope.get('can_see_all') and assignment.created_by_id != current_user.id:
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('assignments.assignments_list'))

    q = Submission.query.options(joinedload(Submission.student)).filter(Submission.assignment_id == assignment.assignment_id)
    # Массовые действия применяем только к реально сданным
    q = q.filter(Submission.status.in_(['SUBMITTED', 'LATE']))

    subs = q.all()
    if not subs:
        flash('Нет сданных работ для массового действия.', 'info')
        return redirect(url_for('lessons.review_queue', status=status_filter, source=source, assignment_type=assignment_type, student=student_query))

    updated = 0
    skipped = 0
    for sub in subs:
        if action == 'mark_returned':
            sub.status = 'RETURNED'
        else:
            # mark_graded: только если есть итоговые баллы
            if sub.total_score is None or sub.max_score is None:
                skipped += 1
                continue
            sub.status = 'GRADED'
            sub.graded_at = moscow_now()
        try:
            # Снимок попытки: полезно для истории пересдач (returned тоже важен)
            _record_submission_attempt(sub)
        except Exception:
            pass

        # Уведомления: только внутренние (email не используем)
        try:
            if sub.student:
                if action == 'mark_returned':
                    notify_student_and_parents(
                        sub.student,
                        kind='assignment_returned',
                        title='Работа возвращена на доработку',
                        body=None,
                        link_url=url_for('assignments.submission_view', submission_id=sub.submission_id),
                        meta={'assignment_id': assignment.assignment_id, 'submission_id': sub.submission_id, 'status': 'RETURNED'},
                    )
                else:
                    notify_student_and_parents(
                        sub.student,
                        kind='assignment_graded',
                        title='Работа проверена',
                        body=(sub.teacher_feedback or '').strip() or None,
                        link_url=url_for('assignments.submission_view', submission_id=sub.submission_id),
                        meta={'assignment_id': assignment.assignment_id, 'submission_id': sub.submission_id, 'status': 'GRADED'},
                    )
        except Exception:
            pass
        updated += 1

        if action == 'mark_graded':
            try:
                _upsert_gradebook_from_submission(sub, actor_user_id=current_user.id)
            except Exception:
                pass

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Bulk review failed for assignment {assignment_id}: {e}", exc_info=True)
        audit_logger.log_error(action=f'assignment_bulk_{action}', entity='Assignment', entity_id=assignment_id, error=str(e))
        flash('Ошибка при массовом обновлении статуса.', 'danger')
        return redirect(url_for('lessons.review_queue', status=status_filter, source=source, assignment_type=assignment_type, student=student_query))

    try:
        audit_logger.log(
            action=f'assignment_bulk_{action}',
            entity='Assignment',
            entity_id=assignment.assignment_id,
            status='success',
            metadata={'updated': updated, 'skipped': skipped},
        )
    except Exception:
        pass

    if action == 'mark_returned':
        flash('Сданные работы возвращены на доработку.', 'success')
    else:
        if skipped:
            flash(f'Отмечено как «Проверено»: {updated}. Пропущено без итоговых баллов: {skipped}.', 'warning')
        else:
            flash('Сданные работы отмечены как «Проверено».', 'success')
    return redirect(url_for('lessons.review_queue', status=status_filter, source=source, assignment_type=assignment_type, student=student_query))


@assignments_bp.route('/submissions/<int:submission_id>/quick-return', methods=['POST'])
@login_required
@check_access('assignment.grade')
def submission_quick_return(submission_id: int):
    """Быстро вернуть 1 сдачу на доработку прямо из очереди проверок."""
    if current_user.is_student() or current_user.is_parent():  # comment
        return redirect(url_for('main.dashboard'))  # comment

    status_filter = (request.form.get('status') or 'submitted').strip().lower()
    source = (request.form.get('source') or 'all').strip().lower()
    assignment_type = (request.form.get('assignment_type') or '').strip().lower()
    student_query = (request.form.get('student') or '').strip()

    submission = Submission.query.options(
        joinedload(Submission.assignment),
        joinedload(Submission.student),
    ).get_or_404(submission_id)

    assignment = submission.assignment
    if not assignment:
        flash('Работа не найдена.', 'danger')
        return redirect(url_for('lessons.review_queue', status=status_filter, source=source, assignment_type=assignment_type, student=student_query))

    scope = get_user_scope(current_user)
    if not scope.get('can_see_all') and assignment.created_by_id != current_user.id:
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('lessons.review_queue', status=status_filter, source=source, assignment_type=assignment_type, student=student_query))

    # Возвращать можно только из "сдано" (SUBMITTED/LATE)
    if (submission.status or '').upper() not in {'SUBMITTED', 'LATE'}:
        flash('Эту сдачу нельзя вернуть из текущего статуса.', 'warning')
        return redirect(url_for('lessons.review_queue', status=status_filter, source=source, assignment_type=assignment_type, student=student_query))

    submission.status = 'RETURNED'
    try:
        _record_submission_attempt(submission)
    except Exception:
        pass

    try:
        if submission.student:
            notify_student_and_parents(
                submission.student,
                kind='assignment_returned',
                title='Работа возвращена на доработку',
                body=None,
                link_url=url_for('assignments.submission_view', submission_id=submission.submission_id),
                meta={'assignment_id': assignment.assignment_id, 'submission_id': submission.submission_id, 'status': 'RETURNED'},
            )
    except Exception:
        pass

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Quick return failed for submission {submission_id}: {e}", exc_info=True)
        audit_logger.log_error(action='submission_quick_returned', entity='Submission', entity_id=submission_id, error=str(e))
        flash('Ошибка при возврате на доработку.', 'danger')
        return redirect(url_for('lessons.review_queue', status=status_filter, source=source, assignment_type=assignment_type, student=student_query))

    try:
        audit_logger.log(
            action='submission_quick_returned',
            entity='Submission',
            entity_id=submission.submission_id,
            status='success',
            metadata={'assignment_id': assignment.assignment_id, 'student_id': submission.student_id},
        )
    except Exception:
        pass

    flash('Сдача возвращена на доработку.', 'success')
    return redirect(url_for('lessons.review_queue', status=status_filter, source=source, assignment_type=assignment_type, student=student_query))


def _upsert_gradebook_from_submission(submission: Submission, actor_user_id: int | None = None) -> None:
    """Создаёт/обновляет запись в журнале по результату проверенной работы."""
    if not submission:
        return
    if (submission.status or '').upper() != 'GRADED':
        return
    if not submission.assignment:
        return

    entry = GradebookEntry.query.filter_by(
        student_id=submission.student_id,
        kind='assignment',
        submission_id=submission.submission_id,
    ).first()

    if not entry:
        entry = GradebookEntry(
            student_id=submission.student_id,
            kind='assignment',
            submission_id=submission.submission_id,
            created_by_user_id=actor_user_id,
            title=submission.assignment.title or 'Работа',
        )
        db.session.add(entry)

    entry.category = (submission.assignment.assignment_type or '').strip().lower() or None
    entry.title = submission.assignment.title or entry.title or 'Работа'
    entry.comment = (submission.teacher_feedback or '').strip() or None
    entry.score = submission.total_score
    entry.max_score = submission.max_score
    entry.grade_text = None
    entry.weight = 1


def _record_submission_attempt(submission: Submission) -> None:
    """Записываем попытку сдачи для Submission (история пересдач)."""
    if not submission:
        return
    try:
        last_no = (
            db.session.query(db.func.max(SubmissionAttempt.attempt_no))
            .filter(SubmissionAttempt.submission_id == submission.submission_id)
            .scalar()
        )
        next_no = int(last_no or 0) + 1
    except Exception:
        next_no = 1

    attempt = SubmissionAttempt(
        submission_id=submission.submission_id,
        attempt_no=next_no,
        submitted_at=submission.submitted_at or moscow_now(),
        graded_at=submission.graded_at,
        status=submission.status,
        total_score=submission.total_score,
        max_score=submission.max_score,
        percentage=submission.percentage,
        teacher_feedback=submission.teacher_feedback,
    )
    db.session.add(attempt)


# ============================================================================
# УТИЛИТЫ
# ============================================================================

def get_student_by_user_id(user_id):
    """Получить Student по User.id (через email)"""
    user = User.query.get(user_id)
    if not user:
        return None

    email = (str(user.email).strip() if user.email else '')
    username = (str(user.username).strip() if user.username else '')

    # 1) email -> Student.email (case-insensitive)
    if email:
        st = Student.query.filter(func.lower(Student.email) == email.lower()).first()
        if st:
            return st

    # 2) username -> Student.platform_id (если email пустой/не совпадает)
    if username:
        try:
            st = Student.query.filter(Student.platform_id == username).first()
            if st:
                return st
        except Exception:
            pass

    # 3) fallback: Student.student_id == User.id — но только если у Student нет email
    # (чтобы избежать коллизий Users.id vs Students.student_id)
    try:
        st = Student.query.filter(Student.student_id == int(user_id), Student.email.is_(None)).first()
        if st:
            return st
    except Exception:
        pass

    return None


def get_students_for_tutor(tutor_user_id):
    """Получить список Student для тьютора"""
    enrollments = Enrollment.query.filter_by(
        tutor_id=tutor_user_id,
        status='active'
    ).all()
    
    user_ids = [e.student_id for e in (enrollments or []) if getattr(e, 'student_id', None)]
    if not user_ids:
        return []

    student_users = User.query.filter(User.id.in_(user_ids)).all()

    emails = []
    usernames = []
    for u in (student_users or []):
        if not u:
            continue
        if u.email and str(u.email).strip():
            emails.append(str(u.email).strip().lower())
        if u.username and str(u.username).strip():
            usernames.append(str(u.username).strip())

    # 1) email -> Student.email (case-insensitive)
    # 2) username -> Student.platform_id
    # 3) fallback: Student.student_id in user_ids — но только если Student.email is NULL
    q = Student.query
    filters = []
    if emails:
        filters.append(func.lower(Student.email).in_(emails))
    if usernames:
        filters.append(Student.platform_id.in_(usernames))
    try:
        filters.append((Student.student_id.in_([int(x) for x in user_ids])) & (Student.email.is_(None)))
    except Exception:
        pass

    if not filters:
        return []

    # OR по всем вариантам сопоставления
    return q.filter(or_(*filters)).all()


def auto_grade_answer(answer, assignment_task):
    """
    Автоматическая проверка ответа
    Возвращает (is_correct, score)
    """
    task = assignment_task.task
    
    # Для SINGLE_CHOICE (задания с одним правильным ответом)
    if task.task_number in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23]:
        # Сравниваем ответ ученика с эталоном
        student_answer = answer.value.strip() if answer.value else ""
        correct_answer = task.answer.strip() if task.answer else ""
        
        if student_answer.lower() == correct_answer.lower():
            return True, assignment_task.max_score
        else:
            return False, 0
    
    # Для CODE (задания 24-27) - можно добавить более сложную логику
    # Пока возвращаем None - требует ручной проверки
    if task.task_number in [24, 25, 26, 27]:
        return None, None
    
    # По умолчанию - требует ручной проверки
    return None, None


# ============================================================================
# API: СОЗДАНИЕ И РАСПРЕДЕЛЕНИЕ РАБОТ (TEACHER)
# ============================================================================

@assignments_bp.route('/assignments/distribute', methods=['POST'])
@login_required
@check_access('assignment.create')
def distribute_assignment():
    """
    Создание и распределение работы среди учеников
    POST /assignments/distribute
    Body: {
        "title": "ЕГЭ Вариант №5",
        "type": "TEST",
        "deadline": "2024-06-01T12:00:00Z",
        "tasks": [{"task_id": 123, "max_score": 1}, ...],
        "recipientIds": [1, 2, 3] или "groupId": "all"
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Некорректный формат данных'}), 400
        
        title = data.get('title', '').strip()
        assignment_type = data.get('type', 'homework')  # homework, classwork, exam, test
        deadline_str = data.get('deadline')
        hard_deadline = data.get('hard_deadline', False)
        time_limit_minutes = data.get('time_limit_minutes')
        description = data.get('description', '').strip()
        lesson_id = data.get('lesson_id')
        tasks_data = data.get('tasks', [])  # [{"task_id": 123, "max_score": 1, "order": 0}, ...]
        recipient_ids = data.get('recipientIds', [])  # Список student_id
        group_id = data.get('groupId')  # "all" или конкретная группа
        
        # Валидация
        if not title:
            return jsonify({'success': False, 'error': 'Название работы обязательно'}), 400
        
        if not deadline_str:
            return jsonify({'success': False, 'error': 'Дедлайн обязателен'}), 400
        
        try:
            deadline = datetime.fromisoformat(deadline_str.replace('Z', '+00:00'))
            if deadline.tzinfo:
                deadline = deadline.astimezone(moscow_now().tzinfo).replace(tzinfo=None)
        except Exception as e:
            return jsonify({'success': False, 'error': f'Некорректный формат дедлайна: {e}'}), 400
        
        if not tasks_data:
            return jsonify({'success': False, 'error': 'Добавьте хотя бы одну задачу'}), 400
        
        # Определяем получателей
        scope = get_user_scope(current_user)
        student_ids = []
        
        if group_id == 'all' and scope['can_see_all']:
            # Все ученики
            student_ids = [s.student_id for s in Student.query.filter_by(is_active=True).all()]
        elif group_id == 'all' and not scope['can_see_all']:
            # Все доступные ученики тьютора
            students = get_students_for_tutor(current_user.id)
            student_ids = [s.student_id for s in students]
        elif recipient_ids:
            # Конкретные ученики
            # Проверяем доступ
            if not scope['can_see_all']:
                accessible_students = get_students_for_tutor(current_user.id)
                accessible_ids = [s.student_id for s in accessible_students]
                recipient_ids = [rid for rid in recipient_ids if rid in accessible_ids]
            student_ids = recipient_ids
        
        if not student_ids:
            return jsonify({'success': False, 'error': 'Не выбраны получатели работы'}), 400
        
        # Создаем Assignment
        assignment = Assignment(
            title=title,
            description=description,
            assignment_type=assignment_type,
            deadline=deadline,
            hard_deadline=hard_deadline,
            time_limit_minutes=time_limit_minutes,
            created_by_id=current_user.id,
            lesson_id=lesson_id,
            is_active=True
        )
        db.session.add(assignment)
        db.session.flush()  # Получаем assignment_id
        
        # Создаем AssignmentTask
        for idx, task_data in enumerate(tasks_data):
            task_id = task_data.get('task_id')
            max_score = task_data.get('max_score', 1)
            order_index = task_data.get('order', idx)
            requires_manual = task_data.get('requires_manual_grading', False)
            
            if not task_id:
                continue
            
            task = Tasks.query.get(task_id)
            if not task:
                continue
            
            # Определяем, требует ли задача ручной проверки
            if task.task_number in [24, 25, 26, 27] or requires_manual:
                requires_manual_grading = True
            else:
                requires_manual_grading = False
            
            assignment_task = AssignmentTask(
                assignment_id=assignment.assignment_id,
                task_id=task_id,
                order_index=order_index,
                max_score=max_score,
                requires_manual_grading=requires_manual_grading
            )
            db.session.add(assignment_task)
        
        # Создаем Submission для каждого ученика
        for student_id in student_ids:
            submission = Submission(
                assignment_id=assignment.assignment_id,
                student_id=student_id,
                status='ASSIGNED',
                assigned_at=moscow_now(),
                max_score=sum(at.max_score for at in assignment.tasks)
            )
            db.session.add(submission)
        
        db.session.commit()
        
        audit_logger.log(
            action='create_assignment',
            entity='Assignment',
            entity_id=assignment.assignment_id,
            status='success',
            metadata={
                'title': title,
                'type': assignment_type,
                'recipients_count': len(student_ids),
                'tasks_count': len(assignment.tasks)
            }
        )
        
        return jsonify({
            'success': True,
            'assignment_id': assignment.assignment_id,
            'submissions_count': len(student_ids)
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in distribute_assignment: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# ПРОСМОТР РАБОТ (TEACHER)
# ============================================================================

@assignments_bp.route('/assignments')
@login_required
@check_access('assignment.view')
def assignments_list():
    """
    Список работ (центр управления):
    - фильтры/поиск/сортировка
    - агрегированная статистика по сдачам без N+1
    - KPI по состояниям (нужно проверить/просрочено/на доработке/готово)
    """
    scope = get_user_scope(current_user)

    q_text = (request.args.get('q') or '').strip()
    atype = _normalize_assignment_type(request.args.get('type'))
    status_filter = (request.args.get('status') or 'all').strip().lower()
    sort = (request.args.get('sort') or 'created_desc').strip().lower()
    show_archived = (request.args.get('archived') or '').strip() == '1'

    now = _now_naive_msk()

    subq = (
        db.session.query(
            Submission.assignment_id.label('assignment_id'),
            func.count(Submission.submission_id).label('total_students'),
            func.sum(
                case(
                    (Submission.status.in_(['SUBMITTED', 'LATE', 'GRADED', 'RETURNED']), 1),
                    else_=0,
                )
            ).label('submitted'),
            func.sum(
                case(
                    (Submission.status.in_(['SUBMITTED', 'LATE']), 1),
                    else_=0,
                )
            ).label('to_grade'),
            func.sum(case((Submission.status == 'GRADED', 1), else_=0)).label('graded'),
            func.sum(case((Submission.status == 'RETURNED', 1), else_=0)).label('returned'),
            func.sum(case((Submission.status == 'IN_PROGRESS', 1), else_=0)).label('in_progress'),
            func.sum(case((Submission.status == 'ASSIGNED', 1), else_=0)).label('assigned'),
        )
        .group_by(Submission.assignment_id)
        .subquery()
    )

    tasks_subq = (
        db.session.query(
            AssignmentTask.assignment_id.label('assignment_id'),
            func.count(AssignmentTask.assignment_task_id).label('tasks_count'),
        )
        .group_by(AssignmentTask.assignment_id)
        .subquery()
    )

    total_students_col = func.coalesce(subq.c.total_students, 0)
    submitted_col = func.coalesce(subq.c.submitted, 0)
    graded_col = func.coalesce(subq.c.graded, 0)
    to_grade_col = func.coalesce(subq.c.to_grade, 0)
    returned_col = func.coalesce(subq.c.returned, 0)
    in_progress_col = func.coalesce(subq.c.in_progress, 0)
    assigned_col = func.coalesce(subq.c.assigned, 0)
    pending_col = assigned_col + in_progress_col + returned_col
    tasks_count_col = func.coalesce(tasks_subq.c.tasks_count, 0)

    base_query = (
        db.session.query(
            Assignment,
            total_students_col.label('total_students'),
            submitted_col.label('submitted'),
            graded_col.label('graded'),
            to_grade_col.label('to_grade'),
            returned_col.label('returned'),
            in_progress_col.label('in_progress'),
            assigned_col.label('assigned'),
            tasks_count_col.label('tasks_count'),
        )
        .outerjoin(subq, subq.c.assignment_id == Assignment.assignment_id)
        .outerjoin(tasks_subq, tasks_subq.c.assignment_id == Assignment.assignment_id)
    )

    if not show_archived:
        base_query = base_query.filter(Assignment.is_active.is_(True))

    if not scope.get('can_see_all'):
        base_query = base_query.filter(Assignment.created_by_id == current_user.id)

    if atype:
        base_query = base_query.filter(func.lower(Assignment.assignment_type) == atype)

    if q_text:
        needle = f"%{q_text.lower()}%"
        base_query = base_query.filter(func.lower(Assignment.title).like(needle))

    # KPI считаем на "базовом" наборе (без status_filter и sort), чтобы табы были понятными
    kpi_rows = base_query.all()

    def _derive_flags(a: Assignment, row) -> dict:
        total_students = _safe_int(getattr(row, 'total_students', 0))
        to_grade = _safe_int(getattr(row, 'to_grade', 0))
        returned = _safe_int(getattr(row, 'returned', 0))
        in_progress = _safe_int(getattr(row, 'in_progress', 0))
        assigned = _safe_int(getattr(row, 'assigned', 0))
        pending = assigned + in_progress + returned

        is_overdue = bool(a.deadline and a.deadline < now and pending > 0)
        is_completed = bool(total_students > 0 and pending == 0 and to_grade == 0)
        is_active = bool(a.deadline and a.deadline >= now and (pending > 0 or to_grade > 0))
        return {
            'total_students': total_students,
            'to_grade': to_grade,
            'returned': returned,
            'in_progress': in_progress,
            'assigned': assigned,
            'pending': pending,
            'is_overdue': is_overdue,
            'is_completed': is_completed,
            'is_active': is_active,
        }

    kpis = {
        'total': 0,
        'active': 0,
        'needs_grading': 0,
        'overdue': 0,
        'returned': 0,
        'completed': 0,
        'archived': 0,
    }
    for row in kpi_rows:
        a: Assignment = row[0]
        flags = _derive_flags(a, row)
        kpis['total'] += 1
        if not a.is_active:
            kpis['archived'] += 1
        if flags['is_active']:
            kpis['active'] += 1
        if flags['to_grade'] > 0:
            kpis['needs_grading'] += 1
        if flags['is_overdue']:
            kpis['overdue'] += 1
        if flags['returned'] > 0:
            kpis['returned'] += 1
        if flags['is_completed']:
            kpis['completed'] += 1

    # Применяем status_filter
    filtered_query = base_query
    if status_filter == 'active':
        filtered_query = filtered_query.filter(Assignment.deadline >= now).filter((pending_col > 0) | (to_grade_col > 0))
    elif status_filter == 'needs_grading':
        filtered_query = filtered_query.filter(to_grade_col > 0)
    elif status_filter == 'overdue':
        filtered_query = filtered_query.filter(Assignment.deadline < now).filter(pending_col > 0)
    elif status_filter == 'returned':
        filtered_query = filtered_query.filter(returned_col > 0)
    elif status_filter == 'completed':
        filtered_query = filtered_query.filter(total_students_col > 0).filter(pending_col == 0).filter(to_grade_col == 0)
    elif status_filter == 'archived':
        filtered_query = filtered_query.filter(Assignment.is_active.is_(False))

    # Сортировка
    if sort == 'deadline_asc':
        filtered_query = filtered_query.order_by(Assignment.deadline.asc(), Assignment.created_at.desc())
    elif sort == 'deadline_desc':
        filtered_query = filtered_query.order_by(Assignment.deadline.desc(), Assignment.created_at.desc())
    elif sort == 'title_asc':
        filtered_query = filtered_query.order_by(func.lower(Assignment.title).asc(), Assignment.created_at.desc())
    else:
        filtered_query = filtered_query.order_by(Assignment.created_at.desc(), Assignment.assignment_id.desc())

    rows = filtered_query.all()

    assignments_data = []
    for row in rows:
        assignment: Assignment = row[0]
        total_students = _safe_int(getattr(row, 'total_students', 0))
        submitted = _safe_int(getattr(row, 'submitted', 0))
        graded = _safe_int(getattr(row, 'graded', 0))
        to_grade = _safe_int(getattr(row, 'to_grade', 0))
        returned = _safe_int(getattr(row, 'returned', 0))
        in_progress = _safe_int(getattr(row, 'in_progress', 0))
        assigned = _safe_int(getattr(row, 'assigned', 0))
        tasks_count = _safe_int(getattr(row, 'tasks_count', 0))
        pending = assigned + in_progress + returned

        is_overdue = bool(assignment.deadline and assignment.deadline < now and pending > 0)
        is_completed = bool(total_students > 0 and pending == 0 and to_grade == 0)

        assignments_data.append({
            'assignment': assignment,
            'type_short': _assignment_type_label_short(assignment.assignment_type),
            'type_long': _assignment_type_label_long(assignment.assignment_type),
            'tasks_count': tasks_count,
            'total_students': total_students,
            'submitted': submitted,
            'graded': graded,
            'to_grade': to_grade,
            'returned': returned,
            'in_progress': in_progress,
            'assigned': assigned,
            'pending': pending,
            'is_overdue': is_overdue,
            'is_completed': is_completed,
            'is_archived': bool(not assignment.is_active),
        })

    return render_template(
        'assignments_list.html',
        assignments_data=assignments_data,
        filters={
            'q': q_text,
            'type': atype,
            'status': status_filter,
            'sort': sort,
            'archived': '1' if show_archived else '0',
        },
        kpis=kpis,
        now=now,
        can_create=has_permission(current_user, 'assignment.create'),
    )


# ============================================================================
# TASK POOL (ACCEPTED) — unified entrypoint for assignment creation
# ============================================================================

@assignments_bp.route('/assignments/accepted')
@login_required
@check_access('assignment.create')
def assignments_accepted():
    """
    "Принятые задания" — буфер между генератором и созданием работ.
    Живёт рядом с разделом "Работы", чтобы не дублировать разделы.
    """
    try:
        task_type = request.args.get('task_type', type=int, default=None)
        assignment_type = (request.args.get('assignment_type') or 'homework').strip().lower()
        if assignment_type not in ['homework', 'classwork', 'exam']:
            assignment_type = 'homework'
        open_create = (request.args.get('create') or '').strip() == '1'

        accepted_tasks = get_accepted_tasks(task_type=task_type)
        if not accepted_tasks:
            flash('Нет принятых заданий.' if not task_type else f'Нет принятых заданий типа {task_type}.', 'info')
            return redirect(url_for('assignments.assignments_list'))

        # Recipients list for the "create assignment" modal
        recipient_options = []
        try:
            scope = get_user_scope(current_user)
            if scope.get('can_see_all'):
                recipient_options = (
                    Student.query.filter(Student.is_active.is_(True))
                    .order_by(Student.name.asc(), Student.student_id.asc())
                    .limit(500)
                    .all()
                )
            else:
                # Reuse mapping logic from assignments utils
                tutor_students = get_students_for_tutor(current_user.id) or []
                ids = [int(s.student_id) for s in tutor_students if getattr(s, 'student_id', None)]
                if ids:
                    recipient_options = (
                        Student.query.filter(Student.student_id.in_(ids))
                        .order_by(Student.name.asc(), Student.student_id.asc())
                        .limit(500)
                        .all()
                    )
        except Exception:
            recipient_options = []

        return render_template(
            'accepted.html',
            tasks=accepted_tasks,
            task_type=task_type,
            assignment_type=assignment_type,
            open_create=open_create,
            recipient_options=recipient_options,
            active_page='assignments',
            accepted_base_url=url_for('assignments.assignments_accepted', assignment_type=assignment_type),
            clear_accepted_url=url_for('assignments.assignments_accepted_clear'),
            back_url=url_for('assignments.assignments_list'),
        )
    except Exception as e:
        flash(f'Ошибка: {e}', 'danger')
        return redirect(url_for('assignments.assignments_list'))


@assignments_bp.route('/assignments/accepted/clear', methods=['POST'])
@login_required
@check_access('assignment.create')
def assignments_accepted_clear():
    """Очистить принятые задания (UsageHistory)."""
    raw = (request.form.get('task_type') or '').strip()
    task_type = None
    if raw:
        try:
            task_type = int(raw)
        except Exception:
            task_type = None

    try:
        reset_history(task_type=task_type)
        audit_logger.log(
            action='accepted_clear',
            entity='Task',
            entity_id=None,
            status='success',
            metadata={'task_type': task_type},
        )
        flash('Принятые задания очищены.' if not task_type else f'Принятые задания типа {task_type} очищены.', 'success')
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        flash(f'Не удалось очистить принятые задания: {e}', 'danger')

    return redirect(url_for('assignments.assignments_list'))


@assignments_bp.route('/assignments/skipped')
@login_required
@check_access('task.manage')
def assignments_skipped():
    """Пропущенные задания (глобальные пропуски) — рядом с работами, как единый раздел."""
    try:
        task_type = request.args.get('task_type', type=int, default=None)
        skipped_tasks = get_skipped_tasks(task_type=task_type)
        if not skipped_tasks:
            flash('Нет пропущенных заданий.' if not task_type else f'Нет пропущенных заданий типа {task_type}.', 'info')
            return redirect(url_for('assignments.assignments_list'))

        return render_template(
            'skipped.html',
            tasks=skipped_tasks,
            task_type=task_type,
            active_page='assignments',
            skipped_base_url=url_for('assignments.assignments_skipped'),
            back_url=url_for('assignments.assignments_list'),
        )
    except Exception as e:
        flash(f'Ошибка: {e}', 'danger')
        return redirect(url_for('assignments.assignments_list'))


@assignments_bp.route('/assignments/generator/results')
@login_required
@check_access('task.manage')
def assignments_generator_results():
    """
    Результаты генерации — переехали из генератора в раздел "Работы" (как единый UX),
    но логика генерации осталась прежней.
    """
    try:
        task_type = request.args.get('task_type', type=int)
        limit_count = request.args.get('limit_count', type=int)
        use_skipped = request.args.get('use_skipped', 'false').lower() == 'true'
        lesson_id = request.args.get('lesson_id', type=int)
        assignment_type = request.args.get('assignment_type', default='homework')
        search_task_id = request.args.get('search_task_id', type=int)
        template_id = request.args.get('template_id', type=int)

        if assignment_type not in ['homework', 'classwork', 'exam']:
            assignment_type = 'homework'

        if not task_type or not limit_count:
            flash('Не указаны тип задания или количество заданий.', 'danger')
            if lesson_id:
                return redirect(url_for('kege_generator.kege_generator', lesson_id=lesson_id, assignment_type=assignment_type))
            return redirect(url_for('kege_generator.kege_generator', assignment_type=assignment_type))
    except Exception:
        flash('Неверные параметры запроса.', 'danger')
        assignment_type = request.args.get('assignment_type', 'homework')
        lesson_id = request.args.get('lesson_id', type=int)
        if lesson_id:
            return redirect(url_for('kege_generator.kege_generator', lesson_id=lesson_id, assignment_type=assignment_type))
        return redirect(url_for('kege_generator.kege_generator', assignment_type=assignment_type))

    lesson = None
    student = None
    student_id = None
    if lesson_id:
        try:
            lesson = Lesson.query.get_or_404(lesson_id)
            student = lesson.student if lesson else None
            student_id = student.student_id if student else None
        except Exception:
            flash('Ошибка при получении урока', 'error')
            return redirect(url_for('kege_generator.kege_generator', assignment_type=assignment_type))

    try:
        if search_task_id:
            task = Tasks.query.filter_by(task_id=search_task_id).first()
            if task:
                tasks = [task]
                task_type = task.task_number
            else:
                flash(f'Задание с ID {search_task_id} не найдено.', 'warning')
                tasks = []
        else:
            tasks = get_unique_tasks(task_type, limit_count, use_skipped=use_skipped, student_id=student_id)
    except Exception as e:
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
                'student_name': student.name if student and hasattr(student, 'name') else None,
            },
        )
    except Exception:
        pass

    if not tasks:
        if use_skipped:
            flash(f'Задания типа {task_type} закончились! Все доступные задания (включая пропущенные) были использованы.', 'warning')
        else:
            flash(f'Задания типа {task_type} закончились! Попробуйте включить пропущенные задания или сбросьте историю.', 'warning')
        if lesson_id:
            return redirect(url_for('kege_generator.kege_generator', lesson_id=lesson_id, assignment_type=assignment_type))
        return redirect(url_for('kege_generator.kege_generator', assignment_type=assignment_type))

    return render_template(
        'results.html',
        tasks=tasks,
        task_type=task_type,
        lesson=lesson,
        student=student,
        lesson_id=lesson_id,
        assignment_type=assignment_type,
        template_id=template_id,
        active_page='assignments',
    )


@assignments_bp.route('/assignments/create')
@login_required
@check_access('assignment.create')
def assignment_create():
    """
    Единый мастер создания работы.

    Источники:
    - source=accepted: из буфера принятых (UsageHistory)
    - source=template: из шаблона (TaskTemplate)
    - source=manual: вручную (вставить task_id)
    """
    source = (request.args.get('source') or 'accepted').strip().lower()
    if source not in {'accepted', 'template', 'manual', 'lesson'}:
        source = 'accepted'

    # Prefill assignment type
    assignment_type = _normalize_assignment_type(request.args.get('assignment_type')) or 'homework'
    task_type = request.args.get('task_type', type=int, default=None)
    template_id = request.args.get('template_id', type=int, default=None)
    lesson_id = request.args.get('lesson_id', type=int, default=None)

    tasks: list[Tasks] = []
    source_label = ''
    source_meta: dict[str, Any] = {}
    default_recipient_ids: list[int] = []

    if source == 'accepted':
        tasks = get_accepted_tasks(task_type=task_type)
        source_label = 'Принятые задания'
        source_meta = {'task_type': task_type}
    elif source == 'template':
        source_label = 'Шаблон'
        if template_id:
            tpl = TaskTemplate.query.options(db.joinedload(TaskTemplate.template_tasks).joinedload(TemplateTask.task)).get(template_id)
            if tpl:
                tts = sorted((tpl.template_tasks or []), key=lambda x: int(getattr(x, 'order', 0) or 0))
                tasks = [tt.task for tt in tts if getattr(tt, 'task', None)]
                source_meta = {'template_id': tpl.template_id, 'template_name': tpl.name, 'template_type': tpl.template_type}
        else:
            tpl = None
        if not template_id:
            tpl = None
    else:
        source_label = 'Вручную'

    if source == 'lesson':
        source_label = 'Урок'
        if not lesson_id:
            flash('Не указан lesson_id.', 'danger')
            return redirect(url_for('assignments.assignments_list'))
        try:
            lesson = Lesson.query.options(
                joinedload(Lesson.student),
                joinedload(Lesson.homework_tasks).joinedload(LessonTask.task),
            ).get_or_404(int(lesson_id))
        except Exception as e:
            flash(f'Не удалось открыть урок: {e}', 'danger')
            return redirect(url_for('assignments.assignments_list'))

        # Access check: must be able to see this student
        try:
            scope = get_user_scope(current_user)
            if not scope.get('can_see_all'):
                allowed_students = get_students_for_tutor(current_user.id) or []
                allowed_ids = {int(s.student_id) for s in allowed_students if getattr(s, 'student_id', None)}
                if int(getattr(lesson, 'student_id', 0) or 0) not in allowed_ids:
                    return redirect(url_for('lessons.lesson_edit', lesson_id=lesson.lesson_id))
        except Exception:
            pass

        # Pull tasks from lesson by assignment_type
        lt_list = list(getattr(lesson, 'homework_tasks', []) or [])
        picked: list[LessonTask] = []
        for lt in lt_list:
            lt_type = (getattr(lt, 'assignment_type', None) or 'homework')
            if assignment_type == 'homework':
                if lt_type == 'homework' or getattr(lt, 'assignment_type', None) is None:
                    picked.append(lt)
            else:
                if lt_type == assignment_type:
                    picked.append(lt)
        # unique tasks in stable order
        seen = set()
        out_tasks: list[Tasks] = []
        for lt in picked:
            t = getattr(lt, 'task', None)
            tid = getattr(t, 'task_id', None)
            if t and tid and tid not in seen:
                seen.add(tid)
                out_tasks.append(t)
        tasks = out_tasks

        st = getattr(lesson, 'student', None)
        source_meta = {
            'lesson_id': lesson.lesson_id,
            'lesson_topic': lesson.topic,
            'student_id': lesson.student_id,
            'student_name': getattr(st, 'name', None),
        }
        default_recipient_ids = [int(lesson.student_id)]

    # Recipients list (for modal/form)
    recipient_options: list[Student] = []
    try:
        if source == 'lesson' and default_recipient_ids:
            recipient_options = (
                Student.query.filter(Student.student_id.in_(default_recipient_ids))
                .order_by(Student.name.asc(), Student.student_id.asc())
                .all()
            )
        else:
            scope = get_user_scope(current_user)
            if scope.get('can_see_all'):
                recipient_options = (
                    Student.query.filter(Student.is_active.is_(True))
                    .order_by(Student.name.asc(), Student.student_id.asc())
                    .limit(500)
                    .all()
                )
            else:
                tutor_students = get_students_for_tutor(current_user.id) or []
                ids = [int(s.student_id) for s in tutor_students if getattr(s, 'student_id', None)]
                if ids:
                    recipient_options = (
                        Student.query.filter(Student.student_id.in_(ids))
                        .order_by(Student.name.asc(), Student.student_id.asc())
                        .limit(500)
                        .all()
                    )
    except Exception:
        recipient_options = []

    # Templates list for picker
    templates: list[TaskTemplate] = []
    try:
        templates = (
            TaskTemplate.query.order_by(TaskTemplate.name.asc(), TaskTemplate.template_id.asc())
            .limit(300)
            .all()
        )
    except Exception:
        templates = []

    task_ids = []
    try:
        task_ids = [int(t.task_id) for t in (tasks or []) if getattr(t, 'task_id', None)]
    except Exception:
        task_ids = []

    return render_template(
        'assignment_create.html',
        active_page='assignments',
        source=source,
        source_label=source_label,
        source_meta=source_meta,
        assignment_type=assignment_type,
        task_type=task_type,
        template_id=template_id,
        lesson_id=lesson_id,
        templates=templates,
        tasks=tasks,
        task_ids=task_ids,
        recipient_options=recipient_options,
        default_recipient_ids=default_recipient_ids,
    )


@assignments_bp.route('/assignments/<int:assignment_id>/archive', methods=['POST'])
@login_required
@check_access('assignment.create')
def assignment_archive(assignment_id: int):
    """Архивирует работу (soft-disable через is_active=False)."""
    if current_user.is_student() or current_user.is_parent():  # comment
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403  # comment

    assignment = Assignment.query.get_or_404(assignment_id)
    scope = get_user_scope(current_user)
    if not scope.get('can_see_all') and assignment.created_by_id != current_user.id:
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    assignment.is_active = False
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Archive assignment failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Ошибка архивации'}), 500

    return jsonify({'success': True}), 200


@assignments_bp.route('/assignments/<int:assignment_id>/duplicate', methods=['POST'])
@login_required
@check_access('assignment.create')
def assignment_duplicate(assignment_id: int):
    """Быстро создаёт копию работы и раздаёт тем же ученикам (с новым дедлайном)."""
    if current_user.is_student() or current_user.is_parent():  # comment
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403  # comment

    src = Assignment.query.options(
        joinedload(Assignment.tasks),
        joinedload(Assignment.submissions),
    ).get_or_404(assignment_id)

    scope = get_user_scope(current_user)
    if not scope.get('can_see_all') and src.created_by_id != current_user.id:
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    now = _now_naive_msk()
    new_deadline = now + timedelta(days=7)

    max_total = 0
    try:
        for t in (src.tasks or []):
            max_total += int(getattr(t, 'max_score', 0) or 0)
    except Exception:
        max_total = None  # type: ignore[assignment]

    new_assignment = Assignment(
        title=f"{(src.title or 'Работа').strip()} (копия)",
        description=src.description,
        assignment_type=src.assignment_type,
        deadline=new_deadline,
        hard_deadline=bool(src.hard_deadline),
        time_limit_minutes=src.time_limit_minutes,
        created_by_id=current_user.id,
        lesson_id=None,
        rubric_template_id=src.rubric_template_id,
        is_active=True,
    )
    db.session.add(new_assignment)
    db.session.flush()

    # Копируем задачи
    for t in (src.tasks or []):
        db.session.add(AssignmentTask(
            assignment_id=new_assignment.assignment_id,
            task_id=t.task_id,
            order_index=t.order_index,
            max_score=t.max_score,
            requires_manual_grading=bool(t.requires_manual_grading),
        ))

    # Копируем получателей (student_id из Submissions)
    student_ids = []
    for s in (src.submissions or []):
        if getattr(s, 'student_id', None):
            student_ids.append(int(s.student_id))
    # уникализируем, сохраняя порядок
    uniq_ids = []
    seen = set()
    for sid in student_ids:
        if sid not in seen:
            seen.add(sid)
            uniq_ids.append(sid)

    for sid in uniq_ids:
        db.session.add(Submission(
            assignment_id=new_assignment.assignment_id,
            student_id=sid,
            status='ASSIGNED',
            assigned_at=moscow_now(),
            max_score=max_total,
        ))

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Duplicate assignment failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Ошибка при создании копии'}), 500

    return jsonify({'success': True, 'assignment_id': new_assignment.assignment_id}), 201


@assignments_bp.route('/assignments/<int:assignment_id>')
@login_required
@check_access('assignment.view')
def assignment_view(assignment_id):
    """Просмотр конкретной работы"""
    assignment = Assignment.query.options(
        joinedload(Assignment.tasks).joinedload(AssignmentTask.task),
        joinedload(Assignment.submissions).joinedload(Submission.student)
    ).get_or_404(assignment_id)
    
    # Проверка доступа
    scope = get_user_scope(current_user)
    if not scope['can_see_all'] and assignment.created_by_id != current_user.id:
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('assignments.assignments_list'))

    status_filter = (request.args.get('status') or 'all').strip().lower()
    student_query = (request.args.get('student') or '').strip().lower()

    subs_all = list(assignment.submissions or [])

    counts = {
        'total': 0,
        'assigned': 0,
        'in_progress': 0,
        'submitted': 0,
        'late': 0,
        'returned': 0,
        'graded': 0,
        'needs_grading': 0,
    }
    for s in subs_all:
        st = (getattr(s, 'status', '') or '').upper()
        counts['total'] += 1
        if st == 'ASSIGNED':
            counts['assigned'] += 1
        elif st == 'IN_PROGRESS':
            counts['in_progress'] += 1
        elif st == 'RETURNED':
            counts['returned'] += 1
        elif st == 'GRADED':
            counts['graded'] += 1
        elif st == 'LATE':
            counts['late'] += 1
            counts['submitted'] += 1
            counts['needs_grading'] += 1
        elif st == 'SUBMITTED':
            counts['submitted'] += 1
            counts['needs_grading'] += 1

    def _matches_status(s: Submission) -> bool:
        if status_filter in {'', 'all'}:
            return True
        st = (getattr(s, 'status', '') or '').upper()
        if status_filter == 'needs_grading':
            return st in {'SUBMITTED', 'LATE'}
        if status_filter == 'submitted':
            return st in {'SUBMITTED', 'LATE', 'GRADED', 'RETURNED'}
        if status_filter == 'pending':
            return st in {'ASSIGNED', 'IN_PROGRESS'}
        return st.lower() == status_filter

    def _matches_student(s: Submission) -> bool:
        if not student_query:
            return True
        name = ''
        try:
            if s.student and getattr(s.student, 'name', None):
                name = str(s.student.name or '').strip().lower()
        except Exception:
            name = ''
        return student_query in name

    submissions = [s for s in subs_all if _matches_status(s) and _matches_student(s)]

    def _sort_key(s: Submission):
        order = {
            'SUBMITTED': 0,
            'LATE': 0,
            'RETURNED': 1,
            'IN_PROGRESS': 2,
            'ASSIGNED': 3,
            'GRADED': 4,
        }
        st = (getattr(s, 'status', '') or '').upper()
        # сначала то, что проверять; затем по времени сдачи
        ts = getattr(s, 'submitted_at', None) or getattr(s, 'assigned_at', None) or getattr(s, 'created_at', None)
        try:
            ts_val = ts.timestamp() if ts else 0
        except Exception:
            ts_val = 0
        return (order.get(st, 9), -ts_val)

    submissions.sort(key=_sort_key)

    can_manage = bool(has_permission(current_user, 'assignment.create')) and (scope.get('can_see_all') or assignment.created_by_id == current_user.id)

    return render_template(
        'assignment_view.html',
        assignment=assignment,
        submissions=submissions,
        counts=counts,
        status_filter=status_filter,
        student_query=student_query,
        can_manage=can_manage,
    )


# ============================================================================
# API: ВЫПОЛНЕНИЕ РАБОТЫ (STUDENT)
# ============================================================================

@assignments_bp.route('/submissions')
@login_required
def submissions_list():
    """Список назначенных работ для ученика"""
    # Получаем Student по текущему пользователю
    student = get_student_by_user_id(current_user.id)
    if not student:
        flash('Профиль ученика не найден', 'warning')
        return redirect(url_for('auth.user_profile'))
    
    # Получаем все назначенные работы
    submissions = Submission.query.filter_by(
        student_id=student.student_id
    ).options(
        joinedload(Submission.assignment).joinedload(Assignment.tasks),
        joinedload(Submission.answers)
    ).order_by(Submission.assigned_at.desc()).all()
    
    # Если работ по новой системе нет — показываем fallback: последние уроки с практикой
    lesson_workspaces = []
    try:
        lessons = Lesson.query.filter_by(student_id=student.student_id).options(
            joinedload(Lesson.homework_tasks).joinedload(LessonTask.task)
        ).order_by(Lesson.lesson_date.desc()).limit(10).all()

        for l in lessons:
            # Берём все задачи урока (все типы), но показываем кратко
            all_tasks = []
            for t in get_sorted_assignments(l, 'homework'):
                all_tasks.append(t)
            for t in get_sorted_assignments(l, 'classwork'):
                all_tasks.append(t)
            for t in get_sorted_assignments(l, 'exam'):
                all_tasks.append(t)

            if not all_tasks:
                continue

            total = len(all_tasks)
            done = sum(1 for t in all_tasks if (t.status or '').lower() in ['submitted', 'graded', 'returned'])
            has_draft = any((t.student_submission or '').strip() and (t.status or '').lower() not in ['submitted', 'graded', 'returned'] for t in all_tasks)

            lesson_workspaces.append({
                'lesson': l,
                'total': total,
                'done': done,
                'has_draft': has_draft,
            })
    except Exception as e:
        logger.warning(f"Failed to build lesson_workspaces for student {student.student_id}: {e}")
        lesson_workspaces = []

    return render_template('submissions_list.html', submissions=submissions, student=student, lesson_workspaces=lesson_workspaces)


@assignments_bp.route('/submissions/<int:submission_id>')
@login_required
def submission_view(submission_id):
    """Просмотр и выполнение работы"""
    submission = Submission.query.options(
        joinedload(Submission.assignment).joinedload(Assignment.tasks).joinedload(AssignmentTask.task),
        joinedload(Submission.answers),
        joinedload(Submission.comments).joinedload(SubmissionComment.author)
    ).get_or_404(submission_id)
    
    # Проверка доступа
    student = get_student_by_user_id(current_user.id)
    if not student or submission.student_id != student.student_id:
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('assignments.submissions_list'))
    
    assignment = submission.assignment
    
    # Проверка дедлайна
    now = moscow_now()
    is_deadline_passed = now > assignment.deadline
    can_submit = not (is_deadline_passed and assignment.hard_deadline)
    
    # Подготовка данных для отображения
    tasks_data = []
    for assignment_task in sorted(assignment.tasks, key=lambda t: t.order_index):
        answer = next((a for a in submission.answers if a.assignment_task_id == assignment_task.assignment_task_id), None)
        tasks_data.append({
            'assignment_task': assignment_task,
            'task': assignment_task.task,
            'answer': answer
        })
    
    return render_template('submission_view.html',
                         submission=submission,
                         assignment=assignment,
                         tasks_data=tasks_data,
                         is_deadline_passed=is_deadline_passed,
                         can_submit=can_submit)


@assignments_bp.route('/submissions/<int:submission_id>/start', methods=['POST'])
@login_required
def submission_start(submission_id):
    """Старт выполнения работы"""
    submission = Submission.query.get_or_404(submission_id)
    
    # Проверка доступа
    student = get_student_by_user_id(current_user.id)
    if not student or submission.student_id != student.student_id:
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    
    # Проверка статуса
    if submission.status != 'ASSIGNED':
        return jsonify({'success': False, 'error': 'Работа уже начата или сдана'}), 400
    
    # Проверка дедлайна
    now = moscow_now()
    if now > submission.assignment.deadline and submission.assignment.hard_deadline:
        return jsonify({'success': False, 'error': 'Дедлайн истек'}), 400
    
    # Устанавливаем статус и время начала
    submission.status = 'IN_PROGRESS'
    submission.started_at = now
    db.session.commit()
    
    return jsonify({'success': True, 'started_at': submission.started_at.isoformat()}), 200


@assignments_bp.route('/submissions/<int:submission_id>/autosave', methods=['PUT'])
@login_required
def submission_autosave(submission_id):
    """
    Автосохранение ответов
    Body: {
        "answers": [
            {"assignment_task_id": 1, "value": "ответ"},
            {"assignment_task_id": 2, "value": "другой ответ"}
        ]
    }
    """
    submission = Submission.query.get_or_404(submission_id)
    
    # Проверка доступа
    student = get_student_by_user_id(current_user.id)
    if not student or submission.student_id != student.student_id:
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    
    # Проверка статуса
    if submission.status not in ['IN_PROGRESS', 'ASSIGNED', 'RETURNED']:
        return jsonify({'success': False, 'error': 'Нельзя сохранять ответы для этой работы'}), 400
    
    try:
        data = request.get_json()
        answers_data = data.get('answers', [])
        
        for answer_data in answers_data:
            assignment_task_id = answer_data.get('assignment_task_id')
            value = answer_data.get('value', '')
            
            if not assignment_task_id:
                continue
            
            # Проверяем, что задача принадлежит этой работе
            assignment_task = AssignmentTask.query.filter_by(
                assignment_task_id=assignment_task_id,
                assignment_id=submission.assignment_id
            ).first()
            
            if not assignment_task:
                continue
            
            # Ищем существующий ответ или создаем новый
            answer = Answer.query.filter_by(
                submission_id=submission_id,
                assignment_task_id=assignment_task_id
            ).first()
            
            if not answer:
                answer = Answer(
                    submission_id=submission_id,
                    assignment_task_id=assignment_task_id,
                    max_score=assignment_task.max_score
                )
                db.session.add(answer)
            
            answer.value = value
            answer.updated_at = moscow_now()
        
        # Обновляем статус, если еще не начата или возвращена на доработку
        if submission.status in ['ASSIGNED', 'RETURNED']:
            submission.status = 'IN_PROGRESS'
            if not submission.started_at:
                submission.started_at = moscow_now()
        
        db.session.commit()
        
        return jsonify({'success': True}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in submission_autosave: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@assignments_bp.route('/submissions/<int:submission_id>/submit', methods=['POST'])
@login_required
def submission_submit(submission_id):
    """Финальная сдача работы"""
    submission = Submission.query.options(
        joinedload(Submission.assignment).joinedload(Assignment.tasks),
        joinedload(Submission.answers)
    ).get_or_404(submission_id)
    
    # Проверка доступа
    student = get_student_by_user_id(current_user.id)
    if not student or submission.student_id != student.student_id:
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    
    # Проверка статуса
    if submission.status not in ['IN_PROGRESS', 'ASSIGNED']:
        return jsonify({'success': False, 'error': 'Работа уже сдана'}), 400
    
    assignment = submission.assignment
    now = moscow_now()
    
    # Проверка дедлайна
    is_late = now > assignment.deadline
    if is_late and assignment.hard_deadline:
        return jsonify({'success': False, 'error': 'Дедлайн истек, сдача невозможна'}), 403
    
    # Устанавливаем статус
    submission.status = 'SUBMITTED'
    submission.submitted_at = now
    submission.is_late = is_late
    
    # Автоматическая проверка
    all_auto_graded = True
    total_score = 0
    max_score = 0
    
    for assignment_task in assignment.tasks:
        max_score += assignment_task.max_score
        
        answer = next((a for a in submission.answers if a.assignment_task_id == assignment_task.assignment_task_id), None)
        
        if not answer:
            if not assignment_task.requires_manual_grading:
                # Нет ответа на задачу с авто-проверкой - 0 баллов
                answer = Answer(
                    submission_id=submission_id,
                    assignment_task_id=assignment_task.assignment_task_id,
                    max_score=assignment_task.max_score,
                    score=0,
                    is_correct=False
                )
                db.session.add(answer)
                total_score += 0
            else:
                all_auto_graded = False
            continue
        
        # Авто-проверка, если не требует ручной проверки
        if not assignment_task.requires_manual_grading:
            is_correct, score = auto_grade_answer(answer, assignment_task)
            if is_correct is not None:
                answer.is_correct = is_correct
                answer.score = score
                total_score += score
            else:
                all_auto_graded = False
        else:
            all_auto_graded = False
    
    submission.total_score = total_score
    submission.max_score = max_score
    submission.percentage = (total_score / max_score * 100) if max_score > 0 else 0
    
    # Если все задачи проверены автоматически, сразу ставим GRADED
    if all_auto_graded:
        submission.status = 'GRADED'
        submission.graded_at = now
        # Авто-добавление в журнал
        _upsert_gradebook_from_submission(submission, actor_user_id=current_user.id)

    # Фиксируем попытку сдачи (для истории пересдач)
    try:
        _record_submission_attempt(submission)
    except Exception as e:
        logger.warning(f"Could not record SubmissionAttempt for {submission.submission_id}: {e}")
    
    db.session.commit()
    
    audit_logger.log(
        action='submit_assignment',
        entity='Submission',
        entity_id=submission_id,
        status='success',
        metadata={
            'assignment_id': assignment.assignment_id,
            'is_late': is_late,
            'auto_graded': all_auto_graded
        }
    )
    
    return jsonify({
        'success': True,
        'status': submission.status,
        'score': total_score,
        'max_score': max_score,
        'percentage': submission.percentage
    }), 200


# ============================================================================
# ПРОВЕРКА РАБОТ (TEACHER)
# ============================================================================

@assignments_bp.route('/submissions/<int:submission_id>/grade')
@login_required
@check_access('assignment.grade')
def submission_grade_view(submission_id):
    """Страница проверки работы учителем"""
    if current_user.is_student() or current_user.is_parent():  # comment
        return redirect(url_for('assignments.submission_view', submission_id=submission_id))  # comment
    submission = Submission.query.options(
        joinedload(Submission.assignment).joinedload(Assignment.tasks).joinedload(AssignmentTask.task),
        joinedload(Submission.answers),
        joinedload(Submission.student),
        joinedload(Submission.comments).joinedload(SubmissionComment.author)
    ).get_or_404(submission_id)
    
    assignment = submission.assignment
    
    # Проверка доступа
    scope = get_user_scope(current_user)
    if not scope['can_see_all'] and assignment.created_by_id != current_user.id:
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('assignments.assignments_list'))
    
    # Подготовка данных
    tasks_data = []
    for assignment_task in sorted(assignment.tasks, key=lambda t: t.order_index):
        answer = next((a for a in submission.answers if a.assignment_task_id == assignment_task.assignment_task_id), None)
        tasks_data.append({
            'assignment_task': assignment_task,
            'task': assignment_task.task,
            'answer': answer
        })

    rubric_template = None
    rubric_templates = []
    try:
        rid = submission.rubric_template_id or assignment.rubric_template_id
        if rid:
            rubric_template = RubricTemplate.query.filter_by(rubric_id=rid, is_active=True).first()
    except Exception:
        rubric_template = None

    try:
        base = RubricTemplate.query.filter(RubricTemplate.is_active.is_(True))
        if not _can_manage_all_rubrics():
            base = base.filter(RubricTemplate.owner_user_id == current_user.id)
        at = (assignment.assignment_type or '').strip().lower()
        if at:
            base = base.filter((db.func.lower(RubricTemplate.assignment_type) == at) | (RubricTemplate.assignment_type.is_(None)))
        rubric_templates = base.order_by(RubricTemplate.updated_at.desc(), RubricTemplate.created_at.desc(), RubricTemplate.rubric_id.desc()).limit(200).all()
    except Exception:
        rubric_templates = []

    return render_template('submission_grade.html',
                         submission=submission,
                         assignment=assignment,
                         tasks_data=tasks_data,
                         rubric_template=rubric_template,
                         rubric_templates=rubric_templates)


@assignments_bp.route('/submissions/<int:submission_id>/grade', methods=['POST'])
@login_required
@check_access('assignment.grade')
def submission_grade_save(submission_id):
    """
    Сохранение оценки работы
    Body: {
        "scores": [
            {"assignment_task_id": 1, "score": 5, "comment": "Хорошо"},
            ...
        ],
        "teacher_feedback": "Общий комментарий",
        "status": "GRADED" или "RETURNED"
    }
    """
    if current_user.is_student() or current_user.is_parent():  # comment
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403  # comment
    submission = Submission.query.options(
        joinedload(Submission.assignment).joinedload(Assignment.tasks),
        joinedload(Submission.answers)
    ).get_or_404(submission_id)
    
    assignment = submission.assignment
    
    # Проверка доступа
    scope = get_user_scope(current_user)
    if not scope['can_see_all'] and assignment.created_by_id != current_user.id:
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    
    # Проверка статуса
    if submission.status != 'SUBMITTED':
        return jsonify({'success': False, 'error': 'Работа не сдана или уже проверена'}), 400
    
    try:
        data = request.get_json()
        scores_data = data.get('scores', [])
        teacher_feedback = data.get('teacher_feedback', '').strip()
        status = data.get('status', 'GRADED')  # GRADED или RETURNED
        rubric_template_id = data.get('rubric_template_id', None)
        rubric_scores = data.get('rubric_scores', None)
        
        if status not in ['GRADED', 'RETURNED']:
            status = 'GRADED'
        
        total_score = 0
        max_score = 0
        
        # Обновляем оценки
        for score_data in scores_data:
            assignment_task_id = score_data.get('assignment_task_id')
            score = score_data.get('score', 0)
            comment = score_data.get('comment', '').strip()
            
            if not assignment_task_id:
                continue
            
            assignment_task = AssignmentTask.query.filter_by(
                assignment_task_id=assignment_task_id,
                assignment_id=assignment.assignment_id
            ).first()
            
            if not assignment_task:
                continue
            
            max_score += assignment_task.max_score
            
            # Находим или создаем ответ
            answer = Answer.query.filter_by(
                submission_id=submission_id,
                assignment_task_id=assignment_task_id
            ).first()
            
            if not answer:
                answer = Answer(
                    submission_id=submission_id,
                    assignment_task_id=assignment_task_id,
                    max_score=assignment_task.max_score
                )
                db.session.add(answer)
            
            answer.score = min(max(0, score), assignment_task.max_score)  # Ограничиваем максимумом
            answer.teacher_comment = comment
            total_score += answer.score
        
        # Обновляем общую оценку
        submission.total_score = total_score
        submission.max_score = max_score
        submission.percentage = (total_score / max_score * 100) if max_score > 0 else 0
        submission.teacher_feedback = teacher_feedback

        # Рубрика/критерии (чек-лист)
        try:
            selected_rubric = None
            # 1) берём выбранную в UI (если есть)
            if rubric_template_id is not None and str(rubric_template_id).strip() != '':
                rid = int(rubric_template_id)
                q = RubricTemplate.query.filter_by(rubric_id=rid, is_active=True)
                if not _can_manage_all_rubrics():
                    q = q.filter(RubricTemplate.owner_user_id == current_user.id)
                selected_rubric = q.first()
            # 2) иначе — текущая закреплённая на работе
            if not selected_rubric and assignment.rubric_template_id:
                selected_rubric = RubricTemplate.query.filter_by(rubric_id=assignment.rubric_template_id, is_active=True).first()

            if selected_rubric:
                # закрепляем на Assignment (чтобы все проверки были консистентны)
                if not assignment.rubric_template_id:
                    assignment.rubric_template_id = selected_rubric.rubric_id
                submission.rubric_template_id = selected_rubric.rubric_id

                cleaned = {}
                if isinstance(rubric_scores, dict):
                    items = selected_rubric.items if isinstance(selected_rubric.items, list) else []
                    max_map = {}
                    for it in items:
                        if isinstance(it, dict) and it.get('key'):
                            k = str(it.get('key'))
                            try:
                                ms = it.get('max_score', None)
                                ms = int(ms) if ms is not None and str(ms) != '' else None
                            except Exception:
                                ms = None
                            max_map[k] = ms

                    for k, v in list(rubric_scores.items())[:120]:
                        key = str(k).strip()
                        if not key or not isinstance(v, dict):
                            continue
                        sc = v.get('score', None)
                        try:
                            sc = int(sc) if sc is not None and str(sc) != '' else None
                        except Exception:
                            sc = None
                        if sc is not None and sc < 0:
                            sc = 0
                        mx = max_map.get(key)
                        if mx is not None and sc is not None and sc > mx:
                            sc = mx
                        comment = str((v.get('comment') or '')).strip() or None
                        cleaned[key] = {'score': sc, 'comment': comment}

                submission.rubric_scores = cleaned if cleaned else None
        except Exception as e:
            logger.warning(f"Failed to save rubric data for submission {submission_id}: {e}")

        submission.status = status
        submission.graded_at = moscow_now()

        # Авто-добавление/обновление записи журнала при проверке
        if status == 'GRADED':
            _upsert_gradebook_from_submission(submission, actor_user_id=current_user.id)
        # История попыток: фиксируем результат проверки для текущей попытки
        try:
            _record_submission_attempt(submission)
        except Exception as e:
            logger.warning(f"Could not record SubmissionAttempt (grade) for {submission.submission_id}: {e}")

        # Уведомление ученику/родителю
        try:
            student = Student.query.get(submission.student_id)
            if student:
                if status == 'GRADED':
                    notify_student_and_parents(
                        student,
                        kind='assignment_graded',
                        title='Работа проверена',
                        body=(teacher_feedback or '').strip() or None,
                        link_url=url_for('assignments.submission_view', submission_id=submission.submission_id),
                        meta={'submission_id': submission.submission_id, 'assignment_id': assignment.assignment_id, 'status': status},
                    )
                else:
                    notify_student_and_parents(
                        student,
                        kind='assignment_returned',
                        title='Работа возвращена на доработку',
                        body=(teacher_feedback or '').strip() or None,
                        link_url=url_for('assignments.submission_view', submission_id=submission.submission_id),
                        meta={'submission_id': submission.submission_id, 'assignment_id': assignment.assignment_id, 'status': status},
                    )
        except Exception as e:
            logger.warning(f"Failed to notify student about submission grade: {e}")
        
        db.session.commit()
        
        audit_logger.log(
            action='grade_submission',
            entity='Submission',
            entity_id=submission_id,
            status='success',
            metadata={
                'assignment_id': assignment.assignment_id,
                'total_score': total_score,
                'max_score': max_score,
                'status': status
            }
        )
        
        # TODO: Отправить уведомление ученику и родителю
        
        return jsonify({
            'success': True,
            'total_score': total_score,
            'max_score': max_score,
            'percentage': submission.percentage
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in submission_grade_save: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@assignments_bp.route('/submissions/<int:submission_id>/comments', methods=['POST'])
@login_required
def submission_comment_create(submission_id):
    """Добавление комментария к сдаче"""
    submission = Submission.query.get_or_404(submission_id)
    
    # Проверка доступа
    scope = get_user_scope(current_user)
    student = get_student_by_user_id(current_user.id)
    
    is_author = student and submission.student_id == student.student_id
    is_teacher = scope['can_see_all'] or submission.assignment.created_by_id == current_user.id
    
    if not (is_author or is_teacher):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
        
    try:
        data = request.get_json()
        text = data.get('text', '').strip()
        
        if not text:
            return jsonify({'success': False, 'error': 'Текст комментария обязателен'}), 400
            
        comment = SubmissionComment(
            submission_id=submission.submission_id,
            author_id=current_user.id,
            text=text,
            created_at=moscow_now()
        )
        db.session.add(comment)
        db.session.commit()
        
        # Получаем данные автора для ответа
        author_name = current_user.username
        if current_user.profile:
            author_name = f"{current_user.profile.first_name or ''} {current_user.profile.last_name or ''}".strip() or current_user.username
            
        return jsonify({
            'success': True,
            'comment': {
                'id': comment.comment_id,
                'text': comment.text,
                'created_at': comment.created_at.isoformat(),
                'author': {
                    'id': current_user.id,
                    'name': author_name,
                    'avatar_url': current_user.avatar_url
                }
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating comment: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
