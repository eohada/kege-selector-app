"""
Маршруты аутентификации
"""
import os
import logging
from werkzeug.utils import secure_filename
from flask import render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_user, logout_user, login_required, current_user
from flask_wtf.csrf import validate_csrf, CSRFError

logger = logging.getLogger(__name__)
from werkzeug.security import check_password_hash
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired

from app.auth import auth_bp
from app.models import db, User, moscow_now, Student
from core.audit_logger import audit_logger

class LoginForm(FlaskForm):
    """Форма входа для пользователей"""
    username = StringField('Логин', validators=[DataRequired()])
    password = PasswordField('Пароль', validators=[DataRequired()])
    submit = SubmitField('Войти')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Страница входа"""
    try:
        # Если это админ-окружение и пользователь уже авторизован - сразу в админку
        is_admin_env = os.environ.get('ENVIRONMENT') == 'admin'
        
        # Безопасная проверка авторизации
        try:
            is_authenticated = current_user.is_authenticated if hasattr(current_user, 'is_authenticated') else False
        except Exception as e:
            logger.warning(f"Error checking authentication: {e}")
            is_authenticated = False
        
        if is_authenticated:
            if is_admin_env:
                return redirect(url_for('remote_admin.dashboard'))
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
                # Проверка для админ-окружения: только creator
                try:
                    is_creator = user.is_creator() if hasattr(user, 'is_creator') else False
                except Exception as e:
                    logger.error(f"Error checking is_creator: {e}", exc_info=True)
                    is_creator = False
                
                if is_admin_env and not is_creator:
                    flash('Доступ к админ-панели разрешен только Создателю', 'danger')
                    return render_template('remote_admin/login.html' if is_admin_env else 'auth/login.html', form=form)
                
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
                
                # Редирект в зависимости от роли
                next_page = request.args.get('next')
                if next_page and next_page.startswith('/'):
                    # Если есть next параметр, используем его
                    pass
                elif is_admin_env:
                    next_page = url_for('remote_admin.dashboard')
                elif user.is_parent():
                    # Родитель идет на свой дашборд
                    next_page = url_for('parents.parent_dashboard')
                elif user.is_student():
                    # Ученик идет на свой профиль
                    student = None
                    if user.email:
                        student = Student.query.filter_by(email=user.email).first()
                    if student:
                        next_page = url_for('students.student_profile', student_id=student.student_id)
                    else:
                        next_page = url_for('main.dashboard')
                elif user.is_admin():
                    # Админ может выбрать dashboard или админку
                    next_page = url_for('main.dashboard')
                else:
                    # Тьютор и остальные - на dashboard
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
    
        if is_admin_env:
            return render_template('remote_admin/login.html', form=form)
        
        return render_template('auth/login.html', form=form)
    except Exception as e:
        logger.error(f"Error in login route: {e}", exc_info=True)
        flash('Произошла ошибка при обработке запроса. Попробуйте позже.', 'danger')
        is_admin_env = os.environ.get('ENVIRONMENT') == 'admin'
        form = LoginForm()
        return render_template('remote_admin/login.html' if is_admin_env else 'auth/login.html', form=form), 500

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
    from werkzeug.exceptions import RequestEntityTooLarge
    
    # Проверка CSRF токена
    try:
        validate_csrf(request.form.get('csrf_token') or request.headers.get('X-CSRFToken'))
    except CSRFError as e:
        logger.warning(f"CSRF validation failed: {e}")
        return jsonify({'success': False, 'error': 'Ошибка безопасности. Обновите страницу.'}), 403
    
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
                # Проверка типа файла
                allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
                filename = secure_filename(file.filename)
                ext = os.path.splitext(filename)[1].lower()
                
                if ext not in allowed_extensions:
                    return jsonify({'success': False, 'error': 'Недопустимый формат файла. Используйте JPG, PNG, GIF или WEBP'}), 400
                
                # Проверка размера (макс 5MB)
                file.seek(0, os.SEEK_END)
                file_size = file.tell()
                file.seek(0)
                if file_size > 5 * 1024 * 1024:
                    return jsonify({'success': False, 'error': 'Файл слишком большой. Максимум 5MB'}), 400
                
                # Генерируем уникальное имя: avatar_USERID.ext
                unique_filename = f"avatar_{current_user.id}{ext}"
                
                # Путь: static/uploads/avatars (на уровне app/)
                # current_app.root_path указывает на папку app/
                # static находится на том же уровне, что и app
                app_root = os.path.dirname(current_app.root_path)
                upload_folder = os.path.join(app_root, 'static', 'uploads', 'avatars')
                upload_folder = os.path.abspath(upload_folder)
                
                logger.info(f"Upload folder path: {upload_folder}")
                os.makedirs(upload_folder, exist_ok=True)
                
                if not os.path.exists(upload_folder):
                    logger.error(f"Failed to create upload folder: {upload_folder}")
                    return jsonify({'success': False, 'error': 'Не удалось создать папку для загрузки'}), 500
                
                file_path = os.path.join(upload_folder, unique_filename)
                logger.info(f"Saving file to: {file_path}")
                file.save(file_path)
                
                if not os.path.exists(file_path):
                    logger.error(f"File was not saved: {file_path}")
                    return jsonify({'success': False, 'error': 'Не удалось сохранить файл'}), 500
                
                # Сохраняем URL (важно использовать прямые слеши для URL)
                avatar_url = f"/static/uploads/avatars/{unique_filename}"
                current_user.avatar_url = avatar_url
                
                logger.info(f"Avatar uploaded for user {current_user.id}: {avatar_url}")

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
        
        return jsonify({'success': True, 'avatar_url': current_user.avatar_url})
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating profile: {e}", exc_info=True)
        audit_logger.log(
            action='profile_update_failed',
            entity='User',
            entity_id=current_user.id,
            status='error',
            metadata={'error': str(e)}
        )
        return jsonify({'success': False, 'error': f'Ошибка сохранения: {str(e)}'}), 500

