from flask import Blueprint, session, redirect, url_for, request, flash
from flask_login import login_required, current_user, login_user
from core.db_models import User, db
from app.auth.rbac_utils import require_role

admin_impersonate_bp = Blueprint('admin_impersonate', __name__, url_prefix='/admin/impersonate')

@admin_impersonate_bp.route('/start', methods=['POST'])
@login_required
@require_role('admin', 'creator', 'chief_admin', 'chief_tester', 'tester')
def start_impersonating():
    target_username = request.form.get('username')
    target_user = User.query.filter_by(username=target_username).first()
    
    if not target_user:
        flash('Пользователь не найден.', 'error')
        return redirect(request.referrer or url_for('main.index'))

    # Защита от "Матрицы" (симуляции внутри симуляции)
    if 'impersonator_id' not in session:
        session['impersonator_id'] = current_user.id

    login_user(target_user)
    flash(f'Вы вошли под аккаунтом: {target_user.username}', 'success')
    return redirect(request.referrer or url_for('main.index'))

@admin_impersonate_bp.route('/<target_identifier>', methods=['GET', 'POST'])
@admin_impersonate_bp.route('/<int:user_id>', methods=['GET', 'POST'])
@login_required
@require_role('admin', 'creator', 'chief_admin', 'chief_tester', 'tester')
def impersonate_user(target_identifier=None, user_id=None):
    """Имперсонация конкретного пользователя по ID или имени пользователя"""
    target = target_identifier or user_id
    target_user = None
    if isinstance(target, int) or (isinstance(target, str) and target.isdigit()):
        uid = int(target)
        target_user = db.session.get(User, uid) or User.query.get(uid)
    
    if not target_user and isinstance(target, str):
        target_user = User.query.filter_by(username=target).first()

    if not target_user:
        flash(f'Пользователь {target} не найден.', 'danger')
        return redirect(request.referrer or url_for('admin.admin_testers_page'))

    if 'impersonator_id' not in session:
        session['impersonator_id'] = current_user.id

    login_user(target_user)
    flash(f'🎭 Вход под аккаунтом: {target_user.username} ({target_user.role})', 'success')

    if target_user.role in ('tester', 'chief_tester'):
        return redirect('/tester')
    elif target_user.role == 'student':
        # A student has no standalone `/student` page.  The V2 dashboard
        # resolves the active role and is the single safe entry point for an
        # impersonated student as well.
        return redirect(url_for('main.dashboard'))
    elif target_user.role == 'teacher':
        return redirect('/dashboard')
    elif target_user.role == 'parent':
        return redirect('/parent')
    else:
        return redirect('/admin/qa')


@admin_impersonate_bp.route('/stop', methods=['GET', 'POST'])
@admin_impersonate_bp.route('/exit', methods=['GET', 'POST'])
@login_required
def stop_impersonating():
    impersonator_id = session.pop('impersonator_id', None)
    if impersonator_id:
        original_user = db.session.get(User, impersonator_id) or User.query.get(impersonator_id)
        if original_user:
            login_user(original_user)
            flash('Вы вернулись в свой профиль', 'success')
            return redirect('/admin/qa')
    
    return redirect(request.referrer or url_for('main.index'))
