@admin_bp.route('/admin/permissions', methods=['GET', 'POST'])
@login_required
def admin_permissions():
    """Управление правами ролей (Рубильники)"""
    # Только для Создателя (или супер-админа)
    if not current_user.is_creator():
        flash('Доступ только для Создателя', 'danger')
        return redirect(url_for('admin.admin_panel'))
        
    roles = ['admin', 'chief_tester', 'tutor', 'designer', 'tester', 'student', 'parent']
    
    if request.method == 'POST':
        try:
            # Очищаем старые права (или обновляем)
            # Для простоты: проходим по всем возможным правам из формы
            changes_count = 0
            for role in roles:
                for perm_key in ALL_PERMISSIONS.keys():
                    is_enabled = request.form.get(f"{role}_{perm_key}") == 'on'
                    
                    # Ищем существующую запись или создаем новую
                    perm_record = RolePermission.query.filter_by(role=role, permission_name=perm_key).first()
                    if not perm_record:
                        perm_record = RolePermission(role=role, permission_name=perm_key)
                        db.session.add(perm_record)
                        if is_enabled: changes_count += 1
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
            
    # Загружаем текущие настройки
    role_permissions = {}
    current_perms = RolePermission.query.all()
    
    # Заполняем структуру: role -> permission -> enabled
    for role in roles:
        role_permissions[role] = {}
        # Сначала заполняем из БД
        for perm in current_perms:
            if perm.role == role:
                role_permissions[role][perm.permission_name] = perm.is_enabled
        
        # Если в БД нет записи, берем дефолтное значение (для отображения)
        # Но сохраняться будет то, что в форме
        from app.auth.permissions import DEFAULT_ROLE_PERMISSIONS
        defaults = DEFAULT_ROLE_PERMISSIONS.get(role, [])
        for perm_key in ALL_PERMISSIONS.keys():
            if perm_key not in role_permissions[role]:
                role_permissions[role][perm_key] = perm_key in defaults

    return render_template('admin_permissions.html', 
                         permissions=ALL_PERMISSIONS, 
                         categories=PERMISSION_CATEGORIES,
                         roles=roles,
                         role_permissions=role_permissions)
