from __future__ import annotations

import json
import logging

from flask import render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from app.rubrics import rubrics_bp
from app.models import db, RubricTemplate
from app.auth.rbac_utils import check_access
from core.audit_logger import audit_logger

logger = logging.getLogger(__name__)


def _can_manage_all() -> bool:
    try:
        return bool(getattr(current_user, 'is_creator', None) and current_user.is_creator()) or bool(getattr(current_user, 'is_admin', None) and current_user.is_admin())
    except Exception:
        return False


def _parse_items(raw: str) -> list[dict]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if not isinstance(data, list):
        return []

    out: list[dict] = []
    seen = set()
    for idx, it in enumerate(data):
        if not isinstance(it, dict):
            continue
        key = str((it.get('key') or '')).strip()
        title = str((it.get('title') or '')).strip()
        if not title:
            continue
        if not key:
            key = f"c{idx+1}"
        # уникальность key
        base = key
        suffix = 1
        while key in seen:
            suffix += 1
            key = f"{base}{suffix}"
        seen.add(key)

        max_score = it.get('max_score', None)
        try:
            max_score = int(max_score) if max_score is not None and str(max_score) != '' else None
        except Exception:
            max_score = None
        if max_score is not None and max_score < 0:
            max_score = 0

        out.append({
            'key': key,
            'title': title,
            'description': str((it.get('description') or '')).strip() or None,
            'max_score': max_score,
        })
    return out[:50]


@rubrics_bp.route('/rubrics')
@login_required
@check_access('assignment.grade')
def rubrics_list():
    q = (request.args.get('q') or '').strip()
    assignment_type = (request.args.get('assignment_type') or '').strip().lower()

    base = RubricTemplate.query.filter(RubricTemplate.is_active.is_(True))
    if not _can_manage_all():
        base = base.filter(RubricTemplate.owner_user_id == current_user.id)
    if q:
        like = f"%{q.lower()}%"
        base = base.filter(db.func.lower(RubricTemplate.title).like(like))
    if assignment_type:
        base = base.filter(db.func.lower(RubricTemplate.assignment_type) == assignment_type)

    templates = base.order_by(RubricTemplate.updated_at.desc(), RubricTemplate.created_at.desc(), RubricTemplate.rubric_id.desc()).limit(200).all()
    return render_template('rubrics_list.html', templates=templates, q=q, assignment_type=assignment_type)


@rubrics_bp.route('/rubrics/new', methods=['GET', 'POST'])
@login_required
@check_access('assignment.grade')
def rubric_new():
    if request.method == 'GET':
        return render_template('rubric_form.html', rubric=None, items_json='[]', is_new=True)

    title = (request.form.get('title') or '').strip()
    assignment_type = (request.form.get('assignment_type') or '').strip().lower() or None
    description = (request.form.get('description') or '').strip() or None
    items = _parse_items(request.form.get('items_json') or '[]')

    if not title:
        flash('Название рубрики обязательно.', 'danger')
        return render_template('rubric_form.html', rubric=None, items_json=json.dumps(items, ensure_ascii=False), is_new=True), 400

    if assignment_type and assignment_type not in {'homework', 'classwork', 'exam', 'test', 'diagnostic'}:
        assignment_type = None

    rubric = RubricTemplate(
        owner_user_id=current_user.id,
        title=title,
        assignment_type=assignment_type,
        description=description,
        items=items,
        is_active=True,
    )
    db.session.add(rubric)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='rubric_create', entity='RubricTemplate', error=str(e))
        flash('Не удалось сохранить рубрику.', 'danger')
        return render_template('rubric_form.html', rubric=None, items_json=json.dumps(items, ensure_ascii=False), is_new=True), 500

    try:
        audit_logger.log(action='rubric_create', entity='RubricTemplate', entity_id=rubric.rubric_id, status='success', metadata={'items': len(items)})
    except Exception:
        pass

    flash('Рубрика создана.', 'success')
    return redirect(url_for('rubrics.rubrics_list'))


@rubrics_bp.route('/rubrics/<int:rubric_id>/edit', methods=['GET', 'POST'])
@login_required
@check_access('assignment.grade')
def rubric_edit(rubric_id: int):
    rubric = RubricTemplate.query.get_or_404(rubric_id)
    if not _can_manage_all() and rubric.owner_user_id != current_user.id:
        abort(403)

    if request.method == 'GET':
        items_json = json.dumps((rubric.items or []), ensure_ascii=False)
        return render_template('rubric_form.html', rubric=rubric, items_json=items_json, is_new=False)

    title = (request.form.get('title') or '').strip()
    assignment_type = (request.form.get('assignment_type') or '').strip().lower() or None
    description = (request.form.get('description') or '').strip() or None
    items = _parse_items(request.form.get('items_json') or '[]')

    if not title:
        flash('Название рубрики обязательно.', 'danger')
        return render_template('rubric_form.html', rubric=rubric, items_json=json.dumps(items, ensure_ascii=False), is_new=False), 400

    if assignment_type and assignment_type not in {'homework', 'classwork', 'exam', 'test', 'diagnostic'}:
        assignment_type = None

    rubric.title = title
    rubric.assignment_type = assignment_type
    rubric.description = description
    rubric.items = items
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='rubric_update', entity='RubricTemplate', entity_id=rubric.rubric_id, error=str(e))
        flash('Не удалось обновить рубрику.', 'danger')
        return render_template('rubric_form.html', rubric=rubric, items_json=json.dumps(items, ensure_ascii=False), is_new=False), 500

    try:
        audit_logger.log(action='rubric_update', entity='RubricTemplate', entity_id=rubric.rubric_id, status='success', metadata={'items': len(items)})
    except Exception:
        pass

    flash('Рубрика обновлена.', 'success')
    return redirect(url_for('rubrics.rubrics_list'))


@rubrics_bp.route('/rubrics/<int:rubric_id>/delete', methods=['POST'])
@login_required
@check_access('assignment.grade')
def rubric_delete(rubric_id: int):
    rubric = RubricTemplate.query.get_or_404(rubric_id)
    if not _can_manage_all() and rubric.owner_user_id != current_user.id:
        abort(403)

    rubric.is_active = False
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='rubric_delete', entity='RubricTemplate', entity_id=rubric.rubric_id, error=str(e))
        flash('Не удалось удалить рубрику.', 'danger')
        return redirect(url_for('rubrics.rubrics_list'))

    try:
        audit_logger.log(action='rubric_delete', entity='RubricTemplate', entity_id=rubric.rubric_id, status='success')
    except Exception:
        pass

    flash('Рубрика удалена.', 'success')
    return redirect(url_for('rubrics.rubrics_list'))

