"""
Инициализация Flask приложения
"""
import os
import logging
from flask import Flask
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from sqlalchemy import text

# Импортируем db из models, чтобы он был доступен для инициализации
from app.models import db
from core.audit_logger import audit_logger
from app.models import User

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
        
        # В Railway внутренний URL должен работать, но если нет - используем внешний
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
        
        # Проверяем подключение к БД
        try:
            with app.app_context():
                db.create_all()
                # Проверяем, что можем подключиться
                db.session.execute(text("SELECT 1"))
                logger.info("✓ Database connection: OK")
        except Exception as e:
            logger.error(f"✗ Database connection: FAILED - {str(e)}")
            logger.error("This may cause issues with the application!")
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
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(students_bp)
    app.register_blueprint(lessons_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(kege_generator_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(schedule_bp)
    app.register_blueprint(templates_bp)
    
    # Исключаем logout из CSRF защиты
    from app.auth.routes import logout
    csrf.exempt(logout)
    
    # Импорт и регистрация хуков before_request
    from app.utils.hooks import register_hooks
    register_hooks(app)
    
    return app

