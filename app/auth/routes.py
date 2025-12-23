"""
Маршруты аутентификации
"""
import os
from werkzeug.utils import secure_filename
from flask import render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired

from app.auth import auth_bp
from app.models import db, User, moscow_now
from core.audit_logger import audit_logger

class LoginForm(FlaskForm):
    """Форма входа для пользователей"""
    username = StringField('Логин', validators=[DataRequired()])
    password = PasswordField('Пароль', validators=[DataRequired()])
    submit = SubmitField('Войти')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Страница входа для тестеров"""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        password = form.password.data
        
        # Ищем пользователя по логину
        user = User.query.filter_by(username=username).first()
        
        if user and user.is_active:
            # Проверяем пароль
            if check_password_hash(user.password_hash, password):
                # Обновляем время последнего входа
                user.last_login = moscow_now()
                try:
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    raise
                
                # Входим
                login_user(user, remember=True)
                
                # Логируем вход
                audit_logger.log(
                    action='login',
                    entity='User',
                    entity_id=user.id,
                    status='success',
                    metadata={'username': user.username, 'role': user.role}
                )
                
                next_page = request.args.get('next')
                if not next_page or not next_page.startswith('/'):
                    next_page = url_for('main.dashboard')
                flash('Вход выполнен успешно!', 'success')
                return redirect(next_page)
            else:
                flash('Неверный логин или пароль.', 'danger')
                audit_logger.log(
                    action='login_failed',
                    entity='User',
                    status='error',
                    metadata={'username': username, 'reason': 'invalid_password'}
                )
        else:
            flash('Неверный логин или пароль.', 'danger')
            audit_logger.log(
                action='login_failed',
                entity='User',
                status='error',
                metadata={'username': username, 'reason': 'user_not_found_or_inactive'}
            )
    
    return render_template('login.html', form=form)

@auth_bp.route('/logout', methods=['GET', 'POST'])
@login_required
def logout():
    """Выход из системы"""
    username = current_user.username
    logout_user()
    flash('Вы вышли из системы.', 'info')
    
    audit_logger.log(
        action='logout',
        entity='User',
        status='success',
        metadata={'username': username}
    )
    
    return redirect(url_for('auth.login'))

@auth_bp.route('/user/profile')
@login_required
def user_profile():
    """Страница профиля пользователя"""
    return render_template('user_profile.html')

@auth_bp.route('/user/profile/update', methods=['POST'])
@login_required
def profile_update():
    """Обновление данных профиля (AJAX)"""
    # Поддерживаем и JSON, и FormData
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form

    try:
        # Обработка аватарки (только если пришел файл)
        if 'avatar_file' in request.files:
            file = request.files['avatar_file']
            if file and file.filename:
                filename = secure_filename(file.filename)
                # Генерируем уникальное имя: avatar_USERID.ext
                ext = os.path.splitext(filename)[1]
                unique_filename = f"avatar_{current_user.id}{ext}"
                
                # Путь: app/static/uploads/avatars
                # current_app.root_path указывает на папку app/
                upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'avatars')
                os.makedirs(upload_folder, exist_ok=True)
                
                file_path = os.path.join(upload_folder, unique_filename)
                file.save(file_path)
                
                # Сохраняем URL (важно использовать прямые слеши для URL)
                current_user.avatar_url = f"/static/uploads/avatars/{unique_filename}"

        # Обновляем текстовые поля
        if 'custom_status' in data:
            current_user.custom_status = data['custom_status'].strip()[:100]
        
        if 'about_me' in data:
            current_user.about_me = data['about_me'].strip()
            
        if 'telegram_link' in data:
            current_user.telegram_link = data['telegram_link'].strip()[:200]
            
        db.session.commit()
        
        audit_logger.log(
            action='profile_updated',
            entity='User',
            entity_id=current_user.id,
            status='success',
            metadata={'updated_fields': list(data.keys())}
        )
        
        return jsonify({'success': True})
        
    except Exception as e:
        db.session.rollback()
        audit_logger.log(
            action='profile_update_failed',
            entity='User',
            entity_id=current_user.id,
            status='error',
            metadata={'error': str(e)}
        )
        return jsonify({'success': False, 'error': 'Ошибка сохранения'}), 500

