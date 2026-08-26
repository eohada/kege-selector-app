"""Безопасные маршруты гостевого контура.

Гостевой токен всегда ограничивает запрос одной сессией и одним участником;
ни один endpoint не принимает произвольный student/task id без проверки связи.
"""
from datetime import timedelta
import hashlib
import json
import secrets
from functools import lru_cache, wraps
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

from flask import (Response, abort, current_app, jsonify, make_response, redirect,
                   render_template, request, send_file, url_for)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app.guest import guest_bp
from app import csrf
from app.limiter import limiter
from app.models import (db, GuestActivity, GuestAttachment, GuestDemoSnapshot,
                        GuestDrawing, GuestTemplate,
                        GuestParticipant, GuestResponse, GuestReview,
                        GuestSession, GuestTask, Student, User, UserRole, utc_now)
from app.auth.rbac_utils import require_role
from app.sandbox.python_runner import normalize_leading_tabs_to_spaces, run_python_sandbox
from app.utils.jinja_filters import prepare_guest_task_content


SESSION_TYPES = {'INTRO_LESSON', 'TRIAL_EXAM'}
TRIAL_TEMPLATES = {
    'trial_ege_full_1': {'title': 'Полный вариант КЕГЭ №1', 'description': 'Реальные задания №1–27 из локального снимка банка Kompege, включая исходные файлы.', 'duration': '3 ч 55 мин', 'outcome': 'Разбор результата по всем номерам КЕГЭ.'},
    'trial_ege_full_2': {'title': 'Полный вариант КЕГЭ №2', 'description': 'Второй независимый набор реальных заданий №1–27 с условиями, файлами и эталонами.', 'duration': '3 ч 55 мин', 'outcome': 'Сравнимый диагностический срез по всем номерам.'},
    'trial_ege_full_3': {'title': 'Полный вариант КЕГЭ №3', 'description': 'Третий независимый набор реальных заданий №1–27 из сохранённого банка.', 'duration': '3 ч 55 мин', 'outcome': 'Повторная диагностика без повтора предыдущих заданий.'},
}
INTRO_TEMPLATES = {
    'intro_platform_tour': {'title': 'Вводный урок BooStudy', 'description': 'Знакомство с программой, теорией и первой практикой.', 'duration': '10–15 минут', 'outcome': 'Первый ориентир и предложение следующего шага.'},
}


def _hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _as_bool(value, default=False):
    """Нормализует JSON и значения HTML FormData без ловушки bool('false')."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {'1', 'true', 'yes', 'on', 'да'}:
        return True
    if normalized in {'0', 'false', 'no', 'off', 'нет', ''}:
        return False
    return default


@lru_cache(maxsize=1)
def _ege_bank():
    """Возвращает проверенный локальный снимок реальных заданий КЕГЭ.

    Контур не зависит от внешнего запроса во время создания сессии: условия,
    ответы, источники и URL исходных файлов уже сохранены в tracked JSON.
    """
    bank_path = Path(current_app.root_path).parent / 'data' / 'tasks.json'
    try:
        with bank_path.open(encoding='utf-8') as source:
            payload = json.load(source)
    except (OSError, json.JSONDecodeError) as error:
        current_app.logger.error('Guest EGE bank is unavailable: %s', error)
        raise RuntimeError('Локальный снимок банка КЕГЭ недоступен') from error
    return payload


def _source_attachments(raw_value):
    if isinstance(raw_value, list):
        items = raw_value
    elif isinstance(raw_value, str) and raw_value.strip():
        try:
            items = json.loads(raw_value)
        except json.JSONDecodeError:
            items = []
    else:
        items = []
    return [
        {'name': str(item.get('name') or 'Исходный файл')[:255], 'url': str(item.get('url') or '')}
        for item in items if isinstance(item, dict) and str(item.get('url') or '').startswith(('https://', 'http://'))
    ]


def _ege_variant_specs(variant_index):
    """Собирает один полный вариант №1–27 из независимых записей банка."""
    payload = _ege_bank()
    specs = []
    for task_number in range(1, 28):
        bank_number = 19 if task_number in {19, 20, 21} else task_number
        records = list((payload.get(str(bank_number)) or {}).get('tasks') or [])
        if not records:
            raise RuntimeError(f'В локальном банке отсутствует задание №{task_number}')
        source = records[variant_index % len(records)]
        source_answer = str(source.get('answer') or '').strip()
        is_game_triplet = task_number in {19, 20, 21}
        prompt = prepare_guest_task_content(
            str(source.get('content_html') or '').strip(),
            task_number=task_number,
            source_url=str(source.get('source_url') or ''),
        )
        specs.append({
            'type': 'manual_text' if is_game_triplet else 'short_text',
            'prompt': prompt,
            'options': [],
            'expected': source_answer,
            'skill': f'ege.task_{task_number:02d}',
            'source_task_id': source.get('task_id'),
            'task_number': task_number,
            'source_url': str(source.get('source_url') or ''),
            'attachments': _source_attachments(source.get('attached_files')),
            'manual_review': is_game_triplet,
        })
    return specs


def _task_specs(template_key):
    python_start = [
        {'type': 'choice', 'prompt': 'Какой тип хранит целое число в Python?', 'options': ['int', 'str', 'list', 'bool'], 'expected': 'int', 'skill': 'python.types'},
        {'type': 'short_text', 'prompt': 'Что выведет программа: print(2 + 3)?', 'options': [], 'expected': '5', 'skill': 'python.io'},
        {'type': 'boolean', 'prompt': 'Верно ли утверждение: 10 <= 10?', 'options': ['Да, утверждение верно', 'Нет, утверждение неверно'], 'expected': 'Да, утверждение верно', 'skill': 'python.conditions'},
        {'type': 'code', 'prompt': 'Напишите выражение, которое выводит число 4.', 'options': [], 'expected': '4', 'skill': 'python.expressions'},
        {'type': 'choice', 'prompt': 'Какой оператор используется для ветвления?', 'options': ['if', 'for', 'def', 'import'], 'expected': 'if', 'skill': 'python.conditions'},
    ]
    algorithms = [
        {'type': 'choice', 'prompt': 'Что делает цикл for?', 'options': ['Повторяет действия для элементов последовательности', 'Создаёт файл', 'Удаляет переменную'], 'expected': 'Повторяет действия для элементов последовательности', 'skill': 'python.loops'},
        {'type': 'short_text', 'prompt': 'Что выведет программа: print(len("ЕГЭ"))?', 'options': [], 'expected': '3', 'skill': 'python.strings'},
        {'type': 'code', 'prompt': 'Запишите условие, проверяющее, что x больше 0.', 'options': [], 'expected': 'x > 0', 'skill': 'python.conditions'},
        {'type': 'boolean', 'prompt': 'Верно ли: список [1, 2] содержит два элемента?', 'options': ['Да', 'Нет'], 'expected': 'Да', 'skill': 'python.collections'},
        {'type': 'choice', 'prompt': 'Какой оператор сравнивает равенство значений?', 'options': ['==', '=', '!=', '=>'], 'expected': '==', 'skill': 'python.conditions'},
    ]
    mixed = [
        {'type': 'choice', 'prompt': 'Какой результат имеет 2 ** 3?', 'options': ['5', '6', '8', '9'], 'expected': '8', 'skill': 'python.arithmetic'},
        {'type': 'short_text', 'prompt': 'Переведите число 5 в двоичную запись.', 'options': [], 'expected': '101', 'skill': 'ege.binary'},
        {'type': 'boolean', 'prompt': 'Истинно ли условие: 7 % 2 == 1?', 'options': ['Да', 'Нет'], 'expected': 'Да', 'skill': 'python.arithmetic'},
        {'type': 'code', 'prompt': 'Напишите код, выводящий числа 1 и 2 через пробел.', 'options': [], 'expected': 'print(1, 2)', 'skill': 'python.io'},
        {'type': 'choice', 'prompt': 'С чего начинается выполнение программы?', 'options': ['С первой команды', 'С последней команды', 'С комментария'], 'expected': 'С первой команды', 'skill': 'python.basics'},
    ]
    intro = [
        {'type': 'choice', 'prompt': 'Где ученик видит свою учебную программу?', 'options': ['В разделе «Курсы»', 'Только в профиле преподавателя', 'В настройках браузера'], 'expected': 'В разделе «Курсы»', 'skill': 'platform.program', 'phase': 'orientation'},
        {'type': 'choice', 'prompt': 'Что открывает теоретический материал?', 'options': ['Карточка урока или темы', 'Только чат', 'Панель администратора'], 'expected': 'Карточка урока или темы', 'skill': 'platform.theory', 'phase': 'theory'},
        {'type': 'code', 'prompt': 'Выполните первую мини-задачу: выведите число 2.', 'options': [], 'expected': '2', 'skill': 'python.first_task', 'phase': 'practice'},
        {'type': 'short_text', 'prompt': 'Какой раздел показывает прогресс обучения?', 'options': [], 'expected': 'аналитика', 'skill': 'platform.analytics', 'phase': 'analytics'},
        {'type': 'boolean', 'prompt': 'Можно ли вернуться к незавершённой гостевой сессии по ссылке?', 'options': ['Да', 'Нет'], 'expected': 'Да', 'skill': 'platform.return', 'phase': 'return'},
        {'type': 'short_text', 'prompt': 'Что бы вы хотели изучить первым?', 'options': [], 'expected': '', 'skill': 'platform.goal', 'phase': 'finish'},
    ]
    if template_key.startswith('trial_ege_full_'):
        return _ege_variant_specs(int(template_key.rsplit('_', 1)[-1]) - 1)
    catalogs = {'intro_platform_tour': intro}
    base = catalogs.get(template_key, python_start)
    if template_key.startswith('trial_'):
        # Каждый системный вариант — полноценный диагностический пробник из
        # 19 коротких заданий. Базовые задания сохраняются, хвост добирается
        # тематическими заданиями без привязки к демонстрационным данным.
        extras = [
            {'type': 'short_text', 'prompt': 'Что выведет программа: print(10 - 4)?', 'options': [], 'expected': '6', 'skill': 'python.arithmetic'},
            {'type': 'choice', 'prompt': 'Как обозначается комментарий в Python?', 'options': ['#', '//', '<!--', '--'], 'expected': '#', 'skill': 'python.syntax'},
            {'type': 'code', 'prompt': 'Запишите выражение, которое вычисляет квадрат x.', 'options': [], 'expected': 'x**2', 'skill': 'python.arithmetic'},
            {'type': 'boolean', 'prompt': 'Верно ли: len([4, 5, 6]) равен 3?', 'options': ['Да', 'Нет'], 'expected': 'Да', 'skill': 'python.collections'},
            {'type': 'choice', 'prompt': 'Какой тип данных хранит последовательность элементов?', 'options': ['list', 'int', 'float', 'None'], 'expected': 'list', 'skill': 'python.collections'},
            {'type': 'short_text', 'prompt': 'Чему равен остаток от деления 17 на 5?', 'options': [], 'expected': '2', 'skill': 'python.arithmetic'},
            {'type': 'choice', 'prompt': 'Какой оператор логически означает «и»?', 'options': ['and', 'or', 'not', 'in'], 'expected': 'and', 'skill': 'python.conditions'},
            {'type': 'code', 'prompt': 'Напишите вызов print для вывода строки Hello.', 'options': [], 'expected': 'print("Hello")', 'skill': 'python.io'},
            {'type': 'boolean', 'prompt': 'Верно ли: цикл while повторяется, пока условие истинно?', 'options': ['Да', 'Нет'], 'expected': 'Да', 'skill': 'python.loops'},
            {'type': 'short_text', 'prompt': 'Переведите число 8 в двоичную запись.', 'options': [], 'expected': '1000', 'skill': 'ege.binary'},
            {'type': 'choice', 'prompt': 'Какая функция считывает строку с клавиатуры?', 'options': ['input', 'print', 'len', 'range'], 'expected': 'input', 'skill': 'python.io'},
            {'type': 'code', 'prompt': 'Запишите условие, проверяющее, что n равно 10.', 'options': [], 'expected': 'n == 10', 'skill': 'python.conditions'},
            {'type': 'boolean', 'prompt': 'Верно ли: индексация списка в Python начинается с нуля?', 'options': ['Да', 'Нет'], 'expected': 'Да', 'skill': 'python.collections'},
            {'type': 'choice', 'prompt': 'Что возвращает функция len?', 'options': ['Количество элементов', 'Последний элемент', 'Тип переменной'], 'expected': 'Количество элементов', 'skill': 'python.basics'},
        ]
        return (base + extras)[:19]
    return base


def _template_seed_rows():
    return [
        ('trial_ege_full_1', 'TRIAL_EXAM', TRIAL_TEMPLATES['trial_ege_full_1'], 2),
        ('trial_ege_full_2', 'TRIAL_EXAM', TRIAL_TEMPLATES['trial_ege_full_2'], 2),
        ('trial_ege_full_3', 'TRIAL_EXAM', TRIAL_TEMPLATES['trial_ege_full_3'], 2),
        ('intro_platform_tour', 'INTRO_LESSON', INTRO_TEMPLATES['intro_platform_tour'], 1),
    ]


def _ensure_guest_templates():
    """Идемпотентно создаёт системные версии сценариев в БД."""
    changed = False
    for key, session_type, meta, version in _template_seed_rows():
        item = GuestTemplate.query.filter_by(template_key=key).first()
        specs = _task_specs(key)
        config = {
            'task_count': len(specs),
            'expected_duration_minutes': 235 if key.startswith('trial_ege_full_') else 30,
            'flow': [task.get('phase') for task in specs if task.get('phase')],
        }
        if item is None:
            item = GuestTemplate(template_key=key, session_type=session_type, title=meta['title'], description=meta['description'], version=version, config=config, is_active=True)
            db.session.add(item)
            changed = True
        elif item.is_active is False:
            item.is_active = True
            changed = True
        # System templates are versioned snapshots.  If an older deployment
        # seeded the short five-task catalog, upgrade only that system row;
        # teacher-authored templates are never rewritten here.
        elif item.version < version or (key.startswith('trial_ege_full_') and (item.config or {}).get('task_count') != 27):
            item.version = version
            item.config = config
            item.title = meta['title']
            item.description = meta['description']
            changed = True
    for retired_key in ('trial_python_start', 'trial_algorithms', 'trial_mixed'):
        retired = GuestTemplate.query.filter_by(template_key=retired_key).first()
        if retired and retired.is_active:
            retired.is_active = False
            changed = True
    if changed:
        db.session.commit()


def _session_link(session):
    """Возвращает постоянный публичный адрес сессии.

    Длинный токен по-прежнему хранится для совместимости и изоляции ранее
    выданных сессий, но не может быть восстановлен из хеша. Короткий код
    уникален, хранится в модели и потому безопасно показывается преподавателю
    после любого обновления страницы.
    """
    return url_for('guest.join_by_code', code=session.access_code, _external=True)


def _new_code():
    for _ in range(20):
        candidate = secrets.token_urlsafe(6).replace('_', '').replace('-', '').upper()[:8]
        if candidate and not GuestSession.query.filter_by(access_code=candidate).first():
            return candidate
    raise RuntimeError('Не удалось создать уникальный код гостевой сессии')


def _session_by_token(raw_token):
    session_obj = GuestSession.query.filter_by(access_token_hash=_hash(raw_token)).first()
    # Короткий код предназначен для ручного ввода. Он только находит сессию;
    # рабочие данные по-прежнему требуют отдельной participant-cookie.
    if not session_obj:
        session_obj = GuestSession.query.filter_by(access_code=str(raw_token).strip().upper()).first()
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


def _participant_deadline(session_obj, participant):
    settings = session_obj.settings or {}
    if not _as_bool(settings.get('timed'), False):
        return None
    minutes = int(settings.get('expected_duration_minutes') or 0)
    if not minutes:
        return None
    joined_at = participant.joined_at
    if joined_at.tzinfo is None:
        joined_at = joined_at.replace(tzinfo=utc_now().tzinfo)
    return joined_at + timedelta(minutes=max(1, minutes))


def _force_submit_expired_participant(session_obj, participant):
    """Фиксирует истёкшую попытку без доверия к клиентскому таймеру."""
    if participant.status != 'active':
        return
    responses = GuestResponse.query.filter_by(participant_id=participant.id).all()
    for response_obj in responses:
        response_obj.status = 'submitted'
        response_obj.submitted_at = utc_now()
        expected = (response_obj.task.expected_answer or '').strip().lower()
        actual = (response_obj.answer_text or '').strip().lower()
        response_obj.auto_checked = response_obj.task.task_type in {'choice', 'boolean', 'short_text', 'code'}
        if response_obj.auto_checked:
            response_obj.score = response_obj.task.max_score if actual == expected else 0
            response_obj.error_reason = None if response_obj.score == response_obj.task.max_score else 'INCOMPLETE_SOLUTION'
        else:
            response_obj.score = None
            response_obj.error_reason = None
    participant.status = 'submitted'
    participant.submitted_at = utc_now()
    review = GuestReview.query.filter_by(session_id=session_obj.id, participant_id=participant.id).first()
    if not review:
        review = GuestReview(session_id=session_obj.id, participant_id=participant.id)
        db.session.add(review)
    review.status = 'pending'
    review.total_score = sum((item.score or 0) for item in responses)
    review.max_score = sum(task.max_score for task in session_obj.tasks)
    review.report = _diagnostic_report(participant)
    _event(session_obj, participant, 'session.time_expired', {'deadline': _participant_deadline(session_obj, participant).isoformat()})
    db.session.commit()


def _event(session_obj, participant, name, payload=None):
    db.session.add(GuestActivity(session_id=session_obj.id, participant_id=getattr(participant, 'id', None), event=name, payload=payload or {}))


def _diagnostic_report(participant):
    """Строит объяснимый отчёт из сохранённых ответов, а не из demo-данных."""
    buckets = {}
    for response in participant.responses:
        skill = response.task.skill_key or 'общие навыки'
        bucket = buckets.setdefault(skill, {'skill': skill, 'earned': 0, 'maximum': 0, 'answered': 0, 'errors': 0})
        bucket['maximum'] += response.task.max_score
        final = response.teacher_score if response.teacher_score is not None else response.score
        if final is not None:
            bucket['earned'] += final
        if (response.answer_text or '').strip() or response.answer_json:
            bucket['answered'] += 1
        if final is not None and final < response.task.max_score:
            bucket['errors'] += 1
    for bucket in buckets.values():
        bucket['percent'] = round(bucket['earned'] / bucket['maximum'] * 100) if bucket['maximum'] else 0
    ordered = sorted(buckets.values(), key=lambda value: (-value['percent'], value['skill']))
    return {
        'skills': ordered,
        'strong': [value['skill'] for value in ordered if value['percent'] >= 70][:5],
        'attention': [value['skill'] for value in ordered if value['percent'] < 70][:5],
        'loss_reasons': {
            reason: sum(1 for response in participant.responses if response.error_reason == reason)
            for reason in ('KNOWLEDGE_GAP', 'CALCULATION_ERROR', 'FORMATTING_ERROR', 'INATTENTION', 'INCOMPLETE_SOLUTION', 'OTHER')
        },
    }


@guest_bp.get('/teacher/guest-sessions')
@require_role('teacher', 'tutor', 'creator', 'admin', 'chief_admin')
def teacher_sessions():
    _ensure_guest_templates()
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
@require_role('teacher', 'tutor', 'creator', 'admin', 'chief_admin')
def teacher_session_detail(session_id):
    item = GuestSession.query.filter_by(id=session_id, teacher_id=current_user.id).first_or_404()
    return render_template('guest/teacher_detail.html', guest_session=item)


@guest_bp.get('/teacher/guest-sessions/<int:session_id>/timeline')
@require_role('teacher', 'tutor', 'creator', 'admin', 'chief_admin')
def teacher_session_timeline(session_id):
    item = GuestSession.query.filter_by(id=session_id, teacher_id=current_user.id).first_or_404()
    try:
        limit = min(max(int(request.args.get('limit', 100)), 1), 500)
    except (TypeError, ValueError):
        return jsonify(error='Параметр limit должен быть числом от 1 до 500'), 400
    events = (GuestActivity.query.filter_by(session_id=item.id)
              .order_by(GuestActivity.created_at.desc(), GuestActivity.id.desc())
              .limit(limit).all())
    return jsonify(events=[{
        'id': event.id,
        'event': event.event,
        'payload': event.payload or {},
        'participant_id': event.participant_id,
        'created_at': event.created_at.isoformat(),
    } for event in events])


@guest_bp.post('/teacher/guest-sessions')
@require_role('teacher', 'tutor', 'creator', 'admin', 'chief_admin')
def create_session():
    _ensure_guest_templates()
    data = request.get_json(silent=True) or request.form
    session_type = str(data.get('session_type', 'TRIAL_EXAM')).upper()
    template_key = str(data.get('template_key', 'trial_ege_full_1'))
    if session_type not in SESSION_TYPES:
        return jsonify(error='Неверный тип гостевой сессии'), 400
    template = GuestTemplate.query.filter_by(template_key=template_key, session_type=session_type, is_active=True).first()
    if template is None:
        return jsonify(error='Шаблон не найден'), 400
    try:
        duration_hours = int(data.get('duration_hours', 24 if session_type == 'INTRO_LESSON' else 24 * 7))
        max_participants = int(data.get('max_participants', 1))
    except (TypeError, ValueError):
        return jsonify(error='Срок и лимит участников должны быть числами'), 400
    if not 1 <= duration_hours <= 24 * 90:
        return jsonify(error='Срок должен быть от 1 часа до 90 дней'), 400
    if not 1 <= max_participants <= 100:
        return jsonify(error='Лимит участников должен быть от 1 до 100'), 400
    title = str(data.get('title') or template.title).strip()[:180] or template.title
    settings = {
        'title': title,
        'template_version': template.version,
        'flow': template.config.get('flow', []),
        'allow_photos': _as_bool(data.get('allow_photos'), True),
        'allow_drawings': _as_bool(data.get('allow_drawings'), True),
        'allow_comments': _as_bool(data.get('allow_comments'), True),
        'timed': _as_bool(data.get('timed'), False),
        'expected_duration_minutes': int((template.config or {}).get('expected_duration_minutes', 180 if session_type == 'TRIAL_EXAM' else 30)),
    }
    raw_token = secrets.token_urlsafe(32)
    expires = utc_now() + timedelta(hours=duration_hours)
    session_obj = GuestSession(teacher_id=current_user.id, session_type=session_type, access_code=_new_code(), access_token_hash=_hash(raw_token), template_key=template_key, template_id=template.id, expires_at=expires, max_participants=max_participants, settings=settings)
    db.session.add(session_obj)
    db.session.flush()
    specs = _task_specs(template_key)
    for position, spec in enumerate(specs, start=1):
        db.session.add(GuestTask(session_id=session_obj.id, source_task_id=spec.get('source_task_id'), position=position, task_type=spec['type'], prompt=spec['prompt'], options=spec['options'], expected_answer=spec['expected'], skill_key=spec['skill'], metadata_json={
            'template': template_key,
            'phase': spec.get('phase', 'practice'),
            'task_number': spec.get('task_number', position),
            'source_url': spec.get('source_url'),
            'attachments': spec.get('attachments', []),
            'manual_review': bool(spec.get('manual_review')),
        }))
    if session_type == 'INTRO_LESSON':
        db.session.add(GuestDemoSnapshot(session_id=session_obj.id, source_template_key=template.template_key, source_template_version=template.version, payload={
            'title': template.title,
            'sections': [
                {'key': 'welcome', 'label': 'СТАРТ', 'title': 'Добро пожаловать', 'body': 'За несколько минут вы увидите путь ученика: цель, программа, теория, практика и результат.'},
                {'key': 'dashboard', 'label': 'ДЕМО', 'title': 'Личный dashboard', 'body': 'В нём собраны ближайшие занятия, текущие работы, прогресс, сильные темы и подсказки наставника.'},
                {'key': 'program', 'label': 'МАРШРУТ', 'title': 'Индивидуальная программа', 'body': 'Программа состоит из модулей и уроков. После диагностики порядок тем уточняется по вашим ответам и навыкам.'},
                {'key': 'theory', 'label': 'ТЕОРИЯ', 'title': 'Теория с практикой', 'body': 'Каждая тема объясняется короткими блоками и сразу закрепляется мини-задачей, кодом или проверкой понимания.'},
                {'key': 'analytics', 'label': 'АНАЛИТИКА', 'title': 'Прогресс и прогноз', 'body': 'Результаты проверок превращаются в метрики: выполнение, баллы, навыки, пробелы и следующий рекомендуемый шаг.'},
                {'key': 'next', 'label': 'ДАЛЬШЕ', 'title': 'Предварительный маршрут', 'body': 'После вводного задания вы получите первый ориентир. Это не финальная оценка, а точка старта для полноценной диагностики.'},
            ],
            'dashboard': {'goal': '80+ баллов', 'forecast': 62, 'progress': 37, 'strong_topics': ['№1', '№5', '№6'], 'attention_topics': ['№13', '№15', '№16'], 'last_trial': 59},
            'template_version': template.version,
        }))
    _event(session_obj, None, 'session.created', {'type': session_type, 'template': template_key})
    db.session.commit()
    return jsonify(id=session_obj.id, code=session_obj.access_code, link=_session_link(session_obj), expires_at=session_obj.expires_at.isoformat())


@guest_bp.post('/teacher/guest-sessions/<int:session_id>/close')
@require_role('teacher', 'tutor', 'creator', 'admin', 'chief_admin')
def close_session(session_id):
    item = GuestSession.query.filter_by(id=session_id, teacher_id=current_user.id).first_or_404()
    item.status = 'closed'
    item.closed_at = utc_now()
    db.session.commit()
    return jsonify(status=item.status)


def _session_expiry_hours(session_type):
    return 24 if session_type == 'INTRO_LESSON' else 24 * 7


@guest_bp.post('/teacher/guest-sessions/<int:session_id>/extend')
@require_role('teacher', 'tutor', 'creator', 'admin', 'chief_admin')
def extend_session(session_id):
    item = GuestSession.query.filter_by(id=session_id, teacher_id=current_user.id).first_or_404()
    data = request.get_json(silent=True) or request.form
    try:
        hours = int(data.get('hours', _session_expiry_hours(item.session_type)))
    except (TypeError, ValueError):
        return jsonify(error='Укажите срок в часах'), 400
    if hours < 1 or hours > 24 * 90:
        return jsonify(error='Срок должен быть от 1 часа до 90 дней'), 400
    item.expires_at = utc_now() + timedelta(hours=hours)
    if item.status == 'closed':
        item.status = 'active'
        item.closed_at = None
        item.reopened_at = utc_now()
    _event(item, None, 'session.extended', {'hours': hours})
    db.session.commit()
    return jsonify(status=item.status, expires_at=item.expires_at.isoformat())


@guest_bp.post('/teacher/guest-sessions/<int:session_id>/reopen')
@require_role('teacher', 'tutor', 'creator', 'admin', 'chief_admin')
def reopen_session(session_id):
    item = GuestSession.query.filter_by(id=session_id, teacher_id=current_user.id).first_or_404()
    data = request.get_json(silent=True) or request.form
    try:
        hours = int(data.get('hours', _session_expiry_hours(item.session_type)))
    except (TypeError, ValueError):
        hours = _session_expiry_hours(item.session_type)
    hours = max(1, min(hours, 24 * 90))
    item.status = 'active'
    item.closed_at = None
    item.reopened_at = utc_now()
    item.expires_at = utc_now() + timedelta(hours=hours)
    _event(item, None, 'session.reopened', {'hours': hours})
    db.session.commit()
    return jsonify(status=item.status, expires_at=item.expires_at.isoformat())


@guest_bp.post('/teacher/guest-sessions/<int:session_id>/rotate-link')
@require_role('teacher', 'tutor', 'creator', 'admin', 'chief_admin')
def rotate_session_link(session_id):
    item = GuestSession.query.filter_by(id=session_id, teacher_id=current_user.id).first_or_404()
    raw_token = secrets.token_urlsafe(32)
    item.access_token_hash = _hash(raw_token)
    item.access_code = _new_code()
    item.access_token_rotated_at = utc_now()
    _event(item, None, 'session.link_rotated')
    db.session.commit()
    return jsonify(code=item.access_code, link=_session_link(item))


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


@guest_bp.get('/guest/code/<code>')
def join_by_code(code):
    """Человеко-читаемый вход: код лишь идентифицирует сессию, а cookie
    участника выдаётся только после ввода имени и не заменяет длинный токен."""
    normalized_code = str(code).strip().upper()
    # Проверяем жизненный цикл до redirect, чтобы закрытая или истёкшая ссылка
    # сразу отдала корректный HTTP-статус, а не временный 302.
    _session_by_token(normalized_code)
    return redirect(url_for('guest.join_session', token=normalized_code))


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
    deadline = _participant_deadline(item, participant)
    if deadline and utc_now() >= deadline and participant.status == 'active':
        _force_submit_expired_participant(item, participant)
        participant = GuestParticipant.query.get(participant.id)
    if participant.status == 'submitted':
        return item, participant
    return item, participant


@guest_bp.post('/guest/s/<token>/api/presence')
@csrf.exempt
def guest_presence(token):
    item, participant = _require_guest(token)
    participant.last_seen_at = utc_now()
    _event(item, participant, 'participant.active')
    db.session.commit()
    return jsonify(active=True, last_seen_at=participant.last_seen_at.isoformat())


@guest_bp.get('/guest/s/<token>/api/state')
def guest_state(token):
    """Полный продолжимый снимок текущей попытки для восстановления после reload."""
    item, participant = _require_guest(token)
    responses = GuestResponse.query.filter_by(participant_id=participant.id).all()
    deadline = _participant_deadline(item, participant)
    return jsonify(
        session={'id': item.id, 'type': item.session_type, 'status': item.status,
                 'template_key': item.template_key, 'template_version': (item.settings or {}).get('template_version'),
                 'flow': (item.settings or {}).get('flow', []),
                 'timed': bool(deadline), 'deadline': deadline.isoformat() if deadline else None,
                 'server_now': utc_now().isoformat()},
        participant={'id': participant.id, 'status': participant.status, 'onboarding_state': participant.onboarding_state or {}},
        snapshot=(item.demo_snapshot.payload if item.demo_snapshot else None),
        responses=[{
            'task_id': response.task_id,
            'answer_text': response.answer_text or '',
            'answer_json': response.answer_json,
            'comment': response.comment or '',
            'flagged': bool(response.flagged),
            'attachments': [{'name': attachment.original_name, 'size': attachment.size_bytes} for attachment in response.attachments],
            'drawing': (response.drawings[-1].payload if response.drawings else None),
        } for response in responses],
    )


@guest_bp.get('/guest/s/<token>/work')
def guest_workspace(token):
    item, participant = _require_guest(token)
    return render_template('guest/workspace.html', guest_session=item, participant=participant, snapshot=item.demo_snapshot, token=token)


@guest_bp.get('/guest/s/<token>/result')
def guest_result(token):
    item, participant = _require_guest(token)
    review = GuestReview.query.filter_by(session_id=item.id, participant_id=participant.id).first()
    return render_template('guest/result.html', guest_session=item, participant=participant, review=review, snapshot=item.demo_snapshot, token=token)


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
    settings = item.settings or {}
    if not _as_bool(settings.get('allow_comments'), True) and str(data.get('comment', '')).strip():
        return jsonify(error='Комментарии отключены для этой сессии'), 403
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


@guest_bp.post('/guest/s/<token>/api/responses/<int:task_id>/run-code')
@csrf.exempt
@limiter.limit('30/minute')
def run_guest_code(token, task_id):
    """Запускает черновик гостя в той же безопасной EGE-песочнице, что и V2 workspace."""
    item, participant = _require_guest(token)
    if participant.status == 'submitted':
        return jsonify(error='Сессия уже отправлена'), 409
    GuestTask.query.filter_by(id=task_id, session_id=item.id).first_or_404()
    data = request.get_json(silent=True) or {}
    code = normalize_leading_tabs_to_spaces(str(data.get('code') or ''))
    if not code.strip():
        return jsonify(error='Введите код для запуска'), 400
    if len(code) > 40_000:
        return jsonify(error='Код превышает лимит 40 000 символов'), 413
    stdout, stderr, turtle_b64 = run_python_sandbox(code, timeout_sec=15)
    _event(item, participant, 'workspace.code_run', {'task_id': task_id, 'ok': not bool(stderr)})
    db.session.commit()
    payload = {'ok': not bool(stderr), 'stdout': stdout, 'stderr': stderr}
    if turtle_b64:
        payload['turtle_image_b64'] = turtle_b64
        payload['turtle_image_mime'] = 'image/svg+xml' if turtle_b64.startswith('PHN2Zy') else 'image/png'
    return jsonify(payload)


@guest_bp.get('/guest/s/<token>/attachments/<int:task_id>/<int:attachment_index>')
def download_guest_source_attachment(token, task_id, attachment_index):
    """Отдаёт только вложение из сохранённого snapshot через guest-сессию.

    Внешний Kompege URL не доступен напрямую из части браузеров, поэтому proxy
    получает его на сервере. Индекс и домен проверяются до исходящего запроса.
    """
    item, _participant = _require_guest(token)
    task = GuestTask.query.filter_by(id=task_id, session_id=item.id).first_or_404()
    attachments = (task.metadata_json or {}).get('attachments') or []
    if not 0 <= attachment_index < len(attachments):
        abort(404)
    attachment = attachments[attachment_index] if isinstance(attachments[attachment_index], dict) else {}
    remote_url = str(attachment.get('url') or '')
    parsed = urlparse(remote_url)
    if parsed.scheme not in {'http', 'https'} or parsed.hostname not in {'kompege.ru', 'www.kompege.ru'}:
        abort(404)
    try:
        remote = requests.get(remote_url, timeout=(5, 25), headers={'User-Agent': 'BooStudy guest attachment proxy/1.0'})
        remote.raise_for_status()
    except requests.RequestException:
        return jsonify(error='Не удалось получить исходный файл. Попробуйте ещё раз позже.'), 502
    max_size = 25 * 1024 * 1024
    content = remote.content
    if len(content) > max_size:
        return jsonify(error='Исходный файл слишком большой для гостевой сессии'), 413
    file_name = secure_filename(str(attachment.get('name') or 'source-file')) or 'source-file'
    response = Response(content, mimetype=remote.headers.get('Content-Type', 'application/octet-stream'))
    response.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote(file_name)}"
    response.headers['Cache-Control'] = 'private, max-age=300'
    return response


@guest_bp.post('/guest/s/<token>/api/responses/<int:task_id>/drawing')
@csrf.exempt
def save_drawing(token, task_id):
    item, participant = _require_guest(token)
    if participant.status == 'submitted':
        return jsonify(error='Сессия уже отправлена'), 409
    if not _as_bool((item.settings or {}).get('allow_drawings'), True):
        return jsonify(error='Рисунки отключены для этой сессии'), 403
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
    if participant.status == 'submitted':
        return jsonify(error='Сессия уже отправлена'), 409
    task = GuestTask.query.filter_by(id=task_id, session_id=item.id).first_or_404()
    files = [file for file in request.files.getlist('file') if file and file.filename]
    if not files:
        return jsonify(error='Файл не выбран'), 400
    max_size = int(current_app.config.get('GUEST_MAX_FILE_BYTES', 10 * 1024 * 1024))
    sizes = []
    for file in files:
        file.stream.seek(0, 2)
        size = file.stream.tell()
        file.stream.seek(0)
        if file.mimetype and file.mimetype.startswith('image/') and not _as_bool((item.settings or {}).get('allow_photos'), True):
            return jsonify(error='Загрузка фотографий отключена для этой сессии'), 403
        if size > max_size:
            return jsonify(error=f'Файл {secure_filename(file.filename)} превышает допустимый размер'), 413
        sizes.append(size)
    response_obj = GuestResponse.query.filter_by(participant_id=participant.id, task_id=task.id).first()
    if not response_obj:
        response_obj = GuestResponse(participant_id=participant.id, task_id=task.id)
        db.session.add(response_obj)
        db.session.flush()
    root = current_app.config.get('GUEST_UPLOAD_ROOT') or current_app.instance_path
    import os
    os.makedirs(root, exist_ok=True)
    saved = []
    for file, size in zip(files, sizes):
        safe_name = secure_filename(file.filename)
        storage_key = f'guest/{item.id}/{participant.id}/{secrets.token_hex(12)}_{safe_name}'
        absolute = os.path.join(root, storage_key)
        os.makedirs(os.path.dirname(absolute), exist_ok=True)
        file.save(absolute)
        db.session.add(GuestAttachment(response_id=response_obj.id, original_name=safe_name, storage_key=storage_key, mime_type=file.mimetype or 'application/octet-stream', size_bytes=size))
        saved.append({'name': safe_name, 'size': size})
    db.session.commit()
    return jsonify(saved=True, files=saved)


@guest_bp.get('/teacher/guest-sessions/<int:session_id>/participants/<int:participant_id>/responses/<int:response_id>/files/<int:attachment_id>')
@require_role('teacher', 'tutor', 'creator', 'admin', 'chief_admin')
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
    data = request.get_json(silent=True) or {}
    # Блокируем участника на время сдачи: двойной клик/две вкладки не создают
    # две разные попытки и не перезаписывают итог.
    participant = (GuestParticipant.query.filter_by(id=participant.id)
                   .with_for_update().first_or_404())
    if participant.status == 'submitted':
        review = GuestReview.query.filter_by(session_id=item.id, participant_id=participant.id).first()
        return jsonify(status='submitted', result_url=url_for('guest.guest_result', token=token), total_score=getattr(review, 'total_score', None))
    responses = GuestResponse.query.filter_by(participant_id=participant.id).all()
    missing = [task.position for task in item.tasks if not next((r for r in responses if r.task_id == task.id and ((r.answer_text or '').strip() or r.answer_json)), None)]
    if missing and not bool(data.get('force')):
        return jsonify(error='Заполните все задания или подтвердите сдачу с пропусками', incomplete=True, missing=missing), 409
    for response_obj in responses:
        response_obj.status = 'submitted'
        response_obj.submitted_at = utc_now()
        expected = (response_obj.task.expected_answer or '').strip().lower()
        actual = (response_obj.answer_text or '').strip().lower()
        if response_obj.task.task_type in {'choice', 'boolean', 'short_text'}:
            response_obj.score = response_obj.task.max_score if actual == expected else 0
            response_obj.auto_checked = True
        elif response_obj.task.task_type == 'code':
            normalized = ''.join(actual.split())
            accepted = {expected, 'print(2+2)', 'print(4)', '4'}
            response_obj.score = response_obj.task.max_score if normalized in accepted else 0
            response_obj.auto_checked = True
        if response_obj.auto_checked:
            response_obj.error_reason = None if response_obj.score == response_obj.task.max_score else (
                'INCOMPLETE_SOLUTION' if not actual and not response_obj.answer_json else 'KNOWLEDGE_GAP'
            )
        else:
            response_obj.score = None
            response_obj.error_reason = None
    participant.status = 'submitted'
    participant.submitted_at = utc_now()
    total = sum((r.score or 0) for r in responses)
    maximum = sum(t.max_score for t in item.tasks)
    review = GuestReview.query.filter_by(session_id=item.id, participant_id=participant.id).first()
    if not review:
        review = GuestReview(session_id=item.id, participant_id=participant.id)
        db.session.add(review)
    review.status = 'pending'
    review.total_score = total
    review.max_score = maximum
    review.report = _diagnostic_report(participant)
    _event(item, participant, 'session.submitted', {'total_score': total, 'max_score': maximum})
    db.session.commit()
    return jsonify(status='submitted', result_url=url_for('guest.guest_result', token=token), total_score=total, max_score=maximum)


@guest_bp.post('/teacher/guest-sessions/<int:session_id>/participants/<int:participant_id>/review')
@require_role('teacher', 'tutor', 'creator', 'admin', 'chief_admin')
def review_participant(session_id, participant_id):
    item = GuestSession.query.filter_by(id=session_id, teacher_id=current_user.id).first_or_404()
    participant = GuestParticipant.query.filter_by(id=participant_id, session_id=item.id).first_or_404()
    data = request.get_json(silent=True) or request.form
    if participant.status not in {'submitted', 'converted'}:
        return jsonify(error='Участник ещё не отправил работу'), 409
    for value in data.get('responses', []) if isinstance(data.get('responses'), list) else []:
        response_obj = GuestResponse.query.filter_by(id=value.get('id'), participant_id=participant.id).first()
        if response_obj:
            try:
                teacher_score = int(value.get('score', 0))
            except (TypeError, ValueError):
                return jsonify(error='Баллы должны быть целым числом'), 400
            response_obj.teacher_score = max(0, min(response_obj.task.max_score, teacher_score))
            response_obj.error_reason = str(value.get('error_reason') or '').upper() or None
            if response_obj.error_reason not in {None, 'KNOWLEDGE_GAP', 'CALCULATION_ERROR', 'FORMATTING_ERROR', 'INATTENTION', 'INCOMPLETE_SOLUTION', 'OTHER'}:
                return jsonify(error='Неизвестная причина потери баллов'), 400
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
    review.total_score = sum((r.teacher_score if r.teacher_score is not None else (r.score or 0)) for r in participant.responses)
    review.max_score = sum(t.max_score for t in item.tasks)
    review.report = _diagnostic_report(participant)
    review.completed_at = utc_now()
    db.session.commit()
    return jsonify(status='completed', total_score=review.total_score, max_score=review.max_score)


@guest_bp.post('/teacher/guest-sessions/<int:session_id>/participants/<int:participant_id>/convert')
@require_role('teacher', 'tutor', 'creator', 'admin', 'chief_admin')
def convert_participant(session_id, participant_id):
    item = GuestSession.query.filter_by(id=session_id, teacher_id=current_user.id).first_or_404()
    participant = (GuestParticipant.query.filter_by(id=participant_id, session_id=item.id)
                   .with_for_update().first_or_404())
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
