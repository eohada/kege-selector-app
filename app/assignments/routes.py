"""
Маршруты для системы заданий и сдачи работ
"""
import logging
from datetime import datetime, timedelta, timezone
from flask import render_template, request, jsonify, flash, redirect, url_for, current_app, session
from flask_login import login_required, current_user
from sqlalchemy import and_, or_, func, case
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError

from app.assignments import assignments_bp
from app.limiter import limiter
from app.models import (
    db, Assignment, AssignmentTask, Submission, Answer,
    Student, User, Tasks, Lesson, LessonTask, Enrollment, GradebookEntry, SubmissionAttempt, RubricTemplate,
    TaskTemplate, TemplateTask, CourseTaskTemplate, GroupStudent, AnalyticsEvent, Course
)
from app.students.utils import get_sorted_assignments
from core.db_models import SubmissionComment, SubmissionCommentThreadRead, MOSCOW_TZ
from app.auth.rbac_utils import check_access, get_user_scope, has_permission
from core.db_models import utc_now
from app.utils.datetime_utc import deadline_from_form_to_utc, effective_timezone_name
from app.utils.relationship_scope import can_user_access_student
from core.audit_logger import audit_logger
from app.notifications.service import notify_student_and_parents, notify_user, build_task_number_summary, build_task_number_counts
from app.telegram.user_notify import notify_user_by_id
from core.selector_logic import get_accepted_tasks, get_skipped_tasks, get_unique_tasks, get_task_ids_in_assignments_for_students, reset_history, reset_skipped
from app.utils.course_tasks import get_task_numbers
from app.utils.jinja_filters import normalize_task_content_assets, normalize_task_content_urls
from app.lessons.utils import normalize_answer_value
from app.assignments.submission_lifecycle_service import (
    normalize_legacy_status,
    transition_submission_status,
    SubmissionLifecycleError,
)
from app.sandbox.python_runner import normalize_leading_tabs_to_spaces, run_python_sandbox
import requests
from flask import Response, stream_with_context, abort, send_from_directory
from werkzeug.utils import secure_filename
import json
import subprocess
import sys
import os
import time
import random
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Локальный флаг: таблица курсоров прочтения чата создана в этой БД (create checkfirst).
_THREAD_READ_SCHEMA_ENSURED = False


def _agent_debug_log(hypothesis_id: str, message: str, data: dict | None = None, run_id: str = 'run1') -> None:
    try:
        payload = {
            'sessionId': '14a550',
            'runId': run_id,
            'hypothesisId': hypothesis_id,
            'location': 'app/assignments/routes.py',
            'message': message,
            'data': data or {},
            'timestamp': int(time.time() * 1000),
        }
        with open('debug-14a550.log', 'a', encoding='utf-8') as f:
            f.write(json.dumps(payload, ensure_ascii=False) + '\n')
    except Exception:
        pass


def _ensure_submission_comment_thread_reads_schema() -> bool:
    """Создать таблицу SubmissionCommentThreadReads при отсутствии (без отдельного Alembic)."""
    global _THREAD_READ_SCHEMA_ENSURED
    if _THREAD_READ_SCHEMA_ENSURED:
        return True
    try:
        SubmissionCommentThreadRead.__table__.create(db.engine, checkfirst=True)
        _THREAD_READ_SCHEMA_ENSURED = True
        return True
    except Exception as e:
        logger.warning('Could not ensure SubmissionCommentThreadReads table: %s', e)
        return False


def _ensure_aware_datetime(dt):
    """Нормализует datetime к aware UTC для корректных сравнений дедлайнов."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        # В БД дедлайны могут храниться как UTC-naive; трактуем как UTC, чтобы избежать ложной просрочки.
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=MOSCOW_TZ).astimezone(timezone.utc)
    return dt.astimezone(timezone.utc)


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


def _datetime_for_user(dt: datetime | None, user=None) -> datetime | None:
    """Return datetime in the viewer's timezone for assignment UI."""
    if dt is None:
        return None
    try:
        zone_name = effective_timezone_name(user or current_user)
        zone = ZoneInfo(zone_name)
    except Exception:
        zone = MOSCOW_TZ
    base = _ensure_aware_datetime(dt)
    return base.astimezone(zone) if base else None


def _datetime_local_value_for_user(dt: datetime | None, user=None) -> str:
    local_dt = _datetime_for_user(dt, user)
    return local_dt.strftime('%Y-%m-%dT%H:%M') if local_dt else ''


def _display_datetime_for_user(dt: datetime | None, user=None) -> str:
    local_dt = _datetime_for_user(dt, user)
    return local_dt.strftime('%d.%m.%Y %H:%M') if local_dt else 'без дедлайна'


def _deadline_payload_to_utc(raw_value) -> datetime:
    dt = datetime.fromisoformat(str(raw_value).replace('Z', '+00:00'))
    if dt.tzinfo is None:
        try:
            dt = dt.replace(tzinfo=ZoneInfo(effective_timezone_name(current_user)))
        except Exception:
            dt = dt.replace(tzinfo=MOSCOW_TZ)
    return deadline_from_form_to_utc(dt)


def _assignment_builder_task_payload(task: Tasks, *, max_score: int = 1, requires_manual_grading: bool = False) -> dict[str, Any]:
    """Serialize a task for the V2 assignment builder without exposing legacy HTML routes."""
    return {
        'task_id': int(task.task_id),
        'task_number': int(task.task_number or 0),
        'max_score': max(1, int(max_score or 1)),
        'answer': task.answer or '',
        'source': task.source_url or getattr(task, 'kege_source_tag', None) or 'Банк задач',
        'content_html': normalize_task_content_assets(
            task.content_html or '',
            getattr(task, 'attached_files', None),
            task.source_url,
        ),
        'requires_manual_grading': bool(requires_manual_grading),
    }


def _assignment_builder_owned_draft(assignment_id: int) -> Assignment | None:
    """Return only the current user's inactive builder draft, never a published work."""
    assignment = Assignment.query.options(joinedload(Assignment.tasks).joinedload(AssignmentTask.task)).get(assignment_id)
    if not assignment or assignment.is_active:
        return None
    scope = get_user_scope(current_user)
    if not scope.get('can_see_all') and assignment.created_by_id != current_user.id:
        return None
    return assignment


def _apply_assignment_builder_payload(assignment: Assignment, data: dict[str, Any]) -> None:
    """Apply validated V2-builder fields to an inactive draft atomically."""
    assignment_type = _normalize_assignment_type(data.get('assignment_type')) or 'homework'
    raw_deadline = data.get('deadline')
    try:
        deadline = _deadline_payload_to_utc(raw_deadline) if raw_deadline else utc_now() + timedelta(days=7)
    except (TypeError, ValueError):
        deadline = utc_now() + timedelta(days=7)

    title = (data.get('title') or '').strip()
    if not title:
        title = f"{assignment_type.title()} — {_datetime_for_user(utc_now()).strftime('%d.%m.%Y')}"

    assignment.title = title[:500]
    assignment.description = (data.get('description') or '').strip() or None
    assignment.assignment_type = assignment_type
    assignment.deadline = deadline
    assignment.hard_deadline = bool(data.get('hard_deadline'))
    assignment.hide_before_start = bool(data.get('hide_before_start'))
    assignment.allow_separate_submission = bool(data.get('allow_separate_submission', True))
    assignment.time_limit_strict = bool(data.get('time_limit_strict'))
    assignment.attempts_per_task = bool(data.get('attempts_per_task'))

    raw_limit = data.get('time_limit_minutes')
    try:
        assignment.time_limit_minutes = max(1, int(raw_limit)) if str(raw_limit or '').strip() else None
    except (TypeError, ValueError):
        assignment.time_limit_minutes = None
    try:
        assignment.max_attempts_default = max(1, int(data.get('max_attempts_default') or 1))
    except (TypeError, ValueError):
        assignment.max_attempts_default = 1

    course_id = data.get('course_id')
    try:
        course = Course.query.filter_by(id=int(course_id), is_active=True).first() if course_id else None
    except (TypeError, ValueError):
        course = None
    assignment.exam_course_id = course.id if course else None

    raw_tasks = data.get('tasks') if isinstance(data.get('tasks'), list) else []
    task_rows = _expand_tasks_data_for_triplets(raw_tasks)
    task_ids = []
    normalized = []
    for index, row in enumerate(task_rows):
        try:
            task_id = int(row.get('task_id'))
        except (TypeError, ValueError, AttributeError):
            continue
        if task_id in task_ids:
            continue
        task_ids.append(task_id)
        normalized.append((
            index,
            task_id,
            max(1, int(row.get('max_score') or 1)),
            bool(row.get('requires_manual_grading')),
        ))
    existing = {row.task_id: row for row in assignment.tasks or []}
    for order_index, task_id, max_score, requires_manual_grading in normalized:
        task = Tasks.query.get(task_id)
        if not task:
            continue
        assignment_task = existing.pop(task_id, None)
        if assignment_task is None:
            assignment_task = AssignmentTask(assignment_id=assignment.assignment_id, task_id=task_id)
            db.session.add(assignment_task)
        assignment_task.order_index = order_index
        assignment_task.max_score = max_score
        assignment_task.requires_manual_grading = _requires_manual_from_template(
            task, bool((task.answer or '').strip()), explicit_override=requires_manual_grading
        )
    for removed in existing.values():
        db.session.delete(removed)


@assignments_bp.route('/assignments/api/create/tasks', methods=['GET'])
@login_required
@check_access('assignment.create')
def assignment_builder_tasks_by_ids():
    raw_ids = request.args.get('ids') or ''
    ids = [int(value) for value in raw_ids.replace(',', ' ').split() if value.isdigit()]
    ids = list(dict.fromkeys(ids))[:200]
    if not ids:
        return jsonify({'success': False, 'message': 'Укажите хотя бы один корректный ID задачи'}), 400
    tasks_by_id = {task.task_id: task for task in Tasks.query.filter(Tasks.task_id.in_(ids)).all()}
    return jsonify({'success': True, 'tasks': [_assignment_builder_task_payload(tasks_by_id[task_id]) for task_id in ids if task_id in tasks_by_id]})


@assignments_bp.route('/assignments/api/create/probnik', methods=['GET'])
@login_required
@check_access('assignment.create')
def assignment_builder_probnik():
    course_id = request.args.get('course_id', type=int)
    if not course_id or not Course.query.filter_by(id=course_id, is_active=True).first():
        return jsonify({'success': False, 'message': 'Выберите активный курс для пробника'}), 400
    tasks = _pick_probnik_tasks_one_per_exam_number(course_id, random_mode=True)
    return jsonify({'success': True, 'tasks': [_assignment_builder_task_payload(task) for task in tasks]})


@assignments_bp.route('/assignments/api/create/templates/<int:template_id>', methods=['GET'])
@login_required
@check_access('assignment.create')
def assignment_builder_template_tasks(template_id: int):
    template = TaskTemplate.query.options(joinedload(TaskTemplate.template_tasks).joinedload(TemplateTask.task)).get_or_404(template_id)
    if not template.is_active:
        return jsonify({'success': False, 'message': 'Этот шаблон больше недоступен'}), 404
    rows = sorted(template.template_tasks or [], key=lambda row: (row.order or 0, row.template_task_id))
    return jsonify({'success': True, 'tasks': [_assignment_builder_task_payload(row.task) for row in rows if row.task]})


@assignments_bp.route('/assignments/api/create/draft', methods=['POST'])
@login_required
@check_access('assignment.create')
def assignment_builder_save_draft():
    data = request.get_json(silent=True) or {}
    try:
        draft_id = data.get('assignment_id')
        draft = _assignment_builder_owned_draft(int(draft_id)) if draft_id else None
        if draft_id and draft is None:
            return jsonify({'success': False, 'message': 'Черновик не найден или недоступен'}), 404
        if draft is None:
            draft = Assignment(
                title='Черновик работы', assignment_type='homework', deadline=utc_now() + timedelta(days=7),
                created_by_id=current_user.id, is_active=False,
            )
            db.session.add(draft)
            db.session.flush()
        _apply_assignment_builder_payload(draft, data)
        db.session.commit()
        return jsonify({'success': True, 'assignment_id': draft.assignment_id, 'message': 'Черновик сохранён'})
    except Exception as exc:
        db.session.rollback()
        logger.exception('Assignment V2 draft save failed')
        return jsonify({'success': False, 'message': f'Не удалось сохранить черновик: {exc}'}), 500


def _is_revision_status(submission: Submission) -> bool:
    return normalize_legacy_status(getattr(submission, 'status', None)) == 'RETURNED'


def _mark_submission_returned_for_revision(submission: Submission) -> None:
    """
    Возврат на доработку открывает новый учебный заход.
    Старый started_at не должен дальше блокировать таймером редактор и сдачу.
    """
    transition_submission_status(submission, 'RETURNED', force=True)
    submission.started_at = None
    submission.is_overtime = False


def _submission_deadline_passed(assignment: Assignment, now: datetime | None = None) -> bool:
    deadline = _ensure_aware_datetime(getattr(assignment, 'deadline', None))
    return bool(deadline and (now or utc_now()) > deadline)


def _submission_hard_deadline_blocks(submission: Submission, assignment: Assignment, now: datetime | None = None) -> bool:
    if _is_revision_status(submission):
        return False
    return bool(getattr(assignment, 'hard_deadline', False) and _submission_deadline_passed(assignment, now))


def _submission_timer_expired(submission: Submission, assignment: Assignment, now: datetime | None = None) -> bool:
    if _is_revision_status(submission):
        return False
    if not (getattr(assignment, 'time_limit_strict', False) and getattr(assignment, 'time_limit_minutes', None) and getattr(submission, 'started_at', None)):
        return False
    started_utc = _started_at_to_utc(submission.started_at)
    now_utc = _ensure_aware_datetime(now or utc_now())
    if not started_utc or not now_utc:
        return False
    return now_utc > started_utc + timedelta(minutes=assignment.time_limit_minutes)


def _assignment_uses_ege_nav_numbering(assignment) -> bool:
    """Пробник (exam): подписи как в ЕГЭ; ДЗ/КР и пр. — подряд 1, 2, 3…"""
    return (getattr(assignment, 'assignment_type', None) or '').strip().lower() == 'exam'


def _triplet_submission_state(items: list[dict]) -> str:
    verdicts = []
    for row in items:
        ans = row.get('answer')
        verdicts.append(getattr(ans, 'is_correct', None) if ans is not None else None)
    decided = [v for v in verdicts if v is not None]
    if not decided:
        return 'pending'
    if len(decided) == len(verdicts):
        if all(v is True for v in decided):
            return 'all_correct'
        if all(v is False for v in decided):
            return 'all_incorrect'
        return 'partial'
    return 'partial'


def _triplet_nav_update_meta(submission, assignment, submitted_assignment_task_id: int) -> dict | None:
    """Для пробника (exam): связка 19–21 — актуальные классы карточки и кнопки навигации после сдачи одного подзадания."""
    if not _assignment_uses_ege_nav_numbering(assignment):
        return None
    tasks_sorted = sorted((assignment.tasks or []), key=lambda t: (getattr(t, 'order_index', 0), t.assignment_task_id))
    sid = int(submitted_assignment_task_id)
    for i in range(len(tasks_sorted) - 2):
        t0, t1, t2 = tasks_sorted[i], tasks_sorted[i + 1], tasks_sorted[i + 2]
        n0 = getattr(t0.task, 'task_number', None) if t0.task else None
        n1 = getattr(t1.task, 'task_number', None) if t1.task else None
        n2 = getattr(t2.task, 'task_number', None) if t2.task else None
        if n0 != 19 or n1 != 20 or n2 != 21:
            continue
        bundle_ids = {int(t0.assignment_task_id), int(t1.assignment_task_id), int(t2.assignment_task_id)}
        if sid not in bundle_ids:
            continue
        answers_by_at = {int(a.assignment_task_id): a for a in (submission.answers or [])}
        items = [
            {'answer': answers_by_at.get(int(t0.assignment_task_id))},
            {'answer': answers_by_at.get(int(t1.assignment_task_id))},
            {'answer': answers_by_at.get(int(t2.assignment_task_id))},
        ]
        state = _triplet_submission_state(items)
        if state == 'all_correct':
            card_cls, nav_cls = 'task-correct', 'correct'
        elif state == 'all_incorrect':
            card_cls, nav_cls = 'task-incorrect', 'incorrect'
        elif state == 'partial':
            card_cls, nav_cls = 'task-pending-review', 'partial'
        else:
            card_cls, nav_cls = 'task-pending-review', 'pending-review'
        return {
            'root_assignment_task_id': int(t0.assignment_task_id),
            'card_class': card_cls,
            'nav_class': nav_cls,
        }
    return None


def build_submission_tasks_view(tasks_data: list[dict], assignment) -> list[dict]:
    """
    Навигация по работе: для exam — номер задания ЕГЭ (task_number), 19+20+21 — один блок «19-21»;
    для homework / classwork / manual_review — порядковый номер без склейки 19–21.
    """
    if not tasks_data:
        return []

    if not _assignment_uses_ege_nav_numbering(assignment):
        out: list[dict] = []
        for idx, item in enumerate(tasks_data):
            single = dict(item)
            single['is_triplet_19_21'] = False
            single['triplet_items'] = []
            single['display_number'] = str(idx + 1)
            single['triplet_state'] = 'pending'
            out.append(single)
        return out

    tasks_view: list[dict] = []
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
                root_item['display_number'] = '19-21'
                root_item['triplet_state'] = _triplet_submission_state([item, next_20, next_21])
                tasks_view.append(root_item)
                i += 3
                continue

        single_item = dict(item)
        single_item['is_triplet_19_21'] = False
        single_item['triplet_items'] = []
        single_num = getattr(single_item.get('task'), 'task_number', None)
        single_item['display_number'] = str(single_num) if single_num is not None else str(len(tasks_view) + 1)
        single_item['triplet_state'] = 'pending'
        tasks_view.append(single_item)
        i += 1
    return tasks_view


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


def _coerce_int_score(raw, default: int = 0) -> int:
    """Безопасно привести балл из JSON/формы к int (пустая строка / мусор → default)."""
    if raw is None:
        return default
    if isinstance(raw, str):
        t = raw.strip().replace("\u2212", "-").replace("−", "-")
        if not t:
            return default
        raw = t
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return default


def _parse_teacher_mmr_override(raw) -> float | None:
    """Разбор ручного ΔMMR (Unicode-минус, запятая как десятичный разделитель)."""
    if raw is None:
        return None
    s = str(raw).strip().replace(",", ".").replace("\u2212", "-").replace("−", "-")
    if not s:
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _answer_has_meaningful_student_work(answer) -> bool:
    """Есть ли реальная работа ученика по заданию (не пустая карточка без ответа)."""
    if not answer:
        return False
    val = getattr(answer, "value", None)
    if val is not None and str(val).strip() != "":
        return True
    code = getattr(answer, "student_code", None)
    if code is not None and str(code).strip() != "":
        return True
    files = getattr(answer, "files", None)
    if isinstance(files, (list, tuple)) and len(files) > 0:
        return True
    if isinstance(files, dict) and len(files) > 0:
        return True
    if isinstance(files, str):
        fs = files.strip()
        if fs and fs not in ("[]", "null", "{}"):
            return True
    if getattr(answer, "submitted_separately_at", None) is not None:
        return True
    if (getattr(answer, "attempts_used", None) or 0) > 0:
        return True
    return False


def _legacy_submission_comment_bucket_task_id(assignment) -> int | None:
    """
    Старые записи SubmissionComment без assignment_task_id.
    Чтобы не дублировать их во всех заданиях, закрепляем за первым заданием работы по order_index.
    """
    tasks = sorted((assignment.tasks or []), key=lambda t: (getattr(t, 'order_index', 0), t.assignment_task_id))
    return int(tasks[0].assignment_task_id) if tasks else None


def _submission_comment_task_id(comment, legacy_bucket_task_id: int | None) -> int:
    if comment.assignment_task_id:
        return int(comment.assignment_task_id)
    return int(legacy_bucket_task_id or 0)


def _bump_submission_comment_thread_read(submission_id: int, assignment_task_id: int, user_id: int, up_to_comment_id: int | None) -> None:
    """Поднять курсор «просмотрено до comment_id» для ветки чата (идемпотентно). up_to=0 — открыли пустой тред."""
    if assignment_task_id is None:
        return
    _ensure_submission_comment_thread_reads_schema()
    sid = int(submission_id)
    tid = int(assignment_task_id)
    uid = int(user_id)
    upto = max(0, int(up_to_comment_id or 0))
    row = SubmissionCommentThreadRead.query.filter_by(
        submission_id=sid, assignment_task_id=tid, user_id=uid
    ).first()
    if not row:
        db.session.add(SubmissionCommentThreadRead(
            submission_id=sid,
            assignment_task_id=tid,
            user_id=uid,
            last_read_comment_id=upto,
            updated_at=utc_now(),
        ))
    elif upto > int(row.last_read_comment_id or 0):
        row.last_read_comment_id = upto
        row.updated_at = utc_now()


def _mark_all_submission_comment_threads_read_on_page_view(submission, viewer_user_id: int, legacy_bucket_task_id: int | None) -> None:
    """
    Страница ученика с общим списком комментариев: считаем все ветки просмотренными для этого пользователя.
    """
    per_tid: dict[int, int] = {}
    for c in (submission.comments or []):
        tid = _submission_comment_task_id(c, legacy_bucket_task_id)
        if tid <= 0:
            continue
        cid = int(c.comment_id or 0)
        if cid > 0:
            per_tid[tid] = max(per_tid.get(tid, 0), cid)
    for tid, mx in per_tid.items():
        _bump_submission_comment_thread_read(submission.submission_id, tid, int(viewer_user_id), mx)


def _compute_submission_chat_unread_task_ids(submission, viewer_user_id: int, legacy_bucket_task_id: int | None) -> set[int]:
    """
    Непрочитанные ветки: есть сообщение не от текущего пользователя с comment_id выше сохранённого курсора прочтения.
    Курсор обновляется при GET /comments?assignment_task_id=… (и при открытии страницы учеником — см. submission_view).
    """
    uid = int(viewer_user_id)
    _ensure_submission_comment_thread_reads_schema()
    reads: dict[int, int] = {}
    try:
        reads = {
            int(r.assignment_task_id): int(r.last_read_comment_id or 0)
            for r in SubmissionCommentThreadRead.query.filter_by(
                submission_id=submission.submission_id,
                user_id=uid,
            ).all()
        }
    except (OperationalError, ProgrammingError) as e:
        logger.warning('SubmissionCommentThreadRead query failed (schema?): %s', e)
        return _compute_submission_chat_unread_fallback_heuristic(submission, viewer_user_id, legacy_bucket_task_id)
    unread: set[int] = set()
    ordered = sorted((submission.comments or []), key=lambda c: (c.created_at or utc_now(), c.comment_id or 0))
    for c in ordered:
        tid = _submission_comment_task_id(c, legacy_bucket_task_id)
        if tid <= 0:
            continue
        if int(c.author_id) == uid:
            continue
        cid = int(c.comment_id or 0)
        lr = reads.get(tid, 0)
        if cid > lr:
            unread.add(tid)
    return unread


def _compute_submission_chat_unread_fallback_heuristic(submission, viewer_user_id: int, legacy_bucket_task_id: int | None) -> set[int]:
    """Если таблицы курсоров нет: непрочитано = чужое сообщение после последнего своего в этой ветке."""
    uid = int(viewer_user_id)
    unread: set[int] = set()
    last_own_at: dict[int, datetime] = {}
    ordered = sorted((submission.comments or []), key=lambda c: (c.created_at or utc_now(), c.comment_id or 0))
    for c in ordered:
        tid = _submission_comment_task_id(c, legacy_bucket_task_id)
        if tid <= 0:
            continue
        if int(c.author_id) == uid:
            last_own_at[tid] = c.created_at or utc_now()
            continue
        last_t = last_own_at.get(tid)
        if last_t is None or (c.created_at and c.created_at > last_t):
            unread.add(tid)
    return unread


def _submission_display_status(submission, assignment, now):
    """
    Возвращает отображаемый статус для списков: "Просрочено по таймеру",
    "Просрочено по дедлайну" или None (показывать обычный submission.status).
    """
    canonical_status = normalize_legacy_status(submission.status)
    if canonical_status not in ('ASSIGNED', 'IN_PROGRESS', 'RETURNED'):
        return None
    if _submission_timer_expired(submission, assignment, now):
        return 'Просрочено по таймеру'
    if canonical_status == 'RETURNED':
        return None
    if _submission_deadline_passed(assignment, now):
        return 'Просрочено по дедлайну'
    return None


def _submission_revision_task_ids(submission: Submission) -> set[int]:
    out: set[int] = set()
    for a in (submission.answers or []):
        try:
            if getattr(a, 'needs_revision', False):
                out.add(int(a.assignment_task_id))
        except Exception:
            continue
    return out


def _can_student_edit_submission_task(submission: Submission, assignment_task_id: int | None) -> bool:
    status = normalize_legacy_status(getattr(submission, 'status', None))
    if status in {'SUBMITTED', 'NEEDS_MANUAL_REVIEW', 'GRADED', 'REVOKED'}:
        return False
    if status == 'ASSIGNED':
        return False
    if status == 'IN_PROGRESS':
        return True
    if status != 'RETURNED':
        return False
    try:
        atid = int(assignment_task_id or 0)
    except Exception:
        return False
    if atid <= 0:
        return False
    allowed_ids = _submission_revision_task_ids(submission)
    # Legacy returned submissions without per-task flags: allow editing all tasks.
    if not allowed_ids:
        return True
    return atid in allowed_ids


def _set_submission_task_revision_flags(submission: Submission, *, mark_all: bool, selected_task_ids: set[int] | None = None) -> None:
    """
    Update Answer.needs_revision flags for submission.

    mark_all=True: all assignment tasks become revision-required.
    mark_all=False: only selected_task_ids are revision-required (empty -> all False).
    """
    selected_task_ids = selected_task_ids or set()
    assignment = submission.assignment
    if not assignment:
        return
    answers_by_task = {
        int(a.assignment_task_id): a
        for a in (submission.answers or [])
        if getattr(a, 'assignment_task_id', None) is not None
    }
    # В рамках одной транзакции в submission.answers могут не попасть только что созданные Answer.
    # Учитываем pending-объекты из сессии, чтобы не пытаться вставить дубликат пары
    # (submission_id, assignment_task_id) и не ловить UniqueViolation на autoflush.
    for pending in list(db.session.new):
        if not isinstance(pending, Answer):
            continue
        if int(getattr(pending, 'submission_id', 0) or 0) != int(submission.submission_id):
            continue
        atid_pending = getattr(pending, 'assignment_task_id', None)
        if atid_pending is None:
            continue
        answers_by_task[int(atid_pending)] = pending
    for assignment_task in (assignment.tasks or []):
        atid = int(assignment_task.assignment_task_id)
        answer = answers_by_task.get(atid)
        if answer is None:
            answer = Answer(
                submission_id=submission.submission_id,
                assignment_task_id=atid,
                max_score=assignment_task.max_score,
            )
            db.session.add(answer)
            try:
                if hasattr(submission, 'answers') and answer not in (submission.answers or []):
                    submission.answers.append(answer)
            except Exception:
                pass
            answers_by_task[atid] = answer
        answer.needs_revision = True if mark_all else (atid in selected_task_ids)

def _normalize_assignment_type(value: str | None) -> str:
    v = (value or '').strip().lower()
    if v in {'homework', 'classwork', 'exam', 'test', 'manual_review'}:
        return v
    return ''


def _assignment_type_label_short(value: str | None) -> str:
    v = _normalize_assignment_type(value)
    return {
        'homework': 'ДЗ',
        'classwork': 'КР',
        'exam': 'Проверочная',
        'test': 'Тест',
        'manual_review': 'Без ответов',
    }.get(v, v or '—')


def _assignment_type_label_long(value: str | None) -> str:
    v = _normalize_assignment_type(value)
    return {
        'homework': 'Домашняя работа',
        'classwork': 'Классная работа',
        'exam': 'Проверочная работа',
        'test': 'Тест',
        'manual_review': 'Без правильных ответов',
    }.get(v, v or 'Работа')


def _now_naive_msk() -> datetime:
    """Текущий момент в UTC (aware), для сравнения с дедлайнами в БД после перехода на timestamptz."""
    return utc_now()


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value or 0)
    except Exception:
        return default


def _duplicate_recipient_options_for_current_user() -> list[dict]:
    """Recipient options for duplicate-assignment modal."""
    options: list[dict] = []
    try:
        scope = get_user_scope(current_user)
        if scope.get('can_see_all'):
            students = (
                Student.query.filter(Student.is_active.is_(True))
                .order_by(Student.name.asc(), Student.student_id.asc())
                .limit(1000)
                .all()
            )
        else:
            students = get_students_for_tutor(current_user.id) or []
        for s in students:
            sid = getattr(s, 'student_id', None)
            if not sid:
                continue
            options.append({
                'student_id': int(sid),
                'name': getattr(s, 'name', None) or f'Ученик #{sid}',
            })
    except Exception:
        logger.warning('Failed to load duplicate recipient options', exc_info=True)
    return options


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
    q = q.filter(Submission.status.in_(['SUBMITTED', 'NEEDS_MANUAL_REVIEW']))

    subs = q.all()
    if not subs:
        flash('Нет сданных работ для массового действия.', 'info')
        return redirect(url_for('lessons.review_queue', status=status_filter, source=source, assignment_type=assignment_type, student=student_query))

    updated = 0
    skipped = 0
    for sub in subs:
        if action == 'mark_returned':
            _mark_submission_returned_for_revision(sub)
            _set_submission_task_revision_flags(sub, mark_all=True)
        else:
            if sub.total_score is None or sub.max_score is None:
                skipped += 1
                continue
            transition_submission_status(sub, 'GRADED', force=True)
            sub.graded_at = utc_now()
            _set_submission_task_revision_flags(sub, mark_all=False, selected_task_ids=set())
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

    if normalize_legacy_status(submission.status) not in {'SUBMITTED', 'NEEDS_MANUAL_REVIEW'}:
        flash('Эту сдачу нельзя вернуть из текущего статуса.', 'warning')
        return redirect(url_for('lessons.review_queue', status=status_filter, source=source, assignment_type=assignment_type, student=student_query))

    _mark_submission_returned_for_revision(submission)
    _set_submission_task_revision_flags(submission, mark_all=True)
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
    if normalize_legacy_status(submission.status) != 'GRADED':
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
        submitted_at=submission.submitted_at or utc_now(),
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

    # A few historical QA/imported student accounts were created before the
    # Student record became mandatory. Repair that missing relation once so an
    # impersonated student receives the same V2 workspace as a newly registered one.
    if getattr(user, 'is_student', lambda: False)():
        try:
            st = Student(
                user_id=user.id,
                platform_id=(getattr(user, 'username', None) or None),
                name=(getattr(user, 'full_name', None) or getattr(user, 'username', None) or 'Ученик').strip(),
                email=(getattr(user, 'email', None) or None),
                is_active=True,
            )
            db.session.add(st)
            db.session.commit()
            return st
        except IntegrityError:
            db.session.rollback()
            return Student.query.filter_by(user_id=user.id).first()
        except Exception:
            db.session.rollback()
            logger.exception('Unable to repair missing student profile for user %s', user.id)
    return None


def _can_current_user_access_submission(submission: Submission | None) -> bool:
    if not submission:
        return False
    if current_user and current_user.is_authenticated and getattr(current_user, 'is_student', lambda: False)():
        stud = get_student_by_user_id(current_user.id)
        valid_ids = {current_user.id}
        if stud:
            if getattr(stud, 'student_id', None):
                valid_ids.add(int(stud.student_id))
            if getattr(stud, 'user_id', None):
                valid_ids.add(int(stud.user_id))
        if submission.student_id in valid_ids:
            return True

    if getattr(submission, 'student', None):
        student_user_id = getattr(submission.student, 'user_id', None)
        student_platform_id = getattr(submission.student, 'student_id', None)
        return can_user_access_student(current_user, student_user_id=student_user_id, student_platform_id=student_platform_id)
    return False


def _can_current_user_comment_submission(submission: Submission | None) -> bool:
    if not _can_current_user_access_submission(submission):
        return False
    if getattr(current_user, 'is_parent', lambda: False)():
        return False
    return True


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
    normalized_student = normalize_answer_value(student_answer)
    normalized_correct = normalize_answer_value(correct_answer)
    if normalized_student == normalized_correct and normalized_correct != '':
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


def _pick_probnik_tasks_one_per_exam_number(course_id: int, *, random_mode: bool = False) -> list[Tasks]:
    """
    Быстрый пробник: по одному активному заданию на каждый «слот» номера 1–27 в рамках курса.
    Любая тройка с общим task_group_id (часто 19–21, иногда другие номера) берётся один раз:
    все номера заданий из этой тройки помечаются занятыми, чтобы не подобрать дубликат группы.
    """
    out: list[Tasks] = []
    seen_triplet_groups: set[str] = set()
    consumed_task_numbers: set[int] = set()
    cid = int(course_id)
    for n in range(1, 28):
        if n in consumed_task_numbers:
            continue
        q = Tasks.query.filter(
            Tasks.course_id == cid,
            Tasks.task_number == n,
            Tasks.is_active.is_(True),
        )
        t = (q.order_by(func.random()).first() if random_mode else q.order_by(Tasks.task_id.asc()).first())
        if not t:
            continue
        gid = (str(getattr(t, 'task_group_id', None) or '').strip())
        trip = _get_triplet_task_ids(t)
        if trip and gid:
            if gid in seen_triplet_groups:
                continue
            seen_triplet_groups.add(gid)
            try:
                for tr in Tasks.query.filter(Tasks.task_id.in_(trip)).all():
                    tn = getattr(tr, 'task_number', None)
                    if tn is not None:
                        consumed_task_numbers.add(int(tn))
            except Exception:
                pass
        out.append(t)
    return out


def _probnik_random_enabled_from_request() -> bool:
    """
    Fast probnik should feel fresh by default.
    Explicit ?probnik_random=0 keeps the old deterministic pick for debugging/repeatability.
    """
    raw = request.args.get('probnik_random')
    if raw is None:
        return True
    return str(raw).strip().lower() not in {'0', 'false', 'off', 'no'}


def _task_difficulty_rank_for_cycle(task: Tasks | None) -> int:
    """1 = легче, 2 = средне / не задано, 3 = сложнее — внутри одного номера билета."""
    if not task:
        return 2
    v = getattr(task, 'difficulty_level', None)
    if v == 1:
        return 1
    if v == 3:
        return 3
    return 2


def _pick_task_cycle_variant(current: Tasks, direction: str, *, random_mode: bool = False) -> Tasks | None:
    """
    Подбор другой задачи с тем же course_id и task_number (активные).
    easier / harder / same — см. мастер создания работы (стрелки у пробника).
    """
    cid = getattr(current, 'course_id', None)
    tn = getattr(current, 'task_number', None)
    if cid is None or tn is None:
        return None
    candidates = (
        Tasks.query.filter(
            Tasks.course_id == int(cid),
            Tasks.task_number == int(tn),
            Tasks.is_active.is_(True),
        )
        .order_by(Tasks.task_id.asc())
        .all()
    )
    if not candidates:
        return None
    by_tid: dict[int, Tasks] = {int(t.task_id): t for t in candidates if getattr(t, 'task_id', None) is not None}
    ids_sorted = sorted(by_tid.keys())
    cur_id = int(current.task_id)
    if cur_id not in by_tid:
        return by_tid[ids_sorted[0]]
    cur_rank = _task_difficulty_rank_for_cycle(current)

    def cyclic_next_full() -> Tasks:
        idx = ids_sorted.index(cur_id)
        nxt = ids_sorted[(idx + 1) % len(ids_sorted)]
        return by_tid[nxt]

    def random_pick(ids: list[int]) -> Tasks | None:
        if not ids:
            return None
        return by_tid[random.choice(ids)]

    if direction == 'easier':
        easier = [
            tid
            for tid in ids_sorted
            if tid != cur_id and _task_difficulty_rank_for_cycle(by_tid[tid]) < cur_rank
        ]
        if easier:
            if random_mode:
                picked = random_pick(easier)
                if picked:
                    return picked
            easier.sort(key=lambda tid: (_task_difficulty_rank_for_cycle(by_tid[tid]), tid))
            return by_tid[easier[0]]
        if random_mode:
            pool = [tid for tid in ids_sorted if tid != cur_id]
            picked = random_pick(pool)
            if picked:
                return picked
        return cyclic_next_full()

    if direction == 'harder':
        harder = [
            tid
            for tid in ids_sorted
            if tid != cur_id and _task_difficulty_rank_for_cycle(by_tid[tid]) > cur_rank
        ]
        if harder:
            if random_mode:
                picked = random_pick(harder)
                if picked:
                    return picked
            harder.sort(key=lambda tid: (_task_difficulty_rank_for_cycle(by_tid[tid]), tid))
            return by_tid[harder[0]]
        if random_mode:
            pool = [tid for tid in ids_sorted if tid != cur_id]
            picked = random_pick(pool)
            if picked:
                return picked
        return cyclic_next_full()

    if direction == 'same':
        same_ids = sorted(
            tid for tid in ids_sorted if _task_difficulty_rank_for_cycle(by_tid[tid]) == cur_rank
        )
        if random_mode:
            pool_same = [tid for tid in same_ids if tid != cur_id]
            picked = random_pick(pool_same)
            if picked:
                return picked
            pool = [tid for tid in ids_sorted if tid != cur_id]
            picked = random_pick(pool)
            if picked:
                return picked
        if len(same_ids) <= 1:
            return cyclic_next_full()
        if cur_id not in same_ids:
            return by_tid[same_ids[0]]
        j = same_ids.index(cur_id)
        nxt = same_ids[(j + 1) % len(same_ids)]
        return by_tid[nxt]

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


@assignments_bp.route('/assignments/api/cycle-task-variant', methods=['GET'])
@login_required
@check_access('assignment.create')
def cycle_task_variant():
    """
    JSON: подобрать другую задачу с тем же номером билета и курсом (для быстрых стрелок в мастере).
    direction=easier | harder | same
    """
    task_id = request.args.get('task_id', type=int)
    direction = (request.args.get('direction') or '').strip().lower()
    random_mode = request.args.get('random', type=int) == 1
    if not task_id or direction not in {'easier', 'harder', 'same'}:
        return jsonify({'success': False, 'error': 'Нужны task_id и direction (easier|harder|same)'}), 400
    task = Tasks.query.get(task_id)
    if not task:
        return jsonify({'success': False, 'error': 'Задача не найдена'}), 404
    picked = _pick_task_cycle_variant(task, direction, random_mode=random_mode)
    if not picked or getattr(picked, 'task_id', None) is None:
        return jsonify({'success': False, 'error': 'Нет других вариантов для этого номера'}), 404
    if int(picked.task_id) == int(task.task_id):
        return jsonify({'success': False, 'error': 'В банке только этот вариант для данного номера'}), 404
    return jsonify(
        {
            'success': True,
            'task_id': int(picked.task_id),
            'task_number': int(getattr(picked, 'task_number', 0) or 0),
            'difficulty_level': getattr(picked, 'difficulty_level', None),
        }
    )


@assignments_bp.route('/assignments/api/task-preview', methods=['GET'])
@login_required
@check_access('assignment.create')
def assignment_task_preview():
    """Вернуть данные карточки задания для моментального обновления UI в мастере."""
    task_id = request.args.get('task_id', type=int)
    if not task_id:
        return jsonify({'success': False, 'error': 'task_id обязателен'}), 400
    task = Tasks.query.get(task_id)
    if not task:
        return jsonify({'success': False, 'error': 'Задача не найдена'}), 404

    files = []
    try:
        raw = (getattr(task, 'attached_files', None) or '').strip()
        if raw:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                files = parsed
    except Exception:
        files = []

    return jsonify(
        {
            'success': True,
            'task': {
                'task_id': int(task.task_id),
                'task_number': int(task.task_number),
                'course_id': int(task.course_id) if getattr(task, 'course_id', None) else None,
                'source_url': getattr(task, 'source_url', None),
                'difficulty_level': getattr(task, 'difficulty_level', None),
                'kege_tier_label_ru': getattr(task, 'kege_tier_label_ru', None),
                'bank_origin': getattr(task, 'bank_origin', None),
                'source_prototype': getattr(task, 'source_prototype', None),
                'content_html': normalize_task_content_assets(
                    getattr(task, 'content_html', '') or '',
                    getattr(task, 'attached_files', None),
                    getattr(task, 'source_url', None),
                ),
                'attached_files': files,
            },
        }
    )


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
        assignment_type = _normalize_assignment_type(data.get('type', 'homework')) or 'homework'
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
        draft_id = data.get('draft_id')
        tasks_data = data.get('tasks', [])  # [{"task_id": 123, "max_score": 1, "order": 0, "max_attempts": null}, ...]
        recipient_ids = data.get('recipientIds', [])  # Список student_id
        group_id = data.get('groupId')  # "all" или конкретная группа
        
        if not title:
            return jsonify({'success': False, 'error': 'Название работы обязательно'}), 400
        
        if not deadline_str:
            return jsonify({'success': False, 'error': 'Дедлайн обязателен'}), 400
        
        try:
            deadline = _deadline_payload_to_utc(deadline_str)
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

        draft_to_remove = None
        if draft_id:
            try:
                draft_to_remove = _assignment_builder_owned_draft(int(draft_id))
            except (TypeError, ValueError):
                return jsonify({'success': False, 'error': 'Некорректный черновик'}), 400
            if draft_to_remove is None:
                return jsonify({'success': False, 'error': 'Черновик не найден или недоступен'}), 404
        
        dist_exam_course_id = None
        requested_course_id = data.get('exam_course_id')
        try:
            requested_course = Course.query.filter_by(id=int(requested_course_id), is_active=True).first() if requested_course_id else None
            dist_exam_course_id = requested_course.id if requested_course else None
        except (TypeError, ValueError):
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
            if assignment_type == 'manual_review':
                # Special type: student answers are always checked manually by teacher.
                requires_manual_grading = True
            else:
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
                assigned_at=utc_now(),
                max_score=sum(at.max_score for at in assignment.tasks)
            )
            db.session.add(submission)

        if draft_to_remove is not None:
            db.session.delete(draft_to_remove)
        
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
        label = {
            'homework': 'Домашняя работа',
            'classwork': 'Классная работа',
            'exam': 'Проверочная работа',
            'test': 'Проверочная работа',
            'manual_review': 'Работа без правильных ответов',
        }.get((assignment_type or 'homework').strip().lower(), 'Задания')
        summary = build_task_number_summary(task_ids)
        task_numbers = build_task_number_counts(task_ids)
        body = f"{label}: {summary}"
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
                submission = Submission.query.filter_by(
                    assignment_id=assignment.assignment_id,
                    student_id=student_id,
                ).first()
                student_link = None
                if submission:
                    student_link = url_for(
                        'assignments.submission_view',
                        submission_id=submission.submission_id,
                        _external=True,
                    )
                elif current_app:
                    student_link = url_for('assignments.assignments_list', _external=True)
                notify_user(
                    user_id,
                    kind='assignment_assigned',
                    title=f"Новые задания — {label}",
                    body=body,
                    link_url=student_link,
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
    if getattr(current_user, 'is_student', lambda: False)() or getattr(current_user, 'is_parent', lambda: False)():
        return redirect(url_for('assignments.submissions_list'))

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
            func.sum(
                case(
                    (func.upper(func.coalesce(Submission.status, '')) != 'REVOKED', 1),
                    else_=0,
                )
            ).label('total_students'),
            func.sum(
                case(
                    (Submission.status.in_(['SUBMITTED', 'GRADED', 'RETURNED', 'NEEDS_MANUAL_REVIEW']), 1),
                    else_=0,
                )
            ).label('submitted'),
            func.sum(
                case(
                    (Submission.status.in_(['SUBMITTED', 'NEEDS_MANUAL_REVIEW']), 1),
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

        dl_utc = _to_utc(a.deadline) if a.deadline else None
        now_utc = _to_utc(now)

        is_overdue = bool(dl_utc and now_utc and dl_utc < now_utc and pending > 0)
        is_completed = bool(total_students > 0 and pending == 0 and to_grade == 0)
        is_active = bool(dl_utc and now_utc and dl_utc >= now_utc and (pending > 0 or to_grade > 0))
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
            normalized_status = normalize_legacy_status(sub_status) or ''
            if normalized_status == 'REVOKED':
                continue
            if aid not in students_by_assignment:
                students_by_assignment[aid] = []
            students_by_assignment[aid].append({
                'name': sname,
                'student_id': sid,
                'status': normalized_status or sub_status,
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

        dl_utc = _to_utc(assignment.deadline) if assignment.deadline else None
        now_utc = _to_utc(now)
        is_overdue = bool(dl_utc and now_utc and dl_utc < now_utc and pending > 0)
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
        duplicate_recipient_options=_duplicate_recipient_options_for_current_user(),
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
        if assignment_type not in ['homework', 'classwork', 'exam', 'manual_review']:
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

        if assignment_type not in ['homework', 'classwork', 'exam', 'manual_review']:
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
    - source=probnik: быстрый набор по одному заданию на номер 1–27 (курс)
    """
    source = (request.args.get('source') or 'manual').strip().lower()
    if source not in {'accepted', 'template', 'manual', 'lesson', 'generator', 'probnik'}:
        source = 'manual'

    assignment_type = _normalize_assignment_type(request.args.get('assignment_type')) or 'homework'
    task_type = request.args.get('task_type', type=int, default=None)
    template_id = request.args.get('template_id', type=int, default=None)
    lesson_id = request.args.get('lesson_id', type=int, default=None)
    task_ids_param = request.args.get('task_ids', type=str, default=None)
    recipient_ids_param = request.args.get('recipient_ids', type=str, default=None)
    draft_id = request.args.get('assignment_id', type=int, default=None)

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

    probnik_mode = False
    if source == 'probnik':
        probnik_mode = True
        assignment_type = _normalize_assignment_type(request.args.get('assignment_type')) or 'exam'
        probnik_random_mode = _probnik_random_enabled_from_request()
        exam_course_id_pb = request.args.get('exam_course_id', type=int)
        if not exam_course_id_pb:
            try:
                dc = Course.query.filter_by(is_active=True).order_by(Course.id.asc()).first()
                exam_course_id_pb = int(dc.id) if dc else None
            except Exception:
                exam_course_id_pb = None
        picked_pb: list[Tasks] = []
        if exam_course_id_pb:
            try:
                picked_pb = _pick_probnik_tasks_one_per_exam_number(int(exam_course_id_pb), random_mode=probnik_random_mode)
            except Exception:
                picked_pb = []
        tasks = picked_pb
        source_label = 'Быстрый пробник'
        source_meta = {'probnik': True, 'exam_course_id': exam_course_id_pb, 'probnik_random': bool(probnik_random_mode)}
        if exam_course_id_pb and not picked_pb:
            flash('Для выбранного курса не найдено активных заданий 1–27. Проверьте банк или другой курс.', 'warning')
        elif exam_course_id_pb and len(picked_pb) < 20:
            flash(
                f'Пробник собран частично: найдено {len(picked_pb)} заданий. Добавьте недостающие номера вручную или смените курс.',
                'warning',
            )
        source = 'generator'

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

    existing_assignment: dict[str, Any] | None = None
    if draft_id:
        draft = _assignment_builder_owned_draft(draft_id)
        if draft is None:
            flash('Черновик не найден или недоступен.', 'warning')
            return redirect(url_for('assignments.assignment_create'))
        source = 'draft'
        source_label = 'Черновик'
        tasks = [row.task for row in sorted(draft.tasks or [], key=lambda row: (row.order_index, row.assignment_task_id)) if row.task]
        source_meta = {'assignment_id': draft.assignment_id}
        assignment_type = draft.assignment_type or assignment_type
        existing_assignment = {
            'id': draft.assignment_id,
            'title': draft.title,
            'description': draft.description or '',
            'assignment_type': draft.assignment_type,
            'deadline': _datetime_local_value_for_user(draft.deadline),
            'time_limit_minutes': draft.time_limit_minutes,
            'max_attempts_default': draft.max_attempts_default,
            'hard_deadline': bool(draft.hard_deadline),
            'hide_before_start': bool(draft.hide_before_start),
            'allow_separate_submission': bool(draft.allow_separate_submission),
            'course_id': draft.exam_course_id,
            'tasks': [
                _assignment_builder_task_payload(
                    row.task,
                    max_score=row.max_score,
                    requires_manual_grading=bool(row.requires_manual_grading),
                )
                for row in sorted(draft.tasks or [], key=lambda row: (row.order_index, row.assignment_task_id))
                if row.task
            ],
        }

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
        _raw_ids = [int(t.task_id) for t in (tasks or []) if getattr(t, 'task_id', None)]
        task_ids = list(dict.fromkeys(_raw_ids))
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

    group_members_map: dict[str, list[int]] = {}
    try:
        for _g in available_groups or []:
            _gid = getattr(_g, 'group_id', None)
            if _gid is None:
                continue
            _gidi = int(_gid)
            rows = GroupStudent.query.filter_by(group_id=_gidi).all()
            group_members_map[str(_gidi)] = [int(r.student_id) for r in rows if getattr(r, 'student_id', None)]
    except Exception:
        group_members_map = {}

    courses_for_probnik: list[Course] = []
    try:
        courses_for_probnik = (
            Course.query.filter_by(is_active=True).order_by(Course.title.asc(), Course.id.asc()).limit(100).all()
        )
    except Exception:
        courses_for_probnik = []

    default_probnik_course_id = None
    probnik_random_mode = False
    try:
        if isinstance(source_meta, dict):
            default_probnik_course_id = source_meta.get('exam_course_id')
            probnik_random_mode = bool(source_meta.get('probnik_random'))
    except Exception:
        default_probnik_course_id = None
        probnik_random_mode = False

    task_card_count = len(tasks or [])
    task_exam_number_slots = 0
    try:
        task_exam_number_slots = len(
            {int(t.task_number) for t in (tasks or []) if getattr(t, 'task_number', None) is not None}
        )
    except Exception:
        task_exam_number_slots = task_card_count

    bank_course_id_for_links = None
    try:
        if isinstance(source_meta, dict):
            bank_course_id_for_links = source_meta.get('exam_course_id')
    except Exception:
        bank_course_id_for_links = None
    if bank_course_id_for_links is None:
        bank_course_id_for_links = default_probnik_course_id

    return render_template(
        'sandbox/create_assignment.html',
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
        group_members_map=group_members_map,
        courses_for_probnik=courses_for_probnik,
        probnik_mode=probnik_mode,
        default_probnik_course_id=default_probnik_course_id,
        probnik_random_mode=probnik_random_mode,
        task_card_count=task_card_count,
        task_exam_number_slots=task_exam_number_slots,
        bank_course_id_for_links=bank_course_id_for_links,
        assignment_id=draft_id,
        existing_assignment=existing_assignment,
        is_admin=bool(get_user_scope(current_user).get('can_see_all')),
        courses=[{'id': course.id, 'title': course.title} for course in courses_for_probnik],
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
        deadline_input_value=_datetime_local_value_for_user(assignment.deadline),
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
                assignment.deadline = _deadline_payload_to_utc(deadline_str)
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


@assignments_bp.route('/submissions/<int:submission_id>/revoke', methods=['POST'])
@login_required
@check_access('assignment.create')
def submission_revoke(submission_id: int):
    """Отзывает назначенную работу у конкретного ученика без удаления Assignment."""
    if current_user.is_student() or current_user.is_parent():  # comment
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403  # comment

    submission = Submission.query.options(
        joinedload(Submission.assignment),
        joinedload(Submission.student),
    ).get_or_404(submission_id)

    assignment = submission.assignment
    if not assignment:
        return jsonify({'success': False, 'error': 'Работа не найдена'}), 404

    scope = get_user_scope(current_user)
    if not scope.get('can_see_all') and assignment.created_by_id != current_user.id:
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    if (submission.status or '').upper() == 'REVOKED':
        return jsonify({'success': True, 'already_revoked': True}), 200

    submission.status = 'REVOKED'
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Revoke submission failed: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Не удалось отозвать работу'}), 500

    return jsonify({'success': True}), 200


@assignments_bp.route('/assignments/<int:assignment_id>/duplicate', methods=['POST'])
@login_required
@check_access('assignment.create')
def assignment_duplicate(assignment_id: int):
    """Создаёт копию работы с возможностью выбрать учеников и настройки."""
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
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        payload = {}

    def _to_bool(val, default=False):
        if val is None:
            return default
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return bool(val)
        s = str(val).strip().lower()
        if s in {'1', 'true', 'yes', 'on'}:
            return True
        if s in {'0', 'false', 'no', 'off'}:
            return False
        return default

    requested_title = (payload.get('title') or '').strip()
    requested_description = payload.get('description')
    requested_deadline = (payload.get('deadline') or '').strip()
    requested_assignment_type = _normalize_assignment_type(payload.get('assignment_type'))
    requested_max_attempts = payload.get('max_attempts_default')
    requested_time_limit = payload.get('time_limit_minutes')
    requested_hard_deadline = payload.get('hard_deadline')
    requested_hide_before_start = payload.get('hide_before_start')
    requested_allow_separate_submission = payload.get('allow_separate_submission')
    requested_attempts_per_task = payload.get('attempts_per_task')
    requested_time_limit_strict = payload.get('time_limit_strict')
    requested_recipient_ids = payload.get('recipientIds') or []

    new_deadline = now + timedelta(days=7)
    if requested_deadline:
        try:
            new_deadline = _deadline_payload_to_utc(requested_deadline)
        except Exception:
            return jsonify({'success': False, 'error': 'Некорректный дедлайн'}), 400

    max_total = 0
    try:
        for t in (src.tasks or []):
            max_total += int(getattr(t, 'max_score', 0) or 0)
    except Exception:
        max_total = None  # type: ignore[assignment]

    selected_student_ids = []
    if isinstance(requested_recipient_ids, list) and requested_recipient_ids:
        for raw_sid in requested_recipient_ids:
            try:
                sid = int(raw_sid)
            except (TypeError, ValueError):
                continue
            if sid > 0:
                selected_student_ids.append(sid)
    else:
        for s in (src.submissions or []):
            if getattr(s, 'student_id', None):
                selected_student_ids.append(int(s.student_id))

    uniq_ids = []
    seen = set()
    for sid in selected_student_ids:
        if sid not in seen:
            seen.add(sid)
            uniq_ids.append(sid)

    if not uniq_ids:
        return jsonify({'success': False, 'error': 'Не выбраны получатели копии'}), 400

    # Scope guard for selected recipients
    if not scope.get('can_see_all'):
        accessible_students = get_students_for_tutor(current_user.id)
        accessible_ids = {int(s.student_id) for s in (accessible_students or []) if getattr(s, 'student_id', None)}
        uniq_ids = [sid for sid in uniq_ids if sid in accessible_ids]
        if not uniq_ids:
            return jsonify({'success': False, 'error': 'Нет доступных получателей для дублирования'}), 403

    max_attempts_default = getattr(src, 'max_attempts_default', None)
    if requested_max_attempts is not None:
        try:
            max_attempts_default = max(1, int(requested_max_attempts))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'Некорректное число попыток'}), 400

    time_limit_minutes = src.time_limit_minutes
    if requested_time_limit is not None and str(requested_time_limit).strip() != '':
        try:
            time_limit_minutes = max(1, int(requested_time_limit))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'Некорректный лимит времени'}), 400

    attempts_per_task = _to_bool(requested_attempts_per_task, bool(getattr(src, 'attempts_per_task', False)))
    allow_separate_submission = _to_bool(
        requested_allow_separate_submission,
        bool(getattr(src, 'allow_separate_submission', True)),
    )
    if attempts_per_task:
        allow_separate_submission = True

    hard_deadline = _to_bool(requested_hard_deadline, bool(src.hard_deadline))
    hide_before_start = _to_bool(requested_hide_before_start, bool(getattr(src, 'hide_before_start', True)))
    time_limit_strict = _to_bool(requested_time_limit_strict, bool(getattr(src, 'time_limit_strict', False)))
    assignment_type = requested_assignment_type or _normalize_assignment_type(getattr(src, 'assignment_type', None))
    if assignment_type not in {'homework', 'classwork', 'exam', 'manual_review'}:
        assignment_type = _normalize_assignment_type(getattr(src, 'assignment_type', None)) or 'homework'

    new_assignment = Assignment(
        title=requested_title or f"{(src.title or 'Работа').strip()} (копия)",
        description=str(requested_description).strip() if requested_description is not None else src.description,
        assignment_type=assignment_type,
        deadline=new_deadline,
        hard_deadline=hard_deadline,
        hide_before_start=hide_before_start,
        allow_separate_submission=allow_separate_submission,
        attempts_per_task=attempts_per_task,
        time_limit_minutes=time_limit_minutes,
        time_limit_strict=time_limit_strict,
        max_attempts_default=max_attempts_default,
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

    for sid in uniq_ids:
        db.session.add(Submission(
            assignment_id=new_assignment.assignment_id,
            student_id=sid,
            status='ASSIGNED',
            assigned_at=utc_now(),
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
            joinedload(Assignment.submissions).joinedload(Submission.student).joinedload(Student.user),
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
            'returned': 0,
            'graded': 0,
            'needs_grading': 0,
        }
        for s in subs_all:
            st = normalize_legacy_status(getattr(s, 'status', '')) or ''
            if st == 'REVOKED':
                continue
            counts['total'] += 1
            if st == 'ASSIGNED':
                counts['assigned'] += 1
            elif st == 'IN_PROGRESS':
                counts['in_progress'] += 1
            elif st == 'RETURNED':
                counts['returned'] += 1
            elif st == 'GRADED':
                counts['graded'] += 1
            elif st == 'SUBMITTED':
                counts['submitted'] += 1
                counts['needs_grading'] += 1
            elif st == 'NEEDS_MANUAL_REVIEW':
                counts['submitted'] += 1
                counts['needs_grading'] += 1

        def _matches_status(s: Submission) -> bool:
            if status_filter in {'', 'all'}:
                st_all = normalize_legacy_status(getattr(s, 'status', '')) or ''
                return st_all != 'REVOKED'
            st = normalize_legacy_status(getattr(s, 'status', '')) or ''
            if st == 'REVOKED':
                return False
            if status_filter == 'needs_grading':
                return st in {'SUBMITTED', 'NEEDS_MANUAL_REVIEW'}
            if status_filter == 'submitted':
                return st in {'SUBMITTED', 'GRADED', 'RETURNED', 'NEEDS_MANUAL_REVIEW'}
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
                'NEEDS_MANUAL_REVIEW': 0,
                'RETURNED': 1,
                'IN_PROGRESS': 2,
                'ASSIGNED': 3,
                'GRADED': 4,
            }
            st = normalize_legacy_status(getattr(s, 'status', '')) or ''
            ts = getattr(s, 'submitted_at', None) or getattr(s, 'assigned_at', None) or getattr(s, 'created_at', None)
            try:
                ts_val = ts.timestamp() if ts else 0
            except Exception:
                ts_val = 0
            return (order.get(st, 9), -ts_val)

        submissions.sort(key=_sort_key)

        now = utc_now()
        submission_display_status = {}
        for s in submissions:
            label = _submission_display_status(s, assignment, now)
            if label:
                submission_display_status[s.submission_id] = label

        can_manage = bool(has_permission(current_user, 'assignment.create')) and (scope.get('can_see_all') or assignment.created_by_id == current_user.id)

        return render_template(
            'sandbox/assignment_detail.html',
            assignment=assignment,
            submissions=submissions,
            counts=counts,
            status_filter=status_filter,
            student_query=student_query,
            can_manage=can_manage,
            submission_display_status=submission_display_status,
            duplicate_recipient_options=_duplicate_recipient_options_for_current_user(),
            assignment_deadline_display=_display_datetime_for_user(assignment.deadline),
            assignment_deadline_input_value=_datetime_local_value_for_user(assignment.deadline),
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

    session_user_id = session.get('_user_id')
    try:
        viewer_user_id = int(session_user_id) if session_user_id is not None else int(current_user.id)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'РћС‚СЃСѓС‚СЃС‚РІСѓРµС‚ Р°РєС‚РёРІРЅР°СЏ СЃРµСЃСЃРёСЏ'}), 401

    student = get_student_by_user_id(viewer_user_id)
    if not student:
        flash('Профиль ученика не найден', 'warning')
        return redirect(url_for('auth.user_profile'))
    
    submissions = Submission.query.join(Submission.assignment).filter(
        Submission.student_id == student.student_id,
        func.upper(func.coalesce(Submission.status, '')) != 'REVOKED',
        Assignment.is_active == True,  # noqa: E712  скрываем архивные
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

    now = utc_now()
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
        if not _can_current_user_access_submission(submission):
            flash('Доступ запрещен', 'danger')
            return redirect(url_for('assignments.submissions_list'))
        student = submission.student
        is_parent_view = bool(getattr(current_user, 'is_parent', lambda: False)())
        if (submission.status or '').upper() == 'REVOKED':
            flash('Эта работа была отозвана преподавателем.', 'info')
            return redirect(url_for('assignments.submissions_list'))
    except Exception as e:
        logger.error(f"Error checking access for submission {submission_id}: {e}", exc_info=True)
        flash('Ошибка при проверке доступа', 'danger')
        return redirect(url_for('assignments.submissions_list'))
    
    assignment = submission.assignment
    if not assignment:
        flash('Работа не найдена', 'danger')
        return redirect(url_for('assignments.submissions_list'))
    # Запрещаем доступ студента к архивным заданиям
    if not assignment.is_active:
        flash('Это задание было архивировано преподавателем.', 'info')
        return redirect(url_for('assignments.submissions_list'))
    
    try:
        now = utc_now()
        normalized_submission_status = normalize_legacy_status(submission.status)
        is_deadline_passed = _submission_deadline_passed(assignment, now)
        can_submit = not _submission_hard_deadline_blocks(submission, assignment, now)
        if normalized_submission_status in {'SUBMITTED', 'NEEDS_MANUAL_REVIEW', 'GRADED', 'REVOKED'}:
            can_submit = False
        
        all_attempts = submission.attempts or []
        attempts_used = sum(1 for a in all_attempts if getattr(a, 'status', '') == 'SUBMITTED')
        effective_max_attempts = assignment.get_effective_max_attempts()
        if attempts_used >= effective_max_attempts and submission.status != 'RETURNED':
            can_submit = False
        attempts_left = max(0, effective_max_attempts - attempts_used)
        
        attempts_per_task = getattr(assignment, 'attempts_per_task', False)
        timer_expired = _submission_timer_expired(submission, assignment, now)
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
                    'mmr_rating_source': 'manual' if flags.get('teacher_adjusted') else 'auto',
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
                'task_can_edit': _can_student_edit_submission_task(submission, assignment_task.assignment_task_id),
            })

        tasks_view = build_submission_tasks_view(tasks_data, assignment)

        tasks_data_sandbox = []
        for idx, assignment_task in enumerate(sorted(assignment.tasks, key=lambda t: t.order_index)):
            answer = next((a for a in submission.answers if a.assignment_task_id == assignment_task.assignment_task_id), None)
            task = assignment_task.task
            
            task_attempts_used = (answer.attempts_used or 0) if answer else 0
            max_for_task = assignment.get_effective_max_attempts_for_task(assignment_task) if attempts_per_task else (assignment.max_attempts_default or 3)
            
            diff_level = getattr(assignment_task, 'difficulty_level', None)
            if diff_level is None and task is not None:
                diff_level = getattr(task, 'difficulty_level', None)
            difficulty_str = 'База' if diff_level == 1 else ('Хард' if diff_level == 3 else 'Стандарт')

            user_ans = (getattr(answer, 'student_answer', None) or getattr(answer, 'answer_text', None) or getattr(answer, 'answer_value', None) or '') if answer else ''
            is_correct = answer.is_correct if answer else None
            is_locked = bool(submission.status in ['SUBMITTED', 'GRADED', 'NEEDS_MANUAL_REVIEW']) or (task_attempts_used >= max_for_task)

            attached_files = []
            if task and getattr(task, 'attachments', None):
                for att in task.attachments:
                    attached_files.append({
                        'name': getattr(att, 'file_name', 'attachment'),
                        'url': f"/uploads/{att.file_path}" if hasattr(att, 'file_path') else '#'
                    })

            tasks_data_sandbox.append({
                'order_index': idx + 1,
                'task_number': getattr(task, 'task_number', idx + 1) if task else (idx + 1),
                'max_score': getattr(assignment_task, 'max_score', 1) or 1,
                'difficulty_str': difficulty_str,
                'assignment_task_id': assignment_task.assignment_task_id,
                'content_html': getattr(task, 'content_html', '') or getattr(task, 'description', '') if task else 'Условие задачи...',
                'user_answer': user_ans,
                'is_correct': is_correct,
                'attempts_used': task_attempts_used,
                'max_attempts': max_for_task,
                'is_locked': is_locked,
                'correct_answer': (task.answer if task and (is_locked or is_correct == True) else None),
                'starter_code': getattr(task, 'starter_code', None) if task else None,
                'solution_html': getattr(task, 'solution_html', None) if task else None,
                'solution_code': getattr(task, 'solution_code', None) if task else None,
                'attached_files': attached_files
            })

        legacy_bucket_task_id = _legacy_submission_comment_bucket_task_id(assignment)
        try:
            _mark_all_submission_comment_threads_read_on_page_view(submission, current_user.id, legacy_bucket_task_id)
            db.session.commit()
        except Exception as e:
            logger.warning('submission_view thread read bump failed: %s', e)
            try:
                db.session.rollback()
            except Exception:
                pass

        return render_template('sandbox/task_detail.html',
                             submission=submission,
                             assignment=assignment,
                             tasks_data=tasks_data_sandbox,
                             tasks_view=tasks_view,
                             is_deadline_passed=is_deadline_passed,
                             can_submit=can_submit,
                             attempts_used=attempts_used,
                             effective_max_attempts=effective_max_attempts,
                             attempts_left=attempts_left,
                             allow_separate_submission=assignment.allow_separate_submission,
                             attempts_per_task=attempts_per_task,
                             time_limit_strict=assignment.time_limit_strict,
                             timer_expired=timer_expired,
                             deadline_display=_display_datetime_for_user(assignment.deadline),
                             started_at_display=_display_datetime_for_user(submission.started_at) if submission.started_at else None,
                             is_parent_view=is_parent_view)
    except Exception as e:
        logger.error(f"Error processing submission_view for submission {submission_id}: {e}", exc_info=True)
        flash('Ошибка при обработке данных работы', 'danger')
        return redirect(url_for('assignments.submissions_list'))
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
        
        if normalize_legacy_status(submission.status) != 'ASSIGNED':
            logger.warning(f"Invalid status for submission {submission_id}: {submission.status}")
            _agent_debug_log(
                'H1',
                'submission_start_rejected_by_status',
                {'normalized_status': normalize_legacy_status(submission.status)}
            )
            return jsonify({'success': False, 'error': 'Работа уже начата или сдана'}), 400

        # Блокируем запуск архивного задания
        if not submission.assignment.is_active:
            return jsonify({'success': False, 'error': 'Задание архивировано'}), 403
        
        now = utc_now()
        deadline = _ensure_aware_datetime(submission.assignment.deadline)
        logger.info(f"Current time: {now}, deadline: {deadline}, hard_deadline: {submission.assignment.hard_deadline}")
        _agent_debug_log(
            'H2',
            'submission_start_deadline_check',
            {
                'has_deadline': bool(deadline),
                'hard_deadline': bool(submission.assignment.hard_deadline),
                'now_iso': now.isoformat() if now else None,
                'deadline_iso': deadline.isoformat() if deadline else None,
                'deadline_passed': bool(deadline and now > deadline),
            }
        )
        
        if _submission_hard_deadline_blocks(submission, submission.assignment, now):
            logger.warning(f"Deadline passed for submission {submission_id}")
            _agent_debug_log('H2', 'submission_start_rejected_deadline')
            return jsonify({'success': False, 'error': 'Срок выполнения работы истёк. Обратись к преподавателю, чтобы открыть работу снова.'}), 400
        
        transition_submission_status(submission, 'IN_PROGRESS')
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


def _can_current_user_access_task_attachment(task_id: int) -> bool:
    """Allow task attachments only through assignments/lessons visible to the user."""
    try:
        scope = get_user_scope(current_user)
        if scope.get('can_see_all'):
            return True
        visible_user_ids = [int(v) for v in (scope.get('student_ids') or []) if v is not None]
        if not visible_user_ids:
            return False
        student_ids = [
            sid for (sid,) in db.session.query(Student.student_id)
            .filter(Student.user_id.in_(visible_user_ids))
            .all()
        ]
        if not student_ids:
            return False
        assigned_exists = (
            db.session.query(Submission.submission_id)
            .join(Assignment, Submission.assignment_id == Assignment.assignment_id)
            .join(AssignmentTask, AssignmentTask.assignment_id == Assignment.assignment_id)
            .filter(
                Submission.student_id.in_(student_ids),
                AssignmentTask.task_id == int(task_id),
                Assignment.is_active == True,  # noqa: E712
                func.upper(func.coalesce(Submission.status, '')) != 'REVOKED',
            )
            .first()
        )
        if assigned_exists:
            return True
        lesson_exists = (
            db.session.query(LessonTask.lesson_task_id)
            .join(Lesson, LessonTask.lesson_id == Lesson.lesson_id)
            .filter(
                Lesson.student_id.in_(student_ids),
                LessonTask.task_id == int(task_id),
            )
            .first()
        )
        return bool(lesson_exists)
    except Exception as exc:
        logger.warning('task attachment access check failed for task %s: %s', task_id, exc)
        return False


@assignments_bp.route('/attachments/task/<int:task_id>/<path:filename>')
@login_required
def attached_task_local(task_id: int, filename: str):
    """Раздача локально скачанных вложений заданий. Если файла нет на диске — пробуем отдать через proxy по URL из БД."""
    import os
    from flask import send_from_directory, redirect
    if not _can_current_user_access_task_attachment(task_id):
        abort(403)
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
        inline = request.args.get('inline', type=int) == 1
        return send_from_directory(task_dir, safe_name, as_attachment=not inline, download_name=download_name)
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
        upstream = requests.get(
            url,
            stream=True,
            timeout=15,
            headers={
                'User-Agent': 'BooStudy/1.0 (+https://boostudy.ru)',
                'Referer': 'https://kompege.ru/',
            },
        )
    except Exception as e:
        logger.error(f'Error fetching upstream attachment {url}: {e}')
        abort(502)
    if upstream.status_code >= 400:
        status_code = upstream.status_code
        upstream.close()
        abort(status_code if status_code in {400, 401, 403, 404, 410, 429, 500, 502, 503, 504} else 502)

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
    disposition = 'inline' if str(content_type).lower().startswith('image/') else 'attachment'
    resp.headers['Content-Disposition'] = f'{disposition}; filename="{filename}"'
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

    if normalize_legacy_status(submission.status) not in ['IN_PROGRESS', 'ASSIGNED', 'RETURNED']:
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
    if not _can_student_edit_submission_task(submission, assignment_task_id):
        return jsonify({'success': False, 'error': 'Это задание не отправлено на доработку'}), 403

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
    answer.updated_at = utc_now()

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

    session_user_id = session.get('_user_id')
    try:
        viewer_user_id = int(session_user_id) if session_user_id is not None else int(current_user.id)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Active session is missing'}), 401

    student = get_student_by_user_id(viewer_user_id)
    if not student or submission.student_id != student.student_id:
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    
    if normalize_legacy_status(submission.status) not in ['IN_PROGRESS', 'ASSIGNED', 'RETURNED']:
        return jsonify({'success': False, 'error': 'Нельзя сохранять ответы для этой работы'}), 400

    # Блокируем автосохранение для архивных заданий
    if not submission.assignment or not submission.assignment.is_active:
        return jsonify({'success': False, 'error': 'Задание архивировано'}), 403
    
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
            if not _can_student_edit_submission_task(submission, assignment_task_id):
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
            answer.updated_at = utc_now()
        
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
        if normalize_legacy_status(submission.status) not in ['IN_PROGRESS', 'ASSIGNED', 'RETURNED']:
            return jsonify({'success': False, 'error': 'Работа уже сдана'}), 400
        assignment = submission.assignment
        # Блокируем сдачу архивного задания
        if not assignment or not assignment.is_active:
            return jsonify({'success': False, 'error': 'Задание архивировано'}), 403
        if not assignment.allow_separate_submission or not getattr(assignment, 'attempts_per_task', False):
            return jsonify({'success': False, 'error': 'Сдача по одному заданию не разрешена для этой работы'}), 400
        now = utc_now()
        if _submission_hard_deadline_blocks(submission, assignment, now):
            return jsonify({
                'success': False,
                'error': 'Срок выполнения работы истёк, поэтому сдача закрыта. Напиши преподавателю, чтобы он вернул работу на доработку или изменил дедлайн.'
            }), 403
        if _submission_timer_expired(submission, assignment, now):
            return jsonify({
                'success': False,
                'error': 'Время на выполнение вышло, поэтому сдача закрыта. Если преподаватель вернёт работу на доработку, появится новая попытка.'
            }), 403
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
        if not _can_student_edit_submission_task(submission, assignment_task_id):
            return jsonify({'success': False, 'error': 'Это задание не отправлено на доработку'}), 403
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
        answer.submitted_separately_at = utc_now()
        answer.updated_at = utc_now()
        db.session.flush()
        server_time_spent_sec = _resolve_answer_time_spent_sec(
            submission,
            answer.submitted_separately_at,
            previous_answered_at=previous_answered_at,
        )
        # Для режима "одно задание на экране" серверное окно может быть общим для всей работы,
        # поэтому для активного задания используем клиентский таймер с верхней отсечкой.
        if client_time_spent_sec is not None:
            time_spent_sec = min(max(0, int(client_time_spent_sec)), 24 * 3600)
        elif normalize_legacy_status(submission.status) == 'RETURNED':
            time_spent_sec = None
        else:
            time_spent_sec = max(0, int(server_time_spent_sec or 0))
        if client_time_spent_sec is not None and server_time_spent_sec is not None and abs(int(client_time_spent_sec) - int(server_time_spent_sec or 0)) > 30:
            logger.info(
                "submit_task time_spent mismatch: submission_id=%s assignment_task_id=%s client=%s server=%s",
                submission_id,
                assignment_task_id,
                client_time_spent_sec,
                server_time_spent_sec,
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
        if normalize_legacy_status(submission.status) == 'ASSIGNED':
            transition_submission_status(submission, 'IN_PROGRESS')
            if not submission.started_at:
                submission.started_at = utc_now()
        db.session.commit()
        triplet_nav = _triplet_nav_update_meta(submission, assignment, int(assignment_task_id))
        payload = {
            'success': True,
            'submitted_separately_at': answer.submitted_separately_at.isoformat(),
            'is_correct': answer.is_correct,
            'score': answer.score,
            'max_score': assignment_task.max_score,
            'time_spent_sec_used': time_spent_sec,
            'attempts_used': answer.attempts_used,
            'max_attempts': max_for_task,
            'rating_meta': details,
        }
        if triplet_nav:
            payload['triplet_nav'] = triplet_nav
        return jsonify(payload), 200
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
            joinedload(Submission.answers),
            joinedload(Submission.student)
        ).get_or_404(submission_id)

        session_user_id = session.get('_user_id')
        try:
            viewer_user_id = int(session_user_id) if session_user_id is not None else int(current_user.id)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'Active session is missing'}), 401

        student = get_student_by_user_id(viewer_user_id)
        if not student or submission.student_id != student.student_id:
            return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
        
        if normalize_legacy_status(submission.status) not in ['IN_PROGRESS', 'ASSIGNED', 'RETURNED']:
            return jsonify({'success': False, 'error': 'Работа уже сдана'}), 400

        assignment = submission.assignment
        # Блокируем сдачу архивного задания
        if not assignment or not assignment.is_active:
            return jsonify({'success': False, 'error': 'Задание архивировано'}), 403

        data = request.get_json(silent=True) or {}
        raw_task_times = data.get('task_times') if isinstance(data, dict) else {}
        task_times_by_assignment_task_id: dict[int, int] = {}
        if isinstance(raw_task_times, dict):
            for key, value in raw_task_times.items():
                try:
                    atid = int(key)
                    seconds = min(max(0, int(float(value))), 24 * 3600)
                except (TypeError, ValueError):
                    continue
                task_times_by_assignment_task_id[atid] = seconds
        now = utc_now()
        deadline = _ensure_aware_datetime(assignment.deadline)
        
        all_attempts = submission.attempts or []
        attempts_used = sum(1 for a in all_attempts if getattr(a, 'status', '') == 'SUBMITTED')
        effective_max = assignment.get_effective_max_attempts()
        attempts_per_task = getattr(assignment, 'attempts_per_task', False)
        if not attempts_per_task and attempts_used >= effective_max and normalize_legacy_status(submission.status) != 'RETURNED':
            return jsonify({'success': False, 'error': f'Исчерпан лимит попыток ({attempts_used}/{effective_max})'}), 403
        
        was_revision = _is_revision_status(submission)
        is_late = deadline and now > deadline
        if _submission_hard_deadline_blocks(submission, assignment, now):
            return jsonify({
                'success': False,
                'error': 'Срок выполнения работы истёк, поэтому сдача закрыта. Напиши преподавателю, чтобы он вернул работу на доработку или изменил дедлайн.'
            }), 403
        
        is_overtime = False
        if not was_revision and assignment.time_limit_minutes and submission.started_at:
            started_utc = _started_at_to_utc(submission.started_at)
            now_utc = now.astimezone(timezone.utc)
            limit_end_utc = started_utc + timedelta(minutes=assignment.time_limit_minutes)
            if now_utc > limit_end_utc:
                if assignment.time_limit_strict:
                    return jsonify({
                        'success': False,
                        'error': 'Время на выполнение вышло, поэтому сдача закрыта. Если преподаватель вернёт работу на доработку, появится новая попытка.'
                    }), 403
                is_overtime = True
        transition_submission_status(submission, 'SUBMITTED')
        submission.submitted_at = now
        submission.is_late = bool(is_late and not was_revision)
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
                            answer_time_spent_sec = task_times_by_assignment_task_id.get(int(assignment_task.assignment_task_id))
                            if answer_time_spent_sec is None:
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
                transition_submission_status(submission, 'NEEDS_MANUAL_REVIEW', force=True)
            else:
                transition_submission_status(submission, 'GRADED', force=True)
                _upsert_gradebook_from_submission(submission, actor_user_id=current_user.id)
            submission.graded_at = now

        # Collect notification info before commit to avoid DetachedInstanceError after commit
        student_name = getattr(submission.student, 'name', None) or 'Ученик'
        student_id = submission.student_id
        assignment_id = assignment.assignment_id
        assignment_title = assignment.title
        creator_id = getattr(assignment, 'created_by_id', None) or (assignment.created_by.id if getattr(assignment, 'created_by', None) else None)

        try:
            _record_submission_attempt(submission)
        except Exception as e:
            logger.warning(f"Could not record SubmissionAttempt for {submission.submission_id}: {e}")
        
        db.session.commit()

        # A submission is a persisted learning action.  Award the base reward
        # once after the status transition has been committed; repeated POSTs
        # are rejected above and cannot duplicate XP or the streak.
        from app.utils.gamification_service import reward_submission
        awarded_xp = reward_submission(student, correct_answers=0)

        try:
            from app.telegram.notifications import on_submission_status_changed
            on_submission_status_changed(submission)
        except Exception:
            logger.warning('on_submission_status_changed after submission_submit failed', exc_info=True)

        if creator_id:
            notify_user(
                creator_id,
                kind='teacher_homework_submitted',
                title='📤 Ученик сдал работу',
                body=f'{student_name} сдал(а) работу «{assignment_title}»',
                link_url=url_for('assignments.submission_view', submission_id=submission_id) if current_app else None,
                meta={'submission_id': submission_id, 'assignment_id': assignment_id, 'student_id': student_id}
            )
        
        audit_logger.log(
            action='submit_assignment',
            entity='Submission',
            entity_id=submission_id,
            status='success',
            metadata={
                'assignment_id': assignment_id,
                'is_late': is_late,
                'auto_graded': all_auto_graded
            }
        )
        
        return jsonify({
            'success': True,
            'status': submission.status,
            'score': total_score,
            'max_score': max_score,
            'percentage': submission.percentage,
            'awarded_xp': awarded_xp,
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
    raw_code = data.get('code') or ''
    if not raw_code.strip():
        return jsonify({'success': False, 'error': 'Код не передан'}), 400
    code = normalize_leading_tabs_to_spaces(raw_code)
    assignment_task_id = data.get('assignment_task_id')
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
    stdout, stderr, turtle_b64 = run_python_sandbox(code, task_files=task_files)
    payload: dict = {'success': True, 'stdout': stdout, 'stderr': stderr}
    if turtle_b64:
        payload['turtle_image_b64'] = turtle_b64
    return jsonify(payload)


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
    raw_code = data.get('code') or ''
    code = normalize_leading_tabs_to_spaces(raw_code)[:100_000]
    assignment_task_id = data.get('assignment_task_id')
    if assignment_task_id is None:
        return jsonify({'success': False, 'error': 'Не указано задание'}), 400
    if not _can_student_edit_submission_task(submission, assignment_task_id):
        return jsonify({'success': False, 'error': 'Это задание не отправлено на доработку'}), 403
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
    answer.student_code = code
    answer.student_code_saved_at = utc_now()
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
    # Flask-Login keeps the authenticated id in the signed session.  Reading
    # it here avoids a lazy refresh of an expired ORM User instance after a
    # role/session switch, while preserving the same ownership boundary.
    viewer_user_id = session.get('_user_id')
    try:
        viewer_user_id = int(viewer_user_id) if viewer_user_id is not None else int(current_user.id)
    except (TypeError, ValueError):
        return redirect(url_for('assignments.assignments_list'))
    if not scope['can_see_all'] and assignment.created_by_id != viewer_user_id:
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('assignments.assignments_list'))
    
    now = utc_now()
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
                'mmr_rating_source': 'manual' if flags.get('teacher_adjusted') else 'auto',
            }
        from app.task_workspace.service import load_workspace_trace_payload, WorkspaceContext
        try:
            temp_ctx = WorkspaceContext(
                context_type="submission_task",
                context_id=submission.submission_id,
                task_id=assignment_task.task_id,
                task=assignment_task.task,
                title="",
                subtitle="",
                source_label="",
                student_id=submission.student_id,
                student_user_id=submission.student.user_id,
                answer_id=answer.answer_id if answer else None,
            )
            playback_data = load_workspace_trace_payload(temp_ctx)
        except Exception:
            playback_data = {"trace_id": None, "frames": [], "meta": {}, "frame_count": 0}

        tasks_data.append({
            'assignment_task': assignment_task,
            'task': assignment_task.task,
            'answer': answer,
            'max_attempts_for_task': max_for_task,
            'task_attempts_used': task_attempts_used,
            'rating_meta': rating_meta,
            'difficulty_label': difficulty_label,
            'playback': playback_data,
        })

    tasks_view = build_submission_tasks_view(tasks_data, assignment)

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
            base = base.filter(RubricTemplate.owner_user_id == viewer_user_id)
        at = (assignment.assignment_type or '').strip().lower()
        if at:
            base = base.filter((db.func.lower(RubricTemplate.assignment_type) == at) | (RubricTemplate.assignment_type.is_(None)))
        rubric_templates = base.order_by(RubricTemplate.updated_at.desc(), RubricTemplate.created_at.desc(), RubricTemplate.rubric_id.desc()).limit(200).all()
    except Exception:
        rubric_templates = []

    can_submit_grade = submission.status in ('SUBMITTED', 'GRADED', 'RETURNED', 'NEEDS_MANUAL_REVIEW')
    legacy_bucket_task_id = _legacy_submission_comment_bucket_task_id(assignment)
    initial_task_id = (tasks_view[0]['assignment_task'].assignment_task_id if tasks_view else legacy_bucket_task_id)
    _ensure_submission_comment_thread_reads_schema()
    unread_task_ids = _compute_submission_chat_unread_task_ids(submission, viewer_user_id, legacy_bucket_task_id)
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
            {"assignment_task_id": 1, "score": 5, "comment": "Хорошо", "mmr_delta": optional },
            ...
        ],
        "teacher_feedback": "Общий комментарий",
        "status": "GRADED" или "RETURNED"
        "scores_only": true — сохранить баллы/рубрику/отзыв без смены статуса уведомлений; MMR пересчитывается (как при завершении), без повторного суммирования при перезаписи
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
    
    from app.utils.relationship_scope import _resolve_active_user
    active_user = _resolve_active_user(current_user)
    cur_user_id = active_user.id if active_user else None
    scope = get_user_scope(active_user or current_user)
    if not scope.get('can_see_all') and assignment.created_by_id != cur_user_id and not _can_current_user_access_submission(submission):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    
    # Разрешаем сохранять оценку и при IN_PROGRESS/ASSIGNED (таймер истёк, ученик не нажал «Сдать» — преподаватель может завершить проверку)
    if normalize_legacy_status(submission.status) not in ('SUBMITTED', 'GRADED', 'RETURNED', 'IN_PROGRESS', 'ASSIGNED', 'NEEDS_MANUAL_REVIEW'):
        return jsonify({'success': False, 'error': 'Нельзя изменить оценку для этой сдачи'}), 400

    try:
        data = request.get_json()
        scores_only = data.get('scores_only') in (True, 'true', 'True', 1, '1', 'yes', 'YES')
        scores_data = data.get('scores', [])
        teacher_feedback = data.get('teacher_feedback', '').strip()
        status = data.get('status', 'GRADED')  # GRADED или RETURNED
        raw_return_task_ids = data.get('return_assignment_task_ids') or []
        rubric_template_id = data.get('rubric_template_id', None)
        rubric_scores = data.get('rubric_scores', None)
        new_deadline_str = (data.get('new_deadline') or '').strip()  # при RETURNED — опционально новый дедлайн
        new_max_attempts = data.get('new_max_attempts')  # при RETURNED — опционально новое число попыток (int)

        if status not in ['GRADED', 'RETURNED']:
            status = 'GRADED'
        return_task_ids: set[int] = set()
        if status == 'RETURNED' and isinstance(raw_return_task_ids, list):
            for v in raw_return_task_ids:
                try:
                    iv = int(v)
                except (TypeError, ValueError):
                    continue
                if iv > 0:
                    return_task_ids.add(iv)
        
        total_score = 0
        max_score = 0

        assignment_tasks_by_id = {
            int(at.assignment_task_id): at
            for at in assignment.tasks
        }
        answers_by_task_id = {
            int(ans.assignment_task_id): ans
            for ans in (submission.answers or [])
            if getattr(ans, 'assignment_task_id', None) is not None
        }
        processed_task_ids: set[int] = set()
        mmr_override_by_task_id: dict[int, float] = {}
        rating_comment_override_by_task_id: dict[int, str] = {}

        for score_data in scores_data:
            if not isinstance(score_data, dict):
                continue
            raw_assignment_task_id = score_data.get('assignment_task_id')
            try:
                assignment_task_id = int(raw_assignment_task_id)
            except (TypeError, ValueError):
                continue
            if assignment_task_id in processed_task_ids:
                continue
            processed_task_ids.add(assignment_task_id)

            score = score_data.get('score', 0)
            comment = str(score_data.get('comment', '') or '').strip()

            assignment_task = assignment_tasks_by_id.get(assignment_task_id)
            if not assignment_task:
                continue

            max_score += assignment_task.max_score

            answer = answers_by_task_id.get(assignment_task_id)
            if not answer:
                answer = Answer(
                    submission_id=submission_id,
                    assignment_task_id=assignment_task_id,
                    max_score=assignment_task.max_score
                )
                db.session.add(answer)
                try:
                    if hasattr(submission, 'answers') and answer not in (submission.answers or []):
                        submission.answers.append(answer)
                except Exception:
                    pass
                answers_by_task_id[assignment_task_id] = answer

            sc_num = _coerce_int_score(score)
            answer.score = min(max(0, sc_num), assignment_task.max_score)  # Ограничиваем максимумом
            # Для ручной проверки считаем задание выполненным корректно, если преподаватель выставил >= 1 балла.
            answer.is_correct = bool((answer.score or 0) >= 1)
            answer.teacher_comment = comment
            total_score += answer.score

            raw_mmr = score_data.get('mmr_delta')
            if raw_mmr is not None and str(raw_mmr).strip() != '':
                mv = _parse_teacher_mmr_override(raw_mmr)
                if mv is not None:
                    score_for_mmr = min(max(0, sc_num), assignment_task.max_score)
                    if mv > 0 and score_for_mmr < 1:
                        pass  # игнор: при 0 баллов ручной «плюс» к MMR недопустим
                    else:
                        mmr_override_by_task_id[assignment_task_id] = mv
            rc_an = str(score_data.get('rating_comment') or '').strip()
            if rc_an:
                rating_comment_override_by_task_id[assignment_task_id] = rc_an[:4000]
        
        submission.total_score = total_score
        submission.max_score = max_score
        submission.percentage = (total_score / max_score * 100) if max_score > 0 else 0
        submission.teacher_feedback = teacher_feedback

        if not scores_only:
            if status == 'RETURNED':
                _set_submission_task_revision_flags(
                    submission,
                    mark_all=(len(return_task_ids) == 0),
                    selected_task_ids=return_task_ids,
                )
            else:
                _set_submission_task_revision_flags(submission, mark_all=False, selected_task_ids=set())

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

        if not scores_only:
            try:
                if status == 'RETURNED':
                    _mark_submission_returned_for_revision(submission)
                else:
                    transition_submission_status(submission, status, force=True)
            except SubmissionLifecycleError as e:
                return jsonify({'success': False, 'error': str(e)}), 400
            submission.graded_at = utc_now()
            # Если ученик не нажал «Сдать» (таймер истёк и т.п.), при завершении проверки фиксируем дату закрытия
            if submission.submitted_at is None:
                submission.submitted_at = utc_now()

            # При возврате на доработку — опционально обновляем дедлайн и/или число попыток работы
            if status == 'RETURNED':
                if new_deadline_str:
                    try:
                        assignment.deadline = _deadline_payload_to_utc(new_deadline_str)
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
                _upsert_gradebook_from_submission(submission, actor_user_id=cur_user_id)
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
            # Иначе у новых Answer в этой же транзакции ещё нет answer_id — в AnalyticsEvent уходит NULL,
            # и карточка проверки не находит событие по answer_id (плашка ΔMMR / «вручную» пустые).
            db.session.flush()
            anchor_for_time = utc_now() if scores_only else (submission.graded_at or utc_now())
            try:
                from app.analytics import AnalyticsEngine

                AnalyticsEngine.revert_submission_teacher_grade_events(submission_id)
                task_by_at_id = {at.assignment_task_id: at for at in assignment.tasks}
                for answer in submission.answers:
                    at = task_by_at_id.get(answer.assignment_task_id)
                    if not at or not at.task:
                        continue
                    manual_delta = mmr_override_by_task_id.get(int(answer.assignment_task_id))
                    has_work = _answer_has_meaningful_student_work(answer)
                    awarded = (answer.score or 0) >= 1
                    if not awarded and not has_work and manual_delta is None:
                        continue
                    is_correct = bool(answer.is_correct) if answer.is_correct is not None else bool((answer.score or 0) >= 1)
                    try:
                        answer_time_spent_sec = _resolve_answer_time_spent_sec(
                            submission,
                            answer.submitted_separately_at or anchor_for_time,
                        )
                        r_comment = rating_comment_override_by_task_id.get(int(answer.assignment_task_id))
                        AnalyticsEngine.process_submission(
                            user_id=user_id,
                            task_id=at.task.task_id,
                            is_correct=is_correct,
                            time_spent_sec=answer_time_spent_sec,
                            submission_id=submission_id,
                            answer_id=answer.answer_id,
                            attempt_no=max(1, int(answer.attempts_used or 1)),
                            mode=AnalyticsEngine.TEACHER_GRADE_MODE,
                            manual_mmr_delta=manual_delta,
                            rating_comment=r_comment if manual_delta is not None else None,
                            grader_user_id=current_user.id if manual_delta is not None else None,
                        )
                    except Exception as anal_err:
                        logger.warning("Analytics process_submission (grade_save) failed: %s", anal_err)
            except Exception as anal_batch_err:
                logger.warning("submission_grade_save: analytics batch failed: %s", anal_batch_err)
        elif submission.student and not submission.student.user_id:
            logger.warning(
                "submission_grade_save: skip MMR — student %s has no user_id (submission %s)",
                submission.student_id,
                submission_id,
            )

        db.session.commit()

        if not scores_only:
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
                'status': status,
                'scores_only': scores_only,
            }
        )

        return jsonify({
            'success': True,
            'total_score': total_score,
            'max_score': max_score,
            'percentage': submission.percentage,
            'scores_only': scores_only,
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

    if not _can_current_user_comment_submission(submission):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    scope = get_user_scope(current_user)
        
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
            created_at=utc_now()
        )
        db.session.add(comment)
        db.session.commit()

        try:
            author = current_user
            is_teacher = not getattr(current_user, 'is_student', lambda: False)()
            if is_teacher and submission.student and submission.student.user_id:
                notify_user_by_id(
                    int(submission.student.user_id),
                    (
                        f'💬 <b>Новый комментарий к работе</b>\n\n'
                        f'{text}\n'
                        f'\n🔗 {url_for("assignments.submission_view", submission_id=submission.submission_id)}'
                    ),
                    kind='lesson_comment',
                    reply_markup={'inline_keyboard': [[{'text': 'Открыть работу', 'url': url_for("assignments.submission_view", submission_id=submission.submission_id)}]]},
                )
            elif not is_teacher and submission.assignment.created_by_id:
                teacher = User.query.get(submission.assignment.created_by_id)
                teacher_profile = getattr(teacher, 'profile', None) if teacher else None
                if teacher_profile and teacher_profile.telegram_chat_id:
                    notify_user_by_id(
                        int(teacher.id),
                        (
                            f'💬 <b>Новый комментарий от ученика</b>\n\n'
                            f'{text}\n'
                            f'\n🔗 {url_for("assignments.submission_view", submission_id=submission.submission_id)}'
                        ),
                        kind='lesson_comment',
                        reply_markup={'inline_keyboard': [[{'text': 'Открыть работу', 'url': url_for("assignments.submission_view", submission_id=submission.submission_id)}]]},
                    )
        except Exception as notify_err:
            logger.warning('submission_comment_create notify failed: %s', notify_err)
        
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

    if not _can_current_user_access_submission(submission):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    legacy_bucket_task_id = _legacy_submission_comment_bucket_task_id(submission.assignment)
    assignment_task_id = request.args.get('assignment_task_id', type=int)
    if assignment_task_id is None:
        assignment_task_id = legacy_bucket_task_id
    if assignment_task_id is not None and not any(t.assignment_task_id == assignment_task_id for t in (submission.assignment.tasks or [])):
        return jsonify({'success': False, 'error': 'Задание не принадлежит этой работе'}), 400

    comments = []
    ordered = sorted((submission.comments or []), key=lambda c: (c.created_at or utc_now(), c.comment_id or 0))
    for comment in ordered:
        comment_task_id = _submission_comment_task_id(comment, legacy_bucket_task_id)
        if comment_task_id <= 0:
            continue

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

    max_in_thread = 0
    for c in ordered:
        if assignment_task_id is not None and _submission_comment_task_id(c, legacy_bucket_task_id) == assignment_task_id:
            max_in_thread = max(max_in_thread, int(c.comment_id or 0))

    if assignment_task_id is not None:
        try:
            _bump_submission_comment_thread_read(submission.submission_id, assignment_task_id, current_user.id, max_in_thread)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            try:
                _bump_submission_comment_thread_read(submission.submission_id, assignment_task_id, current_user.id, max_in_thread)
                db.session.commit()
            except Exception as ex:
                logger.warning('submission_comments_list thread read bump retry failed: %s', ex)
                try:
                    db.session.rollback()
                except Exception:
                    pass
        except Exception as ex:
            logger.warning('submission_comments_list thread read bump failed: %s', ex)
            try:
                db.session.rollback()
            except Exception:
                pass

    unread_task_ids = _compute_submission_chat_unread_task_ids(submission, current_user.id, legacy_bucket_task_id)

    return jsonify({
        'success': True,
        'comments': comments,
        'assignment_task_id': assignment_task_id,
        'unread_task_ids': sorted(unread_task_ids),
        'has_unread_student_comment': assignment_task_id in unread_task_ids if assignment_task_id is not None else False,
    }), 200


# ==========================================
# SANDBOX TASK DETAIL PAGE & API ENDPOINTS
# ==========================================

@assignments_bp.route('/sandbox/task_detail/<int:assignment_id>', methods=['GET'])
@login_required
def sandbox_task_detail_view(assignment_id: int):
    """Открытие каноничной 3D-страницы выполнения работы в формате sandbox."""
    assignment = Assignment.query.get_or_404(assignment_id)
    student = Student.query.filter_by(user_id=current_user.id).first()
    if not student:
        flash('Профиль ученика не найден', 'warning')
        return redirect(url_for('assignments.submissions_list'))
    
    sub = Submission.query.filter_by(assignment_id=assignment_id, student_id=student.student_id).first()
    if not sub:
        sub = Submission(assignment_id=assignment_id, student_id=student.student_id, status='ASSIGNED')
        db.session.add(sub)
        db.session.commit()
    
    return redirect(url_for('assignments.submission_view', submission_id=sub.submission_id))
