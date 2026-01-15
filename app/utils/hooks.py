"""
Хуки before_request для Flask приложения
"""
import logging
import base64
import urllib.parse
from datetime import timedelta
from flask import request, redirect, url_for
from flask_login import current_user
from sqlalchemy import text
from app.models import db, Lesson, moscow_now, MOSCOW_TZ
from app.utils.db_migrations import ensure_schema_columns
from core.audit_logger import audit_logger

logger = logging.getLogger(__name__)

# Флаг для отслеживания, была ли выполнена инициализация схемы
_schema_initialized = False

# Кеш для отслеживания времени последней проверки уроков
_last_lesson_check = None
_lesson_check_interval = timedelta(minutes=5)  # Проверяем не чаще раза в 5 минут для оптимизации

def register_hooks(app):
    """
    Регистрирует все before_request хуки для приложения
    """
    
    @app.before_request
    def ensure_audit_logger_worker():
        """Запускаем worker thread для audit logger при первом запросе"""
        if not audit_logger.is_running:
            audit_logger.start_worker()
    
    @app.before_request
    def initialize_on_first_request():
        """Инициализация схемы БД при первом запросе"""
        global _schema_initialized
        
        # Инициализируем схему БД при первом запросе
        if not _schema_initialized:
            try:
                ensure_schema_columns(app)
                _schema_initialized = True
                logger.info("Database schema initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize database schema: {e}", exc_info=True)
                # Не блокируем запрос, если миграция не удалась
                _schema_initialized = True  # Помечаем как инициализированную, чтобы не повторять
                logger.info("Database schema initialized")
        
        # Запускаем worker thread для audit logger при первом запросе
        if not audit_logger.is_running:
            audit_logger.start_worker()
    
    @app.before_request
    def auto_update_lesson_status():
        """Автоматически обновляет статус запланированных уроков на 'completed' после их окончания"""
        global _last_lesson_check
        
        # Пропускаем статические файлы
        if request.endpoint in ('static', 'favicon') or request.path.startswith('/static/'):
            return
        
        try:
            # Проверяем не чаще чем раз в минуту
            now = moscow_now()
            if _last_lesson_check and (now - _last_lesson_check) < _lesson_check_interval:
                return
            
            _last_lesson_check = now
            
            # Оптимизация: обновляем статусы напрямую через SQL, без загрузки всех уроков
            # Находим уроки, которые должны быть завершены (время окончания прошло)
            # lesson_date + duration <= now означает, что урок уже закончился
            try:
                # Используем SQL для массового обновления
                # Проверяем тип БД и используем соответствующий синтаксис
                db_url = app.config.get('SQLALCHEMY_DATABASE_URI', '')
                
                # Конвертируем now в naive datetime для сравнения с lesson_date в БД
                # lesson_date хранится как naive datetime в московском времени
                now_naive = now.replace(tzinfo=None) if now.tzinfo else now
                
                if 'postgresql' in db_url or 'postgres' in db_url:
                    # PostgreSQL синтаксис
                    # lesson_date хранится как naive datetime, считаем что это московское время
                    result = db.session.execute(text("""
                        UPDATE "Lessons" 
                        SET status = 'completed', updated_at = :now
                        WHERE status = 'planned' 
                        AND (lesson_date + (duration || ' minutes')::interval) <= :now
                    """), {'now': now_naive})
                else:
                    # SQLite синтаксис
                    result = db.session.execute(text("""
                        UPDATE Lessons 
                        SET status = 'completed', updated_at = :now
                        WHERE status = 'planned' 
                        AND datetime(lesson_date, '+' || duration || ' minutes') <= :now
                    """), {'now': now_naive})
                
                updated_count = result.rowcount
                
                if updated_count > 0:
                    db.session.commit()
                    # Уменьшаем логирование - только если обновлено больше 0
                    if updated_count > 5:  # Логируем только если обновлено много уроков
                        logger.info(f"Автоматически обновлено статусов уроков: {updated_count}")
            except Exception as e:
                # Fallback на старый метод, если SQL не работает
                logger.warning(f"Ошибка при массовом обновлении статусов, используем старый метод: {e}")
                try:
                    # Фильтруем только уроки, которые могли закончиться (за последние 24 часа)
                    # Конвертируем now в naive для сравнения с lesson_date в БД
                    now_naive = now.replace(tzinfo=None) if now.tzinfo else now
                    yesterday = now_naive - timedelta(days=1)
                    
                    planned_lessons = Lesson.query.filter(
                        Lesson.status == 'planned',
                        Lesson.lesson_date >= yesterday
                    ).all()
                    
                    if not planned_lessons:
                        return
                    
                    updated_count = 0
                    for lesson in planned_lessons:
                        # lesson.lesson_date может быть naive, нужно добавить timezone для сравнения
                        lesson_date_with_tz = lesson.lesson_date
                        if lesson_date_with_tz.tzinfo is None:
                            # Если naive, считаем что это московское время
                            lesson_date_with_tz = lesson_date_with_tz.replace(tzinfo=MOSCOW_TZ)
                        
                        lesson_end_time = lesson_date_with_tz + timedelta(minutes=lesson.duration)
                        if now >= lesson_end_time:
                            lesson.status = 'completed'
                            lesson.updated_at = now_naive
                            updated_count += 1
                    
                    if updated_count > 0:
                        db.session.commit()
                        logger.info(f"Автоматически обновлено статусов уроков: {updated_count}")
                except Exception as e2:
                    logger.error(f"Ошибка при обновлении статусов уроков: {e2}", exc_info=True)
                    db.session.rollback()
        
        except Exception as e:
            logger.error(f"Ошибка при автоматическом обновлении статуса уроков: {e}", exc_info=True)
            # Не блокируем запрос при ошибке
            db.session.rollback()
    
    @app.before_request
    def check_maintenance_mode():
        """Проверка режима технических работ в песочнице - ДО проверки авторизации"""
        import os
        from flask import redirect, url_for
        from app.models import MaintenanceMode

        if request.path.startswith('/internal/sandbox-admin/'):
            return None
        
        # Получаем окружение - проверяем оба варианта
        environment = os.environ.get('ENVIRONMENT', 'local')
        railway_environment = os.environ.get('RAILWAY_ENVIRONMENT', '')
        
        # Определяем, что это песочница (либо ENVIRONMENT=sandbox, либо RAILWAY_ENVIRONMENT указывает на sandbox)
        is_sandbox = environment == 'sandbox' or 'sandbox' in railway_environment.lower()
        
        # Пропускаем статические файлы сразу
        if request.endpoint == 'static' or request.path.startswith('/static/'):
            return None
        
        # Проверяем тех работы только в песочнице
        if is_sandbox:
            # Исключаем саму страницу тех работ и админ панель из редиректа
            excluded_endpoints = [
                'admin.maintenance_page', 
                'admin.admin_panel', 
                'admin.toggle_maintenance', 
                'admin.update_maintenance_message',
                'auth.login', 
                'auth.logout',
                'static'
            ]
            
            if request.endpoint in excluded_endpoints:
                logger.debug(f"Maintenance check: endpoint {request.endpoint} excluded from redirect")
                return None
            
            # В песочнице проверяем статус тех работ из продакшена через API
            # Приоритет: 1) переменная окружения MAINTENANCE_ENABLED, 2) API продакшена, 3) локальная БД
            maintenance_enabled = False
            maintenance_message = "Ведутся технические работы. Скоро вернемся!"
            
            # Сначала проверяем переменную окружения (самый быстрый способ)
            maintenance_enabled_env = os.environ.get('MAINTENANCE_ENABLED', '').lower()
            if maintenance_enabled_env in ('true', '1', 'yes', 'on'):
                maintenance_enabled = True
                logger.info(f"Maintenance mode from ENV: enabled=True (MAINTENANCE_ENABLED={maintenance_enabled_env})")
            else:
                # Если переменная не установлена, проверяем API продакшена
                production_url = os.environ.get('PRODUCTION_URL', '')
                if production_url:
                    try:
                        import requests
                        api_url = f"{production_url.rstrip('/')}/api/maintenance-status"
                        logger.debug(f"Checking maintenance status from production API: {api_url}")
                        response = requests.get(api_url, timeout=5, headers={'User-Agent': 'Sandbox-Maintenance-Checker/1.0'})
                        logger.debug(f"Production API response: status={response.status_code}, content-type={response.headers.get('Content-Type', 'unknown')}, content-preview={response.text[:200]}")
                        
                        if response.status_code == 200:
                            try:
                                data = response.json()
                                maintenance_enabled = data.get('enabled', False)
                                maintenance_message = data.get('message', maintenance_message)
                                logger.info(f"Maintenance mode from PRODUCTION API: enabled={maintenance_enabled}, message={maintenance_message[:50]}")
                            except ValueError as json_error:
                                logger.error(f"Failed to parse JSON from production API: {json_error}. Response text: {response.text[:500]}")
                                raise Exception(f"Invalid JSON response: {json_error}")
                        else:
                            logger.warning(f"Production API returned status {response.status_code}, response: {response.text[:200]}")
                            raise Exception(f"API returned {response.status_code}")
                    except requests.exceptions.RequestException as req_error:
                        logger.warning(f"Network error when requesting production API: {req_error}, проверяем локальную БД")
                        # Fallback на локальную БД
                        try:
                            maintenance_enabled = MaintenanceMode.is_maintenance_enabled()
                            status = MaintenanceMode.get_status()
                            maintenance_message = status.message
                            logger.info(f"Maintenance mode from local DB (after API error): enabled={maintenance_enabled}")
                        except Exception as db_error:
                            logger.warning(f"Ошибка при проверке режима тех работ из БД: {db_error}")
                            maintenance_enabled = False
                    except Exception as e:
                        logger.error(f"Ошибка при запросе к API продакшена: {e}, проверяем локальную БД", exc_info=True)
                        # Fallback на локальную БД
                        try:
                            maintenance_enabled = MaintenanceMode.is_maintenance_enabled()
                            status = MaintenanceMode.get_status()
                            maintenance_message = status.message
                            logger.info(f"Maintenance mode from local DB (after error): enabled={maintenance_enabled}")
                        except Exception as db_error:
                            logger.warning(f"Ошибка при проверке режима тех работ из БД: {db_error}")
                            maintenance_enabled = False
                else:
                    # Если PRODUCTION_URL не установлен, проверяем локальную БД
                    try:
                        maintenance_enabled = MaintenanceMode.is_maintenance_enabled()
                        status = MaintenanceMode.get_status()
                        maintenance_message = status.message
                        logger.info(f"Maintenance mode from local DB: enabled={maintenance_enabled}")
                    except Exception as db_error:
                        logger.warning(f"Ошибка при проверке режима тех работ из БД: {db_error}")
                        maintenance_enabled = False
            
            logger.info(f"Maintenance mode check: enabled={maintenance_enabled}, endpoint={request.endpoint}, path={request.path}")
            
            if maintenance_enabled:
                logger.info(f"Maintenance mode enabled in sandbox, redirecting from {request.path} to maintenance page with message: {maintenance_message[:50]}")
                # Редиректим на страницу тех работ, передавая сообщение через query параметр
                return redirect(url_for('admin.maintenance_page', message=maintenance_message))
        
        return None
    
    @app.before_request
    def require_login():
        """Проверка авторизации для всех маршрутов кроме login, logout и static"""
        # Исключаем маршруты, которые не требуют авторизации
        excluded_endpoints = ('auth.login', 'auth.logout', 'static', 'main.font_files', 'admin.maintenance_status_api', 'admin.maintenance_page', 'main.setup_first_user', 'main.health_check')
        if request.endpoint in excluded_endpoints or request.path.startswith('/static/') or request.path.startswith('/font/'):
            return

        # Внутренний sandbox-admin API — server-to-server по токену, не требует Flask-Login
        if request.path.startswith('/internal/sandbox-admin/'):
            return
        
        # Внутренний remote-admin API — server-to-server по токену, не требует Flask-Login
        if request.path.startswith('/internal/remote-admin/'):
            return
        
        # Проверяем авторизацию
        if not current_user.is_authenticated:
            # Сохраняем URL для редиректа после входа
            if request.endpoint and request.endpoint != 'auth.login':
                return redirect(url_for('auth.login', next=request.url))
    
    @app.before_request
    def identify_tester():
        """Идентификация тестировщика (только для неавторизованных пользователей)"""
        try:
            # Пропускаем для статических файлов
            if request.endpoint in ('static', 'favicon') or request.path.startswith('/static/'):
                return

            # Для авторизованных пользователей не создаем тестировщиков
            # Логирование будет происходить через Flask-Login
            if current_user.is_authenticated:
                return

            # Получаем имя тестировщика из заголовка, декодируя если нужно
            # HTTP заголовки должны содержать только ISO-8859-1 символы
            # Если имя содержит не-ASCII символы, оно кодируется в base64
            tester_name_raw = request.headers.get('X-Tester-Name')
            tester_name_encoded = request.headers.get('X-Tester-Name-Encoded')
            if tester_name_raw and tester_name_encoded == 'base64':
                # Декодируем из base64
                try:
                    # Декодируем base64
                    decoded_bytes = base64.b64decode(tester_name_raw)
                    # Декодируем URI компонент
                    tester_name = urllib.parse.unquote(decoded_bytes.decode('utf-8'))
                except Exception as e:
                    logger.warning(f"Ошибка декодирования имени тестировщика: {e}")
                    tester_name = tester_name_raw
            else:
                tester_name = tester_name_raw
            # Для неавторизованных пользователей больше не создаем тестировщиков
            # Логирование происходит только для авторизованных пользователей через Flask-Login
            # Старая логика создания тестировщиков удалена
        except Exception as e:
            logger.error(f"Ошибка при идентификации тестировщика: {e}", exc_info=True)
            db.session.rollback()

