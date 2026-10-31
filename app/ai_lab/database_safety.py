"""Fail-closed database checks for explicitly isolated AI Lab runs."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import make_url


_DATABASE_OVERRIDES = ("DATABASE_EXTERNAL_URL", "POSTGRES_URL", "DEMO_DATABASE_URL")


def has_verified_safe_ai_lab_db() -> bool:
    """Return true only when the app factory completed the isolated SQLite checks."""
    from flask import current_app, has_app_context

    if not has_app_context():
        return False
    path = current_app.config.get("AI_LAB_SAFE_DB_PATH")
    identity = current_app.config.get("AI_LAB_SAFE_DB_IDENTITY")
    return bool(
        path
        and isinstance(identity, tuple)
        and len(identity) == 2
        and isinstance(identity[0], int)
        and identity[0] >= 0
        and isinstance(identity[1], int)
        and identity[1] > 0
    )


def _identity(path: Path) -> tuple[int, int]:
    stat = path.stat()
    if not stat.st_ino:
        raise RuntimeError("Файловая система не предоставляет идентификатор SQLite-файла.")
    return stat.st_dev, stat.st_ino


def _database_path(database_url: str) -> Path:
    url = make_url(database_url)
    if url.drivername != "sqlite" or not url.database:
        raise RuntimeError("Изолированный AI Lab разрешает только явную файловую SQLite.")
    try:
        return Path(url.database).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise RuntimeError("Файл разрешённой synthetic SQLite отсутствует или недоступен.") from error


def validate_ai_lab_sqlite_config(
    *,
    expected_path: str,
    sqlite_db_path: str | None,
    database_url: str | None,
    configured_database_url: str | None,
    skip_database_bootstrap: bool,
    runtime_environment: str,
    environment: dict[str, str] | None = None,
) -> tuple[Path, tuple[int, int]]:
    """Validate all DB selectors before SQLAlchemy initializes an engine."""
    env = os.environ if environment is None else environment
    try:
        allowed_path = Path(expected_path).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise RuntimeError("Разрешённая synthetic SQLite отсутствует или недоступна.") from error
    if not allowed_path.is_file():
        raise RuntimeError("Разрешённый путь AI Lab не является файлом SQLite.")

    if not sqlite_db_path:
        raise RuntimeError("SQLITE_DB_PATH обязателен в безопасном режиме AI Lab.")
    try:
        selected_path = Path(sqlite_db_path).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise RuntimeError("SQLITE_DB_PATH отсутствует или недоступен.") from error
    if selected_path != allowed_path:
        raise RuntimeError("SQLITE_DB_PATH не совпадает с разрешённой synthetic SQLite.")

    if not database_url or _database_path(database_url) != allowed_path:
        raise RuntimeError("DATABASE_URL не совпадает с разрешённой synthetic SQLite.")
    if not configured_database_url or _database_path(configured_database_url) != allowed_path:
        raise RuntimeError("Активная конфигурация SQLAlchemy не совпадает с разрешённой synthetic SQLite.")

    active_overrides = [name for name in _DATABASE_OVERRIDES if (env.get(name) or "").strip()]
    if active_overrides:
        raise RuntimeError(
            "Безопасный режим AI Lab запрещает неоднозначные DB-переопределители: "
            + ", ".join(active_overrides)
        )
    if runtime_environment.strip().lower() not in {"local", "development", "dev"}:
        raise RuntimeError("Безопасный режим synthetic AI Lab разрешён только в локальной среде.")
    if not skip_database_bootstrap:
        raise RuntimeError("Безопасный режим AI Lab требует отключённой автоматической инициализации БД.")

    identity = _identity(allowed_path)
    declared_identity = env.get("AI_LAB_SAFE_DB_FILE_ID")
    if not declared_identity or declared_identity != f"{identity[0]}:{identity[1]}":
        raise RuntimeError("Идентификатор файла SQLite отсутствует или изменился после проверки.")
    return allowed_path, identity


def assert_sqlite_connection_identity(connection, expected_path: Path, expected_identity: tuple[int, int]) -> None:
    rows = connection.execute("PRAGMA database_list").fetchall()
    main_path = next((row[2] for row in rows if row[1] == "main"), "")
    if not main_path:
        raise RuntimeError("SQLite не открыла ожидаемый основной файл базы данных.")
    try:
        actual_path = Path(main_path).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise RuntimeError("Открытый SQLite-файл отсутствует или недоступен.") from error
    if actual_path != expected_path or _identity(actual_path) != expected_identity:
        raise RuntimeError("Идентичность открытой SQLite не совпадает с разрешённой базой AI Lab.")


def register_sqlite_identity_guard(engine, expected_path: Path, expected_identity: tuple[int, int]) -> None:
    """Reject an unexpected SQLite connection before application queries run."""

    def verify_connection(dbapi_connection, _connection_record):
        try:
            assert_sqlite_connection_identity(dbapi_connection, expected_path, expected_identity)
        except Exception:
            dbapi_connection.close()
            raise

    event.listen(engine, "connect", verify_connection, insert=True)
