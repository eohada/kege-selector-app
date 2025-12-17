
import json
import logging
import threading
import queue
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from flask import request, session, has_request_context
from sqlalchemy.exc import OperationalError, ProgrammingError

from .db_models import db, AuditLog, Tester, moscow_now

logger = logging.getLogger(__name__)

class AuditLogger:

    def __init__(self, app=None):

        self.app = app
        self.log_queue = queue.Queue()
        self.worker_thread = None
        self.is_running = False

        if app:
            self.init_app(app)

    def init_app(self, app):

        self.app = app

        import atexit
        atexit.register(self.stop_worker)

    def start_worker(self):

        if self.is_running:
            return

        if not self.app:
            logger.warning("Cannot start audit logger worker: app not initialized")
            return

        self.is_running = True
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()
        logger.info("AuditLogger worker thread started")

    def stop_worker(self):

        self.is_running = False
        if self.worker_thread:
            self.log_queue.put(None)
            self.worker_thread.join(timeout=5)
            logger.info("AuditLogger worker thread stopped")

    def _worker_loop(self):

        # Небольшая задержка, чтобы приложение успело полностью инициализироваться
        time.sleep(0.5)
        
        while self.is_running:
            try:
                log_data = self.log_queue.get(timeout=1)
                if log_data is None:
                    break

                # Создаем контекст приложения для каждой операции записи
                if self.app:
                    try:
                        with self.app.app_context():
                            self._write_log(log_data)
                    except Exception as e:
                        logger.error(f"Error writing audit log (with context): {e}", exc_info=True)
                else:
                    logger.warning("Cannot write audit log: app not initialized")
                
                self.log_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error in audit logger worker: {e}", exc_info=True)

    def _write_log(self, log_data: Dict[str, Any]):

        try:
            from core.db_models import AuditLog, User, Tester
            
            # Логируем только для авторизованных пользователей
            user_id = log_data.get('user_id')
            if not user_id:
                logger.debug("Skipping audit log: user not authenticated")
                return
            
            # Проверяем, существует ли пользователь в базе
            user = User.query.get(user_id)
            if not user:
                logger.warning(f"User {user_id} not found in database, skipping audit log")
                return
            
            audit_log = AuditLog()
            audit_log.timestamp = log_data.get('timestamp', moscow_now())
            audit_log.user_id = user_id
            audit_log.tester_name = log_data.get('user_name')  # Имя авторизованного пользователя
            audit_log.action = log_data.get('action', 'unknown')
            audit_log.entity = log_data.get('entity')
            audit_log.entity_id = log_data.get('entity_id')
            audit_log.status = log_data.get('status', 'info')
            audit_log.set_metadata(log_data.get('metadata', {}))
            audit_log.ip_address = log_data.get('ip_address')
            audit_log.user_agent = log_data.get('user_agent')
            # Обрезаем session_id если слишком длинный
            session_id = log_data.get('session_id')
            if session_id and len(session_id) > 500:
                session_id = session_id[:500]
            audit_log.session_id = session_id
            audit_log.duration_ms = log_data.get('duration_ms')
            audit_log.url = log_data.get('url')
            audit_log.method = log_data.get('method')

            db.session.add(audit_log)
            db.session.commit()
            logger.debug(f"Audit log written: {audit_log.action} by {audit_log.tester_name} (user_id: {user_id})")
        except (OperationalError, ProgrammingError) as e:
            # Ошибка структуры БД - возможно, таблица не обновлена
            db.session.rollback()
            error_msg = str(e)
            if 'user_id' in error_msg.lower() or 'column' in error_msg.lower():
                logger.error(f"Database schema error in AuditLog: {e}. Table may need migration.")
                # Пытаемся вызвать миграцию
                try:
                    from app.utils.db_migrations import ensure_schema_columns
                    from flask import current_app
                    ensure_schema_columns(current_app)
                    logger.info("Attempted to fix AuditLog schema, retrying log write...")
                    # Не повторяем запись автоматически, чтобы избежать бесконечного цикла
                except Exception as migration_error:
                    logger.error(f"Failed to migrate AuditLog schema: {migration_error}")
            else:
                logger.error(f"Database error writing audit log: {e}")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error writing audit log: {e}", exc_info=True)
            # Пробуем вывести детали ошибки
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

    def _get_tester_info(self) -> Dict[str, Any]:
        """Получает информацию о пользователе для логирования"""
        from flask_login import current_user
        
        user_id = None
        user_name = None
        tester_id = None
        tester_name = None
        session_id = None

        if has_request_context():
            # Приоритет: используем авторизованного пользователя из Flask-Login
            if current_user.is_authenticated:
                user_id = current_user.id
                user_name = current_user.username
            else:
                # Для неавторизованных пользователей не логируем
                return {
                    'user_id': None,
                    'user_name': None,
                    'tester_id': None,
                    'tester_name': None,
                    'session_id': None
                }
            
            session_id = session.get('_id', request.cookies.get('session'))

        return {
            'user_id': user_id,
            'user_name': user_name,
            'tester_id': tester_id,
            'tester_name': tester_name,
            'session_id': session_id
        }

    def _ensure_tester_exists(self, tester_id: str, tester_name: Optional[str]):
        """Устаревший метод - больше не используется, так как логируем только авторизованных пользователей"""
        # Метод оставлен для обратной совместимости, но не выполняет никаких действий
        # Логирование теперь происходит только для авторизованных пользователей через Flask-Login
        pass

    def _get_request_info(self) -> Dict[str, Any]:

        if not has_request_context():
            return {}

        return {
            'ip_address': request.remote_addr,
            'user_agent': request.headers.get('User-Agent'),
            'url': request.url,
            'method': request.method,
            'referer': request.headers.get('Referer')
        }

    def log(self, action: str, entity: Optional[str] = None, entity_id: Optional[int] = None,
            status: str = 'success', metadata: Optional[Dict[str, Any]] = None,
            duration_ms: Optional[int] = None):

        # Логируем только для авторизованных пользователей
        from flask_login import current_user
        if not has_request_context() or not current_user.is_authenticated:
            logger.debug(f"Skipping audit log for action '{action}': user not authenticated")
            return

        # Ленивая инициализация worker thread при первом вызове
        if not self.is_running:
            if not self.app:
                logger.warning("Cannot log: audit logger app not initialized")
                return
            self.start_worker()

        try:
            user_info = self._get_tester_info()
            request_info = self._get_request_info()

            # Проверяем, что есть user_id (пользователь авторизован)
            if not user_info.get('user_id'):
                logger.debug(f"Skipping audit log for action '{action}': no user_id")
                return

            full_metadata = metadata or {}
            if request_info.get('referer'):
                full_metadata['referer'] = request_info.get('referer')

            log_data = {
                'timestamp': moscow_now(),
                'user_id': user_info.get('user_id'),
                'user_name': user_info.get('user_name'),
                'tester_id': user_info.get('tester_id'),  # Оставляем для обратной совместимости
                'tester_name': user_info.get('user_name'),  # Используем имя пользователя
                'action': action,
                'entity': entity,
                'entity_id': entity_id,
                'status': status,
                'metadata': full_metadata,
                'ip_address': request_info.get('ip_address'),
                'user_agent': request_info.get('user_agent'),
                'session_id': user_info.get('session_id'),
                'duration_ms': duration_ms,
                'url': request_info.get('url'),
                'method': request_info.get('method')
            }

            self.log_queue.put(log_data)
            logger.debug(f"Audit log queued: {action} by {user_info.get('user_name', 'Unknown')}")
        except Exception as e:
            logger.error(f"Error queuing audit log: {e}", exc_info=True)

    def log_page_view(self, page_name: str, metadata: Optional[Dict[str, Any]] = None):

        self.log(
            action='page_view',
            entity='Page',
            entity_id=None,
            status='success',
            metadata={'page_name': page_name, **(metadata or {})}
        )

    def log_error(self, action: str, entity: Optional[str] = None, error: Optional[str] = None,
                  traceback: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):

        error_metadata = metadata or {}
        if error:
            error_metadata['error'] = error
        if traceback:
            error_metadata['traceback'] = traceback

        self.log(
            action=action,
            entity=entity,
            status='error',
            metadata=error_metadata
        )

audit_logger = AuditLogger()
