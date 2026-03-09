"""
Инициализация Flask приложения
"""
import os
import logging
import threading
import time
from flask import Flask
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from sqlalchemy import text
from zoneinfo import ZoneInfo  # comment
from datetime import datetime  # comment
from werkzeug.exceptions import HTTPException

from flask_migrate import Migrate
from app.models import db
from core.audit_logger import audit_logger
from app.models import User, MOSCOW_TZ  # comment

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
    
    db_path = os.path.join(base_dir, 'data', 'keg_tasks.db')
    
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        if database_url.startswith('postgres://'):
            database_url = database_url.replace('postgres://', 'postgresql://', 1)
        external_db_url = os.environ.get('DATABASE_EXTERNAL_URL') or os.environ.get('POSTGRES_URL')
        if external_db_url:
            if external_db_url.startswith('postgres://'):
                external_db_url = external_db_url.replace('postgres://', 'postgresql://', 1)
            database_url = external_db_url
        app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    else:
        app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
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
    
    app.config['MIRO_ACCESS_TOKEN'] = (os.environ.get('MIRO_ACCESS_TOKEN') or '').strip() or None
    app.config['MIRO_CLIENT_ID'] = (os.environ.get('MIRO_CLIENT_ID') or '').strip() or None
    app.config['MIRO_CLIENT_SECRET'] = (os.environ.get('MIRO_CLIENT_SECRET') or '').strip() or None
    app.config['MIRO_REDIRECT_URI'] = (os.environ.get('MIRO_REDIRECT_URI') or '').strip() or None  # например https://boostudy.ru/auth/miro/callback
    
    app.config['DAILY_API_KEY'] = (os.environ.get('DAILY_API_KEY') or '').strip() or None
    app.config['DAILY_DOMAIN'] = 'urep'  # urep.daily.co
    
    app.config['AVATAR_UPLOAD_ROOT'] = (os.environ.get('AVATAR_UPLOAD_ROOT') or '').strip() or None
    app.config['COVER_UPLOAD_ROOT'] = (os.environ.get('COVER_UPLOAD_ROOT') or '').strip() or None
    # Корень папки вложений заданий (uploads/task_attachments). На Timeweb можно задать путь к volume.
    app.config['TASK_ATTACHMENTS_ROOT'] = (os.environ.get('TASK_ATTACHMENTS_ROOT') or '').strip().rstrip(os.sep) or None
    # Корень папки вложений ответов учеников (uploads/answer_attachments).
    app.config['ANSWER_ATTACHMENTS_ROOT'] = os.environ.get('ANSWER_ATTACHMENTS_ROOT') or os.path.join(base_dir, 'uploads', 'answer_attachments')

    app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10 MB

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
        demo_db_url = os.environ.get('DEMO_DATABASE_URL') or os.environ.get('DATABASE_URL')
        if demo_db_url and demo_db_url.startswith('postgres://'):
            demo_db_url = demo_db_url.replace('postgres://', 'postgresql://', 1)
        if demo_db_url:
            app.config['SQLALCHEMY_DATABASE_URI'] = demo_db_url
        # иначе оставляем уже установленный DATABASE_URL выше
    
    csrf.init_app(app)
    db.init_app(app)
    migrate.init_app(app, db)
    audit_logger.init_app(app)
    
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
    
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    log_dir = os.path.join(base_dir, 'logs')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, 'app.log')
    
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.StreamHandler(),  # Вывод в консоль
            logging.FileHandler(log_file, encoding='utf-8')  # Вывод в файл app.log
        ]
    )
    logger = logging.getLogger(__name__)
    logger.info("Логирование инициализировано. Логи также сохраняются в файл app.log")
    
    ENVIRONMENT = os.environ.get('ENVIRONMENT', 'local')
    logger.info(f"=== Application Initialization ===")
    logger.info(f"Environment: {ENVIRONMENT}")
    if database_url:
        external_db_url = os.environ.get('DATABASE_EXTERNAL_URL') or os.environ.get('POSTGRES_URL')
        if external_db_url:
            logger.info("Using external database URL (DATABASE_EXTERNAL_URL or POSTGRES_URL)")
            logger.info("Database type: PostgreSQL (external)")
        else:
            logger.info("Using DATABASE_URL")
            logger.info("Database type: PostgreSQL")
        
        try:
            with app.app_context():
                from app.models import Reminder  # Явный импорт для создания таблицы
                from app.models import Assignment, AssignmentTask, Submission, Answer  # Импортируем новые модели
                from app.models import LessonWhiteboard  # Интерактивная доска Miro
                from app.models import Subject, KnowledgeNode, UserMastery, AnalyticsEvent  # Аналитика (граф знаний)
                from app.models import TheoryBlock, StudentTheoryAccess  # Теория по заданиям ЕГЭ
                db.create_all()
                db.session.execute(text("SELECT 1"))
                logger.info("✓ Database connection: OK")
                from app.utils.db_migrations import ensure_schema_columns
                try:
                    ensure_schema_columns(app)
                    logger.info("✓ Database schema migrations: OK")
                except Exception as mig_error:
                    logger.warning(f"⚠ Schema migration failed: {str(mig_error)}")
                    logger.warning("Application will continue, migrations will retry on first request")
        except Exception as e:
            logger.warning(f"⚠ Database connection check failed: {str(e)}")
            logger.warning("Application will continue, but database operations may fail")
    else:
        logger.warning("DATABASE_URL not set, using SQLite")
        logger.warning("This is likely a local development environment")
    
    logger.info(f"SECRET_KEY set: {'YES' if os.environ.get('SECRET_KEY') else 'NO'}")
    logger.info(f"=== Initialization Complete ===")
    
    from app.auth import auth_bp
    from app.main import main_bp
    from app.students import students_bp
    from app.lessons import lessons_bp
    from app.admin import admin_bp
    from app.task_generator import task_generator_bp
    from app.api import api_bp
    from app.schedule import schedule_bp
    from app.templates_manager import templates_bp
    from app.reminders import reminders_bp
    from app.parents import parents_bp
    from app.designer import designer_bp
    from app.assignments import assignments_bp
    from app.remote_admin import remote_admin_bp
    from app.courses import courses_bp
    from app.library import library_bp
    from app.groups import groups_bp
    from app.notifications import notifications_bp
    from app.onboarding import onboarding_bp
    from app.rubrics import rubrics_bp
    from app.billing import billing_bp
    from app.trainer import trainer_bp
    from app.uploads import uploads_bp
    from app.qa.routes import qa_bp
    from app.theory import theory_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(students_bp)
    app.register_blueprint(lessons_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(task_generator_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(schedule_bp)
    app.register_blueprint(templates_bp)
    app.register_blueprint(reminders_bp)
    app.register_blueprint(parents_bp)
    app.register_blueprint(designer_bp)
    app.register_blueprint(assignments_bp)
    app.register_blueprint(remote_admin_bp)
    app.register_blueprint(courses_bp)
    app.register_blueprint(library_bp)
    app.register_blueprint(groups_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(onboarding_bp)
    app.register_blueprint(rubrics_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(trainer_bp)
    app.register_blueprint(uploads_bp)
    app.register_blueprint(qa_bp)
    app.register_blueprint(theory_bp)

    # Real-time комната урока (WebSocket)
    try:
        from flask_socketio import SocketIO
        socketio = SocketIO(
            app,
            async_mode='threading',
            cors_allowed_origins='*',
            logger=False,
            engineio_logger=False,
        )
        app.socketio = socketio
        from app.lessons.lesson_socket import register_lesson_socket
        register_lesson_socket(socketio)
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

    _start_assignment_notification_worker()

    def _start_lesson_auto_complete_worker() -> None:
        if app.config.get('_LESSON_AUTO_COMPLETE_WORKER_STARTED'):
            return
        poll_seconds = int(os.environ.get('LESSON_AUTO_COMPLETE_POLL_SECONDS', '300'))

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

    _start_lesson_auto_complete_worker()

    from app.auth.routes import logout
    csrf.exempt(logout)
    
    from app.admin.routes import maintenance_status_api
    csrf.exempt(maintenance_status_api)

    from app.api.routes import api_telegram_link_bot
    csrf.exempt(api_telegram_link_bot)

    @app.context_processor
    def inject_csrf_token():
        from flask_wtf.csrf import generate_csrf
        return dict(csrf_token=generate_csrf)
    
    @app.context_processor
    def inject_user_data():
        from flask_login import current_user
        from app.models import Student
        from app.auth.rbac_utils import has_permission
        student_data = None
        if current_user.is_authenticated and current_user.is_student():
            try:
                student = Student.query.filter_by(user_id=current_user.id).first()
                if student:
                    student_data = {'student_id': student.student_id}
            except Exception:
                student_data = None
        cinema_demo_ids = None
        if current_user.is_authenticated and getattr(current_user, 'is_demo_user', False):
            from flask import session as flask_session
            cinema_demo_ids = flask_session.get('cinema_demo_ids')
        return dict(current_student=student_data, has_permission=has_permission, custom_theme_user_id=int(app.config.get('CUSTOM_THEME_USER_ID', 999)), cinema_demo_ids=cinema_demo_ids)
    
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
    csrf.exempt(sandbox_internal_summary)
    csrf.exempt(sandbox_internal_user_tester_create)
    csrf.exempt(sandbox_internal_user_set_password)
    csrf.exempt(sandbox_internal_user_toggle_active)
    csrf.exempt(sandbox_internal_user_delete)
    csrf.exempt(sandbox_internal_tester_entity_create)
    csrf.exempt(sandbox_internal_tester_entity_toggle_active)
    csrf.exempt(sandbox_internal_tester_entity_delete)
    
    
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
    
    from app.utils.jinja_filters import init_jinja_filters
    init_jinja_filters(app)

    def _wants_json_response() -> bool:
        try:
            from flask import request
            if request.path.startswith('/api'):
                return True
            if request.is_json:
                return True
            best = request.accept_mimetypes.best
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
    
    return app

