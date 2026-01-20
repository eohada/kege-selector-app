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
from app.models import db, User, Tasks
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
    for k in ('lesson_id', 'task_type', 'template_id', 'assignment_type'):
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

    # MVP: no cross-lesson side-effects; just select a random task by type
    task = Tasks.query.filter(Tasks.task_number == task_type).order_by(db.func.random()).first()

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

    task = Tasks.query.filter(Tasks.task_number == task_type).order_by(db.func.random()).first()
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

    # MVP: store minimal attempt data in AuditLog (safe baseline). DB model will be added in the next step.
    try:
        task_id = int(data.get('task_id')) if data.get('task_id') not in (None, '') else None
    except Exception:
        task_id = None
    code = (data.get('code') or '')
    if isinstance(code, str) and len(code) > 20000:
        code = code[:20000]

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

