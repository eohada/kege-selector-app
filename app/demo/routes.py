"""
HTTP-маршруты и API интерактивной демоверсии BooStudy Demo Experience.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import jsonify, make_response, redirect, render_template, request, session, url_for
from flask_login import current_user, logout_user

from app.demo import demo_bp
from app.models import CallRequest, Student, db
from app.telegram.config import BOOTSTRAP_CREATOR_CHAT_ID
from app.telegram.delivery import enqueue_direct_delivery
from app.demo.service import (
    ensure_demo_user_and_assignment,
    get_demo_state,
    is_demo_action_allowed,
    is_demo_transition_allowed,
    record_demo_action,
    reset_demo_session,
    update_demo_state,
    verify_demo_task_answer,
)
from core.db_models import utc_now
from app.limiter import limiter

logger = logging.getLogger(__name__)


def _demo_session_required():
    """Fail closed for demo mutations before an isolated demo user exists."""
    if not (
        current_user.is_authenticated
        and getattr(current_user, 'is_demo_user', False)
        and session.get('demo_state')
        and session.get('demo_session_id')
    ):
        return jsonify({'success': False, 'error': 'demo session required'}), 403
    return None


@demo_bp.route('', methods=['GET'])
@demo_bp.route('/', methods=['GET'])
def demo_entry():
    """Точка входа в интерактивную демоверсию (Глава 1: Знакомство с Бу)."""
    state = get_demo_state()
    is_active_demo = current_user.is_authenticated and getattr(current_user, 'is_demo_user', False)
    return render_template(
        'sandbox/demo_welcome.html',
        demo_state=state,
        is_active_demo=is_active_demo,
    )


@demo_bp.route('/api/init', methods=['POST'])
@limiter.limit('10 per minute')
def demo_init():
    """Инициализирует или восстанавливает сессию интерактивного демо."""
    data = request.get_json(silent=True) or {}
    student_name = (data.get('student_name') or 'Демо-ученик').strip()
    exam = (data.get('exam') or 'ege').strip().lower()
    goal = (data.get('goal') or 'ege').strip()
    grade = (data.get('grade') or '11').strip()
    mode = (data.get('mode') or 'guided').strip().lower()
    if mode not in {'guided', 'explore'}:
        mode = 'guided'

    # The CTA at the end of Chapter 1 always starts a new Chapter 2 tour.
    # Reusing a signed demo session here made a second run inherit all three
    # completed dashboard discoveries and jump straight to the trial card.
    fresh_chapter_two = bool(data.get('start_at_dashboard'))
    if fresh_chapter_two:
        reset_demo_session()

    state = ensure_demo_user_and_assignment(
        student_name=student_name,
        exam=exam,
        goal=goal,
        grade=grade,
    )
    logger.info(
        'demo_funnel event=demo_started session_id=%s mode=%s',
        state.get('demo_session_id'), mode,
    )
    # The Cinema → dashboard hand-off changes a signed Flask session cookie.
    # Persist the destination scene in this very response, otherwise a fast
    # navigation can carry the older cookie and lose the first Chapter 2 step.
    if fresh_chapter_two:
        state = update_demo_state({
            'chapter_id': 'chapter_2',
            'step_id': 'dashboard_intro',
        })
        # The dashboard itself is the Chapter 2 stage.  Mark the intro as
        # accepted before navigation so it opens directly into the first
        # visual-novel line and its 0/3 programme objective.
        record_demo_action('demo:chapter2:started')
        state = update_demo_state({
            'chapter_id': 'chapter_2',
            'step_id': 'chapter2_mission',
            'mode': mode,
        })
    return jsonify({
        'success': True,
        'state': state,
        'dashboard_url': url_for('main.dashboard'),
    })


@demo_bp.route('/api/state', methods=['GET', 'POST'])
def demo_state():
    """Получение или обновление текущего состояния сценария."""
    if request.method == 'POST':
        denied = _demo_session_required()
        if denied:
            return denied
        data = request.get_json(silent=True) or {}
        if data.get('step_id') and not is_demo_transition_allowed(
            get_demo_state(), data['step_id'], data.get('chapter_id')
        ):
            return jsonify({'success': False, 'error': 'invalid scenario transition', 'state': get_demo_state()}), 409
        state = update_demo_state(data)
        return jsonify({'success': True, 'state': state})

    return jsonify({'success': True, 'state': get_demo_state()})


@demo_bp.route('/api/director', methods=['POST'])
def demo_director():
    """Development controls for navigating the isolated demo story.

    This endpoint never touches a regular student account: it only rewrites the
    signed session state of the ephemeral demo user so a presenter can rehearse
    any chapter without manually replaying the whole story.
    """
    if not (current_user.is_authenticated and getattr(current_user, 'is_demo_user', False)):
        return jsonify({'success': False, 'error': 'director is available only in a demo session'}), 403

    data = request.get_json(silent=True) or {}
    chapter = str(data.get('chapter') or '')
    scene_map = {
        'chapter_2': ('dashboard_intro', []),
        'chapter_3': ('trial_intro', ['demo:chapter2:started', 'demo:dashboard:lesson_explored', 'demo:dashboard:assignments_explored', 'demo:dashboard:program_explored', 'demo:chapter2:trial_discovered']),
        'chapter_4': ('library_intro', ['demo:chapter2:started', 'demo:dashboard:lesson_explored', 'demo:dashboard:assignments_explored', 'demo:dashboard:program_explored', 'demo:chapter2:trial_discovered', 'demo:chapter3:mode_prompted', 'trial_completed']),
        'chapter_5': ('mistakes_intro', ['demo:chapter2:started', 'demo:dashboard:lesson_explored', 'demo:dashboard:assignments_explored', 'demo:dashboard:program_explored', 'demo:chapter2:trial_discovered', 'demo:chapter3:mode_prompted', 'trial_completed', 'demo:library:material_opened']),
        'chapter_6': ('route_intro', ['demo:chapter2:started', 'demo:dashboard:lesson_explored', 'demo:dashboard:assignments_explored', 'demo:dashboard:program_explored', 'demo:chapter2:trial_discovered', 'demo:chapter3:mode_prompted', 'trial_completed', 'demo:library:material_opened', 'demo:mistakes:review_opened']),
        'chapter_7': ('wins_intro', ['demo:chapter2:started', 'demo:dashboard:lesson_explored', 'demo:dashboard:assignments_explored', 'demo:dashboard:program_explored', 'demo:chapter2:trial_discovered', 'demo:chapter3:mode_prompted', 'trial_completed', 'demo:library:material_opened', 'demo:mistakes:review_opened', 'demo:route:module_opened']),
        'chapter_8': ('schedule_intro', ['demo:chapter2:started', 'demo:dashboard:lesson_explored', 'demo:dashboard:assignments_explored', 'demo:dashboard:program_explored', 'demo:chapter2:trial_discovered', 'demo:chapter3:mode_prompted', 'trial_completed', 'demo:library:material_opened', 'demo:mistakes:review_opened', 'demo:route:module_opened', 'demo:wins:analytics_opened']),
        'chapter_9': ('profile_intro', ['demo:chapter2:started', 'demo:dashboard:lesson_explored', 'demo:dashboard:assignments_explored', 'demo:dashboard:program_explored', 'demo:chapter2:trial_discovered', 'demo:chapter3:mode_prompted', 'trial_completed', 'demo:library:material_opened', 'demo:mistakes:review_opened', 'demo:route:module_opened', 'demo:wins:analytics_opened', 'demo:schedule:week_opened']),
        'chapter_10': ('finale', ['demo:chapter2:started', 'demo:dashboard:lesson_explored', 'demo:dashboard:assignments_explored', 'demo:dashboard:program_explored', 'demo:chapter2:trial_discovered', 'demo:chapter3:mode_prompted', 'trial_completed', 'demo:library:material_opened', 'demo:mistakes:review_opened', 'demo:route:module_opened', 'demo:wins:analytics_opened', 'demo:schedule:week_opened', 'demo:profile:achievements_opened']),
    }
    if chapter == 'chapter_1':
        next_revision = int(get_demo_state().get('director_revision') or 0) + 1
        reset_demo_session()
        state = get_demo_state()
        state['demo_session_id'] = uuid.uuid4().hex
        state['director_revision'] = next_revision
        session['demo_session_id'] = state['demo_session_id']
        session['demo_state'] = state
        session.modified = True
        return jsonify({'success': True, 'state': state, 'url': url_for('demo.demo_entry')})
    if chapter not in scene_map:
        return jsonify({'success': False, 'error': 'unknown demo chapter'}), 400

    state = get_demo_state()
    step_id, prerequisite_actions = scene_map[chapter]
    state['chapter_id'] = chapter
    state['step_id'] = step_id
    state['completed_actions'] = sorted(set(prerequisite_actions))
    state['flags'] = {}
    state['history'] = []
    state['director_revision'] = int(state.get('director_revision') or 0) + 1
    session['demo_state'] = state
    session.modified = True
    destination = url_for('main.dashboard')
    if chapter == 'chapter_4':
        destination = state.get('theory_url') or '/theory'
    elif chapter == 'chapter_5':
        destination = '/submissions'
    elif chapter == 'chapter_6':
        destination = state.get('program_url') or '/courses'
    elif chapter == 'chapter_7':
        destination = state.get('analytics_url') or '/analytics'
    elif chapter == 'chapter_8':
        destination = state.get('schedule_url') or '/schedule?timezone=Europe%2FMoscow&view=week'
    elif chapter in {'chapter_9', 'chapter_10'}:
        destination = state.get('profile_url') or '/workspace/profile'
    return jsonify({'success': True, 'state': state, 'url': destination})


@demo_bp.route('/api/event', methods=['POST'])
@limiter.limit('120 per minute')
def demo_event():
    """Регистрация пользовательского действия в сценарии."""
    denied = _demo_session_required()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    action_id = (data.get('action_id') or '').strip()
    payload = data.get('payload') or {}

    if not action_id:
        return jsonify({'success': False, 'error': 'action_id is required'}), 400

    current_state = get_demo_state()
    logger.info(
        'demo_funnel event=%s session_id=%s chapter=%s step=%s',
        action_id.replace('demo:', '').replace(':', '_'),
        current_state.get('demo_session_id'),
        current_state.get('chapter_id'),
        current_state.get('step_id'),
    )
    # A refresh or a delayed browser request can repeat a semantic action
    # after the story has already moved on.  Replaying it must be harmless:
    # do not reject the visitor or rewind the current scene.
    if action_id != 'transition_step' and action_id in set(current_state.get('completed_actions') or []):
        return jsonify({'success': True, 'state': current_state, 'idempotent': True})

    if not is_demo_action_allowed(current_state, action_id):
        return jsonify({'success': False, 'error': 'invalid scenario action', 'state': current_state}), 409

    if data.get('step_id') and not is_demo_transition_allowed(
        current_state, data['step_id'], data.get('chapter_id')
    ):
        return jsonify({'success': False, 'error': 'invalid scenario transition', 'state': current_state}), 409

    state = record_demo_action(action_id, payload)

    # The finale reward is deliberately session-only.  It gives the story a
    # tangible ending without minting an achievement or changing any regular
    # student's analytics.
    if action_id == 'demo:finale:shown':
        state = update_demo_state({'flags': {'cinema_reward': 'spark'}})

    # Если передано обновление шага/главы
    step_id = data.get('step_id')
    chapter_id = data.get('chapter_id')
    updates = {}
    if step_id:
        updates['step_id'] = step_id
    if chapter_id:
        updates['chapter_id'] = chapter_id
    if updates:
        state = update_demo_state(updates)

    return jsonify({'success': True, 'state': state})


@demo_bp.route('/api/verify-answer', methods=['POST'])
@limiter.limit('30 per minute')
def demo_verify_answer():
    """Проверка демонстрационного ответа на задание Главы 3."""
    denied = _demo_session_required()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    raw_answer = str(data.get('answer', '')).strip()

    state = get_demo_state()
    sub_id = data.get('submission_id') or state.get('submission_id')

    if not sub_id:
        return jsonify({'success': False, 'error': 'submission_id missing'}), 400

    result = verify_demo_task_answer(int(sub_id), raw_answer)
    if not result.get('success') and result.get('error') == 'submission not available for this demo session':
        return jsonify(result), 403
    return jsonify(result)


@demo_bp.route('/api/request', methods=['POST'])
@limiter.limit('3 per hour')
def demo_intro_request():
    """Save one intro-lesson lead for this isolated demo account."""
    if not (current_user.is_authenticated and getattr(current_user, 'is_demo_user', False)):
        return jsonify({'success': False, 'error': 'demo session required'}), 403

    data = request.get_json(silent=True) or {}
    if data.get('consent') is not True:
        return jsonify({'success': False, 'error': 'Для отправки заявки нужно согласиться на обработку данных и связь.'}), 400
    name = str(data.get('name') or '').strip()[:120]
    contact = str(data.get('contact') or '').strip()[:250]
    grade = str(data.get('grade') or '').strip()[:30]
    goal = str(data.get('goal') or '').strip()[:120]
    timezone_name = str(data.get('timezone') or '').strip()[:80]
    local_slot = str(data.get('slot') or '').strip()
    honeypot = str(data.get('website') or '').strip()
    if honeypot:
        return jsonify({'success': False, 'error': 'Не удалось отправить заявку.'}), 400
    if not all((name, contact, grade, goal, timezone_name, local_slot)):
        return jsonify({'success': False, 'error': 'Заполни имя, класс, цель, контакт и время.'}), 400
    contact_is_supported = (
        re.search(r'@[A-Za-z0-9_\.]{3,}', contact)
        or re.search(r'\+?\d[\d\s().-]{6,}', contact)
        or re.search(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', contact)
    )
    if not contact_is_supported:
        return jsonify({'success': False, 'field': 'contact', 'error': 'Укажи Telegram с @, телефон или email — так Бу сможет связаться.'}), 400
    try:
        selected_zone = ZoneInfo(timezone_name)
        preferred_at = datetime.fromisoformat(local_slot).replace(tzinfo=selected_zone).astimezone(ZoneInfo('Europe/Moscow')).replace(tzinfo=None)
    except (ValueError, KeyError):
        return jsonify({'success': False, 'error': 'Не удалось прочитать выбранное время.'}), 400

    state = get_demo_state()
    flags = state.get('flags') or {}
    student = Student.query.filter_by(user_id=current_user.id).first()
    if not student:
        return jsonify({'success': False, 'error': 'Демо-профиль не найден. Обнови страницу и попробуй снова.'}), 409

    # A resubmission edits the original request instead of creating a duplicate.
    row = CallRequest.query.filter_by(id=flags.get('intro_request_id'), student_id=student.student_id).first() if flags.get('intro_request_id') else None
    is_existing = row is not None
    if row is None:
        row = (CallRequest.query
               .filter_by(student_id=student.student_id, created_by_user_id=current_user.id)
               .filter(CallRequest.message.like('[DEMO INTRO] %'))
               .order_by(CallRequest.created_at.desc(), CallRequest.id.desc()).first())
        is_existing = row is not None

    message = '[DEMO INTRO] Имя: {name}; класс: {grade}; цель: {goal}; контакт: {contact}; выбранное время: {slot} ({zone})'.format(
        name=name, grade=grade, goal=goal, contact=contact, slot=local_slot, zone=timezone_name)
    try:
        if row is None:
            row = CallRequest(
                student_id=student.student_id,
                created_by_user_id=current_user.id,
                status='new',
                is_demo=True,
                source='demo_intro',
            )
            db.session.add(row)
        row.preferred_at = preferred_at
        row.message = message
        row.is_demo = True
        row.source = 'demo_intro'
        row.consent_given_at = utc_now()
        db.session.commit()
        update_demo_state({'flags': {'intro_request_id': row.id, 'intro_request_sent': True}})
    except Exception:
        db.session.rollback()
        logger.exception('Could not save demo intro request')
        return jsonify({'success': False, 'error': 'Не получилось отправить автоматически — напиши мне в Telegram, я всё равно помогу.'}), 500

    notification = (
        '📩 Заявка на вводный урок из демо BooStudy\n'
        f'Имя: {name}\nКласс: {grade}\nЦель: {goal}\nКонтакт: {contact}\n'
        f'Время: {local_slot} ({timezone_name})\nЗапись: #{row.id}'
    )
    queued = False
    try:
        delivery = enqueue_direct_delivery(
            current_user.id,
            int(BOOTSTRAP_CREATOR_CHAT_ID),
            notification,
            dedupe_key='demo-lead:%s' % row.id,
        )
        queued = delivery.status in {'pending', 'retry', 'processing', 'sent'}
    except Exception:
        logger.exception('Could not queue creator notification for demo lead_id=%s', row.id)
    return jsonify({'success': True, 'existing': is_existing, 'notified': False, 'queued': queued, 'request_id': row.id})


@demo_bp.route('/api/exit', methods=['POST'])
def demo_exit():
    """Выход из демо-режима с очисткой временного состояния."""
    reset_demo_session()
    if current_user.is_authenticated and getattr(current_user, 'is_demo_user', False):
        logout_user()

    response = make_response(jsonify({'success': True, 'redirect_url': url_for('auth.login')}))
    response.set_cookie('is_demo', '', expires=0)
    response.set_cookie('cinemaMode', '', expires=0)
    return response
