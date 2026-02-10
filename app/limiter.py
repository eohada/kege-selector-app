"""
Flask-Limiter: ограничение частоты запросов (rate limiting).
"""
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


def _key_func():
    try:
        from flask import request
        from flask_login import current_user
        if current_user.is_authenticated:
            return f"user:{current_user.id}"
        return get_remote_address()
    except Exception:
        return get_remote_address()


limiter = Limiter(
    key_func=_key_func,
    default_limits=["200 per minute"],
    storage_uri="memory://",
)
