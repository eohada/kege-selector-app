from __future__ import annotations

import os
import time
import logging
from typing import Any

from werkzeug.utils import secure_filename
from flask import (
    render_template, request, jsonify, current_app, url_for, flash, redirect
)
from flask_login import login_required, current_user
from sqlalchemy import func

from app.library import library_bp
from app.auth.rbac_utils import check_access, get_user_scope
from app.models import db, User, Student, Lesson, MaterialAsset, LessonMaterialLink, LessonRoomTemplate, moscow_now
from sqlalchemy.orm.attributes import flag_modified

logger = logging.getLogger(__name__)


def _require_teacher():
    if current_user.is_student() or current_user.is_parent():
        return False
    return True


def _resolve_accessible_student_ids(scope: dict) -> list[int]:
    if not scope or scope.get('can_see_all'):
        return []
    user_ids = scope.get('student_ids') or []
    if not user_ids:
        return []

    student_ids: list[int] = []
    try:
        student_users = User.query.filter(User.id.in_(user_ids)).all()
        emails = [u.email for u in student_users if u and u.email]
        if emails:
            students_by_email = Student.query.filter(Student.email.in_(emails)).all()
            student_ids.extend([s.student_id for s in students_by_email if s])
    except Exception as e:
        logger.warning(f"Failed to map scope user_ids->student_ids via email: {e}")

    try:
        students_by_id = Student.query.filter(Student.student_id.in_(user_ids)).all()
        student_ids.extend([s.student_id for s in students_by_id if s])
    except Exception as e:
        logger.warning(f"Failed to map scope user_ids->student_ids via id fallback: {e}")

    seen = set()
    out: list[int] = []
    for sid in student_ids:
        if sid not in seen:
            seen.add(sid)
            out.append(sid)
    return out


def _assert_can_access_lesson(lesson: Lesson) -> bool:
    scope = get_user_scope(current_user)
    if scope.get('can_see_all'):
        return True
    accessible = _resolve_accessible_student_ids(scope)
    return bool(accessible and lesson.student_id in accessible)


def _normalize_tags(raw: str) -> list[str]:
    if not raw:
        return []
    parts = [p.strip().lower() for p in raw.replace(';', ',').split(',')]
    tags = []
    seen = set()
    for p in parts:
        if not p:
            continue
        if len(p) > 30:
            p = p[:30]
        if p not in seen:
            seen.add(p)
            tags.append(p)
    return tags[:20]


@library_bp.route('/library/materials')
@login_required
@check_access('lesson.edit')
def materials_library():
    if not _require_teacher():
        return "Forbidden", 403

    q = (request.args.get('q') or '').strip()
    tag = (request.args.get('tag') or '').strip().lower()

    base = MaterialAsset.query.filter(MaterialAsset.is_active.is_(True))
    # приватная библиотека (foundation): только свои
    base = base.filter(MaterialAsset.owner_user_id == current_user.id)

    if q:
        like = f"%{q.lower()}%"
        base = base.filter(func.lower(MaterialAsset.title).like(like))
    if tag:
        # JSON search portable: фильтруем на python после лимита
        pass

    assets = base.order_by(MaterialAsset.updated_at.desc(), MaterialAsset.created_at.desc()).limit(200).all()
    if tag:
        assets = [a for a in assets if isinstance(a.tags, list) and tag in [str(t).lower() for t in a.tags]]

    return render_template('library_materials.html', assets=assets, q=q, tag=tag)


@library_bp.route('/library/materials/api')
@login_required
@check_access('lesson.edit')
def materials_api_list():
    if not _require_teacher():
        return jsonify({'success': False, 'error': 'Forbidden'}), 403

    q = (request.args.get('q') or '').strip()
    base = MaterialAsset.query.filter(MaterialAsset.is_active.is_(True), MaterialAsset.owner_user_id == current_user.id)
    if q:
        like = f"%{q.lower()}%"
        base = base.filter(func.lower(MaterialAsset.title).like(like))

    assets = base.order_by(MaterialAsset.updated_at.desc()).limit(50).all()
    out = []
    for a in assets:
        out.append({
            'asset_id': a.asset_id,
            'title': a.title,
            'file_name': a.file_name,
            'file_url': a.file_url,
            'file_mime': a.file_mime,
            'tags': a.tags or [],
        })
    return jsonify({'success': True, 'assets': out})


@library_bp.route('/library/materials/upload', methods=['POST'])
@login_required
@check_access('lesson.edit')
def materials_upload():
    if not _require_teacher():
        return "Forbidden", 403

    file = request.files.get('file')
    if not file or not file.filename:
        flash('Файл не выбран.', 'danger')
        return redirect(url_for('library.materials_library'))

    title = (request.form.get('title') or '').strip()
    description = (request.form.get('description') or '').strip() or None
    tags = _normalize_tags((request.form.get('tags') or '').strip())

    orig = secure_filename(file.filename)
    if not orig:
        flash('Некорректное имя файла.', 'danger')
        return redirect(url_for('library.materials_library'))

    # Хранилище: static/uploads/library/<user_id>/
    folder = os.path.join(current_app.root_path, 'static', 'uploads', 'library', str(current_user.id))
    os.makedirs(folder, exist_ok=True)

    ts = int(time.time())
    stored_name = f"{ts}_{orig}"
    path = os.path.join(folder, stored_name)
    file.save(path)

    file_url = url_for('static', filename=f"uploads/library/{current_user.id}/{stored_name}")
    mime = getattr(file, 'mimetype', None)
    size = None
    try:
        size = os.path.getsize(path)
    except Exception:
        size = None

    asset = MaterialAsset(
        owner_user_id=current_user.id,
        title=title or orig,
        description=description,
        tags=tags,
        file_name=orig,
        file_url=file_url,
        file_mime=mime,
        file_size=size,
        visibility='private',
        is_active=True
    )
    db.session.add(asset)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to upload material asset: {e}", exc_info=True)
        flash('Ошибка при сохранении материала.', 'danger')
        return redirect(url_for('library.materials_library'))

    flash('Материал добавлен в библиотеку.', 'success')
    return redirect(url_for('library.materials_library'))


@library_bp.route('/library/materials/<int:asset_id>/delete', methods=['POST'])
@login_required
@check_access('lesson.edit')
def materials_delete(asset_id: int):
    if not _require_teacher():
        return "Forbidden", 403
    asset = MaterialAsset.query.get_or_404(asset_id)
    if asset.owner_user_id != current_user.id:
        return "Forbidden", 403
    asset.is_active = False
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to delete material asset: {e}", exc_info=True)
        flash('Ошибка удаления.', 'danger')
        return redirect(url_for('library.materials_library'))
    flash('Материал удалён из библиотеки.', 'success')
    return redirect(url_for('library.materials_library'))


@library_bp.route('/library/materials/<int:asset_id>/attach', methods=['POST'])
@login_required
@check_access('lesson.edit')
def materials_attach(asset_id: int):
    if not _require_teacher():
        return jsonify({'success': False, 'error': 'Forbidden'}), 403

    data: dict[str, Any] = request.get_json(silent=True) or {}
    lesson_id = data.get('lesson_id')
    try:
        lesson_id = int(lesson_id)
    except Exception:
        return jsonify({'success': False, 'error': 'lesson_id required'}), 400

    lesson = Lesson.query.get_or_404(lesson_id)
    if not _assert_can_access_lesson(lesson):
        return jsonify({'success': False, 'error': 'Forbidden'}), 403

    asset = MaterialAsset.query.get_or_404(asset_id)
    if asset.owner_user_id != current_user.id:
        return jsonify({'success': False, 'error': 'Forbidden'}), 403

    link = LessonMaterialLink.query.filter_by(lesson_id=lesson.lesson_id, asset_id=asset.asset_id).first()
    if link:
        return jsonify({'success': True, 'link_id': link.link_id, 'material': {
            'name': asset.title,
            'url': asset.file_url,
            'type': (asset.file_name.split('.')[-1].lower() if '.' in asset.file_name else 'file'),
            'source': 'library'
        }})

    link = LessonMaterialLink(
        lesson_id=lesson.lesson_id,
        asset_id=asset.asset_id,
        created_by_user_id=current_user.id,
        order_index=0
    )
    db.session.add(link)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to attach material: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Ошибка сохранения'}), 500

    return jsonify({'success': True, 'link_id': link.link_id, 'material': {
        'name': asset.title,
        'url': asset.file_url,
        'type': (asset.file_name.split('.')[-1].lower() if '.' in asset.file_name else 'file'),
        'source': 'library'
    }})


@library_bp.route('/library/materials/detach', methods=['POST'])
@login_required
@check_access('lesson.edit')
def materials_detach():
    if not _require_teacher():
        return jsonify({'success': False, 'error': 'Forbidden'}), 403

    data: dict[str, Any] = request.get_json(silent=True) or {}
    link_id = data.get('link_id')
    try:
        link_id = int(link_id)
    except Exception:
        return jsonify({'success': False, 'error': 'link_id required'}), 400

    link = LessonMaterialLink.query.get_or_404(link_id)
    lesson = Lesson.query.get_or_404(link.lesson_id)
    if not _assert_can_access_lesson(lesson):
        return jsonify({'success': False, 'error': 'Forbidden'}), 403

    try:
        db.session.delete(link)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to detach material: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Ошибка удаления'}), 500

    return jsonify({'success': True})


@library_bp.route('/library/lesson-templates')
@login_required
@check_access('lesson.edit')
def lesson_templates():
    if not _require_teacher():
        return "Forbidden", 403

    q = (request.args.get('q') or '').strip()
    lesson_id = request.args.get('lesson_id', type=int)

    base = LessonRoomTemplate.query.filter(LessonRoomTemplate.is_active.is_(True))
    base = base.filter(LessonRoomTemplate.created_by_user_id == current_user.id)
    if q:
        like = f"%{q.lower()}%"
        base = base.filter(func.lower(LessonRoomTemplate.title).like(like))
    templates = base.order_by(LessonRoomTemplate.updated_at.desc(), LessonRoomTemplate.created_at.desc()).limit(200).all()

    lesson = None
    if lesson_id:
        try:
            lesson = Lesson.query.get(lesson_id)
            if lesson and not _assert_can_access_lesson(lesson):
                lesson = None
        except Exception:
            lesson = None

    return render_template('library_lesson_templates.html', templates=templates, q=q, lesson=lesson)


@library_bp.route('/library/lesson-templates/from-lesson', methods=['POST'])
@login_required
@check_access('lesson.edit')
def lesson_template_create_from_lesson():
    if not _require_teacher():
        return jsonify({'success': False, 'error': 'Forbidden'}), 403

    data: dict[str, Any] = request.get_json(silent=True) or {}
    lesson_id = data.get('lesson_id')
    title = (data.get('title') or '').strip()
    description = (data.get('description') or '').strip() or None
    visibility = (data.get('visibility') or 'private').strip().lower()
    if visibility not in {'private', 'shared'}:
        visibility = 'private'

    try:
        lesson_id = int(lesson_id)
    except Exception:
        return jsonify({'success': False, 'error': 'lesson_id required'}), 400

    lesson = Lesson.query.get_or_404(lesson_id)
    if not _assert_can_access_lesson(lesson):
        return jsonify({'success': False, 'error': 'Forbidden'}), 403

    if not title:
        title = lesson.topic or f"Урок #{lesson.lesson_id}"

    # asset ids attached to this lesson
    asset_ids: list[int] = []
    try:
        links = LessonMaterialLink.query.filter_by(lesson_id=lesson.lesson_id).all()
        asset_ids = [l.asset_id for l in links if l and l.asset_id]
    except Exception:
        asset_ids = []

    payload = {
        'content': lesson.content or '',
        'content_blocks': lesson.content_blocks or [],
        'materials': lesson.materials or [],
        'asset_ids': asset_ids,
        'created_from_lesson_id': lesson.lesson_id
    }
    if isinstance(payload['materials'], str):
        try:
            import json as _json
            payload['materials'] = _json.loads(payload['materials'])
        except Exception:
            payload['materials'] = []

    tpl = LessonRoomTemplate(
        created_by_user_id=current_user.id,
        title=title,
        description=description,
        payload=payload,
        visibility=visibility,
        is_active=True
    )
    db.session.add(tpl)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to create lesson template: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Ошибка сохранения'}), 500

    return jsonify({'success': True, 'template_id': tpl.template_id})


@library_bp.route('/library/lesson-templates/<int:template_id>/apply', methods=['POST'])
@login_required
@check_access('lesson.edit')
def lesson_template_apply(template_id: int):
    if not _require_teacher():
        return jsonify({'success': False, 'error': 'Forbidden'}), 403

    data: dict[str, Any] = request.get_json(silent=True) or {}
    lesson_id = data.get('lesson_id')
    replace_materials = bool(data.get('replace_materials', True))
    try:
        lesson_id = int(lesson_id)
    except Exception:
        return jsonify({'success': False, 'error': 'lesson_id required'}), 400

    tpl = LessonRoomTemplate.query.get_or_404(template_id)
    if tpl.created_by_user_id != current_user.id and tpl.visibility != 'shared':
        return jsonify({'success': False, 'error': 'Forbidden'}), 403

    lesson = Lesson.query.get_or_404(lesson_id)
    if not _assert_can_access_lesson(lesson):
        return jsonify({'success': False, 'error': 'Forbidden'}), 403

    payload = tpl.payload or {}
    if not isinstance(payload, dict):
        return jsonify({'success': False, 'error': 'Некорректный шаблон'}), 400

    lesson.content = (payload.get('content') or '')
    lesson.content_blocks = payload.get('content_blocks') or []
    flag_modified(lesson, "content_blocks")

    if replace_materials:
        mats = payload.get('materials') or []
        lesson.materials = mats
        flag_modified(lesson, "materials")

    # replace library links
    asset_ids = payload.get('asset_ids') or []
    if not isinstance(asset_ids, list):
        asset_ids = []

    try:
        LessonMaterialLink.query.filter_by(lesson_id=lesson.lesson_id).delete()
        for aid in asset_ids:
            try:
                aid = int(aid)
            except Exception:
                continue
            asset = MaterialAsset.query.filter_by(asset_id=aid, is_active=True).first()
            if not asset:
                continue
            # приватная библиотека: разрешаем только свои ассеты
            if asset.owner_user_id != current_user.id:
                continue
            db.session.add(LessonMaterialLink(lesson_id=lesson.lesson_id, asset_id=aid, created_by_user_id=current_user.id, order_index=0))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to apply lesson template: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Ошибка применения'}), 500

    return jsonify({'success': True})

