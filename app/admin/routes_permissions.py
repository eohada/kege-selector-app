from flask import render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy.exc import ProgrammingError, OperationalError
from app import db
from app.models import RolePermission
from app.admin import admin_bp
from app.admin.routes import _remote_admin_redirect
from app.auth.permissions import ALL_PERMISSIONS, PERMISSION_CATEGORIES, DEFAULT_ROLE_PERMISSIONS
from app.utils.db_migrations import check_and_fix_rbac_schema
import logging

logger = logging.getLogger(__name__)

@admin_bp.route('/admin/permissions', methods=['GET', 'POST'])
@login_required
def admin_permissions():
    """Управление правами ролей (Рубильники)"""
    if not current_user.is_creator():
        flash('Доступ только для Создателя', 'danger')
        return _remote_admin_redirect()
        
    roles = ['creator', 'chief_admin', 'admin', 'chief_tester', 'content_maker', 'tutor', 'designer', 'tester', 'student', 'parent']
    
    try:
        from flask import current_app
        check_and_fix_rbac_schema(current_app)
    except Exception as e:
        logger.error(f"Critical error during RBAC schema check: {e}")
    
    if request.method == 'POST':
        try:
            changes_count = 0
            
            for role in roles:
                for perm_key in ALL_PERMISSIONS.keys():
                    is_enabled = request.form.get(f"{role}_{perm_key}") == 'on'
                    
                    perm_record = RolePermission.query.filter_by(role=role, permission_name=perm_key).first()
                    if not perm_record:
                        perm_record = RolePermission(role=role, permission_name=perm_key)
                        db.session.add(perm_record)
                        if is_enabled: 
                            perm_record.is_enabled = True
                            changes_count += 1
                        else:
                            perm_record.is_enabled = False
                    else:
                        if perm_record.is_enabled != is_enabled:
                            perm_record.is_enabled = is_enabled
                            changes_count += 1
            
            db.session.commit()
            flash(f'Права доступа обновлены ({changes_count} изменений)', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка: {e}', 'error')
            logger.error(f"Error saving permissions: {e}", exc_info=True)
            
    role_permissions = {}
    try:
        current_perms = RolePermission.query.all()
    except Exception as e:
        logger.error(f"Error loading permissions: {e}")
        current_perms = []
        flash("Не удалось загрузить текущие права. Попробуйте обновить страницу.", "error")
    
    for role in roles:
        role_permissions[role] = {}
        for perm in current_perms:
            if perm.role == role:
                role_permissions[role][perm.permission_name] = perm.is_enabled
        
        defaults = DEFAULT_ROLE_PERMISSIONS.get(role, [])
        for perm_key in ALL_PERMISSIONS.keys():
            if perm_key not in role_permissions[role]:
                role_permissions[role][perm_key] = perm_key in defaults

    return render_template('admin_permissions.html', 
                         permissions=ALL_PERMISSIONS, 
                         categories=PERMISSION_CATEGORIES,
                         roles=roles,
                         role_permissions=role_permissions)
