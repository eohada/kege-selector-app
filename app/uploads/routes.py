from __future__ import annotations

import os
import re
import logging

from flask import send_file, abort, current_app
from flask_login import login_required, current_user

from app.uploads import uploads_bp
from app.models import MaterialAsset, Lesson, Student, User, LessonMaterialLink
from app.auth.rbac_utils import check_access, get_user_scope

logger = logging.getLogger(__name__)

# V2 appends a timestamp to avoid browser and CDN cache collisions. Older uploads
# without it stay valid as well.
AVATAR_FILENAME_RE = re.compile(r'^avatar_\d+(?:_\d+)?\.(jpg|jpeg|png|gif|webp)$', re.IGNORECASE)
COVER_FILENAME_RE = re.compile(r'^cover_\d+(?:_\d+)?\.(jpg|jpeg|png|gif|webp)$', re.IGNORECASE)


def _lesson_material_root(lesson_id: int) -> str:
    configured_root = (current_app.config.get('LESSON_UPLOAD_ROOT') or '').strip()
    # docker-compose монтирует /app/uploads как persistent volume.
    base_root = configured_root or os.path.join(os.path.dirname(current_app.root_path), 'uploads', 'lessons')
    return os.path.join(base_root, str(int(lesson_id)))

def _resolve_uploaded_asset(base_name: str, roots: list[str], allowed_prefix: str) -> str | None:
    """
    Resolve uploaded asset path with a tolerant fallback:
    - exact basename match
    - same stem with any allowed extension
    - search across configured roots
    """
    stem, _ext = os.path.splitext(base_name)
    allowed_exts = ('.jpg', '.jpeg', '.png', '.gif', '.webp')

    for root in roots:
        if not root:
            continue
        root_abs = os.path.abspath(root)
        exact_path = os.path.join(root_abs, base_name)
        if os.path.isfile(exact_path):
            return exact_path
        for ext in allowed_exts:
            candidate = os.path.join(root_abs, stem + ext)
            if os.path.isfile(candidate):
                return candidate

    # Final fallback: look in legacy app static directories.
    legacy_roots = [
        os.path.join(os.path.dirname(current_app.root_path), 'static', 'uploads', allowed_prefix),
        os.path.join(current_app.root_path, 'static', 'uploads', allowed_prefix),
        os.path.join(current_app.root_path, 'uploads', allowed_prefix),
    ]
    for root in legacy_roots:
        root_abs = os.path.abspath(root)
        exact_path = os.path.join(root_abs, base_name)
        if os.path.isfile(exact_path):
            return exact_path
        for ext in allowed_exts:
            candidate = os.path.join(root_abs, stem + ext)
            if os.path.isfile(candidate):
                return candidate
    return None

def _resolve_accessible_student_ids(scope: dict) -> list[int]:
    if not scope or scope.get('can_see_all'):
        return []
    user_ids = scope.get('student_ids') or []
    if not user_ids:
        return []

    student_ids: list[int] = []
    try:
        by_user_id = Student.query.filter(Student.user_id.in_(user_ids)).all()
        student_ids.extend([s.student_id for s in by_user_id if s])
    except Exception as e:
        logger.warning(f"Failed to map scope user_ids->student_ids: {e}")
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


def _can_access_lesson(lesson: Lesson) -> bool:
    if not getattr(current_user, 'is_authenticated', False):
        return False

    try:
        if current_user.is_creator() or current_user.is_admin():
            return True
    except Exception:
        pass

    try:
        if current_user.is_student():
            if lesson.student and getattr(lesson.student, 'user_id', None) == current_user.id:
                return True
            if lesson.student_id == current_user.id:
                return True
            return False
    except Exception:
        pass

    scope = get_user_scope(current_user)
    if scope.get('can_see_all'):
        return True
    accessible = _resolve_accessible_student_ids(scope)
    return bool(accessible and lesson.student_id in accessible)


@uploads_bp.route('/files/library/<int:asset_id>')
@login_required
def library_file(asset_id: int):
    """Защищённая выдача файлов из библиотеки материалов."""
    asset = MaterialAsset.query.get_or_404(asset_id)

    # Владелец имеет доступ всегда
    if asset.owner_user_id == getattr(current_user, 'id', None):
        has_access = True
    else:
        # Проверяем, прикреплен ли ассет к уроку, к которому у пользователя есть доступ
        links = LessonMaterialLink.query.filter_by(asset_id=asset.asset_id).all()
        has_access = False
        for link in links:
            if link.lesson and _can_access_lesson(link.lesson):
                has_access = True
                break

    if not has_access:
        abort(403)

    if not asset.storage_path:
        abort(404)

    abs_path = os.path.join(current_app.root_path, asset.storage_path)
    if not os.path.exists(abs_path):
        abort(404)

    return send_file(abs_path, as_attachment=True, download_name=(asset.file_name or f'asset-{asset.asset_id}'))


@uploads_bp.route('/files/lessons/<int:lesson_id>/<path:stored_name>')
@login_required
def lesson_file(lesson_id: int, stored_name: str):
    """Защищённая выдача файлов урока (материалы)."""
    if not stored_name or stored_name != os.path.basename(stored_name):
        abort(400)

    lesson = Lesson.query.get_or_404(lesson_id)
    if not _can_access_lesson(lesson):
        abort(403)

    abs_path = os.path.join(_lesson_material_root(lesson_id), stored_name)
    if not os.path.exists(abs_path):
        legacy_path = os.path.join(current_app.root_path, 'static', 'uploads', 'lessons', str(lesson_id), stored_name)
        if os.path.exists(legacy_path):
            abs_path = legacy_path
    if not os.path.exists(abs_path):
        abort(404)

    return send_file(abs_path, as_attachment=True, download_name=stored_name)


@uploads_bp.route('/avatars/<path:filename>')
def avatar_file(filename: str):
    """
    Раздача аватарок. Без авторизации (аватарки публичны).
    Если задан AVATAR_UPLOAD_ROOT — файлы берутся оттуда (persistent volume при деплое).
    Иначе — из persistent volume uploads/avatars.
    """
    base_name = os.path.basename(filename)
    if not base_name or not AVATAR_FILENAME_RE.match(base_name):
        abort(404)
    roots = []
    root = current_app.config.get('AVATAR_UPLOAD_ROOT')
    if root:
        roots.append(root)
    roots.extend([
        os.path.join(os.path.dirname(current_app.root_path), 'uploads', 'avatars'),
        os.path.join(os.path.dirname(current_app.root_path), 'static', 'uploads', 'avatars'),
        os.path.join(current_app.root_path, 'static', 'uploads', 'avatars'),
        os.path.join(current_app.root_path, 'uploads', 'avatars'),
    ])
    abs_path = _resolve_uploaded_asset(base_name, roots, 'avatars')
    if not abs_path:
        app_root = os.path.dirname(current_app.root_path)
        fallback_candidates = [
            os.path.join(app_root, 'static', 'images', 'demo_user_avatar.png'),
            os.path.join(app_root, 'static', 'images', 'demo_creator_avatar_1.png'),
            os.path.join(app_root, 'static', 'images', 'demo_creator_avatar.jpg'),
            os.path.join(current_app.root_path, 'static', 'images', 'demo_user_avatar.png'),
            os.path.join(current_app.root_path, 'static', 'images', 'demo_creator_avatar_1.png'),
            os.path.join(current_app.root_path, 'static', 'images', 'demo_creator_avatar.jpg'),
        ]
        for fallback_path in fallback_candidates:
            if os.path.isfile(fallback_path):
                response = send_file(
                    fallback_path,
                    mimetype=None,
                    as_attachment=False,
                    download_name=os.path.basename(fallback_path),
                )
                response.headers['Cache-Control'] = 'no-store, max-age=0'
                return response
        abort(404)
    response = send_file(abs_path, mimetype=None, as_attachment=False, download_name=base_name)
    response.headers['Cache-Control'] = 'public, max-age=300'
    return response


@uploads_bp.route('/covers/<path:filename>')
def cover_file(filename: str):
    """
    Раздача баннеров/обложек профиля (креатор). Публично.
    Если задан COVER_UPLOAD_ROOT — файлы оттуда, иначе persistent volume uploads/covers.
    """
    base_name = os.path.basename(filename)
    if not base_name or not COVER_FILENAME_RE.match(base_name):
        abort(404)
    roots = []
    root = current_app.config.get('COVER_UPLOAD_ROOT')
    if root:
        roots.append(root)
    roots.extend([
        os.path.join(os.path.dirname(current_app.root_path), 'uploads', 'covers'),
        os.path.join(os.path.dirname(current_app.root_path), 'static', 'uploads', 'covers'),
        os.path.join(current_app.root_path, 'static', 'uploads', 'covers'),
        os.path.join(current_app.root_path, 'uploads', 'covers'),
    ])
    abs_path = _resolve_uploaded_asset(base_name, roots, 'covers')
    if not abs_path:
        abort(404)
    response = send_file(abs_path, mimetype=None, as_attachment=False, download_name=base_name)
    response.headers['Cache-Control'] = 'public, max-age=300'
    return response

@uploads_bp.route('/upload/cover', methods=['POST'])
@login_required
def upload_cover():
    from flask import request, jsonify
    from werkzeug.utils import secure_filename
    from app.extensions import db
    
    if 'cover_file' not in request.files:
        return jsonify({'success': False, 'error': 'Файл обложки не передан'}), 400
        
    file = request.files['cover_file']
    if not file or not file.filename:
        return jsonify({'success': False, 'error': 'Пустой файл'}), 400
        
    allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
    filename = secure_filename(file.filename)
    ext = os.path.splitext(filename)[1].lower()
    
    if ext not in allowed_extensions:
        return jsonify({'success': False, 'error': 'Недопустимый формат файла'}), 400
        
    unique_filename = f"cover_{current_user.id}{ext}"
    cover_upload_root = current_app.config.get('COVER_UPLOAD_ROOT')
    
    if cover_upload_root:
        upload_folder = os.path.abspath(cover_upload_root)
        cover_url = f"/covers/{unique_filename}"
    else:
        app_root = os.path.dirname(current_app.root_path)
        upload_folder = os.path.abspath(os.path.join(app_root, 'uploads', 'covers'))
        cover_url = f"/covers/{unique_filename}"
        
    os.makedirs(upload_folder, exist_ok=True)
    if not os.path.isdir(upload_folder):
        logger.error(f"Failed to create upload folder: {upload_folder}")
        return jsonify({'success': False, 'error': 'Не удалось сохранить файл'}), 500
        
    file_path = os.path.join(upload_folder, unique_filename)
    file.save(file_path)
    
    try:
        current_user.cover_url = cover_url
        if getattr(current_user, 'profile', None):
            current_user.profile.cover_url = cover_url
        db.session.commit()
        return jsonify({'success': True, 'cover_url': cover_url})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error saving cover: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Ошибка при сохранении в базу данных'}), 500
