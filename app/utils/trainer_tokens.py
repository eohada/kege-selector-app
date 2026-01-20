from __future__ import annotations

import base64
import hmac
import hashlib
import json
import os
import time
from typing import Any


class TrainerTokenError(Exception):
    pass


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode('utf-8').rstrip('=')


def _b64url_decode(s: str) -> bytes:
    pad = '=' * (-len(s) % 4)
    return base64.urlsafe_b64decode((s + pad).encode('utf-8'))


def _get_secret() -> bytes:
    secret = (os.environ.get('TRAINER_SHARED_SECRET') or '').strip()
    if not secret or len(secret) < 16:
        raise TrainerTokenError('TRAINER_SHARED_SECRET is missing or too short')
    return secret.encode('utf-8')


def issue_trainer_token(*, user_id: int, ttl_seconds: int = 10 * 60, audience: str = 'trainer') -> str:
    """
    Compact HMAC-signed token (JWT-like, but minimal):
    header.payload.signature
    """
    now = int(time.time())
    header: dict[str, Any] = {'alg': 'HS256', 'typ': 'TRAINER', 'v': 1}
    payload: dict[str, Any] = {
        'sub': int(user_id),
        'iat': now,
        'exp': now + int(ttl_seconds),
        'aud': str(audience),
    }
    header_b64 = _b64url_encode(json.dumps(header, separators=(',', ':')).encode('utf-8'))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(',', ':')).encode('utf-8'))
    signing_input = f'{header_b64}.{payload_b64}'.encode('utf-8')
    sig = hmac.new(_get_secret(), signing_input, hashlib.sha256).digest()
    sig_b64 = _b64url_encode(sig)
    return f'{header_b64}.{payload_b64}.{sig_b64}'


def verify_trainer_token(token: str, *, audience: str = 'trainer') -> dict[str, Any]:
    try:
        parts = (token or '').split('.')
        if len(parts) != 3:
            raise TrainerTokenError('bad token format')
        header_b64, payload_b64, sig_b64 = parts

        signing_input = f'{header_b64}.{payload_b64}'.encode('utf-8')
        expected = hmac.new(_get_secret(), signing_input, hashlib.sha256).digest()
        try:
            provided = _b64url_decode(sig_b64)
        except Exception:
            raise TrainerTokenError('bad signature encoding')
        if not hmac.compare_digest(provided, expected):
            raise TrainerTokenError('bad signature')

        try:
            payload = json.loads(_b64url_decode(payload_b64).decode('utf-8'))
        except Exception:
            raise TrainerTokenError('bad payload')

        now = int(time.time())
        exp = int(payload.get('exp') or 0)
        if exp and now > exp:
            raise TrainerTokenError('token expired')
        if audience and (payload.get('aud') != audience):
            raise TrainerTokenError('bad audience')
        return payload
    except TrainerTokenError:
        raise
    except Exception as e:
        raise TrainerTokenError(str(e))

