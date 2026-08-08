import json
import os
import logging
from datetime import datetime
from flask import request, has_request_context

logger = logging.getLogger(__name__)

class UnifiedAuditLogger:
    """Двухрежимный движок аудита BooStudy V2 (local JSON-лог & platform DB-лог)"""

    def __init__(self, log_file_path=None):
        self.log_file_path = log_file_path or os.path.abspath(
            os.path.join(os.path.dirname(__file__), '../logs/audit_local.log')
        )
        os.makedirs(os.path.dirname(self.log_file_path), exist_ok=True)

    def log_event(self, action: str, user_id: int = None, source: str = 'web', entity: str = None, status: str = 'SUCCESS', details: dict = None, mode: str = 'both'):
        """
        Записывает событие аудита.
        mode: 'local', 'platform', or 'both'
        """
        now_iso = datetime.utcnow().isoformat()
        ip_addr = None
        if has_request_context():
            ip_addr = request.headers.get('X-Forwarded-For', request.remote_addr)

        event_payload = {
            'timestamp': now_iso,
            'user_id': user_id,
            'source': source,
            'action': action,
            'entity': entity,
            'status': status,
            'ip_address': ip_addr,
            'details': details or {}
        }

        # 1. Local Mode: append to JSON log file
        if mode in ['local', 'both']:
            try:
                with open(self.log_file_path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(event_payload, ensure_ascii=False) + '\n')
            except Exception as e:
                logger.error(f"Failed writing local audit log: {e}")

        # 2. Platform Mode: save to AuditLog DB model
        if mode in ['platform', 'both']:
            try:
                from core.db_models import db, AuditLog
                log_entry = AuditLog(
                    user_id=user_id,
                    source=source,
                    action=action,
                    entity=entity,
                    status=status,
                    ip_address=ip_addr,
                    details=json.dumps(details or {}, ensure_ascii=False) if details else None
                )
                db.session.add(log_entry)
                db.session.commit()
            except Exception as e:
                logger.error(f"Failed writing DB audit log: {e}")

audit_logger = UnifiedAuditLogger()
