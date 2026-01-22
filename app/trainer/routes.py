from __future__ import annotations

import logging
import os
from urllib.parse import urlencode
from typing import Any

from flask import render_template, request, abort, jsonify
from flask_login import login_required, current_user

from app.trainer import trainer_bp
from app.auth.rbac_utils import has_permission
from app.auth.permissions import ALL_PERMISSIONS
from app.models import db, User, Tasks, Student, Lesson, LessonTask, TrainerSession, StudentTaskSeen
from app.utils.trainer_tokens import issue_trainer_token, verify_trainer_token, TrainerTokenError
from core.audit_logger import audit_logger
from app import csrf

logger = logging.getLogger(__name__)


def _extract_trainer_token_from_request() -> str:
    # Header takes priority
    h = (request.headers.get('X-Trainer-Token') or '').strip()
    if h:
        return h
    auth = (request.headers.get('Authorization') or '').strip()
    if auth.lower().startswith('bearer '):
        return auth.split(' ', 1)[1].strip()
    # Fallback to JSON token field
    data = request.get_json(silent=True) or {}
    if isinstance(data, dict) and data.get('token'):
        return str(data.get('token')).strip()
    # Query param (for convenience)
    q = (request.args.get('token') or '').strip()
    return q


def _get_trainer_user_from_token(require_permission: str | None = 'trainer.use') -> User:
    token = _extract_trainer_token_from_request()
    if not token:
        abort(401)
    try:
        payload = verify_trainer_token(token, audience='trainer')
    except TrainerTokenError:
        abort(401)

    user_id = payload.get('sub')
    try:
        user_id_int = int(user_id)
    except Exception:
        abort(401)

    user = User.query.get(user_id_int)
    if not user or not getattr(user, 'is_active', True):
        abort(401)

    if require_permission and (not has_permission(user, require_permission)):
        abort(403)

    return user


def _task_to_payload(task: Tasks) -> dict[str, Any] | None:
    if not task:
        return None
    return {
        'task_id': task.task_id,
        'task_number': task.task_number,
        'site_task_id': task.site_task_id,
        'source_url': task.source_url,
        'content_html': task.content_html,
        'answer': task.answer,
        'attached_files': task.attached_files,
    }


def _map_user_to_student(user: User) -> Student | None:
    """
    Привязываем Users (auth) -> Students (lesson system).
    В большинстве окружений делаем по email, fallback: Student.student_id == User.id.
    """
    if not user:
        return None
    ident = (getattr(user, 'email', None) or getattr(user, 'username', None) or '').strip()
    if ident:
        try:
            st = Student.query.filter(db.func.lower(Student.email) == ident.lower()).first()
            if st:
                return st
        except Exception:
            pass
    try:
        st = Student.query.get(int(user.id))
        return st
    except Exception:
        return None


def _record_student_task_seen(*, student_id: int, task_id: int, source: str) -> None:
    """Best-effort: record that a student has seen a task (dedup across trainer/lessons)."""
    try:
        student_id_int = int(student_id)
        task_id_int = int(task_id)
    except Exception:
        return
    try:
        exists = StudentTaskSeen.query.filter_by(student_id=student_id_int, task_id=task_id_int).first()
        if exists:
            return
        db.session.add(StudentTaskSeen(student_id=student_id_int, task_id=task_id_int, source=(source or '')[:40] or None))
        db.session.commit()
    except Exception:
        db.session.rollback()
        return


@trainer_bp.route('/trainer')
@login_required
def trainer_embed():
    if not has_permission(current_user, 'trainer.use'):
        abort(403)

    trainer_url = (os.environ.get('TRAINER_URL') or '').strip()
    if not trainer_url:
        return render_template('trainer_embed.html', trainer_url=None, iframe_url=None, config_error='TRAINER_URL не задан')

    try:
        token = issue_trainer_token(user_id=current_user.id, ttl_seconds=10 * 60)
    except Exception as e:
        return render_template('trainer_embed.html', trainer_url=trainer_url, iframe_url=None, config_error=str(e))

    # Forward a few optional query params into the iframe URL
    passthrough = {}
    for k in ('lesson_id', 'task_id', 'task_type', 'template_id', 'assignment_type'):
        v = (request.args.get(k) or '').strip()
        if v:
            passthrough[k] = v

    # Always include token as query param (Streamlit runs in separate origin)
    qs = urlencode({'token': token, **passthrough})
    iframe_url = f"{trainer_url.rstrip('/')}/?{qs}"

    try:
        audit_logger.log(action='trainer_open', entity='Trainer', entity_id=current_user.id, status='success')
    except Exception:
        pass

    return render_template('trainer_embed.html', trainer_url=trainer_url, iframe_url=iframe_url, config_error=None)


# -----------------------------
# Internal API for Streamlit
# -----------------------------

@trainer_bp.route('/internal/trainer/token/validate', methods=['POST'])
@csrf.exempt
def trainer_token_validate():
    user = _get_trainer_user_from_token(require_permission=None)
    return jsonify({
        'success': True,
        'user': {
            'id': user.id,
            'username': user.username,
            'role': user.role,
        },
        'permissions': [k for k in ALL_PERMISSIONS.keys() if has_permission(user, k)],
    })


@trainer_bp.route('/internal/trainer/me', methods=['GET'])
def trainer_me():
    user = _get_trainer_user_from_token(require_permission='trainer.use')
    # Return only minimal data; permissions are computed on demand.
    perms = [k for k in ALL_PERMISSIONS.keys() if has_permission(user, k)]
    return jsonify({'success': True, 'user': {'id': user.id, 'username': user.username, 'role': user.role}, 'permissions': perms})


@trainer_bp.route('/internal/trainer/task/<int:task_id>', methods=['GET'])
def trainer_task_get(task_id: int):
    _ = _get_trainer_user_from_token(require_permission='trainer.use')
    task = Tasks.query.filter_by(task_id=task_id).first()
    if not task:
        return jsonify({'success': False, 'error': 'task_not_found'}), 404
    return jsonify({'success': True, 'task': _task_to_payload(task)})


@trainer_bp.route('/internal/trainer/task/stats', methods=['GET'])
def trainer_task_stats():
    _ = _get_trainer_user_from_token(require_permission='trainer.use')
    rows = (
        db.session.query(Tasks.task_number, db.func.count(Tasks.task_id))
        .group_by(Tasks.task_number)
        .order_by(Tasks.task_number.asc())
        .all()
    )
    counts = {int(n): int(c) for (n, c) in rows if n is not None}
    return jsonify({'success': True, 'counts_by_task_number': counts})


@trainer_bp.route('/internal/trainer/task/stream/start', methods=['POST'])
@csrf.exempt
def trainer_stream_start():
    user = _get_trainer_user_from_token(require_permission='trainer.use')
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'bad_request'}), 400

    try:
        task_type = int(data.get('task_type'))
    except Exception:
        return jsonify({'success': False, 'error': 'task_type_required'}), 400

    st = _map_user_to_student(user) if getattr(user, 'role', None) == 'student' else None

    # Optional: pin a specific task_id
    task_id = data.get('task_id')
    pinned_task: Tasks | None = None
    if task_id not in (None, ''):
        try:
            pinned_id = int(task_id)
            pinned_task = Tasks.query.filter_by(task_id=pinned_id).first()
        except Exception:
            pinned_task = None

    # Optional: exclude already seen tasks (avoid repeats within a session)
    exclude_ids: list[int] = []
    raw_exclude = data.get('exclude_task_ids')
    if isinstance(raw_exclude, list):
        for v in raw_exclude[:200]:
            try:
                exclude_ids.append(int(v))
            except Exception:
                continue

    task: Tasks | None = None
    if pinned_task and int(getattr(pinned_task, 'task_number', 0) or 0) == task_type:
        task = pinned_task
    else:
        q = Tasks.query.filter(Tasks.task_number == task_type)
        if exclude_ids:
            q = q.filter(~Tasks.task_id.in_(exclude_ids))
        # Anti-repeat with lessons and trainer history for this student
        if st:
            q = q.filter(~Tasks.task_id.in_(
                db.session.query(LessonTask.task_id).join(Lesson).filter(Lesson.student_id == st.student_id)
            ))
            q = q.filter(~Tasks.task_id.in_(
                db.session.query(StudentTaskSeen.task_id).filter(StudentTaskSeen.student_id == st.student_id)
            ))
        task = q.order_by(db.func.random()).first()

    if st and task:
        _record_student_task_seen(student_id=st.student_id, task_id=task.task_id, source='trainer')

    try:
        audit_logger.log(action='trainer_stream_start', entity='Trainer', entity_id=user.id, status='success', metadata={'task_type': task_type, 'has_task': bool(task)})
    except Exception:
        pass

    return jsonify({'success': True, 'done': not bool(task), 'task': _task_to_payload(task)})


@trainer_bp.route('/internal/trainer/task/stream/act', methods=['POST'])
@csrf.exempt
def trainer_stream_act():
    user = _get_trainer_user_from_token(require_permission='trainer.use')
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'bad_request'}), 400

    action = (data.get('action') or '').strip()
    if action not in ('next',):
        return jsonify({'success': False, 'error': 'unknown_action'}), 400

    try:
        task_type = int(data.get('task_type'))
    except Exception:
        return jsonify({'success': False, 'error': 'task_type_required'}), 400

    st = _map_user_to_student(user) if getattr(user, 'role', None) == 'student' else None

    # Optional: exclude already seen tasks (avoid repeats within a session)
    exclude_ids: list[int] = []
    raw_exclude = data.get('exclude_task_ids')
    if isinstance(raw_exclude, list):
        for v in raw_exclude[:200]:
            try:
                exclude_ids.append(int(v))
            except Exception:
                continue

    q = Tasks.query.filter(Tasks.task_number == task_type)
    if exclude_ids:
        q = q.filter(~Tasks.task_id.in_(exclude_ids))
    if st:
        q = q.filter(~Tasks.task_id.in_(
            db.session.query(LessonTask.task_id).join(Lesson).filter(Lesson.student_id == st.student_id)
        ))
        q = q.filter(~Tasks.task_id.in_(
            db.session.query(StudentTaskSeen.task_id).filter(StudentTaskSeen.student_id == st.student_id)
        ))
    task = q.order_by(db.func.random()).first()
    if st and task:
        _record_student_task_seen(student_id=st.student_id, task_id=task.task_id, source='trainer')
    try:
        audit_logger.log(action='trainer_stream_next', entity='Trainer', entity_id=user.id, status='success', metadata={'task_type': task_type, 'has_task': bool(task)})
    except Exception:
        pass
    return jsonify({'success': True, 'done': not bool(task), 'task': _task_to_payload(task)})


@trainer_bp.route('/internal/trainer/session/save', methods=['POST'])
@csrf.exempt
def trainer_session_save():
    user = _get_trainer_user_from_token(require_permission='trainer.use')
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'bad_request'}), 400

    # Store attempt in DB (and keep audit log as a baseline).
    try:
        task_id = int(data.get('task_id')) if data.get('task_id') not in (None, '') else None
    except Exception:
        task_id = None
    code = (data.get('code') or '')
    if isinstance(code, str) and len(code) > 20000:
        code = code[:20000]

    # Persist to TrainerSessions
    try:
        st = _map_user_to_student(user)
        sess = TrainerSession(
            user_id=user.id,
            student_id=(st.student_id if st else None),
            task_id=task_id,
            task_type=int(data.get('task_type')) if data.get('task_type') not in (None, '') else None,
            language=(data.get('language') or 'python'),
            code=code if isinstance(code, str) else None,
            analysis=data.get('analysis'),
            tests=data.get('tests'),
            messages=data.get('messages'),
        )
        db.session.add(sess)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.warning(f"trainer_session_save db failed: {e}")

    try:
        audit_logger.log(
            action='trainer_session_save',
            entity='TrainerSession',
            entity_id=task_id,
            status='success',
            metadata={
                'user_id': user.id,
                'task_id': task_id,
                'lang': (data.get('language') or 'python'),
                'code_len': len(code) if isinstance(code, str) else None,
                'analysis': data.get('analysis'),
                'tests': data.get('tests'),
            },
        )
    except Exception as e:
        logger.warning(f"trainer_session_save audit log failed: {e}")

    return jsonify({'success': True})


@trainer_bp.route('/internal/trainer/session/list', methods=['GET'])
def trainer_session_list():
    user = _get_trainer_user_from_token(require_permission='trainer.use')
    limit = request.args.get('limit', default=25, type=int) or 25
    limit = max(1, min(int(limit), 100))
    q = TrainerSession.query.filter_by(user_id=user.id).order_by(TrainerSession.created_at.desc(), TrainerSession.session_id.desc()).limit(limit)
    out = []
    for s in q.all():
        out.append({
            'session_id': s.session_id,
            'task_id': s.task_id,
            'task_type': s.task_type,
            'language': s.language,
            'created_at': s.created_at.isoformat() if s.created_at else None,
            'code_len': len(s.code) if isinstance(s.code, str) else 0,
        })
    return jsonify({'success': True, 'sessions': out})


@trainer_bp.route('/internal/trainer/session/<int:session_id>', methods=['GET'])
def trainer_session_get(session_id: int):
    user = _get_trainer_user_from_token(require_permission='trainer.use')
    s = TrainerSession.query.filter_by(session_id=int(session_id), user_id=user.id).first()
    if not s:
        return jsonify({'success': False, 'error': 'not_found'}), 404
    task = Tasks.query.filter_by(task_id=s.task_id).first() if s.task_id else None
    return jsonify({
        'success': True,
        'session': {
            'session_id': s.session_id,
            'task_id': s.task_id,
            'task_type': s.task_type,
            'language': s.language,
            'code': s.code,
            'analysis': s.analysis,
            'tests': s.tests,
            'messages': s.messages,
            'created_at': s.created_at.isoformat() if s.created_at else None,
        },
        'task': _task_to_payload(task) if task else None,
    })

