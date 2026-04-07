"""HTTP-клиент привязки Telegram к аккаунту платформы (для webhook-бота)."""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Optional

logger = logging.getLogger(__name__)


def call_link_bot_api(
    *,
    chat_id: int,
    telegram_id: Optional[str] = None,
    code: Optional[str] = None,
    link_token: Optional[str] = None,
    app_url: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """
    POST /api/telegram/link-bot. Возвращает dict {status: int, data: dict} или None при сетевой ошибке.
    """
    base = (app_url or os.environ.get('APP_URL') or '').strip().rstrip('/')
    if not base:
        logger.warning('call_link_bot_api: APP_URL is not set')
        return None

    token = (os.environ.get('BOT_INTERNAL_TOKEN') or '').strip()
    payload: dict[str, Any] = {'chat_id': chat_id}
    if telegram_id:
        payload['telegram_id'] = telegram_id
    if link_token:
        payload['link_token'] = link_token.strip()
    elif code:
        payload['code'] = code.strip().upper()
    else:
        return None

    body = json.dumps(payload).encode('utf-8')
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['X-Bot-Token'] = token

    url = f'{base}/api/telegram/link-bot'
    req = urllib.request.Request(url, data=body, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode('utf-8')
            data = json.loads(raw) if raw else {}
            return {'status': resp.status, 'data': data}
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8', errors='replace')
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            data = {}
        return {'status': e.code, 'data': data}
    except Exception as e:
        logger.warning('call_link_bot_api failed: %s', e, exc_info=True)
        return None
