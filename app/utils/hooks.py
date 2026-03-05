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
from datetime import datetime
from app.models import db, Lesson, Student, moscow_now, MOSCOW_TZ, UserSubscription, TariffPlan
from app.utils.subscription_access import get_effective_access_for_user, mark_subscription_expired_if_needed
from app.utils.db_migrations import ensure_schema_columns
from core.audit_logger import audit_logger

logger = logging.getLogger(__name__)

_schema_initialized = False

_last_lesson_check = None
_lesson_check_interval = timedelta(minutes=5)

_last_subscription_check = None
_subscription_check_interval = timedelta(minutes=10)

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
        
        if not _schema_initialized:
            try:
                ensure_schema_columns(app)
                _schema_initialized = True
                logger.info("Database schema initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize database schema: {e}", exc_info=True)
                _schema_initialized = True  # Помечаем как инициализированную, чтобы не повторять
                logger.info("Database schema initialized")
        
        if not audit_logger.is_running:
            audit_logger.start_worker()
    
    @app.before_request
    def auto_update_lesson_status():
        """Автоматически обновляет статус запланированных уроков на 'completed' после их окончания"""
        global _last_lesson_check
        
        if request.endpoint in ('static', 'favicon') or request.path.startswith('/static/'):
            return
        
        try:
            now = moscow_now()
            now_naive = now.replace(tzinfo=None) if getattr(now, 'tzinfo', None) else now
            last = _last_lesson_check
            last_naive = last.replace(tzinfo=None) if (last and getattr(last, 'tzinfo', None)) else last
            if last_naive and (now_naive - last_naive) < _lesson_check_interval:
                return
            
            _last_lesson_check = now_naive
            
            try:
                db_url = app.config.get('SQLALCHEMY_DATABASE_URI', '')
                
                
                if 'postgresql' in db_url or 'postgres' in db_url:
                    result = db.session.execute(text("""
                        UPDATE "Lessons" 
                        SET status = 'completed', updated_at = :now
                        WHERE status = 'planned' 
                        AND (lesson_date + (duration || ' minutes')::interval) <= :now
                    """), {'now': now_naive})
                    
                    result_ip = db.session.execute(text("""
                        UPDATE "Lessons" 
                        SET status = 'completed', updated_at = :now
                        WHERE status = 'in_progress' 
                        AND started_at IS NOT NULL 
                        AND (started_at + interval '60 minutes') <= :now
                    """), {'now': now_naive})
                else:
                    result = db.session.execute(text("""
                        UPDATE Lessons 
                        SET status = 'completed', updated_at = :now
                        WHERE status = 'planned' 
                        AND datetime(lesson_date, '+' || duration || ' minutes') <= :now
                    """), {'now': now_naive})
                    
                    result_ip = db.session.execute(text("""
                        UPDATE Lessons 
                        SET status = 'completed', updated_at = :now
                        WHERE status = 'in_progress' 
                        AND started_at IS NOT NULL 
                        AND datetime(started_at, '+60 minutes') <= :now
                    """), {'now': now_naive})
                
                updated_count = result.rowcount + result_ip.rowcount
                
                if updated_count > 0:
                    db.session.commit()
                    if updated_count > 5:  # Логируем только если обновлено много уроков
                        logger.info(f"Автоматически обновлено статусов уроков: {updated_count}")
            except Exception as e:
                logger.warning(f"Ошибка при массовом обновлении статусов, используем старый метод: {e}")
                try:
                    two_days_ago = now_naive - timedelta(days=2)
                    
                    lessons_to_check = Lesson.query.filter(
                        Lesson.status.in_(['planned', 'in_progress']),
                        Lesson.lesson_date >= two_days_ago
                    ).all()
                    
                    if not lessons_to_check:
                        return
                    
                    updated_count = 0
                    now_with_tz = now if getattr(now, 'tzinfo', None) else now.replace(tzinfo=MOSCOW_TZ)
                    for lesson in lessons_to_check:
                        if lesson.status == 'planned':
                            lesson_date_with_tz = lesson.lesson_date
                            if lesson_date_with_tz.tzinfo is None:
                                lesson_date_with_tz = lesson_date_with_tz.replace(tzinfo=MOSCOW_TZ)
                            
                            lesson_end_time = lesson_date_with_tz + timedelta(minutes=lesson.duration)
                            if now_with_tz >= lesson_end_time:
                                lesson.status = 'completed'
                                lesson.updated_at = now_naive
                                updated_count += 1
                        elif lesson.status == 'in_progress' and lesson.started_at:
                            started_at_with_tz = lesson.started_at
                            if started_at_with_tz.tzinfo is None:
                                started_at_with_tz = started_at_with_tz.replace(tzinfo=MOSCOW_TZ)
                            
                            if now_with_tz >= started_at_with_tz + timedelta(minutes=60):
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
            db.session.rollback()

    @app.before_request
    def auto_expire_subscriptions():
        """Автоматически помечает просроченные подписки как expired (раз в 10 мин)."""
        global _last_subscription_check

        if request.endpoint in ('static', 'favicon') or request.path.startswith('/static/'):
            return

        try:
            now = datetime.utcnow()
            last = _last_subscription_check
            if last and (now - last) < _subscription_check_interval:
                return

            _last_subscription_check = now

            expired_subs = UserSubscription.query.filter(
                UserSubscription.status == 'active',
                UserSubscription.ends_at.isnot(None),
                UserSubscription.ends_at < now,
            ).all()

            updated = 0
            for sub in expired_subs:
                sub.status = 'expired'
                updated += 1

            lessons_expired_subs = UserSubscription.query.filter(
                UserSubscription.status == 'active',
                UserSubscription.lessons_remaining.isnot(None),
                UserSubscription.lessons_remaining <= 0,
            ).all()

            for sub in lessons_expired_subs:
                sub.status = 'expired'
                updated += 1

            if updated > 0:
                db.session.commit()
                logger.info(f"auto_expire_subscriptions: marked {updated} subscription(s) as expired")
        except Exception as e:
            logger.error(f"auto_expire_subscriptions error: {e}", exc_info=True)
            try:
                db.session.rollback()
            except Exception:
                pass

    @app.before_request
    def check_maintenance_mode():
        """Проверка режима технических работ в песочнице - ДО проверки авторизации"""
        import os
        from flask import redirect, url_for
        from app.models import MaintenanceMode

        if request.path.startswith('/internal/sandbox-admin/'):
            return None
        
        if request.path.startswith('/internal/remote-admin/'):
            return None
        
        environment = os.environ.get('ENVIRONMENT', 'local')
        is_sandbox = environment == 'sandbox'
        
        if request.endpoint == 'static' or request.path.startswith('/static/'):
            return None
        
        if is_sandbox:
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
            
            maintenance_enabled = False
            maintenance_message = "Ведутся технические работы. Скоро вернемся!"
            
            maintenance_enabled_env = os.environ.get('MAINTENANCE_ENABLED', '').lower()
            if maintenance_enabled_env in ('true', '1', 'yes', 'on'):
                maintenance_enabled = True
                logger.info(f"Maintenance mode from ENV: enabled=True (MAINTENANCE_ENABLED={maintenance_enabled_env})")
            else:
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
                        try:
                            maintenance_enabled = MaintenanceMode.is_maintenance_enabled()
                            status = MaintenanceMode.get_status()
                            maintenance_message = status.message
                            logger.info(f"Maintenance mode from local DB (after error): enabled={maintenance_enabled}")
                        except Exception as db_error:
                            logger.warning(f"Ошибка при проверке режима тех работ из БД: {db_error}")
                            maintenance_enabled = False
                else:
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
                return redirect(url_for('admin.maintenance_page', message=maintenance_message))
        
        return None
    
    @app.before_request
    def require_login():
        """Проверка авторизации для всех маршрутов кроме login, logout и static"""
        if request.path.startswith('/remote-admin/'):
            logger.info(f"require_login hook: path={request.path}, endpoint={request.endpoint}, authenticated={current_user.is_authenticated if hasattr(current_user, 'is_authenticated') else False}")
        
        excluded_endpoints = ('auth.login', 'auth.logout', 'static', 'main.font_files', 'admin.maintenance_status_api', 'admin.maintenance_page', 'main.setup_first_user', 'main.health_check', 'main.landing', 'main.index', 'main.legal_offer', 'main.legal_privacy', 'main.faq', 'billing.billing_plans_public')
        excluded_paths = ('/', '/landing', '/index', '/home', '/legal/offer', '/legal/privacy', '/faq', '/billing/plans/public')
        
        if (request.endpoint in excluded_endpoints or 
            request.path in excluded_paths or 
            request.path.startswith('/static/') or 
            request.path.startswith('/font/')):
            return

        if request.path.startswith('/internal/sandbox-admin/'):
            return
        
        if request.path.startswith('/internal/remote-admin/'):
            return

        if request.path.startswith('/internal/trainer/'):
            return
        
        if not current_user.is_authenticated:
            if request.endpoint and request.endpoint != 'auth.login':
                logger.info(f"require_login: redirecting unauthenticated user from {request.path} to login")
                return redirect(url_for('auth.login', next=request.url))

    @app.before_request
    def enforce_subscription_access():
        """
        Продажные форматы доступа (ученик/родитель):
        - уроки
        - тренажёр
        - уроки + тренажёр

        Важно: включаем ограничение только если у активной подписки есть тариф и в нём явно заданы allow_lessons/allow_trainer.
        Иначе оставляем старое поведение (backward compatible).
        """
        try:
            if not getattr(current_user, 'is_authenticated', False):
                return None
            if getattr(current_user, 'is_admin', lambda: False)() or getattr(current_user, 'is_creator', lambda: False)() or getattr(current_user, 'is_tutor', lambda: False)():
                return None

            if not (getattr(current_user, 'is_student', lambda: False)() or getattr(current_user, 'is_parent', lambda: False)()):
                return None

            if request.path.startswith('/internal/remote-admin/') or request.path.startswith('/internal/sandbox-admin/'):
                return None
            if request.path.startswith('/static/') or request.path.startswith('/font/'):
                return None
            if request.path.startswith('/api/telegram/'):
                return None

            eff = get_effective_access_for_user(current_user.id)
            sub = eff.subscription
            plan = eff.plan

            if not sub or not plan:
                return None

            if eff.status == 'expired':
                try:
                    mark_subscription_expired_if_needed(sub)
                except Exception:
                    pass
                if (request.endpoint or '').startswith('auth.') or request.endpoint in ('auth.logout', 'auth.user_profile'):
                    return None
                if request.path.startswith('/api/telegram/'):
                    return None
                if request.path.startswith('/internal/trainer/') or (request.endpoint or '').startswith('trainer.'):
                    return redirect(url_for('auth.user_profile'))
                return redirect(url_for('auth.user_profile'))

            if plan.allow_lessons is None and plan.allow_trainer is None:
                return None

            allow_lessons = True if plan.allow_lessons is None else bool(plan.allow_lessons)
            allow_trainer = True if plan.allow_trainer is None else bool(plan.allow_trainer)

            ep = (request.endpoint or '')
            if request.path.startswith('/internal/trainer/') or ep.startswith('trainer.'):
                if not allow_trainer:
                    return redirect(url_for('main.dashboard'))
                return None

            if not allow_lessons and allow_trainer:
                allowed_student_endpoints = {
                    'students.student_analytics',
                    'students.student_statistics',
                }
                if ep == 'main.student_dashboard':
                    return redirect(url_for('trainer.trainer_embed'))
                if ep in allowed_student_endpoints:
                    return None
                if ep.startswith('auth.'):
                    return None
                if request.path.startswith('/api/telegram/'):
                    return None
                return redirect(url_for('trainer.trainer_embed'))

            lesson_prefixes = (
                'lessons.',
                'schedule.',
                'students.',
                'assignments.',
                'task_generator.',
                'diagnostics.',
                'gradebook.',
                'groups.',
                'courses.',
                'main.student_dashboard',
            )
            if ep == 'main.student_dashboard' or any(ep.startswith(pfx) for pfx in lesson_prefixes if pfx != 'main.student_dashboard'):
                if not allow_lessons:
                    return redirect(url_for('main.dashboard'))
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            return None
        return None
    
    @app.context_processor
    def inject_current_student():
        """Добавляет current_student и moscow_now в контекст шаблонов"""
        current_student = None
        if current_user.is_authenticated and current_user.is_student():
            current_student = Student.query.filter_by(user_id=current_user.id).first()
        return dict(current_student=current_student, moscow_now=moscow_now)

    @app.context_processor
    def inject_subscription_access():
        """
        Добавляет subscription_access в шаблоны:
        - allow_lessons / allow_trainer (если определено тарифом)
        - label / ends_at / seconds_left
        """
        try:
            if not getattr(current_user, 'is_authenticated', False):
                return dict(subscription_access=None)
            eff = get_effective_access_for_user(current_user.id)
            return dict(subscription_access=eff)
        except Exception:
            return dict(subscription_access=None)

    @app.before_request
    def identify_tester():
        """Идентификация тестировщика (только для неавторизованных пользователей)"""
        try:
            if request.endpoint in ('static', 'favicon') or request.path.startswith('/static/'):
                return

            if current_user.is_authenticated:
                return

            tester_name_raw = request.headers.get('X-Tester-Name')
            tester_name_encoded = request.headers.get('X-Tester-Name-Encoded')
            if tester_name_raw and tester_name_encoded == 'base64':
                try:
                    decoded_bytes = base64.b64decode(tester_name_raw)
                    tester_name = urllib.parse.unquote(decoded_bytes.decode('utf-8'))
                except Exception as e:
                    logger.warning(f"Ошибка декодирования имени тестировщика: {e}")
                    tester_name = tester_name_raw
            else:
                tester_name = tester_name_raw
        except Exception as e:
            logger.error(f"Ошибка при идентификации тестировщика: {e}", exc_info=True)
            db.session.rollback()

