"""Telegram runtime config used inside the main app package."""
from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

BOT_TOKEN = os.environ.get('BOT_TOKEN') or os.environ.get('TELEGRAM_BOT_TOKEN') or ''
BOT_INTERNAL_TOKEN = os.environ.get('BOT_INTERNAL_TOKEN', '').strip()
APP_URL = (os.environ.get('APP_URL') or 'https://boostudy.ru/').strip()
APP_OPEN_URL = (os.environ.get('APP_OPEN_URL') or 'https://boostudy.ru/login').strip()
TELEGRAM_PROXY_URL = (os.environ.get('TELEGRAM_PROXY_URL') or os.environ.get('HTTP_PROXY') or os.environ.get('HTTPS_PROXY') or '').strip()
BOOTSTRAP_CREATOR_CHAT_ID = int((os.environ.get('BOOTSTRAP_CREATOR_CHAT_ID') or '854161398').strip() or '854161398')
BOOTSTRAP_CREATOR_USERNAME = (os.environ.get('BOOTSTRAP_CREATOR_USERNAME') or 'eohada').strip().lstrip('@').lower()
BOOTSTRAP_CREATOR_DISPLAY_NAME = (os.environ.get('BOOTSTRAP_CREATOR_DISPLAY_NAME') or 'Eohada').strip()


def telegram_proxy_parts() -> dict[str, object] | None:
    raw = TELEGRAM_PROXY_URL.strip()
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
