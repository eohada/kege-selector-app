
import json
import logging
import threading
import queue
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from flask import request, session, has_request_context

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
        self.start_worker()

        import atexit
        atexit.register(self.stop_worker)

    def start_worker(self):

        if self.is_running:
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

        with self.app.app_context():
            while self.is_running:
                try:
                    log_data = self.log_queue.get(timeout=1)
                    if log_data is None:
                        break

                    self._write_log(log_data)
                    self.log_queue.task_done()
                except queue.Empty:
                    continue
                except Exception as e:
                    logger.error(f"Error in audit logger worker: {e}", exc_info=True)

    def _write_log(self, log_data: Dict[str, Any]):

        try:
            audit_log = AuditLog()
            audit_log.timestamp = log_data.get('timestamp', moscow_now())
            audit_log.tester_id = log_data.get('tester_id')
            audit_log.tester_name = log_data.get('tester_name')
            audit_log.action = log_data.get('action', 'unknown')
            audit_log.entity = log_data.get('entity')
            audit_log.entity_id = log_data.get('entity_id')
            audit_log.status = log_data.get('status', 'info')
            audit_log.set_metadata(log_data.get('metadata', {}))
            audit_log.ip_address = log_data.get('ip_address')
            audit_log.user_agent = log_data.get('user_agent')
            audit_log.session_id = log_data.get('session_id')
            audit_log.duration_ms = log_data.get('duration_ms')
            audit_log.url = log_data.get('url')
            audit_log.method = log_data.get('method')

            db.session.add(audit_log)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error writing audit log: {e}", exc_info=True)

    def _get_tester_info(self) -> Dict[str, Any]:

        tester_id = None
        tester_name = None
        session_id = None

        if has_request_context():
            tester_id = session.get('tester_id')
            tester_name = session.get('tester_name')
            session_id = session.get('_id', request.cookies.get('session'))

            if tester_id:
                self._ensure_tester_exists(tester_id, tester_name)

        return {
            'tester_id': tester_id,
            'tester_name': tester_name,
            'session_id': session_id
        }

    def _ensure_tester_exists(self, tester_id: str, tester_name: Optional[str]):

        try:
            tester = Tester.query.get(tester_id)
            if not tester:
                tester = Tester(
                    tester_id=tester_id,
                    name=tester_name or 'Anonymous',
                    ip_address=request.remote_addr if has_request_context() else None,
                    user_agent=request.headers.get('User-Agent') if has_request_context() else None,
                    session_id=session.get('_id') if has_request_context() else None
                )
                db.session.add(tester)
            else:
                tester.last_seen = moscow_now()
                if tester_name and tester.name != tester_name:
                    tester.name = tester_name
                if has_request_context():
                    if request.remote_addr:
                        tester.ip_address = request.remote_addr
                    if request.headers.get('User-Agent'):
                        tester.user_agent = request.headers.get('User-Agent')

            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error ensuring tester exists: {e}", exc_info=True)

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

        try:
            tester_info = self._get_tester_info()
            request_info = self._get_request_info()

            full_metadata = metadata or {}
            if request_info.get('referer'):
                full_metadata['referer'] = request_info.get('referer')

            log_data = {
                'timestamp': moscow_now(),
                'tester_id': tester_info.get('tester_id'),
                'tester_name': tester_info.get('tester_name'),
                'action': action,
                'entity': entity,
                'entity_id': entity_id,
                'status': status,
                'metadata': full_metadata,
                'ip_address': request_info.get('ip_address'),
                'user_agent': request_info.get('user_agent'),
                'session_id': tester_info.get('session_id'),
                'duration_ms': duration_ms,
                'url': request_info.get('url'),
                'method': request_info.get('method')
            }

            self.log_queue.put(log_data)
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
