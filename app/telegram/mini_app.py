"""
Telegram Mini App — lightweight student dashboard inside Telegram.

The Mini App is opened via a Telegram WebApp button.  Telegram passes
``initData`` through its JS SDK; we validate the HMAC signature server-side
and return the student's dashboard.
"""
import hashlib
import hmac
import json
import logging
import os
from urllib.parse import parse_qs

from flask import Blueprint, render_template, request, jsonify
from sqlalchemy import text

logger = logging.getLogger(__name__)

tg_app_bp = Blueprint('tg_app', __name__, url_prefix='/tg-app')


# ---------------------------------------------------------------------------
# initData HMAC validation (per Telegram docs)
# ---------------------------------------------------------------------------

def validate_init_data(init_data: str, bot_token: str) -> dict | None:
    """
    Validate Telegram WebApp ``initData`` string.

    Returns the parsed data dict on success, or ``None`` if invalid.

    Algorithm (from https://core.telegram.org/bots/webapps#validating-data):
      1. Parse query-string pairs from *init_data*.
      2. Remove the ``hash`` field; sort remaining fields alphabetically.
      3. Join as ``key=value`` with ``\\n``.
      4. secret_key = HMAC-SHA256(key=b"WebAppData", msg=bot_token)
      5. Verify HMAC-SHA256(key=secret_key, msg=data_check_string) == hash.
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


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@tg_app_bp.route('/')
def mini_app_dashboard():
    """Render the Telegram Mini App shell (data loaded via JS)."""
    return render_template('telegram/mini_app.html')


@tg_app_bp.route('/api/dashboard', methods=['POST'])
def mini_app_api_dashboard():
    """
    Return dashboard JSON for the authenticated Telegram user.

    Expects ``{"init_data": "<raw initData string>"}`` in the body.
    """
    body = request.get_json(force=True) if request.is_json else {}
    init_data = body.get('init_data', '')
    token = _get_bot_token()

    validated = validate_init_data(init_data, token)
    if validated is None:
        return jsonify({'ok': False, 'error': 'invalid_init_data'}), 403

    tg_user = validated.get('user') or {}
    tg_id = tg_user.get('id')
    if not tg_id:
        return jsonify({'ok': False, 'error': 'no_user_id'}), 403

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
            return jsonify({'ok': False, 'error': 'not_linked'}), 404

        user_id, username, role, first_name, last_name = user_row
        display_name = f'{first_name or ""} {last_name or ""}'.strip() or username

        student_row = session.execute(text("""
            SELECT student_id, name, target_score
            FROM "Students"
            WHERE user_id = :uid AND is_active = TRUE
            LIMIT 1
        """), {'uid': user_id}).fetchone()

        schedule = []
        pending_hw = 0
        recent_grades = []

        if student_row:
            sid = student_row[0]

            # Upcoming lessons (max 5)
            lesson_rows = session.execute(text("""
                SELECT lesson_date, topic, duration, lesson_type
                FROM "Lessons"
                WHERE student_id = :sid
                  AND lesson_date >= NOW() - INTERVAL '1 hour'
                  AND status IN ('planned', 'in_progress')
                ORDER BY lesson_date ASC
                LIMIT 5
            """), {'sid': sid}).fetchall()

            for ld, topic, dur, ltype in lesson_rows:
                schedule.append({
                    'date': ld.isoformat() if ld else None,
                    'topic': topic or 'Урок',
                    'duration': dur or 60,
                    'type': ltype or 'regular',
                })

            # Pending homework count
            pending_hw = session.execute(text("""
                SELECT COUNT(*)
                FROM "Submissions" s
                JOIN "Assignments" a ON a.assignment_id = s.assignment_id
                WHERE s.student_id = :sid
                  AND s.status IN ('ASSIGNED', 'IN_PROGRESS', 'RETURNED')
            """), {'sid': sid}).scalar() or 0

            # Recent grades (last 5 graded submissions)
            grade_rows = session.execute(text("""
                SELECT a.title, s.status, s.graded_at,
                       COALESCE(
                           (SELECT sa.percentage FROM "SubmissionAttempts" sa
                            WHERE sa.submission_id = s.submission_id
                            ORDER BY sa.attempt_no DESC LIMIT 1),
                           NULL
                       ) AS pct
                FROM "Submissions" s
                JOIN "Assignments" a ON a.assignment_id = s.assignment_id
                WHERE s.student_id = :sid
                  AND s.status IN ('GRADED', 'AUTO_GRADED')
                ORDER BY s.graded_at DESC NULLS LAST
                LIMIT 5
            """), {'sid': sid}).fetchall()

            for title, status, graded_at, pct in grade_rows:
                recent_grades.append({
                    'title': title or '—',
                    'status': status,
                    'graded_at': graded_at.isoformat() if graded_at else None,
                    'percentage': round(pct, 1) if pct is not None else None,
                })

        return jsonify({
            'ok': True,
            'user': {
                'name': display_name,
                'role': role,
            },
            'schedule': schedule,
            'pending_homework': pending_hw,
            'recent_grades': recent_grades,
        })

    except Exception as e:
        logger.error('mini_app_api_dashboard error: %s', e, exc_info=True)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
