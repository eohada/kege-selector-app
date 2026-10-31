from __future__ import annotations

import json
import logging
import os
import threading
from time import time
from typing import Any

import redis
from flask import current_app
from sqlalchemy import text

logger = logging.getLogger("app.runtime_state")

_redis_client = None
_redis_lock = threading.Lock()
_memory_store: dict[str, Any] = {}
_memory_ttls: dict[str, float] = {}
_state_lock = threading.Lock()


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
    if os.environ.get("ENVIRONMENT") == "production" or os.path.exists("/.dockerenv"):
        return "redis://redis:6379/0"
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
    url = _resolve_redis_url()
    if not url:
        return True
    try:
        r = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        return bool(r.ping())
    except Exception:
        has_explicit_url = any(
            (os.environ.get(env) or "").strip().startswith("redis://")
            for env in ("REDIS_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND")
        )
        return not has_explicit_url


def set_json(key: str, value: Any, ttl_seconds: int | None = None) -> None:
    client = get_redis_client()
    if client is None:
        with _state_lock:
            _memory_store[key] = json.loads(json.dumps(value, ensure_ascii=False))
            if ttl_seconds:
                _memory_ttls[key] = time() + ttl_seconds
            else:
                _memory_ttls.pop(key, None)
        return
    try:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if ttl_seconds:
            client.setex(key, ttl_seconds, payload)
        else:
            client.set(key, payload)
    except Exception:
        with _state_lock:
            _memory_store[key] = json.loads(json.dumps(value, ensure_ascii=False))


def get_json(key: str) -> Any | None:
    client = get_redis_client()
    if client is None:
        with _state_lock:
            exp = _memory_ttls.get(key)
            if exp is not None and time() > exp:
                _memory_store.pop(key, None)
                _memory_ttls.pop(key, None)
                return None
            val = _memory_store.get(key)
            return json.loads(json.dumps(val)) if val is not None else None
    try:
        raw = client.get(key)
    except Exception:
        with _state_lock:
            return _memory_store.get(key)
    if not raw:
        with _state_lock:
            return _memory_store.get(key)
    try:
        return json.loads(raw)
    except Exception:
        return None


def delete(key: str) -> None:
    client = get_redis_client()
    with _state_lock:
        _memory_store.pop(key, None)
        _memory_ttls.pop(key, None)
    if client is None:
        return
    try:
        client.delete(key)
    except Exception:
        return


delete_key = delete


def hset_json(key: str, field: str, value: Any, ttl_seconds: int | None = None) -> None:
    client = get_redis_client()
    if client is None:
        return
    try:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        client.hset(key, field, payload)
        if ttl_seconds:
            client.expire(key, ttl_seconds)
    except Exception:
        return


def hget_json(key: str, field: str) -> Any | None:
    client = get_redis_client()
    if client is None:
        return None
    try:
        raw = client.hget(key, field)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def hgetall_json(key: str) -> dict[str, Any]:
    client = get_redis_client()
    if client is None:
        return {}
    try:
        raw_dict = client.hgetall(key)
    except Exception:
        return {}
    if not raw_dict:
        return {}
    result = {}
    for k, v in raw_dict.items():
        try:
            result[k] = json.loads(v)
        except Exception:
            result[k] = v
    return result


def hdel(key: str, *fields: str) -> None:
    client = get_redis_client()
    if client is None or not fields:
        return
    try:
        client.hdel(key, *fields)
    except Exception:
        return


def sadd(key: str, *members: str, ttl_seconds: int | None = None) -> None:
    client = get_redis_client()
    if client is None or not members:
        return
    try:
        client.sadd(key, *members)
        if ttl_seconds:
            client.expire(key, ttl_seconds)
    except Exception:
        return


def srem(key: str, *members: str) -> None:
    client = get_redis_client()
    if client is None or not members:
        return
    try:
        client.srem(key, *members)
    except Exception:
        return


def scard(key: str) -> int:
    client = get_redis_client()
    if client is None:
        return 0
    try:
        return int(client.scard(key) or 0)
    except Exception:
        return 0


def smembers(key: str) -> set[str]:
    client = get_redis_client()
    if client is None:
        return set()
    try:
        return set(client.smembers(key) or ())
    except Exception:
        return set()


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
    - for SQL databases: confirm the applied revision is exactly the code head
    """
    try:
        from flask import current_app as app
        uri = (app.config.get("SQLALCHEMY_DATABASE_URI") or "").lower()
        if uri.startswith("sqlite"):
            return True
        from app.models import db

        rows = db.session.execute(text("SELECT version_num FROM alembic_version")).all()
        applied_revisions = {row[0] for row in rows if row and row[0]}

        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from pathlib import Path

        project_root = Path(app.root_path).parent
        config = Config(str(project_root / 'migrations' / 'alembic.ini'))
        config.set_main_option('script_location', str(project_root / 'migrations'))
        script = ScriptDirectory.from_config(config)
        return bool(applied_revisions) and applied_revisions == set(script.get_heads())
    except Exception:
        return False


def socketio_is_ready() -> bool:
    try:
        app = current_app._get_current_object()
        return getattr(app, "socketio", None) is not None
    except Exception:
        return False


def is_single_process_mode() -> bool:
    """True if server runs as an isolated single process without distributed coordination."""
    if os.environ.get("BOOSTUDY_SINGLE_PROCESS") == "1":
        return True
    if os.environ.get("BOOSTUDY_SINGLE_PROCESS") == "0":
        return False
    if os.environ.get("ENVIRONMENT") in ("development", "local", "test") and not _resolve_redis_url():
        return True
    return False


def is_distributed_runtime_healthy() -> bool:
    """True if distributed runtime is operational (Redis reachable) or running in single-process mode."""
    if is_single_process_mode():
        return True
    return redis_ping()


def atomic_cas_json(key: str, update_fn: Any, ttl_seconds: int | None = None, max_retries: int = 5) -> Any:
    """
    Performs an atomic compare-and-set update on a JSON-serialized Redis key using WATCH/MULTI/EXEC.
    update_fn(current_val: dict | None) -> tuple[dict | None, bool]
      Returns (new_val, abort_flag). If abort_flag is True, transaction is cancelled and new_val returned.
    """
    client = get_redis_client()
    if client is None:
        with _state_lock:
            raw = _memory_store.get(key)
            current_val = json.loads(json.dumps(raw)) if raw is not None else None
            new_val, abort = update_fn(current_val)
            if abort:
                return new_val
            _memory_store[key] = json.loads(json.dumps(new_val, ensure_ascii=False))
            if ttl_seconds:
                _memory_ttls[key] = time() + ttl_seconds
            else:
                _memory_ttls.pop(key, None)
            return new_val
    for _ in range(max_retries):
        try:
            with client.pipeline() as pipe:
                pipe.watch(key)
                raw = pipe.get(key)
                current_val = json.loads(raw) if raw else None
                new_val, abort = update_fn(current_val)
                if abort:
                    pipe.unwatch()
                    return new_val
                payload = json.dumps(new_val, ensure_ascii=False, separators=(",", ":"))
                pipe.multi()
                if ttl_seconds:
                    pipe.setex(key, ttl_seconds, payload)
                else:
                    pipe.set(key, payload)
                pipe.execute()
                return new_val
        except redis.WatchError:
            continue
        except Exception as e:
            logger.warning("atomic_cas_json error on key %s: %s", key, e)
            return None
    logger.warning("atomic_cas_json exceeded max_retries for key %s", key)
    return None


CONNECTION_LEASE_TTL = 30


def set_connection_lease(sid: str, metadata: dict[str, Any], ttl_seconds: int = CONNECTION_LEASE_TTL) -> None:
    set_json(f"boostudy:conn_lease:{sid}", metadata, ttl_seconds=ttl_seconds)


def refresh_connection_lease(sid: str, ttl_seconds: int = CONNECTION_LEASE_TTL) -> bool:
    client = get_redis_client()
    if client is None or not sid:
        return False
    try:
        return bool(client.expire(f"boostudy:conn_lease:{sid}", ttl_seconds))
    except Exception:
        return False


def is_connection_lease_active(sid: str) -> bool:
    client = get_redis_client()
    if client is None or not sid:
        return False
    try:
        return bool(client.exists(f"boostudy:conn_lease:{sid}"))
    except Exception:
        return False


def delete_connection_lease(sid: str) -> None:
    delete(f"boostudy:conn_lease:{sid}")


def set_dirty_code(lesson_id: int, revision: int, author_id: int | None = None) -> None:
    set_json(f"boostudy:lesson:{lesson_id}:dirty_code", {
        "revision": revision,
        "author_id": author_id,
        "updated_at": int(time() * 1000),
    }, ttl_seconds=86400)


def get_dirty_code(lesson_id: int) -> dict[str, Any] | None:
    return get_json(f"boostudy:lesson:{lesson_id}:dirty_code")


def clear_dirty_code(lesson_id: int, expected_revision: int | None = None) -> bool:
    """
    Conditionally clear the dirty_code marker.
    If expected_revision is provided, the key is only cleared if the currently stored
    dirty revision is <= expected_revision. This eliminates the race condition where
    a newer revision R+1 is written while revision R is being committed to PostgreSQL.
    """
    key = f"boostudy:lesson:{lesson_id}:dirty_code"
    client = get_redis_client()
    if client is not None:
        try:
            if expected_revision is None:
                client.delete(key)
                return True
            lua_script = """
            local curr = redis.call('GET', KEYS[1])
            if not curr then return 1 end
            local ok, data = pcall(cjson.decode, curr)
            if ok and data and data.revision and tonumber(data.revision) > tonumber(ARGV[1]) then
                return 0
            end
            redis.call('DEL', KEYS[1])
            return 1
            """
            res = client.eval(lua_script, 1, key, expected_revision)
            return bool(res)
        except Exception as e:
            logger.warning("Error conditionally clearing dirty_code for lesson %s: %s", lesson_id, e)
            try:
                # Fallback for environments where EVAL/Lua is unavailable (e.g. fakeredis without lupa)
                cur_raw = client.get(key)
                if not cur_raw:
                    return True
                cur_data = json.loads(cur_raw)
                if cur_data and cur_data.get("revision") and int(cur_data.get("revision")) > int(expected_revision):
                    return False
                client.delete(key)
                return True
            except Exception:
                pass
    with _state_lock:
        curr = _memory_store.get(key)
        if curr is None:
            return True
        if expected_revision is not None and isinstance(curr, dict):
            curr_rev = curr.get("revision")
            if curr_rev is not None and int(curr_rev) > int(expected_revision):
                return False
        _memory_store.pop(key, None)
        _memory_ttls.pop(key, None)
        return True


def reset_runtime_state() -> None:
    """Clear in-memory fallback stores and connection tracking (for test isolation)."""
    with _state_lock:
        _memory_store.clear()
        _memory_ttls.clear()
    client = get_redis_client()
    if client is not None:
        try:
            keys = list(client.keys("boostudy:lesson:*")) + list(client.keys("boostudy:lesson_code:*")) + list(client.keys("boostudy:conn_lease:*"))
            if keys:
                client.delete(*keys)
        except Exception:
            pass

