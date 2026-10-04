import hashlib
import hmac
import json
import logging
import os
import time
from urllib.parse import parse_qs
from flask import Blueprint, render_template, request, jsonify
from core.db_models import db, User, UserProfile, Student, Lesson, QATestCase, BugReport, moscow_now
from app.telegram.config import MAIN_BOT_TOKEN

logger = logging.getLogger(__name__)

tma_bp = Blueprint('tma', __name__)

def _get_bot_token():
    return MAIN_BOT_TOKEN

def validate_init_data(init_data: str, bot_token: str = None) -> dict | None:
    if not init_data:
        return None
    if os.environ.get('FLASK_ENV') == 'testing' and init_data == 'test_mock':
        return {'user': {'id': 12345678, 'username': 'test_user'}}
    token = bot_token or _get_bot_token()
    if not token:
        return None
    try:
        parsed = parse_qs(init_data, keep_blank_values=True)
        flat = {k: v[0] for k, v in parsed.items()}
        received_hash = flat.pop('hash', None)
        if not received_hash:
            return None
        sorted_items = sorted(flat.items(), key=lambda x: x[0])
        data_check_string = '\n'.join(f'{k}={v}' for k, v in sorted_items)
        secret_key = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
        computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if hmac.compare_digest(computed_hash, received_hash):
            auth_date = int(flat.get('auth_date', '0') or 0)
            max_age = max(60, min(int(os.environ.get('TELEGRAM_INIT_DATA_MAX_AGE', '86400')), 604800))
            now = int(time.time())
            if not auth_date or auth_date > now + 60 or now - auth_date > max_age:
                return None
            if 'user' in flat:
                try:
                    flat['user'] = json.loads(flat['user'])
                except Exception:
                    pass
            return flat
    except Exception as e:
        logger.error(f"validate_init_data error: {e}")
    return None

# --- GET Routes (HTML Templates) ---

@tma_bp.route('/tma/schedule')
def tma_student_schedule_page():
    return render_template('tma/student_schedule.html')

@tma_bp.route('/tma/qa/checklist')
def tma_qa_checklist_page():
    return render_template('tma/qa_checklist.html')

@tma_bp.route('/tma/parent/digest')
def tma_parent_digest_page():
    return render_template('tma/parent_digest.html')


from app import csrf

# --- POST API Routes ---

@tma_bp.route('/api/tma/auth', methods=['POST'])
@csrf.exempt
def api_tma_auth():
    data = request.get_json(force=True, silent=True) or {}
    init_data = data.get('initData') or request.headers.get('X-TG-Init-Data', '')
    validated = validate_init_data(init_data)
    
    if not validated or not isinstance(validated.get('user'), dict):
        return jsonify({'ok': False, 'error': 'Invalid Telegram initData signature'}), 403
    tg_user_id = validated['user'].get('id')

    if not tg_user_id:
        return jsonify({'ok': True, 'is_linked': False, 'message': 'initData user ID not provided'}), 200

    user = User.query.join(UserProfile, UserProfile.user_id == User.id).filter(
        UserProfile.telegram_chat_id == int(tg_user_id)
    ).first()

    if user:
        return jsonify({
            'ok': True,
            'is_linked': True,
            'user': {
                'id': user.id,
                'username': user.username,
                'full_name': getattr(user, 'full_name', user.username),
                'role': user.role
            }
        })

    return jsonify({
        'ok': True,
        'is_linked': False,
        'bot_username': (os.environ.get('TELEGRAM_BOT_USERNAME') or '').lstrip('@') or None,
        'message': 'Аккаунт не привязан. Нажмите кнопку ниже для генерации кода привязки'
    })

@tma_bp.route('/api/tma/schedule', methods=['POST'])
@csrf.exempt
def api_tma_schedule():
    data = request.get_json(force=True, silent=True) or {}
    init_data = data.get('initData') or request.headers.get('X-TG-Init-Data', '')
    validated = validate_init_data(init_data)
    
    if not validated or not isinstance(validated.get('user'), dict):
        return jsonify({'ok': False, 'error': 'Invalid Telegram initData signature'}), 403
    tg_user_id = validated['user'].get('id')

    user = None
    if tg_user_id:
        user = User.query.join(UserProfile, UserProfile.user_id == User.id).filter(
            UserProfile.telegram_chat_id == int(tg_user_id)
        ).first()

    if not user:
        return jsonify({'ok': False, 'error': 'telegram_account_not_linked'}), 404

    username = user.username if user else "Ученик"
    
    lessons = []
    rows = Lesson.query.join(Student, Student.student_id == Lesson.student_id).filter(
        Student.user_id == user.id,
        Lesson.status.in_(['planned', 'in_progress']),
    ).order_by(Lesson.lesson_date.asc()).limit(10).all()
    for lesson in rows:
        lesson_id = int(lesson.lesson_id)
        lessons.append({
            'id': lesson_id,
            'title': lesson.topic or f'Занятие #{lesson_id}',
            'date': lesson.lesson_date.strftime('%d.%m %H:%M') if lesson.lesson_date else 'Планируется',
            'status': lesson.status or 'planned',
            'room_url': f'/lesson/{lesson_id}/classwork-tasks',
        })

    return jsonify({
        'ok': True,
        'is_linked': True if user else False,
        'user_name': username,
        'lessons': lessons
    })

@tma_bp.route('/api/tma/qa/checklist', methods=['POST'])
@csrf.exempt
def api_tma_qa_checklist():
    data = request.get_json(force=True, silent=True) or {}
    init_data = data.get('initData') or request.headers.get('X-TG-Init-Data', '')
    validated = validate_init_data(init_data)
    if not validated:
        return jsonify({'ok': False, 'error': 'Invalid Telegram initData signature'}), 403

    tg_user_id = (validated.get('user') or {}).get('id')
    tester = User.query.join(UserProfile, UserProfile.user_id == User.id).filter(
        UserProfile.telegram_chat_id == int(tg_user_id)
    ).first() if tg_user_id else None
    if not tester or (tester.role or '').lower() not in {
        'tester', 'chief_tester', 'admin', 'chief_admin', 'creator', 'teacher', 'tutor'
    }:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403

    test_cases = QATestCase.query.filter_by(is_active=True).limit(20).all()
    items = []
    for tc in test_cases:
        items.append({
            "id": tc.id,
            "title": tc.title,
            "area": tc.area,
            "steps": tc.steps if isinstance(tc.steps, list) else ["1. Открыть страницу", "2. Проверить кнопку"],
            "expected": tc.expected_result or "Страница загрузилась корректно"
        })

    return jsonify({'ok': True, 'test_cases': items})

@tma_bp.route('/api/tma/qa/report-bug', methods=['POST'])
@csrf.exempt
def api_tma_qa_report_bug():
    data = request.get_json(force=True, silent=True) or {}
    init_data = data.get('initData') or request.headers.get('X-TG-Init-Data', '')
    validated = validate_init_data(init_data)
    if not validated:
        return jsonify({'ok': False, 'error': 'Invalid Telegram initData signature'}), 403

    tg_user_id = (validated.get('user') or {}).get('id') if validated else None
    reporter = User.query.join(UserProfile, UserProfile.user_id == User.id).filter(
        UserProfile.telegram_chat_id == int(tg_user_id)
    ).first() if tg_user_id else None
    if not reporter or (reporter.role or '').lower() not in {
        'tester', 'chief_tester', 'admin', 'chief_admin', 'creator', 'teacher', 'tutor'
    }:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403

    title = data.get('title', 'Баг из TMA')
    description = data.get('description', '')
    step_failed = data.get('step_failed', '')
    severity = data.get('severity', 'MAJOR')

    bug = BugReport(
        title=title,
        description=description,
        step_failed=step_failed,
        severity=severity,
        status='NEW',
        reporter_id=reporter.id,
    )
    db.session.add(bug)
    db.session.commit()

    return jsonify({'ok': True, 'bug_id': bug.id, 'status': bug.status})

@tma_bp.route('/api/tma/parent/digest', methods=['POST'])
@csrf.exempt
def api_tma_parent_digest():
    data = request.get_json(force=True, silent=True) or {}
    init_data = data.get('initData') or request.headers.get('X-TG-Init-Data', '')
    validated = validate_init_data(init_data)
    if not validated:
        return jsonify({'ok': False, 'error': 'Invalid Telegram initData signature'}), 403
    tg_user_id = (validated.get('user') or {}).get('id') if validated else None
    parent = User.query.join(UserProfile, UserProfile.user_id == User.id).filter(
        UserProfile.telegram_chat_id == int(tg_user_id)
    ).first() if tg_user_id else None
    if not parent:
        return jsonify({'ok': False, 'error': 'telegram_account_not_linked'}), 404
    from app.telegram.application import build_parent_digest
    digest = build_parent_digest(parent, data.get('student_id'))
    if digest is None:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    from dataclasses import asdict
    return jsonify({'ok': True, 'digest': asdict(digest)})
