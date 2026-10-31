from __future__ import annotations

import os
from flask import current_app, request, session


def is_oristera_enabled() -> bool:
    """Проверка, включена ли новая оболочка Oristera Next."""
    # По умолчанию включено в локальной разработке и preview
    env_flag = os.environ.get("ORISTERA_ENABLED")
    if env_flag is not None:
        return env_flag.strip().lower() in ("1", "true", "yes", "on")
    
    app_flag = current_app.config.get("ORISTERA_ENABLED")
    if app_flag is not None:
        return bool(app_flag)

    # В production выключено по умолчанию
    env_name = (os.environ.get("ENVIRONMENT") or "local").strip().lower()
    return env_name in ("local", "dev", "development", "preview", "staging", "test")


def get_ui_mode() -> str:
    """
    Возвращает активный режим: 'classic' или 'oristera'.
    По умолчанию для всех пользователей — 'classic', пока не выбран режим явно.
    """
    # Явный параметр в URL (например, ?mode=oristera)
    url_mode = request.args.get("ui_mode") or request.args.get("mode")
    if url_mode in ("classic", "oristera"):
        session["ui_mode"] = url_mode
        return url_mode

    # Значение в сессии
    sess_mode = session.get("ui_mode")
    if sess_mode in ("classic", "oristera"):
        return sess_mode

    # Значение в cookie
    cookie_mode = request.cookies.get("boostudy_ui_mode")
    if cookie_mode in ("classic", "oristera"):
        session["ui_mode"] = cookie_mode
        return cookie_mode

    return "classic"


def set_ui_mode(mode: str) -> None:
    """Установить активный режим интерфейса."""
    if mode in ("classic", "oristera"):
        session["ui_mode"] = mode
