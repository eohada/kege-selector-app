"""
Формироватор банка заданий (фундамент).
Цель: инструментальная проверка спаршенных заданий: условие/ответ + статусы ревью.
"""
import logging
import re
from flask import render_template, request, jsonify
from flask_login import login_required, current_user
from sqlalchemy import func

from app.admin import admin_bp
from app.auth.rbac_utils import check_access
from app.models import db, Tasks, TaskReview

logger = logging.getLogger(__name__)


def _normalize_answer(raw: str) -> str:
    if raw is None:
        return ''
    s = str(raw).strip()
    s = re.sub(r'\s+', ' ', s)
    return s


def _extract_source_url_from_html(content_html: str) -> str:
    """Пытаемся восстановить ссылку на источник из HTML условия (если поле source_url пустое)."""
    if not content_html:
        return ''
    html = str(content_html)
    m = re.search(r'href\s*=\s*["\'](https?://[^"\']+)["\']', html, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m2 = re.search(r'(https?://[^\s<>"\']+)', html, flags=re.IGNORECASE)
    if m2:
        return m2.group(1).strip().rstrip(').,;')
    return ''


def _run_quick_checks(task: Tasks):
    """
    Быстрые проверки "в стиле ЕГЭ" (эвристики).
    Возвращает список чеков: {level: ok|warn|fail, title, details}
    """
    checks = []
    html = (task.content_html or '').strip()
    ans = _normalize_answer(task.answer)

    # 1) Условие
    if not html:
        checks.append({
            'level': 'fail',
            'title': 'Пустое условие',
            'details': 'content_html пустой. Вероятно, парсер не сохранил текст задания.'
        })
    else:
        text_len = len(re.sub(r'<[^>]+>', ' ', html))
        if text_len < 60:
            checks.append({
                'level': 'warn',
                'title': 'Слишком короткое условие',
                'details': f'Длина текста (без HTML) выглядит подозрительно маленькой: ~{text_len} символов.'
            })
        if 'undefined' in html.lower() or 'null' in html.lower():
            checks.append({
                'level': 'warn',
                'title': 'Подозрительные токены в условии',
                'details': 'В условии встречается "undefined"/"null". Часто это артефакт парсинга.'
            })

    # 2) Ответ (для 1-23 обычно обязателен)
    if task.task_number in list(range(1, 24)):
        if not ans:
            checks.append({
                'level': 'fail',
                'title': 'Нет ответа',
                'details': 'Для заданий 1–23 ожидается короткий ответ. Сейчас поле answer пустое.'
            })
        else:
            if len(ans) > 60:
                checks.append({
                    'level': 'warn',
                    'title': 'Слишком длинный ответ',
                    'details': f'Ответ слишком длинный для 1–23: {len(ans)} символов.'
                })
            if '<' in ans or '>' in ans:
                checks.append({
                    'level': 'warn',
                    'title': 'Ответ похож на HTML/мусор',
                    'details': 'В ответе есть символы "<" или ">". Возможно, ответ спарсился неправильно.'
                })
            if '\n' in (task.answer or ''):
                checks.append({
                    'level': 'warn',
                    'title': 'Многострочный ответ',
                    'details': 'Для 1–23 ответ обычно однострочный. Проверьте корректность.'
                })
            # эвристика: ответ должен содержать буквы/цифры/простые знаки
            if not re.fullmatch(r"[0-9A-Za-zА-Яа-я\-\+\*/=(),.\s:;%№]+", ans):
                checks.append({
                    'level': 'warn',
                    'title': 'Необычные символы в ответе',
                    'details': 'Ответ содержит необычные символы. Возможно, попали лишние куски.'
                })
    else:
        # 24-27 часто требуют ручной проверки: отсутствие ответа — не ошибка
        if not ans:
            checks.append({
                'level': 'ok',
                'title': 'Ответ не задан (нормально для ручной проверки)',
                'details': 'Для заданий 24–27 ответ может отсутствовать/быть неформальным.'
            })

    # 3) Ссылка-источник (не критично, но полезно)
    # Не превращаем это в постоянный WARN для старых данных: если есть site_task_id, ок.
    src_db = (task.source_url or '').strip()
    src_html = _extract_source_url_from_html(task.content_html or '')
    if not src_db:
        if src_html:
            checks.append({
                'level': 'ok',
                'title': 'Источник найден в условии',
                'details': f'Поле source_url пустое, но в HTML найден URL: {src_html}'
            })
        elif (task.site_task_id or '').strip():
            checks.append({
                'level': 'ok',
                'title': 'Нет source_url',
                'details': 'URL источника не сохранён, но есть site_task_id — верификация возможна.'
            })
        else:
            checks.append({
                'level': 'warn',
                'title': 'Нет source_url',
                'details': 'У задания не сохранён URL источника и нет site_task_id — сложнее верифицировать.'
            })

    if not checks:
        checks.append({'level': 'ok', 'title': 'Базовые проверки пройдены', 'details': 'Явных проблем не найдено.'})
    return checks


def _get_review(task_id: int):
    return TaskReview.query.filter_by(task_id=task_id).first()


@admin_bp.route('/admin/task-formator')
@login_required
@check_access('task.manage')
def admin_task_formator():
    q = (request.args.get('q') or '').strip()
    task_number = request.args.get('task_number', type=int)
    review_status = (request.args.get('review_status') or 'all').strip().lower()
    page = max(1, request.args.get('page', type=int) or 1)
    per_page = 30

    base = db.session.query(Tasks, TaskReview).outerjoin(TaskReview, TaskReview.task_id == Tasks.task_id)

    if task_number:
        base = base.filter(Tasks.task_number == task_number)

    if q:
        like = f"%{q.lower()}%"
        base = base.filter(
            func.lower(Tasks.content_html).like(like) |
            func.lower(func.coalesce(Tasks.answer, '')).like(like) |
            func.lower(func.coalesce(Tasks.source_url, '')).like(like) |
            func.lower(func.coalesce(Tasks.site_task_id, '')).like(like)
        )

    if review_status != 'all':
        if review_status == 'new':
            base = base.filter((TaskReview.status.is_(None)) | (TaskReview.status == 'new'))
        else:
            base = base.filter(TaskReview.status == review_status)

    total = base.count()
    items = base.order_by(Tasks.last_scraped.desc(), Tasks.task_id.desc()).offset((page - 1) * per_page).limit(per_page).all()

    # Сводка по статусам в текущем наборе (учитывая фильтры q/task_number)
    summary_base = db.session.query(Tasks.task_id, TaskReview.status).outerjoin(TaskReview, TaskReview.task_id == Tasks.task_id)
    if task_number:
        summary_base = summary_base.filter(Tasks.task_number == task_number)
    if q:
        like = f"%{q.lower()}%"
        summary_base = summary_base.filter(
            func.lower(Tasks.content_html).like(like) |
            func.lower(func.coalesce(Tasks.answer, '')).like(like) |
            func.lower(func.coalesce(Tasks.source_url, '')).like(like) |
            func.lower(func.coalesce(Tasks.site_task_id, '')).like(like)
        )
    rows = summary_base.all()
    new_count = 0
    ok_count = 0
    needs_fix_count = 0
    skip_count = 0
    for _, st in rows:
        stn = (st or 'new').lower()
        if stn == 'ok':
            ok_count += 1
        elif stn == 'needs_fix':
            needs_fix_count += 1
        elif stn == 'skip':
            skip_count += 1
        else:
            new_count += 1

    summary = {
        'new': new_count,
        'ok': ok_count,
        'needs_fix': needs_fix_count,
        'skip': skip_count,
    }

    # для селекта
    task_numbers = list(range(1, 28))

    return render_template(
        'admin_task_formator.html',
        q=q,
        task_number=task_number,
        review_status=review_status,
        page=page,
        per_page=per_page,
        total=total,
        items=items,
        summary=summary,
        task_numbers=task_numbers,
    )


@admin_bp.route('/admin/task-formator/api/task/<int:task_id>')
@login_required
@check_access('task.manage')
def admin_task_formator_task(task_id: int):
    task = Tasks.query.get_or_404(task_id)
    review = _get_review(task_id)
    checks = _run_quick_checks(task)
    derived = _extract_source_url_from_html(task.content_html or '') if not (task.source_url or '').strip() else ''
    effective_source = (task.source_url or '').strip() or derived or None
    return jsonify({
        'success': True,
        'task': {
            'task_id': task.task_id,
            'task_number': task.task_number,
            'site_task_id': task.site_task_id,
            'source_url': effective_source,
            'last_scraped': task.last_scraped.isoformat() if task.last_scraped else None,
            'content_html': task.content_html,
            'answer': task.answer or '',
        },
        'review': {
            'status': (review.status if review else 'new'),
            'notes': (review.notes if review else ''),
            'updated_at': (review.updated_at.isoformat() if review and review.updated_at else None),
        },
        'checks': checks,
    })


@admin_bp.route('/admin/task-formator/api/task/<int:task_id>/review', methods=['POST'])
@login_required
@check_access('task.manage')
def admin_task_formator_save_review(task_id: int):
    payload = request.get_json(silent=True) or {}
    status = (payload.get('status') or 'new').strip().lower()
    notes = (payload.get('notes') or '').strip()
    if status not in ['new', 'ok', 'needs_fix', 'skip']:
        return jsonify({'success': False, 'error': 'Некорректный статус'}), 400

    task = Tasks.query.get_or_404(task_id)
    review = _get_review(task_id)
    if not review:
        review = TaskReview(task_id=task.task_id, status=status, notes=notes, reviewer_user_id=current_user.id)
        db.session.add(review)
    else:
        review.status = status
        review.notes = notes
        review.reviewer_user_id = current_user.id

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to save TaskReview for task {task_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Ошибка сохранения'}), 500

    return jsonify({
        'success': True,
        'status': review.status,
        'notes': review.notes or '',
        'updated_at': review.updated_at.isoformat() if review.updated_at else None,
    })

