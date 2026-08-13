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

from sqlalchemy import func

logger = logging.getLogger(__name__)
from werkzeug.security import check_password_hash, generate_password_hash
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired

from app.auth import auth_bp
from app.limiter import limiter
from datetime import timedelta
from app.models import db, User, UserProfile, UserRole, moscow_now, Student, Tasks, Assignment, AssignmentTask, Submission, Lesson, LessonTask, Course, ReferralCode, ReferralUsage, Enrollment, FamilyTie
from app.notifications.service import notify_user
from app.utils.subscription_access import get_effective_access_for_user
from app.utils.course_tasks import get_task_numbers, get_max_score_for_task
from app.utils.cross_env_login import verify_cross_env_token
from core.audit_logger import audit_logger

class LoginForm(FlaskForm):
    """Форма входа для пользователей"""
    username = StringField('Логин', validators=[DataRequired()])
    password = PasswordField('Пароль', validators=[DataRequired()])
    submit = SubmitField('Войти')

def _redirect_after_login(user):
    """Редирект после входа (для cross_env)."""
    is_admin_env = os.environ.get('ENVIRONMENT') == 'admin' or (request.host or '').split(':')[0].lower().startswith('admin.')
    if is_admin_env:
        return url_for('remote_admin.dashboard')
    if user.is_parent():
        return url_for('parents.parent_dashboard')
    if user.is_student():
        eff = get_effective_access_for_user(user.id)
        allow_lessons = True if eff.allow_lessons is None else bool(eff.allow_lessons)
        allow_trainer = bool(current_app.config.get('TRAINER_ENABLED', False)) and (
            True if eff.allow_trainer is None else bool(eff.allow_trainer)
        )
        if eff.status == 'expired':
            return url_for('main.workspace_profile')
        if (allow_lessons is False) and (allow_trainer is True):
            return url_for('trainer.trainer_embed')
        if (allow_lessons is False) and (allow_trainer is False):
            return url_for('main.workspace_profile')
        return url_for('main.dashboard')
    return url_for('main.dashboard')


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("15 per minute")
def login():
    """Страница входа"""
    try:
        is_admin_env = os.environ.get('ENVIRONMENT') == 'admin' or (request.host or '').split(':')[0].lower().startswith('admin.')
        is_demo_site = current_app.config.get('DEMO_SITE') is True
        if not is_demo_site and current_app.config.get('DEMO_HOST'):
            req_host = (request.host or '').split(':')[0].lower()
            is_demo_site = req_host == current_app.config.get('DEMO_HOST')

        try:
            is_authenticated = current_user.is_authenticated if hasattr(current_user, 'is_authenticated') else False
        except Exception as e:
            logger.warning(f"Error checking authentication: {e}")
            is_authenticated = False

        # На демо-сайте / демо-хосте авторизация отключена: редирект на выбор демо (ОГЭ/ЕГЭ)
        if is_demo_site and not is_authenticated:
            if request.method == 'GET' and not request.args.get('cross_env'):
                return redirect(url_for('auth.demo_choose'))
            if request.method == 'POST':
                return redirect(url_for('auth.demo_choose'))
        
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
                    
                    if is_admin_env and not (is_creator or user.is_admin()):
                        flash('Доступ к админ-панели разрешен только Создателю или Администратору', 'danger')
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
                        allow_trainer = bool(current_app.config.get('TRAINER_ENABLED', False)) and (
                            True if eff.allow_trainer is None else bool(eff.allow_trainer)
                        )
                        if eff.status == 'expired':
                            next_page = url_for('main.workspace_profile')

                        elif (allow_lessons is False) and (allow_trainer is True):
                            next_page = url_for('trainer.trainer_embed')
                        elif (allow_lessons is False) and (allow_trainer is False):
                            next_page = url_for('main.workspace_profile')
                        else:
                            next_page = url_for('main.dashboard')
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
        is_admin_env = os.environ.get('ENVIRONMENT') == 'admin' or (request.host or '').split(':')[0].lower().startswith('admin.')
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


@auth_bp.route('/demo')
def demo_choose():
    """Страница выбора экзамена (ОГЭ или ЕГЭ) перед запуском демо-тура."""
    return render_template('demo_choose.html')


DEMO_ACCESS_CODE = 'test'


@auth_bp.route('/demo/start')
def demo_start():
    """Создает временного демо-пользователя и запускает кинематографический тур. Обязателен код доступа."""
    from app.models import StudentTaskStatistics, Subject
    from core.db_models import UserMastery, KnowledgeNode
    import random

    code = (request.args.get('code') or '').strip()

    # Новый сценарий: поле «Код доступа» используется либо как персональный реферальный код,
    # либо как общий демонстрационный код DEMO_ACCESS_CODE.
    if not code:
        return redirect(url_for('auth.demo_choose', error='invalid_code'))

    referral_obj = ReferralCode.query.filter(
        func.upper(ReferralCode.code) == code.upper(),
        ReferralCode.is_active.is_(True),
    ).first()

    if not referral_obj and code != DEMO_ACCESS_CODE:
        # Ни реферального кода, ни общего кода — считаем ввод неверным
        session['demo_ref_code_invalid'] = code
        return redirect(url_for('auth.demo_choose', error='invalid_code'))

    if current_user.is_authenticated:
        logout_user()

    if referral_obj:
        session['demo_ref_code'] = referral_obj.code
        session.pop('demo_ref_code_invalid', None)
    else:
        # Используем общий код DEMO_ACCESS_CODE без реферала
        session.pop('demo_ref_code', None)
        session.pop('demo_ref_code_invalid', None)

    exam = (request.args.get('exam') or 'ege').strip().lower()
    if exam not in ('oge', 'ege'):
        exam = 'ege'
    course_slug = 'oge_informatics' if exam == 'oge' else 'ege_informatics'
    course = Course.query.filter_by(slug=course_slug).first()
    course_id = course.id if course else None
    subject_slug = 'oge' if exam == 'oge' else 'kege'
    subject = Subject.query.filter_by(slug=subject_slug).first()
    subject_id = subject.id if subject else None

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

    if referral_obj:
        referral_obj.usage_count += 1
        db.session.add(ReferralUsage(referral_code_id=referral_obj.id, user_id=user.id))
        
        # Уведомляем создателя кода
        friend_label = (referral_obj.note or '').strip()
        inviter_display = friend_label or referral_obj.code
        notify_user(
            referral_obj.creator_id,
            kind='referral_used',
            title='🚀 Новый реферал!',
            body=f"Новый пользователь начал демо-тур по приглашению «{inviter_display}» (код {referral_obj.code}).",
            meta={'referral_code': referral_obj.code, 'demo_user_id': user.id, 'friend_label': friend_label}
        )

        # Уведомляем админов системы о новом реферале
        try:
            # Ищем всех пользователей с админ-ролями (creator, chief_admin, admin, chief_tester)
            # Проверяем как основную роль, так и дополнительные роли из UserRoles
            admin_roles = ['creator', 'chief_admin', 'admin', 'chief_tester']
            admin_users_set = set()
            
            # Сначала проверим основную роль
            basic_admins = User.query.filter(User.role.in_(admin_roles)).all()
            for admin in basic_admins:
                admin_users_set.add(admin.id)
            
            # Затем проверим дополнительные роли
            role_admins = db.session.query(User).join(UserRole).filter(
                UserRole.role.in_(admin_roles)
            ).all()
            for admin in role_admins:
                admin_users_set.add(admin.id)
            
            # Получим объекты пользователей
            admin_users = [User.query.get(uid) for uid in admin_users_set]
            
            logger.info(f"📢 Уведомляю {len(admin_users)} админов(ы) системы о новом реферале: {referral_obj.code}")
            for admin in admin_users:
                if admin.id == referral_obj.creator_id:
                    # Не отправляем второе уведомление создателю
                    continue
                try:
                    notify_user(
                        admin.id,
                        kind='referral_used',
                        title='🚀 Новый реферал!',
                        body=f"Новый пользователь начал демо-тур по приглашению «{inviter_display}» (код {referral_obj.code}).",
                        meta={'referral_code': referral_obj.code, 'demo_user_id': user.id, 'friend_label': friend_label}
                    )
                    logger.info(f"✅ Уведомление добавлено админу {admin.username} о реферале {referral_obj.code}")
                except Exception as e:
                    logger.warning(f"⚠️  Ошибка при создании уведомления для админа {admin.username}: {e}")
        except Exception as e:
            logger.warning(f"⚠️  Ошибка при поиске админов системы: {e}")

    creator = User.query.filter(User.role.in_(['creator', 'chief_admin', 'admin', 'chief_tester', 'tutor'])).first()
    created_by_id = creator.id if creator else user.id

    demo_submission_id = None
    demo_lesson_id = None

    import re as _re
    _surname_re = _re.compile(r'^\s*[\(<]?\s*[А-ЯЁA-Z]\.\s*[А-ЯЁA-Z]?\.?\s*[А-ЯЁа-яёA-Za-z\-]{2,}')

    def _no_surname(t):
        if not t or not t.content_html:
            return True
        return not _surname_re.match(t.content_html.strip())

    # Сначала пробуем жёсткий сценарий из data/demo_scenario.json (засиженные задачи с site_task_id demo:assign:* и demo:trainer)
    _base = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    demo_tasks = []
    lesson_task_numbers = [3, 6, 9] if exam == 'ege' else [1, 3, 5]
    lesson_indices = [0, 1, 2]
    if course_id:
        assign_tasks = Tasks.query.filter(
            Tasks.course_id == course_id,
            Tasks.site_task_id.isnot(None),
            Tasks.site_task_id.like('demo:assign:%'),
        ).order_by(Tasks.site_task_id).all()
        if assign_tasks:
            demo_tasks = assign_tasks
            try:
                import json as _json
                _sc_path = os.path.join(_base, 'data', 'demo_scenario.json')
                if os.path.isfile(_sc_path):
                    with open(_sc_path, 'r', encoding='utf-8') as _f:
                        _sc = _json.load(_f)
                    _key = 'ege' if exam == 'ege' else 'oge'
                    if _key in _sc and _sc[_key].get('lesson_indices') is not None:
                        lesson_indices = _sc[_key]['lesson_indices']
            except Exception:
                pass

    # Fallback: конфиг по номерам из data/demo_tasks_config.json или дефолты
    demo_task_numbers = [3, 6, 9, 10, 14] if exam == 'ege' else [1, 3, 5, 8, 10]
    trainer_task_num = 5
    if not demo_tasks:
        try:
            import json as _json
            _cfg_path = os.path.join(_base, 'data', 'demo_tasks_config.json')
            if os.path.isfile(_cfg_path):
                with open(_cfg_path, 'r', encoding='utf-8') as _f:
                    _cfg = _json.load(_f)
                _key = 'ege' if exam == 'ege' else 'oge'
                if _key in _cfg:
                    _c = _cfg[_key]
                    if _c.get('assignment_task_numbers'):
                        demo_task_numbers = _c['assignment_task_numbers']
                    if _c.get('lesson_task_numbers') is not None:
                        lesson_task_numbers = _c['lesson_task_numbers']
                    if _c.get('trainer_task_number') is not None:
                        trainer_task_num = int(_c['trainer_task_number'])
        except Exception:
            pass
        task_query = Tasks.query.filter(
            Tasks.answer.isnot(None), Tasks.answer != '', Tasks.is_active.is_(True),
        )
        if course_id:
            task_query = task_query.filter_by(course_id=course_id)
        for tn in demo_task_numbers:
            candidates = task_query.filter_by(task_number=tn).all()
            chosen = next((c for c in candidates if _no_surname(c)), None) or (candidates[0] if candidates else None)
            if chosen:
                demo_tasks.append(chosen)
        if not demo_tasks:
            demo_tasks = (
                task_query.limit(5).all()
                if course_id
                else Tasks.query.filter(Tasks.is_active.is_(True)).limit(5).all()
            )

    first_task = demo_tasks[0] if demo_tasks else (
        Tasks.query.filter_by(course_id=course_id, is_active=True).first()
        if course_id
        else Tasks.query.filter(Tasks.is_active.is_(True)).first()
    )

    # --- 8 completed lessons with varied LessonTasks for realistic analytics ---
    all_task_pool = (
        Tasks.query.filter_by(course_id=course_id, is_active=True).limit(30).all()
        if course_id
        else Tasks.query.filter(Tasks.is_active.is_(True)).limit(30).all()
    )
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
        assignment_title = 'Тренировочный вариант ОГЭ — информатика' if exam == 'oge' else 'Тренировочный вариант ЕГЭ — информатика'
        assignment = Assignment(
            title=assignment_title,
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
            score = get_max_score_for_task(course_id, t.task_number)
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

        lesson_topic = 'Демо-урок' if exam == 'ege' else 'Демо-урок: Алгоритмы'
        lesson_content = '# Теория игр\nОсновы комбинаторики и теории игр для задания 19 ЕГЭ по информатике.' if exam == 'ege' else '# Алгоритмы\nОсновы программирования для ОГЭ по информатике.'
        demo_lesson = Lesson(
            student_id=demo_student.student_id,
            lesson_type='regular',
            lesson_date=moscow_now() + timedelta(hours=1),
            duration=60,
            status='in_progress',
            topic=lesson_topic,
            content=lesson_content,
        )
        db.session.add(demo_lesson)
        db.session.flush()
        demo_lesson_id = demo_lesson.lesson_id

        # Для демо-урока: из сценария — по lesson_indices, иначе по номерам
        if demo_tasks and all(getattr(t, 'site_task_id', None) and str(t.site_task_id or '').startswith('demo:assign:') for t in demo_tasks):
            lesson_tasks_for_demo = [demo_tasks[i] for i in lesson_indices if 0 <= i < len(demo_tasks)]
        else:
            lesson_tasks_for_demo = []
            task_query = Tasks.query.filter(
                Tasks.answer.isnot(None), Tasks.answer != '', Tasks.is_active.is_(True),
            )
            if course_id:
                task_query = task_query.filter_by(course_id=course_id)
            for tn in lesson_task_numbers:
                cands = task_query.filter_by(task_number=tn).all()
                ch = next((c for c in cands if _no_surname(c)), None) or (cands[0] if cands else None)
                if ch:
                    lesson_tasks_for_demo.append(ch)
        if not lesson_tasks_for_demo:
            lesson_tasks_for_demo = demo_tasks[:3]
        for t in lesson_tasks_for_demo:
            db.session.add(LessonTask(
                lesson_id=demo_lesson.lesson_id,
                task_id=t.task_id,
                assignment_type='classwork',
                status='pending',
            ))

    # --- Student stats for analytics — varied distribution ---
    task_numbers = get_task_numbers(course_id)
    weak_tasks = {3, 7, 12, 18, 24} if exam == 'ege' else {2, 5, 9, 12}
    strong_tasks = {1, 5, 8, 14, 20} if exam == 'ege' else {1, 4, 7, 11, 15}
    for tn in task_numbers:
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
            course_id=course_id,
            task_number=tn,
            manual_correct=correct,
            manual_incorrect=incorrect,
        ))

    # --- Trainer: приоритет — задача из сценария (site_task_id demo:trainer), иначе по номеру ---
    trainer_task = None
    trainer_hint = 'Обрати внимание на ограничения в условии и проверь граничные значения.'
    trainer_correction = ''
    if course_id:
        trainer_task = Tasks.query.filter_by(course_id=course_id, site_task_id='demo:trainer').first()
    if trainer_task and trainer_task.hints and isinstance(trainer_task.hints, list):
        raw = trainer_task.hints
        if len(raw) >= 2:
            h0, h1 = raw[0], raw[1]
            trainer_hint = (h0.get('text') or h0.get('content') or '') if isinstance(h0, dict) else str(h0)
            trainer_correction = (h1.get('text') or h1.get('content') or '') if isinstance(h1, dict) else str(h1)
        elif raw:
            h0 = raw[0]
            trainer_hint = (h0.get('text') or h0.get('content') or '') if isinstance(h0, dict) else str(h0)

    if not trainer_task:
        trainer_query = Tasks.query.filter(
            Tasks.task_number == trainer_task_num,
            Tasks.answer.isnot(None),
            Tasks.answer != '',
            Tasks.is_active.is_(True),
        )
        if course_id:
            trainer_query = trainer_query.filter_by(course_id=course_id)
        trainer_candidates = trainer_query.all()
        for tc in trainer_candidates:
            if _no_surname(tc):
                trainer_task = tc
                break
        if not trainer_task and trainer_candidates:
            trainer_task = trainer_candidates[0]
        if not trainer_task:
            trainer_query = Tasks.query.filter(
                Tasks.answer.isnot(None), Tasks.answer != '', Tasks.is_active.is_(True),
            )
            if course_id:
                trainer_query = trainer_query.filter_by(course_id=course_id)
            trainer_task = trainer_query.first()
        if trainer_task and trainer_task.hints:
            try:
                raw = trainer_task.hints
                if isinstance(raw, list) and raw:
                    first = raw[0]
                    if isinstance(first, dict):
                        trainer_hint = first.get('text') or first.get('content') or trainer_hint
                    elif isinstance(first, str) and len(first) > 10:
                        trainer_hint = first
            except Exception:
                pass

    # --- UserMastery for realistic analytics ratings ---
    strong_nodes = {1, 5, 8, 14, 20} if exam == 'ege' else {1, 4, 7, 11, 15}
    weak_nodes = {3, 7, 12, 18, 24} if exam == 'ege' else {2, 5, 9, 12}
    knowledge_nodes = KnowledgeNode.query.filter_by(subject_id=subject_id).all() if subject_id else KnowledgeNode.query.all()
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

    # Тренажёр: из demo_scenario.json — ответ, вопрос, код с ошибкой, исправленный код, ответ помощника
    trainer_answer = (trainer_task.answer or '42') if trainer_task else '42'
    trainer_question = ''
    trainer_assistant_reply = ''
    trainer_buggy_code = ''
    trainer_fixed_code = ''
    trainer_condition_html = ''
    trainer_error_line = 5
    try:
        import json as _json
        _sc_path = os.path.join(_base, 'data', 'demo_scenario.json')
        if os.path.isfile(_sc_path):
            with open(_sc_path, 'r', encoding='utf-8') as _f:
                _sc = _json.load(_f)
            _key = 'ege' if exam == 'ege' else 'oge'
            if _key in _sc and isinstance(_sc[_key].get('trainer'), dict):
                tr = _sc[_key]['trainer']
                if tr.get('answer'):
                    trainer_answer = str(tr['answer']).strip()
                trainer_question = (tr.get('question') or '').strip()
                trainer_hint = (tr.get('hint') or trainer_hint).strip()
                trainer_assistant_reply = (tr.get('assistant_reply') or '').strip()
                trainer_correction = (tr.get('correction_text') or trainer_correction).strip()
                trainer_buggy_code = (tr.get('buggy_code') or '').strip().replace('\\n', '\n')
                trainer_fixed_code = (tr.get('fixed_code') or '').strip().replace('\\n', '\n')
                trainer_condition_html = (tr.get('condition_html') or '').strip()
                if tr.get('error_line') is not None:
                    trainer_error_line = int(tr.get('error_line', 5))
    except Exception:
        pass

    creator_name = 'Команда платформы'
    creator_profile_url = None
    creator_student_id = None
    creator_user_id = None
    creator_user = User.query.filter_by(role='creator').first()
    if creator_user:
        creator_user_id = creator_user.id
        creator_name = (getattr(creator_user, 'username', None) or getattr(creator_user, 'email', None) or creator_name).strip() or creator_name
        try:
            st = Student.query.filter_by(user_id=creator_user.id).first()
            if not st:
                st = Student(
                    name='Создатель платформы',
                    user_id=creator_user.id,
                    is_active=True,
                    email=getattr(creator_user, 'email', None) or 'creator@demo.local',
                )
                db.session.add(st)
                db.session.flush()
            if st:
                creator_student_id = st.student_id
                creator_profile_url = url_for('students.student_analytics', student_id=st.student_id)
        except Exception:
            pass

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

    session['cinema_demo_ids'] = {
        'exam': exam,
        'submissionId': demo_submission_id,
        'lessonId': demo_lesson_id,
        'studentId': demo_student.student_id,
        'taskAnswers': task_answer_map,
        'trainerTaskId': trainer_task.task_id if trainer_task else None,
        'trainerTaskNumber': trainer_task.task_number if trainer_task else 1,
        'trainerAnswer': trainer_answer,
        'trainerHint': trainer_hint,
        'trainerAssistantReply': trainer_assistant_reply,
        'trainerCorrection': trainer_correction,
        'trainerQuestion': trainer_question,
        'trainerBuggyCode': trainer_buggy_code,
        'trainerFixedCode': trainer_fixed_code,
        'trainerConditionHtml': trainer_condition_html,
        'trainerErrorLine': trainer_error_line,
        'creatorName': creator_name,
        'creatorProfileUrl': creator_profile_url,
        'creatorStudentId': creator_student_id,
        'creatorUserId': creator_user_id,
    }

    cinema_scene = request.args.get('cinema_scene', '').strip()
    if cinema_scene in ('1', '2', '3', '4', '5', '6', '7', '8', '9'):
        dest = url_for('main.dashboard')
        if cinema_scene == '3':
            dest = url_for('theory.theory_index')
        elif cinema_scene == '4':
            dest = url_for('main.dashboard')
        elif cinema_scene == '5' and demo_lesson_id:
            dest = url_for('lessons.lesson_classwork_view', lesson_id=demo_lesson_id) + '?cinema_scene=5'
        elif cinema_scene == '6':
            dest = url_for('main.dashboard')
        elif cinema_scene in ('7', '8', '9') and demo_student.student_id:
            dest = url_for('students.student_analytics', student_id=demo_student.student_id) + '?cinema_scene=' + cinema_scene
        if cinema_scene in ('1', '2'):
            dest = dest + ('&' if '?' in dest else '?') + 'cinema_scene=' + cinema_scene
        response = make_response(redirect(dest))
    else:
        dashboard_url = url_for('main.dashboard')
        dest = dashboard_url + ('&' if '?' in dashboard_url else '?') + 'cinema_scene=0'
        response = make_response(redirect(dest))
    response.set_cookie('is_demo', 'true', max_age=60*60*24)
    response.set_cookie('cinemaMode', 'prologue', max_age=60*60*24)
    return response

def _legacy_user_profile():
    """Страница профиля пользователя"""
    from app.models import Student, Lesson, db, User
    from app.utils.relationship_scope import get_family_ties_for_parent, get_family_ties_for_student
    linked_student = None
    recent_lessons = []
    lesson_counts = {'total': 0, 'planned': 0, 'completed': 0}
    parent_children = []
    student_parents = []
    parent_children_count = 0
    parent_children_confirmed_count = 0
    student_parents_count = 0
    user_profile = getattr(current_user, 'profile', None)
    profile_tz = (
        getattr(current_user, 'timezone_iana', None)
        or getattr(user_profile, 'timezone', None)
        or 'Europe/Moscow'
    )
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
                student_parents = get_family_ties_for_student(current_user.id, include_pending=True)
        elif current_user.is_parent():
            for tie in get_family_ties_for_parent(current_user.id, include_pending=True):
                child_user = User.query.get(tie.student_id)
                if not child_user:
                    continue
                child_student = Student.query.filter_by(user_id=child_user.id).first()
                parent_children.append({
                    'user': child_user,
                    'student': child_student,
                    'confirmed': bool(tie.is_confirmed),
                    })
            parent_children_count = len(parent_children)
            parent_children_confirmed_count = len([item for item in parent_children if item['confirmed']])
    except Exception as e:
        logger.warning(f"Failed to build profile context for user {current_user.id}: {e}")
        linked_student = None
        recent_lessons = []
        lesson_counts = {'total': 0, 'planned': 0, 'completed': 0}
        parent_children = []
        student_parents = []
        parent_children_count = 0
        parent_children_confirmed_count = 0
        student_parents_count = 0

    if current_user.is_student():
        student_parents_count = len(student_parents)
        if linked_student:
            try:
                from app.utils.achievement_service import check_and_grant_dynamic_achievements
                check_and_grant_dynamic_achievements(linked_student)
            except Exception as e:
                logger.error(f"Error checking achievements on profile load: {e}")

    if current_user.is_student():
        return render_template(
            'user_profile_student.html',
            linked_student=linked_student,
            recent_lessons=recent_lessons,
            lesson_counts=lesson_counts,
            profile_tz=profile_tz,
        )

    if current_user.is_creator():
        return render_template(
            'user_profile_creator_v2.html',
            linked_student=linked_student,
            recent_lessons=recent_lessons,
            lesson_counts=lesson_counts,
            profile_tz=profile_tz,
        )

    return render_template(
        'user_profile.html',
        linked_student=linked_student,
        recent_lessons=recent_lessons,
        lesson_counts=lesson_counts,
        parent_children=parent_children,
        student_parents=student_parents,
        parent_children_count=parent_children_count,
        parent_children_confirmed_count=parent_children_confirmed_count,
        student_parents_count=student_parents_count,
        profile_tz=profile_tz,
    )


@auth_bp.route('/user/profile')
@login_required
def workspace_profile():
    """Совместимый адрес: отправляет только в каноничный профиль V2."""
    return redirect(url_for('main.workspace_profile'))


@auth_bp.route('/user/<int:user_id>')
@login_required
def user_public_profile(user_id: int):
    """
    Публичный (read-only) профиль пользователя для просмотра “как в соцсетях”.
    Не показывает приватные данные (телефон), только имя/роль/описание/аватар/ID/Telegram.
    """
    if user_id == current_user.id:
        return redirect(url_for('main.workspace_profile'))

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
    cinema_demo_ids = None
    demo_profile_override = None
    if request.args.get('cinema_scene') == '8' and getattr(current_user, 'is_demo_user', False):
        cinema_demo_ids = session.get('cinema_demo_ids')
        cid = (cinema_demo_ids or {}).get('creatorUserId')
        if cid is not None and u.id == int(cid) or (u.username or '').lower() in ('creator', 'demo_creator'):
            demo_profile_override = {
                'display_name': 'creator',
                'username': 'creator',
                'public_numeric_id': '777',
                'about_me': (
                    'Инноватор в сфере EdTech и практикующий IT-наставник.\n'
                    'Специалист, который не просто учит коду, а создает среду для его изучения.\n'
                    'Путь от репетитора до разработчика собственной платформы позволил автоматизировать рутину и сфокусироваться на главном — прогрессе ученика.\n'
                    'В обучении информатике и математике делает ставку на алгоритмическое мышление и использование современных инструментов разработки, подготавливая студентов к реальным вызовам цифрового мира.'
                ),
                'custom_status': 'слеп, но не глуп',
                'telegram_link': '@eohada',
                'created_at_display': '05.12.2025',
                'avatar_url': current_app.config.get('DEMO_CREATOR_AVATAR_URL') or url_for('static', filename='images/demo_creator_avatar.jpg'),
                'creator_cover_url': current_app.config.get('DEMO_CREATOR_COVER_URL') or url_for('static', filename='images/demo_creator_cover.png'),
            }
    tutor_subjects = []
    active_students_count = None
    if u.is_tutor():
        from app.models import Enrollment
        subjects = [row[0] for row in db.session.query(Enrollment.subject).filter_by(tutor_id=u.id, status='active').distinct().all()]
        subject_map = {
            'ege_informatics': 'ЕГЭ Информатика',
            'oge_informatics': 'ОГЭ Информатика',
            'informatics': 'Информатика',
            'math': 'Математика',
            'physics': 'Физика',
        }
        tutor_subjects = [subject_map.get(s.lower().strip(), s) for s in subjects if s]
        active_students_count = db.session.query(Enrollment.student_id).filter_by(tutor_id=u.id, status='active').distinct().count()

    return redirect(url_for('main.universal_profile_view', user_id=u.id))

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
                
                unique_filename = f"avatar_{current_user.id}{ext}"
                avatar_upload_root = current_app.config.get('AVATAR_UPLOAD_ROOT')
                if avatar_upload_root:
                    upload_folder = os.path.abspath(avatar_upload_root)
                    avatar_url = f"/avatars/{unique_filename}"
                else:
                    app_root = os.path.dirname(current_app.root_path)
                    upload_folder = os.path.abspath(os.path.join(app_root, 'uploads', 'avatars'))
                    avatar_url = f"/avatars/{unique_filename}"
                
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
        if 'cover_file' in request.files:
            file = request.files['cover_file']
            if file and file.filename:
                allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
                filename = secure_filename(file.filename)
                ext = os.path.splitext(filename)[1].lower()
                if ext not in allowed_extensions:
                    return jsonify({'success': False, 'error': 'Недопустимый формат. Используйте JPG, PNG, GIF или WEBP'}), 400
                unique_filename = f"cover_{current_user.id}{ext}"
                cover_root = current_app.config.get('COVER_UPLOAD_ROOT')
                if cover_root:
                    upload_folder = os.path.abspath(cover_root)
                    cover_url = f"/covers/{unique_filename}"
                else:
                    app_root = os.path.dirname(current_app.root_path)
                    upload_folder = os.path.abspath(os.path.join(app_root, 'uploads', 'covers'))
                    cover_url = f"/covers/{unique_filename}"
                os.makedirs(upload_folder, exist_ok=True)
                if not os.path.isdir(upload_folder):
                    return jsonify({'success': False, 'error': 'Не удалось создать папку для загрузки'}), 500
                file_path = os.path.join(upload_folder, unique_filename)
                if not os.path.abspath(file_path).startswith(os.path.abspath(upload_folder)):
                    return jsonify({'success': False, 'error': 'Недопустимый путь'}), 400
                file.save(file_path)
                current_user.cover_url = cover_url
                if getattr(current_user, 'profile', None):
                    current_user.profile.cover_url = cover_url
                logger.info(f"Cover uploaded for user {current_user.id}: {cover_url}")

        if 'custom_status' in data:
            current_user.custom_status = data['custom_status'].strip()[:100]
        
        if 'about_me' in data:
            current_user.about_me = data['about_me'].strip()
            
        if 'telegram_link' in data:
            current_user.telegram_link = data['telegram_link'].strip()[:200]

        tz_value = None
        if request.is_json and isinstance(data, dict):
            tz_value = (data.get('creator_tz_iana') or data.get('profile_tz_iana') or data.get('timezone_iana') or '').strip()
        else:
            tz_value = (request.form.get('creator_tz_iana') or request.form.get('profile_tz_iana') or request.form.get('timezone_iana') or '').strip()
        if tz_value:
            current_user.timezone_mode = 'manual'
            current_user.timezone_iana = tz_value[:64]
            prof = getattr(current_user, 'profile', None)
            if prof:
                prof.timezone = tz_value[:50]

        if getattr(current_user, 'is_creator', lambda: False)():
            magic_in_payload = False
            magic_on = False
            if request.is_json and isinstance(data, dict):
                if 'presence_techno_magic_enabled' in data:
                    magic_in_payload = True
                    v = data.get('presence_techno_magic_enabled')
                    if isinstance(v, bool):
                        magic_on = v
                    else:
                        magic_on = str(v).strip().lower() in ('1', 'true', 'yes', 'on')
            elif not request.is_json and 'presence_techno_magic_enabled' in request.form:
                magic_in_payload = True
                magic_on = request.form.get('presence_techno_magic_enabled') == '1'
            if magic_in_payload:
                prof = UserProfile.query.filter_by(user_id=current_user.id).first()
                if not prof:
                    prof = UserProfile(user_id=current_user.id)
                    db.session.add(prof)
                prof.presence_techno_magic_enabled = bool(magic_on)
            
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


import hashlib
from core.db_models import InviteLink, TeacherStudent, TeacherProfile

def _find_invite_link_by_token(token: str) -> InviteLink | None:
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    invite = InviteLink.query.filter_by(token_hash=token_hash).first()
    if not invite:
        invite = InviteLink.query.filter_by(token_hash=token).first()
    return invite


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """Самостоятельная регистрация преподавателя (Teacher/Tutor)"""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    # Редирект старых запросов с кодами инвайтов на новые токен-маршруты, если токен передан в query
    invite_token = request.args.get('token') or request.args.get('code')
    if invite_token:
        inv = _find_invite_link_by_token(invite_token)
        if inv and inv.is_valid:
            if inv.role == 'parent':
                return redirect(url_for('auth.register_parent_invite', token=invite_token))
            elif inv.role == 'student':
                return redirect(url_for('auth.register_student_invite', token=invite_token))

    tutor_id_param = request.args.get('tutor_id', type=int) or request.form.get('tutor_id', type=int)
    invite_parent_to_param = request.args.get('invite_parent_to', type=int) or request.form.get('invite_parent_to', type=int)
    ref_param = (request.args.get('ref', '') or request.form.get('ref', '')).strip()

    tutor = None
    invite_student = None
    if tutor_id_param:
        tutor = User.query.filter_by(id=tutor_id_param).first()
    if invite_parent_to_param:
        invite_student = Student.query.filter_by(user_id=invite_parent_to_param).first()

    if request.method == 'POST':
        full_name = (request.form.get('full_name') or request.form.get('username') or '').strip()
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password')
        password_confirm = request.form.get('password_confirm')
        role = request.form.get('role', 'tutor').strip()

        if not username or not password:
            return render_template('auth/register.html', error='Все обязательные поля должны быть заполнены.',
                                   tutor=tutor, invite_student=invite_student, ref=ref_param,
                                   username=username, email=email, full_name=full_name)

        if password_confirm and password != password_confirm:
            return render_template('auth/register.html', error='Пароли не совпадают.',
                                   tutor=tutor, invite_student=invite_student, ref=ref_param,
                                   username=username, email=email, full_name=full_name)

        if invite_student:
            role = 'parent'
        elif tutor:
            role = 'student'
        elif role not in ('tutor', 'teacher'):
            role = 'tutor'
        else:
            role = 'tutor'

        if User.query.filter_by(username=username).first():
            return render_template('auth/register.html', error='Пользователь с таким логином уже существует.',
                                   tutor=tutor, invite_student=invite_student, ref=ref_param,
                                   username=username, email=email, full_name=full_name)

        if email and User.query.filter_by(email=email).first():
            return render_template('auth/register.html', error='Пользователь с таким email уже существует.',
                                   tutor=tutor, invite_student=invite_student, ref=ref_param,
                                   username=username, email=email, full_name=full_name)

        try:
            from app.utils.referral_service import ReferralCodeError, get_active_referral_code
            referral = get_active_referral_code(ref_param)
        except ReferralCodeError as error:
            return render_template('auth/register.html', error=str(error),
                                   tutor=tutor, invite_student=invite_student, ref=ref_param,
                                   username=username, email=email, full_name=full_name)

        try:
            new_user = User(
                username=username,
                email=email if email else None,
                password_hash=generate_password_hash(password),
                role=role,
                is_active=True
            )
            db.session.add(new_user)
            db.session.flush()

            from app.utils.referral_service import apply_referral_code
            apply_referral_code(new_user, referral)

            db.session.add(UserRole(user_id=new_user.id, role=role))
            profile = UserProfile(user_id=new_user.id, first_name=full_name or username, last_name='')
            db.session.add(profile)

            if role == 'tutor':
                tp = TeacherProfile(user_id=new_user.id)
                db.session.add(tp)
            elif role == 'student':
                student = Student(
                    name=full_name or username,
                    user_id=new_user.id,
                    is_active=True,
                    email=email if email else None,
                    mentor_id=tutor.id if tutor else None
                )
                db.session.add(student)
                db.session.flush()
                if tutor:
                    db.session.add(TeacherStudent(teacher_id=tutor.id, student_id=new_user.id, status='active'))
                    db.session.add(Enrollment(tutor_id=tutor.id, student_id=new_user.id, subject='Информатика', status='active'))

            if invite_student and role == 'parent':
                family_tie = FamilyTie(
                    parent_id=new_user.id,
                    student_id=invite_student.user_id,
                    access_level='full',
                    is_confirmed=True
                )
                db.session.add(family_tie)

            db.session.commit()

            login_user(new_user, remember=True)
            new_user.last_login = moscow_now()
            db.session.commit()

            audit_logger.log(
                action='register',
                entity='User',
                entity_id=new_user.id,
                status='success',
                metadata={'username': username, 'role': role}
            )

            flash('Регистрация прошла успешно! Добро пожаловать!', 'success')
            return redirect(_redirect_after_login(new_user))

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error during registration: {e}", exc_info=True)
            return render_template('auth/register.html', error=f'Ошибка при регистрации: {str(e)}',
                                   tutor=tutor, invite_student=invite_student, ref=ref_param,
                                   username=username, email=email, full_name=full_name)

    return render_template('auth/register.html', tutor=tutor, invite_student=invite_student, ref=ref_param)


@auth_bp.route('/register/student/<token>', methods=['GET', 'POST'])
@auth_bp.route('/invite/student/<token>', methods=['GET', 'POST'])
def register_student_invite(token: str):
    """Регистрация Ученика по токен-ссылке приглашения преподавателя"""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    invite = _find_invite_link_by_token(token)
    if not invite:
        return render_template('auth/register_student_invite.html', error='Приглашение не найдено. Пожалуйста, попросите преподавателя отправить вам новую ссылку.', invite=None), 404

    if not invite.is_valid:
        if invite.used_at:
            return render_template('auth/register_student_invite.html', error='Эта ссылка-приглашение уже была использована.', invite=None), 400
        if invite.revoked_at:
            return render_template('auth/register_student_invite.html', error='Эта ссылка-приглашение была отозвана преподавателем.', invite=None), 400
        return render_template('auth/register_student_invite.html', error='Срок действия ссылки-приглашения истёк. Запросите новую ссылку у преподавателя.', invite=None), 410

    teacher = invite.teacher or invite.created_by

    if request.method == 'POST':
        full_name = (request.form.get('full_name') or request.form.get('username') or '').strip()
        username = (request.form.get('username') or '').strip()
        email = (request.form.get('email') or '').strip()
        password = request.form.get('password')
        password_confirm = request.form.get('password_confirm')

        if not username or not password:
            return render_template('auth/register_student_invite.html', error='Все обязательные поля должны быть заполнены.', invite=invite, teacher=teacher, username=username, email=email, full_name=full_name), 400

        if password_confirm and password != password_confirm:
            return render_template('auth/register_student_invite.html', error='Пароли не совпадают.', invite=invite, teacher=teacher, username=username, email=email, full_name=full_name), 400

        if User.query.filter_by(username=username).first():
            return render_template('auth/register_student_invite.html', error='Пользователь с таким логином уже существует.', invite=invite, teacher=teacher, username=username, email=email, full_name=full_name), 400

        if email and User.query.filter_by(email=email).first():
            return render_template('auth/register_student_invite.html', error='Пользователь с таким email уже существует.', invite=invite, teacher=teacher, username=username, email=email, full_name=full_name), 400

        try:
            new_user = User(
                username=username,
                email=email if email else None,
                password_hash=generate_password_hash(password),
                role='student',
                is_active=True
            )
            db.session.add(new_user)
            db.session.flush()

            db.session.add(UserRole(user_id=new_user.id, role='student'))
            profile = UserProfile(user_id=new_user.id, first_name=full_name or username, last_name='')
            db.session.add(profile)

            teacher_id = teacher.id if teacher else None
            student_profile = Student(
                name=full_name or username,
                user_id=new_user.id,
                is_active=True,
                email=email if email else None,
                mentor_id=teacher_id
            )
            db.session.add(student_profile)
            db.session.flush()

            if teacher_id:
                existing_ts = TeacherStudent.query.filter_by(teacher_id=teacher_id, student_id=new_user.id).first()
                if not existing_ts:
                    ts = TeacherStudent(teacher_id=teacher_id, student_id=new_user.id, status='active')
                    db.session.add(ts)
                enrollment = Enrollment(tutor_id=teacher_id, student_id=new_user.id, subject='Информатика', status='active')
                db.session.add(enrollment)

            invite.mark_used(new_user.id)
            db.session.commit()

            login_user(new_user, remember=True)
            new_user.last_login = moscow_now()
            db.session.commit()

            flash(f'Регистрация прошла успешно! Вы привязаны к преподавателю {teacher.username if teacher else ""}.', 'success')
            return redirect(url_for('main.dashboard'))
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error registering student via invite: {e}", exc_info=True)
            return render_template('auth/register_student_invite.html', error=f'Ошибка при регистрации: {str(e)}', invite=invite, teacher=teacher, username=username, email=email, full_name=full_name), 500

    return render_template('auth/register_student_invite.html', invite=invite, teacher=teacher)


@auth_bp.route('/register/parent/<token>', methods=['GET', 'POST'])
@auth_bp.route('/invite/parent/<token>', methods=['GET', 'POST'])
def register_parent_invite(token: str):
    """Регистрация Родителя по токен-ссылке приглашения"""
    if current_user.is_authenticated:
        return redirect(url_for('parents.parent_dashboard'))

    invite = _find_invite_link_by_token(token)
    if not invite:
        return render_template('auth/register_parent_invite.html', error='Приглашение не найдено. Пожалуйста, попросите преподавателя отправить вам новую ссылку.', invite=None), 404

    if not invite.is_valid:
        if invite.used_at:
            return render_template('auth/register_parent_invite.html', error='Эта ссылка-приглашение уже была использована.', invite=None), 400
        if invite.revoked_at:
            return render_template('auth/register_parent_invite.html', error='Эта ссылка-приглашение была отозвана.', invite=None), 400
        return render_template('auth/register_parent_invite.html', error='Срок действия ссылки-приглашения истёк. Запросите новую ссылку.', invite=None), 410

    target_student = invite.student
    target_student_user = target_student.user if target_student else None

    if request.method == 'POST':
        full_name = (request.form.get('full_name') or request.form.get('username') or '').strip()
        username = (request.form.get('username') or '').strip()
        email = (request.form.get('email') or '').strip()
        password = request.form.get('password')
        password_confirm = request.form.get('password_confirm')

        if not username or not password:
            return render_template('auth/register_parent_invite.html', error='Все обязательные поля должны быть заполнены.', invite=invite, student=target_student, student_user=target_student_user, username=username, email=email, full_name=full_name), 400

        if password_confirm and password != password_confirm:
            return render_template('auth/register_parent_invite.html', error='Пароли не совпадают.', invite=invite, student=target_student, student_user=target_student_user, username=username, email=email, full_name=full_name), 400

        if User.query.filter_by(username=username).first():
            return render_template('auth/register_parent_invite.html', error='Пользователь с таким логином уже существует.', invite=invite, student=target_student, student_user=target_student_user, username=username, email=email, full_name=full_name), 400

        if email and User.query.filter_by(email=email).first():
            return render_template('auth/register_parent_invite.html', error='Пользователь с таким email уже существует.', invite=invite, student=target_student, student_user=target_student_user, username=username, email=email, full_name=full_name), 400

        try:
            new_user = User(
                username=username,
                email=email if email else None,
                password_hash=generate_password_hash(password),
                role='parent',
                is_active=True
            )
            db.session.add(new_user)
            db.session.flush()

            db.session.add(UserRole(user_id=new_user.id, role='parent'))
            profile = UserProfile(user_id=new_user.id, first_name=full_name or username, last_name='')
            db.session.add(profile)

            if target_student_user:
                family_tie = FamilyTie.query.filter_by(parent_id=new_user.id, student_id=target_student_user.id).first()
                if not family_tie:
                    family_tie = FamilyTie(
                        parent_id=new_user.id,
                        student_id=target_student_user.id,
                        access_level='full',
                        is_confirmed=True
                    )
                    db.session.add(family_tie)

            invite.mark_used(new_user.id)
            db.session.commit()

            login_user(new_user, remember=True)
            new_user.last_login = moscow_now()
            db.session.commit()

            flash('Регистрация прошла успешно! Вы подключены к дашборду ученика.', 'success')
            return redirect(url_for('parents.parent_dashboard'))
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error registering parent via invite: {e}", exc_info=True)
            return render_template('auth/register_parent_invite.html', error=f'Ошибка при регистрации: {str(e)}', invite=invite, student=target_student, student_user=target_student_user, username=username, email=email, full_name=full_name), 500

    return render_template('auth/register_parent_invite.html', invite=invite, student=target_student, student_user=target_student_user)


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    import random
    from flask import session, flash, redirect, url_for, request, render_template
    from app.utils.email import send_email
    if request.method == 'POST':
        username_or_email = request.form.get('username_or_email', '').strip()
        user = User.query.filter((User.username == username_or_email) | (User.email == username_or_email)).first()
        if not user:
            flash('Пользователь с таким логином или email не найден.', 'danger')
            return redirect(url_for('auth.forgot_password'))
        
        # Генерируем 6-значный код подтверждения
        code = f"{random.randint(100000, 999999)}"
        session['reset_code'] = code
        session['reset_user_id'] = user.id
        
        # Форматируем красивое HTML письмо
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Восстановление пароля - BooStudy</title>
    <style>
        body {{
            font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
            background-color: #0a0a0c;
            color: #ffffff;
            margin: 0;
            padding: 0;
        }}
        .container {{
            max-width: 600px;
            margin: 0 auto;
            padding: 40px 20px;
        }}
        .card {{
            background-color: #121216;
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 20px;
            padding: 40px;
            text-align: center;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
        }}
        .logo {{
            font-size: 24px;
            font-weight: 800;
            color: #00e0ff;
            margin-bottom: 30px;
            letter-spacing: -0.02em;
        }}
        h1 {{
            font-size: 22px;
            font-weight: 700;
            margin-bottom: 20px;
            color: #ffffff;
        }}
        p {{
            font-size: 15px;
            color: #8a8a93;
            line-height: 1.6;
            margin-bottom: 30px;
        }}
        .code-box {{
            background-color: #1a1a20;
            border: 1px dashed rgba(0, 224, 255, 0.3);
            border-radius: 12px;
            padding: 20px;
            font-size: 32px;
            font-weight: 800;
            letter-spacing: 6px;
            color: #00e0ff;
            display: inline-block;
            margin-bottom: 30px;
        }}
        .footer {{
            margin-top: 40px;
            font-size: 12px;
            color: #4c4c52;
            text-align: center;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <div class="logo">BooStudy</div>
            <h1>Восстановление пароля</h1>
            <p>Привет, {user.username}!<br>Мы получили запрос на сброс пароля для твоего аккаунта. Используй этот код подтверждения на сайте, чтобы задать новый пароль:</p>
            <div class="code-box">{code}</div>
            <p style="margin-bottom: 0; font-size: 13px;">Если ты не отправлял этот запрос, просто проигнорируй это письмо.</p>
        </div>
        <div class="footer">
            © 2026 BooStudy. Все права защищены.
        </div>
    </div>
</body>
</html>"""
        
        text_content = f"Привет, {user.username}! Код сброса пароля: {code}"
        
        # Отправляем email
        email_sent = send_email(user.email or "user@example.com", "Восстановление пароля - BooStudy", html_content, text_content)
        
        # Для простоты локального тестирования пишем в консоль
        print(f"\n[DEV MODE] КОД ВОССТАНОВЛЕНИЯ ПАРОЛЯ ДЛЯ {user.username}: {code}\n")
        
        if email_sent:
            flash(f'[DEV MODE] Код сброса пароля: {code}', 'success')
        else:
            flash(f'[DEV MODE] Код сброса пароля: {code} (SMTP не настроен)', 'warning')
            
        return redirect(url_for('auth.reset_password_confirm'))
        
    return render_template('auth/forgot_password.html')


@auth_bp.route('/reset-password-confirm', methods=['GET', 'POST'])
def reset_password_confirm():
    from flask import session, flash, redirect, url_for, request, render_template
    from werkzeug.security import generate_password_hash
    if request.method == 'POST':
        input_code = request.form.get('reset_code', '').strip()
        new_password = request.form.get('new_password', '').strip()
        
        saved_code = session.get('reset_code')
        user_id = session.get('reset_user_id')
        
        if not saved_code or not user_id or input_code != saved_code:
            flash('Неверный или устаревший код подтверждения.', 'danger')
            return redirect(url_for('auth.reset_password_confirm'))
            
        user = User.query.get(user_id)
        if user:
            user.password_hash = generate_password_hash(new_password)
            db.session.commit()
            
            # Очищаем сессию сброса
            session.pop('reset_code', None)
            session.pop('reset_user_id', None)
            
            flash('Пароль успешно изменен! Войдите с новым паролем.', 'success')
            return redirect(url_for('auth.login'))
        else:
            flash('Пользователь не найден.', 'danger')
            return redirect(url_for('auth.forgot_password'))
            
    return render_template('auth/reset_password_confirm.html')


@auth_bp.route('/debug/last-email')
def debug_last_email():
    import os
    from flask import abort, send_from_directory
    debug_dir = os.path.join(os.getcwd(), 'debug_output')
    if not os.path.exists(os.path.join(debug_dir, 'last_sent_email.html')):
        abort(404, description="No email sent yet.")
    return send_from_directory(debug_dir, 'last_sent_email.html')
