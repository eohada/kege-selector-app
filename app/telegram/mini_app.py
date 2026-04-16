"""
Telegram Mini App — дашборд ученика / панель создателя (TWA + JSON API).

Проверка initData — HMAC по документации Telegram.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs

from flask import Blueprint, render_template, request, jsonify, url_for
from sqlalchemy import text

logger = logging.getLogger(__name__)

tg_app_bp = Blueprint('tg_app', __name__, url_prefix='/tg-app')


def validate_init_data(init_data: str, bot_token: str) -> dict | None:
    """
    Validate Telegram WebApp ``initData`` string.

    Returns the parsed data dict on success, or ``None`` if invalid.
    """
    if not init_data or not bot_token:
        return None

    try:
        parsed = parse_qs(init_data, keep_blank_values=True)
        flat: dict[str, str] = {k: v[0] for k, v in parsed.items()}
    except Exception:
        return None

    received_hash = flat.pop('hash', None)
    if not received_hash:
        return None

    sorted_items = sorted(flat.items(), key=lambda x: x[0])
    data_check_string = '\n'.join(f'{k}={v}' for k, v in sorted_items)

    secret_key = hmac.new(
        b'WebAppData', bot_token.encode(), hashlib.sha256,
    ).digest()

    computed_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    if 'user' in flat:
        try:
            flat['user'] = json.loads(flat['user'])
        except (json.JSONDecodeError, TypeError):
            pass

    return flat


def _get_bot_token() -> str:
    return os.environ.get('BOT_TOKEN') or os.environ.get('TELEGRAM_BOT_TOKEN') or ''


def _external_base_url() -> str:
    return (os.environ.get('APP_URL') or '').strip().rstrip('/')


def _lesson_room_url(lesson_id: int) -> str:
    path = url_for('lessons.lesson_classwork_view', lesson_id=lesson_id)
    base = _external_base_url()
    if base:
        return base + path
    return url_for('lessons.lesson_classwork_view', lesson_id=lesson_id, _external=True)


def _profile_unlink_hint_url() -> str:
    path = url_for('auth.user_profile')
    base = _external_base_url()
    if base:
        return base + path
    return url_for('auth.user_profile', _external=True)


def resolve_user_from_init_data(body: dict | None) -> tuple[dict | None, tuple[Any, ...] | None, str | None]:
    """
    Валидация init_data и строка пользователя из БД.

    Возвращает (validated_flat, user_row, error_key).
    user_row: (id, username, role, first_name, last_name)
    """
    body = body or {}
    init_data = body.get('init_data', '') or body.get('initData', '')
    token = _get_bot_token()
    validated = validate_init_data(init_data, token)
    if validated is None:
        return None, None, 'invalid_init_data'

    tg_user = validated.get('user') or {}
    tg_id = tg_user.get('id')
    if not tg_id:
        return None, None, 'no_user_id'

    from app.models import db

    session = db.session
    try:
        user_row = session.execute(text("""
            SELECT u.id, u.username, u.role, up.first_name, up.last_name
            FROM "Users" u
            JOIN "UserProfiles" up ON up.user_id = u.id
            WHERE up.telegram_chat_id = :chat_id
        """), {'chat_id': int(tg_id)}).fetchone()

        if not user_row:
            return validated, None, 'not_linked'

        return validated, user_row, None
    except Exception as e:
        logger.error('resolve_user_from_init_data: %s', e, exc_info=True)
        return None, None, 'server_error'


def _is_creator_role(user_id: int) -> bool:
    from app.models import User

    u = User.query.get(int(user_id))
    if not u:
        return False
    return bool(u.is_creator() or u.is_chief_admin())


def _student_row_for_user(session, user_id: int) -> tuple[Any, ...] | None:
    return session.execute(text("""
        SELECT student_id, name, target_score
        FROM "Students"
        WHERE user_id = :uid AND is_active = TRUE
        LIMIT 1
    """), {'uid': user_id}).fetchone()


def _schedule_rows(session, student_id: int, since_naive):
    return session.execute(text("""
        SELECT lesson_id, lesson_date, topic, duration, lesson_type, status
        FROM "Lessons"
        WHERE student_id = :sid
          AND lesson_date >= :since
          AND status IN ('planned', 'in_progress')
        ORDER BY lesson_date ASC
        LIMIT 10
    """), {'sid': student_id, 'since': since_naive}).fetchall()


def _build_dashboard_payload(session, user_id: int, user_row: tuple) -> dict:
    from core.db_models import moscow_now

    _, username, role, first_name, last_name = user_row
    display_name = f'{first_name or ""} {last_name or ""}'.strip() or username

    now = moscow_now()
    since = (now - timedelta(hours=1)).replace(tzinfo=None) if now.tzinfo else (now - timedelta(hours=1))

    schedule = []
    pending_hw = 0
    recent_grades = []
    creator_mode = _is_creator_role(user_id)

    creator_stats = None
    if creator_mode:
        active_students = session.execute(text("""SELECT COUNT(*) FROM "Students" WHERE is_active = TRUE""")).scalar() or 0
        pending_checks = session.execute(text("""SELECT COUNT(*) FROM "Lessons" WHERE homework_status = 'submitted'""")).scalar() or 0
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_naive = today_start.replace(tzinfo=None) if today_start.tzinfo else today_start
        today_end_naive = today_start_naive + timedelta(days=1)
        today_lessons = session.execute(text("""
            SELECT COUNT(*) FROM "Lessons"
            WHERE lesson_date >= :tstart AND lesson_date < :tend
              AND status IN ('planned', 'in_progress')
        """), {'tstart': today_start_naive, 'tend': today_end_naive}).scalar() or 0
        creator_stats = {
            'active_students': active_students,
            'pending_checks': pending_checks,
            'today_lessons': today_lessons,
        }

    student_row = _student_row_for_user(session, user_id)

    if student_row:
        sid = student_row[0]

        lesson_rows = _schedule_rows(session, sid, since)

        for lid, ld, topic, dur, ltype, st in lesson_rows:
            schedule.append({
                'lesson_id': int(lid),
                'date': ld.isoformat() if ld else None,
                'topic': topic or 'Урок',
                'duration': dur or 60,
                'type': ltype or 'regular',
                'status': st,
                'lesson_url': _lesson_room_url(int(lid)),
            })

        pending_hw = session.execute(text("""
            SELECT COUNT(*)
            FROM "Lessons"
            WHERE student_id = :sid AND homework_status IN ('assigned', 'returned')
        """), {'sid': sid}).scalar() or 0

        grade_rows = session.execute(text("""
            SELECT topic, homework_status, updated_at, homework_result_percent
            FROM "Lessons"
            WHERE student_id = :sid AND homework_status IN ('graded', 'submitted')
            ORDER BY updated_at DESC
            LIMIT 5
        """), {'sid': sid}).fetchall()

        for title, status, updated_at, pct in grade_rows:
            recent_grades.append({
                'title': title or '—',
                'status': status,
                'graded_at': updated_at.isoformat() if updated_at else None,
                'percentage': round(float(pct), 1) if pct is not None else None,
            })

    return {
        'ok': True,
        'user': {
            'name': display_name,
            'role': role,
        },
        'creator_mode': creator_mode,
        'creator_stats': creator_stats,
        'schedule': schedule,
        'pending_homework': pending_hw,
        'recent_grades': recent_grades,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@tg_app_bp.route('/')
def mini_app_dashboard():
    return render_template('telegram/mini_app.html')


@tg_app_bp.route('/api/dashboard', methods=['POST'])
def mini_app_api_dashboard():
    body = request.get_json(force=True) if request.is_json else {}
    validated, user_row, err = resolve_user_from_init_data(body)
    if err:
        code = 404 if err == 'not_linked' else 403 if err != 'server_error' else 500
        return jsonify({'ok': False, 'error': err}), code
    assert user_row is not None

    from app.models import db

    try:
        payload = _build_dashboard_payload(db.session, int(user_row[0]), user_row)
        return jsonify(payload)
    except Exception as e:
        logger.error('mini_app_api_dashboard error: %s', e, exc_info=True)
        return jsonify({'ok': False, 'error': 'server_error'}), 500


@tg_app_bp.route('/api/schedule', methods=['POST'])
def mini_app_api_schedule():
    body = request.get_json(force=True) if request.is_json else {}
    _, user_row, err = resolve_user_from_init_data(body)
    if err:
        code = 404 if err == 'not_linked' else 403 if err != 'server_error' else 500
        return jsonify({'ok': False, 'error': err}), code
    assert user_row is not None
    user_id = int(user_row[0])

    from app.models import db
    from core.db_models import moscow_now

    student_row = _student_row_for_user(db.session, user_id)
    if not student_row:
        return jsonify({'ok': True, 'lessons': []})

    now = moscow_now()
    since = (now - timedelta(hours=1)).replace(tzinfo=None) if now.tzinfo else (now - timedelta(hours=1))
    rows = _schedule_rows(db.session, int(student_row[0]), since)
    lessons = []
    for lid, ld, topic, dur, ltype, st in rows:
        lessons.append({
            'lesson_id': int(lid),
            'topic': topic or 'Урок',
            'starts_at': ld.isoformat() if ld else None,
            'duration': dur or 60,
            'type': ltype or 'regular',
            'status': st,
            'lesson_url': _lesson_room_url(int(lid)),
        })
    return jsonify({'ok': True, 'lessons': lessons})


@tg_app_bp.route('/api/progress', methods=['POST'])
def mini_app_api_progress():
    body = request.get_json(force=True) if request.is_json else {}
    _, user_row, err = resolve_user_from_init_data(body)
    if err:
        code = 404 if err == 'not_linked' else 403 if err != 'server_error' else 500
        return jsonify({'ok': False, 'error': err}), code
    assert user_row is not None
    user_id = int(user_row[0])

    from app.models import db

    student_row = _student_row_for_user(db.session, user_id)
    if not student_row:
        return jsonify({'ok': True, 'pending_homework': 0, 'submissions': [], 'gradebook': []})

    sid = int(student_row[0])
    pending_hw = db.session.execute(text("""
        SELECT COUNT(*)
        FROM "Lessons"
        WHERE student_id = :sid
          AND homework_status IN ('assigned', 'returned')
    """), {'sid': sid}).scalar() or 0

    sub_rows = db.session.execute(text("""
        SELECT lesson_id, topic, homework_status, updated_at, homework_result_percent
        FROM "Lessons"
        WHERE student_id = :sid
          AND homework_status != 'not_assigned'
        ORDER BY updated_at DESC
        LIMIT 25
    """), {'sid': sid}).fetchall()

    submissions = []
    for lid, title, status, activity_at, pct in sub_rows:
        submissions.append({
            'title': title or '—',
            'status': status,
            'lesson_url': _lesson_room_url(int(lid)),
            'activity_at': activity_at.isoformat() if activity_at else None,
            'percentage': round(float(pct), 1) if pct is not None else None,
        })

    gb_rows = db.session.execute(text("""
        SELECT topic, homework_result_percent, updated_at
        FROM "Lessons"
        WHERE student_id = :sid AND homework_status = 'graded'
        ORDER BY updated_at DESC
        LIMIT 8
    """), {'sid': sid}).fetchall()

    gradebook = []
    for title, pct, updated_at in gb_rows:
        gradebook.append({
            'title': title or '—',
            'score': round(float(pct), 1) if pct is not None else None,
            'max_score': 100,
            'grade_text': '',
            'created_at': updated_at.isoformat() if updated_at else None,
        })

    return jsonify({
        'ok': True,
        'pending_homework': int(pending_hw),
        'submissions': submissions,
        'gradebook': gradebook,
    })


@tg_app_bp.route('/api/theory/index', methods=['POST'])
def mini_app_api_theory_index():
    body = request.get_json(force=True) if request.is_json else {}
    _, user_row, err = resolve_user_from_init_data(body)
    if err:
        code = 404 if err == 'not_linked' else 403 if err != 'server_error' else 500
        return jsonify({'ok': False, 'error': err}), code
    assert user_row is not None

    from app.models import User, TheoryBlock
    from app.auth.rbac_utils import has_permission

    u = User.query.get(int(user_row[0]))
    if not u or not has_permission(u, 'theory.view'):
        return jsonify({'ok': False, 'error': 'forbidden'}), 403

    blocks = (
        TheoryBlock.query.order_by(TheoryBlock.position, TheoryBlock.id)
        .limit(300)
        .all()
    )
    items = [
        {
            'id': b.id,
            'task_number': b.task_number,
            'title': b.title or f'Задание {b.task_number}',
            'read_minutes': b.read_minutes,
        }
        for b in blocks
    ]
    return jsonify({'ok': True, 'blocks': items})


@tg_app_bp.route('/api/theory/article', methods=['POST'])
def mini_app_api_theory_article():
    body = request.get_json(force=True) if request.is_json else {}
    _, user_row, err = resolve_user_from_init_data(body)
    if err:
        code = 404 if err == 'not_linked' else 403 if err != 'server_error' else 500
        return jsonify({'ok': False, 'error': err}), code
    assert user_row is not None

    from app.models import User, TheoryBlock
    from app.auth.rbac_utils import has_permission
    from app.theory.routes import _render_theory_content_html

    u = User.query.get(int(user_row[0]))
    if not u or not has_permission(u, 'theory.view'):
        return jsonify({'ok': False, 'error': 'forbidden'}), 403

    block_id = body.get('block_id') or body.get('id')
    try:
        block_id = int(block_id)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'bad_block_id'}), 400

    block = TheoryBlock.query.get(block_id)
    if not block:
        return jsonify({'ok': False, 'error': 'not_found'}), 404

    html = _render_theory_content_html(block.content or '')
    return jsonify({
        'ok': True,
        'id': block.id,
        'task_number': block.task_number,
        'title': block.title or f'Задание {block.task_number}',
        'html': html,
    })


@tg_app_bp.route('/api/profile', methods=['POST'])
def mini_app_api_profile():
    body = request.get_json(force=True) if request.is_json else {}
    _, user_row, err = resolve_user_from_init_data(body)
    if err:
        code = 404 if err == 'not_linked' else 403 if err != 'server_error' else 500
        return jsonify({'ok': False, 'error': err}), code
    assert user_row is not None

    from app.models import db, User, UserProfile, UserSubscription

    uid = int(user_row[0])
    u = User.query.get(uid)
    prof = UserProfile.query.filter_by(user_id=uid).first()
    student_row = _student_row_for_user(db.session, uid)

    display_name = f'{prof.first_name or ""} {prof.last_name or ""}'.strip() if prof else ''
    display_name = display_name or (u.username if u else '')

    phone, email = None, None
    if student_row:
        st = db.session.execute(text("""
            SELECT phone, email FROM "Students" WHERE student_id = :sid LIMIT 1
        """), {'sid': int(student_row[0])}).fetchone()
        if st:
            phone, email = st[0], st[1]

    sub = (
        UserSubscription.query.filter_by(user_id=uid)
        .order_by(UserSubscription.ends_at.desc().nullslast())
        .first()
    )
    sub_summary = None
    if sub:
        sub_summary = {
            'status': sub.status,
            'ends_at': sub.ends_at.isoformat() if sub.ends_at else None,
        }

    bot_username = (os.environ.get('TELEGRAM_BOT_USERNAME') or os.environ.get('BOT_USERNAME') or '').lstrip('@')

    return jsonify({
        'ok': True,
        'profile': {
            'name': display_name,
            'username': u.username if u else None,
            'role': u.role if u else None,
            'phone': phone,
            'email': email,
            'subscription': sub_summary,
            'unlink': {
                'profile_url': _profile_unlink_hint_url(),
                'bot_unlink_command': '/unlink',
                'bot_open': f'https://t.me/{bot_username}' if bot_username else None,
            },
        },
    })


@tg_app_bp.route('/api/broadcast/create', methods=['POST'])
def mini_app_api_broadcast_create():
    body = request.get_json(force=True) if request.is_json else {}
    _, user_row, err = resolve_user_from_init_data(body)
    if err:
        code = 404 if err == 'not_linked' else 403 if err != 'server_error' else 500
        return jsonify({'ok': False, 'error': err}), code
    assert user_row is not None

    uid = int(user_row[0])
    if not _is_creator_role(uid):
        return jsonify({'ok': False, 'error': 'forbidden'}), 403

    message = (body.get('message') or body.get('message_text') or '').strip()
    if not message:
        return jsonify({'ok': False, 'error': 'empty_message'}), 400
    photo_url = (body.get('photo_url') or body.get('image_url') or '').strip() or None

    from app.models import TelegramBroadcast, db
    from app.tasks.telegram_broadcast import process_telegram_broadcast_batch

    br = TelegramBroadcast(
        created_by_user_id=uid,
        message_text=message,
        photo_url=photo_url,
        status='pending',
        recipient_scope='all_linked_students',
    )
    db.session.add(br)
    db.session.commit()
    process_telegram_broadcast_batch.delay(int(br.broadcast_id))
    return jsonify({'ok': True, 'broadcast_id': br.broadcast_id, 'status': br.status})


@tg_app_bp.route('/api/assignments', methods=['POST'])
def mini_app_api_assignments():
    """Список заданий (Submissions) ученика с фильтром по статусу."""
    body = request.get_json(force=True) if request.is_json else {}
    _, user_row, err = resolve_user_from_init_data(body)
    if err:
        code = 404 if err == 'not_linked' else 403 if err != 'server_error' else 500
        return jsonify({'ok': False, 'error': err}), code
    assert user_row is not None

    from app.models import db

    uid = int(user_row[0])
    student_row = _student_row_for_user(db.session, uid)
    if not student_row:
        return jsonify({'ok': True, 'submissions': []})

    sid = int(student_row[0])
    status_filter = body.get('status_filter')  # 'pending' | 'graded' | None (all)

    if status_filter == 'pending':
        status_clause = "AND s.status IN ('ASSIGNED','IN_PROGRESS','RETURNED')"
    elif status_filter == 'graded':
        status_clause = "AND s.status IN ('GRADED')"
    else:
        status_clause = ''

    rows = db.session.execute(text(f"""
        SELECT s.submission_id, a.title, s.status, a.deadline,
               s.submitted_at, s.updated_at
        FROM "Submissions" s
        JOIN "Assignments" a ON a.assignment_id = s.assignment_id
        WHERE s.student_id = :sid {status_clause}
        ORDER BY a.deadline ASC NULLS LAST, s.updated_at DESC
        LIMIT 50
    """), {'sid': sid}).fetchall()

    base = _external_base_url()
    items = []
    for sub_id, title, status, deadline, submitted_at, updated_at in rows:
        items.append({
            'submission_id': int(sub_id),
            'title': title or '—',
            'status': status,
            'deadline': deadline.isoformat() if deadline else None,
            'submitted_at': submitted_at.isoformat() if submitted_at else None,
            'updated_at': updated_at.isoformat() if updated_at else None,
            'url': f'{base}/submissions/{sub_id}' if base else None,
        })
    return jsonify({'ok': True, 'submissions': items})


@tg_app_bp.route('/api/profile/notifications', methods=['POST'])
def mini_app_api_profile_notifications():
    """Получить и обновить настройки уведомлений из Mini App."""
    body = request.get_json(force=True) if request.is_json else {}
    _, user_row, err = resolve_user_from_init_data(body)
    if err:
        code = 404 if err == 'not_linked' else 403 if err != 'server_error' else 500
        return jsonify({'ok': False, 'error': err}), code
    assert user_row is not None

    from app.models import db, UserProfile

    uid = int(user_row[0])
    profile = UserProfile.query.filter_by(user_id=uid).first()
    if not profile:
        return jsonify({'ok': False, 'error': 'no_profile'}), 404

    _FIELDS = [
        'telegram_notifications_enabled',
        'tg_notify_homework_checked',
        'tg_notify_homework_returned',
        'tg_notify_lesson_scheduled',
        'tg_notify_lesson_reminder',
        'tg_notify_news',
        'tg_notify_daily_digest',
        'tg_notify_subscription_expiring',
        'tg_notify_bug_report_reply',
        'tg_quiet_hours_start',
        'tg_quiet_hours_end',
    ]

    # If 'updates' key present — apply changes
    updates = body.get('updates') or {}
    if updates:
        for key, val in updates.items():
            if key in _FIELDS:
                setattr(profile, key, val)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error('profile_notifications update: %s', e)
            return jsonify({'ok': False, 'error': 'db_error'}), 500

    result = {f: getattr(profile, f, None) for f in _FIELDS}
    return jsonify({'ok': True, 'notifications': result})


@tg_app_bp.route('/api/creator/bug-reports', methods=['POST'])
def mini_app_api_creator_bug_reports():
    """Список баг-репортов для создателя."""
    body = request.get_json(force=True) if request.is_json else {}
    _, user_row, err = resolve_user_from_init_data(body)
    if err:
        code = 404 if err == 'not_linked' else 403 if err != 'server_error' else 500
        return jsonify({'ok': False, 'error': err}), code
    assert user_row is not None

    uid = int(user_row[0])
    if not _is_creator_role(uid):
        return jsonify({'ok': False, 'error': 'forbidden'}), 403

    from app.models import db

    status_filter = body.get('status') or 'new'  # new|answered|closed|all
    if status_filter == 'all':
        status_clause = ''
        params: dict = {}
    else:
        status_clause = "WHERE ber.status = :status"
        params = {'status': status_filter}

    rows = db.session.execute(text(f"""
        SELECT ber.report_id, ber.message, ber.status, ber.created_at,
               ber.admin_reply, ber.replied_at, ber.screenshot_file_id,
               u.username, up.first_name, up.last_name, ber.telegram_chat_id
        FROM "BotErrorReports" ber
        LEFT JOIN "Users" u ON u.id = ber.user_id
        LEFT JOIN "UserProfiles" up ON up.user_id = ber.user_id
        {status_clause}
        ORDER BY ber.created_at DESC
        LIMIT 50
    """), params).fetchall()

    items = []
    for rid, msg, status, created_at, reply, replied_at, screenshot, uname, fname, lname, tg_cid in rows:
        name = f'{fname or ""} {lname or ""}'.strip() or uname or 'Аноним'
        items.append({
            'report_id': int(rid),
            'message': msg or '',
            'status': status,
            'created_at': created_at.isoformat() if created_at else None,
            'admin_reply': reply,
            'replied_at': replied_at.isoformat() if replied_at else None,
            'has_screenshot': screenshot is not None,
            'student_name': name,
            'telegram_chat_id': tg_cid,
        })
    return jsonify({'ok': True, 'reports': items, 'total': len(items)})


@tg_app_bp.route('/api/creator/bug-reports/reply', methods=['POST'])
def mini_app_api_creator_bug_reports_reply():
    """Ответить на баг-репорт из Mini App."""
    body = request.get_json(force=True) if request.is_json else {}
    _, user_row, err = resolve_user_from_init_data(body)
    if err:
        code = 404 if err == 'not_linked' else 403 if err != 'server_error' else 500
        return jsonify({'ok': False, 'error': err}), code
    assert user_row is not None

    uid = int(user_row[0])
    if not _is_creator_role(uid):
        return jsonify({'ok': False, 'error': 'forbidden'}), 403

    report_id = body.get('report_id')
    reply_text = (body.get('reply') or '').strip()
    if not report_id or not reply_text:
        return jsonify({'ok': False, 'error': 'missing_fields'}), 400

    from app.models import db
    from core.db_models import BotErrorReport, moscow_now

    report = BotErrorReport.query.get(int(report_id))
    if not report:
        return jsonify({'ok': False, 'error': 'not_found'}), 404

    try:
        report.admin_reply = reply_text
        report.status = 'answered'
        report.replied_at = moscow_now()
        report.reply_sent_at = moscow_now()
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': 'db_error'}), 500

    # Отправить студенту в TG
    if report.telegram_chat_id:
        from app.telegram.notifications import notify_bug_report_reply
        notify_bug_report_reply(
            student_chat_id=int(report.telegram_chat_id),
            report_id=int(report_id),
            reply_text=reply_text,
        )

    return jsonify({'ok': True, 'report_id': int(report_id), 'status': 'answered'})


@tg_app_bp.route('/api/creator/stats', methods=['POST'])
def mini_app_api_creator_stats():
    """Расширенная статистика платформы для создателя."""
    body = request.get_json(force=True) if request.is_json else {}
    _, user_row, err = resolve_user_from_init_data(body)
    if err:
        code = 404 if err == 'not_linked' else 403 if err != 'server_error' else 500
        return jsonify({'ok': False, 'error': err}), code
    assert user_row is not None

    uid = int(user_row[0])
    if not _is_creator_role(uid):
        return jsonify({'ok': False, 'error': 'forbidden'}), 403

    from app.models import db

    s = db.session
    total_users = s.execute(text('SELECT COUNT(*) FROM "Users"')).scalar() or 0
    active_students = s.execute(text('SELECT COUNT(*) FROM "Students" WHERE is_active = TRUE')).scalar() or 0
    tg_linked = s.execute(text(
        'SELECT COUNT(*) FROM "UserProfiles" WHERE telegram_chat_id IS NOT NULL'
    )).scalar() or 0
    lessons_today = s.execute(text(
        "SELECT COUNT(*) FROM \"Lessons\" WHERE lesson_date::date = CURRENT_DATE"
    )).scalar() or 0
    pending_sub = s.execute(text(
        "SELECT COUNT(*) FROM \"Submissions\" WHERE status IN ('SUBMITTED','NEEDS_MANUAL_REVIEW')"
    )).scalar() or 0
    active_subs = s.execute(text(
        "SELECT COUNT(*) FROM \"UserSubscriptions\" WHERE status = 'active'"
    )).scalar() or 0
    new_bug_reports = s.execute(text(
        "SELECT COUNT(*) FROM \"BotErrorReports\" WHERE status = 'new'"
    )).scalar() or 0
    broadcasts_total = s.execute(text('SELECT COUNT(*) FROM "TelegramBroadcasts"')).scalar() or 0

    return jsonify({
        'ok': True,
        'stats': {
            'total_users': total_users,
            'active_students': active_students,
            'tg_linked': tg_linked,
            'lessons_today': lessons_today,
            'pending_submissions': pending_sub,
            'active_subscriptions': active_subs,
            'new_bug_reports': new_bug_reports,
            'broadcasts_total': broadcasts_total,
        },
    })


@tg_app_bp.route('/api/creator/broadcasts', methods=['POST'])
def mini_app_api_creator_broadcasts():
    """История рассылок для создателя."""
    body = request.get_json(force=True) if request.is_json else {}
    _, user_row, err = resolve_user_from_init_data(body)
    if err:
        code = 404 if err == 'not_linked' else 403 if err != 'server_error' else 500
        return jsonify({'ok': False, 'error': err}), code
    assert user_row is not None

    uid = int(user_row[0])
    if not _is_creator_role(uid):
        return jsonify({'ok': False, 'error': 'forbidden'}), 403

    from app.models import db

    rows = db.session.execute(text("""
        SELECT tb.broadcast_id, tb.message_text, tb.status,
               tb.total_planned, tb.sent_ok, tb.created_at, tb.completed_at,
               up.first_name
        FROM "TelegramBroadcasts" tb
        LEFT JOIN "UserProfiles" up ON up.user_id = tb.created_by_user_id
        ORDER BY tb.created_at DESC
        LIMIT 20
    """)).fetchall()

    items = []
    for bid, msg, status, total, ok_cnt, created_at, completed_at, fname in rows:
        items.append({
            'broadcast_id': int(bid),
            'message_preview': (msg or '')[:100],
            'status': status,
            'total_planned': total or 0,
            'sent_ok': ok_cnt or 0,
            'created_at': created_at.isoformat() if created_at else None,
            'completed_at': completed_at.isoformat() if completed_at else None,
            'creator_name': fname or 'Создатель',
        })
    return jsonify({'ok': True, 'broadcasts': items})


@tg_app_bp.route('/api/creator/students', methods=['POST'])
def mini_app_api_creator_students():
    body = request.get_json(force=True) if request.is_json else {}
    _, user_row, err = resolve_user_from_init_data(body)
    if err:
        code = 404 if err == 'not_linked' else 403 if err != 'server_error' else 500
        return jsonify({'ok': False, 'error': err}), code
    assert user_row is not None

    uid = int(user_row[0])
    if not _is_creator_role(uid):
        return jsonify({'ok': False, 'error': 'forbidden'}), 403

    from app.models import db

    rows = db.session.execute(text("""
        SELECT s.student_id, s.name, up.telegram_chat_id,
               u.last_login, up.telegram_last_interaction_at
        FROM "Students" s
        JOIN "Users" u ON u.id = s.user_id
        LEFT JOIN "UserProfiles" up ON up.user_id = u.id
        WHERE s.is_active = TRUE
        ORDER BY s.student_id DESC
        LIMIT 800
    """)).fetchall()

    items = []
    for sid, name, telegram_chat_id, last_login, tg_inter in rows:
        times = [t for t in (last_login, tg_inter) if t is not None]
        last_activity = max(times) if times else None
        items.append({
            'student_id': int(sid),
            'name': name or '—',
            'telegram_linked': telegram_chat_id is not None,
            'last_activity_at': last_activity.isoformat() if last_activity else None,
        })
    return jsonify({'ok': True, 'students': items})
