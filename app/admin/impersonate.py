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

@admin_impersonate_bp.route('/stop', methods=['GET', 'POST'])
@login_required
def stop_impersonating():
    impersonator_id = session.pop('impersonator_id', None)
    if impersonator_id:
        original_user = User.query.get(impersonator_id)
        if original_user:
            login_user(original_user)
            flash('Вы вернулись в свой профиль', 'success')
    
    return redirect(request.referrer or url_for('main.index'))
