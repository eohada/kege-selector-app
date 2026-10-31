from flask import Flask

from app.main.routes import _synthetic_role_switch_enabled, _synthetic_student_user_ids


def _app():
    app = Flask(__name__)
    app.config.update(DEBUG=False, TESTING=False)
    return app


def test_local_environment_alone_does_not_enable_role_switch(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setattr("app.ai_lab.database_safety.has_verified_safe_ai_lab_db", lambda: False)
    monkeypatch.setattr("app.ai_lab.provider.is_local_ai_lab_enabled", lambda: True)

    with _app().app_context():
        assert not _synthetic_role_switch_enabled()


def test_role_switch_requires_verified_database_and_local_ai_lab(monkeypatch):
    monkeypatch.setattr("app.ai_lab.database_safety.has_verified_safe_ai_lab_db", lambda: True)
    monkeypatch.setattr("app.ai_lab.provider.is_local_ai_lab_enabled", lambda: False)

    with _app().app_context():
        assert not _synthetic_role_switch_enabled()

    monkeypatch.setattr("app.ai_lab.provider.is_local_ai_lab_enabled", lambda: True)
    with _app().app_context():
        assert _synthetic_role_switch_enabled()


def test_synthetic_switcher_allowlist_ignores_malformed_and_nonpositive_ids(monkeypatch):
    monkeypatch.delenv("AI_LAB_PLATFORM_TEST_USER_IDS", raising=False)
    app = _app()
    app.config["AI_LAB_PLATFORM_TEST_USER_IDS"] = "9313001, bad, 0, -4, 9311001"

    with app.app_context():
        assert _synthetic_student_user_ids() == {9311001, 9313001}
