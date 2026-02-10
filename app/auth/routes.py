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
from app.models import db, User, UserProfile, moscow_now, Student
from app.utils.subscription_access import get_effective_access_for_user
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
        is_admin_env = os.environ.get('ENVIRONMENT') == 'admin'
        
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
            
            user = User.query.filter_by(username=username).first()
            
            if user and user.is_active:
                if check_password_hash(user.password_hash, password):
                    try:
                        is_creator = user.is_creator() if hasattr(user, 'is_creator') else False
                    except Exception as e:
                        logger.error(f"Error checking is_creator: {e}", exc_info=True)
                        is_creator = False
                    
                    if is_admin_env and not is_creator:
                        flash('Доступ к админ-панели разрешен только Создателю', 'danger')
                        return render_template('remote_admin/login.html' if is_admin_env else 'auth/login.html', form=form)
                    
                    user.last_login = moscow_now()
                    try:
                        db.session.commit()
                    except Exception as e:
                        db.session.rollback()
                        raise
                    
                    login_user(user, remember=True)
                    
                    audit_logger.log(
                        action='login',
                        entity='User',
                        entity_id=user.id,
                        status='success',
                        metadata={'username': user.username, 'role': user.role}
                    )
                    
                    next_page = request.args.get('next')
                    if next_page and next_page.startswith('/'):
                        pass
                    elif is_admin_env:
                        next_page = url_for('remote_admin.dashboard')
                    elif user.is_parent():
                        next_page = url_for('parents.parent_dashboard')
                    elif user.is_student():
                        eff = get_effective_access_for_user(user.id)
                        allow_lessons = True if eff.allow_lessons is None else bool(eff.allow_lessons)
                        allow_trainer = True if eff.allow_trainer is None else bool(eff.allow_trainer)
                        if eff.status == 'expired':
                            next_page = url_for('auth.user_profile')

                        elif (allow_lessons is False) and (allow_trainer is True):
                            next_page = url_for('trainer.trainer_embed')
                        elif (allow_lessons is False) and (allow_trainer is False):
                            next_page = url_for('auth.user_profile')
                        else:
                            student = Student.query.filter_by(user_id=user.id).first()
                            if student:
                                next_page = url_for('students.student_profile', student_id=student.student_id)
                            else:
                                next_page = url_for('main.student_dashboard')
                    elif user.is_admin():
                        next_page = url_for('main.dashboard')
                    else:
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
    from app.models import Student, Lesson, db
    linked_student = None
    recent_lessons = []
    lesson_counts = {'total': 0, 'planned': 0, 'completed': 0}
    try:
        if current_user.is_student():
            linked_student = Student.query.filter_by(user_id=current_user.id).first()
            if linked_student:
                recent_lessons = Lesson.query.filter_by(student_id=linked_student.student_id).order_by(
                    Lesson.lesson_date.desc()
                ).limit(6).all()
                lesson_counts['total'] = Lesson.query.filter_by(student_id=linked_student.student_id).count()
                lesson_counts['planned'] = Lesson.query.filter_by(student_id=linked_student.student_id, status='planned').count()
                lesson_counts['completed'] = Lesson.query.filter_by(student_id=linked_student.student_id, status='completed').count()
    except Exception as e:
        logger.warning(f"Failed to build profile context for user {current_user.id}: {e}")
        linked_student = None
        recent_lessons = []
        lesson_counts = {'total': 0, 'planned': 0, 'completed': 0}

    return render_template(
        'user_profile.html',
        linked_student=linked_student,
        recent_lessons=recent_lessons,
        lesson_counts=lesson_counts,
    )


@auth_bp.route('/user/<int:user_id>')
@login_required
def user_public_profile(user_id: int):
    """
    Публичный (read-only) профиль пользователя для просмотра “как в соцсетях”.
    Не показывает приватные данные (телефон), только имя/роль/описание/аватар/ID/Telegram.
    """
    if user_id == current_user.id:
        return redirect(url_for('auth.user_profile'))

    u = User.query.get_or_404(user_id)

    display_name = None
    try:
        if u.profile:
            fn = (u.profile.first_name or '').strip()
            ln = (u.profile.last_name or '').strip()
            name = (fn + ' ' + ln).strip()
            display_name = name or None
    except Exception:
        display_name = None

    creator_cover_url = None
    custom_theme_user_id = int(current_app.config.get('CUSTOM_THEME_USER_ID', 999))
    if (getattr(u, 'is_creator', lambda: False)() or u.id == custom_theme_user_id) and getattr(u, 'profile', None):
        creator_cover_url = getattr(u.profile, 'cover_url', None)
    public_numeric_id = None
    if getattr(u, 'is_student', lambda: False)():
        from app.models import Student
        st = Student.query.filter_by(user_id=u.id).first()
        if st and getattr(st, 'platform_id', None):
            public_numeric_id = str(st.platform_id)
    if public_numeric_id is None and getattr(u, 'numeric_id', None):
        public_numeric_id = str(u.numeric_id)
    if public_numeric_id is None:
        public_numeric_id = str(u.id)
    return render_template(
        'user_public_profile.html',
        public_user=u,
        public_display_name=display_name or u.username,
        creator_cover_url=creator_cover_url,
        public_numeric_id=public_numeric_id,
    )

@auth_bp.route('/user/profile/update', methods=['POST'])
@login_required
def profile_update():
    """Обновление данных профиля (AJAX)"""
    from werkzeug.exceptions import RequestEntityTooLarge
    
    try:
        validate_csrf(request.form.get('csrf_token') or request.headers.get('X-CSRFToken'))
    except CSRFError as e:
        logger.warning(f"CSRF validation failed: {e}")
        return jsonify({'success': False, 'error': 'Ошибка безопасности. Обновите страницу.'}), 403
    
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form

    try:
        if 'avatar_file' in request.files:
            file = request.files['avatar_file']
            if file and file.filename:
                allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
                filename = secure_filename(file.filename)
                ext = os.path.splitext(filename)[1].lower()
                
                if ext not in allowed_extensions:
                    return jsonify({'success': False, 'error': 'Недопустимый формат файла. Используйте JPG, PNG, GIF или WEBP'}), 400
                
                file.seek(0, os.SEEK_END)
                file_size = file.tell()
                file.seek(0)
                if file_size > 5 * 1024 * 1024:
                    return jsonify({'success': False, 'error': 'Файл слишком большой. Максимум 5MB'}), 400
                
                unique_filename = f"avatar_{current_user.id}{ext}"
                avatar_upload_root = current_app.config.get('AVATAR_UPLOAD_ROOT')
                if avatar_upload_root:
                    upload_folder = os.path.abspath(avatar_upload_root)
                    avatar_url = f"/avatars/{unique_filename}"
                else:
                    app_root = os.path.dirname(current_app.root_path)
                    upload_folder = os.path.join(app_root, 'static', 'uploads', 'avatars')
                    upload_folder = os.path.abspath(upload_folder)
                    avatar_url = f"/static/uploads/avatars/{unique_filename}"
                
                os.makedirs(upload_folder, exist_ok=True)
                if not os.path.isdir(upload_folder):
                    logger.error(f"Failed to create upload folder: {upload_folder}")
                    return jsonify({'success': False, 'error': 'Не удалось создать папку для загрузки'}), 500
                file_path = os.path.join(upload_folder, unique_filename)
                if not os.path.abspath(file_path).startswith(os.path.abspath(upload_folder)):
                    return jsonify({'success': False, 'error': 'Недопустимый путь'}), 400
                file.save(file_path)
                if not os.path.isfile(file_path):
                    logger.error(f"File was not saved: {file_path}")
                    return jsonify({'success': False, 'error': 'Не удалось сохранить файл'}), 500
                current_user.avatar_url = avatar_url
                if getattr(current_user, 'profile', None):
                    current_user.profile.avatar_url = avatar_url
                logger.info(f"Avatar uploaded for user {current_user.id}: {avatar_url}")

        if getattr(current_user, 'is_creator', lambda: False)() and 'cover_file' in request.files:
            file = request.files['cover_file']
            if file and file.filename:
                allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
                filename = secure_filename(file.filename)
                ext = os.path.splitext(filename)[1].lower()
                if ext not in allowed_extensions:
                    return jsonify({'success': False, 'error': 'Недопустимый формат. Используйте JPG, PNG, GIF или WEBP'}), 400
                file.seek(0, os.SEEK_END)
                file_size = file.tell()
                file.seek(0)
                if file_size > 8 * 1024 * 1024:
                    return jsonify({'success': False, 'error': 'Файл слишком большой. Максимум 8MB'}), 400
                unique_filename = f"cover_{current_user.id}{ext}"
                cover_root = current_app.config.get('COVER_UPLOAD_ROOT')
                if cover_root:
                    upload_folder = os.path.abspath(cover_root)
                    cover_url = f"/covers/{unique_filename}"
                else:
                    app_root = os.path.dirname(current_app.root_path)
                    upload_folder = os.path.join(app_root, 'static', 'uploads', 'covers')
                    upload_folder = os.path.abspath(upload_folder)
                    cover_url = f"/static/uploads/covers/{unique_filename}"
                os.makedirs(upload_folder, exist_ok=True)
                if not os.path.isdir(upload_folder):
                    return jsonify({'success': False, 'error': 'Не удалось создать папку для загрузки'}), 500
                file_path = os.path.join(upload_folder, unique_filename)
                if not os.path.abspath(file_path).startswith(os.path.abspath(upload_folder)):
                    return jsonify({'success': False, 'error': 'Недопустимый путь'}), 400
                file.save(file_path)
                if getattr(current_user, 'profile', None):
                    current_user.profile.cover_url = cover_url
                logger.info(f"Cover uploaded for user {current_user.id}: {cover_url}")

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
        
        cover_url = None
        if getattr(current_user, 'profile', None):
            cover_url = getattr(current_user.profile, 'cover_url', None)
        return jsonify({'success': True, 'avatar_url': current_user.avatar_url, 'cover_url': cover_url})
        
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



@auth_bp.route('/miro/callback', methods=['GET', 'POST'])
def miro_oauth_callback():
    """
    Callback endpoint для Miro OAuth 2.0.
    Miro редиректит сюда после авторизации пользователя.
    """
    code = request.args.get('code')
    error = request.args.get('error')
    state = request.args.get('state')  # Для CSRF защиты
    
    if error:
        logger.warning(f"Miro OAuth error: {error}")
        flash(f'Ошибка авторизации Miro: {error}', 'danger')
        return redirect(url_for('main.dashboard'))
    
    if not code:
        return jsonify({'status': 'ok', 'message': 'Miro OAuth callback endpoint'}), 200
    
    
    logger.info(f"Miro OAuth callback received with code: {code[:10]}...")
    flash('Miro авторизация успешна!', 'success')
    return redirect(url_for('main.dashboard'))
