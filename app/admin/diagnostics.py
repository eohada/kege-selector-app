"""
Диагностический endpoint для проверки конфигурации окружения
Помогает выявить различия между production и sandbox
"""
import os
import logging
from flask import jsonify, render_template
from flask_login import login_required
from sqlalchemy import text, inspect
from app.models import db, Student, Lesson, User, Tasks
from app.admin import admin_bp

logger = logging.getLogger(__name__)

@admin_bp.route('/admin/diagnostics')
@login_required
def diagnostics():
    """Страница диагностики конфигурации"""
    from flask import current_app
    with current_app.app_context():
        diagnostics_data = get_diagnostics_data()
    return render_template('admin_diagnostics.html', 
                         diagnostics_data=diagnostics_data)

@admin_bp.route('/admin/diagnostics/api')
@login_required
def diagnostics_api():
    """API endpoint для получения диагностической информации"""
    from flask import current_app
    with current_app.app_context():
        diagnostics_data = get_diagnostics_data()
    return jsonify(diagnostics_data)

@admin_bp.route('/admin/diagnostics/test')
def diagnostics_test():
    """Простой тестовый endpoint для проверки доступности (без авторизации)"""
    return jsonify({
        'status': 'OK',
        'message': 'Диагностический endpoint доступен',
        'endpoint': '/admin/diagnostics',
        'note': 'Для полной диагностики требуется авторизация'
    })

@admin_bp.route('/admin/diagnostics/db-check')
def diagnostics_db_check():
    """
    Простая проверка подключения к БД (без авторизации для удобства)
    Можно использовать для проверки БД в Railway
    """
    result = {
        'status': 'checking',
        'environment': os.environ.get('ENVIRONMENT', 'unknown'),
        'database': {},
        'timestamp': None
    }
    
    try:
        from datetime import datetime
        result['timestamp'] = datetime.now().isoformat()
        
        # Проверка DATABASE_URL
        database_url = os.environ.get('DATABASE_URL', 'NOT SET')
        result['database']['DATABASE_URL_set'] = 'YES' if database_url != 'NOT SET' else 'NO'
        result['database']['DATABASE_URL_preview'] = _mask_url(database_url)
        result['database']['database_type'] = _get_database_type(database_url)
        
        # Проверка подключения
        from flask import current_app
        with current_app.app_context():
            with db.engine.connect() as conn:
                # Простой запрос для проверки
                conn.execute(text("SELECT 1"))
                result['database']['connection_status'] = 'OK'
                result['status'] = 'success'
                
                # Проверка таблиц
                try:
                    inspector = inspect(db.engine)
                    tables = inspector.get_table_names()
                    result['database']['tables_count'] = len(tables)
                    result['database']['tables'] = sorted(tables)
                    
                    # Проверка основных таблиц
                    important_tables = ['Users', 'Students', 'Lessons', 'Tasks']
                    result['database']['important_tables'] = {}
                    for table in important_tables:
                        if table in tables:
                            try:
                                count_result = conn.execute(text(f'SELECT COUNT(*) FROM "{table}"'))
                                count = count_result.fetchone()[0]
                                result['database']['important_tables'][table] = count
                            except Exception as e:
                                result['database']['important_tables'][table] = f'error: {str(e)}'
                        else:
                            result['database']['important_tables'][table] = 'not found'
                            
                except Exception as e:
                    result['database']['tables_error'] = str(e)
                    
    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)
        result['database']['connection_status'] = 'ERROR'
        result['database']['connection_error'] = str(e)
    
    return jsonify(result)

def get_diagnostics_data():
    """
    Собирает диагностическую информацию о текущем окружении
    """
    diagnostics = {
        'environment': {},
        'database': {},
        'application': {},
        'errors': []
    }
    
    # Информация об окружении
    diagnostics['environment'] = {
        'ENVIRONMENT': os.environ.get('ENVIRONMENT', 'NOT SET'),
        'RAILWAY_ENVIRONMENT': os.environ.get('RAILWAY_ENVIRONMENT', 'NOT SET'),
        'RAILWAY_SERVICE_NAME': os.environ.get('RAILWAY_SERVICE_NAME', 'NOT SET'),
        'PORT': os.environ.get('PORT', 'NOT SET'),
        'PYTHON_VERSION': os.environ.get('PYTHON_VERSION', 'NOT SET'),
    }
    
    # Информация о базе данных
    database_url = os.environ.get('DATABASE_URL', 'NOT SET')
    external_db_url = os.environ.get('DATABASE_EXTERNAL_URL') or os.environ.get('POSTGRES_URL')
    
    diagnostics['database'] = {
        'DATABASE_URL_set': 'YES' if database_url != 'NOT SET' else 'NO',
        'DATABASE_URL_preview': _mask_url(database_url) if database_url != 'NOT SET' else 'NOT SET',
        'DATABASE_EXTERNAL_URL_set': 'YES' if external_db_url else 'NO',
        'DATABASE_EXTERNAL_URL_preview': _mask_url(external_db_url) if external_db_url else 'NOT SET',
        'SQLALCHEMY_DATABASE_URI_preview': _mask_url(db.engine.url) if hasattr(db, 'engine') else 'NOT INITIALIZED',
        'database_type': _get_database_type(database_url),
    }
    
    # Проверка подключения к БД
    try:
        from flask import current_app
        with current_app.app_context():
            with db.engine.connect() as conn:
                result = conn.execute(text("SELECT version()"))
                db_version = result.fetchone()[0]
                diagnostics['database']['connection_status'] = 'OK'
                diagnostics['database']['postgres_version'] = db_version.split(',')[0] if db_version else 'UNKNOWN'
    except Exception as e:
        diagnostics['database']['connection_status'] = 'ERROR'
        diagnostics['database']['connection_error'] = str(e)
        diagnostics['errors'].append(f"Database connection error: {str(e)}")
    
    # Проверка таблиц
    try:
        from flask import current_app
        with current_app.app_context():
            inspector = inspect(db.engine)
            tables = inspector.get_table_names()
            diagnostics['database']['tables_count'] = len(tables)
            diagnostics['database']['tables'] = sorted(tables)
    except Exception as e:
        diagnostics['database']['tables_error'] = str(e)
        diagnostics['errors'].append(f"Tables inspection error: {str(e)}")
    
    # Проверка данных в БД
    try:
        from flask import current_app
        with current_app.app_context():
            diagnostics['database']['data_counts'] = {
                'students': Student.query.count(),
                'lessons': Lesson.query.count(),
                'users': User.query.count(),
                'tasks': Tasks.query.count() if hasattr(Tasks, 'query') else 0,
            }
    except Exception as e:
        diagnostics['database']['data_counts_error'] = str(e)
        diagnostics['errors'].append(f"Data counts error: {str(e)}")
    
    # Информация о приложении
    diagnostics['application'] = {
        'SECRET_KEY_set': 'YES' if os.environ.get('SECRET_KEY') else 'NO',
        'SECRET_KEY_length': len(os.environ.get('SECRET_KEY', '')) if os.environ.get('SECRET_KEY') else 0,
        'WTF_CSRF_ENABLED': os.environ.get('WTF_CSRF_ENABLED', 'NOT SET'),
    }
    
    # Проверка конфигурации Flask
    try:
        from flask import has_app_context, current_app
        if has_app_context():
            diagnostics['application']['flask_config'] = {
                'SQLALCHEMY_DATABASE_URI_set': 'YES' if current_app.config.get('SQLALCHEMY_DATABASE_URI') else 'NO',
                'SECRET_KEY_set': 'YES' if current_app.config.get('SECRET_KEY') else 'NO',
                'WTF_CSRF_ENABLED': current_app.config.get('WTF_CSRF_ENABLED', False),
            }
        else:
            diagnostics['application']['flask_config'] = {
                'SQLALCHEMY_DATABASE_URI_set': 'UNKNOWN (no app context)',
                'SECRET_KEY_set': 'UNKNOWN (no app context)',
                'WTF_CSRF_ENABLED': False,
            }
    except Exception as e:
        diagnostics['application']['flask_config_error'] = str(e)
        diagnostics['errors'].append(f"Flask config error: {str(e)}")
    
    # Проверка переменных окружения Railway
    railway_vars = {k: v for k, v in os.environ.items() if 'RAILWAY' in k}
    diagnostics['environment']['railway_variables'] = railway_vars
    
    return diagnostics

def _mask_url(url):
    """Маскирует чувствительные данные в URL"""
    if not url or url == 'NOT SET':
        return url
    
    if isinstance(url, str):
        if '@' in url:
            # Маскируем пароль в URL
            parts = url.split('@')
            if len(parts) == 2:
                user_pass = parts[0].split('://')
                if len(user_pass) == 2:
                    protocol = user_pass[0]
                    credentials = user_pass[1]
                    if ':' in credentials:
                        user = credentials.split(':')[0]
                        return f"{protocol}://{user}:***@{parts[1]}"
        return url[:50] + '...' if len(url) > 50 else url
    else:
        # SQLAlchemy URL object
        return str(url).split('@')[0] + '@***' if '@' in str(url) else str(url)

def _get_database_type(database_url):
    """Определяет тип базы данных из URL"""
    if not database_url or database_url == 'NOT SET':
        return 'UNKNOWN'
    
    if 'postgresql' in database_url or 'postgres' in database_url:
        return 'PostgreSQL'
    elif 'sqlite' in database_url:
        return 'SQLite'
    else:
        return 'UNKNOWN'

