"""Contract and security tests for BooStudy Pocket OS (Fail-Closed).

Sprint 1: Mobile Lesson Experience & Teacher-Directed Focus.
Verifies:
1. Hard fail-closed lockout on production / staging / unknown environments.
2. Safe enablement strictly in confirmed local development.
3. Domain-level blocking (boostudy.ru).
4. Socket.IO contract for 'whiteboard_show_here', 'whiteboard_viewport' (mobile), and 'focus_suggestion'.
5. Role-based permissions (student cannot invoke teacher master controls).
6. Asset presence and structural validity.
"""
from __future__ import annotations

import os
from unittest.mock import patch, MagicMock
import pytest
from flask import Flask

from app.utils.pocket_os import is_pocket_os_enabled


class TestPocketOsFeatureFlagContract:
    """Rigorous fail-closed matrix tests for is_pocket_os_enabled."""

    def test_production_environment_hard_lockout(self):
        """Even if BOOSTUDY_POCKET_OS_ENABLED=1, production must ALWAYS return False."""
        with patch.dict(os.environ, {
            "ENVIRONMENT": "production",
            "APP_ENV": "production",
            "FLASK_ENV": "production",
            "BOOSTUDY_POCKET_OS_ENABLED": "1",
        }, clear=True):
            assert is_pocket_os_enabled() is False

    def test_staging_and_sandbox_hard_lockout(self):
        """Staging or sandbox environments must strictly return False."""
        for env_name in ("staging", "sandbox", "prod"):
            with patch.dict(os.environ, {
                "ENVIRONMENT": env_name,
                "BOOSTUDY_POCKET_OS_ENABLED": "1",
            }, clear=True):
                assert is_pocket_os_enabled() is False, f"Failed for env: {env_name}"

    def test_production_flag_override(self):
        """BOOSTUDY_PRODUCTION=1 must unconditionally disable Pocket OS."""
        with patch.dict(os.environ, {
            "ENVIRONMENT": "local",
            "BOOSTUDY_PRODUCTION": "1",
            "BOOSTUDY_POCKET_OS_ENABLED": "1",
        }, clear=True):
            assert is_pocket_os_enabled() is False

    def test_unknown_or_empty_environment_fail_closed(self):
        """Undefined, blank, or unrecognized environment strings must fail-closed."""
        for unknown in ("", "unknown", "ci-build", "docker-test", "preview-stage"):
            with patch.dict(os.environ, {
                "ENVIRONMENT": unknown,
                "APP_ENV": "",
                "FLASK_ENV": "",
                "BOOSTUDY_POCKET_OS_ENABLED": "1",
            }, clear=True):
                assert is_pocket_os_enabled() is False, f"Did not fail-closed for '{unknown}'"

    def test_production_domain_context_lockout(self):
        """If request context host is boostudy.ru, never activate."""
        app = Flask("test_pocket_os_app")
        app.config["ENVIRONMENT"] = "local"
        with app.test_request_context("/", headers={"Host": "boostudy.ru"}):
            with patch.dict(os.environ, {"ENVIRONMENT": "local", "BOOSTUDY_POCKET_OS_ENABLED": "1"}):
                assert is_pocket_os_enabled(app) is False

        with app.test_request_context("/", headers={"Host": "api.boostudy.ru:443"}):
            with patch.dict(os.environ, {"ENVIRONMENT": "local", "BOOSTUDY_POCKET_OS_ENABLED": "1"}):
                assert is_pocket_os_enabled(app) is False

    def test_local_development_explicit_disable(self):
        """In local development, if flag is explicitly false/0/off, return False."""
        for false_val in ("0", "false", "off", "no"):
            with patch.dict(os.environ, {
                "ENVIRONMENT": "local",
                "BOOSTUDY_POCKET_OS_ENABLED": false_val,
            }, clear=True):
                assert is_pocket_os_enabled() is False

    def test_local_development_enabled(self):
        """In confirmed local development, flag is True."""
        with patch.dict(os.environ, {
            "ENVIRONMENT": "local",
            "BOOSTUDY_POCKET_OS_ENABLED": "1",
        }, clear=True):
            assert is_pocket_os_enabled() is True


class TestPocketOsSocketContracts:
    """Verifies Socket.IO event contracts and permission gates."""

    def test_socket_teacher_master_kinds_include_show_here_and_suggestion(self):
        """_on_lesson_room_ui must permit show_here and focus_suggestion only for teachers."""
        import inspect
        from app.lessons import lesson_socket

        source = inspect.getsource(lesson_socket.register_lesson_socket)
        assert '"show_here"' in source
        assert '"focus_suggestion"' in source
        assert '"set_focus"' in source
        assert '"terminal_close"' in source
        assert '"focus_suggestion_ack"' in source

    def test_socket_whiteboard_show_here_handler_registered(self):
        """Dedicated whiteboard_show_here handler exists and checks role."""
        import inspect
        from app.lessons import lesson_socket

        source = inspect.getsource(lesson_socket.register_lesson_socket)
        assert '@socketio.on("whiteboard_show_here", namespace="/lesson")' in source
        assert 'role != "teacher"' in source
        assert 'Показать здесь доступно только преподавателю' in source

    def test_socket_whiteboard_viewport_includes_mobile_and_device(self):
        """whiteboard_viewport handles is_mobile, device, and terminal_open metadata."""
        import inspect
        from app.lessons import lesson_socket
        from app.lessons.whiteboard_service import default_control

        ctrl = default_control()
        assert "teacher_controls_focus" in ctrl
        assert ctrl["teacher_controls_focus"] is False

        source = inspect.getsource(lesson_socket.register_lesson_socket)
        assert '"is_mobile": bool(payload.get("is_mobile", False))' in source
        assert '"device": str(payload.get("device") or "desktop")[:16]' in source
        assert '"terminal_open": bool(payload.get("terminal_open", False))' in source


class TestPocketOsAssetsIntegrity:
    """Verifies that static assets exist and contain the required components."""

    def test_css_asset_exists_and_contains_core_classes(self):
        css_path = os.path.join(os.path.dirname(__file__), "..", "..", "static", "css", "boostudy-pocket-os.css")
        assert os.path.isfile(css_path), f"CSS asset missing at {css_path}"
        with open(css_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "body.pocket-os-active" in content
        assert "pocket-focus-surface" in content
        assert "pocket-nav-bar" in content
        assert "pocket-virtual-symbols" in content
        assert "pocket-video-pill" in content
        assert "pocket-toast" in content
        assert "is-mobile-contour" in content

    def test_js_asset_exists_and_exports_pocket_os(self):
        js_path = os.path.join(os.path.dirname(__file__), "..", "..", "static", "js", "boostudy-pocket-os.js")
        assert os.path.isfile(js_path), f"JS asset missing at {js_path}"
        with open(js_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "window.BooStudyPocketOS = BooStudyPocketOS" in content
        assert "switchFocus(mode" in content
        assert "whiteboard_show_here" in content
        assert "focus_suggestion" in content
        assert "whiteboard_viewport" in content
        assert "reportMobileViewport" in content
        assert "enforceReadOnlyCanvas" in content
        assert "pocket-virtual-symbols" in content
