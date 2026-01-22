from __future__ import annotations

import os
import logging

from flask import send_file, abort, current_app
from flask_login import login_required, current_user

from app.uploads import uploads_bp
from app.models import MaterialAsset, Lesson, Student, User
from app.auth.rbac_utils import check_access, get_user_scope

logger = logging.getLogger(__name__)

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


def _can_access_lesson(lesson: Lesson) -> bool:
    if not getattr(current_user, 'is_authenticated', False):
        return False

    try:
        if current_user.is_creator() or current_user.is_admin():
            return True
    except Exception:
        pass

    # student: only own
    try:
        if current_user.is_student():
            me_email = (current_user.email or '').strip().lower()
            st_email = ''
            try:
                st_email = (lesson.student.email or '').strip().lower() if (lesson.student and lesson.student.email) else ''
            except Exception:
                st_email = ''
            if me_email and st_email and st_email == me_email:
                return True
            # Fallback допустим только если у Student нет email (иначе возможны коллизии User.id vs Student.student_id)
            if (not st_email) and lesson.student_id == current_user.id:
                return True
            return False
    except Exception:
        pass

    # parent/tutor/etc: via data-scope
    scope = get_user_scope(current_user)
    if scope.get('can_see_all'):
        return True
    accessible = _resolve_accessible_student_ids(scope)
    return bool(accessible and lesson.student_id in accessible)


@uploads_bp.route('/files/library/<int:asset_id>')
@login_required
@check_access('lesson.edit')
def library_file(asset_id: int):
    """Защищённая выдача файлов из библиотеки материалов."""
    asset = MaterialAsset.query.get_or_404(asset_id)

    # MVP: приватная библиотека — только владелец
    if asset.owner_user_id != getattr(current_user, 'id', None):
        abort(403)

    if not asset.storage_path:
        # fallback: если старый asset без storage_path — даём public URL
        abort(404)

    abs_path = os.path.join(current_app.root_path, asset.storage_path)
    if not os.path.exists(abs_path):
        abort(404)

    return send_file(abs_path, as_attachment=True, download_name=(asset.file_name or f'asset-{asset.asset_id}'))


@uploads_bp.route('/files/lessons/<int:lesson_id>/<path:stored_name>')
@login_required
def lesson_file(lesson_id: int, stored_name: str):
    """Защищённая выдача файлов урока (материалы)."""
    # защита от path traversal
    if not stored_name or stored_name != os.path.basename(stored_name):
        abort(400)

    lesson = Lesson.query.get_or_404(lesson_id)
    if not _can_access_lesson(lesson):
        abort(403)

    abs_path = os.path.join(current_app.root_path, 'static', 'uploads', 'lessons', str(lesson_id), stored_name)
    if not os.path.exists(abs_path):
        abort(404)

    return send_file(abs_path, as_attachment=True, download_name=stored_name)

