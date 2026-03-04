from __future__ import annotations

import logging
import os
from urllib.parse import urlencode
from typing import Any

from flask import render_template, request, abort, jsonify, send_file
from flask_login import login_required, current_user

from app.trainer import trainer_bp
from app.auth.rbac_utils import has_permission
from app.auth.permissions import ALL_PERMISSIONS
from app.models import (
    db, User, Tasks, Student, Lesson, LessonTask, TrainerSession,
    StudentTaskSeen, AuditLog, TrainerLlmLog, moscow_now,
    UserMastery, KnowledgeNode, AnalyticsEvent, Course, CourseTaskTemplate
)
from app.analytics.engine import AnalyticsEngine
from app.utils.trainer_tokens import issue_trainer_token, verify_trainer_token, TrainerTokenError
from app.utils.course_tasks import get_task_numbers
from app.lessons.utils import normalize_answer_value
import re
from core.audit_logger import audit_logger
from app import csrf

logger = logging.getLogger(__name__)


def _extract_trainer_token_from_request() -> str:
    h = (request.headers.get('X-Trainer-Token') or '').strip()
    if h:
        return h
    auth = (request.headers.get('Authorization') or '').strip()
    if auth.lower().startswith('bearer '):
        return auth.split(' ', 1)[1].strip()
    data = request.get_json(silent=True) or {}
    if isinstance(data, dict) and data.get('token'):
        return str(data.get('token')).strip()
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
    hints_raw = getattr(task, 'hints', None)
    has_hints = bool(hints_raw) and (isinstance(hints_raw, list) and len(hints_raw) > 0 or isinstance(hints_raw, dict))
    return {
        'task_id': task.task_id,
        'task_number': task.task_number,
        'site_task_id': task.site_task_id,
        'source_url': task.source_url,
        'content_html': task.content_html,
        'answer': task.answer,
        'attached_files': task.attached_files,
        'has_hints_in_db': has_hints,
    }


def _map_user_to_student(user: User) -> Student | None:
    """Привязка User -> Student по user_id, platform_id или legacy student_id."""
    if not user:
        return None
    st = Student.query.filter_by(user_id=user.id).first()
    if st:
        return st
    if (user.username or '').strip():
        try:
            st = Student.query.filter(Student.platform_id == (user.username or '').strip()).first()
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


def _audit_log_token_user(
    user: User,
    *,
    action: str,
    status: str = 'success',
    entity: str | None = None,
    entity_id: int | None = None,
    metadata: dict[str, Any] | None = None,
    duration_ms: int | None = None,
) -> None:
    """
    Пишем AuditLog напрямую (без Flask-Login), т.к. внутренний trainer API авторизуется токеном.
    Best-effort: ошибки логирования не должны ломать основной ответ.
    """
    try:
        al = AuditLog()
        al.timestamp = moscow_now()
        al.user_id = user.id
        al.tester_name = user.username
        al.action = (action or 'unknown')[:50]
        al.entity = (entity or 'TrainerLLM')[:50] if (entity or 'TrainerLLM') else None
        al.entity_id = entity_id
        al.status = (status or 'success')[:20]
        try:
            al.set_metadata(metadata or {})
        except Exception:
            al.meta_data = None
        try:
            al.ip_address = request.remote_addr
            al.user_agent = request.headers.get('User-Agent')
            al.url = request.url
            al.method = request.method
        except Exception:
            pass
        al.duration_ms = duration_ms
        db.session.add(al)
        db.session.commit()
    except Exception:
        db.session.rollback()
        return


@trainer_bp.route('/trainer', strict_slashes=False)
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

    passthrough = {}
    for k in ('lesson_id', 'task_id', 'task_type', 'template_id', 'assignment_type', 'course_id'):
        v = (request.args.get(k) or '').strip()
        if v:
            passthrough[k] = v

    qs = urlencode({'token': token, **passthrough})
    iframe_url = f"{trainer_url.rstrip('/')}/?{qs}"

    try:
        audit_logger.log(action='trainer_open', entity='Trainer', entity_id=current_user.id, status='success')
    except Exception:
        pass

    return render_template('trainer_embed.html', trainer_url=trainer_url, iframe_url=iframe_url, config_error=None)


@trainer_bp.route('/trainer/v2', strict_slashes=False)
@login_required
def trainer_v2():
    """
    Trainer v2 UI (без Streamlit): полноценный фронтенд внутри платформы.

    Внутренние trainer api авторизуются токеном (X-Trainer-Token / Bearer),
    поэтому выдаём короткоживущий токен и прокидываем его в шаблон.
    """
    if not has_permission(current_user, 'trainer.use'):
        abort(403)

    try:
        token = issue_trainer_token(user_id=current_user.id, ttl_seconds=10 * 60)
    except Exception as e:
        return render_template('trainer_v2.html', trainer_token=None, config_error=str(e), zen_mode=False, passthrough={}, task_numbers=get_task_numbers(None))

    passthrough = {}
    for k in ('lesson_id', 'task_id', 'task_type', 'template_id', 'assignment_type', 'course_id'):
        v = (request.args.get(k) or '').strip()
        if v:
            passthrough[k] = v

    zen_mode = (request.args.get('zen') or '').strip() in ('1', 'true', 'yes', 'on')

    try:
        audit_logger.log(action='trainer_v2_open', entity='Trainer', entity_id=current_user.id, status='success')
    except Exception:
        pass

    task_numbers = get_task_numbers(request.args.get('course_id', type=int))
    return render_template(
        'trainer_v2.html',
        trainer_token=token,
        config_error=None,
        zen_mode=zen_mode,
        passthrough=passthrough,
        active_page='trainer',
        task_numbers=task_numbers,
    )



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
    perms = [k for k in ALL_PERMISSIONS.keys() if has_permission(user, k)]
    return jsonify({'success': True, 'user': {'id': user.id, 'username': user.username, 'role': user.role}, 'permissions': perms})


@trainer_bp.route('/internal/trainer/llm/info', methods=['GET'])
def trainer_llm_info():
    _ = _get_trainer_user_from_token(require_permission='trainer.use')
    try:
        from trainer_app.llm.providers import get_llm_info
        return jsonify({'success': True, 'llm': get_llm_info()})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@trainer_bp.route('/internal/trainer/llm/diagnose', methods=['GET'])
@csrf.exempt
def trainer_llm_diagnose():
    """
    Диагностика LLM (GigaChat): проверка ключей (без вывода самих ключей) и тестовый запрос.
    GET ?test=1 — выполнить тестовый запрос.
    """
    _ = _get_trainer_user_from_token(require_permission='trainer.use')
    gigachat_creds = (os.environ.get('GIGACHAT_CREDENTIALS') or '').strip()
    gigachat_model = (os.environ.get('GIGACHAT_MODEL') or 'GigaChat').strip()

    diag = {
        'gigachat_key_set': bool(gigachat_creds),
        'gigachat_key_len': len(gigachat_creds),
        'gigachat_model': gigachat_model,
    }

    test = request.args.get('test', '').strip().lower() in ('1', 'true', 'yes')
    if test:
        try:
            from trainer_app.llm.providers import get_llm_client, get_llm_info
            info = get_llm_info()
            llm = get_llm_client()
            if not llm:
                diag['test_error'] = 'LLM не настроен: задайте GIGACHAT_CREDENTIALS в окружении'
            else:
                resp = llm.chat(
                    messages=[{'role': 'user', 'content': 'Ответь одним словом: OK'}],
                    temperature=0,
                    max_tokens=5,
                )
                diag['test_success'] = True
                diag['test_response'] = (resp or '')[:200]
                diag['test_provider'] = info.get('picked', {}).get('provider', 'unknown')
        except Exception as ex:
            diag['test_success'] = False
            diag['test_error'] = str(ex)[:500]

    return jsonify({'success': True, 'diagnose': diag})


@trainer_bp.route('/internal/trainer/llm/ping', methods=['POST'])
@csrf.exempt
def trainer_llm_ping():
    user = _get_trainer_user_from_token(require_permission='trainer.use')
    try:
        from trainer_app.llm.providers import get_llm_client, get_llm_info
        import time

        started = time.time()
        info = get_llm_info()
        llm = get_llm_client()
        if not llm:
            _audit_log_token_user(user, action='trainer_llm_ping', status='error', metadata={'error': 'not_configured', 'llm': info})
            return jsonify({'success': False, 'error': 'not_configured', 'llm': info}), 400

        ans = llm.chat(
            messages=[{'role': 'system', 'content': 'Answer with a single word OK.'}, {'role': 'user', 'content': 'ping'}],
            temperature=0.0,
            max_tokens=5,
        )
        duration_ms = int((time.time() - started) * 1000)
        try:
            picked = (info.get('picked') or {}) if isinstance(info, dict) else {}
            st = _map_user_to_student(user) if getattr(user, 'role', None) == 'student' else None
            rec = TrainerLlmLog(
                user_id=user.id,
                student_id=(st.student_id if st else None),
                task_id=None,
                task_type=None,
                request_kind='ping',
                provider=(picked.get('provider') if isinstance(picked, dict) else None),
                model=(picked.get('model') if isinstance(picked, dict) else None),
                messages=[{'role': 'system', 'content': 'Answer with a single word OK.'}, {'role': 'user', 'content': 'ping'}],
                answer=(str(ans)[:800] if ans is not None else None),
                error=None,
                duration_ms=duration_ms,
            )
            db.session.add(rec)
            db.session.commit()
        except Exception:
            db.session.rollback()

        _audit_log_token_user(
            user,
            action='trainer_llm_ping',
            status='success',
            metadata={'llm': info, 'answer_preview': (str(ans).strip()[:120])},
            duration_ms=duration_ms,
        )
        return jsonify({'success': True, 'answer': (str(ans).strip()[:300]), 'llm': info, 'duration_ms': duration_ms})
    except Exception as e:
        try:
            _audit_log_token_user(user, action='trainer_llm_ping', status='error', metadata={'error': str(e)[:500]})
        except Exception:
            pass
        return jsonify({'success': False, 'error': str(e)}), 500


@trainer_bp.route('/internal/trainer/llm/chat', methods=['POST'])
@csrf.exempt
def trainer_llm_chat():
    user = _get_trainer_user_from_token(require_permission='trainer.use')
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'bad_request'}), 400

    raw_msgs = data.get('messages')
    if not isinstance(raw_msgs, list) or not raw_msgs:
        return jsonify({'success': False, 'error': 'messages_required'}), 400

    messages: list[dict[str, str]] = []
    for m in raw_msgs[-24:]:
        if not isinstance(m, dict):
            continue
        role = str(m.get('role') or 'user').strip().lower()
        if role not in ('system', 'user', 'assistant'):
            role = 'user'
        content = str(m.get('content') or '')
        if len(content) > 4000:
            content = content[:4000] + ' …'
        if content.strip():
            messages.append({'role': role, 'content': content})
    if not messages:
        return jsonify({'success': False, 'error': 'messages_required'}), 400

    try:
        temperature = float(data.get('temperature', 0.2))
    except Exception:
        temperature = 0.2
    try:
        max_tokens = int(data.get('max_tokens', 700))
    except Exception:
        max_tokens = 700
    max_tokens = max(16, min(max_tokens, 1200))

    try:
        task_id = int(data.get('task_id')) if data.get('task_id') not in (None, '') else None
    except Exception:
        task_id = None
    try:
        task_type = int(data.get('task_type')) if data.get('task_type') not in (None, '') else None
    except Exception:
        task_type = None

    try:
        from trainer_app.llm.providers import get_llm_client, get_llm_info
        import time

        info = get_llm_info()
        llm = get_llm_client()
        if not llm:
            _audit_log_token_user(user, action='trainer_llm_chat', status='error', metadata={'error': 'not_configured', 'llm': info})
            return jsonify({'success': False, 'error': 'not_configured', 'llm': info}), 400

        started = time.time()
        answer = llm.chat(messages=messages, temperature=temperature, max_tokens=max_tokens)
        duration_ms = int((time.time() - started) * 1000)

        try:
            picked = (info.get('picked') or {}) if isinstance(info, dict) else {}
            st = _map_user_to_student(user) if getattr(user, 'role', None) == 'student' else None
            ans_txt = (answer or '')
            if isinstance(ans_txt, str) and len(ans_txt) > 12000:
                ans_txt = ans_txt[:12000] + ' …'
            rec = TrainerLlmLog(
                user_id=user.id,
                student_id=(st.student_id if st else None),
                task_id=task_id,
                task_type=task_type,
                request_kind='chat',
                provider=(picked.get('provider') if isinstance(picked, dict) else None),
                model=(picked.get('model') if isinstance(picked, dict) else None),
                messages=messages,
                answer=ans_txt if isinstance(ans_txt, str) else None,
                error=None,
                duration_ms=duration_ms,
            )
            db.session.add(rec)
            db.session.commit()
        except Exception:
            db.session.rollback()

        _audit_log_token_user(
            user,
            action='trainer_llm_chat',
            status='success',
            metadata={
                'llm': info,
                'messages_count': len(messages),
                'chars_in': sum(len(m.get('content') or '') for m in messages),
                'max_tokens': max_tokens,
            },
            duration_ms=duration_ms,
        )
        return jsonify({'success': True, 'answer': (answer or ''), 'llm': info, 'duration_ms': duration_ms})
    except Exception as e:
        try:
            info2 = None
            try:
                from trainer_app.llm.providers import get_llm_info as _info
                info2 = _info()
            except Exception:
                info2 = None
            picked = (info2.get('picked') or {}) if isinstance(info2, dict) else {}
            st = _map_user_to_student(user) if getattr(user, 'role', None) == 'student' else None
            rec = TrainerLlmLog(
                user_id=user.id,
                student_id=(st.student_id if st else None),
                task_id=task_id,
                task_type=task_type,
                request_kind='chat',
                provider=(picked.get('provider') if isinstance(picked, dict) else None),
                model=(picked.get('model') if isinstance(picked, dict) else None),
                messages=messages,
                answer=None,
                error=str(e)[:4000],
                duration_ms=None,
            )
            db.session.add(rec)
            db.session.commit()
        except Exception:
            db.session.rollback()

        try:
            _audit_log_token_user(user, action='trainer_llm_chat', status='error', metadata={'error': str(e)[:500]})
        except Exception:
            pass
        # Диагностика 403: ключи в логе (без самого ключа)
        ex_str = str(e)
        if '403' in ex_str or 'gigachat_error' in ex_str.lower():
            gigachat_creds = (os.environ.get('GIGACHAT_CREDENTIALS') or '').strip()
            logger.warning(
                "LLM 403 diagnostic: gigachat_key_set=%s",
                bool(gigachat_creds),
            )
        return jsonify({'success': False, 'error': str(e)}), 500


def _get_hint_for_level(hints: list | None, level: int) -> str | None:
    """Из лестницы подсказок (список {level, text}) возвращает текст подсказки для уровня level или None."""
    if not hints or not isinstance(hints, list):
        return None
    for h in hints:
        if not isinstance(h, dict):
            continue
        try:
            if int(h.get('level', 0)) == level:
                return (h.get('text') or '').strip() or None
        except (TypeError, ValueError):
            continue
    return None


@trainer_bp.route('/internal/trainer/task/<int:task_id>/hint', methods=['GET'])
def trainer_task_hint(task_id: int):
    """
    Возвращает подсказку для задания по уровню (1, 2 или 3).
    Источник: поле Tasks.hints (лестница из эталонных прототипов). Ответ и решение не отдаём.
    """
    user = _get_trainer_user_from_token(require_permission='trainer.use')
    level_raw = request.args.get('level', '1').strip()
    try:
        level = int(level_raw)
    except ValueError:
        level = 1
    if level < 1:
        level = 1
    if level > 5:
        level = 5

    task = Tasks.query.filter_by(task_id=task_id).first()
    if not task:
        return jsonify({'success': False, 'error': 'task_not_found'}), 404

    hints = getattr(task, 'hints', None)
    text = _get_hint_for_level(hints, level)
    if not text:
        return jsonify({
            'success': False,
            'error': 'no_hint',
            'message': 'Для этого задания нет подсказки на выбранном уровне.',
        }), 404

    try:
        audit_logger.log(
            action='trainer_hint',
            entity='Trainer',
            entity_id=user.id,
            status='success',
            metadata={'task_id': task_id, 'level': level},
        )
    except Exception:
        pass
    return jsonify({'success': True, 'level': level, 'hint': text})


@trainer_bp.route('/internal/trainer/task/<int:task_id>', methods=['GET'])
def trainer_task_get(task_id: int):
    _ = _get_trainer_user_from_token(require_permission='trainer.use')
    task = Tasks.query.filter_by(task_id=task_id).first()
    if not task:
        return jsonify({'success': False, 'error': 'task_not_found'}), 404
    return jsonify({'success': True, 'task': _task_to_payload(task)})


@trainer_bp.route('/internal/trainer/task/<int:task_id>/attachment', methods=['GET'])
def trainer_task_attachment(task_id: int):
    """Скачивание вложения задания. Требует: ?path=attachments/filename.xlsx"""
    _ = _get_trainer_user_from_token(require_permission='trainer.use')
    path = (request.args.get('path') or '').strip()
    if not path or '..' in path or path.startswith('/'):
        abort(400)
    task = Tasks.query.filter_by(task_id=task_id).first()
    if not task:
        abort(404)
    source = (getattr(task, 'source_prototype', None) or '').strip()
    if not source:
        abort(404)
    proto_dir = os.path.dirname(source)
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    prototypes_dir = os.path.join(repo_root, 'data', 'reference_prototypes')
    full_dir = os.path.normpath(os.path.join(prototypes_dir, proto_dir))
    full_path = os.path.normpath(os.path.join(full_dir, path))
    if not full_path.startswith(full_dir):
        abort(400)
    if not os.path.isfile(full_path):
        abort(404)
    try:
        return send_file(full_path, as_attachment=True, download_name=os.path.basename(path))
    except Exception as e:
        logger.warning("trainer attachment send_file error: %s", e)
        abort(500)


def _check_answer(expected: str, given: str) -> bool:
    if not expected or not expected.strip():
        return False
    variants = [v.strip() for v in re.split(r'[|;\n]+', expected) if v.strip()]
    norm_exp = [normalize_answer_value(v) for v in variants]
    norm_exp = [v for v in norm_exp if v]
    norm_given = normalize_answer_value(given)
    return norm_given in norm_exp and norm_given != ''


@trainer_bp.route('/internal/trainer/recommendations', methods=['GET'])
def trainer_recommendations():
    """Smart-лента (Daily Mix): 5-7 задач на сегодня."""
    user = _get_trainer_user_from_token(require_permission='trainer.use')
    st = _map_user_to_student(user) if user.role == 'student' else None
    
    # 1. Задачи с низким рейтингом (на повторение)
    # 2. Новые задачи (не StudentTaskSeen)
    # 3. Задачи из популярных тем или просто рандом
    
    recommendations = []
    
    # Сначала ищем по UserMastery (слабые места)
    masteries = UserMastery.query.filter_by(user_id=user.id).order_by(UserMastery.rating.asc()).limit(3).all()
    for m in masteries:
        # Пытаемся найти подходящую задачу для этого узла
        t = Tasks.query.filter_by(knowledge_node_id=m.node_id).order_by(db.func.random()).first()
        if t:
            recommendations.append(_task_to_payload(t))
            
    # Добиваем новыми задачами
    exclude_ids = [r['task_id'] for r in recommendations if r]
    if st:
        # Исключаем виденные
        seen_q = db.session.query(StudentTaskSeen.task_id).filter(StudentTaskSeen.student_id == st.student_id)
        q = Tasks.query.filter(~Tasks.task_id.in_(seen_q))
        if exclude_ids:
            q = q.filter(~Tasks.task_id.in_(exclude_ids))
        
        new_tasks = q.order_by(db.func.random()).limit(7 - len(recommendations)).all()
        for t in new_tasks:
            recommendations.append(_task_to_payload(t))
            
    # Если всё еще мало, просто рандом
    if len(recommendations) < 5:
        q = Tasks.query
        exclude_ids = [r['task_id'] for r in recommendations if r]
        if exclude_ids:
            q = q.filter(~Tasks.task_id.in_(exclude_ids))
        rand_tasks = q.order_by(db.func.random()).limit(5 - len(recommendations)).all()
        for t in rand_tasks:
            recommendations.append(_task_to_payload(t))
            
    return jsonify({'success': True, 'recommendations': recommendations[:7]})


@trainer_bp.route('/internal/trainer/task_success_rates', methods=['GET'])
def trainer_task_success_rates():
    """Процент успеха по каждому номеру задания (для тепловой карты)."""
    user = _get_trainer_user_from_token(require_permission='trainer.use')
    course_id = request.args.get('course_id', type=int)
    
    # Агрегация по AnalyticsEvent
    q = (
        db.session.query(Tasks.task_number, db.func.count(AnalyticsEvent.id), db.func.sum(db.cast(AnalyticsEvent.is_correct, db.Integer)))
        .join(Tasks, AnalyticsEvent.task_id == Tasks.task_id)
        .filter(AnalyticsEvent.user_id == user.id)
    )
    if course_id is not None:
        q = q.filter(Tasks.course_id == course_id)
    rows = q.group_by(Tasks.task_number).all()
    
    rates = {}
    for task_num, total, correct in rows:
        if total > 0:
            rates[int(task_num)] = round((correct / total) * 100)
            
    return jsonify({'success': True, 'rates': rates})


@trainer_bp.route('/internal/trainer/task/submit_answer', methods=['POST'])
@csrf.exempt
def trainer_submit_answer():
    """Проверка ответа и обновление рейтинга (AnalyticsEngine)."""
    user = _get_trainer_user_from_token(require_permission='trainer.use')
    data = request.get_json(silent=True) or {}
    
    task_id = data.get('task_id')
    user_answer = str(data.get('answer', '')).strip()
    time_spent_sec = data.get('time_spent_sec')
    
    task = Tasks.query.get(task_id)
    if not task:
        return jsonify({'success': False, 'error': 'task_not_found'}), 404
        
    is_correct = _check_answer(task.answer, user_answer)
    
    # Обновляем рейтинг
    new_rating = AnalyticsEngine.process_submission(
        user_id=user.id,
        task_id=task.task_id,
        is_correct=is_correct,
        time_spent_sec=time_spent_sec
    )
    
    return jsonify({
        'success': True,
        'is_correct': is_correct,
        'expected': task.answer,
        'new_rating': new_rating
    })


@trainer_bp.route('/internal/trainer/code/run', methods=['POST'])
@csrf.exempt
def trainer_code_run():
    """
    Запуск кода (runner) для trainer v2.
    Feature-flagged: TRAINER_ENABLE_RUNNER=true.
    Body: { code: str, stdin?: str, timeout_seconds?: float }
    """
    _ = _get_trainer_user_from_token(require_permission='trainer.use')
    try:
        from trainer_app.runner.sandbox import is_runner_enabled, run_python_program
    except Exception:
        return jsonify({'success': False, 'error': 'runner_import_failed'}), 500

    if not is_runner_enabled():
        return jsonify({'success': False, 'error': 'runner_disabled'}), 403

    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'bad_request'}), 400

    code = str(data.get('code') or '')
    stdin = str(data.get('stdin') or '')
    try:
        timeout_seconds = float(data.get('timeout_seconds') or 2.0)
    except Exception:
        timeout_seconds = 2.0
    timeout_seconds = max(0.5, min(timeout_seconds, 5.0))

    res = run_python_program(code=code, stdin=stdin, timeout_seconds=timeout_seconds)
    return jsonify({'success': True, 'run': res})


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


def _task_has_knowledge(task_id: int, task_number: int, course_id: int | None = None) -> bool:
    """
    Проверяет наличие trainer_knowledge для задания (файл существует).
    Для заданий в одной группе (task_group_id, напр. 19–21) использует общий knowledge по CourseTaskTemplate.
    """
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    base = os.path.join(repo_root, 'trainer_knowledge', 'tasks')
    if os.path.isfile(os.path.join(base, f'{int(task_id)}.json')):
        return True
    tn = int(task_number)
    if os.path.isfile(os.path.join(base, 'by_number', f'{tn}.json')):
        return True
    # Группа заданий (19,20,21 и т.п.): ищем canonical task_number по task_group_id
    task = Tasks.query.get(task_id)
    if task and getattr(task, 'task_group_id', None):
        q = Tasks.query.filter(Tasks.task_group_id == task.task_group_id)
        if course_id:
            q = q.filter(Tasks.course_id == course_id)
        group_tasks = q.all()
        if group_tasks:
            min_tn = min((t.task_number for t in group_tasks if t.task_number is not None), default=None)
            if min_tn is not None and min_tn != tn and os.path.isfile(os.path.join(base, 'by_number', f'{min_tn}.json')):
                return True
    # Fallback: legacy EGE (20, 21 -> 19) при отсутствии course_id
    if course_id is None and tn in (20, 21) and os.path.isfile(os.path.join(base, 'by_number', '19.json')):
        return True
    return False


@trainer_bp.route('/internal/trainer/task/fallback-candidates', methods=['GET'])
def trainer_fallback_candidates():
    """
    Задания без hints в БД, но с trainer_knowledge — для проверки LLM-фоллбэка.
    Только те, где фоллбэк реально сработает (есть контекст).
    Доступно только создателям (trainer.manage_knowledge).
    """
    user = _get_trainer_user_from_token(require_permission='trainer.use')
    if not has_permission(user, 'trainer.manage_knowledge'):
        return jsonify({'success': False, 'error': 'forbidden'}), 403

    task_type_arg = request.args.get('task_type', '').strip()
    task_type_filter = None
    if task_type_arg:
        try:
            task_type_filter = int(task_type_arg)
        except ValueError:
            task_type_filter = None
    course_id = request.args.get('course_id', type=int)

    q = db.session.query(Tasks.task_number, Tasks.task_id, Tasks.hints)
    if task_type_filter is not None:
        q = q.filter(Tasks.task_number == task_type_filter)
    if course_id is not None:
        q = q.filter(Tasks.course_id == course_id)
    rows = q.all()

    by_number: dict[int, list[int]] = {}
    for n, tid, h in rows:
        if n is None or tid is None:
            continue
        has_hints = bool(h) and (
            (isinstance(h, list) and len(h) > 0) or (isinstance(h, dict) and bool(h))
        )
        if not has_hints and _task_has_knowledge(int(tid), int(n), course_id):
            by_number.setdefault(int(n), []).append(int(tid))

    counts = {n: len(ids) for n, ids in sorted(by_number.items())}
    return jsonify({
        'success': True,
        'counts_by_task_number': counts,
        'task_ids_by_number': {str(k): v for k, v in by_number.items()},
    })


def _parse_course_id(data: dict) -> int | None:
    """Извлекает course_id из данных запроса."""
    v = data.get('course_id')
    if v is None or v == '':
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


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

    course_id = _parse_course_id(data)
    st = _map_user_to_student(user) if getattr(user, 'role', None) == 'student' else None

    task_id = data.get('task_id')
    pinned_task: Tasks | None = None
    if task_id not in (None, ''):
        try:
            pinned_id = int(task_id)
            pinned_task = Tasks.query.filter_by(task_id=pinned_id).first()
        except Exception:
            pinned_task = None

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
        if course_id is not None:
            q = q.filter(Tasks.course_id == course_id)
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

    course_id = _parse_course_id(data)
    st = _map_user_to_student(user) if getattr(user, 'role', None) == 'student' else None

    exclude_ids: list[int] = []
    raw_exclude = data.get('exclude_task_ids')
    if isinstance(raw_exclude, list):
        for v in raw_exclude[:200]:
            try:
                exclude_ids.append(int(v))
            except Exception:
                continue

    q = Tasks.query.filter(Tasks.task_number == task_type)
    if course_id is not None:
        q = q.filter(Tasks.course_id == course_id)
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

    try:
        task_id = int(data.get('task_id')) if data.get('task_id') not in (None, '') else None
    except Exception:
        task_id = None
    code = (data.get('code') or '')
    if isinstance(code, str) and len(code) > 20000:
        code = code[:20000]

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


@trainer_bp.route('/internal/trainer/stats', methods=['GET'])
def trainer_stats():
    """sessions_today (по Москве), last_session для блока «Продолжить»."""
    user = _get_trainer_user_from_token(require_permission='trainer.use')
    now = moscow_now()
    try:
        start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    except Exception:
        start_of_today = now
    sessions_today = TrainerSession.query.filter(
        TrainerSession.user_id == user.id,
        TrainerSession.created_at >= start_of_today,
    ).count()
    last = (
        TrainerSession.query.filter_by(user_id=user.id)
        .order_by(TrainerSession.created_at.desc(), TrainerSession.session_id.desc())
        .limit(1)
        .first()
    )
    last_session = None
    if last:
        last_session = {
            'session_id': last.session_id,
            'task_type': last.task_type,
            'created_at': last.created_at.isoformat() if last.created_at else None,
        }
    return jsonify({
        'success': True,
        'sessions_today': sessions_today,
        'last_session': last_session,
    })


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

