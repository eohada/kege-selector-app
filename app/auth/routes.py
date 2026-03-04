"""
Маршруты аутентификации
"""
import os
import logging
from werkzeug.utils import secure_filename
from flask import render_template, request, redirect, url_for, flash, jsonify, current_app, make_response, session
from flask_login import login_user, logout_user, login_required, current_user
from flask_wtf.csrf import validate_csrf, CSRFError
import uuid

logger = logging.getLogger(__name__)
from werkzeug.security import check_password_hash, generate_password_hash
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired

from app.auth import auth_bp
from app.limiter import limiter
from datetime import timedelta
from app.models import db, User, UserProfile, UserRole, moscow_now, Student, Tasks, Assignment, AssignmentTask, Submission, Lesson, LessonTask
from app.utils.subscription_access import get_effective_access_for_user
from app.utils.cross_env_login import verify_cross_env_token
from core.audit_logger import audit_logger

class LoginForm(FlaskForm):
    """Форма входа для пользователей"""
    username = StringField('Логин', validators=[DataRequired()])
    password = PasswordField('Пароль', validators=[DataRequired()])
    submit = SubmitField('Войти')

def _redirect_after_login(user):
    """Редирект после входа (для cross_env)."""
    is_admin_env = os.environ.get('ENVIRONMENT') == 'admin'
    if is_admin_env:
        return url_for('remote_admin.dashboard')
    if user.is_parent():
        return url_for('parents.parent_dashboard')
    if user.is_student():
        eff = get_effective_access_for_user(user.id)
        allow_lessons = True if eff.allow_lessons is None else bool(eff.allow_lessons)
        allow_trainer = True if eff.allow_trainer is None else bool(eff.allow_trainer)
        if eff.status == 'expired':
            return url_for('auth.user_profile')
        if (allow_lessons is False) and (allow_trainer is True):
            return url_for('trainer.trainer_embed')
        if (allow_lessons is False) and (allow_trainer is False):
            return url_for('auth.user_profile')
        student = Student.query.filter_by(user_id=user.id).first()
        if student:
            return url_for('students.student_profile', student_id=student.student_id)
        return url_for('main.student_dashboard')
    return url_for('main.dashboard')


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("15 per minute")
def login():
    """Страница входа"""
    try:
        is_admin_env = os.environ.get('ENVIRONMENT') == 'admin'
        
        try:
            is_authenticated = current_user.is_authenticated if hasattr(current_user, 'is_authenticated') else False
        except Exception as e:
            logger.warning(f"Error checking authentication: {e}")
            is_authenticated = False
        
        # Кросс-вход с другого окружения (Прод/Песочница): GET /login?cross_env=TOKEN
        if request.method == 'GET' and not is_authenticated:
            cross_token = request.args.get('cross_env')
            secret = current_app.config.get('CROSS_ENV_LOGIN_SECRET')
            if cross_token and secret:
                payload = verify_cross_env_token(cross_token, secret)
                if payload:
                    user = User.query.get(payload['user_id']) or User.query.filter_by(username=payload['username']).first()
                    if user and user.is_active:
                        login_user(user, remember=True)
                        try:
                            user.last_login = moscow_now()
                            db.session.commit()
                        except Exception:
                            db.session.rollback()
                        audit_logger.log(
                            action='login',
                            entity='User',
                            entity_id=user.id,
                            status='success',
                            metadata={'username': user.username, 'role': user.role, 'cross_env': True}
                        )
                        flash('Вход выполнен (кросс-окружение).', 'success')
                        return redirect(_redirect_after_login(user))
                    else:
                        flash('Пользователь не найден в этом окружении.', 'warning')
                else:
                    flash('Ссылка для входа устарела или неверна. Войдите вручную.', 'warning')
        
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
        entity_id=username, # Note: using username as entity_id for logout if current_user is already cleared
        status='success',
        metadata={'username': username}
    )
    
    # Очищаем localStorage на клиенте, если это был демо-режим
    response = make_response(redirect(url_for('auth.login')))
    response.set_cookie('is_demo', '', expires=0)
    response.set_cookie('cinemaMode', '', expires=0)
    return response

@auth_bp.route('/demo/start')
def demo_start():
    """Создает временного демо-пользователя и запускает кинематографический тур."""
    from app.models import StudentTaskStatistics
    from core.db_models import UserMastery, KnowledgeNode
    import random

    if current_user.is_authenticated:
        logout_user()

    demo_username = f"demo_user_{uuid.uuid4().hex[:8]}"
    demo_password = uuid.uuid4().hex
    hashed_password = generate_password_hash(demo_password)

    user = User(username=demo_username, email=f"{demo_username}@demo.local",
                password_hash=hashed_password, role='student', is_demo_user=True)
    db.session.add(user)
    db.session.flush()
    db.session.add(UserRole(user_id=user.id, role='student'))
    demo_student = Student(name='Демо-ученик', user_id=user.id, is_active=True, email=f"{demo_username}@demo.local")
    db.session.add(demo_student)
    db.session.flush()

    creator = User.query.filter(User.role.in_(['creator', 'chief_admin', 'admin', 'tutor'])).first()
    created_by_id = creator.id if creator else user.id

    demo_submission_id = None
    demo_lesson_id = None

    import re as _re
    _surname_re = _re.compile(r'^\s*[\(<]?\s*[А-ЯЁA-Z]\.\s*[А-ЯЁA-Z]?\.?\s*[А-ЯЁа-яёA-Za-z\-]{2,}')

    def _no_surname(t):
        if not t or not t.content_html:
            return True
        return not _surname_re.match(t.content_html.strip())

    demo_tasks = []
    for tn in [2, 5, 8, 10, 14]:
        candidates = Tasks.query.filter_by(task_number=tn).all()
        chosen = None
        for c in candidates:
            if _no_surname(c):
                chosen = c
                break
        if not chosen and candidates:
            chosen = candidates[0]
        if chosen:
            demo_tasks.append(chosen)
    if not demo_tasks:
        demo_tasks = Tasks.query.limit(5).all()

    first_task = demo_tasks[0] if demo_tasks else Tasks.query.first()

    # --- 8 completed lessons with varied LessonTasks for realistic analytics ---
    all_task_pool = Tasks.query.limit(30).all()
    lesson_topics = [
        'Системы счисления', 'Логические выражения', 'Графы и деревья',
        'Алгоритмы обработки данных', 'Программирование на Python',
        'Кодирование информации', 'Базы данных и SQL', 'Рекурсия и динамика',
    ]
    lesson_task_configs = [
        (2, [True, True],        1, [True]),
        (3, [True, False, True], 1, [False]),
        (1, [False],             2, [True, False]),
        (2, [True, False],       1, [True]),
        (2, [False, True],       1, [False]),
        (3, [True, True, False], 0, []),
        (1, [True],              2, [False, True]),
        (2, [True, True],        1, [True]),
    ]

    for i, topic in enumerate(lesson_topics):
        completed_lesson = Lesson(
            student_id=demo_student.student_id,
            lesson_type='regular',
            lesson_date=moscow_now() - timedelta(days=(i + 1) * 4),
            duration=60,
            status='completed',
            topic=f'Урок {i + 1}: {topic}',
        )
        db.session.add(completed_lesson)
        db.session.flush()

        n_hw, hw_correct, n_exam, exam_correct = lesson_task_configs[i]
        for j in range(n_hw):
            t = all_task_pool[(i * 3 + j) % len(all_task_pool)] if all_task_pool else first_task
            if t:
                db.session.add(LessonTask(
                    lesson_id=completed_lesson.lesson_id, task_id=t.task_id,
                    assignment_type='homework', status='graded',
                    submission_correct=hw_correct[j], student_answer=t.answer or '42',
                ))
        for j in range(n_exam):
            t = all_task_pool[(i * 3 + n_hw + j) % len(all_task_pool)] if all_task_pool else first_task
            if t:
                db.session.add(LessonTask(
                    lesson_id=completed_lesson.lesson_id, task_id=t.task_id,
                    assignment_type='exam', status='graded',
                    submission_correct=exam_correct[j], student_answer=t.answer or '42',
                ))

    # --- Main demo assignment (ASSIGNED — for interactive demo) ---
    task_answer_map = {}
    if demo_tasks:
        deadline = moscow_now() + timedelta(days=7)
        assignment = Assignment(
            title='Тренировочный вариант ЕГЭ — информатика',
            description='Демо-вариант: реши задания, вставь ответы и сдай работу.',
            assignment_type='homework',
            deadline=deadline,
            hard_deadline=False,
            created_by_id=created_by_id,
            is_active=True,
        )
        db.session.add(assignment)
        db.session.flush()

        total_score = 0
        at_objects = []
        for idx, t in enumerate(demo_tasks):
            score = 2 if t.task_number >= 19 else 1
            total_score += score
            at = AssignmentTask(
                assignment_id=assignment.assignment_id,
                task_id=t.task_id,
                order_index=idx,
                max_score=score,
            )
            db.session.add(at)
            at_objects.append((at, t))

        db.session.flush()
        for at, t in at_objects:
            task_answer_map[str(at.assignment_task_id)] = t.answer or str(random.randint(10, 999))

        sub = Submission(
            assignment_id=assignment.assignment_id,
            student_id=demo_student.student_id,
            status='ASSIGNED',
            assigned_at=moscow_now(),
            max_score=total_score,
        )
        db.session.add(sub)
        db.session.flush()
        demo_submission_id = sub.submission_id

        demo_lesson = Lesson(
            student_id=demo_student.student_id,
            lesson_type='regular',
            lesson_date=moscow_now() + timedelta(hours=1),
            duration=60,
            status='in_progress',
            topic='Демо-урок: Теория игр',
            content='# Теория игр\nОсновы комбинаторики и теории игр для задания 19 ЕГЭ по информатике.',
        )
        db.session.add(demo_lesson)
        db.session.flush()
        demo_lesson_id = demo_lesson.lesson_id

        for i, t in enumerate(demo_tasks[:3]):
            db.session.add(LessonTask(
                lesson_id=demo_lesson.lesson_id,
                task_id=t.task_id,
                assignment_type='classwork',
                status='pending',
            ))

    # --- Student stats for analytics — varied distribution ---
    weak_tasks = {3, 7, 12, 18, 24}
    strong_tasks = {1, 5, 8, 14, 20}
    for tn in range(1, 28):
        if tn in weak_tasks:
            correct = random.randint(2, 6)
            incorrect = random.randint(4, 9)
        elif tn in strong_tasks:
            correct = random.randint(13, 20)
            incorrect = random.randint(0, 3)
        else:
            correct = random.randint(5, 14)
            incorrect = random.randint(2, 7)
        db.session.add(StudentTaskStatistics(
            student_id=demo_student.student_id,
            task_number=tn,
            manual_correct=correct,
            manual_incorrect=incorrect,
        ))

    # --- Trainer: find task 5 without surname, with known answer ---
    trainer_candidates = Tasks.query.filter(
        Tasks.task_number == 5,
        Tasks.answer.isnot(None),
        Tasks.answer != '',
    ).all()
    trainer_task = None
    for tc in trainer_candidates:
        if _no_surname(tc):
            trainer_task = tc
            break
    if not trainer_task and trainer_candidates:
        trainer_task = trainer_candidates[0]
    if not trainer_task:
        trainer_task = Tasks.query.filter(
            Tasks.answer.isnot(None), Tasks.answer != '',
        ).first()

    trainer_hint = 'Обрати внимание на ограничения в условии и проверь граничные значения.'
    if trainer_task and trainer_task.hints:
        try:
            raw = trainer_task.hints
            if isinstance(raw, list) and raw:
                first = raw[0]
                if isinstance(first, str) and len(first) > 10:
                    trainer_hint = first
                elif isinstance(first, dict):
                    trainer_hint = first.get('text') or first.get('content') or trainer_hint
        except Exception:
            pass

    # --- UserMastery for realistic EGE analytics ratings ---
    strong_nodes = {1, 5, 8, 14, 20}
    weak_nodes = {3, 7, 12, 18, 24}
    knowledge_nodes = KnowledgeNode.query.all()
    for node in knowledge_nodes:
        tn = None
        if node.code:
            try:
                tn = int(''.join(c for c in node.code if c.isdigit()) or '0')
            except ValueError:
                tn = 0
        if tn in strong_nodes:
            rating = random.uniform(1400, 1800)
        elif tn in weak_nodes:
            rating = random.uniform(700, 950)
        else:
            rating = random.uniform(1050, 1350)
        db.session.add(UserMastery(
            user_id=user.id,
            node_id=node.id,
            rating=round(rating, 1),
            volatility=round(random.uniform(100, 250), 1),
            streak_days=random.randint(0, 12),
        ))

    db.session.commit()

    login_user(user, remember=True)

    session['cinema_demo_ids'] = {
        'submissionId': demo_submission_id,
        'lessonId': demo_lesson_id,
        'studentId': demo_student.student_id,
        'taskAnswers': task_answer_map,
        'trainerTaskId': trainer_task.task_id if trainer_task else None,
        'trainerTaskNumber': trainer_task.task_number if trainer_task else 1,
        'trainerAnswer': (trainer_task.answer or '42') if trainer_task else '42',
        'trainerHint': trainer_hint,
    }

    response = make_response(redirect(url_for('main.student_dashboard')))
    response.set_cookie('is_demo', 'true', max_age=60*60*24)
    response.set_cookie('cinemaMode', 'prologue', max_age=60*60*24)
    return response

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
    is_custom_theme_user = u.id == custom_theme_user_id or (getattr(u, 'numeric_id', None) is not None and str(u.numeric_id) == str(custom_theme_user_id))
    if (getattr(u, 'is_creator', lambda: False)() or is_custom_theme_user) and getattr(u, 'profile', None):
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

        custom_theme_user_id = int(current_app.config.get('CUSTOM_THEME_USER_ID', 999))
        is_custom_theme_user = (current_user.id == custom_theme_user_id or (getattr(current_user, 'numeric_id', None) is not None and str(current_user.numeric_id) == str(custom_theme_user_id)))
        if (getattr(current_user, 'is_creator', lambda: False)() or is_custom_theme_user) and 'cover_file' in request.files:
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
