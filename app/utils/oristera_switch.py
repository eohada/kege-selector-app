"""Oristera Next UI Switcher Visibility Guard (Fail-Closed).

Controls the visibility of the 'Oristera Next' entry button in BooStudy OS.
Strict Security & Environment Rules:
- Fail-closed: default is False.
- Production: strictly False under all circumstances (even if flag is set to true).
- Unknown / Ambiguous environment: strictly False.
- Local development (ENVIRONMENT in ('local', 'dev', 'development')): True only if
  confirmed local development and not explicitly disabled.
"""
from __future__ import annotations

import os


def is_oristera_next_switch_enabled(app=None) -> bool:
    """Return True only if the Oristera Next switcher is permitted to display.

    Fail-closed policy:
    1. If request host domain is boostudy.ru -> strictly False.
    2. If environment (ENVIRONMENT, APP_ENV, FLASK_ENV) is production, prod, staging, sandbox -> strictly False.
    3. If running inside a container without explicit local designation -> strictly False.
    4. If environment is undefined or unknown (not local/dev) -> strictly False.
    5. If explicit ORISTERA_NEXT_SWITCH_ENABLED is false/0/off -> False.
    6. If environment is confirmed local/dev AND not explicitly disabled -> True.
    """
    # 0. Request context domain check — never show on production domain
    try:
        from flask import has_request_context, request
        if has_request_context():
            host = (request.host or "").lower().split(":")[0].strip()
            if host == "boostudy.ru" or host.endswith(".boostudy.ru"):
                return False
    except Exception:
        pass

    # 1. Resolve environment candidates from process env and Flask app config
    env_candidates = [
        (os.environ.get("ENVIRONMENT") or "").strip().lower(),
        (os.environ.get("APP_ENV") or "").strip().lower(),
        (os.environ.get("FLASK_ENV") or "").strip().lower(),
    ]
    if app:
        try:
            env_candidates.extend([
                (app.config.get("ENVIRONMENT") or "").strip().lower(),
                (app.config.get("APP_ENV") or "").strip().lower(),
                (app.config.get("FLASK_ENV") or "").strip().lower(),
            ])
        except Exception:
            pass

    # 2. Hard production lockout — if ANY indicator specifies production/staging, NEVER display
    if os.environ.get("BOOSTUDY_PRODUCTION") == "1" or (app and bool(app.config.get("BOOSTUDY_PRODUCTION"))):
        return False

    for env_val in env_candidates:
        if env_val in ("production", "prod", "staging", "sandbox"):
            return False

    # 3. Running in Docker container without explicit local tag -> fail-closed
    primary_env = next((e for e in env_candidates if e), "")
    if os.path.exists("/.dockerenv") and primary_env not in ("local", "dev", "development"):
        return False

    # 4. Fail-closed on any non-local or unknown environment
    if primary_env not in ("local", "dev", "development"):
        return False


    # 5. Check explicit feature flag if set
    flag = os.environ.get("ORISTERA_NEXT_SWITCH_ENABLED")
    if flag is not None:
        return flag.strip().lower() in ("1", "true", "yes", "on")

    if app:
        try:
            app_flag = app.config.get("ORISTERA_NEXT_SWITCH_ENABLED")
            if app_flag is not None:
                return bool(app_flag)
        except Exception:
            pass

    # In confirmed local development, enabled by default for developer convenience
    return True

