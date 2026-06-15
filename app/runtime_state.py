from __future__ import annotations

import json
import os
import threading
from typing import Any

import redis
from flask import current_app
from sqlalchemy import text

_redis_client = None
_redis_lock = threading.Lock()


def _resolve_redis_url() -> str | None:
    app = current_app._get_current_object() if current_app else None
    if app:
        url = (app.config.get("REDIS_URL") or "").strip()
        if url:
            return url
    for env_name in ("REDIS_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND"):
        raw = (os.environ.get(env_name) or "").strip()
        if raw.startswith("redis://") or raw.startswith("rediss://"):
            return raw
    return None


def get_redis_client():
    global _redis_client
    url = _resolve_redis_url()
    if not url:
        return None
    if _redis_client is not None:
        return _redis_client
    with _redis_lock:
        if _redis_client is not None:
            return _redis_client
        _redis_client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            health_check_interval=30,
        )
    return _redis_client


def redis_ping() -> bool:
    client = get_redis_client()
    if client is None:
        return False
    try:
        return bool(client.ping())
    except Exception:
        return False


def set_json(key: str, value: Any, ttl_seconds: int | None = None) -> None:
    client = get_redis_client()
    if client is None:
        return
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if ttl_seconds:
        client.setex(key, ttl_seconds, payload)
    else:
        client.set(key, payload)


def get_json(key: str) -> Any | None:
    client = get_redis_client()
    if client is None:
        return None
    try:
        raw = client.get(key)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def delete(key: str) -> None:
    client = get_redis_client()
    if client is None:
        return
    try:
        client.delete(key)
    except Exception:
        return


def db_is_ready() -> bool:
    try:
        from app.models import db

        db.session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def migrations_are_ready() -> bool:
    """
    Best-effort readiness check:
    - for SQLite/local dev: skip hard gate
    - for SQL databases: confirm alembic_version exists and has a value
    """
    try:
        from flask import current_app as app
        uri = (app.config.get("SQLALCHEMY_DATABASE_URI") or "").lower()
        if uri.startswith("sqlite"):
            return True
        from app.models import db

        row = db.session.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).first()
        return bool(row and row[0])
    except Exception:
        return False


def socketio_is_ready() -> bool:
    try:
        app = current_app._get_current_object()
        return getattr(app, "socketio", None) is not None
    except Exception:
        return False

