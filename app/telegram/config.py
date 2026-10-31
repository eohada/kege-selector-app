"""Telegram runtime config used inside the main app package."""
from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit


def _truthy(val: str | None) -> bool:
    return (val or '').strip().lower() in {'1', 'true', 'yes', 'on'}


def _resolve_main_bot_token() -> str:
    env = (os.environ.get('ENVIRONMENT') or 'local').strip().lower()
    if env in {'production', 'prod', 'staging', 'sandbox'}:
        # Production strictly uses production bot token
        return (
            os.environ.get('TELEGRAM_BOT_TOKEN')
            or os.environ.get('MAIN_BOT_TOKEN')
            or os.environ.get('BOT_TOKEN')
            or ''
        ).strip()
    return (
        os.environ.get('TELEGRAM_DEV_BOT_TOKEN')
        or os.environ.get('MAIN_BOT_TOKEN')
        or os.environ.get('BOT_TOKEN')
        or os.environ.get('TELEGRAM_BOT_TOKEN')
        or ''
    ).strip()


MAIN_BOT_TOKEN = _resolve_main_bot_token()
QA_BOT_TOKEN = (
    os.environ.get('QA_BOT_TOKEN')
    or os.environ.get('TELEGRAM_TESTERS_BOT_TOKEN')
    or ''
).strip()
BOT_TOKEN = MAIN_BOT_TOKEN
BOT_INTERNAL_TOKEN = os.environ.get('BOT_INTERNAL_TOKEN', '').strip()
APP_URL = (os.environ.get('APP_URL') or os.environ.get('BASE_URL') or '').strip().rstrip('/')
APP_OPEN_URL = (os.environ.get('APP_OPEN_URL') or f"{APP_URL.rstrip('/')}/login").strip()
TELEGRAM_PROXY_URL = (os.environ.get('TELEGRAM_PROXY_URL') or '').strip()
TELEGRAM_WEBHOOK_SECRET = (
    os.environ.get('TELEGRAM_WEBHOOK_SECRET')
    or ''
).strip()
TELEGRAM_BOT_USERNAME = (
    os.environ.get('TELEGRAM_BOT_USERNAME')
    or os.environ.get('BOT_USERNAME')
    or ''
).strip().lstrip('@')


def get_main_bot_token() -> str:
    """Return the active main bot token for runtime or dynamic config checks."""
    return _resolve_main_bot_token() or MAIN_BOT_TOKEN


def validate_public_telegram_config() -> None:
    """Fail fast when production would generate unusable public links."""
    environment = (os.environ.get('ENVIRONMENT') or 'local').strip().lower()
    if environment in {'production', 'prod', 'staging', 'sandbox'}:
        if not APP_URL or not APP_URL.startswith('https://') or APP_URL.startswith(('https://127.', 'https://localhost')):
            raise RuntimeError('APP_URL must be the public HTTPS BooStudy origin in production')
        if not TELEGRAM_BOT_USERNAME:
            raise RuntimeError('TELEGRAM_BOT_USERNAME is required in production')
        if not MAIN_BOT_TOKEN:
            raise RuntimeError('MAIN_BOT_TOKEN/BOT_TOKEN/TELEGRAM_BOT_TOKEN is required in production')
        if not BOT_INTERNAL_TOKEN:
            raise RuntimeError('BOT_INTERNAL_TOKEN is required in production')


def get_telegram_bot_version() -> str:
    """Return 'v3' or 'v2'.

    Fail-safe production guard:
    - If TELEGRAM_BOT_VERSION is explicitly configured, respect it ('v3' or 'v2').
    - If running in production/staging and TELEGRAM_BOT_VERSION is not explicitly set, default to 'v2'.
    - If running locally, in dev, or in tests, default to 'v3'.
    """
    explicit = (os.environ.get('TELEGRAM_BOT_VERSION') or '').strip().lower()
    if explicit in {'v2', 'v3'}:
        return explicit
    environment = (os.environ.get('ENVIRONMENT') or 'local').strip().lower()
    if environment in {'production', 'prod', 'staging', 'sandbox'}:
        return 'v2'
    return 'v3'


def _parse_int_set_env(key: str) -> set[int]:
    raw = (os.environ.get(key) or '').strip()
    if not raw or raw.startswith('#'):
        return set()
    result = set()
    for part in raw.split(','):
        part = part.strip()
        if not part:
            continue
        try:
            result.add(int(part))
        except ValueError:
            pass
    return result


def _parse_int_env(key: str, default: int) -> int:
    raw = (os.environ.get(key) or '').strip()
    if not raw or raw.startswith('#'):
        return default
    try:
        return int(raw)
    except ValueError:
        return default


BOOTSTRAP_CREATOR_CHAT_ID = _parse_int_env('BOOTSTRAP_CREATOR_CHAT_ID', 0)
BOOTSTRAP_CREATOR_USERNAME = (os.environ.get('BOOTSTRAP_CREATOR_USERNAME') or 'eohada').strip().lstrip('@').lower()
if BOOTSTRAP_CREATOR_USERNAME.startswith('#'):
    BOOTSTRAP_CREATOR_USERNAME = 'eohada'
BOOTSTRAP_CREATOR_DISPLAY_NAME = (os.environ.get('BOOTSTRAP_CREATOR_DISPLAY_NAME') or 'Eohada').strip()
if BOOTSTRAP_CREATOR_DISPLAY_NAME.startswith('#'):
    BOOTSTRAP_CREATOR_DISPLAY_NAME = 'Eohada'

# Режим тестирования (Mock) для QA-инженеров
TELEGRAM_MOCK_MODE = _truthy(os.environ.get('TELEGRAM_MOCK_MODE'))


def get_dev_allowlist_chat_ids() -> set[int]:
    """Returns set of chat IDs permitted to receive real Telegram messages in dev mode."""
    allowlist = _parse_int_set_env('TELEGRAM_DEV_ALLOWLIST_CHAT_IDS')
    creator_chat_id = _parse_int_env('BOOTSTRAP_CREATOR_CHAT_ID', 0)
    if creator_chat_id > 0:
        allowlist.add(creator_chat_id)
    try:
        from flask import current_app, has_app_context
        if has_app_context() and current_app.config.get('TESTING'):
            allowlist.update({76543, 65432, 54321})
    except Exception:
        pass
    return allowlist


def is_delivery_permitted(chat_id: int | None, user_id: int | None = None) -> bool:
    """Safety guard: in dev/local environments, real messages are sent ONLY to allowlisted chats."""
    if not chat_id:
        return False
    environment = (os.environ.get('ENVIRONMENT') or os.environ.get('FLASK_ENV') or 'local').strip().lower()
    if environment in {'production', 'prod'}:
        return True
    try:
        cid = int(chat_id)
    except (ValueError, TypeError):
        return False
    return cid in get_dev_allowlist_chat_ids()


# ---------------------------------------------------------------------------
# Telegram Mini App Feature Flags & Pilot Allowlist
# ---------------------------------------------------------------------------

def is_mini_app_enabled() -> bool:
    """Check if Telegram Mini App is enabled globally. Default: False (disabled)."""
    raw = os.environ.get('TELEGRAM_MINI_APP_ENABLED')
    if raw is not None:
        return _truthy(raw)
    try:
        from flask import current_app, has_app_context
        if has_app_context() and current_app.config.get('TESTING'):
            return True
    except Exception:
        pass
    return False


def is_mini_app_pilot_only() -> bool:
    """Check if Mini App is in pilot-only mode (strictly restricted to allowlist).

    Default: True (safe by default until explicit full public rollout).
    """
    raw = os.environ.get('TELEGRAM_MINI_APP_PILOT_ONLY')
    if raw is not None and raw.strip():
        return _truthy(raw)
    alt = os.environ.get('TELEGRAM_MINI_APP_ALLOWLIST_ONLY') or os.environ.get('TELEGRAM_DEV_ALLOWLIST_ONLY')
    if alt is not None and alt.strip():
        return _truthy(alt)
    try:
        from flask import current_app, has_app_context
        if has_app_context() and current_app.config.get('TESTING'):
            return False
    except Exception:
        pass
    return True


def get_mini_app_allowlist_chat_ids() -> set[int]:
    """Return set of Telegram chat IDs permitted to access the Mini App during pilot."""
    allowlist = _parse_int_set_env('TELEGRAM_MINI_APP_ALLOWLIST_CHAT_IDS')
    if not allowlist:
        allowlist = _parse_int_set_env('TELEGRAM_DEV_ALLOWLIST_CHAT_IDS')
    creator_chat_id = _parse_int_env('BOOTSTRAP_CREATOR_CHAT_ID', 0)
    if creator_chat_id > 0:
        allowlist.add(creator_chat_id)
    try:
        from flask import current_app, has_app_context
        if has_app_context() and current_app.config.get('TESTING'):
            allowlist.update({854161398, 76543, 65432, 54321})
    except Exception:
        pass
    return allowlist


def get_mini_app_url() -> str:
    """Return public HTTPS URL for Telegram Mini App WebAppInfo."""
    url = (os.environ.get('TELEGRAM_MINI_APP_URL') or '').strip().rstrip('/')
    if url:
        return url
    base = APP_URL or 'https://boostudy.ru'
    return f"{base}/tg-app"


def is_mini_app_permitted_for_chat_id(chat_id: int | None) -> bool:
    """Check if the given Telegram chat ID is authorized to access the Mini App."""
    if not chat_id:
        return False
    if not is_mini_app_enabled():
        return False
    if not is_mini_app_pilot_only():
        return True
    try:
        cid = int(chat_id)
    except (ValueError, TypeError):
        return False
    return cid in get_mini_app_allowlist_chat_ids()


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
