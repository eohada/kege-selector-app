# -*- coding: utf-8 -*-
"""
Одноразовый подписанный токен для кросс-входа Прод ↔ Песочница.
Оба окружения должны иметь один и тот же CROSS_ENV_LOGIN_SECRET.
"""
import base64
import hmac
import hashlib
import json
import time

# TTL токена в секундах (1 минута)
CROSS_ENV_TOKEN_TTL = 60


def _sign(payload_bytes: bytes, secret: str) -> str:
    return hmac.new(secret.encode('utf-8'), payload_bytes, hashlib.sha256).hexdigest()


def build_cross_env_token(user_id: int, username: str, secret: str) -> str:
    """Собрать токен: base64(payload).signature"""
    exp = int(time.time()) + CROSS_ENV_TOKEN_TTL
    payload = {'user_id': user_id, 'username': username, 'exp': exp}
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode('utf-8')).decode('ascii').rstrip('=')
    sig = _sign(payload_b64.encode('utf-8'), secret)
    return f"{payload_b64}.{sig}"


def verify_cross_env_token(token: str, secret: str):
    """
    Проверить токен. Возвращает dict с user_id, username или None при ошибке.
    """
    if not token or not secret:
        return None
    try:
        parts = token.split('.')
        if len(parts) != 2:
            return None
        payload_b64, sig = parts[0], parts[1]
        if _sign(payload_b64.encode('utf-8'), secret) != sig:
            return None
        pad = 4 - len(payload_b64) % 4
        if pad != 4:
            payload_b64 += '=' * pad
        raw = base64.urlsafe_b64decode(payload_b64)
        payload = json.loads(raw.decode('utf-8'))
        if payload.get('exp', 0) < time.time():
            return None
        return {'user_id': payload['user_id'], 'username': payload['username']}
    except Exception:
        return None
