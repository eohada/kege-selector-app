"""Telegram runtime config used inside the main app package."""
from __future__ import annotations

import json
import logging
import os
from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)


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


ALLOWLIST_CHAT_IDS = frozenset({854161398})


_CONTROL_FILE: str | None = None


def is_live_delivery_active() -> bool:
    """Check if real outbound Telegram messaging is explicitly enabled in dev mode.

    Default in development: False (dry-run / simulated mode only).
    Can be dynamically activated via instance/telegram_delivery_mode.json,
    TELEGRAM_LIVE_TEST_MODE=1, or when running under automated test suite (TESTING=True).
    """
    environment = (os.environ.get('ENVIRONMENT') or os.environ.get('FLASK_ENV') or 'local').strip().lower()
    if environment in {'production', 'prod'}:
        return True

    # 1. Check control file first (explicit toggle in dev / tests)
    try:
        from flask import current_app, has_app_context
        instance_dir = current_app.instance_path if has_app_context() else os.path.join(os.getcwd(), 'instance')
        mode_file = _CONTROL_FILE or os.path.join(instance_dir, 'telegram_delivery_mode.json')
        if os.path.exists(mode_file):
            with open(mode_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if 'live_mode' in data:
                    return bool(data['live_mode'])
    except Exception:
        pass

    # 2. Check automated test suite default
    try:
        from flask import current_app, has_app_context
        if has_app_context() and current_app.config.get('TESTING'):
            return True
    except Exception:
        pass

    return _truthy(os.environ.get('TELEGRAM_LIVE_TEST_MODE')) or _truthy(os.environ.get('TELEGRAM_DEV_SEND_LIVE_NOTIFICATIONS'))


def set_live_delivery_active(active: bool) -> None:
    """Set the dynamic live delivery mode flag in instance/telegram_delivery_mode.json."""
    try:
        from datetime import datetime, timezone
        from flask import current_app, has_app_context
        instance_dir = current_app.instance_path if has_app_context() else os.path.join(os.getcwd(), 'instance')
        mode_file = _CONTROL_FILE or os.path.join(instance_dir, 'telegram_delivery_mode.json')
        os.makedirs(os.path.dirname(mode_file), exist_ok=True)
        data = {}
        if os.path.exists(mode_file):
            try:
                with open(mode_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                pass
        data['live_mode'] = bool(active)
        data['updated_at'] = datetime.now(timezone.utc).isoformat()
        with open(mode_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning('Failed to write telegram_delivery_mode.json: %s', e)


def is_kill_switch_active() -> bool:
    """Check if emergency kill switch / pause is active without requiring process restart.
    
    Checks:
    1. os.environ: TELEGRAM_KILL_SWITCH=1 or TELEGRAM_OUTBOX_PAUSED=1.
    2. instance/telegram_kill_switch.flag file presence.
    3. instance/telegram_delivery_mode.json {"kill_switch": true} or {"paused": true}.
    """
    if _truthy(os.environ.get('TELEGRAM_KILL_SWITCH')) or _truthy(os.environ.get('TELEGRAM_OUTBOX_PAUSED')):
        return True

    try:
        from flask import current_app, has_app_context
        instance_dir = current_app.instance_path if has_app_context() else os.path.join(os.getcwd(), 'instance')
        flag_file = os.path.join(instance_dir, 'telegram_kill_switch.flag')
        if os.path.exists(flag_file):
            return True

        mode_file = _CONTROL_FILE or os.path.join(instance_dir, 'telegram_delivery_mode.json')
        if os.path.exists(mode_file):
            with open(mode_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if data.get('kill_switch') or data.get('paused'):
                    return True
    except Exception:
        pass

    return False


def set_kill_switch_active(active: bool) -> None:
    """Set dynamic emergency kill switch state via flag file and mode JSON."""
    try:
        from flask import current_app, has_app_context
        instance_dir = current_app.instance_path if has_app_context() else os.path.join(os.getcwd(), 'instance')
        os.makedirs(instance_dir, exist_ok=True)
        flag_file = os.path.join(instance_dir, 'telegram_kill_switch.flag')
        if active:
            with open(flag_file, 'w', encoding='utf-8') as f:
                f.write('1\n')
        else:
            if os.path.exists(flag_file):
                try:
                    os.remove(flag_file)
                except OSError:
                    pass

        mode_file = _CONTROL_FILE or os.path.join(instance_dir, 'telegram_delivery_mode.json')
        data = {}
        if os.path.exists(mode_file):
            try:
                with open(mode_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                pass
        data['kill_switch'] = bool(active)
        data['paused'] = bool(active)
        data['kill_switch_updated_at'] = datetime.now(timezone.utc).isoformat()
        with open(mode_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning('Failed to update kill switch state: %s', e)


def is_delivery_permitted(chat_id: int | None, user_id: int | None = None) -> bool:
    """Safety guard: in dev/local environments, real messages are sent ONLY when live mode is active AND chat is in allowlist.
    In any environment, an active kill switch acts as an immediate emergency stop.
    """
    if not chat_id:
        return False
    if is_kill_switch_active():
        logger.warning('telegram_delivery_suppressed_by_emergency_kill_switch chat_id=%s', chat_id)
        return False
    environment = (os.environ.get('ENVIRONMENT') or os.environ.get('FLASK_ENV') or 'local').strip().lower()
    if environment in {'production', 'prod'}:
        return True
    if not is_live_delivery_active():
        return False
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
