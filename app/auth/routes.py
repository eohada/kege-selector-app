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
from app.models import db, User, UserProfile, UserRole, moscow_now, Student, Tasks, Assignment, AssignmentTask, Submission, Lesson, LessonTask, Course, ReferralCode, ReferralUsage
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
        task_query = Tasks.query.filter(Tasks.answer.isnot(None), Tasks.answer != '')
        if course_id:
            task_query = task_query.filter_by(course_id=course_id)
        for tn in demo_task_numbers:
            candidates = task_query.filter_by(task_number=tn).all()
            chosen = next((c for c in candidates if _no_surname(c)), None) or (candidates[0] if candidates else None)
            if chosen:
                demo_tasks.append(chosen)
        if not demo_tasks:
            demo_tasks = (task_query.limit(5).all() if course_id else Tasks.query.limit(5).all())

    first_task = demo_tasks[0] if demo_tasks else (Tasks.query.filter_by(course_id=course_id).first() if course_id else Tasks.query.first())

    # --- 8 completed lessons with varied LessonTasks for realistic analytics ---
    all_task_pool = (Tasks.query.filter_by(course_id=course_id).limit(30).all() if course_id else Tasks.query.limit(30).all())
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
            task_query = Tasks.query.filter(Tasks.answer.isnot(None), Tasks.answer != '')
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
            trainer_query = Tasks.query.filter(Tasks.answer.isnot(None), Tasks.answer != '')
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
        dest = url_for('main.student_dashboard')
        if cinema_scene == '3':
            dest = url_for('theory.theory_index')
        elif cinema_scene == '4':
            dest = url_for('main.student_dashboard')
        elif cinema_scene == '5' and demo_lesson_id:
            dest = url_for('lessons.lesson_classwork_view', lesson_id=demo_lesson_id) + '?cinema_scene=5'
        elif cinema_scene == '6' and trainer_task:
            dest = url_for('trainer.trainer_v2', task_id=trainer_task.task_id) + '?cinema_scene=6&exam=' + exam
        elif cinema_scene in ('7', '8', '9') and demo_student.student_id:
            dest = url_for('students.student_analytics', student_id=demo_student.student_id) + '?cinema_scene=' + cinema_scene
        if cinema_scene in ('1', '2'):
            dest = dest + ('&' if '?' in dest else '?') + 'cinema_scene=' + cinema_scene
        response = make_response(redirect(dest))
    else:
        dest = url_for('main.student_dashboard') + ('&' if '?' in url_for('main.student_dashboard') else '?') + 'cinema_scene=0'
        response = make_response(redirect(dest))
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

    # Student profile should match the dedicated student profile etalon page.
    if current_user.is_student() and linked_student:
        return redirect(url_for('students.student_profile', student_id=linked_student.student_id))

    if current_user.is_creator():
        return render_template(
            'user_profile_creator.html',
            linked_student=linked_student,
            recent_lessons=recent_lessons,
            lesson_counts=lesson_counts,
        )

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
    return render_template(
        'user_public_profile.html',
        public_user=u,
        public_display_name=(demo_profile_override.get('display_name') if demo_profile_override else None) or display_name or u.username,
        creator_cover_url=demo_profile_override.get('creator_cover_url') if demo_profile_override else creator_cover_url,
        public_numeric_id=(demo_profile_override.get('public_numeric_id') if demo_profile_override else None) or public_numeric_id,
        cinema_demo_ids=cinema_demo_ids,
        demo_profile_override=demo_profile_override,
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
