"""
Маршруты для системы заданий и сдачи работ
"""
import logging
from datetime import datetime, timedelta, timezone
from flask import render_template, request, jsonify, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from sqlalchemy import and_, or_, func, case
from sqlalchemy.orm import joinedload

from app.assignments import assignments_bp
from app.limiter import limiter
from app.models import (
    db, Assignment, AssignmentTask, Submission, Answer,
    Student, User, Tasks, Lesson, LessonTask, Enrollment, GradebookEntry, SubmissionAttempt, RubricTemplate,
    TaskTemplate, TemplateTask, CourseTaskTemplate, GroupStudent, AnalyticsEvent
)
from app.students.utils import get_sorted_assignments
from core.db_models import SubmissionComment, MOSCOW_TZ
from app.auth.rbac_utils import check_access, get_user_scope, has_permission
from core.db_models import moscow_now
from core.audit_logger import audit_logger
from app.notifications.service import notify_student_and_parents, notify_user, build_task_number_summary, build_task_number_counts
from core.selector_logic import get_accepted_tasks, get_skipped_tasks, get_unique_tasks, get_task_ids_in_assignments_for_students, reset_history, reset_skipped
from app.utils.course_tasks import get_task_numbers
import requests
from flask import Response, stream_with_context, abort, send_from_directory
from werkzeug.utils import secure_filename
import json
import subprocess
import sys
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

# Редактор кода: песочница для запуска Python
_PYTHON_RUNNER = r"""
import sys, io, os

_cwd = os.getcwd()
_real_open = open

def _safe_open(path, mode='r', encoding=None, **kw):
    if any(c in mode for c in 'wax+'):
        raise PermissionError('Запись файлов запрещена в песочнице')
    abs_path = os.path.abspath(path)
    if not abs_path.startswith(_cwd + os.sep) and abs_path != _cwd:
        raise PermissionError('Доступ к файлам за пределами рабочей директории запрещён')
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"Файл не найден: {path}")
    if 'b' in mode:
        return _real_open(abs_path, mode, **kw)
    return _real_open(abs_path, mode, encoding=encoding or 'utf-8', **kw)

import itertools, math, ipaddress

_ALLOWED_MODULES = {
    'itertools': itertools, 'math': math, 'ipaddress': ipaddress,
}
_real_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name in _ALLOWED_MODULES:
        mod = _ALLOWED_MODULES[name]
        if fromlist:
            return mod
        return mod
    raise ImportError(f"Модуль '{name}' недоступен в песочнице. Доступны: itertools, math, ipaddress")

code = sys.stdin.read()
out = io.StringIO()
err = io.StringIO()
sys.stdout = out
sys.stderr = err
try:
    safe_builtins = {'print': print, 'len': len, 'range': range, 'list': list, 'dict': dict, 'str': str, 'int': int, 'float': float,
                     'sum': sum, 'min': min, 'max': max, 'abs': abs, 'sorted': sorted, 'map': map, 'filter': filter, 'zip': zip,
                     'enumerate': enumerate, 'tuple': tuple, 'set': set, 'bool': bool, 'True': True, 'False': False, 'None': None,
                     'round': round, 'repr': repr, 'any': any, 'all': all,
                     'open': _safe_open, 'input': input, '__import__': _safe_import,
                     'type': type, 'isinstance': isinstance, 'chr': chr, 'ord': ord,
                     'hex': hex, 'bin': bin, 'pow': pow, 'reversed': reversed,
                     'bytes': bytes, 'format': format, 'hash': hash,
                     'Exception': Exception, 'ValueError': ValueError, 'TypeError': TypeError,
                     'KeyError': KeyError, 'IndexError': IndexError, 'StopIteration': StopIteration,
                     'FileNotFoundError': FileNotFoundError, 'ImportError': ImportError,
                     'ZeroDivisionError': ZeroDivisionError, 'RuntimeError': RuntimeError,
                     'AttributeError': AttributeError, 'OverflowError': OverflowError}
    safe = {'__builtins__': safe_builtins, 'itertools': itertools, 'math': math, 'ipaddress': ipaddress, 'os': None}
    exec(code, safe)
except Exception as e:
    err.write(str(e))
sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__
print(out.getvalue())
print(err.getvalue(), file=sys.__stderr__)
"""

def _ensure_aware_datetime(dt):
    """Конвертирует naive datetime в aware (Moscow timezone)"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=MOSCOW_TZ)
    return dt


def _started_at_to_utc(dt):
    """
    Приводит started_at к UTC для сравнения таймера.
    Naive считаем UTC (типично при хранении в PostgreSQL/Docker в UTC),
    иначе блокировка срабатывает сразу после старта.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def _resolve_answer_time_spent_sec(submission, answered_at, previous_answered_at=None):
    """
    Пытается оценить время решения ответа в секундах.
    Базовый ориентир: от submission.started_at до момента ответа.
    """
    if not answered_at:
        return None
    try:
        if previous_answered_at is not None:
            started_utc = _started_at_to_utc(previous_answered_at)
        else:
            if not submission or not getattr(submission, 'started_at', None):
                return None
            started_utc = _started_at_to_utc(submission.started_at)
        answered_utc = _started_at_to_utc(answered_at)
        if not started_utc or not answered_utc:
            return None
        delta = int((answered_utc - started_utc).total_seconds())
        return max(0, delta)
    except Exception:
        return None


def _submission_display_status(submission, assignment, now):
    """
    Возвращает отображаемый статус для списков: "Просрочено по таймеру",
    "Просрочено по дедлайну" или None (показывать обычный submission.status).
    """
    if submission.status not in ('ASSIGNED', 'IN_PROGRESS', 'RETURNED'):
        return None
    if getattr(assignment, 'time_limit_strict', False) and getattr(assignment, 'time_limit_minutes', None) and getattr(submission, 'started_at', None):
        started_utc = _started_at_to_utc(submission.started_at)
        now_utc = now.astimezone(timezone.utc)
        limit_end_utc = started_utc + timedelta(minutes=assignment.time_limit_minutes)
        if now_utc > limit_end_utc:
            return 'Просрочено по таймеру'
    deadline = _ensure_aware_datetime(assignment.deadline) if getattr(assignment, 'deadline', None) else None
    if deadline and now > deadline:
        return 'Просрочено по дедлайну'
    return None

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

    if status_filter != 'submitted':
        flash('Массовые действия доступны только в статусе «Сдано».', 'warning')
        return redirect(url_for('lessons.review_queue', status=status_filter, source=source, assignment_type=assignment_type, student=student_query))

    assignment = Assignment.query.get_or_404(assignment_id)

    scope = get_user_scope(current_user)
    if not scope.get('can_see_all') and assignment.created_by_id != current_user.id:
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('assignments.assignments_list'))

    q = Submission.query.options(joinedload(Submission.student)).filter(Submission.assignment_id == assignment.assignment_id)
    q = q.filter(Submission.status.in_(['SUBMITTED', 'LATE', 'NEEDS_MANUAL_REVIEW']))

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
            if sub.total_score is None or sub.max_score is None:
                skipped += 1
                continue
            sub.status = 'GRADED'
            sub.graded_at = moscow_now()
        try:
            _record_submission_attempt(sub)
        except Exception:
            pass

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

    if (submission.status or '').upper() not in {'SUBMITTED', 'LATE', 'NEEDS_MANUAL_REVIEW'}:
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
        from app.telegram.notifications import on_submission_status_changed
        on_submission_status_changed(submission)
    except Exception:
        logger.warning('on_submission_status_changed after quick return failed', exc_info=True)

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



def get_student_by_user_id(user_id):
    """Получить Student по User.id"""
    user = User.query.get(user_id)
    if not user:
        return None

    st = Student.query.filter_by(user_id=user_id).first()
    if st:
        return st

    username = (str(user.username).strip() if user.username else '')
    if username:
        try:
            st = Student.query.filter(Student.platform_id == username).first()
            if st:
                return st
        except Exception:
            pass
    try:
        st = Student.query.filter(Student.student_id == int(user_id)).first()
        if st:
            return st
    except Exception:
        pass

    # Fallback через RBAC scope: для некоторых аккаунтов student_ids в scope
    # содержат User.id, который нужно домапить в Student.
    try:
        scope = get_user_scope(user)
        scope_user_ids = scope.get('student_ids') or []
        if user.id not in scope_user_ids and user.is_student():
            scope_user_ids = [user.id] + list(scope_user_ids)

        if scope_user_ids:
            st = Student.query.filter(Student.user_id.in_(scope_user_ids)).first()
            if st:
                return st

            usernames = []
            users = User.query.filter(User.id.in_(scope_user_ids)).all()
            for u in users:
                uname = (u.username or '').strip()
                if uname:
                    usernames.append(uname)
            if usernames:
                st = Student.query.filter(Student.platform_id.in_(usernames)).first()
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

    by_user_id = Student.query.filter(Student.user_id.in_(user_ids)).all()
    if by_user_id:
        return by_user_id
    usernames = []
    for u in User.query.filter(User.id.in_(user_ids)).all() or []:
        if u and (u.username or '').strip():
            usernames.append((u.username or '').strip())
    if usernames:
        return Student.query.filter(Student.platform_id.in_(usernames)).all()
    try:
        return Student.query.filter(Student.student_id.in_([int(x) for x in user_ids])).all()
    except Exception:
        return []


def _effective_correct_answer(assignment_task):
    """Эталонный ответ для сравнения: переопределение в работе или ответ из задания."""
    override = (assignment_task.answer_override or '').strip()
    if override:
        return override
    task = assignment_task.task
    return (task.answer or '').strip()


def _get_task_template(task):
    """Возвращает CourseTaskTemplate для задания по course_id и task_number, или None."""
    if not task or task.course_id is None:
        return None
    return CourseTaskTemplate.query.filter_by(
        course_id=task.course_id,
        task_number=task.task_number
    ).first()


def _requires_manual_from_template(task, has_answer, explicit_override=None):
    """
    Определяет, требуется ли ручная проверка, на основе CourseTaskTemplate.
    Если шаблон не найден — по умолчанию не требуется (для обратной совместимости).
    """
    template = _get_task_template(task)
    if template is None:
        return bool(explicit_override) if explicit_override is not None else False
    return (template.requires_manual_review and not has_answer) or bool(explicit_override)


def _assignment_has_manual_review_tasks(assignment):
    """
    Проверяет, есть ли в работе хотя бы одно задание с requires_manual_review=True
    в CourseTaskTemplate. Используется для установки статуса NEEDS_MANUAL_REVIEW
    вместо GRADED после авто-проверки.
    """
    for at in (assignment.tasks or []):
        task = getattr(at, 'task', None)
        if not task:
            continue
        template = _get_task_template(task)
        if template and template.requires_manual_review:
            return True
    return False


def auto_grade_answer(answer, assignment_task):
    """
    Автоматическая проверка ответа.
    Возвращает (is_correct, score). Работает для любого типа экзамена (ЕГЭ, ОГЭ и т.д.)
    на основе CourseTaskTemplate: max_primary_score для балла, requires_manual_review не влияет
    на саму авто-проверку — если задан эталонный ответ, авто-проверка выполняется.
    """
    task = assignment_task.task
    student_answer = (answer.value or '').strip()
    correct_answer = _effective_correct_answer(assignment_task)

    template = _get_task_template(task)
    if template is None:
        return None, None

    if not correct_answer:
        return None, None

    score_value = template.max_primary_score if template.max_primary_score is not None else assignment_task.max_score
    if student_answer.lower() == correct_answer.lower():
        return True, score_value
    return False, 0


def _get_triplet_task_ids(task: Tasks | None):
    """
    Для заданий 19–21 с task_group_id возвращает [task_id_19, task_id_20, task_id_21] по порядку
    или None, если полной тройки в БД нет.
    """
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


def _expand_task_ids_for_triplets(task_ids: list[int]) -> list[int]:
    """
    Расширяет список task_id: тройка 19–21 по одному task_group_id добавляется целиком (19, 20, 21).
    Повторяющиеся id в одной группе не дублируются.
    """
    out: list[int] = []
    seen: set[int] = set()
    seen_groups: set[str] = set()
    for tid in task_ids:
        try:
            tid_int = int(tid)
        except (TypeError, ValueError):
            continue
        task = Tasks.query.get(tid_int)
        if not task:
            continue
        trip = _get_triplet_task_ids(task)
        if trip:
            gid = (str(task.task_group_id or '')).strip()
            if not gid:
                if tid_int not in seen:
                    seen.add(tid_int)
                    out.append(tid_int)
                continue
            if gid in seen_groups:
                continue
            seen_groups.add(gid)
            for x in trip:
                if x not in seen:
                    seen.add(x)
                    out.append(x)
        else:
            if tid_int not in seen:
                seen.add(tid_int)
                out.append(tid_int)
    return out


def _expand_tasks_list_for_triplets(tasks: list) -> list:
    """Для мастера создания работы: расширяет список объектов Tasks по тройкам 19–21."""
    out: list = []
    seen: set[int] = set()
    seen_groups: set[str] = set()
    for t in tasks or []:
        if not t:
            continue
        tid = getattr(t, 'task_id', None)
        if tid is None:
            continue
        trip = _get_triplet_task_ids(t)
        if trip:
            gid = (str(t.task_group_id or '')).strip()
            if not gid:
                if tid not in seen:
                    seen.add(tid)
                    out.append(t)
                continue
            if gid in seen_groups:
                continue
            seen_groups.add(gid)
            for sub_id in trip:
                if sub_id in seen:
                    continue
                sub = Tasks.query.get(sub_id)
                if sub:
                    seen.add(sub_id)
                    out.append(sub)
        else:
            if tid not in seen:
                seen.add(tid)
                out.append(t)
    return out


def _expand_tasks_data_for_triplets(tasks_data: list) -> list:
    """
    Для distribute / assignment_update: дублирует строки задач по полной тройке 19–21,
    выставляет order и max_score по шаблону курса для каждой позиции.

    Если клиент уже передал все три task_id тройки (редактирование работы, отдельные
    answer_override на 19/20/21), строки не сливаются — иначе копировался бы один
    answer_override с первой строки на все три.
    """
    prepared: list[tuple[int, Tasks, dict]] = []
    for row in tasks_data or []:
        if not isinstance(row, dict):
            continue
        task_id = row.get('task_id')
        if not task_id:
            continue
        try:
            tid_int = int(task_id)
        except (TypeError, ValueError):
            continue
        task = Tasks.query.get(tid_int)
        if not task:
            continue
        prepared.append((tid_int, task, dict(row)))

    gid_to_trip_ids: dict[str, list[int]] = {}
    gid_present: dict[str, set[int]] = {}
    for tid_int, task, _row in prepared:
        trip = _get_triplet_task_ids(task)
        if not trip:
            continue
        gid = (str(task.task_group_id or '')).strip()
        if not gid:
            continue
        if gid not in gid_to_trip_ids:
            gid_to_trip_ids[gid] = trip
        gid_present.setdefault(gid, set()).add(tid_int)

    fully_covered = {
        gid for gid, trip in gid_to_trip_ids.items()
        if gid_present.get(gid) == set(trip)
    }

    flat: list[dict] = []
    emitted_full_triplet: set[str] = set()
    partial_expanded_group: set[str] = set()

    for tid_int, task, row in prepared:
        trip_ids = _get_triplet_task_ids(task)
        if not trip_ids:
            flat.append(dict(row))
            continue
        gid = (str(task.task_group_id or '')).strip()
        if not gid:
            flat.append(dict(row))
            continue

        if gid in fully_covered:
            if gid not in emitted_full_triplet:
                emitted_full_triplet.add(gid)
                trip_set = set(trip_ids)
                for tid2, t2, r2 in prepared:
                    g2 = (str(t2.task_group_id or '')).strip()
                    if g2 == gid and tid2 in trip_set:
                        flat.append(dict(r2))
            continue

        if gid in partial_expanded_group:
            continue
        partial_expanded_group.add(gid)
        for sub_tid in trip_ids:
            sub_task = Tasks.query.get(sub_tid)
            if not sub_task:
                continue
            sub = dict(row)
            sub['task_id'] = sub_tid
            tpl = _get_task_template(sub_task)
            if tpl and tpl.max_primary_score is not None:
                sub['max_score'] = int(tpl.max_primary_score)
            else:
                try:
                    sub['max_score'] = int(row.get('max_score', 1) or 1)
                except (TypeError, ValueError):
                    sub['max_score'] = 1
            has_ans = bool((sub_task.answer or '').strip())
            sub['requires_manual_grading'] = _requires_manual_from_template(
                sub_task, has_ans, explicit_override=row.get('requires_manual_grading', False)
            )
            flat.append(sub)
    for i, row in enumerate(flat):
        row['order'] = i
    return flat


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
        hide_before_start = data.get('hide_before_start', True)
        allow_separate_submission = data.get('allow_separate_submission', True)
        attempts_per_task = data.get('attempts_per_task', False)
        if attempts_per_task:
            allow_separate_submission = True  # попытки на каждое задание подразумевают сдачу по одному
        time_limit_minutes = data.get('time_limit_minutes')
        time_limit_strict = data.get('time_limit_strict', False)
        max_attempts_default = data.get('max_attempts_default')
        if max_attempts_default is not None:
            try:
                max_attempts_default = max(1, int(max_attempts_default))
            except (TypeError, ValueError):
                max_attempts_default = 1
        else:
            max_attempts_default = 1
        description = data.get('description', '').strip()
        lesson_id = data.get('lesson_id')
        tasks_data = data.get('tasks', [])  # [{"task_id": 123, "max_score": 1, "order": 0, "max_attempts": null}, ...]
        recipient_ids = data.get('recipientIds', [])  # Список student_id
        group_id = data.get('groupId')  # "all" или конкретная группа
        
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

        tasks_data = _expand_tasks_data_for_triplets(tasks_data)
        if not tasks_data:
            return jsonify({'success': False, 'error': 'Добавьте хотя бы одну задачу'}), 400
        
        scope = get_user_scope(current_user)
        student_ids = []
        
        if group_id == 'all' and scope['can_see_all']:
            student_ids = [s.student_id for s in Student.query.filter_by(is_active=True).all()]
        elif group_id == 'all' and not scope['can_see_all']:
            students = get_students_for_tutor(current_user.id)
            student_ids = [s.student_id for s in students]
        elif group_id and str(group_id).isdigit():
            group_members = GroupStudent.query.filter_by(group_id=int(group_id)).all()
            student_ids = [gm.student_id for gm in group_members]
            if not scope['can_see_all']:
                accessible_students = get_students_for_tutor(current_user.id)
                accessible_ids = [s.student_id for s in accessible_students]
                student_ids = [sid for sid in student_ids if sid in accessible_ids]
        elif recipient_ids:
            if not scope['can_see_all']:
                accessible_students = get_students_for_tutor(current_user.id)
                accessible_ids = [s.student_id for s in accessible_students]
                recipient_ids = [rid for rid in recipient_ids if rid in accessible_ids]
            student_ids = recipient_ids
        
        if not student_ids:
            return jsonify({'success': False, 'error': 'Не выбраны получатели работы'}), 400
        
        dist_exam_course_id = None
        if lesson_id:
            lesson_obj = Lesson.query.get(lesson_id)
            if lesson_obj and lesson_obj.exam_course_id:
                dist_exam_course_id = lesson_obj.exam_course_id

        assignment = Assignment(
            title=title,
            description=description,
            assignment_type=assignment_type,
            deadline=deadline,
            hard_deadline=hard_deadline,
            hide_before_start=hide_before_start,
            allow_separate_submission=allow_separate_submission,
            attempts_per_task=attempts_per_task,
            time_limit_minutes=time_limit_minutes,
            time_limit_strict=time_limit_strict,
            max_attempts_default=max_attempts_default,
            created_by_id=current_user.id,
            lesson_id=lesson_id,
            exam_course_id=dist_exam_course_id,
            is_active=True
        )
        db.session.add(assignment)
        db.session.flush()  # Получаем assignment_id
        
        for idx, task_data in enumerate(tasks_data):
            task_id = task_data.get('task_id')
            max_score = task_data.get('max_score', 1)
            order_index = task_data.get('order', idx)
            requires_manual = task_data.get('requires_manual_grading', False)
            task_max_attempts = task_data.get('max_attempts')
            if task_max_attempts is not None:
                try:
                    task_max_attempts = max(1, int(task_max_attempts))
                except (TypeError, ValueError):
                    task_max_attempts = None
            
            if not task_id:
                continue
            
            task = Tasks.query.get(task_id)
            if not task:
                continue
            
            has_answer = bool((task.answer or '').strip())
            requires_manual_grading = _requires_manual_from_template(task, has_answer, explicit_override=requires_manual)
            assignment_task = AssignmentTask(
                assignment_id=assignment.assignment_id,
                task_id=task_id,
                order_index=order_index,
                max_score=max_score,
                max_attempts=task_max_attempts,
                requires_manual_grading=requires_manual_grading
            )
            db.session.add(assignment_task)
        
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

        task_ids = [at.task_id for at in assignment.tasks]
        label = {'homework': 'Домашняя работа', 'classwork': 'Классная работа', 'exam': 'Проверочная работа', 'test': 'Проверочная работа'}.get((assignment_type or 'homework').strip().lower(), 'Задания')
        summary = build_task_number_summary(task_ids)
        task_numbers = build_task_number_counts(task_ids)
        body = f"{label}: {summary}"
        link_url = url_for('assignments.assignments_list', _external=True)
        for student_id in student_ids:
            student = Student.query.get(student_id)
            if not student:
                continue
            user_id = getattr(student, 'user_id', None)
            if not user_id:
                try:
                    u = User.query.get(student.student_id)
                    if u and getattr(u, 'role', None) == 'student':
                        user_id = u.id
                except Exception:
                    pass
            if user_id:
                notify_user(
                    user_id,
                    kind='assignment_assigned',
                    title=f"Новые задания — {label}",
                    body=body,
                    link_url=link_url,
                    meta={'assignment_id': assignment.assignment_id, 'assignment_type': (assignment_type or 'homework').strip().lower(), 'tasks_count': len(task_ids), 'task_numbers': task_numbers},
                )
        try:
            db.session.commit()
        except Exception as notif_err:
            logger.warning("Failed to commit assignment notifications: %s", notif_err)
            db.session.rollback()

        return jsonify({
            'success': True,
            'assignment_id': assignment.assignment_id,
            'submissions_count': len(student_ids)
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in distribute_assignment: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500



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
                    (Submission.status.in_(['SUBMITTED', 'LATE', 'GRADED', 'RETURNED', 'NEEDS_MANUAL_REVIEW']), 1),
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

    kpi_rows = base_query.all()

    def _derive_flags(a: Assignment, row) -> dict:
        total_students = _safe_int(getattr(row, 'total_students', 0))
        to_grade = _safe_int(getattr(row, 'to_grade', 0))
        returned = _safe_int(getattr(row, 'returned', 0))
        in_progress = _safe_int(getattr(row, 'in_progress', 0))
        assigned = _safe_int(getattr(row, 'assigned', 0))
        pending = assigned + in_progress + returned

        deadline_naive = None
        if a.deadline:
            deadline_naive = a.deadline.replace(tzinfo=None) if a.deadline.tzinfo else a.deadline
        
        is_overdue = bool(deadline_naive and deadline_naive < now and pending > 0)
        is_completed = bool(total_students > 0 and pending == 0 and to_grade == 0)
        is_active = bool(deadline_naive and deadline_naive >= now and (pending > 0 or to_grade > 0))
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

    if sort == 'deadline_asc':
        filtered_query = filtered_query.order_by(Assignment.deadline.asc(), Assignment.created_at.desc())
    elif sort == 'deadline_desc':
        filtered_query = filtered_query.order_by(Assignment.deadline.desc(), Assignment.created_at.desc())
    elif sort == 'title_asc':
        filtered_query = filtered_query.order_by(func.lower(Assignment.title).asc(), Assignment.created_at.desc())
    else:
        filtered_query = filtered_query.order_by(Assignment.created_at.desc(), Assignment.assignment_id.desc())

    rows = filtered_query.all()

    assignment_ids = [row[0].assignment_id for row in rows]
    students_by_assignment = {}
    if assignment_ids:
        student_subs = (
            db.session.query(
                Submission.assignment_id,
                Submission.status,
                Student.name,
                Student.student_id,
            )
            .join(Student, Student.student_id == Submission.student_id)
            .filter(Submission.assignment_id.in_(assignment_ids))
            .order_by(Student.name)
            .all()
        )
        for aid, sub_status, sname, sid in student_subs:
            if aid not in students_by_assignment:
                students_by_assignment[aid] = []
            students_by_assignment[aid].append({
                'name': sname,
                'student_id': sid,
                'status': sub_status,
            })

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

        deadline_naive = None
        if assignment.deadline:
            deadline_naive = assignment.deadline.replace(tzinfo=None) if assignment.deadline.tzinfo else assignment.deadline
        
        is_overdue = bool(deadline_naive and deadline_naive < now and pending > 0)
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
            'student_submissions': students_by_assignment.get(assignment.assignment_id, []),
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
            task_numbers=get_task_numbers(None),
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
    assignment_type = (request.form.get('assignment_type') or 'homework').strip().lower()
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

    return redirect(url_for('assignments.assignments_accepted', assignment_type=assignment_type, task_type=task_type))


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
            task_numbers=get_task_numbers(None),
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
                return redirect(url_for('task_generator.task_generator', lesson_id=lesson_id, assignment_type=assignment_type))
            return redirect(url_for('task_generator.task_generator', assignment_type=assignment_type))
    except Exception:
        flash('Неверные параметры запроса.', 'danger')
        assignment_type = request.args.get('assignment_type', 'homework')
        lesson_id = request.args.get('lesson_id', type=int)
        if lesson_id:
            return redirect(url_for('task_generator.task_generator', lesson_id=lesson_id, assignment_type=assignment_type))
        return redirect(url_for('task_generator.task_generator', assignment_type=assignment_type))

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
            return redirect(url_for('task_generator.task_generator', assignment_type=assignment_type))

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
            return redirect(url_for('task_generator.task_generator', lesson_id=lesson_id, assignment_type=assignment_type))
        return redirect(url_for('task_generator.task_generator', assignment_type=assignment_type))

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
            return redirect(url_for('task_generator.task_generator', lesson_id=lesson_id, assignment_type=assignment_type))
        return redirect(url_for('task_generator.task_generator', assignment_type=assignment_type))

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
    source = (request.args.get('source') or 'manual').strip().lower()
    if source not in {'accepted', 'template', 'manual', 'lesson', 'generator'}:
        source = 'manual'

    assignment_type = _normalize_assignment_type(request.args.get('assignment_type')) or 'homework'
    task_type = request.args.get('task_type', type=int, default=None)
    template_id = request.args.get('template_id', type=int, default=None)
    lesson_id = request.args.get('lesson_id', type=int, default=None)
    task_ids_param = request.args.get('task_ids', type=str, default=None)
    recipient_ids_param = request.args.get('recipient_ids', type=str, default=None)

    tasks: list[Tasks] = []
    source_label = ''
    source_meta: dict[str, Any] = {}
    default_recipient_ids: list[int] = []
    if recipient_ids_param:
        try:
            default_recipient_ids = [int(x.strip()) for x in recipient_ids_param.split(',') if x.strip() and x.strip().isdigit()]
            scope = get_user_scope(current_user)
            if not scope.get('can_see_all'):
                allowed = get_students_for_tutor(current_user.id) or []
                allowed_ids = {int(s.student_id) for s in allowed if getattr(s, 'student_id', None)}
                default_recipient_ids = [x for x in default_recipient_ids if x in allowed_ids]
        except Exception:
            default_recipient_ids = []

    # Каждый новый запуск мастера должен стартовать с пустого пула задач.
    # "Новая работа" = нет явно переданных task_ids/template/lesson.
    if not task_ids_param and not template_id and not lesson_id and source in {'accepted', 'manual', 'generator'}:
        source = 'manual'

    if source == 'generator' and task_ids_param:
        try:
            ids = [int(x.strip()) for x in task_ids_param.split(',') if x.strip() and x.strip().isdigit()]
            ids = list(dict.fromkeys(ids))[:500]
            if ids:
                tasks = Tasks.query.filter(Tasks.task_id.in_(ids)).order_by(Tasks.task_id.asc()).all()
                tasks = sorted(tasks, key=lambda t: ids.index(t.task_id) if t.task_id in ids else 999)
            source_label = 'Из генератора'
            source_meta = {'task_ids': ids}
        except Exception:
            tasks = []
            source_label = 'Из генератора'
    elif source == 'generator':
        source_label = 'Вручную'
    elif source == 'accepted':
        tasks = get_accepted_tasks(task_type=task_type)
        source_label = 'Из генератора (буфер принятых)'
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

        try:
            scope = get_user_scope(current_user)
            if not scope.get('can_see_all'):
                allowed_students = get_students_for_tutor(current_user.id) or []
                allowed_ids = {int(s.student_id) for s in allowed_students if getattr(s, 'student_id', None)}
                if int(getattr(lesson, 'student_id', 0) or 0) not in allowed_ids:
                    return redirect(url_for('lessons.lesson_edit', lesson_id=lesson.lesson_id))
        except Exception:
            pass

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

    templates: list[TaskTemplate] = []
    try:
        templates = (
            TaskTemplate.query.order_by(TaskTemplate.name.asc(), TaskTemplate.template_id.asc())
            .limit(300)
            .all()
        )
    except Exception:
        templates = []

    tasks = _expand_tasks_list_for_triplets(tasks or [])

    task_ids = []
    try:
        task_ids = [int(t.task_id) for t in (tasks or []) if getattr(t, 'task_id', None)]
    except Exception:
        task_ids = []

    already_sent_task_ids: list[int] = []
    if default_recipient_ids:
        already_sent_task_ids = sorted(get_task_ids_in_assignments_for_students(default_recipient_ids))

    from app.models import SchoolGroup
    available_groups = []
    try:
        scope = get_user_scope(current_user)
        if scope.get('can_see_all'):
            available_groups = SchoolGroup.query.filter_by(status='active').order_by(SchoolGroup.title.asc()).all()
        else:
            available_groups = SchoolGroup.query.filter_by(
                status='active', owner_user_id=current_user.id
            ).order_by(SchoolGroup.title.asc()).all()
    except Exception:
        pass

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
        already_sent_task_ids=already_sent_task_ids,
        available_groups=available_groups,
    )


@assignments_bp.route('/assignments/<int:assignment_id>/edit', methods=['GET'])
@login_required
@check_access('assignment.create')
def assignment_edit(assignment_id: int):
    """Страница редактирования работы: название, дедлайн, состав заданий."""
    assignment = Assignment.query.options(
        joinedload(Assignment.tasks).joinedload(AssignmentTask.task),
        joinedload(Assignment.created_by),
    ).get_or_404(assignment_id)
    scope = get_user_scope(current_user)
    if not scope.get('can_see_all') and assignment.created_by_id != current_user.id:
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('assignments.assignments_list'))
    assignment_tasks = sorted(assignment.tasks or [], key=lambda at: (at.order_index, at.assignment_task_id))
    return render_template(
        'assignment_edit.html',
        active_page='assignments',
        assignment=assignment,
        assignment_tasks=assignment_tasks,
    )


@assignments_bp.route('/assignments/<int:assignment_id>/update', methods=['POST', 'PUT'])
@login_required
@check_access('assignment.create')
def assignment_update(assignment_id: int):
    """Обновление работы: название, описание, дедлайн, состав заданий (порядок, баллы)."""
    assignment = Assignment.query.get_or_404(assignment_id)
    scope = get_user_scope(current_user)
    if not scope.get('can_see_all') and assignment.created_by_id != current_user.id:
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    try:
        data = request.get_json() or {}
        title = (data.get('title') or '').strip()
        if title:
            assignment.title = title
        description = (data.get('description') or '').strip()
        assignment.description = description if description else None
        deadline_str = data.get('deadline')
        if deadline_str:
            try:
                deadline = datetime.fromisoformat(deadline_str.replace('Z', '+00:00'))
                if deadline.tzinfo:
                    deadline = deadline.astimezone(moscow_now().tzinfo).replace(tzinfo=None)
                assignment.deadline = deadline
            except Exception:
                pass
        assignment.hard_deadline = bool(data.get('hard_deadline', assignment.hard_deadline))
        assignment.hide_before_start = bool(data.get('hide_before_start', assignment.hide_before_start))
        assignment.allow_separate_submission = bool(data.get('allow_separate_submission', assignment.allow_separate_submission))
        assignment.attempts_per_task = bool(data.get('attempts_per_task', assignment.attempts_per_task))
        if 'time_limit_minutes' in data:
            v = data['time_limit_minutes']
            assignment.time_limit_minutes = int(v) if v is not None and str(v).strip() != '' else None
        assignment.time_limit_strict = bool(data.get('time_limit_strict', assignment.time_limit_strict))
        if 'max_attempts_default' in data:
            v = data['max_attempts_default']
            try:
                assignment.max_attempts_default = max(1, int(v)) if v is not None and str(v).strip() != '' else 1
            except (TypeError, ValueError):
                assignment.max_attempts_default = 1
        tasks_data = data.get('tasks', [])
        if isinstance(tasks_data, list) and len(tasks_data) > 0:
            tasks_data = _expand_tasks_data_for_triplets(tasks_data)
        if isinstance(tasks_data, list) and len(tasks_data) > 0:
            new_task_ids = [t.get('task_id') for t in tasks_data if t.get('task_id')]
            existing_by_task_id = {at.task_id: at for at in (assignment.tasks or [])}
            for idx, t_data in enumerate(tasks_data):
                task_id = t_data.get('task_id')
                if not task_id:
                    continue
                if task_id not in existing_by_task_id:
                    task = Tasks.query.get(task_id)
                    if not task:
                        continue
                    has_ans = bool((task.answer or '').strip()) or bool((t_data.get('answer_override') or '').strip())
                    requires_manual = _requires_manual_from_template(task, has_ans, explicit_override=t_data.get('requires_manual_grading', False))
                    at = AssignmentTask(
                        assignment_id=assignment.assignment_id,
                        task_id=task_id,
                        order_index=idx,
                        max_score=int(t_data.get('max_score', 1)) or 1,
                        max_attempts=t_data.get('max_attempts'),
                        answer_override=(t_data.get('answer_override') or '').strip() or None,
                        requires_manual_grading=requires_manual,
                    )
                    db.session.add(at)
                    existing_by_task_id[task_id] = at
                else:
                    at = existing_by_task_id[task_id]
                    at.order_index = idx
                    at.max_score = int(t_data.get('max_score', at.max_score)) or 1
                    if 'max_attempts' in t_data:
                        at.max_attempts = t_data['max_attempts']
                    if 'answer_override' in t_data:
                        at.answer_override = (t_data.get('answer_override') or '').strip() or None
                    task = at.task
                    if task:
                        has_ans = bool((task.answer or '').strip()) or bool((at.answer_override or '').strip())
                        at.requires_manual_grading = _requires_manual_from_template(task, has_ans)
            for at in list(assignment.tasks or []):
                if at.task_id not in new_task_ids:
                    db.session.delete(at)
            db.session.flush()
            new_total = sum(at.max_score for at in existing_by_task_id.values())
            for sub in (assignment.submissions or []):
                sub.max_score = new_total
        db.session.commit()
        return jsonify({'success': True, 'redirect': url_for('assignments.assignment_view', assignment_id=assignment.assignment_id)})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Assignment update failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@assignments_bp.route('/assignments/<int:assignment_id>/tasks', methods=['POST'])
@login_required
@check_access('assignment.create')
def assignment_add_tasks(assignment_id: int):
    """Добавить задания в работу (из генератора). Body: { "task_ids": [1,2,3] }."""
    assignment = Assignment.query.get_or_404(assignment_id)
    scope = get_user_scope(current_user)
    if not scope.get('can_see_all') and assignment.created_by_id != current_user.id:
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    try:
        data = request.get_json() or {}
        task_ids = data.get('task_ids') or []
        if not isinstance(task_ids, list):
            task_ids = [task_ids]
        task_ids = [int(x) for x in task_ids if x is not None and str(x).strip() != '']
        task_ids = _expand_task_ids_for_triplets(task_ids)
        existing_task_ids = {at.task_id for at in (assignment.tasks or [])}
        max_order = max((at.order_index for at in (assignment.tasks or [])), default=-1)
        added = 0
        for i, task_id in enumerate(task_ids):
            if task_id in existing_task_ids:
                continue
            task = Tasks.query.get(task_id)
            if not task:
                continue
            has_answer = bool((task.answer or '').strip())
            requires_manual = _requires_manual_from_template(task, has_answer)
            template = _get_task_template(task)
            default_score = template.max_primary_score if template and template.max_primary_score is not None else 1
            at = AssignmentTask(
                assignment_id=assignment.assignment_id,
                task_id=task_id,
                order_index=max_order + 1 + i,
                max_score=default_score,
                requires_manual_grading=requires_manual,
            )
            db.session.add(at)
            existing_task_ids.add(task_id)
            added += 1
        db.session.commit()
        return jsonify({'success': True, 'added': added, 'redirect': url_for('assignments.assignment_edit', assignment_id=assignment.assignment_id)})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Assignment add tasks failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


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
        hide_before_start=bool(getattr(src, 'hide_before_start', True)),
        time_limit_minutes=src.time_limit_minutes,
        max_attempts_default=getattr(src, 'max_attempts_default', None),
        created_by_id=current_user.id,
        lesson_id=None,
        rubric_template_id=src.rubric_template_id,
        is_active=True,
    )
    db.session.add(new_assignment)
    db.session.flush()

    for t in (src.tasks or []):
        db.session.add(AssignmentTask(
            assignment_id=new_assignment.assignment_id,
            task_id=t.task_id,
            order_index=t.order_index,
            max_score=t.max_score,
            max_attempts=getattr(t, 'max_attempts', None),
            answer_override=getattr(t, 'answer_override', None),
            requires_manual_grading=bool(t.requires_manual_grading),
        ))

    student_ids = []
    for s in (src.submissions or []):
        if getattr(s, 'student_id', None):
            student_ids.append(int(s.student_id))
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
    try:
        assignment = Assignment.query.options(
            joinedload(Assignment.tasks).joinedload(AssignmentTask.task),
            joinedload(Assignment.submissions).joinedload(Submission.student),
            joinedload(Assignment.created_by)
        ).get_or_404(assignment_id)
    except Exception as e:
        logger.error(f"Error loading assignment {assignment_id}: {e}", exc_info=True)
        flash('Ошибка при загрузке работы', 'danger')
        return redirect(url_for('assignments.assignments_list'))
    
    try:
        scope = get_user_scope(current_user)
        can_access = scope.get('can_see_all', False) or (assignment.created_by_id == current_user.id)
        if not can_access:
            flash('Доступ запрещен', 'danger')
            return redirect(url_for('assignments.assignments_list'))
    except Exception as e:
        logger.error(f"Error checking access for assignment {assignment_id}: {e}", exc_info=True)
        flash('Ошибка при проверке доступа', 'danger')
        return redirect(url_for('assignments.assignments_list'))

    try:
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
                return st in {'SUBMITTED', 'LATE', 'GRADED', 'RETURNED', 'NEEDS_MANUAL_REVIEW'}
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
            ts = getattr(s, 'submitted_at', None) or getattr(s, 'assigned_at', None) or getattr(s, 'created_at', None)
            try:
                ts_val = ts.timestamp() if ts else 0
            except Exception:
                ts_val = 0
            return (order.get(st, 9), -ts_val)

        submissions.sort(key=_sort_key)

        now = moscow_now()
        submission_display_status = {}
        for s in submissions:
            label = _submission_display_status(s, assignment, now)
            if label:
                submission_display_status[s.submission_id] = label

        can_manage = bool(has_permission(current_user, 'assignment.create')) and (scope.get('can_see_all') or assignment.created_by_id == current_user.id)

        return render_template(
            'assignment_view.html',
            assignment=assignment,
            submissions=submissions,
            counts=counts,
            status_filter=status_filter,
            student_query=student_query,
            can_manage=can_manage,
            submission_display_status=submission_display_status,
        )
    except Exception as e:
        logger.error(f"Error processing assignment_view for assignment {assignment_id}: {e}", exc_info=True)
        flash('Ошибка при обработке данных работы', 'danger')
        return redirect(url_for('assignments.assignments_list'))



@assignments_bp.route('/submissions')
@login_required
def submissions_list():
    """Список назначенных работ для ученика"""
    try:
        db.session.rollback()
    except Exception:
        pass

    student = get_student_by_user_id(current_user.id)
    if not student:
        flash('Профиль ученика не найден', 'warning')
        return redirect(url_for('auth.user_profile'))
    
    submissions = Submission.query.join(Submission.assignment).filter(
        Submission.student_id == student.student_id,
        Assignment.is_active.is_(True)
    ).options(
        joinedload(Submission.assignment).joinedload(Assignment.tasks),
        joinedload(Submission.assignment).joinedload(Assignment.created_by),
        joinedload(Submission.answers)
    ).order_by(Submission.assigned_at.desc()).all()
    
    lesson_workspaces = []
    try:
        lessons = Lesson.query.filter_by(student_id=student.student_id).options(
            joinedload(Lesson.homework_tasks).joinedload(LessonTask.task)
        ).order_by(Lesson.lesson_date.desc()).limit(10).all()

        for l in lessons:
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

    now = moscow_now()
    submission_display_status = {}
    for sub in submissions:
        label = _submission_display_status(sub, sub.assignment, now)
        if label:
            submission_display_status[sub.submission_id] = label

    return render_template('submissions_list.html', submissions=submissions, student=student, lesson_workspaces=lesson_workspaces, submission_display_status=submission_display_status)


@assignments_bp.route('/submissions/<int:submission_id>')
@login_required
def submission_view(submission_id):
    """Просмотр и выполнение работы"""
    try:
        db.session.rollback()
    except Exception:
        pass

    try:
        submission = Submission.query.options(
            joinedload(Submission.assignment).joinedload(Assignment.tasks).joinedload(AssignmentTask.task),
            joinedload(Submission.assignment).joinedload(Assignment.created_by),
            joinedload(Submission.answers),
            joinedload(Submission.attempts),
            joinedload(Submission.comments).joinedload(SubmissionComment.author)
        ).get_or_404(submission_id)
    except Exception as e:
        logger.error(f"Error loading submission {submission_id}: {e}", exc_info=True)
        flash('Ошибка при загрузке работы', 'danger')
        return redirect(url_for('assignments.submissions_list'))
    
    try:
        student = get_student_by_user_id(current_user.id)
        if not student or submission.student_id != student.student_id:
            flash('Доступ запрещен', 'danger')
            return redirect(url_for('assignments.submissions_list'))
    except Exception as e:
        logger.error(f"Error checking access for submission {submission_id}: {e}", exc_info=True)
        flash('Ошибка при проверке доступа', 'danger')
        return redirect(url_for('assignments.submissions_list'))
    
    assignment = submission.assignment
    if not assignment:
        flash('Работа не найдена', 'danger')
        return redirect(url_for('assignments.submissions_list'))
    
    try:
        now = moscow_now()
        deadline = _ensure_aware_datetime(assignment.deadline)
        
        if deadline:
            is_deadline_passed = now > deadline
        else:
            is_deadline_passed = False
        can_submit = not (is_deadline_passed and assignment.hard_deadline)
        
        all_attempts = submission.attempts or []
        attempts_used = sum(1 for a in all_attempts if getattr(a, 'status', '') == 'SUBMITTED')
        effective_max_attempts = assignment.get_effective_max_attempts()
        if attempts_used >= effective_max_attempts and submission.status != 'RETURNED':
            can_submit = False
        attempts_left = max(0, effective_max_attempts - attempts_used)
        
        attempts_per_task = getattr(assignment, 'attempts_per_task', False)
        timer_expired = False
        if assignment.time_limit_strict and assignment.time_limit_minutes and submission.started_at:
            if submission.status != 'RETURNED':
                started_utc = _started_at_to_utc(submission.started_at)
                now_utc = now.astimezone(timezone.utc)
                limit_end_utc = started_utc + timedelta(minutes=assignment.time_limit_minutes)
                timer_expired = now_utc > limit_end_utc
        events = (
            AnalyticsEvent.query
            .filter(AnalyticsEvent.submission_id == submission_id)
            .order_by(AnalyticsEvent.id.desc())
            .all()
        )
        event_by_answer: dict[int, AnalyticsEvent] = {}
        event_by_task: dict[int, AnalyticsEvent] = {}
        for ev in events:
            if ev.answer_id and ev.answer_id not in event_by_answer:
                event_by_answer[int(ev.answer_id)] = ev
            if ev.task_id and ev.task_id not in event_by_task:
                event_by_task[int(ev.task_id)] = ev

        tasks_data = []
        for assignment_task in sorted(assignment.tasks, key=lambda t: t.order_index):
            answer = next((a for a in submission.answers if a.assignment_task_id == assignment_task.assignment_task_id), None)
            max_for_task = assignment.get_effective_max_attempts_for_task(assignment_task) if attempts_per_task else 1
            task_attempts_used = (answer.attempts_used or 0) if answer else 0
            task = assignment_task.task
            template = _get_task_template(task)
            requires_manual_review = bool(template and template.requires_manual_review)
            diff_level = getattr(assignment_task, 'difficulty_level', None)
            if diff_level is None and task is not None:
                diff_level = getattr(task, 'difficulty_level', None)
            difficulty_label = 'Стандарт'
            if diff_level == 1:
                difficulty_label = 'База'
            elif diff_level == 3:
                difficulty_label = 'Хард'
            ev = None
            if answer and getattr(answer, 'answer_id', None):
                ev = event_by_answer.get(int(answer.answer_id))
            if ev is None and task and getattr(task, 'task_id', None):
                ev = event_by_task.get(int(task.task_id))
            flags = (ev.behavior_flags or {}) if ev else {}
            rating_meta = None
            if ev:
                rating_meta = {
                    'mmr_delta': float(ev.mmr_delta or 0.0),
                    'new_rating': float(ev.new_rating) if ev.new_rating is not None else None,
                    'difficulty_label': flags.get('difficulty_label') or (
                        'База' if ev.task_difficulty == 1 else ('Хард' if ev.task_difficulty == 3 else 'Стандарт')
                    ),
                    'time_coeff': flags.get('time_coeff'),
                    'attempt_coeff': flags.get('attempt_coeff'),
                    'time_spent_sec': ev.time_spent_sec,
                    'time_band': flags.get('time_band'),
                }
            tasks_data.append({
                'assignment_task': assignment_task,
                'task': task,
                'answer': answer,
                'max_attempts_for_task': max_for_task,
                'task_attempts_used': task_attempts_used,
                'requires_manual_review': requires_manual_review,
                'rating_meta': rating_meta,
                'difficulty_label': difficulty_label,
            })

        tasks_view = []
        i = 0
        while i < len(tasks_data):
            item = tasks_data[i]
            item_task = item.get('task')
            item_num = getattr(item_task, 'task_number', None) if item_task else None
            item_group = getattr(item_task, 'task_group_id', None) if item_task else None

            can_bundle = i + 2 < len(tasks_data)
            if item_num == 19 and can_bundle:
                next_20 = tasks_data[i + 1]
                next_21 = tasks_data[i + 2]
                task_20 = next_20.get('task')
                task_21 = next_21.get('task')
                num_20 = getattr(task_20, 'task_number', None) if task_20 else None
                num_21 = getattr(task_21, 'task_number', None) if task_21 else None
                group_20 = getattr(task_20, 'task_group_id', None) if task_20 else None
                group_21 = getattr(task_21, 'task_group_id', None) if task_21 else None

                same_group = bool(item_group and group_20 and group_21 and item_group == group_20 == group_21)
                legacy_consecutive = (num_20 == 20 and num_21 == 21)

                if (num_20 == 20 and num_21 == 21) and (same_group or legacy_consecutive):
                    root_item = dict(item)
                    root_item['is_triplet_19_21'] = True
                    root_item['triplet_items'] = [next_20, next_21]
                    tasks_view.append(root_item)
                    i += 3
                    continue

            single_item = dict(item)
            single_item['is_triplet_19_21'] = False
            single_item['triplet_items'] = []
            tasks_view.append(single_item)
            i += 1
        
        return render_template('submission_view.html',
                             submission=submission,
                             assignment=assignment,
                             tasks_data=tasks_data,
                             tasks_view=tasks_view,
                             is_deadline_passed=is_deadline_passed,
                             can_submit=can_submit,
                             attempts_used=attempts_used,
                             effective_max_attempts=effective_max_attempts,
                             attempts_left=attempts_left,
                             allow_separate_submission=assignment.allow_separate_submission,
                             attempts_per_task=attempts_per_task,
                             time_limit_strict=assignment.time_limit_strict,
                             timer_expired=timer_expired)
    except Exception as e:
        logger.error(f"Error processing submission_view for submission {submission_id}: {e}", exc_info=True)
        flash('Ошибка при обработке данных работы', 'danger')
        return redirect(url_for('assignments.submissions_list'))


@assignments_bp.route('/submissions/<int:submission_id>/start', methods=['POST'])
@login_required
@limiter.limit("10 per minute")
def submission_start(submission_id):
    """Старт выполнения работы"""
    try:
        logger.info(f"Starting submission {submission_id} for user {current_user.id}")
        
        submission = Submission.query.get_or_404(submission_id)
        logger.info(f"Found submission {submission_id}")
        
        student = get_student_by_user_id(current_user.id)
        logger.info(f"Student for user {current_user.id}: {student}")
        
        if not student or submission.student_id != student.student_id:
            logger.warning(f"Access denied: student={student}, submission.student_id={submission.student_id}")
            return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
        
        if submission.status != 'ASSIGNED':
            logger.warning(f"Invalid status for submission {submission_id}: {submission.status}")
            return jsonify({'success': False, 'error': 'Работа уже начата или сдана'}), 400
        
        now = moscow_now()
        deadline = _ensure_aware_datetime(submission.assignment.deadline)
        logger.info(f"Current time: {now}, deadline: {deadline}, hard_deadline: {submission.assignment.hard_deadline}")
        
        if deadline and now > deadline and submission.assignment.hard_deadline:
            logger.warning(f"Deadline passed for submission {submission_id}")
            return jsonify({'success': False, 'error': 'Дедлайн истек'}), 400
        
        submission.status = 'IN_PROGRESS'
        submission.started_at = now
        logger.info(f"Saving submission {submission_id} with status IN_PROGRESS and started_at {now}")
        db.session.commit()
        logger.info(f"Successfully committed submission {submission_id}")
        
        return jsonify({'success': True, 'started_at': submission.started_at.isoformat()}), 200
    
    except Exception as e:
        logger.error(f"Error in submission_start for submission {submission_id}: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Ошибка сервера: {str(e)}'}), 500


def _attachment_fallback_url_from_db(task_id: int, filename: str):
    """Если файла нет на диске — по task_id и имени файла ищем url в attached_files и возвращаем URL для proxy или None."""
    import json
    task = Tasks.query.filter_by(task_id=task_id).first()
    if not task or not task.attached_files:
        return None
    try:
        files = json.loads(task.attached_files) if isinstance(task.attached_files, str) else task.attached_files
    except Exception:
        return None
    safe_name = (filename or '').strip()
    if not safe_name:
        return None
    for f in (files or []):
        if not isinstance(f, dict):
            continue
        name = (f.get('name') or f.get('filename') or '').strip()
        path = (f.get('path') or '').strip()
        path_basename = path.split('/')[-1].split('?')[0] if path else ''
        if name == safe_name or path_basename == safe_name:
            url = (f.get('url') or f.get('href') or '').strip()
            if url.startswith('//'):
                url = 'https:' + url
            elif url.startswith('/'):
                url = 'https://kompege.ru' + url
            if url.startswith('https://kompege.ru/') or url.startswith('http://kompege.ru/'):
                return url
            break
    return None


@assignments_bp.route('/attachments/task/<int:task_id>/<path:filename>')
@login_required
def attached_task_local(task_id: int, filename: str):
    """Раздача локально скачанных вложений заданий. Если файла нет на диске — пробуем отдать через proxy по URL из БД."""
    import os
    from flask import send_from_directory, redirect
    custom_root = current_app.config.get('TASK_ATTACHMENTS_ROOT')
    if custom_root and os.path.isdir(custom_root):
        root = custom_root
    else:
        root = os.path.join(current_app.root_path, 'uploads', 'task_attachments')
    task_dir = os.path.join(root, str(task_id))
    safe_name = os.path.basename(filename) if filename else ''
    if not safe_name or '..' in (filename or ''):
        abort(404)
    file_on_disk = os.path.isfile(os.path.join(task_dir, safe_name)) if os.path.isdir(task_dir) else False
    if file_on_disk:
        download_name = request.args.get('download_name', '').strip()
        if not download_name or '..' in download_name or '/' in download_name:
            download_name = safe_name
        return send_from_directory(task_dir, safe_name, as_attachment=True, download_name=download_name)
    # Файла нет на диске — пробуем взять url из БД и отдать через proxy
    fallback_url = _attachment_fallback_url_from_db(task_id, safe_name)
    if fallback_url:
        proxy_url = url_for('assignments.attached_proxy', url=fallback_url, _external=False)
        return redirect(proxy_url)
    abort(404)


@assignments_bp.route('/attachments/proxy')
@login_required
def attached_proxy():
    """Proxy для скачивания внешних вложений (ограничен по домену).
    Принимает параметр `url` — внешний адрес файла. Возвращает потоковый ответ с заголовками.
    """
    url = request.args.get('url', '')
    if not url:
        abort(400)

    allowed_prefixes = ('https://kompege.ru/', 'http://kompege.ru/')
    if not any(url.startswith(p) for p in allowed_prefixes):
        logger.warning(f'Attempt to proxy disallowed url: {url}')
        abort(400)

    try:
        upstream = requests.get(url, stream=True, timeout=15)
    except Exception as e:
        logger.error(f'Error fetching upstream attachment {url}: {e}')
        abort(502)

    def generate():
        try:
            for chunk in upstream.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    content_type = upstream.headers.get('content-type', 'application/octet-stream')
    filename = url.split('/')[-1].split('?')[0]
    resp = Response(stream_with_context(generate()), content_type=content_type)
    resp.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp


@assignments_bp.route('/submissions/<int:submission_id>/upload-answer-file', methods=['POST'])
@login_required
@limiter.limit('30/minute')
def upload_answer_file(submission_id):
    """
    Загрузка файла к ответу на задание.
    multipart/form-data: file, assignment_task_id
    """
    submission = Submission.query.options(
        joinedload(Submission.assignment).joinedload(Assignment.tasks),
        joinedload(Submission.answers),
    ).filter_by(submission_id=submission_id).first_or_404()

    student = get_student_by_user_id(current_user.id)
    scope = get_user_scope(current_user)
    can_see = scope.get('can_see_all') or getattr(current_user, 'is_tutor', lambda: False)() or getattr(current_user, 'is_admin', lambda: False)()
    is_owner = student and student.student_id == submission.student_id
    if not is_owner and not can_see:
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    if submission.status not in ['IN_PROGRESS', 'ASSIGNED', 'RETURNED']:
        return jsonify({'success': False, 'error': 'Нельзя загружать файлы для сданной работы'}), 400

    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'Файл не передан'}), 400

    file = request.files['file']
    if not file or not getattr(file, 'filename', None) or not str(file.filename or '').strip():
        return jsonify({'success': False, 'error': 'Файл не выбран'}), 400

    assignment_task_id = request.form.get('assignment_task_id')
    if not assignment_task_id:
        return jsonify({'success': False, 'error': 'Укажите assignment_task_id'}), 400
    try:
        assignment_task_id = int(assignment_task_id)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Некорректный assignment_task_id'}), 400

    assignment = submission.assignment
    at = next((t for t in (assignment.tasks or []) if t.assignment_task_id == assignment_task_id), None)
    if not at:
        return jsonify({'success': False, 'error': 'Задание не найдено в этой работе'}), 404

    root = current_app.config.get('ANSWER_ATTACHMENTS_ROOT')
    if not root:
        root = os.path.join(current_app.root_path, 'uploads', 'answer_attachments')
    base_folder = os.path.join(root, f'submission_{submission_id}')
    os.makedirs(base_folder, exist_ok=True)

    raw_name = str(file.filename or '').strip()
    safe_full = secure_filename(raw_name)
    ext = (os.path.splitext(raw_name)[1] or '').lower()
    safe_base = secure_filename(os.path.splitext(raw_name)[0]) or 'file'
    orig = f"{safe_base}{ext}" if ext else f"{safe_base}"
    allowed_exts = {'pdf', 'doc', 'docx', 'txt', 'png', 'jpg', 'jpeg', 'gif', 'xls', 'xlsx', 'zip', 'py'}
    if ext.lstrip('.') not in allowed_exts:
        return jsonify({'success': False, 'error': f'Тип файла не разрешён. Разрешены: {", ".join(sorted(allowed_exts))}'}), 400

    stored_name = f"{int(time.time())}_{orig}"
    abs_path = os.path.join(base_folder, stored_name)
    if not os.path.abspath(abs_path).startswith(os.path.abspath(base_folder)):
        return jsonify({'success': False, 'error': 'Некорректный путь'}), 400

    try:
        file.save(abs_path)
    except Exception as e:
        logger.warning(f"Failed to save answer file: {e}")
        return jsonify({'success': False, 'error': 'Ошибка сохранения файла'}), 500

    answer = next((a for a in (submission.answers or []) if a.assignment_task_id == assignment_task_id), None)
    if not answer:
        answer = Answer(
            submission_id=submission_id,
            assignment_task_id=assignment_task_id,
            max_score=at.max_score,
        )
        db.session.add(answer)

    files_list = list(answer.files) if isinstance(answer.files, list) else []
    if answer.files is None:
        files_list = []
    files_list.append({
        'filename': stored_name,
        'original_name': raw_name,
        'assignment_task_id': assignment_task_id,
    })
    answer.files = files_list
    answer.updated_at = moscow_now()

    if submission.status in ['ASSIGNED', 'RETURNED']:
        submission.status = 'IN_PROGRESS'
        if not submission.started_at:
            submission.started_at = moscow_now()

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        try:
            os.remove(abs_path)
        except Exception:
            pass
        return jsonify({'success': False, 'error': 'Ошибка сохранения в БД'}), 500

    return jsonify({
        'success': True,
        'filename': stored_name,
        'original_name': raw_name,
        'url': url_for('assignments.serve_answer_file', submission_id=submission_id, filename=stored_name),
    }), 200


@assignments_bp.route('/answer-files/<int:submission_id>/<path:filename>')
@login_required
def serve_answer_file(submission_id, filename):
    """Раздача прикреплённого файла ответа."""
    submission = Submission.query.options(
        joinedload(Submission.answers),
    ).filter_by(submission_id=submission_id).first_or_404()

    student = get_student_by_user_id(current_user.id)
    scope = get_user_scope(current_user)
    can_see = scope.get('can_see_all') or getattr(current_user, 'is_tutor', lambda: False)() or getattr(current_user, 'is_admin', lambda: False)()
    is_owner = student and student.student_id == submission.student_id
    if not is_owner and not can_see:
        abort(403)

    safe_name = os.path.basename(filename) if filename else ''
    if not safe_name or '..' in (filename or '') or '/' in safe_name:
        abort(404)

    found = False
    for ans in (submission.answers or []):
        flist = ans.files if isinstance(ans.files, list) else []
        for f in flist:
            if isinstance(f, dict) and f.get('filename') == safe_name:
                found = True
                break
        if found:
            break
    if not found:
        abort(404)

    root = current_app.config.get('ANSWER_ATTACHMENTS_ROOT')
    if not root:
        root = os.path.join(current_app.root_path, 'uploads', 'answer_attachments')
    dir_path = os.path.join(root, f'submission_{submission_id}')
    file_path = os.path.join(dir_path, safe_name)
    if not os.path.isfile(file_path) or not os.path.abspath(file_path).startswith(os.path.abspath(dir_path)):
        abort(404)

    original_name = safe_name
    for ans in (submission.answers or []):
        for f in (ans.files or []):
            if isinstance(f, dict) and f.get('filename') == safe_name:
                original_name = f.get('original_name', safe_name)
                break
    return send_from_directory(dir_path, safe_name, as_attachment=True, download_name=original_name)


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
    
    student = get_student_by_user_id(current_user.id)
    if not student or submission.student_id != student.student_id:
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    
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
            
            assignment_task = AssignmentTask.query.filter_by(
                assignment_task_id=assignment_task_id,
                assignment_id=submission.assignment_id
            ).first()
            
            if not assignment_task:
                continue
            
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


@assignments_bp.route('/submissions/<int:submission_id>/submit-task', methods=['POST'])
@login_required
@limiter.limit("30 per minute")
def submission_submit_task(submission_id):
    """Сдача одного задания (при allow_separate_submission и attempts_per_task). Body: { "assignment_task_id": int, "value": "..." }"""
    try:
        submission = Submission.query.options(
            joinedload(Submission.assignment),
            joinedload(Submission.answers)
        ).get_or_404(submission_id)
        student = get_student_by_user_id(current_user.id)
        if not student or submission.student_id != student.student_id:
            return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
        if submission.status not in ['IN_PROGRESS', 'ASSIGNED', 'RETURNED']:
            return jsonify({'success': False, 'error': 'Работа уже сдана'}), 400
        assignment = submission.assignment
        if not assignment.allow_separate_submission or not getattr(assignment, 'attempts_per_task', False):
            return jsonify({'success': False, 'error': 'Сдача по одному заданию не разрешена для этой работы'}), 400
        if getattr(assignment, 'time_limit_strict', False) and getattr(assignment, 'time_limit_minutes', None) and getattr(submission, 'started_at', None):
            now = moscow_now()
            started_utc = _started_at_to_utc(submission.started_at)
            now_utc = now.astimezone(timezone.utc)
            limit_end_utc = started_utc + timedelta(minutes=assignment.time_limit_minutes)
            if now_utc > limit_end_utc:
                return jsonify({'success': False, 'error': 'Время на выполнение истекло. Сдача заблокирована.'}), 403
        data = request.get_json() or {}
        assignment_task_id = data.get('assignment_task_id')
        value = data.get('value', '')
        raw_time_spent_sec = data.get('time_spent_sec')
        client_time_spent_sec = None
        if raw_time_spent_sec is not None:
            try:
                client_time_spent_sec = max(0, int(float(raw_time_spent_sec)))
            except (TypeError, ValueError):
                client_time_spent_sec = None
        if not assignment_task_id:
            return jsonify({'success': False, 'error': 'Укажите assignment_task_id'}), 400
        assignment_task = AssignmentTask.query.filter_by(
            assignment_task_id=assignment_task_id,
            assignment_id=submission.assignment_id
        ).first()
        if not assignment_task:
            return jsonify({'success': False, 'error': 'Задание не найдено'}), 404
        max_for_task = assignment.get_effective_max_attempts_for_task(assignment_task)
        answer = Answer.query.filter_by(
            submission_id=submission_id,
            assignment_task_id=assignment_task_id
        ).first()
        previous_answered_at = None
        if answer:
            previous_answered_at = answer.submitted_separately_at or answer.updated_at
        if not answer:
            answer = Answer(
                submission_id=submission_id,
                assignment_task_id=assignment_task_id,
                max_score=assignment_task.max_score
            )
            db.session.add(answer)
        if answer.attempts_used >= max_for_task:
            return jsonify({'success': False, 'error': f'Попытки по этому заданию исчерпаны ({answer.attempts_used}/{max_for_task})'}), 403
        answer.value = value
        answer.attempts_used = (answer.attempts_used or 0) + 1
        answer.submitted_separately_at = moscow_now()
        answer.updated_at = moscow_now()
        db.session.flush()
        server_time_spent_sec = _resolve_answer_time_spent_sec(
            submission,
            answer.submitted_separately_at,
            previous_answered_at=previous_answered_at,
        )
        # Анти-абуз: клиентское время используем только как диагностику, доверяем серверному окну.
        time_spent_sec = max(0, int(server_time_spent_sec or 0))
        if client_time_spent_sec is not None and abs(int(client_time_spent_sec) - time_spent_sec) > 30:
            logger.info(
                "submit_task time_spent mismatch: submission_id=%s assignment_task_id=%s client=%s server=%s",
                submission_id,
                assignment_task_id,
                client_time_spent_sec,
                time_spent_sec,
            )
        is_correct, score = auto_grade_answer(answer, assignment_task)
        if is_correct is not None:
            answer.is_correct = is_correct
            answer.score = score if score is not None else (assignment_task.max_score if is_correct else 0)
            try:
                from app.analytics import AnalyticsEngine
                details = AnalyticsEngine.process_submission_details(
                    user_id=current_user.id,
                    task_id=assignment_task.task.task_id,
                    is_correct=is_correct,
                    time_spent_sec=time_spent_sec,
                    submission_id=submission_id,
                    answer_id=answer.answer_id,
                    attempt_no=max(1, int(answer.attempts_used or 1)),
                    mode='homework_manual',
                )
            except Exception as anal_err:
                logger.warning("Analytics process_submission (submit_task) failed: %s", anal_err)
                details = None
        if submission.status in ['ASSIGNED', 'RETURNED']:
            submission.status = 'IN_PROGRESS'
            if not submission.started_at:
                submission.started_at = moscow_now()
        db.session.commit()
        return jsonify({
            'success': True,
            'submitted_separately_at': answer.submitted_separately_at.isoformat(),
            'is_correct': answer.is_correct,
            'score': answer.score,
            'max_score': assignment_task.max_score,
            'time_spent_sec_used': time_spent_sec,
            'attempts_used': answer.attempts_used,
            'max_attempts': max_for_task,
            'rating_meta': details,
        }), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in submission_submit_task: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@assignments_bp.route('/submissions/<int:submission_id>/submit', methods=['POST'])
@login_required
@limiter.limit("10 per minute")
def submission_submit(submission_id):
    """Финальная сдача работы"""
    try:
        submission = Submission.query.options(
            joinedload(Submission.assignment).joinedload(Assignment.tasks).joinedload(AssignmentTask.task),
            joinedload(Submission.answers)
        ).get_or_404(submission_id)
        
        student = get_student_by_user_id(current_user.id)
        if not student or submission.student_id != student.student_id:
            return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
        
        if submission.status not in ['IN_PROGRESS', 'ASSIGNED', 'RETURNED']:
            return jsonify({'success': False, 'error': 'Работа уже сдана'}), 400
        
        assignment = submission.assignment
        now = moscow_now()
        deadline = _ensure_aware_datetime(assignment.deadline)
        
        all_attempts = submission.attempts or []
        attempts_used = sum(1 for a in all_attempts if getattr(a, 'status', '') == 'SUBMITTED')
        effective_max = assignment.get_effective_max_attempts()
        attempts_per_task = getattr(assignment, 'attempts_per_task', False)
        if not attempts_per_task and attempts_used >= effective_max and submission.status != 'RETURNED':
            return jsonify({'success': False, 'error': f'Исчерпан лимит попыток ({attempts_used}/{effective_max})'}), 403
        
        is_late = deadline and now > deadline
        if is_late and assignment.hard_deadline:
            return jsonify({'success': False, 'error': 'Дедлайн истек, сдача невозможна'}), 403
        
        is_overtime = False
        if assignment.time_limit_minutes and submission.started_at:
            started_utc = _started_at_to_utc(submission.started_at)
            now_utc = now.astimezone(timezone.utc)
            limit_end_utc = started_utc + timedelta(minutes=assignment.time_limit_minutes)
            if now_utc > limit_end_utc:
                if assignment.time_limit_strict:
                    return jsonify({'success': False, 'error': 'Время на выполнение истекло. Сдача заблокирована.'}), 403
                is_overtime = True
        submission.status = 'SUBMITTED'
        submission.submitted_at = now
        submission.is_late = is_late
        submission.is_overtime = is_overtime
        
        all_auto_graded = True
        total_score = 0
        max_score = 0
        
        for assignment_task in assignment.tasks:
            max_score += assignment_task.max_score
            
            answer = next((a for a in submission.answers if a.assignment_task_id == assignment_task.assignment_task_id), None)
            previous_answered_at = None
            was_submitted_separately = bool(getattr(answer, 'submitted_separately_at', None)) if answer else False
            
            if not answer:
                if not assignment_task.requires_manual_grading:
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
            
            if attempts_per_task:
                max_for_task = assignment.get_effective_max_attempts_for_task(assignment_task)
                if (not was_submitted_separately) and (answer.attempts_used or 0) < max_for_task and answer.value:
                    previous_answered_at = answer.submitted_separately_at or answer.updated_at
                    answer.attempts_used = (answer.attempts_used or 0) + 1
                    answer.submitted_separately_at = now
            
            if not assignment_task.requires_manual_grading:
                is_correct, score = auto_grade_answer(answer, assignment_task)
                if is_correct is not None:
                    answer.is_correct = is_correct
                    answer.score = score
                    total_score += score
                    try:
                        # Если задание уже было сдано отдельно, MMR уже начислен в submit_task.
                        # На финальной сдаче не дублируем начисление.
                        if not was_submitted_separately:
                            from app.analytics import AnalyticsEngine
                            answer_time_spent_sec = _resolve_answer_time_spent_sec(
                                submission,
                                answer.submitted_separately_at or now,
                                previous_answered_at=previous_answered_at,
                            )
                            AnalyticsEngine.process_submission(
                                user_id=current_user.id,
                                task_id=assignment_task.task.task_id,
                                is_correct=is_correct,
                                time_spent_sec=answer_time_spent_sec,
                                submission_id=submission_id,
                                answer_id=answer.answer_id,
                                attempt_no=max(1, int(answer.attempts_used or 1)),
                                mode='homework_manual',
                            )
                    except Exception as anal_err:
                        logger.warning("Analytics process_submission failed: %s", anal_err)
                else:
                    all_auto_graded = False
            else:
                all_auto_graded = False
        
        submission.total_score = total_score
        submission.max_score = max_score
        submission.percentage = (total_score / max_score * 100) if max_score > 0 else 0
        
        if all_auto_graded:
            if _assignment_has_manual_review_tasks(assignment):
                submission.status = 'NEEDS_MANUAL_REVIEW'
            else:
                submission.status = 'GRADED'
                _upsert_gradebook_from_submission(submission, actor_user_id=current_user.id)
            submission.graded_at = now

        try:
            _record_submission_attempt(submission)
        except Exception as e:
            logger.warning(f"Could not record SubmissionAttempt for {submission.submission_id}: {e}")
        
        db.session.commit()

        try:
            from app.telegram.notifications import on_submission_status_changed
            on_submission_status_changed(submission)
        except Exception:
            logger.warning('on_submission_status_changed after submission_submit failed', exc_info=True)

        creator_id = getattr(assignment, 'created_by_id', None) or (assignment.created_by.id if getattr(assignment, 'created_by', None) else None)
        if creator_id and assignment.created_by_id:
            student_name = getattr(submission.student, 'name', None) or 'Ученик'
            notify_user(
                assignment.created_by_id,
                kind='teacher_homework_submitted',
                title='📤 Ученик сдал работу',
                body=f'{student_name} сдал(а) работу «{assignment.title}»',
                link_url=url_for('assignments.submission_view', submission_id=submission_id) if current_app else None,
                meta={'submission_id': submission_id, 'assignment_id': assignment.assignment_id, 'student_id': submission.student_id}
            )
        
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
    
    except Exception as e:
        logger.error(f"Error in submission_submit for submission {submission_id}: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Ошибка при сдаче работы: {str(e)}'}), 500


def _collect_sandbox_files(task_id: int | None, user_id: int) -> list[tuple[str, bytes]]:
    """Collect task attachment files + student workspace files for sandbox execution.

    Returns list of (filename, bytes) tuples.  Reads at most 20 files,
    each capped at 10 MB to prevent abuse.
    """
    MAX_SANDBOX_FILES = 20
    MAX_FILE_SIZE = 10 * 1024 * 1024
    result: list[tuple[str, bytes]] = []
    seen_names: set[str] = set()

    if task_id:
        try:
            task = Tasks.query.filter_by(task_id=task_id).first()
            if task and task.attached_files:
                files_list = json.loads(task.attached_files) if isinstance(task.attached_files, str) else task.attached_files
                if isinstance(files_list, list):
                    from app.workspace.routes import _read_task_attachment_bytes
                    for fmeta in files_list[:MAX_SANDBOX_FILES]:
                        fname = (fmeta.get('file_name') or fmeta.get('name') or '').strip()
                        if not fname or fname in seen_names:
                            continue
                        fpath = fmeta.get('file_path') or ''
                        furl = fmeta.get('file_url') or fmeta.get('url') or ''
                        try:
                            fbytes = _read_task_attachment_bytes(task_id, fpath, furl, fname)
                            if fbytes and len(fbytes) <= MAX_FILE_SIZE:
                                result.append((fname, fbytes))
                                seen_names.add(fname)
                        except Exception:
                            pass
        except Exception:
            logger.debug("_collect_sandbox_files: could not load task attachments for task_id=%s", task_id, exc_info=True)

    if task_id and len(result) < MAX_SANDBOX_FILES:
        try:
            from core.db_models import StudentWorkspaceFile
            from app.workspace.routes import _read_file_bytes
            ws_files = StudentWorkspaceFile.query.filter_by(
                user_id=user_id, task_id=task_id,
            ).limit(MAX_SANDBOX_FILES - len(result)).all()
            for wf in ws_files:
                fname = wf.current_filename
                if not fname or fname in seen_names:
                    continue
                try:
                    fbytes = _read_file_bytes(wf)
                    if fbytes and len(fbytes) <= MAX_FILE_SIZE:
                        result.append((fname, fbytes))
                        seen_names.add(fname)
                except Exception:
                    pass
        except Exception:
            logger.debug("_collect_sandbox_files: could not load workspace files", exc_info=True)

    return result


def _run_python_sandbox(code: str, timeout_sec: int = 5,
                        task_files: list[tuple[str, bytes]] | None = None):
    """Запуск кода Python в песочнице. task_files — [(filename, bytes), ...]."""
    import tempfile
    try:
        with tempfile.TemporaryDirectory(prefix='boostudy_sandbox_') as tmpdir:
            if task_files:
                for fname, fbytes in task_files:
                    fpath = os.path.join(tmpdir, fname)
                    with open(fpath, 'wb') as f:
                        f.write(fbytes)
            proc = subprocess.run(
                [sys.executable, '-c', _PYTHON_RUNNER],
                input=code,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                cwd=tmpdir,
            )
            return proc.stdout or '', proc.stderr or ''
    except subprocess.TimeoutExpired:
        return '', 'Превышено время выполнения (макс. {} с).'.format(timeout_sec)
    except Exception as e:
        return '', str(e)


@assignments_bp.route('/submissions/<int:submission_id>/run-code', methods=['POST'])
@login_required
@limiter.limit('30/minute')
def submission_run_code(submission_id):
    """Запуск кода ученика в песочнице с файлами задания доступными через open()."""
    submission = Submission.query.filter_by(submission_id=submission_id).first_or_404()
    student = get_student_by_user_id(current_user.id)
    is_owner = student and student.student_id == submission.student_id
    scope = get_user_scope(current_user)
    can_see = scope.get('can_see_all') or (getattr(current_user, 'is_teacher', lambda: False)() or getattr(current_user, 'is_admin', lambda: False)())
    if not is_owner and not can_see:
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    data = request.get_json() or {}
    code = (data.get('code') or '').strip()
    assignment_task_id = data.get('assignment_task_id')
    if not code:
        return jsonify({'success': False, 'error': 'Код не передан'}), 400
    assignment = submission.assignment
    at = None
    if assignment_task_id is not None:
        at = next((t for t in (assignment.tasks or []) if t.assignment_task_id == assignment_task_id), None)
        if not at:
            return jsonify({'success': False, 'error': 'Задание не найдено'}), 400

    task_files = _collect_sandbox_files(
        task_id=at.task_id if at else None,
        user_id=current_user.id,
    )
    stdout, stderr = _run_python_sandbox(code, task_files=task_files)
    return jsonify({'success': True, 'stdout': stdout, 'stderr': stderr})


@assignments_bp.route('/submissions/<int:submission_id>/save-code', methods=['POST'])
@login_required
@limiter.limit('60/minute')
def submission_save_code(submission_id):
    """Сохранение кода ученика для задания (для проверки преподавателем)."""
    submission = Submission.query.options(
        joinedload(Submission.assignment).joinedload(Assignment.tasks),
        joinedload(Submission.answers),
    ).filter_by(submission_id=submission_id).first_or_404()
    student = get_student_by_user_id(current_user.id)
    if not student or student.student_id != submission.student_id:
        return jsonify({'success': False, 'error': 'Только автор сдачи может сохранять код'}), 403
    data = request.get_json() or {}
    code = (data.get('code') or '').strip()
    assignment_task_id = data.get('assignment_task_id')
    if assignment_task_id is None:
        return jsonify({'success': False, 'error': 'Не указано задание'}), 400
    assignment = submission.assignment
    at = next((t for t in (assignment.tasks or []) if t.assignment_task_id == int(assignment_task_id)), None)
    if not at:
        return jsonify({'success': False, 'error': 'Задание не найдено'}), 400
    answer = next((a for a in (submission.answers or []) if a.assignment_task_id == at.assignment_task_id), None)
    if not answer:
        answer = Answer(
            submission_id=submission_id,
            assignment_task_id=at.assignment_task_id,
            max_score=at.max_score,
        )
        db.session.add(answer)
    answer.student_code = code[: 100_000]
    answer.student_code_saved_at = moscow_now()
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify({'success': True, 'saved_at': answer.student_code_saved_at.isoformat()})


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
        joinedload(Submission.attempts),
        joinedload(Submission.student),
        joinedload(Submission.comments).joinedload(SubmissionComment.author)
    ).get_or_404(submission_id)
    
    assignment = submission.assignment
    
    scope = get_user_scope(current_user)
    if not scope['can_see_all'] and assignment.created_by_id != current_user.id:
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('assignments.assignments_list'))
    
    now = moscow_now()
    display_status_label = _submission_display_status(submission, assignment, now)
    display_status_class = ''
    if display_status_label == 'Просрочено по таймеру':
        display_status_class = 'status-overdue-timer'
    elif display_status_label == 'Просрочено по дедлайну':
        display_status_class = 'status-overdue-deadline'
    attempts_used = len(submission.attempts or [])
    try:
        effective_max_attempts = assignment.get_effective_max_attempts()
    except Exception:
        effective_max_attempts = 1
    attempts_left = max(0, effective_max_attempts - attempts_used)
    attempts_per_task = getattr(assignment, 'attempts_per_task', False)

    events = (
        AnalyticsEvent.query
        .filter(AnalyticsEvent.submission_id == submission_id)
        .order_by(AnalyticsEvent.id.desc())
        .all()
    )
    event_by_answer: dict[int, AnalyticsEvent] = {}
    event_by_task: dict[int, AnalyticsEvent] = {}
    for ev in events:
        if ev.answer_id and ev.answer_id not in event_by_answer:
            event_by_answer[int(ev.answer_id)] = ev
        if ev.task_id and ev.task_id not in event_by_task:
            event_by_task[int(ev.task_id)] = ev

    tasks_data = []
    for assignment_task in sorted(assignment.tasks or [], key=lambda t: getattr(t, 'order_index', 0)):
        if getattr(assignment_task, 'task', None) is None:
            continue
        answer = next((a for a in (submission.answers or []) if a.assignment_task_id == assignment_task.assignment_task_id), None)
        try:
            max_for_task = assignment.get_effective_max_attempts_for_task(assignment_task) if attempts_per_task else 1
        except Exception:
            max_for_task = 1
        task_attempts_used = (getattr(answer, 'attempts_used', None) or 0) if answer else 0
        diff_level = getattr(assignment_task, 'difficulty_level', None)
        if diff_level is None and assignment_task.task is not None:
            diff_level = getattr(assignment_task.task, 'difficulty_level', None)
        difficulty_label = 'Стандарт'
        if diff_level == 1:
            difficulty_label = 'База'
        elif diff_level == 3:
            difficulty_label = 'Хард'
        ev = None
        if answer and getattr(answer, 'answer_id', None):
            ev = event_by_answer.get(int(answer.answer_id))
        if ev is None and assignment_task.task and getattr(assignment_task.task, 'task_id', None):
            ev = event_by_task.get(int(assignment_task.task.task_id))
        flags = (ev.behavior_flags or {}) if ev else {}
        rating_meta = None
        if ev:
            rating_meta = {
                'mmr_delta': float(ev.mmr_delta or 0.0),
                'new_rating': float(ev.new_rating) if ev.new_rating is not None else None,
                'difficulty_label': flags.get('difficulty_label') or (
                    'База' if ev.task_difficulty == 1 else ('Хард' if ev.task_difficulty == 3 else 'Стандарт')
                ),
                'time_coeff': flags.get('time_coeff'),
                'attempt_coeff': flags.get('attempt_coeff'),
                'time_spent_sec': ev.time_spent_sec,
                'time_band': flags.get('time_band'),
            }
        tasks_data.append({
            'assignment_task': assignment_task,
            'task': assignment_task.task,
            'answer': answer,
            'max_attempts_for_task': max_for_task,
            'task_attempts_used': task_attempts_used,
            'rating_meta': rating_meta,
            'difficulty_label': difficulty_label,
        })

    tasks_view = []
    i = 0
    while i < len(tasks_data):
        item = tasks_data[i]
        item_task = item.get('task')
        item_num = getattr(item_task, 'task_number', None) if item_task else None
        item_group = getattr(item_task, 'task_group_id', None) if item_task else None

        can_bundle = i + 2 < len(tasks_data)
        if item_num == 19 and can_bundle:
            next_20 = tasks_data[i + 1]
            next_21 = tasks_data[i + 2]
            task_20 = next_20.get('task')
            task_21 = next_21.get('task')
            num_20 = getattr(task_20, 'task_number', None) if task_20 else None
            num_21 = getattr(task_21, 'task_number', None) if task_21 else None
            group_20 = getattr(task_20, 'task_group_id', None) if task_20 else None
            group_21 = getattr(task_21, 'task_group_id', None) if task_21 else None

            same_group = bool(item_group and group_20 and group_21 and item_group == group_20 == group_21)
            legacy_consecutive = (num_20 == 20 and num_21 == 21)

            if (num_20 == 20 and num_21 == 21) and (same_group or legacy_consecutive):
                root_item = dict(item)
                root_item['is_triplet_19_21'] = True
                root_item['triplet_items'] = [next_20, next_21]
                tasks_view.append(root_item)
                i += 3
                continue

        single_item = dict(item)
        single_item['is_triplet_19_21'] = False
        single_item['triplet_items'] = []
        tasks_view.append(single_item)
        i += 1

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

    can_submit_grade = submission.status in ('SUBMITTED', 'GRADED', 'RETURNED', 'NEEDS_MANUAL_REVIEW')
    initial_task_id = (tasks_view[0]['assignment_task'].assignment_task_id if tasks_view else None)
    unread_task_ids: set[int] = set()
    latest_teacher_comment_by_task: dict[int, datetime] = {}
    for c in sorted((submission.comments or []), key=lambda x: (x.created_at or moscow_now(), x.comment_id or 0)):
        task_id = int(c.assignment_task_id or (initial_task_id or 0))
        if task_id <= 0:
            continue
        if c.author_id == current_user.id:
            latest_teacher_comment_by_task[task_id] = c.created_at
            continue
        latest_teacher = latest_teacher_comment_by_task.get(task_id)
        if latest_teacher is None or (c.created_at and c.created_at > latest_teacher):
            unread_task_ids.add(task_id)
    return render_template('submission_grade.html',
                         submission=submission,
                         assignment=assignment,
                         tasks_data=tasks_data,
                         tasks_view=tasks_view,
                         rubric_template=rubric_template,
                         rubric_templates=rubric_templates,
                         display_status_label=display_status_label,
                         display_status_class=display_status_class,
                         attempts_used=attempts_used,
                         effective_max_attempts=effective_max_attempts,
                         attempts_left=attempts_left,
                         attempts_per_task=attempts_per_task,
                         can_submit_grade=can_submit_grade,
                         initial_task_id=initial_task_id,
                         unread_task_ids=sorted(unread_task_ids))


@assignments_bp.route('/submissions/<int:submission_id>/save-comments', methods=['POST'])
@login_required
@check_access('assignment.grade')
def submission_save_comments(submission_id):
    """
    Сохранение только комментариев к заданиям (и общего комментария) без завершения проверки.
    Ученик увидит комментарии при выполнении работы.
    Body: {
        "comments": [ {"assignment_task_id": 1, "teacher_comment": "..."}, ... ],
        "teacher_feedback": "Общий комментарий (необязательно)"
    }
    """
    if current_user.is_student() or current_user.is_parent():
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    submission = Submission.query.options(
        joinedload(Submission.assignment).joinedload(Assignment.tasks).joinedload(AssignmentTask.task),
        joinedload(Submission.answers),
    ).get_or_404(submission_id)
    assignment = submission.assignment
    if not assignment:
        return jsonify({'success': False, 'error': 'Работа не найдена'}), 404
    scope = get_user_scope(current_user)
    if not scope['can_see_all'] and assignment.created_by_id != current_user.id:
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    try:
        data = request.get_json() or {}
        comments_data = data.get('comments', [])
        teacher_feedback = (data.get('teacher_feedback') or '').strip()

        for item in comments_data:
            assignment_task_id = item.get('assignment_task_id')
            teacher_comment = (item.get('teacher_comment') or '').strip()
            if assignment_task_id is None:
                continue
            assignment_task = next(
                (t for t in (assignment.tasks or []) if t.assignment_task_id == int(assignment_task_id)),
                None
            )
            if not assignment_task:
                continue
            answer = next(
                (a for a in (submission.answers or []) if a.assignment_task_id == assignment_task.assignment_task_id),
                None
            )
            if not answer:
                answer = Answer(
                    submission_id=submission_id,
                    assignment_task_id=assignment_task.assignment_task_id,
                    max_score=assignment_task.max_score,
                )
                db.session.add(answer)
            answer.teacher_comment = teacher_comment or None

        submission.teacher_feedback = teacher_feedback or None
        db.session.commit()
        return jsonify({'success': True}), 200
    except Exception as e:
        logger.error(f"Error in submission_save_comments for submission {submission_id}: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


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
        joinedload(Submission.assignment).joinedload(Assignment.tasks).joinedload(AssignmentTask.task),
        joinedload(Submission.answers),
        joinedload(Submission.student),
    ).get_or_404(submission_id)
    
    assignment = submission.assignment
    
    scope = get_user_scope(current_user)
    if not scope['can_see_all'] and assignment.created_by_id != current_user.id:
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    
    # Разрешаем сохранять оценку и при IN_PROGRESS/ASSIGNED (таймер истёк, ученик не нажал «Сдать» — преподаватель может завершить проверку)
    if submission.status not in ('SUBMITTED', 'GRADED', 'RETURNED', 'IN_PROGRESS', 'ASSIGNED', 'NEEDS_MANUAL_REVIEW'):
        return jsonify({'success': False, 'error': 'Нельзя изменить оценку для этой сдачи'}), 400

    try:
        data = request.get_json()
        scores_data = data.get('scores', [])
        teacher_feedback = data.get('teacher_feedback', '').strip()
        status = data.get('status', 'GRADED')  # GRADED или RETURNED
        rubric_template_id = data.get('rubric_template_id', None)
        rubric_scores = data.get('rubric_scores', None)
        new_deadline_str = (data.get('new_deadline') or '').strip()  # при RETURNED — опционально новый дедлайн
        new_max_attempts = data.get('new_max_attempts')  # при RETURNED — опционально новое число попыток (int)

        if status not in ['GRADED', 'RETURNED']:
            status = 'GRADED'
        
        total_score = 0
        max_score = 0
        
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
        
        submission.total_score = total_score
        submission.max_score = max_score
        submission.percentage = (total_score / max_score * 100) if max_score > 0 else 0
        submission.teacher_feedback = teacher_feedback

        try:
            selected_rubric = None
            if rubric_template_id is not None and str(rubric_template_id).strip() != '':
                rid = int(rubric_template_id)
                q = RubricTemplate.query.filter_by(rubric_id=rid, is_active=True)
                if not _can_manage_all_rubrics():
                    q = q.filter(RubricTemplate.owner_user_id == current_user.id)
                selected_rubric = q.first()
            if not selected_rubric and assignment.rubric_template_id:
                selected_rubric = RubricTemplate.query.filter_by(rubric_id=assignment.rubric_template_id, is_active=True).first()

            if selected_rubric:
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
        # Если ученик не нажал «Сдать» (таймер истёк и т.п.), при завершении проверки фиксируем дату закрытия
        if submission.submitted_at is None:
            submission.submitted_at = moscow_now()

        # При возврате на доработку — опционально обновляем дедлайн и/или число попыток работы
        if status == 'RETURNED':
            if new_deadline_str:
                try:
                    deadline_dt = datetime.fromisoformat(new_deadline_str.replace('Z', '+00:00'))
                    if deadline_dt.tzinfo is None:
                        deadline_dt = deadline_dt.replace(tzinfo=MOSCOW_TZ)
                    deadline_dt = deadline_dt.astimezone(MOSCOW_TZ).replace(tzinfo=None)
                    assignment.deadline = deadline_dt
                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid new_deadline for submission {submission_id}: {e}")
            if new_max_attempts is not None:
                try:
                    n = int(new_max_attempts)
                    if n >= 1:
                        assignment.max_attempts_default = n
                except (ValueError, TypeError):
                    pass

        if status == 'GRADED':
            _upsert_gradebook_from_submission(submission, actor_user_id=current_user.id)
        try:
            _record_submission_attempt(submission)
        except Exception as e:
            logger.warning(f"Could not record SubmissionAttempt (grade) for {submission.submission_id}: {e}")

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

        user_id = submission.student.user_id if submission.student else None
        if user_id:
            task_by_at_id = {at.assignment_task_id: at for at in assignment.tasks}
            for answer in submission.answers:
                at = task_by_at_id.get(answer.assignment_task_id)
                if not at or not at.task:
                    continue
                is_correct = (answer.score or 0) >= (at.max_score or 1)
                try:
                    from app.analytics import AnalyticsEngine
                    answer_time_spent_sec = _resolve_answer_time_spent_sec(
                        submission,
                        answer.submitted_separately_at or submission.graded_at or moscow_now(),
                    )
                    AnalyticsEngine.process_submission(
                        user_id=user_id,
                        task_id=at.task.task_id,
                        is_correct=is_correct,
                        time_spent_sec=answer_time_spent_sec,
                        submission_id=submission_id,
                        answer_id=answer.answer_id,
                        attempt_no=max(1, int(answer.attempts_used or 1)),
                        mode='homework_manual',
                    )
                except Exception as anal_err:
                    logger.warning("Analytics process_submission (grade_save) failed: %s", anal_err)
        
        db.session.commit()

        try:
            from app.telegram.notifications import on_submission_status_changed
            on_submission_status_changed(submission)
        except Exception:
            logger.warning('on_submission_status_changed after grade_save failed', exc_info=True)
        
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
    
    scope = get_user_scope(current_user)
    student = get_student_by_user_id(current_user.id)
    
    is_author = student and submission.student_id == student.student_id
    is_teacher = scope['can_see_all'] or submission.assignment.created_by_id == current_user.id
    
    if not (is_author or is_teacher):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
        
    try:
        data = request.get_json() or {}
        text = (data.get('text') or '').strip()
        assignment_task_id = data.get('assignment_task_id')
        
        if not text:
            return jsonify({'success': False, 'error': 'Текст комментария обязателен'}), 400
        if assignment_task_id is None:
            return jsonify({'success': False, 'error': 'Укажите assignment_task_id'}), 400
        try:
            assignment_task_id = int(assignment_task_id)
        except Exception:
            return jsonify({'success': False, 'error': 'Некорректный assignment_task_id'}), 400
        if not any(t.assignment_task_id == assignment_task_id for t in (submission.assignment.tasks or [])):
            return jsonify({'success': False, 'error': 'Задание не принадлежит этой работе'}), 400
            
        comment = SubmissionComment(
            submission_id=submission.submission_id,
            author_id=current_user.id,
            assignment_task_id=assignment_task_id,
            text=text,
            created_at=moscow_now()
        )
        db.session.add(comment)
        db.session.commit()
        
        author_name = current_user.username
        if current_user.profile:
            author_name = f"{current_user.profile.first_name or ''} {current_user.profile.last_name or ''}".strip() or current_user.username
            
        return jsonify({
            'success': True,
            'comment': {
                'id': comment.comment_id,
                'text': comment.text,
                'created_at': comment.created_at.isoformat(),
                'assignment_task_id': comment.assignment_task_id,
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


@assignments_bp.route('/submissions/<int:submission_id>/comments', methods=['GET'])
@login_required
def submission_comments_list(submission_id):
    """Список комментариев к сдаче (для чата без перезагрузки)."""
    submission = Submission.query.options(
        joinedload(Submission.comments).joinedload(SubmissionComment.author),
        joinedload(Submission.assignment),
    ).get_or_404(submission_id)

    scope = get_user_scope(current_user)
    student = get_student_by_user_id(current_user.id)

    is_author = student and submission.student_id == student.student_id
    is_teacher = scope['can_see_all'] or submission.assignment.created_by_id == current_user.id

    if not (is_author or is_teacher):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    assignment_task_id = request.args.get('assignment_task_id', type=int)
    if assignment_task_id is None:
        first_at = sorted((submission.assignment.tasks or []), key=lambda t: (getattr(t, 'order_index', 0), t.assignment_task_id))
        assignment_task_id = first_at[0].assignment_task_id if first_at else None
    if assignment_task_id is not None and not any(t.assignment_task_id == assignment_task_id for t in (submission.assignment.tasks or [])):
        return jsonify({'success': False, 'error': 'Задание не принадлежит этой работе'}), 400

    comments = []
    latest_teacher_by_task: dict[int, datetime] = {}
    unread_task_ids: set[int] = set()
    ordered = sorted((submission.comments or []), key=lambda c: (c.created_at or moscow_now(), c.comment_id or 0))
    for comment in ordered:
        comment_task_id = int(comment.assignment_task_id or (assignment_task_id or 0))
        if comment_task_id <= 0:
            continue
        if comment.author_id == current_user.id:
            latest_teacher_by_task[comment_task_id] = comment.created_at
        else:
            last_teacher = latest_teacher_by_task.get(comment_task_id)
            if last_teacher is None or (comment.created_at and comment.created_at > last_teacher):
                unread_task_ids.add(comment_task_id)

        if assignment_task_id is not None and comment_task_id != assignment_task_id:
            continue
        author_name = (comment.author.username if comment.author else f'User {comment.author_id}')
        if comment.author and comment.author.profile:
            author_name = (
                f"{comment.author.profile.first_name or ''} {comment.author.profile.last_name or ''}".strip()
                or comment.author.username
            )
        comments.append({
            'id': comment.comment_id,
            'text': comment.text or '',
            'created_at': comment.created_at.isoformat() if comment.created_at else None,
            'created_human': comment.created_at.strftime('%d.%m.%Y %H:%M') if comment.created_at else '',
            'assignment_task_id': comment_task_id,
            'author': {
                'id': comment.author_id,
                'name': author_name,
                'avatar_url': comment.author.avatar_url if comment.author else None,
            },
            'is_mine': comment.author_id == current_user.id,
        })

    return jsonify({
        'success': True,
        'comments': comments,
        'assignment_task_id': assignment_task_id,
        'unread_task_ids': sorted(unread_task_ids),
        'has_unread_student_comment': assignment_task_id in unread_task_ids if assignment_task_id is not None else False,
    }), 200
