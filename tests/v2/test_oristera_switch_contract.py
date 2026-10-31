"""Contract tests for Oristera Next UI switcher visibility (Fail-Closed)."""
from __future__ import annotations

import os
from unittest.mock import patch
import pytest

from app.utils.oristera_switch import is_oristera_next_switch_enabled


class DummyUser:
    def __init__(self, role="teacher", is_creator_flag=False):
        self.is_authenticated = True
        self.id = 1
        self.username = "test_user"
        self.role = role
        self.full_name = "Test User"
        self.avatar_url = None
        self.student_profile = None
        self._is_creator_flag = is_creator_flag

    def is_admin(self):
        return self.role in ("admin", "chief_admin")

    def is_creator(self):
        return self._is_creator_flag or self.role == "creator"

    def is_chief_admin(self):
        return self.role == "chief_admin"

    def is_chief_tester(self):
        return self.role == "chief_tester"

    def is_tester(self):
        return self.role in ("tester", "chief_tester")

    def is_teacher(self):
        return self.role in ("teacher", "tutor")

    def is_tutor(self):
        return self.role in ("teacher", "tutor")

    def is_student(self):
        return self.role == "student"

    def is_parent(self):
        return self.role == "parent"


def test_oristera_switch_strictly_disabled_in_production(app):
    """In production, switcher is strictly and forcefully disabled."""
    with patch.dict(os.environ, {"ENVIRONMENT": "production", "ORISTERA_NEXT_SWITCH_ENABLED": "true"}):
        assert is_oristera_next_switch_enabled() is False

    with patch.dict(os.environ, {"ENVIRONMENT": "production", "ORISTERA_NEXT_SWITCH_ENABLED": "1"}):
        assert is_oristera_next_switch_enabled() is False

    with patch.dict(os.environ, {"ENVIRONMENT": "prod"}):
        assert is_oristera_next_switch_enabled() is False

    with patch.dict(os.environ, {"ENVIRONMENT": "staging"}):
        assert is_oristera_next_switch_enabled() is False

    with patch.dict(os.environ, {"APP_ENV": "production"}):
        assert is_oristera_next_switch_enabled() is False

    with patch.dict(os.environ, {"FLASK_ENV": "production"}):
        assert is_oristera_next_switch_enabled() is False

    # Domain lockout: even if environment were misconfigured, production host disables it
    with app.test_request_context("/", headers={"Host": "boostudy.ru"}):
        with patch.dict(os.environ, {"ENVIRONMENT": "local"}):
            assert is_oristera_next_switch_enabled() is False



def test_oristera_switch_fail_closed_on_unknown_environment():
    """Unknown or empty environment must default to disabled."""
    with patch.dict(os.environ, {"ENVIRONMENT": "unknown_env"}):
        assert is_oristera_next_switch_enabled() is False


def test_oristera_switch_enabled_in_local_development():
    """In confirmed local development, switcher is enabled by default."""
    with patch.dict(os.environ, {"ENVIRONMENT": "local"}, clear=False):
        os.environ.pop("ORISTERA_NEXT_SWITCH_ENABLED", None)
        assert is_oristera_next_switch_enabled() is True

    with patch.dict(os.environ, {"ENVIRONMENT": "development"}, clear=False):
        os.environ.pop("ORISTERA_NEXT_SWITCH_ENABLED", None)
        assert is_oristera_next_switch_enabled() is True


def test_oristera_switch_can_be_disabled_in_local_development():
    """In local development, explicit flag can disable it."""
    with patch.dict(os.environ, {"ENVIRONMENT": "local", "ORISTERA_NEXT_SWITCH_ENABLED": "0"}):
        assert is_oristera_next_switch_enabled() is False

    with patch.dict(os.environ, {"ENVIRONMENT": "local", "ORISTERA_NEXT_SWITCH_ENABLED": "false"}):
        assert is_oristera_next_switch_enabled() is False


def test_production_templates_contain_zero_oristera_switcher(app):
    """Ensure that in production app context, rendered HTML has zero switcher buttons."""
    from flask import render_template

    with app.test_request_context("/", headers={"Host": "boostudy.ru"}):
        with patch.dict(os.environ, {"ENVIRONMENT": "production"}):
            # 1. Render layout_dashboard.html
            html_dashboard = render_template(
                "sandbox/layout_dashboard.html",
                current_user=DummyUser(),
                is_student_shell=False,
                dashboard_admin_shell=False,
            )
            assert "✨ Oristera Next" not in html_dashboard
            assert "/oristera/toggle" not in html_dashboard

            # 2. Render dev_switcher.html
            html_dev = render_template(
                "sandbox/components/dev_switcher.html",
                current_user=DummyUser(role="creator", is_creator_flag=True),
                show_dev_tools=True,
            )
            assert "dev-switcher-oristera-btn" not in html_dev
            assert "/oristera/toggle" not in html_dev


def test_local_templates_contain_working_oristera_switcher(app):
    """Ensure that in local development app context, switcher is rendered and functional."""
    from flask import render_template

    with app.test_request_context("/", headers={"Host": "127.0.0.1:5000"}):
        with patch.dict(os.environ, {"ENVIRONMENT": "local"}, clear=False):
            os.environ.pop("ORISTERA_NEXT_SWITCH_ENABLED", None)
            html_dashboard = render_template(
                "sandbox/layout_dashboard.html",
                current_user=DummyUser(),
                is_student_shell=False,
                dashboard_admin_shell=False,
            )
            assert "✨ Oristera Next" in html_dashboard
            assert "/oristera/toggle?to=oristera" in html_dashboard

            html_dev = render_template(
                "sandbox/components/dev_switcher.html",
                current_user=DummyUser(role="creator", is_creator_flag=True),
                show_dev_tools=True,
            )
            assert "dev-switcher-oristera-btn" in html_dev
            assert "/oristera/toggle?to=oristera" in html_dev

