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
from app.models import db, Lesson, moscow_now
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
                if 'postgresql' in db_url or 'postgres' in db_url:
                    # PostgreSQL синтаксис
                    result = db.session.execute(text("""
                        UPDATE "Lessons" 
                        SET status = 'completed', updated_at = :now
                        WHERE status = 'planned' 
                        AND (lesson_date + (duration || ' minutes')::interval) <= :now
                    """), {'now': now})
                else:
                    # SQLite синтаксис
                    result = db.session.execute(text("""
                        UPDATE Lessons 
                        SET status = 'completed', updated_at = :now
                        WHERE status = 'planned' 
                        AND datetime(lesson_date, '+' || duration || ' minutes') <= :now
                    """), {'now': now})
                
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
                    yesterday = now - timedelta(days=1)
                    planned_lessons = Lesson.query.filter(
                        Lesson.status == 'planned',
                        Lesson.lesson_date >= yesterday
                    ).all()
                    
                    if not planned_lessons:
                        return
                    
                    updated_count = 0
                    for lesson in planned_lessons:
                        lesson_end_time = lesson.lesson_date + timedelta(minutes=lesson.duration)
                        if now >= lesson_end_time:
                            lesson.status = 'completed'
                            lesson.updated_at = now
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
    def require_login():
        """Проверка авторизации для всех маршрутов кроме login, logout и static"""
        # Исключаем маршруты, которые не требуют авторизации
        if request.endpoint in ('auth.login', 'auth.logout', 'static', 'main.font_files') or request.path.startswith('/static/') or request.path.startswith('/font/'):
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

