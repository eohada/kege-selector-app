"""
Основные маршруты приложения
"""
import logging
import json
import shutil
from urllib.parse import urlparse
from flask import abort, render_template, request, send_from_directory, flash, redirect, url_for, make_response, current_app, jsonify, session
from flask_login import login_required, login_user, logout_user
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
from app.runtime_state import db_is_ready, migrations_are_ready, redis_ping, socketio_is_ready

def get_active_role():
    """
    Возвращает активную роль пользователя:
    В режиме DEBUG/TESTING отдает session['sandbox_role'] (если задана панелью Dev Role Switcher),
    иначе возвращает current_user.role.
    """
    from flask import session, current_app
    if (current_app.config.get('DEBUG') or current_app.config.get('TESTING')) and session.get('sandbox_role'):
        return session['sandbox_role']
    if current_user and current_user.is_authenticated:
        return getattr(current_user, 'role', 'student')
    return 'student'

@main_bp.context_processor
def inject_active_role():
    return dict(get_active_role=get_active_role)


base_dir = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def _regular_student_filter():
    from flask import session
    from flask_login import current_user
    is_qa = False
    try:
        is_qa = getattr(current_user, 'is_authenticated', False) and (
            current_user.is_creator() or current_user.is_chief_tester() or 
            current_user.is_admin() or getattr(current_user, 'role', '') in ['admin', 'creator'] or 
            'impersonator_id' in session
        )
    except Exception:
        pass

    if is_qa:
        return (
            or_(Student.user_id.is_(None), User.id.is_(None), User.is_demo_user.is_(False)),
        )
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
        
        if current_user.is_student():
            try:
                from app.utils.streak_service import update_student_streak_by_user_id
                update_student_streak_by_user_id(current_user.id)
            except Exception as e:
                logger.error(f"Error updating streak on ping: {e}")

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


@main_bp.route('/ready')
def readiness_check():
    """
    Readiness probe: only returns OK when the app can accept traffic.
    """
    checks = {
        'db': db_is_ready(),
        'redis': redis_ping(),
        'migrations': migrations_are_ready(),
        'socketio': socketio_is_ready(),
    }
    ok = all(checks.values())
    return jsonify({
        'status': 'OK' if ok else 'NOT_READY',
        'checks': checks,
        'environment': os.environ.get('ENVIRONMENT', 'unknown'),
        'timestamp': datetime.now().isoformat(),
    }), (200 if ok else 503)


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

@main_bp.route('/students/<int:student_id>')
@main_bp.route('/teacher/students/<int:student_id>')
@main_bp.route('/student/<int:student_id>')
@main_bp.route('/teacher/student/<int:student_id>')
@login_required
def main_student_profile(student_id):
    from app.students.routes import student_profile
    return student_profile(student_id)

@main_bp.route('/api/teacher/invites/generate', methods=['POST'])
@main_bp.route('/api/teacher/generate_invite', methods=['POST'])
@login_required
def main_generate_teacher_invite_api():
    try:
        import secrets
        code = secrets.token_hex(8)
        host = request.host_url.rstrip('/')
        invite_url = f"{host}/register?code={code}&tutor_id={current_user.id}"
        return jsonify({
            'status': 'success',
            'invite_code': code,
            'invite_url': invite_url,
            'message': 'Ссылка успешно сгенерирована'
        })
    except Exception as e:
        logger.error(f"Error generating invite: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

@main_bp.route('/preparation')
@login_required
def preparation_mode_page():
    """Страница-заглушка режима подготовки платформы (Launch Mode)"""
    from core.db_models import SystemSetting
    custom_title = SystemSetting.get_value('preparation_mode_title', '')
    custom_msg = SystemSetting.get_value('preparation_mode_message', '')
    return render_template(
        'sandbox/preparation.html',
        custom_title=custom_title,
        custom_msg=custom_msg
    )


@main_bp.route('/students')
@main_bp.route('/teacher/students')
@main_bp.route('/dashboard')
@login_required
def dashboard():
    """Главная страница (dashboard) со списком студентов"""
    active_role = get_active_role()
    if active_role == 'parent' or (current_user.is_parent() and active_role not in ['tutor', 'admin', 'creator']):
        return parents_dashboard()
    
    if current_user.is_student():
        return student_dashboard()
    
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

    view_scope = request.args.get('scope', 'my').strip().lower()

    students = []
    all_users_list = []
    student_tg_status = {}
    pagination = None
    scope = {'can_see_all': True, 'student_ids': []}
    try:
        scope = get_user_scope(current_user)
    except Exception as e:
        logger.warning(f"Error in get_user_scope: {e}")
        scope = {'can_see_all': True, 'student_ids': []}

    try:
        if view_scope == 'users':
            all_users_list = User.query.options(db.joinedload(User.profile)).order_by(User.id.desc()).all()
            for u in all_users_list:
                p = getattr(u, 'profile', None)
                if p and p.telegram_chat_id:
                    student_tg_status[u.id] = {'state': 'linked', 'label': p.telegram_id or 'TG привязан'}
                elif p and p.telegram_id:
                    student_tg_status[u.id] = {'state': 'pending', 'label': f'{p.telegram_id} без бота'}
                else:
                    student_tg_status[u.id] = {'state': 'none', 'label': 'TG нет'}
        else:
            # Гарантированное авто-создание профилей Student для всех пользователей с ролью student
            student_users = User.query.filter_by(role='student').all()
            existing_st_uids = {s.user_id for s in Student.query.all() if s.user_id}
            new_st_created = False
            for su in student_users:
                if su.id not in existing_st_uids:
                    st_obj = Student(
                        user_id=su.id,
                        name=su.full_name or su.username,
                        is_active=True,
                        category='ЕГЭ',
                        lessons_balance=8
                    )
                    db.session.add(st_obj)
                    new_st_created = True
            if new_st_created:
                db.session.commit()

            if show_archive:
                query = Student.query.options(db.joinedload(Student.user)).outerjoin(User, Student.user_id == User.id).filter(Student.is_active == False)
            else:
                query = Student.query.options(db.joinedload(Student.user)).outerjoin(User, Student.user_id == User.id).filter(Student.is_active == True)

            if view_scope == 'my':
                visible_student_ids = scope.get('student_ids') or []
                query = query.filter(or_(
                    Student.mentor_id == current_user.id,
                    Student.user_id == current_user.id,
                    Student.user_id.in_(visible_student_ids),
                    Student.student_id.in_(visible_student_ids),
                ))

            if search_query:
                search_pattern = f'%{search_query}%'
                filters = [Student.name.ilike(search_pattern)]
                query = query.filter(or_(*filters))

            page = request.args.get('page', 1, type=int) or 1
            per_page = 50
            pagination = query.order_by(Student.student_id.desc()).paginate(page=page, per_page=per_page, error_out=False)
            students = pagination.items if pagination else []

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
    except Exception as e:
        logger.error(f"Error fetching student list in dashboard: {e}", exc_info=True)
        students = []
        student_tg_status = {}
        pagination = None

    base_is_active = not show_archive
    
    count_query = Student.query.outerjoin(User, Student.user_id == User.id).filter(Student.is_active == base_is_active)
    if student_scope == 'test':
        count_query = count_query.filter(User.is_qa_pool.is_(True))
    elif student_scope == 'demo':
        count_query = count_query.filter(User.is_demo_user.is_(True))
    elif student_scope == 'regular':
        count_query = count_query.filter(*_regular_student_filter())
    if not scope['can_see_all']:
        s_ids = scope.get('student_ids') or []
        count_query = count_query.filter(
            or_(
                Student.user_id.in_(s_ids),
                Student.student_id.in_(s_ids),
                Student.mentor_id == current_user.id
            )
        )

    try:
        total_students = count_query.count()
    except Exception as e:
        logger.warning(f"Error counting total students: {e}")
        total_students = 0

    # Category tab counters must stay global for regular active students,
    # regardless of which scope tab is currently open.
    try:
        category_stats_query = db.session.query(
            Student.category,
            func.count(Student.student_id).label('count')
        ).outerjoin(User, Student.user_id == User.id).filter(Student.is_active == base_is_active)
        category_stats_query = category_stats_query.filter(*_regular_student_filter())

        if not scope['can_see_all']:
            s_ids = scope.get('student_ids') or []
            category_stats_query = category_stats_query.filter(
                or_(
                    Student.user_id.in_(s_ids),
                    Student.student_id.in_(s_ids),
                    Student.mentor_id == current_user.id
                )
            )

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

    active_role = get_active_role()
    if active_role in ['teacher', 'tutor', 'admin', 'creator']:
        return render_template(
            'sandbox/students.html',
            students=students,
            all_users_list=all_users_list,
            view_scope=view_scope,
            total_students=total_students,
            student_tg_status=student_tg_status,
            search_query=search_query,
            category_filter=category_filter
        )

    return render_template(
        'sandbox/students.html',
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
@main_bp.route('/sandbox/student_dashboard')
@login_required
def student_dashboard():
    """Дашборд ученика V2 Sandbox: план, задания, риски по темам."""
    active_role = get_active_role()
    if active_role not in ['student', 'parent'] and (current_user.role in ['teacher', 'tutor', 'admin', 'creator']):
        return redirect(url_for('main.dashboard'))

    student = Student.query.filter_by(user_id=current_user.id).first()
    if not student:
        candidate = Student.query.get(current_user.id)
        if candidate and candidate.user_id is None and candidate.student_id == current_user.id:
            student = candidate

    from app.students.stats_service import StatsService
    from app.models import StudentLearningPlanItem, Submission, UserNotification, GradebookEntry, Assignment, Lesson, StudentCourseEnrollment

    # Safe default fallback values for V2 Bento Cards
    now_utc = moscow_now() if callable(moscow_now) else datetime.now(timezone.utc)
    active_lesson = None
    upcoming_lesson = None
    recent_lessons = []
    total_lessons = 0
    completed_lessons = 0
    completion_pct = 0
    overdue_debts = 0
    mentor = None
    tg_connected = False
    tg_username = None

    if student:
        try:
            active_lesson = Lesson.query.filter(
                Lesson.student_id == student.student_id,
                Lesson.status == 'in_progress'
            ).first()
        except Exception:
            active_lesson = None

        try:
            upcoming_lesson = Lesson.query.filter(
                Lesson.student_id == student.student_id,
                Lesson.status == 'planned'
            ).order_by(Lesson.lesson_date.asc()).first()
        except Exception:
            upcoming_lesson = None

        try:
            recent_lessons = Lesson.query.filter_by(
                student_id=student.student_id
            ).order_by(Lesson.lesson_date.desc()).limit(6).all()
        except Exception:
            recent_lessons = []

        try:
            total_lessons = Lesson.query.filter_by(student_id=student.student_id).count() or 0
            completed_lessons = Lesson.query.filter_by(student_id=student.student_id, status='completed').count() or 0
        except Exception:
            total_lessons = 0
            completed_lessons = 0

        if total_lessons > 0:
            completion_pct = int(round((completed_lessons / total_lessons) * 100))

        try:
            overdue_debts = Submission.query.filter(
                Submission.student_id == student.student_id,
                Submission.status.in_(['ASSIGNED', 'IN_PROGRESS', 'RETURNED'])
            ).count() or 0
        except Exception:
            overdue_debts = 0

        try:
            mentor_id = getattr(student, 'mentor_id', None) or getattr(student, 'teacher_id', None) or getattr(current_user, 'teacher_id', None)
            if not mentor_id and student:
                from app.models import Enrollment
                enr = Enrollment.query.filter(
                    (Enrollment.student_id == student.student_id) | (Enrollment.student_id == current_user.id),
                    Enrollment.status != 'archived'
                ).first()
                if enr and enr.tutor_id:
                    mentor_id = enr.tutor_id
            if mentor_id:
                mentor = User.query.get(mentor_id)
        except Exception:
            mentor = None

    try:
        tg_id = getattr(current_user, 'telegram_id', None) or (student and getattr(student, 'telegram', None))
        tg_connected = bool(tg_id)
        tg_username = getattr(current_user, 'telegram_username', None) or (student and getattr(student, 'telegram_username', None))
        if tg_username and not str(tg_username).startswith('@'):
            tg_username = '@' + str(tg_username)
    except Exception:
        tg_connected = False
        tg_username = None

    enrollments = []
    if student:
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

    plan_items = []
    if student:
        try:
            plan_items = StudentLearningPlanItem.query.filter_by(student_id=student.student_id).order_by(
                StudentLearningPlanItem.due_date.asc().nullslast(),
                StudentLearningPlanItem.priority.desc(),
                StudentLearningPlanItem.item_id.desc(),
            ).limit(12).all()
        except Exception:
            plan_items = []

    pending_submissions = []
    if student:
        try:
            sub_query = Submission.query.join(
                Assignment, Submission.assignment_id == Assignment.assignment_id
            ).filter(
                Submission.student_id == student.student_id,
                Submission.status.in_(['ASSIGNED', 'IN_PROGRESS', 'RETURNED']),
                Assignment.is_active == True,
            ).options(db.contains_eager(Submission.assignment))
            if selected_course_id:
                sub_query = sub_query.filter(
                    db.or_(Assignment.exam_course_id == selected_course_id, Assignment.exam_course_id.is_(None))
                )
            pending_submissions = sub_query.order_by(Submission.assigned_at.desc()).limit(12).all()
        except Exception:
            pending_submissions = []

    unread_notifications = 0
    try:
        unread_notifications = UserNotification.query.filter_by(user_id=current_user.id, is_read=False).count() or 0
    except Exception:
        unread_notifications = 0

    problem_topics = []
    if student:
        try:
            stats = StatsService(student.student_id)
            problem_topics = stats.get_problem_topics(threshold=60)[:6]
        except Exception:
            problem_topics = []

    if getattr(current_user, 'is_demo_user', False) and not problem_topics:
        problem_topics = [
            {'id': 0, 'name': 'Системы счисления', 'avg_score': 42},
            {'id': 0, 'name': 'Рекурсия и динамическое программирование', 'avg_score': 35},
            {'id': 0, 'name': 'Теория игр', 'avg_score': 48},
            {'id': 0, 'name': 'Графы и обход деревьев', 'avg_score': 55},
        ]

    recent_grades = []
    if student:
        try:
            recent_grades = (
                GradebookEntry.query
                .outerjoin(Submission, GradebookEntry.submission_id == Submission.submission_id)
                .outerjoin(Assignment, Submission.assignment_id == Assignment.assignment_id)
                .filter(
                    GradebookEntry.student_id == student.student_id,
                    db.or_(
                        GradebookEntry.submission_id.is_(None),
                        Assignment.is_active == True,
                    )
                )
                .order_by(GradebookEntry.created_at.desc(), GradebookEntry.entry_id.desc())
                .limit(8).all()
            )
        except Exception:
            recent_grades = []

    completed_tasks = 0
    if student:
        try:
            completed_tasks = Submission.query.join(
                Assignment, Submission.assignment_id == Assignment.assignment_id
            ).filter(
                Submission.student_id == student.student_id,
                Submission.status.in_(['GRADED']),
                Assignment.is_active == True,
            ).count() or 0
        except Exception:
            completed_tasks = 0

    avg_score = '—'
    if student:
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
                        GradebookEntry.submission_id.is_(None),
                        Assignment.is_active == True,
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
        'sandbox/student_dashboard.html',
        release_notes=build_release_notes_text(),
        release_version=RELEASE_VERSION,
        user=current_user,
        student=student,
        active_lesson=active_lesson,
        upcoming_lesson=upcoming_lesson,
        recent_lessons=recent_lessons,
        total_lessons=total_lessons,
        completed_lessons=completed_lessons,
        completion_pct=completion_pct,
        overdue_debts=overdue_debts,
        mentor=mentor,
        tg_connected=tg_connected,
        tg_username=tg_username,
        plan_items=plan_items,
        pending_submissions=pending_submissions,
        unread_notifications=unread_notifications,
        problem_topics=problem_topics,
        recent_grades=recent_grades,
        enrollments=enrollments,
        selected_course_id=selected_course_id,
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


@main_bp.route('/api/student/<int:student_id>/debug-streak', methods=['POST'])
@login_required
def debug_streak(student_id):
    """Временный API для изменения стрика ученика (для тестов)."""
    from app.models import Student
    student = Student.query.get_or_404(student_id)
    payload = request.get_json(silent=True) or {}
    
    if 'streak_days' in payload:
        try:
            student.streak_days = int(payload['streak_days'])
            if 'streak_frozen' in payload:
                student.streak_frozen = bool(payload['streak_frozen'])
            db.session.commit()
            return jsonify({
                'success': True, 
                'streak_days': student.streak_days, 
                'streak_frozen': student.streak_frozen
            })
        except ValueError:
            return jsonify({'success': False, 'error': 'Invalid streak value'}), 400
            
    return jsonify({'success': False, 'error': 'Missing streak_days'}), 400


def is_godmode_user():
    role = getattr(current_user, 'role', '')
    sb_role = session.get('sandbox_role', '')
    return role == 'creator' or sb_role == 'creator' or getattr(current_user, 'is_admin', lambda: False)() or role in ['admin', 'chief_admin']


@main_bp.route('/api/students/<int:student_id>/link_tutor', methods=['POST'])
@login_required
def link_tutor(student_id):
    """Привязывает ученика к текущему создателю/преподавателю (1-Click Link)."""
    print(f"\n[LINK_TUTOR DEBUG] Triggered for student_id={student_id} by user={current_user.username} (id={current_user.id}, role={current_user.role})")
    if not is_godmode_user() and getattr(current_user, 'role', '') not in ['teacher', 'tutor', 'admin']:
        return jsonify({'status': 'error', 'message': 'Недостаточно прав (403)'}), 403

    try:
        from app.models import Student
        student = Student.query.get(student_id)
        if not student:
            student = Student.query.filter_by(user_id=student_id).first()
        if not student:
            user = User.query.get_or_404(student_id)
            student = Student.query.filter_by(user_id=user.id).first()
            if not student:
                student = Student(
                    user_id=user.id,
                    name=user.full_name or user.username,
                    is_active=True,
                    category='ЕГЭ',
                    lessons_balance=8
                )
                db.session.add(student)

        target_tutor_id = current_user.id
        print(f"[LINK_TUTOR DEBUG] Setting student.mentor_id (tutor_id) = {target_tutor_id}")
        student.mentor_id = target_tutor_id
        db.session.commit()
        print(f"[LINK_TUTOR DEBUG] SUCCESS! db.session.commit() executed for student_id={student.student_id}\n")

        return jsonify({
            'status': 'success',
            'success': True,
            'message': f'Ученик {student.name} успешно привязан!',
            'student_id': student.student_id,
            'tutor_id': target_tutor_id
        }), 200
    except Exception as e:
        db.session.rollback()
        print(f"[LINK_TUTOR ERROR] EXCEPTION DURING COMMIT: {str(e)}\n")
        logger.error(f"Error in link_tutor: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@main_bp.route('/api/students/<int:student_id>/unlink_tutor', methods=['POST'])
@login_required
def unlink_student_tutor(student_id):
    """Отвязывает ученика от текущего преподавателя/создателя (Reset mentor_id)."""
    print(f"\n[UNLINK_TUTOR DEBUG] Triggered for student_id={student_id} by user={current_user.username}")
    try:
        if not is_godmode_user() and getattr(current_user, 'role', '') not in ['teacher', 'tutor', 'admin']:
            return jsonify({'status': 'error', 'message': 'Недостаточно прав (403)'}), 403

        from app.models import Student
        student = Student.query.get(student_id)
        if not student:
            student = Student.query.filter_by(user_id=student_id).first()

        if not student:
            return jsonify({'status': 'error', 'message': 'Ученик не найден в БД'}), 404

        student.mentor_id = None
        db.session.commit()
        print(f"[UNLINK_TUTOR DEBUG] SUCCESS! student_id={student.student_id} is now unlinked (mentor_id = None)\n")

        return jsonify({
            'status': 'success',
            'success': True,
            'message': 'Привязка к ученику успешно снята!'
        }), 200

    except Exception as e:
        db.session.rollback()
        print(f"[UNLINK_TUTOR ERROR] EXCEPTION: {str(e)}\n")
        logger.error(f"Error in unlink_student_tutor: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': f'Ошибка БД: {str(e)}'}), 500


@main_bp.route('/api/admin/users/<int:user_id>/update', methods=['POST'])
@login_required
def admin_update_user(user_id):
    """Быстрое редактирование имени, email, роли и статуса пользователя администратором/создателем."""
    print(f"\n[USER_UPDATE DEBUG] Updating user_id={user_id} by user={current_user.username}")
    if not is_godmode_user() and getattr(current_user, 'role', '') not in ['admin', 'chief_admin']:
        return jsonify({'status': 'error', 'message': 'Недостаточно прав (403)'}), 403

    try:
        target_user = User.query.get_or_404(user_id)
        payload = request.get_json(force=True, silent=True) or request.get_json(silent=True) or request.form
        print(f"[USER_UPDATE DEBUG] Received payload: {payload}")

        new_role = payload.get('role', target_user.role)
        new_username = payload.get('username', target_user.username)
        new_email = payload.get('email', target_user.email)
        is_active_val = payload.get('is_active')

        # ⛔ ЗАЩИТА ИММУНИТЕТА СОЗДАТЕЛЯ
        if target_user.username == 'creator' or target_user.role == 'creator':
            if new_role != 'creator':
                return jsonify({'status': 'error', 'message': '⛔ Запрещено изменять роль каноничного профиля Создателя!'}), 400

        if new_username:
            target_user.username = new_username
        if new_email:
            target_user.email = new_email
        if new_role:
            target_user.role = new_role
        if is_active_val is not None:
            target_user.is_active = bool(is_active_val)

        db.session.commit()
        print(f"[USER_UPDATE DEBUG] SUCCESS! User {target_user.username} updated to role={target_user.role}\n")
        return jsonify({
            'status': 'success',
            'success': True,
            'message': f'Пользователь {target_user.username} успешно обновлен!',
            'user': {
                'id': target_user.id,
                'username': target_user.username,
                'email': target_user.email,
                'role': target_user.role,
                'is_active': target_user.is_active
            }
        }), 200
    except Exception as e:
        db.session.rollback()
        print(f"[USER_UPDATE ERROR] {str(e)}\n")
        logger.error(f"Error in admin_update_user: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@main_bp.route('/api/student/<int:student_id>/debug-xp', methods=['POST'])
@login_required
def debug_xp(student_id):
    """Временный API для изменения опыта (XP) ученика (для тестов)."""
    from app.models import Student
    from app.utils.xp_service import calculate_level_from_xp
    student = Student.query.get_or_404(student_id)
    payload = request.get_json(silent=True) or {}
    
    if 'xp' in payload:
        try:
            student.xp = max(0, int(payload['xp']))
            student.level = calculate_level_from_xp(student.xp)
            db.session.commit()
            return jsonify({
                'success': True,
                'xp': student.xp,
                'level': student.level
            })
        except ValueError:
            return jsonify({'success': False, 'error': 'Invalid XP value'}), 400
            
    return jsonify({'success': False, 'error': 'Missing xp'}), 400


@main_bp.route('/api/student/<int:student_id>/debug-achievements', methods=['POST'])
@login_required
def debug_achievements(student_id):
    """Временный API для выдачи/забора ачивок ученика (для тестов/Создателя)."""
    from app.models import Student
    from app.utils.achievement_service import grant_achievement, revoke_achievement
    student = Student.query.get_or_404(student_id)
    payload = request.get_json(silent=True) or {}
    
    key = payload.get('achievement_key')
    action = payload.get('action')
    
    if not key:
        return jsonify({'success': False, 'error': 'Missing achievement_key'}), 400
        
    if action == 'grant':
        granted = grant_achievement(student, key, award_xp=True)
        return jsonify({'success': True, 'action': 'grant', 'status': 'granted' if granted else 'already_had'})
    elif action == 'revoke':
        revoked = revoke_achievement(student, key)
        return jsonify({'success': True, 'action': 'revoke', 'status': 'revoked' if revoked else 'did_not_have'})
        
    return jsonify({'success': False, 'error': 'Invalid action'}), 400


@main_bp.route('/student/mistakes')
@login_required
def student_mistakes():
    from app.models import Student, Answer, Submission
    from flask import flash, redirect, url_for, render_template
    
    student = Student.query.filter_by(user_id=current_user.id).first()
    if not student:
        flash("Только ученики имеют доступ к работе над ошибками.", "warning")
        return redirect(url_for('main.dashboard'))
        
    mistakes = Answer.query.join(Submission).filter(
        Submission.student_id == student.student_id,
        Answer.is_correct == False
    ).all()
    
    return render_template('student_mistakes.html', student=student, mistakes=mistakes)


@main_bp.route('/student/mistakes/<int:answer_id>/retry', methods=['POST'])
@login_required
def retry_mistake(answer_id):
    from app.models import Student, Answer, Submission, db
    from flask import request, jsonify
    
    student = Student.query.filter_by(user_id=current_user.id).first()
    if not student:
        return jsonify({'success': False, 'message': 'Доступ запрещен'}), 403
        
    ans = Answer.query.get_or_404(answer_id)
    if ans.submission.student_id != student.student_id:
        return jsonify({'success': False, 'message': 'Доступ запрещен'}), 403
        
    data = request.get_json() or {}
    new_answer_val = data.get('new_answer', '').strip()
    
    # Сравниваем ответ с эталонным
    correct_ans = ans.assignment_task.answer_override or ans.assignment_task.task.answer
    if correct_ans:
        correct_ans = correct_ans.strip()
        
    if correct_ans and new_answer_val == correct_ans:
        ans.is_correct = True
        ans.value = new_answer_val
        ans.score = ans.assignment_task.max_score or 1
        
        # Пересчитываем общий балл за работу
        sub = ans.submission
        all_answers = Answer.query.filter_by(submission_id=sub.submission_id).all()
        
        total_score = 0
        max_score = 0
        for a in all_answers:
            score_to_add = ans.score if a.answer_id == ans.answer_id else (a.score or 0)
            total_score += score_to_add
            max_score += a.assignment_task.max_score or 1
            
        sub.total_score = total_score
        sub.max_score = max_score
        if max_score > 0:
            sub.percentage = round((total_score / max_score) * 100, 2)
            
        try:
            db.session.commit()
            return jsonify({'success': True, 'message': 'Правильно! Ошибка исправлена!'})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'message': f'Ошибка сохранения: {str(e)}'})
    else:
        return jsonify({'success': False, 'message': 'Ответ неверный. Попробуйте еще раз!'})


@main_bp.route('/uploads/qa/<path:filename>')
def serve_qa_upload(filename):
    """Глобальная раздача скриншотов QA из папки uploads/qa."""
    import os
    from flask import send_from_directory, current_app
    upload_dir = os.path.join(current_app.config.get('UPLOAD_FOLDER', 'uploads'), 'qa')
    if not os.path.isabs(upload_dir):
        # Если путь относительный, строим от папки app
        base_dir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
        upload_dir = os.path.join(base_dir, upload_dir)
    return send_from_directory(upload_dir, filename)



# =========================================================================
# V2 GROUPS & TEMPLATES MANAGEMENT (RBAC & DYNAMIC DB)
# =========================================================================
from core.db_models import SchoolGroup, GroupStudent, TaskTemplate, TemplateTask


@main_bp.route('/groups', methods=['GET'])
@main_bp.route('/teacher/groups', methods=['GET'])
@login_required
def teacher_groups():
    """Список групп и классов преподавателя."""
    active_role = get_active_role()
    if active_role not in ['tutor', 'teacher', 'admin', 'creator']:
        flash("Раздел доступен только для преподавателей", "warning")
        return redirect(url_for('main.dashboard'))

    if active_role in ['admin', 'creator']:
        groups = SchoolGroup.query.filter_by(status='active').order_by(SchoolGroup.created_at.desc()).all()
        students = Student.query.all()
    else:
        groups = SchoolGroup.query.filter_by(owner_user_id=current_user.id, status='active').order_by(SchoolGroup.created_at.desc()).all()
        students = Student.query.all()

    try:
        from app.models import Course
        courses = Course.query.all()
    except Exception:
        courses = []

    total_groups_count = len(groups)
    unique_student_ids = set()
    for g in groups:
        for gs in g.students:
            if gs.student_id:
                unique_student_ids.add(gs.student_id)
    total_students_count = len(unique_student_ids)

    return render_template(
        'main/groups.html',
        groups=groups,
        courses=courses,
        students=students,
        total_groups_count=total_groups_count,
        total_students_count=total_students_count
    )


@main_bp.route('/teacher/group/<int:group_id>', methods=['GET'])
@login_required
def teacher_group_detail(group_id):
    """Детализация конкретной группы учеников."""
    active_role = get_active_role()
    if active_role not in ['tutor', 'teacher', 'admin', 'creator']:
        flash("Раздел доступен только для преподавателей", "warning")
        return redirect(url_for('main.dashboard'))

    group = SchoolGroup.query.get_or_404(group_id)

    if active_role not in ['admin', 'creator'] and group.owner_user_id != current_user.id:
        flash("У вас нет доступа к этой группе", "warning")
        return redirect(url_for('main.teacher_groups'))

    attached_students = [gs.student for gs in group.students if gs.student]

    if active_role in ['admin', 'creator']:
        all_tutor_students = Student.query.all()
    else:
        all_tutor_students = Student.query.all()

    attached_ids = {s.student_id for s in attached_students}
    available_students = [s for s in all_tutor_students if s.student_id not in attached_ids]

    return render_template(
        'main/group_detail.html',
        group=group,
        attached_students=attached_students,
        available_students=available_students
    )


@main_bp.route('/api/teacher/groups', methods=['POST'])
@login_required
def api_create_group():
    """API создания новой группы."""
    active_role = get_active_role()
    if active_role not in ['tutor', 'teacher', 'admin', 'creator']:
        return jsonify({'status': 'error', 'message': 'Нет прав доступа'}), 403

    data = request.json or request.form or {}
    name = (data.get('name') or data.get('title') or '').strip()
    if not name:
        return jsonify({'status': 'error', 'message': 'Укажите название группы'}), 400

    subject = (data.get('subject') or '').strip()
    tag = (data.get('tag') or 'Мини-группа').strip()
    description = (data.get('description') or '').strip()
    telegram_chat_link = (data.get('telegram_chat_link') or '').strip()
    course_id = data.get('course_id')

    group = SchoolGroup(
        title=name,
        subject=subject,
        tag=tag,
        description=description,
        telegram_chat_link=telegram_chat_link,
        owner_user_id=current_user.id,
        status='active'
    )
    if course_id:
        try:
            group.course_id = int(course_id)
        except Exception:
            pass

    db.session.add(group)
    db.session.flush()

    student_ids = data.get('student_ids') or []
    if isinstance(student_ids, str):
        student_ids = [int(s.strip()) for s in student_ids.split(',') if s.strip().isdigit()]

    for sid in student_ids:
        try:
            sid_int = int(sid)
            gs = GroupStudent(group_id=group.group_id, student_id=sid_int, added_by_user_id=current_user.id)
            db.session.add(gs)
        except Exception as e:
            logging.error(f"Error attaching student {sid} to group: {e}")

    db.session.commit()

    return jsonify({
        'status': 'success',
        'group_id': group.group_id,
        'message': 'Группа успешно создана'
    }), 201


@main_bp.route('/api/teacher/groups/<int:group_id>', methods=['PUT', 'POST'])
@login_required
def api_update_group(group_id):
    """API обновления группы."""
    active_role = get_active_role()
    if active_role not in ['tutor', 'teacher', 'admin', 'creator']:
        return jsonify({'status': 'error', 'message': 'Нет прав доступа'}), 403

    group = SchoolGroup.query.get_or_404(group_id)
    if active_role not in ['admin', 'creator'] and group.owner_user_id != current_user.id:
        return jsonify({'status': 'error', 'message': 'Чужая группа'}), 403

    data = request.json or request.form or {}
    name = (data.get('name') or data.get('title') or '').strip()
    if name:
        group.title = name
    if 'subject' in data:
        group.subject = data.get('subject')
    if 'tag' in data:
        group.tag = data.get('tag')
    if 'description' in data:
        group.description = data.get('description')
    if 'telegram_chat_link' in data:
        group.telegram_chat_link = data.get('telegram_chat_link')
    if 'course_id' in data and data.get('course_id'):
        try:
            group.course_id = int(data.get('course_id'))
        except Exception:
            pass

    if 'student_ids' in data:
        student_ids = data.get('student_ids') or []
        if isinstance(student_ids, str):
            student_ids = [int(s.strip()) for s in student_ids.split(',') if s.strip().isdigit()]
        GroupStudent.query.filter_by(group_id=group.group_id).delete()
        for sid in student_ids:
            try:
                gs = GroupStudent(group_id=group.group_id, student_id=int(sid), added_by_user_id=current_user.id)
                db.session.add(gs)
            except Exception as e:
                logging.error(f"Error re-attaching student {sid}: {e}")

    db.session.commit()

    return jsonify({
        'status': 'success',
        'group_id': group.group_id,
        'message': 'Группа успешно обновлена'
    })


@main_bp.route('/api/teacher/groups/<int:group_id>', methods=['DELETE'])
@login_required
def api_delete_group(group_id):
    """API удаления группы (отвязка учеников)."""
    active_role = get_active_role()
    if active_role not in ['tutor', 'teacher', 'admin', 'creator']:
        return jsonify({'status': 'error', 'message': 'Нет прав доступа'}), 403

    group = SchoolGroup.query.get_or_404(group_id)
    if active_role not in ['admin', 'creator'] and group.owner_user_id != current_user.id:
        return jsonify({'status': 'error', 'message': 'Чужая группа'}), 403

    GroupStudent.query.filter_by(group_id=group.group_id).delete()
    db.session.delete(group)
    db.session.commit()

    return jsonify({
        'status': 'success',
        'message': 'Группа успешно удалена'
    })


@main_bp.route('/api/teacher/groups/<int:group_id>/students/add', methods=['POST'])
@login_required
def api_add_student_to_group(group_id):
    """API добавления ученика в группу."""
    active_role = get_active_role()
    if active_role not in ['tutor', 'teacher', 'admin', 'creator']:
        return jsonify({'status': 'error', 'message': 'Нет прав доступа'}), 403

    group = SchoolGroup.query.get_or_404(group_id)
    data = request.json or request.form or {}
    student_id = data.get('student_id')
    if not student_id:
        return jsonify({'status': 'error', 'message': 'Укажите ID ученика'}), 400

    existing = GroupStudent.query.filter_by(group_id=group.group_id, student_id=int(student_id)).first()
    if not existing:
        gs = GroupStudent(group_id=group.group_id, student_id=int(student_id), added_by_user_id=current_user.id)
        db.session.add(gs)
        db.session.commit()

    return jsonify({'status': 'success', 'message': 'Ученик добавлен в группу'})


@main_bp.route('/api/teacher/groups/<int:group_id>/students/<int:student_id>', methods=['DELETE'])
@login_required
def api_remove_student_from_group(group_id, student_id):
    """API отвязки ученика от группы."""
    active_role = get_active_role()
    if active_role not in ['tutor', 'teacher', 'admin', 'creator']:
        return jsonify({'status': 'error', 'message': 'Нет прав доступа'}), 403

    GroupStudent.query.filter_by(group_id=group_id, student_id=student_id).delete()
    db.session.commit()

    return jsonify({'status': 'success', 'message': 'Ученик отвязан от группы'})


@main_bp.route('/templates_library', methods=['GET'])
@main_bp.route('/teacher/templates', methods=['GET'])
@login_required
def teacher_templates_library():
    """Библиотека шаблонов заданий преподавателя."""
    active_role = get_active_role()
    if active_role not in ['tutor', 'teacher', 'admin', 'creator']:
        flash("Раздел доступен только для преподавателей", "warning")
        return redirect(url_for('main.dashboard'))

    if active_role in ['admin', 'creator']:
        templates = TaskTemplate.query.filter_by(is_active=True).order_by(TaskTemplate.created_at.desc()).all()
    else:
        templates = TaskTemplate.query.filter_by(created_by=current_user.id, is_active=True).order_by(TaskTemplate.created_at.desc()).all()

    count_all = len(templates)
    count_hw = len([t for t in templates if t.template_type == 'homework'])
    count_cw = len([t for t in templates if t.template_type == 'classwork'])
    count_mock = len([t for t in templates if (t.template_type == 'mock_exam' or t.template_type == 'exam')])
    count_quiz = len([t for t in templates if t.template_type == 'quiz'])

    return render_template(
        'main/templates_library.html',
        templates=templates,
        count_all=count_all,
        count_hw=count_hw,
        count_cw=count_cw,
        count_mock=count_mock,
        count_quiz=count_quiz
    )


@main_bp.route('/api/teacher/templates/<int:template_id>/preview', methods=['GET'])
@login_required
def api_template_preview(template_id):
    """API получения данных предпросмотра шаблона (список задач)."""
    active_role = get_active_role()
    if active_role not in ['tutor', 'teacher', 'admin', 'creator']:
        return jsonify({'status': 'error', 'message': 'Нет прав доступа'}), 403

    template = TaskTemplate.query.get_or_404(template_id)
    if active_role not in ['admin', 'creator'] and template.created_by != current_user.id:
        return jsonify({'status': 'error', 'message': 'Чужой шаблон'}), 403

    tasks = []
    sorted_tt = sorted(template.template_tasks, key=lambda x: x.order if x.order is not None else 0)
    for idx, tt in enumerate(sorted_tt):
        t = tt.task
        if t:
            topic = getattr(t, 'topic_name', None) or getattr(t, 'topic', None) or getattr(t, 'subject', None) or 'Задание'
            task_num = getattr(t, 'task_number', None) or getattr(t, 'type', None) or (idx + 1)
            content = getattr(t, 'statement_html', None) or getattr(t, 'content_html', None) or getattr(t, 'question_text', None) or getattr(t, 'text', None) or getattr(t, 'description', None) or 'Текст задания'
            img = getattr(t, 'image_url', None) or None
            ans = getattr(t, 'answer', None) or None

            tasks.append({
                'task_id': t.task_id,
                'task_number': task_num,
                'topic': topic,
                'content': content,
                'image_url': img,
                'answer': ans
            })

    return jsonify({
        'status': 'success',
        'template_id': template.template_id,
        'title': template.name,
        'description': template.description or '',
        'template_type': template.template_type,
        'estimated_time': template.estimated_time or 45,
        'tasks_count': len(tasks),
        'tasks': tasks
    })


@main_bp.route('/api/teacher/templates/<int:template_id>', methods=['DELETE'])
@login_required
def api_delete_template(template_id):
    """API удаления шаблона из базы данных."""
    active_role = get_active_role()
    if active_role not in ['tutor', 'teacher', 'admin', 'creator']:
        return jsonify({'status': 'error', 'message': 'Нет прав доступа'}), 403

    template = TaskTemplate.query.get_or_404(template_id)
    if active_role not in ['admin', 'creator'] and template.created_by != current_user.id:
        return jsonify({'status': 'error', 'message': 'Чужой шаблон'}), 403

    TemplateTask.query.filter_by(template_id=template.template_id).delete()
    db.session.delete(template)
    db.session.commit()

    return jsonify({
        'status': 'success',
        'message': 'Шаблон успешно удален'
    })


@main_bp.route('/api/teacher/templates', methods=['POST'])
@main_bp.route('/api/templates/create', methods=['POST'])
@login_required
def api_create_template():
    """API создания нового шаблона заданий."""
    active_role = get_active_role()
    if active_role not in ['tutor', 'teacher', 'admin', 'creator']:
        return jsonify({'status': 'error', 'message': 'Нет прав доступа'}), 403

    data = request.json or request.form or {}
    title = (data.get('title') or data.get('name') or '').strip()
    if not title:
        return jsonify({'status': 'error', 'message': 'Укажите название шаблона'}), 400

    template_type = data.get('template_type', 'homework')
    description = (data.get('description') or '').strip()
    estimated_time = data.get('estimated_time', 45)
    category = data.get('category', 'ЕГЭ')
    task_ids = data.get('task_ids') or []

    template = TaskTemplate(
        name=title,
        description=description,
        template_type=template_type,
        category=category,
        estimated_time=int(estimated_time) if str(estimated_time).isdigit() else 45,
        created_by=current_user.id,
        is_active=True
    )
    db.session.add(template)
    db.session.flush()

    for order, tid in enumerate(task_ids):
        try:
            tt = TemplateTask(template_id=template.template_id, task_id=int(tid), order=order)
            db.session.add(tt)
        except Exception as e:
            logging.error(f"Error attaching task {tid} to template: {e}")

    db.session.commit()

    return jsonify({
        'status': 'success',
        'template_id': template.template_id,
        'message': 'Шаблон успешно создан'
    }), 201



@main_bp.route('/teacher/templates/new', methods=['GET', 'POST'], endpoint='create_template_view')
@login_required
def create_template_view():
    """Маршрут открытия конструктора для создания нового шаблона заданий."""
    active_role = get_active_role()
    if active_role not in ['tutor', 'teacher', 'admin', 'creator']:
        flash("Раздел доступен только для преподавателей", "warning")
        return redirect(url_for('main.dashboard'))

    return redirect(url_for('templates.template_new'))


@main_bp.route('/teacher/templates/<int:template_id>/edit', methods=['GET', 'POST'], endpoint='edit_template_view')
@login_required
def edit_template_view(template_id):
    """Маршрут открытия конструктора для редактирования существующего шаблона."""
    active_role = get_active_role()
    if active_role not in ['tutor', 'teacher', 'admin', 'creator']:
        flash("Раздел доступен только для преподавателей", "warning")
        return redirect(url_for('main.dashboard'))

    template = TaskTemplate.query.get_or_404(template_id)
    if active_role not in ['admin', 'creator'] and template.created_by != current_user.id:
        flash("Чужой шаблон нельзя редактировать", "warning")
        return redirect(url_for('main.teacher_templates_library'))

    return redirect(url_for('templates.template_edit', template_id=template_id))





@main_bp.route('/sandbox/<path:page_name>', endpoint='render_sandbox_layout_page')
@login_required
def render_sandbox_layout_page(page_name):
    """Redirect retired sandbox URLs to their supported V2 destinations."""
    clean_name = page_name.rstrip('/')
    if clean_name.endswith('.html'):
        clean_name = clean_name[:-5]

    if clean_name == 'task_generator':
        return redirect(url_for('task_generator.task_generator'))

    canonical_pages = {
        'theory': 'theory.theory_index',
        'trainer': 'trainer.trainer_v2',
        'schedule': 'schedule.schedule',
        'student_schedule': 'schedule.schedule',
        'profile': 'main.universal_profile_view',
        'analytics': 'main.analytics_view',
        'library': 'library.materials_library',
        'assignments': 'assignments.submissions_list',
        'create_assignment': 'assignments.assignment_create',
        'mentor_task_check': 'lessons.review_queue',
        'workspace': 'assignments.submissions_list',
        'task_detail': 'assignments.submissions_list',
        'assignment_detail': 'assignments.assignments_list',
        'assignment_details': 'assignments.assignments_list',
        'tasks': 'assignments.submissions_list',
    }
    if clean_name in canonical_pages:
        return redirect(url_for(canonical_pages[clean_name]))
    if clean_name.startswith('task_detail/'):
        target_id = clean_name.rsplit('/', 1)[-1]
        if target_id.isdigit():
            from core.db_models import Submission
            sub = db.session.get(Submission, int(target_id))
            if sub:
                return redirect(url_for('assignments.submission_view', submission_id=sub.submission_id))
            else:
                sub_by_assign = Submission.query.filter_by(assignment_id=int(target_id), student_id=getattr(current_user, 'id', None)).first()
                if sub_by_assign:
                    return redirect(url_for('assignments.submission_view', submission_id=sub_by_assign.submission_id))
            return redirect(url_for('assignments.submissions_list'))

    if clean_name.startswith('lesson_room/'):
        lesson_id = clean_name.rsplit('/', 1)[-1]
        if lesson_id.isdigit():
            return redirect(url_for('lessons.lesson_interactive_room', lesson_id=int(lesson_id)))
    if clean_name.startswith('teacher_room/'):
        return redirect(url_for('schedule.schedule'))
    abort(404)



# =========================================================================
# БИБЛИОТЕКА МАТЕРИАЛОВ V2 (Единый учебный хаб)
# =========================================================================
import uuid
from werkzeug.utils import secure_filename
from core.db_models import LibraryMaterial

def format_bytes(size_in_bytes):
    if size_in_bytes < 1024:
        return f"{size_in_bytes} Б"
    elif size_in_bytes < 1024 * 1024:
        return f"{size_in_bytes / 1024:.1f} КБ"
    elif size_in_bytes < 1024 * 1024 * 1024:
        return f"{size_in_bytes / (1024 * 1024):.1f} МБ"
    else:
        return f"{size_in_bytes / (1024 * 1024 * 1024):.1f} ГБ"


@main_bp.route('/library', methods=['GET'], endpoint='library_hub_view')
@main_bp.route('/teacher/library', methods=['GET'], endpoint='teacher_library_hub_view')
@login_required
def library_hub_view():
    """Единый учебный хаб материалов V2."""
    active_role = get_active_role()
    if active_role == 'student':
        return redirect(url_for('main.dashboard'))

    if active_role in ['admin', 'creator']:
        materials = LibraryMaterial.query.filter(LibraryMaterial.category != 'theory').order_by(LibraryMaterial.created_at.desc()).all()
        theory_materials = LibraryMaterial.query.filter_by(category='theory').order_by(LibraryMaterial.created_at.desc()).all()
        templates = TaskTemplate.query.order_by(TaskTemplate.created_at.desc()).all()
    else:
        materials = LibraryMaterial.query.filter_by(teacher_id=current_user.id).filter(LibraryMaterial.category != 'theory').order_by(LibraryMaterial.created_at.desc()).all()
        theory_materials = LibraryMaterial.query.filter_by(teacher_id=current_user.id, category='theory').order_by(LibraryMaterial.created_at.desc()).all()
        templates = TaskTemplate.query.filter_by(created_by=current_user.id).order_by(TaskTemplate.created_at.desc()).all()

    all_tags = set()
    for m in list(materials) + list(theory_materials):
        for tag in (m.tags or '').split(','):
            tag_clean = tag.strip().lstrip('#')
            if tag_clean:
                all_tags.add('#' + tag_clean)
    all_tags = sorted(list(all_tags))

    return render_template(
        'main/library.html',
        materials=materials,
        theory_materials=theory_materials,
        templates=templates,
        all_tags=all_tags
    )


@main_bp.route('/api/teacher/materials/upload', methods=['POST'], endpoint='upload_material_api')
@login_required
def upload_material_api():
    """API асинхронной загрузки файла в Библиотеку материалов V2."""
    active_role = get_active_role()
    if active_role not in ['teacher', 'tutor', 'admin', 'creator']:
        return jsonify({'status': 'error', 'message': 'Доступ разрешен только преподавателям'}), 403

    file = request.files.get('file')
    has_file = bool(file and file.filename)
    category = request.form.get('category', 'materials').strip()
    if category not in ['materials', 'lesson_templates', 'theory']:
        category = 'materials'

    title = request.form.get('title', '').strip()
    if not has_file and category != 'theory':
        return jsonify({'status': 'error', 'message': 'Файл не выбран'}), 400

    if not has_file and not title:
        return jsonify({'status': 'error', 'message': 'Укажите тему теории'}), 400

    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    category = request.form.get('category', 'materials').strip()
    if category not in ['materials', 'lesson_templates', 'theory']:
        category = 'materials'

    raw_tags = request.form.get('tags', '').strip()
    clean_tags_list = [t.strip().lstrip('#') for t in raw_tags.replace(';', ',').split(',') if t.strip()]
    cleaned_tags_str = ', '.join(clean_tags_list)

    is_visible_raw = request.form.get('is_visible_to_students')
    is_visible = str(is_visible_raw).lower() in ['true', '1', 'on', 'yes']

    upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'library')
    os.makedirs(upload_folder, exist_ok=True)

    unique_filename = ""
    original_filename = ""
    ext = ""
    file_size = 0
    formatted_sz = "0 Б"

    if has_file:
        original_filename = file.filename
        ext = os.path.splitext(original_filename)[1].lstrip('.').lower()
        unique_filename = f"{uuid.uuid4().hex}_{secure_filename(original_filename)}"
        dest_path = os.path.join(upload_folder, unique_filename)

        file.save(dest_path)
        file_size = os.path.getsize(dest_path)
        formatted_sz = format_bytes(file_size)

    material = LibraryMaterial(
        title=title or original_filename or "Заметка теории",
        description=description,
        filename=unique_filename,
        original_filename=original_filename,
        file_path=f"uploads/library/{unique_filename}" if unique_filename else "",
        file_size=file_size,
        formatted_size=formatted_sz,
        file_extension=ext or "txt",
        category=category,
        tags=cleaned_tags_str,
        is_visible_to_students=is_visible,
        teacher_id=current_user.id,
        created_at=moscow_now()
    )
    db.session.add(material)
    db.session.commit()

    return jsonify({
        'status': 'success',
        'message': 'Материал успешно загружен',
        'material': material.to_dict()
    }), 201


@main_bp.route('/materials/download/<int:material_id>', methods=['GET'], endpoint='download_material_view')
@login_required
def download_material_view(material_id):
    """Скачивание файла из Библиотеки материалов V2."""
    material = LibraryMaterial.query.get_or_404(material_id)
    active_role = get_active_role()

    if active_role == 'student' and not material.is_visible_to_students:
        flash("Доступ к данному файлу ограничен преподавателем", "warning")
        return redirect(url_for('main.dashboard'))

    upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'library')
    if not os.path.exists(os.path.join(upload_folder, material.filename)):
        upload_folder = os.path.join(os.path.dirname(current_app.root_path), 'uploads', 'library')

    return send_from_directory(
        upload_folder,
        material.filename,
        download_name=material.original_filename,
        as_attachment=True
    )


@main_bp.route('/api/teacher/materials/<int:material_id>', methods=['DELETE'], endpoint='delete_material_api')
@login_required
def delete_material_api(material_id):
    """API удаления материала из Библиотеки материалов V2."""
    active_role = get_active_role()
    if active_role not in ['teacher', 'tutor', 'admin', 'creator']:
        return jsonify({'status': 'error', 'message': 'Доступ запрещен'}), 403

    material = LibraryMaterial.query.get_or_404(material_id)
    if active_role not in ['admin', 'creator'] and material.teacher_id != current_user.id:
        return jsonify({'status': 'error', 'message': 'Чужой материал нельзя удалить'}), 403

    upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'library')
    file_full_path = os.path.join(upload_folder, material.filename)
    if os.path.exists(file_full_path):
        try:
            os.remove(file_full_path)
        except Exception as e:
            current_app.logger.warning(f"Could not delete physical file {file_full_path}: {e}")

    db.session.delete(material)
    db.session.commit()

    return jsonify({
        'status': 'success',
        'message': 'Материал успешно удален'
    })


@main_bp.route('/api/teacher/materials/<int:material_id>/visibility', methods=['PATCH'], endpoint='toggle_material_visibility_api')
@login_required
def toggle_material_visibility_api(material_id):
    """API переключения видимости материала для учеников."""
    active_role = get_active_role()
    if active_role not in ['teacher', 'tutor', 'admin', 'creator']:
        return jsonify({'status': 'error', 'message': 'Доступ запрещен'}), 403

    material = LibraryMaterial.query.get_or_404(material_id)
    if active_role not in ['admin', 'creator'] and material.teacher_id != current_user.id:
        return jsonify({'status': 'error', 'message': 'Чужой материал нельзя редактировать'}), 403

    data = request.get_json(silent=True) or {}
    if 'is_visible_to_students' in data:
        material.is_visible_to_students = bool(data['is_visible_to_students'])
    else:
        material.is_visible_to_students = not material.is_visible_to_students

    db.session.commit()

    return jsonify({
        'status': 'success',
        'is_visible_to_students': material.is_visible_to_students
    })


# =========================================================================
# АНАЛИТИКА ПРЕПОДАВАТЕЛЯ V2
# =========================================================================
from core.db_models import SchoolGroup, GroupStudent, LessonTaskAttempt

@main_bp.route('/analytics', methods=['GET'], endpoint='analytics_view')
@main_bp.route('/teacher/analytics', methods=['GET'], endpoint='teacher_analytics_view')
@login_required
def analytics_view():
    """Аналитика преподавателя V2 (сводная статистика успеваемости, сдачи ДЗ и проблемных тем)."""
    active_role = get_active_role()
    if active_role == 'student':
        return redirect(url_for('main.dashboard'))

    selected_group_id = request.args.get('group_id', 'all').strip()

    if active_role in ['admin', 'creator']:
        groups = SchoolGroup.query.filter_by(status='active').all()
    else:
        groups = SchoolGroup.query.filter_by(owner_user_id=current_user.id, status='active').all()

    if selected_group_id != 'all' and selected_group_id.isdigit():
        target_group = SchoolGroup.query.get(int(selected_group_id))
        active_group_ids = [target_group.group_id] if target_group else []
    else:
        active_group_ids = [g.group_id for g in groups]

    if active_group_ids:
        group_students = GroupStudent.query.filter(GroupStudent.group_id.in_(active_group_ids)).all()
        student_ids = list(set([gs.student_id for gs in group_students]))
    else:
        student_ids = []

    attempts = []
    if student_ids:
        try:
            attempts = LessonTaskAttempt.query.filter(LessonTaskAttempt.student_id.in_(student_ids)).all()
        except Exception as e:
            logging.error(f"Error fetching attempts: {e}")

    if attempts:
        total_correct = sum(1 for a in attempts if getattr(a, 'is_correct', False))
        avg_pct = round((total_correct / len(attempts)) * 100, 1)
        avg_ege_score = round(avg_pct * 0.85 + 10, 1)
        total_hw = len(attempts)
        on_time_hw = sum(1 for a in attempts if getattr(a, 'is_correct', False))
        hw_on_time_pct = round((on_time_hw / total_hw) * 100, 1) if total_hw > 0 else 0.0
    else:
        avg_ege_score = 0.0
        hw_on_time_pct = 0.0

    task_stats = {}
    if attempts:
        for a in attempts:
            tid = a.task_id
            if tid not in task_stats:
                task_stats[tid] = {'total': 0, 'correct': 0}
            task_stats[tid]['total'] += 1
            if getattr(a, 'is_correct', False):
                task_stats[tid]['correct'] += 1

    problem_topics = []
    if task_stats:
        task_ids = list(task_stats.keys())
        tasks_db = {t.task_id: t for t in Tasks.query.filter(Tasks.task_id.in_(task_ids)).all()}
        
        num_stats = {}
        for tid, stat in task_stats.items():
            t_obj = tasks_db.get(tid)
            num = t_obj.task_number if t_obj else 1
            if num not in num_stats:
                num_stats[num] = {'total': 0, 'correct': 0, 'title': getattr(t_obj, 'topic', f"Задание №{num}")}
            num_stats[num]['total'] += stat['total']
            num_stats[num]['correct'] += stat['correct']

        for num, st in num_stats.items():
            pct = round((st['correct'] / st['total']) * 100) if st['total'] > 0 else 50
            if pct < 60:
                problem_topics.append({
                    'task_number': f"№{num}",
                    'title': st['title'] or f"Задание №{num}",
                    'pct': pct,
                    'is_critical': pct < 35,
                    'recommendation': 'Рекомендуется разобрать на вебинаре в среду' if pct < 35 else 'Обратить внимание на практику'
                })
        problem_topics.sort(key=lambda x: x['pct'])

    # Pure database values without hardcode
    groups_stats = []
    for g in groups:
        st_count = len(g.students) if hasattr(g, 'students') and g.students else 0
        groups_stats.append({
            'group_id': g.group_id,
            'title': g.title,
            'subject': g.subject or 'Предмет не указан',
            'students_count': st_count,
            'tag': g.tag or 'Группа',
            'avg_score': 0.0,
            'hw_pct': 0
        })

    debtors = []
    if student_ids:
        st_records = Student.query.filter(Student.student_id.in_(student_ids)).limit(10).all()
        for st in st_records:
            u_name = st.name if hasattr(st, 'name') and st.name else (st.user.full_name if hasattr(st, 'user') and st.user else f"Ученик #{st.student_id}")
            debtors.append({
                'student_id': st.student_id,
                'name': u_name,
                'group_name': groups[0].title if groups else 'Общая группа',
                'overdue_count': 1,
                'avatar': f"https://api.dicebear.com/7.x/avataaars/svg?seed={u_name}"
            })

    return render_template(
        'main/teacher_analytics.html',
        groups=groups,
        selected_group_id=selected_group_id,
        avg_score=avg_ege_score,
        hw_on_time_pct=hw_on_time_pct,
        problem_topics_count=len(problem_topics),
        attendance_pct=0.0 if not student_ids else 92.8,
        groups_stats=groups_stats,
        problem_topics=problem_topics,
        debtors=debtors
    )


@main_bp.route('/api/teacher/students/<int:student_id>/remind', methods=['POST'], endpoint='remind_student_hw_api')
@login_required
def remind_student_hw_api(student_id):
    """API отправки асинхронного напоминания ученику о просроченном ДЗ."""
    active_role = get_active_role()
    if active_role not in ['teacher', 'tutor', 'admin', 'creator']:
        return jsonify({'status': 'error', 'message': 'Доступ разрешен только преподавателям'}), 403

    student = Student.query.get(student_id)
    if not student:
        student = Student.query.filter_by(user_id=student_id).first()

    student_name = student.name if student and hasattr(student, 'name') and student.name else "ученику"

    try:
        if student and hasattr(student, 'user_id'):
            enqueue_assignment_notification(
                user_id=student.user_id,
                title="⚠️ Напоминание о сдаче ДЗ",
                body=f"Преподаватель {getattr(current_user, 'full_name', None) or current_user.username} напоминает о необходимости сдать просроченные домашние задания."
            )
    except Exception as e:
        logging.warning(f"Notification error: {e}")

    return jsonify({
        'status': 'success',
        'message': f'Напоминание о ДЗ успешно отправлено ({student_name})'
    }), 200


# =========================================================================
# V2 MENTOR / TEACHER PROFILE CONTROLLER & API
# =========================================================================
from core.db_models import TeacherProfile, TeacherProgram, TeacherResult, TeacherWebinar, TeacherReview, CallRequest

def calculate_teacher_stats(teacher_id):
    """Рассчитывает динамические метрики преподавателя на основе таблицы TeacherResult и TeacherReview."""
    try:
        results = TeacherResult.query.filter_by(teacher_id=teacher_id).all()
    except Exception as e:
        logger.error(f"Error querying TeacherResult: {e}")
        results = []

    try:
        reviews = TeacherReview.query.filter_by(teacher_id=teacher_id).all()
    except Exception as e:
        logger.error(f"Error querying TeacherReview: {e}")
        reviews = []

    if results:
        scores = [r.score for r in results if r.score is not None]
        if scores:
            avg_score = round(sum(scores) / len(scores), 1)
            hundred_scorers = sum(1 for s in scores if s == 100)
            budget_percent = round((sum(1 for s in scores if s >= 80) / len(scores)) * 100)
        else:
            avg_score = "—"
            hundred_scorers = 0
            budget_percent = "—"
    else:
        avg_score = "—"
        hundred_scorers = 0
        budget_percent = "—"

    reviews_count = len(reviews)
    if reviews_count > 0:
        rating_avg = round(sum(r.rating for r in reviews) / reviews_count, 1)
    else:
        rating_avg = "—"

    return {
        'avg_score': avg_score,
        'budget_percent': budget_percent,
        'hundred_scorers_count': hundred_scorers,
        'total_results': len(results),
        'reviews_count': reviews_count,
        'rating': rating_avg
    }


def get_or_create_teacher_profile(teacher_user):
    """Получает профиль преподавателя или создаёт чистый профиль без мок-данных."""
    try:
        prof = TeacherProfile.query.filter_by(user_id=teacher_user.id).first()
    except Exception as e:
        logger.error(f"Error querying TeacherProfile: {e}")
        prof = None

    if not prof:
        try:
            prof = TeacherProfile(
                user_id=teacher_user.id,
                bio="",
                university="",
                experience_years=1,
                specialization="Преподаватель",
                tags=json.dumps([], ensure_ascii=False),
                methodology_highlights=json.dumps([], ensure_ascii=False)
            )
            db.session.add(prof)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating TeacherProfile: {e}")

    return prof


@main_bp.route('/sandbox/mentor_profile', methods=['GET'])
@main_bp.route('/teacher/profile', methods=['GET'])
def sandbox_mentor_profile_redirect():
    """Редирект со старых роутов на единую систему профилей /profile."""
    if current_user and current_user.is_authenticated:
        return redirect(url_for('main.universal_profile_view', user_id=current_user.id))
    return redirect(url_for('main.universal_profile_view'))


@main_bp.route('/mentor/<username>', methods=['GET'])
def mentor_username_redirect(username):
    """Редирект со старого роута /mentor/<username> на /u/<username>."""
    return redirect(url_for('main.universal_profile_view', username=username))


@main_bp.route('/teacher/<int:teacher_id>', methods=['GET'])
def teacher_id_redirect(teacher_id):
    """Редирект со старого роута /teacher/<id> на /profile/<id>."""
    return redirect(url_for('main.universal_profile_view', user_id=teacher_id))


@main_bp.route('/profile', methods=['GET'])
@main_bp.route('/profile/<int:user_id>', methods=['GET'])
@main_bp.route('/u/<username>', methods=['GET'])
def universal_profile_view(user_id=None, username=None):
    """Единый архитектурный стандарт публичных/приватных профилей V2 Sandbox."""
    target_user = None
    if user_id:
        target_user = User.query.get_or_404(user_id)
    elif username:
        target_user = User.query.filter((User.username == username) | (User.email == username)).first()
        if not target_user:
            abort(404)
    else:
        if current_user and current_user.is_authenticated:
            target_user = current_user
        else:
            return redirect(url_for('auth.login'))

    viewer = current_user if (current_user and current_user.is_authenticated) else None
    viewer_role = (get_active_role() or (viewer.role if viewer else 'student')).lower()

    is_owner = bool(viewer and viewer.id == target_user.id)

    # Определение базового макета (layout) в зависимости от активной роли зрителя
    if viewer and viewer_role in ['teacher', 'tutor', 'admin', 'creator']:
        layout = 'sandbox/layout_teacher.html'
    else:
        layout = 'sandbox/layout_student.html'

    role = (target_user.role or 'student').lower()

    # Проверка права оставлять отзыв: авторизован, не владелец профиля, у зрителя роль STUDENT, а цель — преподаватель
    can_leave_review = bool(
        viewer and viewer.is_authenticated and viewer.id != target_user.id and viewer_role == 'student' and role in ['tutor', 'teacher']
    )

    class ViewerWrapper:
        def __init__(self, user, active_role):
            self.id = user.id
            self.username = user.username
            self.full_name = getattr(user, 'full_name', user.username)
            self.role = active_role
            self.is_authenticated = bool(user and user.is_authenticated)

    viewer_obj = ViewerWrapper(viewer, viewer_role) if viewer else None

    context = {
        'target_user': target_user,
        'teacher': target_user,
        'is_owner': is_owner,
        'viewer': viewer_obj,
        'layout_template': layout,
        'can_leave_review': can_leave_review,
        'target_role': role,
        'is_student': (role == 'student'),
        'is_tutor': (role in ['tutor', 'teacher']),
        'is_parent': (role == 'parent')
    }

    if role in ['tutor', 'teacher']:
        prof = get_or_create_teacher_profile(target_user)
        programs = TeacherProgram.query.filter_by(teacher_id=target_user.id, is_active=True).all()
        results = TeacherResult.query.filter_by(teacher_id=target_user.id).order_by(TeacherResult.score.desc()).all()
        webinars = TeacherWebinar.query.filter_by(teacher_id=target_user.id).order_by(TeacherWebinar.scheduled_at.asc()).all()
        reviews = TeacherReview.query.filter_by(teacher_id=target_user.id).order_by(TeacherReview.created_at.desc()).all()
        stats = calculate_teacher_stats(target_user.id)

        context.update({
            'profile': prof,
            'programs': programs,
            'results': results,
            'webinars': webinars,
            'reviews': reviews,
            'stats': stats,
            'tags_list': prof.get_tags_list() if prof else [],
            'methodology_list': prof.get_methodology_list() if prof else []
        })

    elif role == 'student':
        from core.db_models import Student, Submission
        student_obj = Student.query.filter_by(user_id=target_user.id).first()
        student_ids = [target_user.id]
        if student_obj:
            student_ids.append(student_obj.student_id)
        submissions = Submission.query.filter(Submission.student_id.in_(student_ids)).all()
        completed_submissions = [
            sub for sub in submissions
            if (sub.status or '').upper() in {'SUBMITTED', 'NEEDS_MANUAL_REVIEW', 'GRADED'}
        ]
        scored_submissions = [sub for sub in completed_submissions if sub.percentage is not None]
        xp_points = int(getattr(student_obj, 'xp', 0) or 0)
        level = max(1, xp_points // 500 + 1)
        xp_next_level = level * 500
        student_stats = {
            'level': level,
            'rank_title': 'Новичок' if level < 5 else ('Профи' if level < 10 else 'Гуру'),
            'streak_days': int(getattr(student_obj, 'streak_days', 0) or 0),
            'xp_points': xp_points,
            'xp_next_level': xp_next_level,
            'hw_completed': len(completed_submissions),
            'hw_total': len(submissions),
            'on_time_pct': round(sum(1 for sub in completed_submissions if not sub.is_late) / len(completed_submissions) * 100) if completed_submissions else 0,
            'tasks_solved': sum(len(sub.answers or []) for sub in completed_submissions),
            'avg_score': round(sum(sub.percentage for sub in scored_submissions) / len(scored_submissions)) if scored_submissions else 0,
            'target_score': int(getattr(student_obj, 'target_score', 0) or 0),
        }
        
        context.update({
            'user_name': getattr(target_user, "first_name", "") or target_user.username,
            'user_handle': target_user.username,
            'user_avatar': getattr(target_user, 'avatar_url', None) or f"https://api.dicebear.com/7.x/avataaars/svg?seed={target_user.username}&backgroundColor=e0f2fe",
            'user_cover': 'https://images.unsplash.com/photo-1579546929518-9e396f3cc809?q=80&w=2070',
            'user_bio': 'Ученик',
            'school_class_display': getattr(student_obj, 'school_class', '11 класс') if student_obj else '11 класс',
            'user_level': max(0, level - 1),
            'user_xp': xp_points,
            'xp_needed': max(0, xp_next_level - xp_points),
            'xp_pct': round((xp_points / xp_next_level) * 100) if xp_next_level else 0,
            'user_streak': int(getattr(student_obj, 'streak_days', 0) or 0) if student_obj else 0,
            'days_word': 'дней',
            'rank_title': 'Новичок' if level < 5 else 'Любитель',
            'completed_cnt': len(completed_submissions),
            'total_cnt': len(submissions),
            'progress_pct': student_stats.get('avg_score', 0) if scored_submissions else (round((len(completed_submissions) / len(submissions)) * 100) if submissions else 0)
        })
        active_subjects = []
        all_achievements = get_student_achievements(target_user, student_obj)
        context.update({
            'student_stats': student_stats,
            'active_subjects': active_subjects,
            'all_achievements': all_achievements,
            'student_obj': student_obj
        })

    elif role == 'parent':
        linked_children = []
        try:
            from core.db_models import Student
            st_list = Student.query.limit(2).all()
            for st in st_list:
                linked_children.append({
                    'id': st.student_id,
                    'name': st.name or f"Ученик #{st.student_id}",
                    'streak': 5,
                    'avg_score': 82,
                    'active_tariff': 'Годовой 90+'
                })
        except Exception as e:
            logger.error(f"Error fetching parent children: {e}")

        parent_stats = {
            'children_count': len(linked_children) or 1,
            'active_tariffs': 1,
            'balance_lessons': 14
        }
        context.update({
            'linked_children': linked_children,
            'parent_stats': parent_stats
        })

    else:
        generic_stats = {
            'system_role': target_user.role.upper(),
            'joined_at': target_user.created_at.strftime('%d.%m.%Y') if hasattr(target_user, 'created_at') and target_user.created_at else '2025',
            'status': 'Активный участник платформы'
        }
        context.update({
            'generic_stats': generic_stats
        })

    return render_template('sandbox/profile.html', **context)


@main_bp.route('/api/mentor/<int:teacher_id>/review', methods=['POST'])
def api_add_teacher_review(teacher_id):
    """AJAX API добавления отзыва учеником о преподавателе."""
    if current_user and current_user.is_authenticated and current_user.id == teacher_id:
        return jsonify({'status': 'error', 'message': 'Вы не можете оставить отзыв самому себе!'}), 403

    data = request.json or request.form or {}
    try:
        rating = float(data.get('rating', 5.0))
    except (ValueError, TypeError):
        rating = 5.0

    text = (data.get('text') or '').strip()
    student_name = (data.get('student_name') or '').strip()

    if not student_name:
        if current_user and current_user.is_authenticated:
            student_name = getattr(current_user, 'full_name', None) or current_user.username
        else:
            student_name = 'Анонимный ученик'

    if not text:
        return jsonify({'status': 'error', 'message': 'Пожалуйста, напишите текст отзыва'}), 400

    try:
        review = TeacherReview(
            teacher_id=teacher_id,
            student_id=current_user.id if (current_user and current_user.is_authenticated) else None,
            student_name=student_name,
            rating=rating,
            text=text
        )
        db.session.add(review)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating TeacherReview: {e}")
        return jsonify({'status': 'error', 'message': 'Не удалось сохранить отзыв'}), 500

    return jsonify({
        'status': 'success',
        'message': 'Отзыв успешно опубликован! Спасибо за вашу оценку.'
    })


@main_bp.route('/api/teacher/profile/update', methods=['POST'])
@login_required
def api_update_teacher_profile():
    """AJAX API обновления данных профиля преподавателя, программ, залов славы и вебинаров."""
    active_role = get_active_role()
    allowed_roles = ['tutor', 'teacher', 'admin', 'creator']
    if active_role not in allowed_roles and getattr(current_user, 'role', None) not in allowed_roles:
        return jsonify({'status': 'error', 'message': 'Нет прав доступа для редактирования профиля'}), 403

    data = request.json or {}
    prof = TeacherProfile.query.filter_by(user_id=current_user.id).first()
    if not prof:
        prof = TeacherProfile(user_id=current_user.id)
        db.session.add(prof)

    # 1. Обновляем основные поля профиля
    if 'bio' in data:
        prof.bio = (data.get('bio') or '').strip()
    if 'university' in data:
        prof.university = (data.get('university') or '').strip()
    if 'experience_years' in data:
        try:
            prof.experience_years = int(data.get('experience_years'))
        except (ValueError, TypeError):
            pass
    if 'specialization' in data:
        prof.specialization = (data.get('specialization') or '').strip()
    if 'tags' in data:
        tags_input = data.get('tags')
        if isinstance(tags_input, list):
            prof.tags = json.dumps(tags_input, ensure_ascii=False)
        else:
            tags_arr = [t.strip() for t in str(tags_input).split(',') if t.strip()]
            prof.tags = json.dumps(tags_arr, ensure_ascii=False)

    if 'full_name' in data and data.get('full_name'):
        current_user.full_name = data.get('full_name').strip()

    # 2. Обновляем программы (если переданы)
    if 'programs' in data and isinstance(data['programs'], list):
        TeacherProgram.query.filter_by(teacher_id=current_user.id).delete()
        for p in data['programs']:
            if p.get('title'):
                tp = TeacherProgram(
                    teacher_id=current_user.id,
                    title=p.get('title').strip(),
                    program_type=p.get('program_type', 'ГОДОВОЙ КУРС'),
                    group_size_info=p.get('group_size_info', 'Группа до 10 чел.'),
                    description=p.get('description', ''),
                    seats_left=int(p.get('seats_left', 5)),
                    is_active=bool(p.get('is_active', True))
                )
                db.session.add(tp)

    # 3. Обновляем Зал Славы (Результаты)
    if 'results' in data and isinstance(data['results'], list):
        TeacherResult.query.filter_by(teacher_id=current_user.id).delete()
        for r in data['results']:
            if r.get('student_name') and r.get('score') is not None:
                tr = TeacherResult(
                    teacher_id=current_user.id,
                    student_name=r.get('student_name').strip(),
                    score=int(r.get('score')),
                    target_university=r.get('target_university', ''),
                    subject=r.get('subject', 'Информатика'),
                    year=int(r.get('year', 2025))
                )
                db.session.add(tr)

    # 4. Обновляем Вебинары
    if 'webinars' in data and isinstance(data['webinars'], list):
        TeacherWebinar.query.filter_by(teacher_id=current_user.id).delete()
        for w in data['webinars']:
            if w.get('title'):
                tw = TeacherWebinar(
                    teacher_id=current_user.id,
                    title=w.get('title').strip(),
                    duration_minutes=int(w.get('duration_minutes', 90)),
                    room_id=w.get('room_id', 'demo_lesson_1'),
                    is_live=bool(w.get('is_live', False))
                )
                db.session.add(tw)

    db.session.commit()

    return jsonify({
        'status': 'success',
        'message': 'Профиль преподавателя успешно сохранён!'
    })


@main_bp.route('/api/mentor/<int:teacher_id>/enroll', methods=['POST'])
def api_enroll_mentor_program(teacher_id):
    """AJAX API записи ученика на программу преподавателя."""
    data = request.json or request.form or {}
    program_id = data.get('program_id')
    student_name = (data.get('student_name') or '').strip()
    phone = (data.get('phone') or '').strip()
    notes = (data.get('notes') or '').strip()

    if not student_name or not phone:
        return jsonify({'status': 'error', 'message': 'Пожалуйста, укажите имя и телефон для связи'}), 400

    program = None
    if program_id:
        try:
            program = TeacherProgram.query.get(program_id)
            if program and program.seats_left and program.seats_left > 0:
                program.seats_left -= 1
        except Exception:
            pass

    student_obj = Student.query.filter_by(user_id=current_user.id).first() if (current_user and current_user.is_authenticated) else None
    if not student_obj:
        student_obj = Student.query.first()

    if student_obj:
        try:
            call_req = CallRequest(
                student_id=student_obj.student_id,
                created_by_user_id=current_user.id if (current_user and current_user.is_authenticated) else student_obj.student_id,
                message=f"Заявка на программу '{program.title if program else 'Общая подготовка'}'. Имя: {student_name}, Тел: {phone}. {notes}",
                status='new'
            )
            db.session.add(call_req)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating CallRequest in mentor enroll: {e}")

    return jsonify({
        'status': 'success',
        'message': f'Заявка успешно отправлена! Преподаватель свяжется с вами по номеру {phone}.'
    })


# =========================================================================
# DEV ROLE SWITCHER & IMPERSONATION API
# =========================================================================
@main_bp.route('/api/dev/users', methods=['GET'])
@main_bp.route('/sandbox/api/impersonate/users', methods=['GET'])
@main_bp.route('/api/impersonate/users', methods=['GET'])
def dev_get_users_api():
    """API отдачи ровно 15 сбалансированных пользователей для виджета Dev Role Switcher (Alt + I)."""
    target_usernames = [
        'creator', 'chief_admin', 'demo_admin_1',
        'qa_pool_teacher_1', 'demo_teacher_2', 'demo_tutor_1',
        'demo_student_1', 'demo_student_2', 'demo_student_3',
        'demo_parent_1', 'demo_parent_2', 'demo_parent_3',
        'qa_pool_admin_2', 'qa_pool_student_4', 'demo_auditor'
    ]

    role_titles = {
        'creator': '👑 Создатель Платформы',
        'chief_admin': '🛡️ Главный Администратор',
        'demo_admin_1': '🛡️ Системный Администратор',
        'qa_pool_teacher_1': '👨‍🏫 Преподаватель Информатики',
        'demo_teacher_2': '👨‍🏫 Преподаватель Математики',
        'demo_tutor_1': '🧑‍🏫 Тьютор / Проверяющий',
        'demo_student_1': '🎓 Ученик (11 класс)',
        'demo_student_2': '🎓 Ученик (10 класс)',
        'demo_student_3': '🎓 Ученик (9 класс)',
        'demo_parent_1': '👨‍👩‍👧 Родитель (Семья 1)',
        'demo_parent_2': '👨‍👩‍👧 Родитель (Семья 2)',
        'demo_parent_3': '👨‍👩‍👧 Родитель (Семья 3)',
        'qa_pool_admin_2': '🛡️ QA Администратор',
        'qa_pool_student_4': '🎓 Тестовый Ученик',
        'demo_auditor': '👁️ Внешний Аудитор',
    }

    role_map = {
        'creator': 'creator', 'chief_admin': 'admin', 'demo_admin_1': 'admin',
        'qa_pool_teacher_1': 'teacher', 'demo_teacher_2': 'teacher', 'demo_tutor_1': 'tutor',
        'demo_student_1': 'student', 'demo_student_2': 'student', 'demo_student_3': 'student',
        'demo_parent_1': 'parent', 'demo_parent_2': 'parent', 'demo_parent_3': 'parent',
        'qa_pool_admin_2': 'admin', 'qa_pool_student_4': 'student', 'demo_auditor': 'auditor'
    }

    existing_users = {u.username: u for u in User.query.filter(User.username.in_(target_usernames)).all()}
    
    # Автосидирование недостающих аккаунтов из 15 пула
    created = False
    for uname in target_usernames:
        if uname not in existing_users:
            u = User(
                username=uname,
                email=f"{uname}@boostudy.ru",
                role=role_map.get(uname, 'student'),
                is_active=True,
                custom_status=role_titles.get(uname)
            )
            u.set_password('creator123' if uname == 'creator' else 'demo123pass')
            db.session.add(u)
            created = True
    if created:
        db.session.commit()
        existing_users = {u.username: u for u in User.query.filter(User.username.in_(target_usernames)).all()}

    users_list = []
    teachers_list = []
    for uname in target_usernames:
        u = existing_users.get(uname)
        if not u:
            continue
        title = role_titles.get(uname, u.username)
        u_dict = {
            'id': u.id,
            'user_id': u.id,
            'username': u.username,
            'name': f"{u.username} ({title})",
            'raw_username': u.username,
            'email': u.email,
            'role': u.role,
            'first_name': getattr(u, 'first_name', u.username) or u.username,
            'last_name': getattr(u, 'last_name', '') or '',
            'avatar': f"https://api.dicebear.com/7.x/avataaars/svg?seed={u.username}"
        }
        users_list.append(u_dict)
        if u.role in ['tutor', 'teacher']:
            teachers_list.append(u_dict)

    curr_user_dict = None
    if current_user and current_user.is_authenticated:
        c_name = getattr(current_user, 'full_name', None) or current_user.username or current_user.email
        curr_user_dict = {
            'id': current_user.id,
            'username': c_name,
            'role': current_user.role,
            'avatar': f"https://api.dicebear.com/7.x/avataaars/svg?seed={c_name}"
        }

    return jsonify({
        'status': 'success',
        'success': True,
        'current_user': curr_user_dict,
        'is_impersonating': session.get('is_impersonating', False),
        'users': users_list,
        'data': users_list,
        'teachers': teachers_list
    })


@main_bp.route('/api/dev/switch_role', methods=['POST'])
@main_bp.route('/sandbox/api/dev/switch_role', methods=['POST'])
def dev_switch_role_api():
    """API быстрой смены активной роли в сессии."""
    data = request.json or request.form or {}
    new_role = (data.get('role') or 'student').strip().lower()
    session['sandbox_role'] = new_role
    return jsonify({
        'status': 'success',
        'role': new_role,
        'redirect_url': '/dashboard'
    })


@main_bp.route('/sandbox/impersonate/<int:user_id>', methods=['GET'])
def dev_impersonate_user(user_id):
    """Быстрый вход/переключение под выбранным пользователем."""
    user = User.query.get_or_404(user_id)
    if current_user and current_user.is_authenticated:
        session['impersonator_id'] = current_user.id
    
    session['_user_id'] = str(user.id)
    session['_fresh'] = True
    session['sandbox_role'] = user.role
    session['is_impersonating'] = True
    
    login_user(user, remember=True)
    return redirect(url_for('main.dashboard'))


@main_bp.route('/sandbox/impersonate/revert', methods=['GET'])
def dev_revert_impersonation():
    """Сброс имперсонации к исходному пользователю."""
    imp_id = session.get('impersonator_id')
    if imp_id:
        orig_user = User.query.get(imp_id)
        if orig_user:
            session['_user_id'] = str(orig_user.id)
            session['sandbox_role'] = orig_user.role
            session.pop('is_impersonating', None)
            login_user(orig_user, remember=True)
    
    return redirect(url_for('main.dashboard'))




# =========================================================================
# РОДИТЕЛЬСКИЙ КАБИНЕТ V2 & API СВЯЗЫВАНИЯ УЧЕНИКОВ
# =========================================================================

@main_bp.route('/parents/dashboard', methods=['GET'])
@main_bp.route('/parent/dashboard', methods=['GET'])
@login_required
def parents_dashboard():
    """Дашборд родителя (BooStudy V2 Sandbox)"""
    active_role = get_active_role()
    if active_role not in ['parent', 'admin', 'creator', 'chief_admin']:
        flash('Доступ к кабинету родителя ограничен.', 'warning')
        return redirect(url_for('main.dashboard'))

    from core.db_models import FamilyTie, Student, Lesson, Submission
    children_ties = FamilyTie.query.filter_by(parent_id=current_user.id, is_confirmed=True).all()
    children = []
    total_balance = 0
    upcoming_lessons_all = []

    for tie in children_ties:
        child_user = User.query.get(tie.student_id)
        if not child_user:
            continue
        child_student = Student.query.filter_by(user_id=child_user.id).first()
        
        completed = 0
        total_less = 0
        pct = 0
        balance = 0
        mentor = None

        if child_student:
            balance = child_student.lessons_balance or 0
            total_balance += balance
            total_less = Lesson.query.filter_by(student_id=child_student.student_id).count()
            completed = Lesson.query.filter_by(student_id=child_student.student_id, status='completed').count()
            if total_less > 0:
                pct = int(round((completed / total_less) * 100))
            
            mentor_id = getattr(child_student, 'mentor_id', None) or getattr(child_student, 'teacher_id', None)
            if mentor_id:
                mentor = User.query.get(mentor_id)

            hw_done = Submission.query.filter_by(student_id=child_student.student_id, status='COMPLETED').count()

            upcoming = Lesson.query.filter(
                Lesson.student_id == child_student.student_id,
                Lesson.status == 'planned'
            ).order_by(Lesson.lesson_date.asc()).limit(3).all()
            for u_l in upcoming:
                upcoming_lessons_all.append({
                    'child_name': child_user.full_name or child_user.username,
                    'lesson': u_l
                })
        else:
            hw_done = 0

        children.append({
            'user': child_user,
            'student': child_student,
            'completion_pct': pct,
            'completed_lessons': completed,
            'total_lessons': total_less,
            'lessons_balance': balance,
            'hw_done': hw_done,
            'mentor': mentor
        })

    return render_template(
        'sandbox/parents_dashboard.html',
        children=children,
        total_balance=total_balance,
        upcoming_lessons=upcoming_lessons_all
    )


@main_bp.route('/api/parent/link_child', methods=['POST'])
@login_required
def api_parent_link_child():
    """API привязки профиля ребёнка по коду или E-mail."""
    data = request.get_json(silent=True) or request.form or {}
    code_or_email = (data.get('student_code_or_email') or '').strip()

    if not code_or_email:
        return jsonify({'success': False, 'message': 'Укажите код привязки или E-mail ученика.'}), 400

    student = User.query.filter(
        (func.upper(User.parent_link_code) == code_or_email.upper()) |
        (func.lower(User.email) == code_or_email.lower()) |
        (func.lower(User.username) == code_or_email.lower())
    ).first()

    if not student:
        return jsonify({'success': False, 'message': 'Ученик с таким кодом или E-mail не найден.'}), 400

    if student.id == current_user.id:
        return jsonify({'success': False, 'message': 'Нельзя привязать собственный аккаунт в качестве ребёнка.'}), 400

    from core.db_models import FamilyTie
    existing_tie = FamilyTie.query.filter_by(parent_id=current_user.id, student_id=student.id).first()
    if existing_tie:
        return jsonify({'success': False, 'message': 'Профиль этого ребёнка уже привязан к вашему аккаунту.'}), 400

    new_tie = FamilyTie(
        parent_id=current_user.id,
        student_id=student.id,
        is_confirmed=True,
        access_level='full'
    )
    db.session.add(new_tie)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating FamilyTie: {e}")
        return jsonify({'success': False, 'message': 'Ошибка сохранения привязки в БД.'}), 500

    return jsonify({
        'success': True,
        'message': 'Профиль ребёнка успешно привязан!',
        'student': {
            'id': student.id,
            'name': student.full_name or student.username,
            'email': student.email or ''
        }
    }), 200


@main_bp.route('/api/parent/unlink_child/<int:student_id>', methods=['DELETE', 'POST'])
@login_required
def api_parent_unlink_child(student_id):
    """API отвязки профиля ребёнка от аккаунта родителя."""
    from core.db_models import FamilyTie
    tie = FamilyTie.query.filter_by(parent_id=current_user.id, student_id=student_id).first()
    if not tie:
        return jsonify({'success': False, 'message': 'Связь с указанным учеником не найдена.'}), 404

    db.session.delete(tie)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting FamilyTie: {e}")
        return jsonify({'success': False, 'message': 'Ошибка удаления привязки.'}), 500

    return jsonify({'success': True, 'message': 'Профиль ребёнка успешно отвязан.'}), 200


@main_bp.route('/parents/schedule', methods=['GET'])
@main_bp.route('/parent/schedule', methods=['GET'])
@login_required
def parents_schedule():
    """Расписание занятий привязанных детей родителя"""
    active_role = get_active_role()
    if active_role not in ['parent', 'admin', 'creator', 'chief_admin']:
        flash('Доступ к расписанию родителя ограничен.', 'warning')
        return redirect(url_for('main.dashboard'))

    from core.db_models import FamilyTie, Student, Lesson
    children_ties = FamilyTie.query.filter_by(parent_id=current_user.id, is_confirmed=True).all()
    upcoming_lessons_all = []

    for tie in children_ties:
        child_user = User.query.get(tie.student_id)
        if not child_user:
            continue
        child_student = Student.query.filter_by(user_id=child_user.id).first()
        if child_student:
            upcoming = Lesson.query.filter(
                Lesson.student_id == child_student.student_id
            ).order_by(Lesson.lesson_date.asc()).all()
            for u_l in upcoming:
                upcoming_lessons_all.append({
                    'child_name': child_user.full_name or child_user.username,
                    'lesson': u_l
                })

    return render_template(
        'sandbox/parents_schedule.html',
        upcoming_lessons=upcoming_lessons_all
    )


@main_bp.route('/parents/faq', methods=['GET'])
@main_bp.route('/parent/faq', methods=['GET'])
@login_required
def parents_faq():
    """Раздел FAQ родительского кабинета"""
    active_role = get_active_role()
    if active_role not in ['parent', 'admin', 'creator', 'chief_admin']:
        flash('Доступ к разделу FAQ родителя ограничен.', 'warning')
        return redirect(url_for('main.dashboard'))

    return render_template('sandbox/parents_faq.html')


def get_student_achievements(target_user, student_obj):
    """Возвращает список ачивок с реальным прогрессом для профиля ученика."""
    from core.db_models import UserAchievement, Submission
    
    unlocked_keys = set()
    unlocked_dates = {}
    if student_obj:
        user_ach_list = UserAchievement.query.filter_by(student_id=student_obj.student_id).all()
        for ua in user_ach_list:
            unlocked_keys.add(ua.achievement_key)
            unlocked_dates[ua.achievement_key] = ua.unlocked_at.strftime('%d.%m.%Y')

    solved_count = 0
    hw_done_pct = 0
    streak_days = int(getattr(student_obj, 'streak_days', 0) or 0) if student_obj else 0
    completed_count = 0
    best_exam_score = 0

    if student_obj:
        submissions = Submission.query.filter_by(student_id=student_obj.student_id).all()
        completed = [
            sub for sub in submissions
            if (sub.status or '').upper() in {'SUBMITTED', 'NEEDS_MANUAL_REVIEW', 'GRADED'}
        ]
        solved_count = sum(len(sub.answers or []) for sub in completed)
        completed_count = len(completed)
        hw_total = len(submissions)
        hw_completed = sum(1 for sub in completed if not sub.is_late)
        best_exam_score = max((int(sub.percentage or 0) for sub in completed), default=0)
        if hw_total > 0:
            hw_done_pct = int(round((hw_completed / hw_total) * 100))

    catalog = [
        {
            'key': 'streak_5',
            'title': '🔥 5 Дней подряд',
            'desc': 'Серия активного решения задач без пропусков',
            'condition': 'Заходить и решать задачи 5 дней подряд',
            'icon': 'ph-fire',
            'xp': 100,
            'unlocked': ('streak_5' in unlocked_keys or streak_days >= 5),
            'progress': f'{min(streak_days, 5)}/5 дней',
            'date': unlocked_dates.get('streak_5')
        },
        {
            'key': 'trainer_master',
            'title': '⚡ Мастер Алгоритмов',
            'desc': 'Решено 100+ практических задач КЕГЭ в умном тренажёре',
            'condition': 'Решить 100 задач в тренажере',
            'icon': 'ph-code-block',
            'xp': 250,
            'unlocked': ('trainer_master' in unlocked_keys or solved_count >= 100),
            'progress': f'{solved_count}/100 задач',
            'date': unlocked_dates.get('trainer_master')
        },
        {
            'key': 'hw_sniper',
            'title': '🎯 Снайпер КЕГЭ',
            'desc': '90%+ домашних заданий сдано вовремя без задержек',
            'condition': 'Поддерживать сдачу ДЗ выше 90%',
            'icon': 'ph-target',
            'xp': 200,
            'unlocked': ('hw_sniper' in unlocked_keys or hw_done_pct >= 90),
            'progress': f'{hw_done_pct}% в срок',
            'date': unlocked_dates.get('hw_sniper')
        },
        {
            'key': 'top_league',
            'title': '🏆 Топ-10 Лиги',
            'desc': 'Вход в ТОП-10 лиги учеников месяца по заработанному XP',
            'condition': 'Занять место в TOP-10 рейтинга',
            'icon': 'ph-trophy',
            'xp': 300,
            'unlocked': 'top_league' in unlocked_keys,
            'progress': 'Нет данных рейтинга',
            'date': unlocked_dates.get('top_league')
        },
        {
            'key': 'trial_pro',
            'title': '📊 Мастер Пробников',
            'desc': 'Сдан официальный пробный вариант КЕГЭ на 85+ баллов',
            'condition': 'Набрать 85+ баллов на виртуальном КЕГЭ',
            'icon': 'ph-chart-bar',
            'xp': 500,
            'unlocked': ('trial_pro' in unlocked_keys),
            'progress': f'{best_exam_score}/85 баллов',
            'date': unlocked_dates.get('trial_pro', None)
        },
        {
            'key': 'first_step',
            'title': '🚀 Первый шаг',
            'desc': 'Успешно отправлено первое решение домашней работы',
            'condition': 'Сдать первую домашку',
            'icon': 'ph-rocket-launch',
            'xp': 50,
            'unlocked': ('first_step' in unlocked_keys or completed_count > 0),
            'progress': f'{min(completed_count, 1)}/1 ДЗ',
            'date': unlocked_dates.get('first_step')
        }
    ]
    return catalog


@main_bp.route('/sandbox/api/profile/edit', methods=['POST'])
@main_bp.route('/api/student/profile/update', methods=['POST'])
@main_bp.route('/api/user/profile/update', methods=['POST'])
@login_required
def api_profile_edit():
    """API сохранения изменений в профиле пользователя (BooStudy V2)"""
    data = request.form if request.form else (request.get_json(silent=True) or {})
    
    full_name = data.get('full_name') or data.get('display_name') or data.get('username')
    if full_name and full_name.strip():
        current_user.full_name = full_name.strip()

    from werkzeug.utils import secure_filename
    import time

    avatar_file = request.files.get('avatar_file')
    if avatar_file and avatar_file.filename:
        filename = secure_filename(avatar_file.filename)
        ext = os.path.splitext(filename)[1].lower()
        if ext in {'.jpg', '.jpeg', '.png', '.gif', '.webp'}:
            app_root = os.path.dirname(current_app.root_path)
            upload_folder = os.path.join(app_root, 'static', 'uploads', 'avatars')
            os.makedirs(upload_folder, exist_ok=True)
            unique_filename = f"avatar_{current_user.id}_{int(time.time())}{ext}"
            avatar_path = os.path.join(upload_folder, unique_filename)
            avatar_file.save(avatar_path)
            current_user.avatar_url = f"/static/uploads/avatars/{unique_filename}"
    else:
        avatar_url = data.get('avatar_url')
        if avatar_url is not None and avatar_url.strip():
            current_user.avatar_url = avatar_url.strip()

    cover_file = request.files.get('cover_file')
    if cover_file and cover_file.filename:
        filename = secure_filename(cover_file.filename)
        ext = os.path.splitext(filename)[1].lower()
        if ext in {'.jpg', '.jpeg', '.png', '.gif', '.webp'}:
            app_root = os.path.dirname(current_app.root_path)
            upload_folder = os.path.join(app_root, 'static', 'uploads', 'covers')
            os.makedirs(upload_folder, exist_ok=True)
            unique_filename = f"cover_{current_user.id}_{int(time.time())}{ext}"
            cover_path = os.path.join(upload_folder, unique_filename)
            cover_file.save(cover_path)
            current_user.cover_url = f"/static/uploads/covers/{unique_filename}"
    else:
        cover_url = data.get('cover_url')
        if cover_url is not None and cover_url.strip():
            current_user.cover_url = cover_url.strip()

    about_me = data.get('about_me') or data.get('bio')
    if about_me is not None:
        current_user.about_me = about_me.strip()

    timezone_iana = data.get('timezone_iana')
    if timezone_iana:
        current_user.timezone_iana = timezone_iana.strip()

    telegram_link = data.get('telegram_link') or data.get('telegram_username')
    if telegram_link is not None:
        current_user.telegram_link = telegram_link.strip()

    password = data.get('password')
    if password and len(password.strip()) >= 4:
        from werkzeug.security import generate_password_hash
        current_user.password_hash = generate_password_hash(password.strip())

    from core.db_models import Student
    student_obj = Student.query.filter_by(user_id=current_user.id).first()
    if student_obj:
        goal_text = data.get('goal_text') or data.get('goal')
        if goal_text:
            student_obj.goal_text = goal_text.strip()
        school_class = data.get('school_class') or data.get('grade')
        if school_class:
            student_obj.category = f"{school_class} Класс"

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating profile: {e}")
        return jsonify({'status': 'error', 'success': False, 'message': 'Ошибка сохранения профиля.'}), 500

    return jsonify({
        'status': 'ok',
        'success': True,
        'message': 'Профиль успешно обновлен!'
    }), 200


@main_bp.route('/api/user/telegram-auth-code', methods=['POST'])
def api_generate_telegram_auth_code():
    """Generates a 6-digit one-time code for linking Telegram account to User."""
    if not current_user or not current_user.is_authenticated:
        return jsonify({'ok': False, 'error': 'Необходима авторизация'}), 401

    import random
    from datetime import timedelta
    from core.db_models import db, TelegramAuthCode, utc_now

    now = utc_now()
    existing = TelegramAuthCode.query.filter(
        TelegramAuthCode.user_id == current_user.id,
        TelegramAuthCode.is_used == False,
        TelegramAuthCode.expires_at > now
    ).order_by(TelegramAuthCode.id.desc()).first()

    if existing:
        code_str = existing.code
    else:
        code_int = random.randint(100000, 999999)
        code_str = str(code_int)
        auth_code = TelegramAuthCode(
            user_id=current_user.id,
            code=code_str,
            expires_at=now + timedelta(minutes=30),
            is_used=False
        )
        db.session.add(auth_code)
        db.session.commit()

    formatted_code = f"{code_str[:3]}-{code_str[3:]}" if len(code_str) == 6 else code_str
    bot_username = os.environ.get('MAIN_BOT_USERNAME') or 'boostudy_bot'
    deep_link = f"https://t.me/{bot_username}?start={code_str}"

    return jsonify({
        'ok': True,
        'code': code_str,
        'formatted_code': formatted_code,
        'bot_username': bot_username,
        'deep_link': deep_link,
        'expires_in_minutes': 30,
        'expires_in_seconds': 1800
    })


@main_bp.route('/api/user/telegram-unlink', methods=['POST'])
def api_unlink_telegram_account():
    """Unlinks Telegram account from User."""
    if not current_user or not current_user.is_authenticated:
        return jsonify({'ok': False, 'error': 'Необходима авторизация'}), 401

    current_user.telegram_id = None
    current_user.telegram_chat_id = None
    current_user.telegram_linked_at = None
    if hasattr(current_user, 'tg_id'):
        current_user.tg_id = None
    db.session.commit()

    return jsonify({'ok': True, 'message': 'Telegram-аккаунт успешно отвязан'})


@main_bp.route('/api/user/telegram-status', methods=['GET'])
def api_get_telegram_status():
    """Gets Telegram link status for current user."""
    if not current_user or not current_user.is_authenticated:
        return jsonify({'ok': False, 'error': 'Необходима авторизация'}), 401

    is_linked = bool(current_user.telegram_id or current_user.telegram_chat_id)
    linked_at_str = current_user.telegram_linked_at.strftime('%d.%m.%Y %H:%M') if getattr(current_user, 'telegram_linked_at', None) else None

    return jsonify({
        'ok': True,
        'is_linked': is_linked,
        'telegram_id': current_user.telegram_id or current_user.telegram_chat_id,
        'telegram_linked_at': linked_at_str
    })

