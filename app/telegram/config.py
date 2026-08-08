"""Telegram runtime config used inside the main app package."""
from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

BOT_TOKEN = os.environ.get('BOT_TOKEN') or os.environ.get('TELEGRAM_BOT_TOKEN') or ''
BOT_INTERNAL_TOKEN = os.environ.get('BOT_INTERNAL_TOKEN', '').strip()
APP_URL = (os.environ.get('APP_URL') or os.environ.get('BASE_URL') or 'http://127.0.0.1:5000/').strip()
APP_OPEN_URL = (os.environ.get('APP_OPEN_URL') or f"{APP_URL.rstrip('/')}/login").strip()
TELEGRAM_PROXY_URL = (os.environ.get('TELEGRAM_PROXY_URL') or '').strip()

def _parse_int_env(key: str, default: int) -> int:
    raw = (os.environ.get(key) or '').strip()
    if not raw or raw.startswith('#'):
        return default
    try:
        return int(raw)
    except ValueError:
        return default

BOOTSTRAP_CREATOR_CHAT_ID = _parse_int_env('BOOTSTRAP_CREATOR_CHAT_ID', 854161398)
BOOTSTRAP_CREATOR_USERNAME = (os.environ.get('BOOTSTRAP_CREATOR_USERNAME') or 'eohada').strip().lstrip('@').lower()
if BOOTSTRAP_CREATOR_USERNAME.startswith('#'):
    BOOTSTRAP_CREATOR_USERNAME = 'eohada'
BOOTSTRAP_CREATOR_DISPLAY_NAME = (os.environ.get('BOOTSTRAP_CREATOR_DISPLAY_NAME') or 'Eohada').strip()
if BOOTSTRAP_CREATOR_DISPLAY_NAME.startswith('#'):
    BOOTSTRAP_CREATOR_DISPLAY_NAME = 'Eohada'

# Режим тестирования (Mock) для QA-инженеров
TELEGRAM_MOCK_MODE = (os.environ.get('TELEGRAM_MOCK_MODE') or '').strip().lower() in ('1', 'true', 'yes', 'on')


def telegram_proxy_parts() -> dict[str, object] | None:
    raw = (TELEGRAM_PROXY_URL or '').strip()
    if not raw:
        return None

    cleaned = raw.strip().strip('[]()<>').replace(' ', '')
    parsed = urlsplit(cleaned)
    if not parsed.scheme or not parsed.hostname or not parsed.port:
        return None

    base_url = urlunsplit((parsed.scheme, f'{parsed.hostname}:{parsed.port}', '', '', ''))
    auth = None
    if parsed.username or parsed.password:
        auth = (parsed.username or '', parsed.password or '')

    return {'url': base_url, 'auth': auth}
