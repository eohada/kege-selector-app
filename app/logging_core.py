"""
Unified structured logging for the platform.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any

from flask import has_request_context, request, g
from flask_login import current_user


class RequestContextFilter(logging.Filter):
    """Injects request/user context into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = getattr(record, "request_id", None)
        record.trace_id = getattr(record, "trace_id", None)
        record.user_id = getattr(record, "user_id", None)
        record.role = getattr(record, "role", None)
        record.url = getattr(record, "url", None)
        record.method = getattr(record, "method", None)
        record.remote_addr = getattr(record, "remote_addr", None)
        record.event = getattr(record, "event", None)
        record.entity = getattr(record, "entity", None)
        record.entity_id = getattr(record, "entity_id", None)
        record.status = getattr(record, "status", None)
        record.duration_ms = getattr(record, "duration_ms", None)

        if has_request_context():
            req_id = getattr(g, "request_id", None) or request.headers.get("X-Request-ID")
            if not record.request_id:
                record.request_id = req_id
            if not record.trace_id:
                record.trace_id = req_id
            if not record.url:
                record.url = request.path
            if not record.method:
                record.method = request.method
            if not record.remote_addr:
                record.remote_addr = request.remote_addr

            try:
                if current_user and current_user.is_authenticated:
                    if not record.user_id:
                        record.user_id = getattr(current_user, "id", None)
                    if not record.role:
                        record.role = getattr(current_user, "role", None)
            except Exception:
                pass

        return True


class JsonFormatter(logging.Formatter):
    """JSON formatter with stable schema for app logs."""

    def __init__(self, service_name: str):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": self.service_name,
            "module": record.name,
            "event": getattr(record, "event", None) or record.getMessage(),
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
            "trace_id": getattr(record, "trace_id", None),
            "user_id": getattr(record, "user_id", None),
            "role": getattr(record, "role", None),
            "url": getattr(record, "url", None),
            "method": getattr(record, "method", None),
            "remote_addr": getattr(record, "remote_addr", None),
            "entity": getattr(record, "entity", None),
            "entity_id": getattr(record, "entity_id", None),
            "status": getattr(record, "status", None),
            "duration_ms": getattr(record, "duration_ms", None),
        }

        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)

        for key, value in record.__dict__.items():
            if key.startswith("_"):
                continue
            if key in payload:
                continue
            if key in {
                "args",
                "asctime",
                "created",
                "exc_info",
                "exc_text",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "msg",
                "name",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "thread",
                "threadName",
            }:
                continue
            payload[key] = value

        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(base_dir: str, environment: str, service_name: str = "boostudy") -> logging.Logger:
    """Configures root logger with JSON output (console + rotating file)."""
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, log_level, logging.INFO)

    logs_dir = os.path.join(base_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    log_file = os.path.join(logs_dir, "app.log")

    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)

    formatter = JsonFormatter(service_name=service_name)
    context_filter = RequestContextFilter()

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.addFilter(context_filter)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(context_filter)
    root.addHandler(file_handler)

    logger = logging.getLogger(__name__)
    logger.info(
        "logging_initialized",
        extra={
            "event": "logging_initialized",
            "status": "success",
            "environment": environment,
            "log_level": log_level,
            "log_file": log_file,
            "ts_ms": int(time.time() * 1000),
        },
    )
    return logger

