"""Fail-closed guard for tests that could initialize or write application data."""
from __future__ import annotations

import os

import pytest
from sqlalchemy.engine import make_url


def pytest_sessionstart(session: pytest.Session) -> None:
    """Refuse test collection unless the process is explicitly isolated."""
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise pytest.UsageError(
            "Tests require an explicit DATABASE_URL=sqlite:///:memory:; "
            "no application database has been selected."
        )

    try:
        url = make_url(database_url)
    except Exception as exc:
        raise pytest.UsageError("DATABASE_URL is invalid; tests were stopped before collection.") from exc

    allow_isolated_pg = (
        os.environ.get("BOOSTUDY_ALLOW_TEST_POSTGRES", "").strip().lower() in {"1", "true", "yes"}
        and url.get_backend_name() in ("postgresql", "postgres")
        and (url.database or "").endswith("_test")
        and (url.host in (None, "", "localhost", "127.0.0.1") or (url.query.get("host") or "").startswith("/tmp"))
    )
    if not allow_isolated_pg and (url.get_backend_name() != "sqlite" or url.database not in (None, "", ":memory:")):
        raise pytest.UsageError(
            "Tests only allow an in-memory SQLite DATABASE_URL or an isolated local test PostgreSQL database (with BOOSTUDY_ALLOW_TEST_POSTGRES=1); persistent, dev, and production databases are blocked."
        )

    skip_bootstrap = os.environ.get("BOOSTUDY_SKIP_DATABASE_BOOTSTRAP", "").strip().lower()
    if skip_bootstrap not in {"1", "true", "yes", "on"}:
        raise pytest.UsageError(
            "Set BOOSTUDY_SKIP_DATABASE_BOOTSTRAP=1 so test startup cannot run application bootstrap or migrations."
        )

    workers_enabled = os.environ.get("BOOSTUDY_BACKGROUND_WORKERS_ENABLED", "").strip().lower()
    if workers_enabled not in {"0", "false", "no", "off"}:
        raise pytest.UsageError(
            "Set BOOSTUDY_BACKGROUND_WORKERS_ENABLED=0 so tests cannot start background workers."
        )
