"""
Основные маршруты приложения
"""
import logging
import json
import shutil
from urllib.parse import urlparse
from flask import render_template, request, send_from_directory, flash, redirect, url_for, make_response, current_app, jsonify
from flask_login import login_required
import os
from datetime import datetime

from app.main import main_bp
from app.models import Student, Lesson, Tasks, UsageHistory, SkippedTasks, BlacklistTasks, db, moscow_now
from app.models import User, UserProfile, Enrollment, FamilyTie, UserConsent, StudentCourseEnrollment
from app.students.forms import normalize_school_class
from app.auth.rbac_utils import get_user_scope, apply_data_scope
from app.utils.release_notes import build_release_notes_text, RELEASE_VERSION
from sqlalchemy import func, or_
from datetime import timedelta
from core.audit_logger import audit_logger
from flask_login import current_user
from app import csrf

base_dir = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def _regular_student_filter():
    return (
        or_(Student.user_id.is_(None), User.id.is_(None), User.is_demo_user.is_(False)),
        or_(Student.user_id.is_(None), User.id.is_(None), User.is_qa_pool.is_(False)),
    )


@main_bp.route('/api/presence/ping', methods=['GET', 'POST'])
@login_required
def presence_ping():
    """Heartbeat для онлайн-статуса. GET — без CSRF (удобно для fetch из base.html)."""
    try:
        page_path = ''
        page_endpoint = ''
        if request.method == 'POST':
            payload = request.get_json(silent=True) or {}
            page_path = (payload.get('path') or '').strip()
            page_endpoint = (payload.get('endpoint') or '').strip()
        if not page_path:
            page_path = (request.args.get('path') or request.headers.get('X-Page-Path') or '').strip()
        # Пустой path или подстановка request.path давали /api/presence/ping → всегда fallback active_teacher.
        if (not page_path) or (not page_path.startswith('/')) or page_path.startswith('/api/'):
            ref = (request.headers.get('Referer') or '').strip()
            if ref:
                try:
                    cand = (urlparse(ref).path or '').strip()
                    if cand.startswith('/') and not cand.startswith('/api/'):
                        page_path = cand
                except Exception:
                    pass
        if not page_path or not page_path.startswith('/'):
            page_path = '/'
        elif page_path.startswith('/api/'):
            page_path = '/'
        if not page_endpoint:
            page_endpoint = (request.args.get('endpoint') or request.headers.get('X-Page-Endpoint') or '').strip()

        from app.utils.hooks import resolve_presence_activity

        now = moscow_now()
        new_key, new_text = resolve_presence_activity(current_user, page_endpoint, page_path)
        current_user.presence_last_seen_at = now
        current_user.presence_activity_key = new_key
        current_user.presence_activity_text = new_text
        current_user.presence_updated_at = now
        db.session.commit()

        try:
            sio = current_app.socketio
            if sio is not None:
                sio.emit(
                    'presence_update',
                    {'user_id': current_user.id, 'online': True, 'activity': new_text},
                    room=f'presence:{current_user.id}',
                    namespace='/presence',
                )
        except Exception:
            pass

        return jsonify({'success': True, 'online': True, 'activity': new_text})
    except Exception:
        db.session.rollback()
        return jsonify({'success': False}), 500


@main_bp.route('/api/presence/user/<int:user_id>', methods=['GET'])
@login_required
def presence_user(user_id):
    """Получить текущий статус присутствия и активность указанного пользователя."""
    import datetime as _dt
    try:
        # filter_by избегает identity-map кэша, гарантирует свежие данные из БД
        user = User.query.filter_by(id=user_id).first()
        if not user:
            return jsonify({'error': 'not_found'}), 404

        online = False
        last_seen_seconds_ago = None
        last_seen_label = ''

        seen = user.presence_last_seen_at
        if seen is not None:
            try:
                # psycopg2 сохраняет tz-aware в TIMESTAMP WITHOUT TIME ZONE как UTC naive.
                # Поэтому сравниваем: datetime.utcnow() vs seen (naive UTC).
                if getattr(seen, 'tzinfo', None) is not None:
                    now_utc = _dt.datetime.now(_dt.timezone.utc)
                    delta_sec = (now_utc - seen.astimezone(_dt.timezone.utc)).total_seconds()
                else:
                    now_utc_naive = _dt.datetime.utcnow()
                    delta_sec = (now_utc_naive - seen).total_seconds()
                delta_sec = max(0.0, delta_sec)
                online = delta_sec <= 120
                last_seen_seconds_ago = int(delta_sec)
                if delta_sec < 60:
                    last_seen_label = 'только что'
                elif delta_sec < 3600:
                    last_seen_label = f'{int(delta_sec) // 60} мин. назад'
                elif delta_sec < 86400:
                    last_seen_label = f'{int(delta_sec) // 3600} ч. назад'
                else:
                    last_seen_label = f'{int(delta_sec) // 86400} д. назад'
            except Exception:
                pass

        activity = user.get_live_activity_text() or ''
        return jsonify({
            'user_id': user_id,
            'online': online,
            'activity': activity,
            'last_seen_seconds_ago': last_seen_seconds_ago,
            'last_seen_label': last_seen_label,
        })
    except Exception:
        return jsonify({'error': 'server_error'}), 500


@main_bp.route('/legal/offer')
def legal_offer():
    return render_template('legal_offer.html')


@main_bp.route('/legal/privacy')
def legal_privacy():
    return render_template('legal_privacy.html')


@main_bp.route('/favicon.ico')
def favicon():
    # Prevent noisy 404s in console. We reuse the existing logo as a favicon.
    return redirect(url_for('static', filename='icons/BooStudyLogo1-Photoroom.png'))


@main_bp.route('/legal/accept', methods=['POST'])
@login_required
def legal_accept():
    """Зафиксировать согласие пользователя с документом (MVP)."""
    doc = (request.form.get('document_key') or '').strip().lower()
    version = (request.form.get('version') or '1').strip()
    if doc not in {'offer', 'privacy'}:
        flash('Некорректный документ.', 'danger')
        return redirect(url_for('main.dashboard'))

    try:
        consent = UserConsent(
            user_id=current_user.id,
            document_key=doc,
            version=version,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
        )
        db.session.add(consent)
        db.session.commit()
    except Exception:
        db.session.rollback()

    flash('Согласие сохранено.', 'success')
    return redirect(url_for('main.dashboard'))

@main_bp.route('/health')
def health_check():
    """
    Простейший endpoint для проверки работоспособности приложения
    Не требует авторизации и не использует БД
    """
    try:
        from flask import jsonify
        return jsonify({
            'status': 'OK',
            'message': 'Application is running',
            'environment': os.environ.get('ENVIRONMENT', 'unknown'),
            'database_url_set': 'YES' if os.environ.get('DATABASE_URL') else 'NO',
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        from flask import jsonify
        return jsonify({
            'status': 'ERROR',
            'error': str(e)
        }), 200


@main_bp.route('/parent/dashboard')
@main_bp.route('/parent/parent/dashboard')
@login_required
def parent_dashboard_alias():
    """
    Alias для родительского дашборда (исторические/короткие URL).
    Канонический роут живёт в blueprint `parents` (с url_prefix '/parents').
    """
    return redirect(url_for('parents.parent_dashboard', **request.args.to_dict(flat=True)))

@main_bp.route('/setup/first-user', methods=['GET', 'POST'])
@csrf.exempt  # Отключаем CSRF для этого endpoint (работает только если в БД нет пользователей)
def setup_first_user():
    """
    Временный endpoint для создания первого пользователя в пустой базе
    Работает только если в базе нет пользователей (для безопасности)
    После создания первого пользователя этот endpoint автоматически отключается
    """
    from flask import jsonify, request
    from werkzeug.security import generate_password_hash
    from core.db_models import moscow_now
    
    try:
        try:
            user_count = User.query.count()
        except Exception as db_error:
            return jsonify({
                'success': False,
                'error': f'Database connection failed: {str(db_error)}',
                'hint': 'Check DATABASE_URL configuration in environment variables'
            }), 500
        
        if user_count > 0:
            return jsonify({
                'success': False,
                'error': 'Users already exist. This endpoint is disabled for security.',
                'user_count': user_count
            }), 403
        
        if request.method == 'GET':
            return jsonify({
                'message': 'Create first user',
                'method': 'POST',
                'fields': {
                    'username': 'string (required)',
                    'password': 'string (required)',
                    'role': 'string (optional, default: creator)'
                },
                'example': {
                    'username': 'admin',
                    'password': 'your_secure_password',
                    'role': 'creator'
                }
            }), 200
        
        data = request.get_json() if request.is_json else request.form
        
        username = data.get('username', '').strip()
        password = data.get('password', '')
        role = data.get('role', 'creator').strip()
        if not username:
            return jsonify({'success': False, 'error': 'Username is required'}), 400
        
        if not password:
            return jsonify({'success': False, 'error': 'Password is required'}), 400
        
        if len(password) < 8:
            return jsonify({'success': False, 'error': 'Password must be at least 8 characters'}), 400
        
        try:
            if User.query.filter_by(username=username).first():
                return jsonify({'success': False, 'error': 'Username already exists'}), 409
        except Exception as db_error:
            return jsonify({
                'success': False,
                'error': f'Database query failed: {str(db_error)}',
                'hint': 'Check DATABASE_URL configuration'
            }), 500
        
        try:
            user = User(
                username=username,
                email=None,
                password_hash=generate_password_hash(password),
                role=role,
                is_active=True,
                created_at=moscow_now()
            )
            db.session.add(user)
            db.session.commit()
        except Exception as db_error:
            db.session.rollback()
            return jsonify({
                'success': False,
                'error': f'Failed to create user: {str(db_error)}',
                'hint': 'Check database connection and permissions'
            }), 500
        
        return jsonify({
            'success': True,
            'message': f'User "{username}" created successfully',
            'username': username,
            'role': role,
            'note': 'You can now login with these credentials. This endpoint is now disabled.'
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating first user: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@main_bp.route('/')
@main_bp.route('/landing')
def landing():
    """Гостевая страница (landing page) - доступна без авторизации"""
    is_admin_env = os.environ.get('ENVIRONMENT') == 'admin' or (request.host or '').split(':')[0].lower().startswith('admin.')
    if is_admin_env:
        return redirect(url_for('remote_admin.dashboard'))
    # На демо-сайте или при заходе на демо-хост — сразу страница выбора экзамена
    is_demo = current_app.config.get('DEMO_SITE')
    if not is_demo and current_app.config.get('DEMO_HOST'):
        req_host = (request.host or '').split(':')[0].lower()
        is_demo = req_host == current_app.config.get('DEMO_HOST')
    if is_demo:
        return render_template('demo_choose.html')
    return render_template('landing.html')


@main_bp.route('/index')
@main_bp.route('/home')
def index():
    """Главная страница с описанием платформы"""
    is_admin_env = os.environ.get('ENVIRONMENT') == 'admin' or (request.host or '').split(':')[0].lower().startswith('admin.')
    if is_admin_env:
        return redirect(url_for('remote_admin.dashboard'))

    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return render_template('index.html')

@main_bp.route('/dashboard')
@login_required
def dashboard():
    """Главная страница (dashboard) со списком студентов"""
    if current_user.is_parent():
        return redirect(url_for('parents.parent_dashboard'))
    
    if current_user.is_student():
        return redirect(url_for('main.student_dashboard'))
    
    if current_user.is_designer():
        pass  # Продолжаем выполнение, покажем пустой dashboard
    elif current_user.role == 'tester' and not current_user.is_chief_tester():
        pass  # Продолжаем выполнение, покажем пустой dashboard
    
    search_query = request.args.get('search', '').strip()
    category_filter = request.args.get('category', '')
    show_archive = request.args.get('show_archive', 'false').lower() == 'true'  # Параметр для просмотра архива
    student_scope = (request.args.get('student_scope') or 'regular').strip().lower()
    if student_scope not in {'regular', 'test', 'demo'}:
        student_scope = 'regular'

    if show_archive:
        query = Student.query.options(db.joinedload(Student.user)).outerjoin(User, Student.user_id == User.id).filter(Student.is_active == False)
    else:
        query = Student.query.options(db.joinedload(Student.user)).outerjoin(User, Student.user_id == User.id).filter(Student.is_active == True)

    if student_scope == 'test':
        query = query.filter(User.is_qa_pool.is_(True))
    elif student_scope == 'demo':
        query = query.filter(User.is_demo_user.is_(True))
    else:
        query = query.filter(*_regular_student_filter())
    
    scope = get_user_scope(current_user)
    if not scope['can_see_all'] and scope['student_ids']:
        accessible_students = Student.query.filter(Student.user_id.in_(scope['student_ids'])).all()
        if accessible_students:
            accessible_student_ids = [s.student_id for s in accessible_students]
            query = query.filter(Student.student_id.in_(accessible_student_ids))
        else:
            query = query.filter(False)
    elif not scope['can_see_all'] and not scope['student_ids']:
        query = query.filter(False)

    if search_query:
        search_pattern = f'%{search_query}%'
        filters = [
            Student.name.ilike(search_pattern)
        ]
        
        if search_query.startswith('#'):
            platform_id_query = search_query[1:].strip()
            if platform_id_query:
                filters.append(Student.platform_id.ilike(f'%{platform_id_query}%'))
        else:
            filters.append(Student.platform_id.ilike(search_pattern))
            try:
                student_id_num = int(search_query)
                if current_user.id != student_id_num:
                    filters.append(Student.student_id == student_id_num)
            except ValueError:
                pass
        
        query = query.filter(or_(*filters))

    if category_filter and student_scope == 'regular':
        query = query.filter(Student.category == category_filter)

    page = request.args.get('page', 1, type=int)
    per_page = 20
    pagination = query.order_by(Student.name).paginate(page=page, per_page=per_page, error_out=False)
    students = pagination.items
    student_tg_status = {}
    student_user_ids = [s.user_id for s in students if getattr(s, 'user_id', None)]
    if student_user_ids:
        profiles = UserProfile.query.filter(UserProfile.user_id.in_(student_user_ids)).all()
        by_user_id = {p.user_id: p for p in profiles}
        for student in students:
            profile = by_user_id.get(student.user_id)
            if not profile:
                student_tg_status[student.student_id] = {'state': 'none', 'label': 'TG нет'}
            elif profile.telegram_chat_id:
                student_tg_status[student.student_id] = {
                    'state': 'linked',
                    'label': profile.telegram_id or 'TG привязан',
                }
            elif profile.telegram_id:
                student_tg_status[student.student_id] = {
                    'state': 'pending',
                    'label': f'{profile.telegram_id} без бота',
                }
            else:
                student_tg_status[student.student_id] = {'state': 'none', 'label': 'TG нет'}

    base_is_active = not show_archive
    
    count_query = Student.query.outerjoin(User, Student.user_id == User.id).filter(Student.is_active == base_is_active)
    if student_scope == 'test':
        count_query = count_query.filter(User.is_qa_pool.is_(True))
    elif student_scope == 'demo':
        count_query = count_query.filter(User.is_demo_user.is_(True))
    elif student_scope == 'regular':
        count_query = count_query.filter(*_regular_student_filter())
    if not scope['can_see_all'] and scope['student_ids']:
        count_query = count_query.filter(Student.user_id.in_(scope['student_ids']))
    elif not scope['can_see_all']:
        count_query = count_query.filter(False)

    try:
        total_students = count_query.count()
    except Exception as e:
        logger.warning(f"Error counting total students: {e}")
        total_students = 0

    # Tab counters must stay global for the selected scope, regardless of
    # which category tab is currently active.
    try:
        category_stats_query = db.session.query(
            Student.category,
            func.count(Student.student_id).label('count')
        ).outerjoin(User, Student.user_id == User.id).filter(Student.is_active == base_is_active)

        if student_scope == 'test':
            category_stats_query = category_stats_query.filter(User.is_qa_pool.is_(True))
        elif student_scope == 'demo':
            category_stats_query = category_stats_query.filter(User.is_demo_user.is_(True))
        elif student_scope == 'regular':
            category_stats_query = category_stats_query.filter(*_regular_student_filter())

        if not scope['can_see_all'] and scope['student_ids']:
            category_stats_query = category_stats_query.filter(Student.user_id.in_(scope['student_ids']))
        elif not scope['can_see_all']:
            category_stats_query = category_stats_query.filter(False)

        category_stats = category_stats_query.group_by(Student.category).all()
        category_dict = {cat[0]: cat[1] for cat in category_stats if cat[0]}
        ege_students = category_dict.get('ЕГЭ', 0)
        oge_students = category_dict.get('ОГЭ', 0)
        levelup_students = category_dict.get('ЛЕВЕЛАП', 0)
        programming_students = category_dict.get('ПРОГРАММИРОВАНИЕ', 0)
    except Exception as e:
        logger.warning(f"Error getting category statistics: {e}")
        ege_students = 0
        oge_students = 0
        levelup_students = 0
        programming_students = 0
    
    try:
        lesson_query = db.session.query(
            Lesson.status,
            func.count(Lesson.lesson_id).label('count')
        )
        
        if not scope['can_see_all'] and scope['student_ids']:
            accessible_students = Student.query.filter(Student.user_id.in_(scope['student_ids'])).all()
            accessible_student_ids = [s.student_id for s in accessible_students]
            lesson_query = lesson_query.filter(Lesson.student_id.in_(accessible_student_ids))
        elif not scope['can_see_all']:
            accessible_student_ids = []
        else:
            accessible_student_ids = None
        
        lesson_stats = lesson_query.group_by(Lesson.status).all()
        
        lesson_stats_dict = {stat[0]: stat[1] for stat in lesson_stats}
        total_lessons = sum(lesson_stats_dict.values())
        completed_lessons = lesson_stats_dict.get('completed', 0)
        planned_lessons = lesson_stats_dict.get('planned', 0)
        in_progress_lessons = lesson_stats_dict.get('in_progress', 0)
        cancelled_lessons = lesson_stats_dict.get('cancelled', 0)
    except Exception as e:
        logger.warning(f"Error getting lesson statistics: {e}")
        accessible_student_ids = []
        total_lessons = 0
        completed_lessons = 0
        planned_lessons = 0
        in_progress_lessons = 0
        cancelled_lessons = 0
    
    try:
        archived_students_count = (
            Student.query.outerjoin(User, Student.user_id == User.id)
            .filter(Student.is_active == False)
            .filter(*_regular_student_filter())
            .count()
        )
    except Exception as e:
        logger.warning(f"Error counting archived students: {e}")
        archived_students_count = 0

    try:
        regular_students_count = (
            Student.query.outerjoin(User, Student.user_id == User.id)
            .filter(Student.is_active == True)
            .filter(*_regular_student_filter())
            .count()
        )
        test_students_count = (
            Student.query.join(User, Student.user_id == User.id)
            .filter(Student.is_active == True, User.is_qa_pool.is_(True))
            .count()
        )
        demo_students_count = (
            Student.query.join(User, Student.user_id == User.id)
            .filter(Student.is_active == True, User.is_demo_user.is_(True))
            .count()
        )
    except Exception as e:
        logger.warning(f"Error counting student scopes: {e}")
        regular_students_count = total_students if student_scope == 'regular' else 0
        test_students_count = total_students if student_scope == 'test' else 0
        demo_students_count = total_students if student_scope == 'demo' else 0
    
    try:
        if current_user.is_student() or current_user.is_parent() or current_user.is_designer() or (current_user.role == 'tester' and not current_user.is_chief_tester()):
            total_tasks = 0
            accepted_tasks_count = 0
            skipped_tasks_count = 0
            blacklisted_tasks_count = 0
        else:
            total_tasks = Tasks.query.count()
            accepted_tasks_count = db.session.query(func.count(func.distinct(UsageHistory.task_fk))).scalar() or 0
            skipped_tasks_count = db.session.query(func.count(func.distinct(SkippedTasks.task_fk))).scalar() or 0
            blacklisted_tasks_count = db.session.query(func.count(func.distinct(BlacklistTasks.task_fk))).scalar() or 0
    except Exception as e:
        logger.warning(f"Error getting task statistics: {e}")
        total_tasks = 0
        accepted_tasks_count = 0
        skipped_tasks_count = 0
        blacklisted_tasks_count = 0
    
    try:
        now = moscow_now()
        week_ago = now - timedelta(days=7)
        prev_week_start = now - timedelta(days=14)
        
        recent_completed_query = Lesson.query.filter(
            Lesson.status == 'completed',
            Lesson.lesson_date >= week_ago,
            Lesson.lesson_date <= now
        )
        if accessible_student_ids is not None:
            recent_completed_query = recent_completed_query.filter(Lesson.student_id.in_(accessible_student_ids))
        recent_completed = recent_completed_query.count()
        
        week_ahead = now + timedelta(days=7)
        recent_planned_query = Lesson.query.filter(
            Lesson.status.in_(['planned', 'in_progress']),
            Lesson.lesson_date >= now,
            Lesson.lesson_date <= week_ahead
        )
        if accessible_student_ids is not None:
            recent_planned_query = recent_planned_query.filter(Lesson.student_id.in_(accessible_student_ids))
        recent_planned = recent_planned_query.count()
        
        recent_lessons = recent_completed + recent_planned
        
        homework_query = Lesson.query.filter(
            Lesson.status == 'completed',
            Lesson.lesson_date >= week_ago,
            Lesson.lesson_date <= now,
            Lesson.homework_status.in_(['assigned_done', 'assigned_not_done'])
        )
        if accessible_student_ids is not None:
            homework_query = homework_query.filter(Lesson.student_id.in_(accessible_student_ids))
        lessons_with_homework = homework_query.count()
    except Exception as e:
        logger.warning(f"Error getting recent lessons statistics: {e}")
        recent_lessons = 0
        lessons_with_homework = 0

    # ── Deltas for dashboard KPIs (match mock “+N”) ──
    students_delta_30d = 0
    completed_lessons_delta_7d = 0
    try:
        # Students growth: created in last 30 days minus previous 30 days.
        qs_students = Student.query
        if base_is_active is not None:
            qs_students = qs_students.filter(Student.is_active == base_is_active)
        qs_students = qs_students.outerjoin(User, Student.user_id == User.id)
        if student_scope == 'test':
            qs_students = qs_students.filter(User.is_qa_pool.is_(True))
        elif student_scope == 'demo':
            qs_students = qs_students.filter(User.is_demo_user.is_(True))
        else:
            qs_students = qs_students.filter(*_regular_student_filter())
        if not scope.get('can_see_all') and scope.get('student_ids'):
            qs_students = qs_students.filter(Student.user_id.in_(scope['student_ids']))
        elif not scope.get('can_see_all'):
            qs_students = qs_students.filter(False)

        month_ago = now - timedelta(days=30)
        prev_month_start = now - timedelta(days=60)
        students_last_30 = qs_students.filter(Student.created_at >= month_ago, Student.created_at <= now).count()
        students_prev_30 = qs_students.filter(Student.created_at >= prev_month_start, Student.created_at < month_ago).count()
        students_delta_30d = max(0, int(students_last_30) - int(students_prev_30))
    except Exception as e:
        logger.warning(f"Error building students delta: {e}")
        students_delta_30d = 0

    try:
        # Completed lessons growth: completed in last 7 days minus previous 7 days.
        q_completed = Lesson.query.filter(Lesson.status == 'completed')
        if accessible_student_ids is not None:
            q_completed = q_completed.filter(Lesson.student_id.in_(accessible_student_ids))
        completed_last_7 = q_completed.filter(Lesson.lesson_date >= week_ago, Lesson.lesson_date <= now).count()
        completed_prev_7 = q_completed.filter(Lesson.lesson_date >= prev_week_start, Lesson.lesson_date < week_ago).count()
        completed_lessons_delta_7d = max(0, int(completed_last_7) - int(completed_prev_7))
    except Exception as e:
        logger.warning(f"Error building completed lessons delta: {e}")
        completed_lessons_delta_7d = 0

    review_lesson_tasks_count = 0
    review_submissions_count = 0
    groups_count = 0
    try:
        from app.models import LessonTask, Submission, Assignment, SchoolGroup

        accessible_ids = None
        if not scope.get('can_see_all'):
            accessible_ids = []
            try:
                user_ids = scope.get('student_ids') or []
                if user_ids:
                    st = Student.query.filter(Student.user_id.in_(user_ids)).all()
                    accessible_ids = [s.student_id for s in st if s]
            except Exception:
                accessible_ids = []

        qlt = LessonTask.query.join(Lesson, Lesson.lesson_id == LessonTask.lesson_id).filter(LessonTask.status == 'submitted')
        if accessible_ids is not None:
            if not accessible_ids:
                qlt = qlt.filter(False)
            else:
                qlt = qlt.filter(Lesson.student_id.in_(accessible_ids))
        review_lesson_tasks_count = qlt.count()

        qs = Submission.query.join(Assignment, Assignment.assignment_id == Submission.assignment_id).filter(Submission.status.in_(['SUBMITTED', 'NEEDS_MANUAL_REVIEW']))
        if not scope.get('can_see_all'):
            qs = qs.filter(Assignment.created_by_id == current_user.id)
        if accessible_ids is not None:
            if not accessible_ids:
                qs = qs.filter(False)
            else:
                qs = qs.filter(Submission.student_id.in_(accessible_ids))
        review_submissions_count = qs.count()

        qg = SchoolGroup.query
        if not scope.get('can_see_all'):
            qg = qg.filter(SchoolGroup.owner_user_id == current_user.id)
        groups_count = qg.count()
    except Exception as e:
        logger.warning(f"Failed to build teacher overview counters: {e}")

    my_tutors = []
    if getattr(current_user, 'is_student', None) and current_user.is_student():
        try:
            enrollments = Enrollment.query.filter_by(student_id=current_user.id).options(
                db.joinedload(Enrollment.tutor)
            ).all()
            my_tutors = [e.tutor for e in enrollments if getattr(e, 'tutor', None)]
        except Exception:
            pass

    return render_template('dashboard.html',
                         release_notes=build_release_notes_text(),
                         release_version=RELEASE_VERSION,
                         students=students,
                         student_tg_status=student_tg_status,
                         pagination=pagination,
                         search_query=search_query,
                         category_filter=category_filter,
                         show_archive=show_archive,
                         student_scope=student_scope,
                         my_tutors=my_tutors,
                         total_students=total_students,
                         regular_students_count=regular_students_count,
                         test_students_count=test_students_count,
                         demo_students_count=demo_students_count,
                         students_delta_30d=students_delta_30d,
                         total_lessons=total_lessons,
                         completed_lessons=completed_lessons,
                         completed_lessons_delta_7d=completed_lessons_delta_7d,
                         planned_lessons=planned_lessons,
                         in_progress_lessons=in_progress_lessons,
                         cancelled_lessons=cancelled_lessons,
                         ege_students=ege_students,
                         oge_students=oge_students,
                         levelup_students=levelup_students,
                         programming_students=programming_students,
                         archived_students_count=archived_students_count,
                         total_tasks=total_tasks,
                         accepted_tasks_count=accepted_tasks_count,
                         skipped_tasks_count=skipped_tasks_count,
                         blacklisted_tasks_count=blacklisted_tasks_count,
                         lessons_with_homework=lessons_with_homework,
                         recent_lessons=recent_lessons,
                         review_lesson_tasks_count=review_lesson_tasks_count,
                         review_submissions_count=review_submissions_count,
                         groups_count=groups_count)


@main_bp.route('/student/dashboard')
@login_required
def student_dashboard():
    """Дашборд ученика: план, задания, риски по темам."""
    if not current_user.is_student():
        return redirect(url_for('main.dashboard'))

    student = Student.query.filter_by(user_id=current_user.id).first()
    if not student:
        candidate = Student.query.get(current_user.id)
        if candidate and candidate.user_id is None and candidate.student_id == current_user.id:
            student = candidate

    if not student:
        flash('Профиль ученика не найден.', 'warning')
        return render_template(
            'student_dashboard.html',
            release_notes=build_release_notes_text(),
            release_version=RELEASE_VERSION,
            student=None,
            plan_items=[],
            pending_submissions=[],
            unread_notifications=0,
            problem_topics=[],
            enrollments=[],
            selected_course_id=None,
        )

    from app.students.stats_service import StatsService
    from app.models import StudentLearningPlanItem, Submission, UserNotification, GradebookEntry, Assignment, Lesson

    enrollments = []
    try:
        enrollments = StudentCourseEnrollment.query.filter_by(
            student_id=student.student_id, is_active=True
        ).options(db.joinedload(StudentCourseEnrollment.course)).order_by(
            StudentCourseEnrollment.enrolled_at.asc()
        ).all()
    except Exception:
        pass

    selected_course_id = request.args.get('course_id', type=int)
    if not selected_course_id and enrollments:
        selected_course_id = enrollments[0].course_id

    try:
        plan_items = StudentLearningPlanItem.query.filter_by(student_id=student.student_id).order_by(
            StudentLearningPlanItem.due_date.asc().nullslast(),
            StudentLearningPlanItem.priority.desc(),
            StudentLearningPlanItem.item_id.desc(),
        ).limit(12).all()
    except Exception:
        plan_items = []

    completion_pct = 0
    try:
        total_cnt = StudentLearningPlanItem.query.filter_by(student_id=student.student_id).count()
        if total_cnt > 0:
            done_cnt = StudentLearningPlanItem.query.filter_by(student_id=student.student_id, status='done').count()
            completion_pct = int(round((done_cnt / total_cnt) * 100))
    except Exception:
        completion_pct = 0

    try:
        sub_query = Submission.query.join(
            Assignment, Submission.assignment_id == Assignment.assignment_id
        ).filter(
            Submission.student_id == student.student_id,
            Submission.status.in_(['ASSIGNED', 'IN_PROGRESS', 'RETURNED']),
            Assignment.is_active == True,  # noqa: E712  скрываем архивные
        ).options(db.contains_eager(Submission.assignment))
        if selected_course_id:
            sub_query = sub_query.filter(
                db.or_(Assignment.exam_course_id == selected_course_id, Assignment.exam_course_id.is_(None))
            )
        pending_submissions = sub_query.order_by(Submission.assigned_at.desc()).limit(12).all()
    except Exception:
        pending_submissions = []

    try:
        unread_notifications = UserNotification.query.filter_by(user_id=current_user.id, is_read=False).count()
    except Exception:
        unread_notifications = 0

    problem_topics = []
    try:
        stats = StatsService(student.student_id)
        problem_topics = stats.get_problem_topics(threshold=60)[:6]
    except Exception:
        problem_topics = []

    if current_user.is_demo_user and not problem_topics:
        problem_topics = [
            {'id': 0, 'name': 'Системы счисления', 'avg_score': 42},
            {'id': 0, 'name': 'Рекурсия и динамическое программирование', 'avg_score': 35},
            {'id': 0, 'name': 'Теория игр', 'avg_score': 48},
            {'id': 0, 'name': 'Графы и обход деревьев', 'avg_score': 55},
        ]

    try:
        # Исключаем записи журнала, связанные с архивными заданиями
        recent_grades = (
            GradebookEntry.query
            .outerjoin(Submission, GradebookEntry.submission_id == Submission.submission_id)
            .outerjoin(Assignment, Submission.assignment_id == Assignment.assignment_id)
            .filter(
                GradebookEntry.student_id == student.student_id,
                db.or_(
                    GradebookEntry.submission_id.is_(None),  # ручные записи — всегда показываем
                    Assignment.is_active == True,  # noqa: E712
                )
            )
            .order_by(GradebookEntry.created_at.desc(), GradebookEntry.entry_id.desc())
            .limit(8).all()
        )
    except Exception:
        recent_grades = []

    total_lessons = None
    try:
        total_lessons = Lesson.query.filter_by(student_id=student.student_id).count()
    except Exception:
        total_lessons = None

    completed_tasks = 0
    try:
        completed_tasks = Submission.query.join(
            Assignment, Submission.assignment_id == Assignment.assignment_id
        ).filter(
            Submission.student_id == student.student_id,
            Submission.status.in_(['GRADED']),
            Assignment.is_active == True,  # noqa: E712  скрываем архивные
        ).count()
    except Exception:
        completed_tasks = 0

    avg_score = '—'
    try:
        rows = (
            GradebookEntry.query
            .outerjoin(Submission, GradebookEntry.submission_id == Submission.submission_id)
            .outerjoin(Assignment, Submission.assignment_id == Assignment.assignment_id)
            .filter(
                GradebookEntry.student_id == student.student_id,
                GradebookEntry.score.isnot(None),
                GradebookEntry.max_score.isnot(None),
                GradebookEntry.max_score > 0,
                db.or_(
                    GradebookEntry.submission_id.is_(None),  # ручные записи — всегда учитываем
                    Assignment.is_active == True,  # noqa: E712  скрываем архивные
                )
            )
            .order_by(GradebookEntry.created_at.desc(), GradebookEntry.entry_id.desc())
            .limit(30)
            .all()
        )
        if rows:
            pct_vals = [(float(r.score) / float(r.max_score)) * 100.0 for r in rows if r.score is not None and r.max_score]
            if pct_vals:
                avg_score = str(int(round(sum(pct_vals) / len(pct_vals))))
    except Exception:
        avg_score = '—'

    return render_template(
        'student_dashboard.html',
        release_notes=build_release_notes_text(),
        release_version=RELEASE_VERSION,
        student=student,
        plan_items=plan_items,
        pending_submissions=pending_submissions,
        unread_notifications=unread_notifications,
        problem_topics=problem_topics,
        recent_grades=recent_grades,
        enrollments=enrollments,
        selected_course_id=selected_course_id,
        completion_pct=completion_pct,
        total_lessons=total_lessons,
        completed_tasks=completed_tasks,
        avg_score=avg_score,
    )

@main_bp.route('/font/<path:filename>')
def font_files(filename):
    """Сервим шрифты из папки static/font"""
    font_dir = os.path.join(base_dir, 'static', 'font')
    return send_from_directory(font_dir, filename, mimetype='font/otf' if filename.endswith('.otf') else 'font/ttf')

HOMEWORK_STATUS_VALUES = {'assigned_done', 'assigned_not_done', 'not_assigned'}
LEGACY_HOMEWORK_STATUS_MAP = {
    'completed': 'assigned_done',
    'pending': 'assigned_not_done',
    'not_done': 'assigned_not_done',
    'not_assigned': 'not_assigned'
}

def normalize_homework_status_value(raw_status):
    """Преобразует устаревшие статусы к актуальным"""
    if raw_status is None:
        return 'not_assigned'
    if isinstance(raw_status, str):
        normalized = raw_status.strip()
    else:
        normalized = raw_status
    normalized = LEGACY_HOMEWORK_STATUS_MAP.get(normalized, normalized)
    return normalized if normalized in HOMEWORK_STATUS_VALUES else 'not_assigned'

logger = logging.getLogger(__name__)

@main_bp.route('/export-data')
@login_required
def export_data():
    """Экспорт данных в JSON"""
    if not (current_user.is_admin() or current_user.is_creator()):
        flash('Доступ запрещен. Экспорт доступен только администратору/создателю.', 'danger')
        return redirect(url_for('main.dashboard'))
    try:
        logger.info('Начало экспорта данных')
        export_data_dict = {
            'students': [{
                'name': s.name,
                'platform_id': s.platform_id,
                'category': s.category,
                'target_score': s.target_score,
                'deadline': s.deadline,
                'diagnostic_level': s.diagnostic_level,
                'description': s.description,
                'notes': s.notes,
                'strengths': s.strengths,
                'weaknesses': s.weaknesses,
                'preferences': s.preferences,
                'overall_rating': s.overall_rating,
                'school_class': s.school_class,
                'goal_text': s.goal_text,
                'programming_language': s.programming_language
            } for s in Student.query.filter_by(is_active=True).all()],
            'lessons': [{
                'student_id': l.student_id,
                'lesson_type': l.lesson_type,
                'lesson_date': l.lesson_date.isoformat() if l.lesson_date else None,
                'duration': l.duration,
                'status': l.status,
                'topic': l.topic,
                'notes': l.notes,
                'homework': l.homework,
                'homework_status': l.homework_status,
                'homework_result_percent': l.homework_result_percent,
                'homework_result_notes': l.homework_result_notes
            } for l in Lesson.query.all()]
        }
        response = make_response(json.dumps(export_data_dict, ensure_ascii=False, indent=2))
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        response.headers['Content-Disposition'] = f'attachment; filename=export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        logger.info(f'Экспорт завершен: {len(export_data_dict["students"])} учеников, {len(export_data_dict["lessons"])} уроков')
        
        audit_logger.log(
            action='export_data',
            entity='Data',
            entity_id=None,
            status='success',
            metadata={
                'students_count': len(export_data_dict["students"]),
                'lessons_count': len(export_data_dict["lessons"])
            }
        )
        
        return response
    except Exception as e:
        logger.error(f'Ошибка при экспорте данных: {e}')
        audit_logger.log_error(
            action='export_data',
            entity='Data',
            error=str(e)
        )
        flash(f'Ошибка при экспорте данных: {str(e)}', 'error')
        return redirect(url_for('main.dashboard'))

@main_bp.route('/import-data', methods=['GET', 'POST'])
@login_required
def import_data():
    """Импорт данных из JSON"""
    if not (current_user.is_admin() or current_user.is_creator()):
        flash('Доступ запрещен. Импорт доступен только администратору/создателю.', 'danger')
        return redirect(url_for('main.dashboard'))
    if request.method == 'GET':
        return render_template('import_data.html')
    try:
        if 'file' not in request.files:
            flash('Файл не выбран', 'error')
            return redirect(url_for('main.import_data'))
        file = request.files['file']
        if file.filename == '':
            flash('Файл не выбран', 'error')
            return redirect(url_for('main.import_data'))
        if not file.filename.endswith('.json'):
            flash('Поддерживаются только JSON файлы', 'error')
            return redirect(url_for('main.import_data'))
        data = json.loads(file.read().decode('utf-8'))
        imported_students = 0
        imported_lessons = 0
        if 'students' in data:
            for student_data in data['students']:
                existing = Student.query.filter_by(
                    name=student_data.get('name'),
                    platform_id=student_data.get('platform_id')
                ).first()
                if not existing:
                    student = Student(
                        name=student_data.get('name'),
                        platform_id=student_data.get('platform_id'),
                        category=student_data.get('category'),
                        target_score=student_data.get('target_score'),
                        deadline=student_data.get('deadline'),
                        diagnostic_level=student_data.get('diagnostic_level'),
                        description=student_data.get('description'),
                        notes=student_data.get('notes'),
                        strengths=student_data.get('strengths'),
                        weaknesses=student_data.get('weaknesses'),
                        preferences=student_data.get('preferences'),
                        overall_rating=student_data.get('overall_rating'),
                        school_class=normalize_school_class(student_data.get('school_class')),
                        goal_text=student_data.get('goal_text'),
                        programming_language=student_data.get('programming_language'),
                        is_active=True
                    )
                    db.session.add(student)
                    imported_students += 1
        if 'lessons' in data:
            for lesson_data in data['lessons']:
                if Student.query.get(lesson_data.get('student_id')):
                    imported_type = lesson_data.get('lesson_type')
                    imported_homework_status = normalize_homework_status_value(lesson_data.get('homework_status'))
                    imported_homework = lesson_data.get('homework')
                    if imported_type == 'introductory':
                        imported_homework = ''
                        imported_homework_status = 'not_assigned'
                    lesson = Lesson(
                        student_id=lesson_data.get('student_id'),
                        lesson_type=imported_type,
                        lesson_date=datetime.fromisoformat(lesson_data['lesson_date']) if lesson_data.get('lesson_date') else moscow_now(),
                        duration=lesson_data.get('duration', 60),
                        status=lesson_data.get('status', 'planned'),
                        topic=lesson_data.get('topic'),
                        notes=lesson_data.get('notes'),
                        homework=imported_homework,
                        homework_status=imported_homework_status,
                        homework_result_percent=lesson_data.get('homework_result_percent'),
                        homework_result_notes=lesson_data.get('homework_result_notes')
                    )
                    db.session.add(lesson)
                    imported_lessons += 1
        db.session.commit()
        logger.info(f'Импорт завершен: {imported_students} учеников, {imported_lessons} уроков')
        
        audit_logger.log(
            action='import_data',
            entity='Data',
            entity_id=None,
            status='success',
            metadata={
                'students_count': imported_students,
                'lessons_count': imported_lessons,
                'filename': file.filename
            }
        )
        
        flash(f'Импорт завершен: добавлено {imported_students} учеников и {imported_lessons} уроков', 'success')
        return redirect(url_for('main.dashboard'))
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при импорте данных: {e}')
        audit_logger.log_error(
            action='import_data',
            entity='Data',
            error=str(e)
        )
        flash(f'Ошибка при импорте данных: {str(e)}', 'error')
        return redirect(url_for('main.import_data'))

@main_bp.route('/backup-db')
@login_required
def backup_db():
    """Создание резервной копии базы данных"""
    if not (current_user.is_admin() or current_user.is_creator()):
        flash('Доступ запрещен. Резервное копирование доступно только администратору/создателю.', 'danger')
        return redirect(url_for('main.dashboard'))
    try:
        logger.info('Попытка создания резервной копии базы данных')
        
        db_url = os.environ.get('DATABASE_URL', '')
        if 'postgresql' in db_url or 'postgres' in db_url:
            flash('Для PostgreSQL резервное копирование должно выполняться через pg_dump или панель хостинга. Используйте экспорт данных для создания резервной копии.', 'info')
            return redirect(url_for('main.export_data'))
        
        backup_dir = os.path.join(base_dir, 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        backup_filename = f'keg_tasks_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'
        backup_path = os.path.join(backup_dir, backup_filename)
        
        db_path = os.path.join(base_dir, 'data', 'keg_tasks.db')
        if os.path.exists(db_path):
            shutil.copy2(db_path, backup_path)
            logger.info(f'Резервная копия создана: {backup_path}')
            
            audit_logger.log(
                action='backup_database',
                entity='Database',
                entity_id=None,
                status='success',
                metadata={
                    'backup_filename': backup_filename,
                    'backup_path': backup_path
                }
            )
            flash(f'Резервная копия создана: {backup_filename}', 'success')
        else:
            flash('Файл базы данных не найден. Используется PostgreSQL.', 'info')
            return redirect(url_for('main.export_data'))
        
        return redirect(url_for('main.dashboard'))
    except Exception as e:
        logger.error(f'Ошибка при создании резервной копии: {e}')
        flash(f'Ошибка при создании резервной копии: {str(e)}', 'error')
        return redirect(url_for('main.dashboard'))


@main_bp.route('/faq')
def faq():
    """База знаний / FAQ для учеников и родителей."""
    return render_template('faq.html', active_page='faq')


@main_bp.route('/platform-bug-reports')
@login_required
def platform_bug_reports():
    """Страница просмотра и управления баг-репортами пользователей (создатель/администратор)."""
    if not (current_user.is_creator() or current_user.is_admin() or current_user.is_chief_admin()):
        flash('Доступ запрещен', 'error')
        return redirect(url_for('main.dashboard'))
    return render_template('platform_bug_reports.html', active_page='bug_reports')
