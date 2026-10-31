import hashlib
import sqlite3

import pytest
from sqlalchemy import create_engine

from app.ai_lab.database_safety import (
    assert_sqlite_connection_identity,
    register_sqlite_identity_guard,
    validate_ai_lab_sqlite_config,
)


def _create_sqlite(path):
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO marker VALUES ('synthetic')")


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_environment(path):
    stat = path.stat()
    return {
        "AI_LAB_SAFE_DB_FILE_ID": f"{stat.st_dev}:{stat.st_ino}",
        "DATABASE_EXTERNAL_URL": "",
        "POSTGRES_URL": "",
        "DEMO_DATABASE_URL": "",
    }


def test_safe_ai_lab_configuration_rejects_ambiguous_database_without_writes(tmp_path):
    allowed = tmp_path / "allowed.sqlite"
    _create_sqlite(allowed)
    allowed_before = _digest(allowed)
    missing_wrong_target = tmp_path / "must-not-be-created.sqlite"
    environment = _safe_environment(allowed)

    with pytest.raises(RuntimeError, match="отсутствует или недоступен"):
        validate_ai_lab_sqlite_config(
            expected_path=str(allowed),
            sqlite_db_path=str(allowed),
            database_url=f"sqlite:///{allowed.as_posix()}",
            configured_database_url=f"sqlite:///{missing_wrong_target.as_posix()}",
            skip_database_bootstrap=True,
            runtime_environment="local",
            environment=environment,
        )

    assert _digest(allowed) == allowed_before
    assert not missing_wrong_target.exists()


def test_safe_ai_lab_configuration_rejects_override_and_bootstrap(tmp_path):
    allowed = tmp_path / "allowed.sqlite"
    _create_sqlite(allowed)
    before = _digest(allowed)
    environment = _safe_environment(allowed)
    environment["POSTGRES_URL"] = "postgresql://configured-elsewhere"

    with pytest.raises(RuntimeError, match="переопределители"):
        validate_ai_lab_sqlite_config(
            expected_path=str(allowed),
            sqlite_db_path=str(allowed),
            database_url=f"sqlite:///{allowed.as_posix()}",
            configured_database_url=f"sqlite:///{allowed.as_posix()}",
            skip_database_bootstrap=False,
            runtime_environment="local",
            environment=environment,
        )

    assert _digest(allowed) == before


def test_sqlite_connection_guard_checks_canonical_path_and_file_identity(tmp_path):
    allowed = tmp_path / "allowed.sqlite"
    unexpected = tmp_path / "unexpected.sqlite"
    _create_sqlite(allowed)
    _create_sqlite(unexpected)
    allowed_identity = (allowed.stat().st_dev, allowed.stat().st_ino)
    allowed_engine = create_engine(f"sqlite:///{allowed.as_posix()}")
    unexpected_engine = create_engine(f"sqlite:///{unexpected.as_posix()}")
    register_sqlite_identity_guard(allowed_engine, allowed.resolve(), allowed_identity)
    register_sqlite_identity_guard(unexpected_engine, allowed.resolve(), allowed_identity)

    with allowed_engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT value FROM marker").scalar_one() == "synthetic"

    with pytest.raises(RuntimeError, match="Идентичность открытой SQLite"):
        unexpected_engine.connect()

    allowed_engine.dispose()
    unexpected_engine.dispose()


def test_sqlite_connection_guard_rejects_replaced_file_identity(tmp_path):
    allowed = tmp_path / "allowed.sqlite"
    replacement = tmp_path / "replacement.sqlite"
    _create_sqlite(allowed)
    _create_sqlite(replacement)
    expected_identity = (allowed.stat().st_dev, allowed.stat().st_ino)

    with sqlite3.connect(replacement) as connection:
        with pytest.raises(RuntimeError, match="Идентичность открытой SQLite"):
            assert_sqlite_connection_identity(connection, allowed.resolve(), expected_identity)


def test_create_app_rejects_safe_mode_uri_override_before_opening_wrong_database(tmp_path, monkeypatch):
    from app import create_app

    allowed = tmp_path / "allowed.sqlite"
    wrong = tmp_path / "wrong.sqlite"
    _create_sqlite(allowed)
    _create_sqlite(wrong)
    allowed_before = _digest(allowed)
    wrong_before = _digest(wrong)
    stat = allowed.stat()
    monkeypatch.setenv("AI_LAB_SAFE_DB_MODE", "1")
    monkeypatch.setenv("AI_LAB_SAFE_DB_PATH", str(allowed))
    monkeypatch.setenv("AI_LAB_SAFE_DB_FILE_ID", f"{stat.st_dev}:{stat.st_ino}")
    monkeypatch.setenv("SQLITE_DB_PATH", str(allowed))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{allowed.as_posix()}")
    monkeypatch.setenv("BOOSTUDY_SKIP_DATABASE_BOOTSTRAP", "1")
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("SECRET_KEY", "test-only-safe-ai-lab")
    for key in ("DATABASE_EXTERNAL_URL", "POSTGRES_URL", "DEMO_DATABASE_URL"):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(RuntimeError, match="SQLAlchemy"):
        create_app({"SQLALCHEMY_DATABASE_URI": f"sqlite:///{wrong.as_posix()}"})

    assert _digest(allowed) == allowed_before
    assert _digest(wrong) == wrong_before


def test_create_app_safe_mode_connects_only_to_explicit_synthetic_file(tmp_path, monkeypatch):
    from app import create_app, db

    allowed = tmp_path / "allowed.sqlite"
    _create_sqlite(allowed)
    stat = allowed.stat()
    monkeypatch.setenv("AI_LAB_SAFE_DB_MODE", "1")
    monkeypatch.setenv("AI_LAB_SAFE_DB_PATH", str(allowed))
    monkeypatch.setenv("AI_LAB_SAFE_DB_FILE_ID", f"{stat.st_dev}:{stat.st_ino}")
    monkeypatch.setenv("SQLITE_DB_PATH", str(allowed))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{allowed.as_posix()}")
    monkeypatch.setenv("BOOSTUDY_SKIP_DATABASE_BOOTSTRAP", "1")
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("SECRET_KEY", "test-only-safe-ai-lab")
    for key in ("DATABASE_EXTERNAL_URL", "POSTGRES_URL", "DEMO_DATABASE_URL"):
        monkeypatch.delenv(key, raising=False)

    app = create_app()
    with app.app_context():
        assert db.session.execute(db.text("SELECT value FROM marker")).scalar_one() == "synthetic"

