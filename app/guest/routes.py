"""Безопасные маршруты гостевого контура.

Гостевой токен всегда ограничивает запрос одной сессией и одним участником;
ни один endpoint не принимает произвольный student/task id без проверки связи.
"""
from datetime import timedelta
import hashlib
import secrets
from functools import wraps

from flask import (abort, current_app, jsonify, make_response, redirect,
                   render_template, request, send_file, url_for)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app.guest import guest_bp
from app import csrf
from app.models import (db, GuestActivity, GuestAttachment, GuestDrawing,
                        GuestParticipant, GuestResponse, GuestReview,
                        GuestSession, GuestTask, Student, User, UserRole, utc_now)
from app.auth.rbac_utils import require_role


SESSION_TYPES = {'INTRO_LESSON', 'TRIAL_EXAM'}
TRIAL_TEMPLATES = {
    'trial_python_start': {'title': 'Python с нуля', 'description': 'Переменные, ввод и условия'},
    'trial_algorithms': {'title': 'Алгоритмы КЕГЭ', 'description': 'Логика, циклы и проверка ответа'},
    'trial_mixed': {'title': 'Смешанная диагностика', 'description': 'Короткая диагностика по информатике'},
}
INTRO_TEMPLATES = {
    'intro_platform_tour': {'title': 'Знакомство с BooStudy', 'description': 'Программа, теория и первая задача'},
}


def _hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _task_specs(template_key):
    common = [
        {'type': 'choice', 'prompt': 'Какой тип хранит целое число в Python?', 'options': ['int', 'str', 'list', 'bool'], 'expected': 'int', 'skill': 'python.types'},
        {'type': 'short_text', 'prompt': 'Что выведет программа: print(2 + 3)?', 'options': [], 'expected': '5', 'skill': 'python.io'},
        {'type': 'boolean', 'prompt': 'Верно ли утверждение: 10 <= 10?', 'options': ['Да, утверждение верно', 'Нет, утверждение неверно'], 'expected': 'Да, утверждение верно', 'skill': 'python.conditions'},
        {'type': 'code', 'prompt': 'Напишите выражение, которое выводит число 4.', 'options': [], 'expected': '4', 'skill': 'python.expressions'},
        {'type': 'choice', 'prompt': 'Какой оператор используется для ветвления?', 'options': ['if', 'for', 'def', 'import'], 'expected': 'if', 'skill': 'python.conditions'},
    ]
    if template_key.startswith('intro_'):
        return common[:1] + [{'type': 'short_text', 'prompt': 'Какая страница открывает учебную программу?', 'options': [], 'expected': 'программа', 'skill': 'platform.program'}]
    return common * 4  # 20 вопросов в диагностике, ответы остаются снимком сессии


def _session_link(session, raw_token):
    return url_for('guest.join_session', token=raw_token, _external=True)


def _new_code():
    return secrets.token_urlsafe(6).replace('_', '').replace('-', '').upper()[:8]


def _session_by_token(raw_token):
    session_obj = GuestSession.query.filter_by(access_token_hash=_hash(raw_token)).first()
    if not session_obj:
        abort(404)
    expiry = session_obj.expires_at
    if expiry is not None and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=utc_now().tzinfo)
    if session_obj.status != 'active' or (expiry is not None and expiry < utc_now()):
        abort(410)
    return session_obj


def _guest_context(session_obj):
    raw = request.cookies.get(f'guest_session_{session_obj.id}')
    if not raw:
        return None
    participant = GuestParticipant.query.filter_by(session_id=session_obj.id, guest_token_hash=_hash(raw)).first()
    if participant:
        participant.last_seen_at = utc_now()
    return participant


def _event(session_obj, participant, name, payload=None):
    db.session.add(GuestActivity(session_id=session_obj.id, participant_id=getattr(participant, 'id', None), event=name, payload=payload or {}))


@guest_bp.get('/teacher/guest-sessions')
@require_role('tutor', 'creator', 'admin', 'chief_admin')
def teacher_sessions():
    status = request.args.get('status')
    kind = request.args.get('type')
    query = GuestSession.query.filter_by(teacher_id=current_user.id)
    if status:
        query = query.filter_by(status=status)
    if kind in SESSION_TYPES:
        query = query.filter_by(session_type=kind)
    sessions = query.order_by(GuestSession.created_at.desc()).all()
    return render_template('guest/teacher_sessions.html', sessions=sessions, trial_templates=TRIAL_TEMPLATES, intro_templates=INTRO_TEMPLATES)


@guest_bp.get('/teacher/guest-sessions/<int:session_id>')
@require_role('tutor', 'creator', 'admin', 'chief_admin')
def teacher_session_detail(session_id):
    item = GuestSession.query.filter_by(id=session_id, teacher_id=current_user.id).first_or_404()
    return render_template('guest/teacher_detail.html', guest_session=item)


@guest_bp.post('/teacher/guest-sessions')
@require_role('tutor', 'creator', 'admin', 'chief_admin')
def create_session():
    data = request.get_json(silent=True) or request.form
    session_type = str(data.get('session_type', 'TRIAL_EXAM')).upper()
    template_key = str(data.get('template_key', 'trial_python_start'))
    if session_type not in SESSION_TYPES:
        return jsonify(error='Неверный тип гостевой сессии'), 400
    catalog = INTRO_TEMPLATES if session_type == 'INTRO_LESSON' else TRIAL_TEMPLATES
    if template_key not in catalog:
        return jsonify(error='Шаблон не найден'), 400
    raw_token = secrets.token_urlsafe(32)
    expires = utc_now() + timedelta(hours=24 if session_type == 'INTRO_LESSON' else 24 * 7)
    session_obj = GuestSession(teacher_id=current_user.id, session_type=session_type, access_code=_new_code(), access_token_hash=_hash(raw_token), template_key=template_key, expires_at=expires, settings={'title': catalog[template_key]['title']})
    db.session.add(session_obj)
    db.session.flush()
    for position, spec in enumerate(_task_specs(template_key), start=1):
        db.session.add(GuestTask(session_id=session_obj.id, position=position, task_type=spec['type'], prompt=spec['prompt'], options=spec['options'], expected_answer=spec['expected'], skill_key=spec['skill'], metadata_json={'template': template_key}))
    _event(session_obj, None, 'session.created', {'type': session_type, 'template': template_key})
    db.session.commit()
    return jsonify(id=session_obj.id, code=session_obj.access_code, link=_session_link(session_obj, raw_token), expires_at=session_obj.expires_at.isoformat())


@guest_bp.post('/teacher/guest-sessions/<int:session_id>/close')
@require_role('tutor', 'creator', 'admin', 'chief_admin')
def close_session(session_id):
    item = GuestSession.query.filter_by(id=session_id, teacher_id=current_user.id).first_or_404()
    item.status = 'closed'
    item.closed_at = utc_now()
    db.session.commit()
    return jsonify(status=item.status)


@guest_bp.post('/guest/s/<token>/onboarding')
@csrf.exempt
def save_onboarding(token):
    item, participant = _require_guest(token)
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify(error='Некорректные данные онбординга'), 400
    state = participant.onboarding_state if isinstance(participant.onboarding_state, dict) else {}
    state.update({str(key): value for key, value in payload.items() if str(key)[:40]})
    participant.onboarding_state = state
    _event(item, participant, 'onboarding.updated', {'keys': list(payload.keys())[:20]})
    db.session.commit()
    return jsonify(saved=True, onboarding_state=state)


@guest_bp.get('/guest/s/<token>')
def join_session(token):
    item = _session_by_token(token)
    participant = _guest_context(item)
    if participant:
        return redirect(url_for('guest.guest_workspace', token=token))
    return render_template('guest/join.html', guest_session=item, token=token)


@guest_bp.post('/guest/s/<token>/join')
@csrf.exempt
def join_session_post(token):
    item = _session_by_token(token)
    participant = _guest_context(item)
    if participant:
        return jsonify(link=url_for('guest.guest_workspace', token=token))
    name = str((request.get_json(silent=True) or request.form).get('display_name', '')).strip()
    if not 2 <= len(name) <= 160:
        return jsonify(error='Укажите имя от 2 до 160 символов'), 400
    if len(item.participants) >= item.max_participants:
        return jsonify(error='Лимит участников этой сессии исчерпан'), 409
    raw_participant_token = secrets.token_urlsafe(32)
    participant = GuestParticipant(session_id=item.id, display_name=name, guest_token_hash=_hash(raw_participant_token), onboarding_state={'completed': False})
    db.session.add(participant)
    db.session.flush()
    _event(item, participant, 'participant.joined', {'display_name': name})
    db.session.commit()
    response = jsonify(link=url_for('guest.guest_workspace', token=token))
    response.set_cookie(f'guest_session_{item.id}', raw_participant_token, max_age=7 * 86400, httponly=True, samesite='Lax')
    return response


def _require_guest(token):
    item = _session_by_token(token)
    participant = _guest_context(item)
    if not participant:
        abort(401)
    if participant.status == 'submitted':
        return item, participant
    return item, participant


@guest_bp.get('/guest/s/<token>/work')
def guest_workspace(token):
    item, participant = _require_guest(token)
    return render_template('guest/workspace.html', guest_session=item, participant=participant, token=token)


@guest_bp.get('/guest/s/<token>/result')
def guest_result(token):
    item, participant = _require_guest(token)
    review = GuestReview.query.filter_by(session_id=item.id, participant_id=participant.id).first()
    return render_template('guest/result.html', guest_session=item, participant=participant, review=review, token=token)


@guest_bp.post('/guest/s/<token>/api/responses/<int:task_id>')
@csrf.exempt
def save_response(token, task_id):
    item, participant = _require_guest(token)
    if participant.status == 'submitted':
        return jsonify(error='Сессия уже отправлена'), 409
    task = GuestTask.query.filter_by(id=task_id, session_id=item.id).first()
    if not task:
        abort(404)
    data = request.get_json(silent=True) or {}
    response_obj = GuestResponse.query.filter_by(participant_id=participant.id, task_id=task.id).first()
    if not response_obj:
        response_obj = GuestResponse(participant_id=participant.id, task_id=task.id)
        db.session.add(response_obj)
    response_obj.answer_text = str(data.get('answer_text', ''))[:20000]
    response_obj.answer_json = data.get('answer_json') if isinstance(data.get('answer_json'), (dict, list)) else None
    response_obj.comment = str(data.get('comment', ''))[:4000]
    response_obj.flagged = bool(data.get('flagged', False))
    _event(item, participant, 'response.saved', {'task_id': task.id})
    db.session.commit()
    return jsonify(saved=True, response_id=response_obj.id)


@guest_bp.post('/guest/s/<token>/api/responses/<int:task_id>/drawing')
@csrf.exempt
def save_drawing(token, task_id):
    item, participant = _require_guest(token)
    task = GuestTask.query.filter_by(id=task_id, session_id=item.id).first_or_404()
    response_obj = GuestResponse.query.filter_by(participant_id=participant.id, task_id=task.id).first()
    if not response_obj:
        response_obj = GuestResponse(participant_id=participant.id, task_id=task.id)
        db.session.add(response_obj)
        db.session.flush()
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict) or len(str(payload)) > 2_000_000:
        return jsonify(error='Некорректный рисунок'), 400
    db.session.add(GuestDrawing(response_id=response_obj.id, payload=payload))
    db.session.commit()
    return jsonify(saved=True)


@guest_bp.get('/guest/s/<token>/api/responses/<int:task_id>/drawing')
def latest_drawing(token, task_id):
    item, participant = _require_guest(token)
    task = GuestTask.query.filter_by(id=task_id, session_id=item.id).first_or_404()
    response_obj = GuestResponse.query.filter_by(participant_id=participant.id, task_id=task.id).first()
    drawing = (GuestDrawing.query.filter_by(response_id=response_obj.id)
               .order_by(GuestDrawing.created_at.desc(), GuestDrawing.id.desc()).first()) if response_obj else None
    return jsonify(drawing=drawing.payload if drawing else None)


@guest_bp.post('/guest/s/<token>/api/responses/<int:task_id>/files')
@csrf.exempt
def upload_file(token, task_id):
    item, participant = _require_guest(token)
    task = GuestTask.query.filter_by(id=task_id, session_id=item.id).first_or_404()
    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify(error='Файл не выбран'), 400
    file.stream.seek(0, 2)
    size = file.stream.tell()
    file.stream.seek(0)
    max_size = int(current_app.config.get('GUEST_MAX_FILE_BYTES', 10 * 1024 * 1024))
    if size > max_size:
        return jsonify(error='Файл превышает допустимый размер'), 413
    response_obj = GuestResponse.query.filter_by(participant_id=participant.id, task_id=task.id).first()
    if not response_obj:
        response_obj = GuestResponse(participant_id=participant.id, task_id=task.id)
        db.session.add(response_obj)
        db.session.flush()
    root = current_app.config.get('GUEST_UPLOAD_ROOT') or current_app.instance_path
    import os
    os.makedirs(root, exist_ok=True)
    storage_key = f'guest/{item.id}/{participant.id}/{secrets.token_hex(12)}_{secure_filename(file.filename)}'
    absolute = os.path.join(root, storage_key)
    os.makedirs(os.path.dirname(absolute), exist_ok=True)
    file.save(absolute)
    db.session.add(GuestAttachment(response_id=response_obj.id, original_name=secure_filename(file.filename), storage_key=storage_key, mime_type=file.mimetype or 'application/octet-stream', size_bytes=size))
    db.session.commit()
    return jsonify(saved=True, name=secure_filename(file.filename), size=size)


@guest_bp.get('/teacher/guest-sessions/<int:session_id>/participants/<int:participant_id>/responses/<int:response_id>/files/<int:attachment_id>')
@require_role('tutor', 'creator', 'admin', 'chief_admin')
def teacher_attachment(session_id, participant_id, response_id, attachment_id):
    item = GuestSession.query.filter_by(id=session_id, teacher_id=current_user.id).first_or_404()
    participant = GuestParticipant.query.filter_by(id=participant_id, session_id=item.id).first_or_404()
    response_obj = GuestResponse.query.filter_by(id=response_id, participant_id=participant.id).first_or_404()
    attachment = GuestAttachment.query.filter_by(id=attachment_id, response_id=response_obj.id).first_or_404()
    import os
    root = current_app.config.get('GUEST_UPLOAD_ROOT') or current_app.instance_path
    absolute = os.path.abspath(os.path.join(root, attachment.storage_key))
    if not absolute.startswith(os.path.abspath(root) + os.sep) or not os.path.isfile(absolute):
        abort(404)
    return send_file(absolute, as_attachment=False, download_name=attachment.original_name, mimetype=attachment.mime_type)


@guest_bp.post('/guest/s/<token>/submit')
@csrf.exempt
def submit_session(token):
    item, participant = _require_guest(token)
    if participant.status == 'submitted':
        review = GuestReview.query.filter_by(session_id=item.id, participant_id=participant.id).first()
        return jsonify(status='submitted', result_url=url_for('guest.guest_result', token=token), total_score=getattr(review, 'total_score', None))
    responses = GuestResponse.query.filter_by(participant_id=participant.id).all()
    for response_obj in responses:
        response_obj.status = 'submitted'
        response_obj.submitted_at = utc_now()
        expected = (response_obj.task.expected_answer or '').strip().lower()
        actual = (response_obj.answer_text or '').strip().lower()
        if response_obj.task.task_type in {'choice', 'boolean', 'short_text'}:
            response_obj.score = response_obj.task.max_score if actual == expected else 0
            response_obj.auto_checked = True
    participant.status = 'submitted'
    participant.submitted_at = utc_now()
    total = sum((r.score or 0) for r in responses)
    maximum = sum(r.task.max_score for r in responses) if responses else sum(t.max_score for t in item.tasks)
    review = GuestReview.query.filter_by(session_id=item.id, participant_id=participant.id).first()
    if not review:
        review = GuestReview(session_id=item.id, participant_id=participant.id)
        db.session.add(review)
    review.status = 'pending'
    review.total_score = total
    review.max_score = maximum
    _event(item, participant, 'session.submitted', {'total_score': total, 'max_score': maximum})
    db.session.commit()
    return jsonify(status='submitted', result_url=url_for('guest.guest_result', token=token), total_score=total, max_score=maximum)


@guest_bp.post('/teacher/guest-sessions/<int:session_id>/participants/<int:participant_id>/review')
@require_role('tutor', 'creator', 'admin', 'chief_admin')
def review_participant(session_id, participant_id):
    item = GuestSession.query.filter_by(id=session_id, teacher_id=current_user.id).first_or_404()
    participant = GuestParticipant.query.filter_by(id=participant_id, session_id=item.id).first_or_404()
    data = request.get_json(silent=True) or request.form
    for value in data.get('responses', []) if isinstance(data.get('responses'), list) else []:
        response_obj = GuestResponse.query.filter_by(id=value.get('id'), participant_id=participant.id).first()
        if response_obj:
            response_obj.score = max(0, min(response_obj.task.max_score, int(value.get('score', 0))))
            response_obj.teacher_comment = str(value.get('teacher_comment', ''))[:4000]
            response_obj.status = 'graded'
            response_obj.graded_at = utc_now()
    review = GuestReview.query.filter_by(session_id=item.id, participant_id=participant.id).first()
    if not review:
        review = GuestReview(session_id=item.id, participant_id=participant.id)
        db.session.add(review)
    review.status = 'completed'
    review.recommendation = str(data.get('recommendation', ''))[:4000]
    review.teacher_comment = str(data.get('teacher_comment', ''))[:4000]
    review.total_score = sum((r.score or 0) for r in participant.responses)
    review.max_score = sum(r.task.max_score for r in participant.responses) or sum(t.max_score for t in item.tasks)
    review.completed_at = utc_now()
    db.session.commit()
    return jsonify(status='completed', total_score=review.total_score, max_score=review.max_score)


@guest_bp.post('/teacher/guest-sessions/<int:session_id>/participants/<int:participant_id>/convert')
@require_role('tutor', 'creator', 'admin', 'chief_admin')
def convert_participant(session_id, participant_id):
    item = GuestSession.query.filter_by(id=session_id, teacher_id=current_user.id).first_or_404()
    participant = GuestParticipant.query.filter_by(id=participant_id, session_id=item.id).first_or_404()
    if participant.converted_student_id:
        return jsonify(status='converted', student_id=participant.converted_student_id)
    base = ''.join(ch.lower() if ch.isalnum() else '_' for ch in participant.display_name).strip('_') or 'guest'
    username = f'guest_{participant.id}_{base[:32]}'
    user = User(username=username, email=f'{username}@guest.local', role='student', is_active=True)
    user.set_password(secrets.token_urlsafe(24))
    db.session.add(user)
    db.session.flush()
    db.session.add(UserRole(user_id=user.id, role='student'))
    student = Student(name=participant.display_name, user_id=user.id, mentor_id=item.teacher_id, is_active=True, email=user.email)
    db.session.add(student)
    db.session.flush()
    participant.converted_student_id = student.student_id
    participant.status = 'converted'
    _event(item, participant, 'participant.converted', {'student_id': student.student_id})
    db.session.commit()
    return jsonify(status='converted', student_id=student.student_id, username=username)
