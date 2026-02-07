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

# Импортируем db из models, чтобы он был доступен для инициализации
from app.models import db
from core.audit_logger import audit_logger
from app.models import User, MOSCOW_TZ  # comment

# Инициализация расширений
csrf = CSRFProtect()
login_manager = LoginManager()

def create_app(config_name=None):
    """
    Фабрика приложений Flask
    Создает и настраивает экземпляр Flask приложения
    """
    # Базовая директория проекта
    base_dir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    template_dir = os.path.join(base_dir, 'templates')
    static_dir = os.path.join(base_dir, 'static')
    
    app = Flask(__name__, 
                template_folder=template_dir,
                static_folder=static_dir)
    
    db_path = os.path.join(base_dir, 'data', 'keg_tasks.db')
    
    # Настройка базы данных
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        if database_url.startswith('postgres://'):
            database_url = database_url.replace('postgres://', 'postgresql://', 1)
        
        # В Railway используем внутренний URL, для локального запуска - внешний
        is_railway = os.environ.get('RAILWAY_ENVIRONMENT') is not None
        if not is_railway:
            # Локальный запуск - используем внешний URL если доступен
            external_db_url = os.environ.get('DATABASE_EXTERNAL_URL') or os.environ.get('POSTGRES_URL')
            if external_db_url:
                if external_db_url.startswith('postgres://'):
                    external_db_url = external_db_url.replace('postgres://', 'postgresql://', 1)
                database_url = external_db_url
        
        app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    else:
        app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'local-dev-key-12345')
    app.config['WTF_CSRF_ENABLED'] = True
    app.config['WTF_CSRF_TIME_LIMIT'] = None
    app.config['TRAINER_URL'] = (os.environ.get('TRAINER_URL') or '').strip() or None
    app.config['TRAINER_SHARED_SECRET'] = (os.environ.get('TRAINER_SHARED_SECRET') or '').strip() or None
    
    # Miro API для интерактивных досок
    app.config['MIRO_ACCESS_TOKEN'] = (os.environ.get('MIRO_ACCESS_TOKEN') or '').strip() or None
    app.config['MIRO_CLIENT_ID'] = (os.environ.get('MIRO_CLIENT_ID') or '').strip() or None
    app.config['MIRO_CLIENT_SECRET'] = (os.environ.get('MIRO_CLIENT_SECRET') or '').strip() or None
    
    # Daily.co для видеозвонков
    app.config['DAILY_API_KEY'] = (os.environ.get('DAILY_API_KEY') or '').strip() or None
    app.config['DAILY_DOMAIN'] = 'urep'  # urep.daily.co
    
    # Определение окружения (production, sandbox, local)
    ENVIRONMENT = os.environ.get('ENVIRONMENT', 'local')
    
    # Инициализация расширений
    csrf.init_app(app)
    db.init_app(app)
    audit_logger.init_app(app)
    
    # Настройка Flask-Login
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Для доступа к системе необходимо войти.'
    login_manager.login_message_category = 'warning'
    
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
            # Добавляем краткое обозначение зоны, чтобы не было двусмысленности
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
    
    # Настройка логирования
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
    
    # Логируем информацию о БД после инициализации logger
    ENVIRONMENT = os.environ.get('ENVIRONMENT', 'local')
    logger.info(f"=== Application Initialization ===")
    logger.info(f"Environment: {ENVIRONMENT}")
    logger.info(f"RAILWAY_ENVIRONMENT: {os.environ.get('RAILWAY_ENVIRONMENT', 'NOT SET')}")
    
    if database_url:
        external_db_url = os.environ.get('DATABASE_EXTERNAL_URL') or os.environ.get('POSTGRES_URL')
        if external_db_url:
            logger.info("Using external database URL (DATABASE_EXTERNAL_URL or POSTGRES_URL)")
            logger.info(f"Database type: PostgreSQL (external)")
        else:
            logger.info(f"Using DATABASE_URL (internal Railway connection)")
            logger.info(f"Database type: PostgreSQL (internal)")
        
        # Проверяем подключение к БД и выполняем миграции (не блокируем запуск при ошибке)
        try:
            with app.app_context():
                # Импортируем все модели, чтобы они были зарегистрированы в SQLAlchemy
                from app.models import Reminder  # Явный импорт для создания таблицы
                from app.models import Assignment, AssignmentTask, Submission, Answer  # Импортируем новые модели
                from app.models import LessonWhiteboard  # Интерактивная доска Miro
                db.create_all()
                # Проверяем, что можем подключиться
                db.session.execute(text("SELECT 1"))
                logger.info("✓ Database connection: OK")
                # Выполняем миграции схемы
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
            # Не блокируем запуск приложения, даже если БД недоступна
    else:
        logger.warning("DATABASE_URL not set, using SQLite")
        logger.warning("This is likely a local development environment")
    
    logger.info(f"SECRET_KEY set: {'YES' if os.environ.get('SECRET_KEY') else 'NO'}")
    logger.info(f"=== Initialization Complete ===")
    
    # Регистрация блюпринтов
    from app.auth import auth_bp
    from app.main import main_bp
    from app.students import students_bp
    from app.lessons import lessons_bp
    from app.admin import admin_bp
    from app.kege_generator import kege_generator_bp
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
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(students_bp)
    app.register_blueprint(lessons_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(kege_generator_bp)
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
    
    # Исключаем logout из CSRF защиты
    from app.auth.routes import logout
    csrf.exempt(logout)
    
    # Исключаем публичный API для проверки статуса тех работ из CSRF защиты
    from app.admin.routes import maintenance_status_api
    csrf.exempt(maintenance_status_api)

    # Добавляем csrf_token в контекст всех шаблонов
    @app.context_processor
    def inject_csrf_token():
        from flask_wtf.csrf import generate_csrf
        return dict(csrf_token=generate_csrf)
    
    # Добавляем данные пользователя в контекст для навигации
    @app.context_processor
    def inject_user_data():
        from flask_login import current_user
        from app.models import Student
        from app.auth.rbac_utils import has_permission
        student_data = None
        if current_user.is_authenticated and current_user.is_student():
            try:
                # Сначала по user_id (Create Pack и новая схема), затем по email
                student = Student.query.filter_by(user_id=current_user.id).first()
                if not student and current_user.email:
                    student = Student.query.filter_by(email=current_user.email).first()
                if student:
                    student_data = {'student_id': student.student_id}
            except Exception:
                # Важно: контекст-процессор не должен ронять страницу (особенно error pages).
                student_data = None
        return dict(current_student=student_data, has_permission=has_permission)
    
    # Исключаем внутренний sandbox-admin API из CSRF (server-to-server по токену)
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
    
    # Исключаем внутренний remote-admin API из CSRF (server-to-server по токену)
    # Используем декоратор @csrf.exempt прямо в remote_admin_api.py для избежания проблем с импортами
    # Здесь просто убеждаемся, что пути исключены через before_request хук
    
    # Импорт и регистрация хуков before_request
    from app.utils.hooks import register_hooks
    register_hooks(app)
    
    # Регистрация фильтра from_json для Jinja2
    @app.template_filter('from_json')
    def from_json_filter(value):
        """Фильтр для преобразования JSON строки в объект Python"""
        if not value:
            return []
        try:
            import json
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
    
    # Инициализируем Jinja2 фильтры (включая mask_contact)
    from app.utils.jinja_filters import init_jinja_filters
    init_jinja_filters(app)

    # =========================================================================
    # Красивые страницы ошибок (UI) + JSON для API
    # =========================================================================
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
        # Важно: 500 часто приходит после exception — пытаемся безопасно откатить транзакцию.
        try:
            db.session.rollback()
        except Exception:
            pass
        return _render_error(
            500,
            'СТРАНИЦА НЕ ЗАГРУЗИЛАСЬ, ОШИБКА!!',
            'Что-то пошло не так на сервере. Попробуй обновить страницу. Если повторяется — напиши в поддержку.',
        )

    # CSRF ошибки показываем как 403 (более понятный UX).
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

    # Не даём “левым” исключениям превращаться в HTML для API — но и не ломаем HTTPException.
    @app.errorhandler(Exception)
    def handle_unexpected_exception(e: Exception):
        if isinstance(e, HTTPException):
            return e
        try:
            db.session.rollback()
        except Exception:
            pass
        return _render_error(
            500,
            'СТРАНИЦА НЕ ЗАГРУЗИЛАСЬ, ОШИБКА!!',
            'Произошла непредвиденная ошибка. Попробуй обновить страницу.',
        )
    
    # Регистрация фильтра markdown для Jinja2
    @app.template_filter('markdown')
    def markdown_filter(text):
        """Фильтр для преобразования Markdown в HTML"""
        if not text:
            return ''
        try:
            import markdown
            md = markdown.Markdown(extensions=['extra', 'codehilite', 'nl2br'])
            return md.convert(text)
        except ImportError:
            # Если библиотека markdown не установлена, используем простую замену через regex
            import re
            html = text
            
            # Заголовки
            html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)
            html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
            html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
            html = re.sub(r'^#### (.+)$', r'<h4>\1</h4>', html, flags=re.MULTILINE)
            
            # Жирный и курсив
            html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
            html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
            
            # Код
            html = re.sub(r'`(.+?)`', r'<code>\1</code>', html)
            
            # Списки
            html = re.sub(r'^- (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
            html = re.sub(r'(<li>.*?</li>)', r'<ul>\1</ul>', html, flags=re.DOTALL)
            html = re.sub(r'^\d+\. (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
            
            # Абзацы
            html = re.sub(r'\n\n', r'</p><p>', html)
            html = '<p>' + html + '</p>'
            return html
    
    # Miro OAuth callback endpoint (напрямую в app для гарантированной регистрации)
    @app.route('/auth/miro/callback', methods=['GET', 'POST'])
    def miro_oauth_callback():
        """Callback endpoint для Miro OAuth 2.0."""
        from flask import request, jsonify, redirect, url_for, flash, session
        from flask_login import current_user
        import requests
        from datetime import datetime, timedelta
        
        code = request.args.get('code')
        error = request.args.get('error')
        
        # Если нет code - это проверка URL от Miro
        if not code and not error:
            return jsonify({'status': 'ok', 'message': 'Miro OAuth callback endpoint'}), 200
        
        if error:
            logger.warning(f"Miro OAuth error: {error}")
            flash(f'Ошибка авторизации Miro: {error}', 'danger')
            return redirect(url_for('main.dashboard'))
        
        # Проверяем авторизацию пользователя
        if not current_user.is_authenticated:
            flash('Войдите в систему для подключения Miro', 'warning')
            return redirect(url_for('auth.login'))
        
        # Обмениваем code на access_token
        client_id = app.config.get('MIRO_CLIENT_ID')
        client_secret = app.config.get('MIRO_CLIENT_SECRET')
        # Принудительно используем https (Railway прокси скрывает https)
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
            expires_in = token_data.get('expires_in', 3600)
            
            # Сохраняем токен в БД
            from app.models import MiroUserToken
            
            miro_token = MiroUserToken.query.filter_by(user_id=current_user.id).first()
            if not miro_token:
                miro_token = MiroUserToken(user_id=current_user.id)
                db.session.add(miro_token)
            
            miro_token.access_token = access_token
            miro_token.refresh_token = refresh_token
            miro_token.expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
            miro_token.miro_user_id = token_data.get('user_id')
            miro_token.miro_team_id = token_data.get('team_id')
            
            db.session.commit()
            
            logger.info(f"Miro OAuth successful for user {current_user.id}")
            flash('Miro успешно подключен! Теперь вы можете редактировать доски.', 'success')
            
            # Редирект обратно на урок, если был сохранён
            lesson_id = session.pop('miro_auth_lesson_id', None)
            if lesson_id:
                return redirect(url_for('lessons.lesson_homework_view', lesson_id=lesson_id) + '#tab=whiteboard')
            
            return redirect(url_for('main.dashboard'))
            
        except Exception as e:
            logger.error(f"Miro OAuth error: {e}", exc_info=True)
            flash(f'Ошибка подключения Miro: {str(e)}', 'danger')
            return redirect(url_for('main.dashboard'))
    
    # Endpoint для начала Miro OAuth авторизации
    @app.route('/auth/miro/authorize')
    def miro_oauth_authorize():
        """Начало OAuth авторизации Miro."""
        from flask import redirect, session, request
        from flask_login import current_user, login_required
        
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        
        client_id = app.config.get('MIRO_CLIENT_ID')
        # Принудительно используем https
        base_url = request.url_root.rstrip('/').replace('http://', 'https://')
        redirect_uri = base_url + '/auth/miro/callback'
        
        # Сохраняем lesson_id для редиректа после авторизации
        lesson_id = request.args.get('lesson_id')
        if lesson_id:
            session['miro_auth_lesson_id'] = lesson_id
        
        # Формируем URL авторизации Miro
        auth_url = (
            f"https://miro.com/oauth/authorize"
            f"?response_type=code"
            f"&client_id={client_id}"
            f"&redirect_uri={redirect_uri}"
        )
        
        return redirect(auth_url)
    
    return app

