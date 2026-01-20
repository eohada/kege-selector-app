"""
Маршруты для системы заданий и сдачи работ
"""
import logging
from datetime import datetime, timedelta
from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import and_, or_, func
from sqlalchemy.orm import joinedload

from app.assignments import assignments_bp
from app.models import (
    db, Assignment, AssignmentTask, Submission, Answer,
    Student, User, Tasks, Lesson, Enrollment, GradebookEntry, SubmissionAttempt
)
from app.students.utils import get_sorted_assignments
from core.db_models import SubmissionComment
from app.auth.rbac_utils import check_access, get_user_scope, has_permission
from core.db_models import moscow_now
from core.audit_logger import audit_logger
from app.notifications.service import notify_student_and_parents

logger = logging.getLogger(__name__)

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

    candidates = []
    if user.email and str(user.email).strip():
        candidates.append(str(user.email).strip())
    # В некоторых окружениях логин хранится в username, а email может быть пустым
    if user.username and str(user.username).strip():
        candidates.append(str(user.username).strip())

    # Удаляем дубли, нормализуем пробелы
    seen = set()
    normalized = []
    for c in candidates:
        key = c.strip().lower()
        if key and key not in seen:
            seen.add(key)
            normalized.append(c.strip())

    if not normalized:
        return None

    # Пытаемся найти Student по email (case-insensitive)
    for c in normalized:
        st = Student.query.filter(func.lower(Student.email) == c.lower()).first()
        if st:
            return st

    return None


def get_students_for_tutor(tutor_user_id):
    """Получить список Student для тьютора"""
    enrollments = Enrollment.query.filter_by(
        tutor_id=tutor_user_id,
        status='active'
    ).all()
    
    student_users = User.query.filter(
        User.id.in_([e.student_id for e in enrollments])
    ).all()
    
    student_emails = [u.email for u in student_users if u.email]
    if not student_emails:
        return []
    
    return Student.query.filter(Student.email.in_(student_emails)).all()


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
    """Список всех работ для учителя"""
    scope = get_user_scope(current_user)
    
    query = Assignment.query.filter_by(is_active=True).order_by(Assignment.created_at.desc())
    
    # Фильтрация по доступу
    if not scope['can_see_all']:
        # Только работы, созданные текущим пользователем
        query = query.filter_by(created_by_id=current_user.id)
    
    assignments = query.all()
    
    # Добавляем статистику
    assignments_data = []
    for assignment in assignments:
        submissions = Submission.query.filter_by(assignment_id=assignment.assignment_id).all()
        assignments_data.append({
            'assignment': assignment,
            'total_students': len(submissions),
            'submitted': len([s for s in submissions if s.status in ['SUBMITTED', 'GRADED', 'RETURNED']]),
            'graded': len([s for s in submissions if s.status == 'GRADED'])
        })
    
    return render_template('assignments_list.html', assignments_data=assignments_data)


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
    
    submissions = Submission.query.filter_by(assignment_id=assignment_id).all()
    
    return render_template('assignment_view.html', 
                         assignment=assignment, 
                         submissions=submissions)


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
    
    return render_template('submission_grade.html',
                         submission=submission,
                         assignment=assignment,
                         tasks_data=tasks_data)


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
