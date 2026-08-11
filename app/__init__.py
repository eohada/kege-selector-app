"""
Инициализация Flask приложения
"""
import os
import logging
import threading
import time
import uuid
import json
from flask import Flask, request, jsonify
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from sqlalchemy import text
from zoneinfo import ZoneInfo  # comment
from datetime import datetime, timezone  # comment
from werkzeug.exceptions import HTTPException
from werkzeug.exceptions import RequestEntityTooLarge

from flask_migrate import Migrate
from app.models import db
from core.audit_logger import audit_logger
from app.models import User, MOSCOW_TZ  # comment
from app.logging_core import configure_logging

csrf = CSRFProtect()
login_manager = LoginManager()
migrate = Migrate()

def create_app(config_name=None):
    """
    Фабрика приложений Flask
    Создает и настраивает экземпляр Flask приложения
    """
    base_dir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    template_dir = os.path.join(base_dir, 'templates')
    static_dir = os.path.join(base_dir, 'static')
    
    app = Flask(__name__, 
                template_folder=template_dir,
                static_folder=static_dir)

    from app.json_provider import BooJSONProvider
    app.json = BooJSONProvider(app)
    
    db_path = os.environ.get('SQLITE_DB_PATH') or os.path.abspath(os.path.join(base_dir, 'instance', 'boostudy_dev.db'))
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    database_url = os.environ.get('DATABASE_URL')
    database_url_source = None
    external_db_url = os.environ.get('DATABASE_EXTERNAL_URL')
    postgres_alt_url = os.environ.get('POSTGRES_URL')

    def _normalize_db_url(url: str | None) -> str | None:
        if not url:
            return None
        url = url.strip()
        if not url:
            return None
        if url.startswith('postgres://'):
            return url.replace('postgres://', 'postgresql://', 1)
        return url

    database_url = _normalize_db_url(database_url)
    external_db_url = _normalize_db_url(external_db_url)
    postgres_alt_url = _normalize_db_url(postgres_alt_url)

    # Priority:
    # 1. DATABASE_EXTERNAL_URL — explicit external override
    # 2. DATABASE_URL          — primary runtime DSN
    # 3. POSTGRES_URL          — legacy fallback only if DATABASE_URL is absent
    selected_database_url = None
    if external_db_url:
        selected_database_url = external_db_url
        database_url_source = 'DATABASE_EXTERNAL_URL'
    elif database_url:
        selected_database_url = database_url
        database_url_source = 'DATABASE_URL'
    elif postgres_alt_url:
        selected_database_url = postgres_alt_url
        database_url_source = 'POSTGRES_URL'

    if selected_database_url:
        database_url = selected_database_url
        app.config['SQLALCHEMY_DATABASE_URI'] = selected_database_url
    else:
        app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
        database_url_source = 'sqlite'
    
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    if selected_database_url and ('postgresql' in selected_database_url or 'postgres' in selected_database_url):
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            'pool_pre_ping': True,
            'pool_recycle': int(os.environ.get('SQLALCHEMY_POOL_RECYCLE', '280')),
        }
    ENVIRONMENT = os.environ.get('ENVIRONMENT', 'local')
    secret_key = os.environ.get('SECRET_KEY')
    if not secret_key:
        if ENVIRONMENT not in ('local', 'development', 'dev'):
            raise RuntimeError(
                f"SECRET_KEY is not set! Refusing to start in '{ENVIRONMENT}' environment. "
                "Set the SECRET_KEY environment variable."
            )
        import secrets as _secrets
        secret_key = _secrets.token_hex(32)
        logging.getLogger(__name__).warning(
            "SECRET_KEY not set — generated a random key. Sessions will reset on restart."
        )
    app.config['SECRET_KEY'] = secret_key
    app.config['WTF_CSRF_ENABLED'] = True
    app.config['WTF_CSRF_TIME_LIMIT'] = None
    app.config['TRAINER_URL'] = (os.environ.get('TRAINER_URL') or '').strip() or None
    app.config['TRAINER_SHARED_SECRET'] = (os.environ.get('TRAINER_SHARED_SECRET') or '').strip() or None
    # The module stays deployed but is closed until the subscription rollout is ready.
    app.config['TRAINER_ENABLED'] = (os.environ.get('TRAINER_ENABLED') or '').strip().lower() in {'1', 'true', 'yes', 'on'}
    app.config['REDIS_URL'] = (
        os.environ.get('REDIS_URL')
        or os.environ.get('CELERY_BROKER_URL')
        or os.environ.get('CELERY_RESULT_BACKEND')
        or ''
    ).strip() or None
    
    app.config['MIRO_ACCESS_TOKEN'] = (os.environ.get('MIRO_ACCESS_TOKEN') or '').strip() or None
    app.config['MIRO_CLIENT_ID'] = (os.environ.get('MIRO_CLIENT_ID') or '').strip() or None
    app.config['MIRO_CLIENT_SECRET'] = (os.environ.get('MIRO_CLIENT_SECRET') or '').strip() or None
    app.config['MIRO_REDIRECT_URI'] = (os.environ.get('MIRO_REDIRECT_URI') or '').strip() or None  # например https://boostudy.ru/auth/miro/callback
    
    app.config['DAILY_API_KEY'] = (os.environ.get('DAILY_API_KEY') or '').strip() or None
    app.config['DAILY_DOMAIN'] = 'urep'  # urep.daily.co
    
    app.config['AVATAR_UPLOAD_ROOT'] = (os.environ.get('AVATAR_UPLOAD_ROOT') or '').strip() or None
    app.config['COVER_UPLOAD_ROOT'] = (os.environ.get('COVER_UPLOAD_ROOT') or '').strip() or None
    app.config['THEORY_UPLOAD_ROOT'] = (os.environ.get('THEORY_UPLOAD_ROOT') or '').strip() or None
    # Материалы уроков должны жить в persistent volume, а не внутри образа web-приложения.
    app.config['LESSON_UPLOAD_ROOT'] = (os.environ.get('LESSON_UPLOAD_ROOT') or '').strip().rstrip(os.sep) or None
    # Корень папки вложений заданий (uploads/task_attachments). На Timeweb можно задать путь к volume.
    app.config['TASK_ATTACHMENTS_ROOT'] = (os.environ.get('TASK_ATTACHMENTS_ROOT') or '').strip().rstrip(os.sep) or None
    # Корень папки вложений ответов учеников (uploads/answer_attachments).
    app.config['ANSWER_ATTACHMENTS_ROOT'] = os.environ.get('ANSWER_ATTACHMENTS_ROOT') or os.path.join(base_dir, 'uploads', 'answer_attachments')

    app.config['MAX_CONTENT_LENGTH'] = None

    app.config['S3_ENDPOINT_URL'] = (os.environ.get('S3_ENDPOINT_URL') or '').strip() or None
    app.config['S3_ACCESS_KEY'] = (os.environ.get('S3_ACCESS_KEY') or '').strip() or None
    app.config['S3_SECRET_KEY'] = (os.environ.get('S3_SECRET_KEY') or '').strip() or None
    app.config['S3_BUCKET'] = (os.environ.get('S3_BUCKET') or '').strip() or 'boostudy'

    app.config['ADMIN_URL'] = (os.environ.get('ADMIN_URL') or '').strip().rstrip('/') or None
    
    app.config['IS_SANDBOX'] = os.environ.get('IS_SANDBOX', 'False').lower() == 'true'
    # Для переключателя Прод ↔ Песочница в QA God Mode (автовход через подписанный токен)
    app.config['PROD_URL'] = (os.environ.get('PROD_URL') or '').strip().rstrip('/') or None
    app.config['SANDBOX_URL'] = (os.environ.get('SANDBOX_URL') or '').strip().rstrip('/') or None
    app.config['CROSS_ENV_LOGIN_SECRET'] = (os.environ.get('CROSS_ENV_LOGIN_SECRET') or '').strip() or None

    # Демо-сайт: отдельный инстанс с отдельной БД (изоляция от прода)
    # Значение: "true" / "1" / "yes" (без учёта регистра и пробелов)
    _demo = (os.environ.get('DEMO_SITE') or '').strip().lower()
    app.config['DEMO_SITE'] = _demo in ('true', '1', 'yes')
    logging.getLogger(__name__).info('DEMO_SITE=%s (env raw=%r)', app.config['DEMO_SITE'], os.environ.get('DEMO_SITE'))
    app.config['DEMO_BASE_URL'] = (os.environ.get('DEMO_BASE_URL') or '').strip().rstrip('/') or None
    # Демо по хосту: если запрос на этот домен — считаем инстанс демо (для одного деплоя с двумя доменами)
    app.config['DEMO_HOST'] = (os.environ.get('DEMO_HOST') or '').strip().lower() or None  # например demo.boostudy.ru
    if app.config['DEMO_SITE']:
        app.config['DEMO_CREATOR_AVATAR_URL'] = (os.environ.get('DEMO_CREATOR_AVATAR_URL') or '').strip() or None
        app.config['DEMO_CREATOR_COVER_URL'] = (os.environ.get('DEMO_CREATOR_COVER_URL') or '').strip() or None
        demo_db_url = _normalize_db_url(os.environ.get('DEMO_DATABASE_URL') or os.environ.get('DATABASE_URL'))
        if demo_db_url:
            app.config['SQLALCHEMY_DATABASE_URI'] = demo_db_url
        # иначе оставляем уже установленный DATABASE_URL выше
    
    logger = configure_logging(base_dir=base_dir, environment=ENVIRONMENT, service_name='boostudy')

    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    csrf.init_app(app)
    db.init_app(app)
    # Keep Alembic independent from the current working directory.  A relative
    # default can make one-off production commands discover zero revisions.
    migrate.init_app(app, db, directory=os.path.join(base_dir, 'migrations'))
    from app.commands.schema import schema_audit_command
    app.cli.add_command(schema_audit_command)
    audit_logger.init_app(app)

    from app.storage import storage as file_storage
    file_storage.init_app(app)

    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Для доступа к системе необходимо войти.'
    login_manager.login_message_category = 'warning'

    ratelimit_enabled = os.environ.get('RATELIMIT_ENABLED', 'true').strip().lower() == 'true'
    app.config['RATELIMIT_ENABLED'] = ratelimit_enabled
    from app.limiter import limiter
    limiter.init_app(app)
    
    @login_manager.user_loader
    def load_user(user_id):
        """Загрузка пользователя для Flask-Login"""
        return User.query.get(int(user_id))

    @app.errorhandler(RequestEntityTooLarge)
    def handle_request_entity_too_large(error):
        payload = {'success': False, 'error': 'Файл слишком большой. Максимум 10MB.'}
        try:
            accepts_json = (
                'application/json' in (request.headers.get('Accept') or '').lower()
                or request.path.startswith('/sandbox/api/')
                or request.path.startswith('/api/')
            )
        except Exception:
            accepts_json = False
        return jsonify(payload), 413

    @app.template_filter('format_dt_tz')  # comment
    def format_dt_tz(dt, tz_name='Europe/Moscow'):  # comment
        """Форматируем datetime в таймзоне пользователя. В БД время обычно хранится как naive MSK."""  # comment
        if not dt:  # comment
            return ''  # comment
        try:  # comment
            tz = ZoneInfo(tz_name or 'Europe/Moscow')  # comment
        except Exception:  # comment
            tz = ZoneInfo('Europe/Moscow')  # comment
        value = dt  # comment
        if isinstance(value, datetime):  # comment
            if value.tzinfo is None:  # comment
                value = value.replace(tzinfo=MOSCOW_TZ)  # comment
            value_local = value.astimezone(tz)  # comment
            return value_local.strftime('%d.%m.%Y %H:%M') + f" ({value_local.tzname() or ''})"  # comment
        return str(value)  # comment

    @app.template_filter('to_tz')  # comment
    def to_tz(dt, tz_name='Europe/Moscow'):  # comment
        """
        Переводим datetime в заданную таймзону и возвращаем timezone-aware datetime.
        У нас в БД `Lesson.lesson_date` обычно хранится как naive MSK.
        Это нужно, чтобы в шаблонах можно было безопасно делать `.strftime()` уже в локальном времени.
        """  # comment
        if not dt:  # comment
            return None  # comment
        try:  # comment
            tz = ZoneInfo(tz_name or 'Europe/Moscow')  # comment
        except Exception:  # comment
            tz = ZoneInfo('Europe/Moscow')  # comment
        value = dt  # comment
        if isinstance(value, datetime):  # comment
            if value.tzinfo is None:  # comment
                value = value.replace(tzinfo=MOSCOW_TZ)  # comment
            return value.astimezone(tz)  # comment
        return dt  # comment

    @app.template_filter('user_dt')
    def user_dt(dt, format_string='%H:%M'):
        """
        Новый стандарт: переводит UTC datetime в локальное время пользователя и форматирует.
        """
        if not dt:
            return ''
        from flask_login import current_user
        try:
            # Получаем IANA-таймзону, по умолчанию Europe/Moscow
            tz_name = getattr(current_user, 'timezone_iana', None)
            if not tz_name:
                profile = getattr(current_user, 'profile', None)
                if profile:
                    tz_name = getattr(profile, 'timezone', None)
            tz = ZoneInfo(tz_name or 'Europe/Moscow')
        except Exception:
            tz = ZoneInfo('Europe/Moscow')
        
        value = dt
        if isinstance(value, datetime):
            if value.tzinfo is None:
                # Согласно новому стандарту БД, naive это UTC
                value = value.replace(tzinfo=timezone.utc)
            value_local = value.astimezone(tz)
            return value_local.strftime(format_string)
        return str(value)
    
    ENVIRONMENT = os.environ.get('ENVIRONMENT', 'local')
    logger.info(f"=== Application Initialization ===")
    logger.info(f"Environment: {ENVIRONMENT}")
    if database_url:
        logger.info(f"Using database source: {database_url_source}")
        logger.info("Database type: PostgreSQL")
        
        try:
            with app.app_context():
                db.session.execute(text("SELECT 1"))
                logger.info("✓ Database connection: OK")
                from app.utils.db_migrations import (
                    ensure_schema_columns,
                    is_auto_db_schema_sync_enabled,
                )
                if is_auto_db_schema_sync_enabled():
                    # Только для одиночного процесса / локали. В multi-worker используйте ``flask db upgrade``.
                    from app.models import Assignment, AssignmentTask, Submission, Answer  # noqa: F401
                    from app.models import LessonWhiteboard  # noqa: F401
                    from app.models import Subject, KnowledgeNode, UserMastery, AnalyticsEvent  # noqa: F401
                    from app.models import TheoryBlock, StudentTheoryAccess  # noqa: F401
                    db.create_all()
                    try:
                        ensure_schema_columns(app)
                        logger.info("✓ Database schema migrations (AUTO_DB_SCHEMA_SYNC): OK")
                    except Exception as mig_error:
                        logger.warning("⚠ Schema migration failed: %s", mig_error)
                        logger.warning(
                            "Application will continue; fix DB with ``flask db upgrade`` "
                            "or retry with AUTO_DB_SCHEMA_SYNC=1 in a single process."
                        )
                else:
                    logger.info(
                        "Database schema auto-sync is disabled (default). "
                        "Apply migrations with ``flask db upgrade``. "
                        "For legacy auto-sync set AUTO_DB_SCHEMA_SYNC=1 (single-worker only)."
                    )
        except Exception as e:
            logger.warning(f"⚠ Database connection check failed: {str(e)}")
            logger.warning("Application will continue, but database operations may fail")
    else:
        logger.warning("DATABASE_URL not set, using SQLite")
        logger.warning("This is likely a local development environment")
        try:
            with app.app_context():
                # Локальная sqlite-сборка должна подхватывать новые таблицы автоматически,
                # иначе свежие модели вроде CodePlaybackTrace ломают workspace на старте.
                db.create_all()
                try:
                    with db.engine.connect() as conn:
                        conn.execute(db.text("ALTER TABLE Students ADD COLUMN mentor_id INTEGER REFERENCES Users(id)"))
                        conn.commit()
                except Exception:
                    pass
                try:
                    with db.engine.connect() as conn:
                        conn.execute(db.text("ALTER TABLE Assignments ADD COLUMN status VARCHAR(30) DEFAULT 'active'"))
                        conn.commit()
                except Exception:
                    pass
                logger.info("✓ Local SQLite schema ensured via db.create_all()")
        except Exception as schema_error:
            logger.warning("⚠ Local SQLite schema bootstrap failed: %s", schema_error)

    logger.info(f"SECRET_KEY set: {'YES' if os.environ.get('SECRET_KEY') else 'NO'}")
    logger.info(f"=== Initialization Complete ===")

    app.config['_WORKSPACE_AUTOSAVE_STARTED'] = False

    @app.before_request
    def _attach_request_id():
        from flask import g, request
        g.request_started_at = time.perf_counter()
        incoming = (request.headers.get('X-Request-ID') or '').strip()
        g.request_id = incoming or uuid.uuid4().hex

    def _agent_debug_log(hypothesis_id: str, message: str, data: dict | None = None, run_id: str = 'run1') -> None:
        # region agent log
        try:
            payload = {
                'sessionId': '14a550',
                'runId': run_id,
                'hypothesisId': hypothesis_id,
                'location': 'app/__init__.py',
                'message': message,
                'data': data or {},
                'timestamp': int(time.time() * 1000),
            }
            with open('debug-14a550.log', 'a', encoding='utf-8') as f:
                f.write(json.dumps(payload, ensure_ascii=False) + '\n')
        except Exception:
            pass
        # endregion

    @app.after_request
    def _log_request(response):
        from flask import g, request
        started = getattr(g, 'request_started_at', None)
        duration_ms = None
        if started is not None:
            duration_ms = int((time.perf_counter() - started) * 1000)
        request_id = getattr(g, 'request_id', None)
        if request_id:
            response.headers['X-Request-ID'] = request_id

        logging.getLogger('http.request').info(
            'http_request',
            extra={
                'event': 'http_request',
                'status': response.status_code,
                'method': request.method,
                'url': request.path,
                'duration_ms': duration_ms,
                'request_id': request_id,
                'trace_id': request_id,
            }
        )
        if response.status_code >= 400:
            _agent_debug_log(
                'H6',
                'http_error_response',
                {
                    'status': response.status_code,
                    'method': request.method,
                    'path': request.path,
                    'duration_ms': duration_ms,
                    'request_id': request_id,
                }
            )
        return response
    
    from app.auth import auth_bp
    from app.main import main_bp
    from app.students import students_bp
    from app.lessons import lessons_bp
    from app.admin import admin_bp
    from app.admin.qa_management import qa_bp as qa_admin_bp
    from app.qa.routes import qa_tester_bp
    from app.qa.api import qa_api_bp
    from app.task_generator import task_generator_bp
    from app.api import api_bp
    from app.schedule import schedule_bp
    from app.templates_manager import templates_bp
    from app.parents import parents_bp
    from app.assignments import assignments_bp
    from app.remote_admin import remote_admin_bp
    from app.courses import courses_bp
    from app.library import library_bp
    from app.groups import groups_bp
    from app.notifications import notifications_bp
    from app.billing import billing_bp
    from app.trainer import trainer_bp
    from app.uploads import uploads_bp
    from app.storage.routes import storage_bp
    from app.chief_tester import chief_tester_bp
    from app.theory import theory_bp
    from app.reminders import reminders_bp
    from app.telegram.webhook import telegram_bp
    from app.telegram.mini_app import tg_app_bp
    from app.routes.webhooks import webhooks_bp
    from app.routes.tma import tma_bp
    from app.workspace import workspace_bp
    from app.task_workspace import task_workspace_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(webhooks_bp)
    app.register_blueprint(tma_bp)
    from app.main.routes import presence_ping as _presence_ping_view
    csrf.exempt(_presence_ping_view)
    app.register_blueprint(students_bp)
    app.register_blueprint(lessons_bp)
    app.register_blueprint(admin_bp)
    from app.admin.impersonate import admin_impersonate_bp
    app.register_blueprint(admin_impersonate_bp)
    
    app.register_blueprint(qa_admin_bp)
    app.register_blueprint(qa_api_bp)
    app.register_blueprint(qa_tester_bp)

    from app.qa.routes import (
        index as qa_tester_index_view,
        get_assigned_test_cases,
        get_test_case_detail,
        get_test_case_steps,
        toggle_test_step,
        fail_test_case_with_report,
        create_bug_report_api,
        get_bug_report_comments,
        add_bug_report_comment,
        update_test_case_status
    )
    app.add_url_rule('/tester', endpoint='tester_workspace_v2', view_func=qa_tester_index_view)
    app.add_url_rule('/api/qa/assigned-test-cases', endpoint='api_qa_assigned_test_cases', view_func=get_assigned_test_cases)
    app.add_url_rule('/api/qa/test-cases/<int:tc_id>', endpoint='api_qa_test_case_detail', view_func=get_test_case_detail, methods=['GET'])
    app.add_url_rule('/api/qa/test-cases/<int:tc_id>/steps', endpoint='api_qa_test_case_steps', view_func=get_test_case_steps)
    app.add_url_rule('/api/qa/test-steps/<int:step_id>/toggle', endpoint='api_qa_test_step_toggle', view_func=toggle_test_step, methods=['POST'])
    app.add_url_rule('/api/qa/test-cases/<int:tc_id>/fail-with-report', endpoint='api_qa_test_case_fail_with_report', view_func=fail_test_case_with_report, methods=['POST'])
    app.add_url_rule('/api/qa/test-cases/<int:tc_id>/status', endpoint='api_qa_test_case_status_post', view_func=update_test_case_status, methods=['POST'])
    app.add_url_rule('/tester/test-cases/<int:tc_id>/status', endpoint='tester_test_case_status_post', view_func=update_test_case_status, methods=['POST'])
    app.add_url_rule('/api/qa/bug-reports/create', endpoint='api_qa_bug_reports_create', view_func=create_bug_report_api, methods=['POST'])
    app.add_url_rule('/api/qa/bug-reports/<int:bug_id>/comments', endpoint='api_qa_bug_report_comments_get', view_func=get_bug_report_comments, methods=['GET'])
    app.add_url_rule('/api/qa/bug-reports/<int:bug_id>/comments', endpoint='api_qa_bug_report_comments_add', view_func=add_bug_report_comment, methods=['POST'])

    # CSRF exceptions for QA AJAX APIs
    csrf.exempt(create_bug_report_api)
    csrf.exempt(add_bug_report_comment)
    csrf.exempt(update_test_case_status)
    csrf.exempt(toggle_test_step)
    csrf.exempt(fail_test_case_with_report)

    # CSRF exceptions for QA AJAX APIs
    from app.qa.routes import upload_video, upload_screenshot
    csrf.exempt(upload_video)
    csrf.exempt(upload_screenshot)

    # Исключаем десктопный API из CSRF проверки
    from app.qa.api import desktop_report
    csrf.exempt(desktop_report)
    app.register_blueprint(task_generator_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(schedule_bp)
    app.register_blueprint(templates_bp)
    app.register_blueprint(parents_bp)
    app.register_blueprint(assignments_bp)
    app.register_blueprint(remote_admin_bp)
    app.register_blueprint(courses_bp)
    app.register_blueprint(library_bp)
    app.register_blueprint(groups_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(trainer_bp)
    app.register_blueprint(uploads_bp)
    app.register_blueprint(storage_bp)
    
    app.register_blueprint(chief_tester_bp)
    app.register_blueprint(theory_bp)
    app.register_blueprint(reminders_bp)
    app.register_blueprint(telegram_bp)
    app.register_blueprint(tg_app_bp)
    app.register_blueprint(workspace_bp)
    app.register_blueprint(task_workspace_bp)

    try:
        from app.utils.dev_logger import init_dev_logger
        init_dev_logger(app)
    except Exception as dev_err:
        logger.warning(f"Could not init dev_logger: {dev_err}")

    try:
        from flask_socketio import SocketIO
        
        # Select async mode dynamically: 'eventlet' only if eventlet monkey patching is active, otherwise 'threading'
        async_mode = 'threading'
        try:
            import eventlet
            if eventlet.patcher.is_monkey_patched('socket'):
                async_mode = 'eventlet'
        except ImportError:
            pass

        socketio = SocketIO(
            app,
            async_mode=async_mode,
            cors_allowed_origins='*',
            logger=False,
            engineio_logger=False,
        )
        app.socketio = socketio
        from app.main.sandbox_socket import register_sandbox_socket
        register_sandbox_socket(socketio)
        from app.lessons.lesson_socket import register_lesson_socket
        register_lesson_socket(socketio)
        from app.task_workspace.socket import register_task_workspace_socket
        register_task_workspace_socket(socketio)
        from app.main.presence_socket import register_presence_socket
        register_presence_socket(socketio)
    except ImportError as e:
        app.socketio = None
        logging.getLogger(__name__).warning("Flask-SocketIO not available (install flask-socketio): %s", e)

    def _start_assignment_notification_worker() -> None:
        if app.config.get('_ASSIGNMENT_NOTIFY_WORKER_STARTED'):
            return
        poll_seconds = int(os.environ.get('ASSIGNMENT_NOTIFY_POLL_SECONDS', '60'))
        debounce_seconds = int(os.environ.get('ASSIGNMENT_NOTIFY_DEBOUNCE_SECONDS', '300'))

        def worker():
            while True:
                try:
                    with app.app_context():
                        from app.notifications.service import process_pending_assignment_notifications
                        process_pending_assignment_notifications(debounce_seconds=debounce_seconds)
                except Exception as e:
                    try:
                        app.logger.warning(f"Assignment notification worker error: {e}")
                    except Exception:
                        pass
                time.sleep(poll_seconds)

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        app.config['_ASSIGNMENT_NOTIFY_WORKER_STARTED'] = True

    background_workers_enabled = str(os.environ.get('DISABLE_BACKGROUND_WORKERS', '')).strip().lower() not in {'1', 'true', 'yes', 'on'}
    if background_workers_enabled:
        _start_assignment_notification_worker()

    def _start_lesson_auto_complete_worker() -> None:
        if app.config.get('_LESSON_AUTO_COMPLETE_WORKER_STARTED'):
            return
        poll_seconds = int(os.environ.get('LESSON_AUTO_COMPLETE_POLL_SECONDS', '10'))

        def worker():
            while True:
                try:
                    with app.app_context():
                        from app.lessons.routes import auto_complete_overdue_lessons
                        n = auto_complete_overdue_lessons()
                        if n:
                            app.logger.info(f"Auto-completed {n} overdue lesson(s)")
                except Exception as e:
                    try:
                        app.logger.warning(f"Lesson auto-complete worker error: {e}")
                    except Exception:
                        pass
                time.sleep(poll_seconds)

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        app.config['_LESSON_AUTO_COMPLETE_WORKER_STARTED'] = True

    if background_workers_enabled:
        _start_lesson_auto_complete_worker()

    from app.auth.routes import logout
    csrf.exempt(logout)
    
    from app.admin.routes import maintenance_status_api
    csrf.exempt(maintenance_status_api)

    from app.api.routes import api_telegram_link_bot, api_internal_telegram_dispatch
    csrf.exempt(api_telegram_link_bot)
    csrf.exempt(api_internal_telegram_dispatch)

    from app.telegram.webhook import telegram_webhook, set_webhook
    csrf.exempt(telegram_webhook)
    csrf.exempt(set_webhook)
    csrf.exempt(webhooks_bp)
    csrf.exempt(tma_bp)

    from app.telegram.mini_app import (
        mini_app_api_dashboard,
        mini_app_api_schedule,
        mini_app_api_progress,
        mini_app_api_theory_index,
        mini_app_api_theory_article,
        mini_app_api_profile,
        mini_app_api_broadcast_create,
        mini_app_api_creator_students,
        mini_app_api_assignments,
        mini_app_api_profile_notifications,
        mini_app_api_creator_bug_reports,
        mini_app_api_creator_bug_reports_reply,
        mini_app_api_creator_stats,
        mini_app_api_creator_broadcasts,
    )
    for _fn in (
        mini_app_api_dashboard,
        mini_app_api_schedule,
        mini_app_api_progress,
        mini_app_api_theory_index,
        mini_app_api_theory_article,
        mini_app_api_profile,
        mini_app_api_broadcast_create,
        mini_app_api_creator_students,
        mini_app_api_assignments,
        mini_app_api_profile_notifications,
        mini_app_api_creator_bug_reports,
        mini_app_api_creator_bug_reports_reply,
        mini_app_api_creator_stats,
        mini_app_api_creator_broadcasts,
    ):
        csrf.exempt(_fn)

    @app.context_processor
    def inject_csrf_token():
        from flask_wtf.csrf import generate_csrf
        return dict(csrf_token=generate_csrf)
    
    @app.context_processor
    def inject_user_data():
        from flask_login import current_user
        from app.models import Student, User
        from app.auth.rbac_utils import has_permission
        template_user = current_user
        state = getattr(current_user, '_sa_instance_state', None)
        if state is not None and state.detached and state.identity:
            template_user = db.session.get(User, state.identity[0])

        student_data = None
        if template_user and template_user.is_authenticated and template_user.is_student():
            try:
                student = Student.query.filter_by(user_id=template_user.id).first()
                if student:
                    student_data = {'student_id': student.student_id}
            except Exception:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                student_data = None
        cinema_demo_ids = None
        if template_user and template_user.is_authenticated and getattr(template_user, 'is_demo_user', False):
            from flask import session as flask_session
            cinema_demo_ids = flask_session.get('cinema_demo_ids')
        tz_eff = 'Europe/Moscow'
        if template_user and template_user.is_authenticated:
            try:
                from app.utils.datetime_utc import effective_timezone_name
                tz_eff = effective_timezone_name(template_user)
            except Exception:
                tz_eff = 'Europe/Moscow'
        from app.utils.release_notes import build_release_notes_text, RELEASE_VERSION
        
        # Передаем список зон для QA-виджета
        qa_widget_areas = [
            'Авторизация и доступ', 'Биллинг и подписки', 'Админка', 
            'Курсы и уроки', 'Генератор задач', 'Песочница (Sandbox)', 
            'Telegram', 'Библиотека', 'Workspace', 'Мобильная версия', 'Общая'
        ]

        return dict(
            current_user=template_user,
            current_student=student_data,
            has_permission=has_permission,
            custom_theme_user_id=int(app.config.get('CUSTOM_THEME_USER_ID', 999)),
            cinema_demo_ids=cinema_demo_ids,
            user_timezone_effective=tz_eff,
            user_timezone_mode=(getattr(template_user, 'timezone_mode', 'auto') if template_user and template_user.is_authenticated else 'auto'),
            user_timezone_iana=(getattr(template_user, 'timezone_iana', None) if template_user and template_user.is_authenticated else None),
            release_notes=build_release_notes_text(),
            release_version=RELEASE_VERSION,
            qa_widget_areas=qa_widget_areas,
            trainer_available=bool(app.config.get('TRAINER_ENABLED', False)),
        )
    
    from app.admin.routes import (
        sandbox_internal_summary,
        sandbox_internal_user_tester_create,
        sandbox_internal_user_set_password,
        sandbox_internal_user_toggle_active,
        sandbox_internal_user_delete,
        sandbox_internal_tester_entity_create,
        sandbox_internal_tester_entity_toggle_active,
        sandbox_internal_tester_entity_delete,
    )
    from app.main.routes import (
        api_parent_link_child,
        api_parent_unlink_child,
    )
    csrf.exempt(sandbox_internal_summary)
    csrf.exempt(sandbox_internal_user_tester_create)
    csrf.exempt(sandbox_internal_user_set_password)
    csrf.exempt(sandbox_internal_user_toggle_active)
    csrf.exempt(sandbox_internal_user_delete)
    csrf.exempt(sandbox_internal_tester_entity_create)
    csrf.exempt(sandbox_internal_tester_entity_toggle_active)
    csrf.exempt(sandbox_internal_tester_entity_delete)
    csrf.exempt(api_parent_link_child)
    csrf.exempt(api_parent_unlink_child)
    
    
    from app.utils.hooks import register_hooks
    register_hooks(app)
    
    @app.template_filter('from_json')
    def from_json_filter(value):
        """Фильтр для преобразования JSON строки в объект Python"""
        if not value:
            return []
        try:
            import json
            import ast
            if isinstance(value, (list, dict)):
                return value
            parsed = json.loads(value)
            if isinstance(parsed, str):
                try:
                    parsed = json.loads(parsed)
                except Exception:
                    pass
            if isinstance(parsed, (list, dict)):
                return parsed
            return []
        except (json.JSONDecodeError, TypeError, ValueError):
            try:
                import ast
                parsed = ast.literal_eval(value)
                return parsed if isinstance(parsed, (list, dict)) else []
            except Exception:
                return []
    

    @app.template_filter('fromjson')
    def fromjson_filter_final(value):
        import json
        if not value: return []
        if isinstance(value, str):
            try: return json.loads(value)
            except: return []
        return value

    from app.utils.jinja_filters import init_jinja_filters
    init_jinja_filters(app)

    def _wants_json_response() -> bool:
        """True для AJAX/JSON: чтобы fetch не получал HTML-страницы ошибок."""
        try:
            from flask import request
            if request.path.startswith('/api'):
                return True
            if getattr(request, 'is_json', False):
                return True
            if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
                if request.path.endswith('/run-code') or request.path.endswith('/save-code'):
                    return True
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return True
            best = request.accept_mimetypes.best_match(['application/json', 'text/html'])
            return best == 'application/json'
        except Exception:
            return False

    def _render_error(code: int, headline: str, subtitle: str | None = None):
        from flask import render_template, jsonify

        if _wants_json_response():
            payload = {
                'success': False,
                'error': headline,
                'code': code,
                'message': subtitle or '',
            }
            return jsonify(payload), code

        return render_template(
            'errors/error.html',
            code=code,
            headline=headline,
            subtitle=subtitle,
        ), code

    @login_manager.unauthorized_handler
    def handle_login_required():
        """Сессия истекла: fetch с JSON не должен следовать за редиректом на HTML-страницу входа."""
        from flask import request, redirect, url_for

        if _wants_json_response():
            return _render_error(
                401,
                'НУЖНО ВОЙТИ',
                'Эта страница доступна только после входа в аккаунт.',
            )
        return redirect(url_for(login_manager.login_view, next=request.url))

    @app.errorhandler(400)
    def bad_request(error):
        return _render_error(
            400,
            'ПЛОХОЙ ЗАПРОС',
            'Кажется, данные отправлены в неправильном формате. Попробуй обновить страницу и повторить.',
        )

    @app.errorhandler(401)
    def unauthorized(error):
        return _render_error(
            401,
            'НУЖНО ВОЙТИ',
            'Эта страница доступна только после входа в аккаунт.',
        )

    @app.errorhandler(403)
    def forbidden(error):
        if request.path.startswith('/api/') or request.path.startswith('/sandbox/api/') or request.is_json:
            return jsonify({'error': 'Доступ запрещен'}), 403
        return _render_error(
            403,
            'ТЕБЕ СЮДА НЕЛЬЗЯ',
            'У тебя нет прав на доступ к этой странице.',
        )

    @app.errorhandler(404)
    def not_found(error):
        return _render_error(
            404,
            'ТУТ НИЧЕГО НЕТ',
            'Страница не найдена. Возможно, ссылка устарела или была удалена.',
        )

    @app.errorhandler(429)
    def too_many_requests(error):
        _agent_debug_log(
            'H7',
            'rate_limit_triggered',
            {'error_type': type(error).__name__}
        )
        return _render_error(
            429,
            'СЛИШКОМ ЧАСТО',
            'Ты делаешь слишком много запросов подряд. Подожди немного и попробуй ещё раз.',
        )

    @app.errorhandler(500)
    def internal_error(error):
        import traceback
        try:
            tb = ''.join(traceback.format_exception(type(error), error, getattr(error, '__traceback__', None))) if error else ''
            app.logger.error("500 Internal Server Error: %s\n%s", error, tb or traceback.format_stack())
        except Exception:
            pass
        try:
            db.session.rollback()
        except Exception:
            pass
        try:
            from app.notifications.service import notify_admins_critical_error
            notify_admins_critical_error(
                'Критическая ошибка сервера (500)',
                (str(error) or 'Unknown')[:500],
                meta={'type': type(error).__name__}
            )
            db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
        return _render_error(
            500,
            'СТРАНИЦА НЕ ЗАГРУЗИЛАСЬ, ОШИБКА!!',
            'Что-то пошло не так на сервере. Попробуй обновить страницу. Если повторяется — напиши в поддержку.',
        )

    try:
        from flask_wtf.csrf import CSRFError

        @app.errorhandler(CSRFError)
        def handle_csrf_error(e: CSRFError):
            _agent_debug_log(
                'H8',
                'csrf_error',
                {'error_type': type(e).__name__, 'description': str(e)[:200]}
            )
            if request.path.startswith('/api/') or request.path.startswith('/sandbox/api/') or request.is_json:
                return jsonify({'error': 'Сессия устарела или токен безопасности неверный.'}), 403
            return _render_error(
                403,
                'ТЕБЕ СЮДА НЕЛЬЗЯ',
                'Сессия устарела или токен безопасности неверный. Обнови страницу и попробуй снова.',
            )
    except Exception:
        pass

    @app.errorhandler(Exception)
    def handle_unexpected_exception(e: Exception):
        import traceback
        if isinstance(e, HTTPException):
            return e
        try:
            app.logger.exception("Unhandled exception (500): %s", e)
        except Exception:
            try:
                logging.getLogger(__name__).exception("Unhandled exception (500): %s", e)
            except Exception:
                pass
        try:
            db.session.rollback()
        except Exception:
            pass
        try:
            from app.notifications.service import notify_admins_critical_error
            notify_admins_critical_error(
                'Необработанное исключение (500)',
                (str(e) or 'Unknown')[:500],
                meta={'type': type(e).__name__}
            )
            db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
        return _render_error(
            500,
            'СТРАНИЦА НЕ ЗАГРУЗИЛАСЬ, ОШИБКА!!',
            'Произошла непредвиденная ошибка. Попробуй обновить страницу.',
        )
    
    @app.template_filter('markdown')
    def markdown_filter(text):
        """Фильтр для преобразования Markdown в HTML (зачёркивание ~~...~~, код с языком)."""
        if not text:
            return ''
        import re
        try:
            import markdown
            try:
                from markdown.extensions.codehilite import CodeHiliteExtension
                md = markdown.Markdown(extensions=['extra', 'nl2br', CodeHiliteExtension(use_pygments=False)])
            except (ImportError, TypeError):
                md = markdown.Markdown(extensions=['extra', 'codehilite', 'nl2br'])
            html = md.convert(text)
            html = re.sub(r'~~(.+?)~~', r'<del>\1</del>', html, flags=re.DOTALL)
            return html
        except ImportError:
            import re
            html = text
            
            html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)
            html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
            html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
            html = re.sub(r'^#### (.+)$', r'<h4>\1</h4>', html, flags=re.MULTILINE)
            
            html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
            html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
            html = re.sub(r'~~(.+?)~~', r'<del>\1</del>', html, flags=re.DOTALL)
            html = re.sub(r'`(.+?)`', r'<code>\1</code>', html)
            
            html = re.sub(r'^- (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
            html = re.sub(r'(<li>.*?</li>)', r'<ul>\1</ul>', html, flags=re.DOTALL)
            html = re.sub(r'^\d+\. (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
            
            html = re.sub(r'\n\n', r'</p><p>', html)
            html = '<p>' + html + '</p>'
            return html
    
    @app.route('/auth/miro/callback', methods=['GET', 'POST'])
    def miro_oauth_callback():
        """Callback endpoint для Miro OAuth 2.0."""
        from flask import request, jsonify, redirect, url_for, flash, session
        from flask_login import current_user
        import requests
        from datetime import datetime, timedelta
        
        code = request.args.get('code')
        error = request.args.get('error')
        
        if not code and not error:
            return jsonify({'status': 'ok', 'message': 'Miro OAuth callback endpoint'}), 200
        
        if error:
            logger.warning(f"Miro OAuth error: {error}")
            flash(f'Ошибка авторизации Miro: {error}', 'danger')
            return redirect(url_for('main.dashboard'))
        
        if not current_user.is_authenticated:
            flash('Войдите в систему для подключения Miro', 'warning')
            return redirect(url_for('auth.login'))
        
        client_id = app.config.get('MIRO_CLIENT_ID')
        client_secret = app.config.get('MIRO_CLIENT_SECRET')
        redirect_uri = app.config.get('MIRO_REDIRECT_URI')
        if not redirect_uri:
            base_url = request.url_root.rstrip('/').replace('http://', 'https://')
            redirect_uri = base_url + '/auth/miro/callback'
        
        try:
            token_response = requests.post(
                'https://api.miro.com/v1/oauth/token',
                data={
                    'grant_type': 'authorization_code',
                    'client_id': client_id,
                    'client_secret': client_secret,
                    'code': code,
                    'redirect_uri': redirect_uri
                },
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            
            if token_response.status_code != 200:
                logger.error(f"Miro token exchange failed: {token_response.text}")
                flash('Ошибка получения токена Miro', 'danger')
                return redirect(url_for('main.dashboard'))
            
            token_data = token_response.json()
            access_token = token_data.get('access_token')
            refresh_token = token_data.get('refresh_token')
            raw_expires = token_data.get('expires_in')
            try:
                expires_in = int(raw_expires) if raw_expires is not None else None
            except (TypeError, ValueError):
                expires_in = None
            if expires_in is not None and expires_in <= 0:
                expires_in = None
            
            from app.models import MiroUserToken
            
            miro_token = MiroUserToken.query.filter_by(user_id=current_user.id).first()
            if not miro_token:
                miro_token = MiroUserToken(user_id=current_user.id)
                db.session.add(miro_token)
            
            miro_token.access_token = access_token
            miro_token.refresh_token = refresh_token
            if expires_in is not None:
                miro_token.expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
            else:
                miro_token.expires_at = None  # токен без срока — не требуем повторную авторизацию
            miro_token.miro_user_id = token_data.get('user_id')
            miro_token.miro_team_id = token_data.get('team_id')
            
            db.session.commit()
            
            logger.info(f"Miro OAuth successful for user {current_user.id}")
            flash('Miro успешно подключен! Теперь вы можете редактировать доски.', 'success')
            
            lesson_id = session.pop('miro_auth_lesson_id', None)
            if lesson_id:
                return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson_id) + '#tab=whiteboard')
            
            return redirect(url_for('main.dashboard'))
            
        except Exception as e:
            logger.error(f"Miro OAuth error: {e}", exc_info=True)
            flash(f'Ошибка подключения Miro: {str(e)}', 'danger')
            return redirect(url_for('main.dashboard'))
    
    @app.route('/auth/miro/authorize')
    def miro_oauth_authorize():
        """Начало OAuth авторизации Miro."""
        from flask import redirect, session, request
        from flask_login import current_user, login_required
        
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        
        client_id = app.config.get('MIRO_CLIENT_ID')
        redirect_uri = app.config.get('MIRO_REDIRECT_URI')
        if not redirect_uri:
            base_url = request.url_root.rstrip('/').replace('http://', 'https://')
            redirect_uri = base_url + '/auth/miro/callback'
        
        lesson_id = request.args.get('lesson_id')
        if lesson_id:
            session['miro_auth_lesson_id'] = lesson_id
        
        auth_url = (
            f"https://miro.com/oauth/authorize"
            f"?response_type=code"
            f"&client_id={client_id}"
            f"&redirect_uri={redirect_uri}"
        )
        
        return redirect(auth_url)
    

    # Register QA comment parser
    from app.utils.markdown_helper import render_qa_comment
    app.jinja_env.filters['render_qa_comment'] = render_qa_comment

    
    # Safe JSON filter
    
    
    return app

