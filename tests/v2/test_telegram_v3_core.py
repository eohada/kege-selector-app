"""Tests for BooStudy Bot V3 Core: context, RBAC authorization, UI formatting and helpers."""
import pytest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.telegram.v3.constants import (
    CB_PREFIX,
    DOMAIN_ADMIN,
    DOMAIN_CONTEXT,
    DOMAIN_CREATOR,
    DOMAIN_NAV,
    DOMAIN_PARENT,
    DOMAIN_SETTINGS,
    DOMAIN_STUDENT,
    DOMAIN_TEACHER,
)
from app.telegram.v3.context import (
    get_active_context,
    get_user_contexts,
    switch_context,
    toggle_creator_mode,
)
from app.telegram.v3.router import check_domain_access
from app.telegram.v3.ui import (
    build_nav_row,
    build_pagination_row,
    card_header,
    escape,
    format_dt,
)


class MockUser:
    def __init__(self, roles, user_id=10, mode="ADMIN", username="testuser"):
        self.id = user_id
        self.username = username
        self.role = roles[0]
        self._roles = roles
        self.creator_bot_mode = mode

    def roles(self):
        return self._roles


def test_escape_html():
    assert escape("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"
    assert escape("Hello & World") == "Hello &amp; World"
    assert escape(None) == ""
    assert escape(123) == "123"


def test_format_dt_russian_relative():
    now_utc = datetime.now(timezone.utc)
    res_today = format_dt(now_utc)
    assert "Сегодня в" in res_today

    none_res = format_dt(None)
    assert none_res == "Не указано"


def test_build_pagination_row():
    # Only 1 page: no pagination buttons needed
    assert build_pagination_row("stu", "hw", 1, 1) == []

    # Page 1 of 3: [·, 1 / 3, ▶]
    row = build_pagination_row("stu", "hw", 1, 3)
    assert len(row) == 3
    assert row[0].text == "·"
    assert row[1].text == "1 / 3"
    assert row[2].callback_data == f"{CB_PREFIX}:stu:hw:2"

    # Page 2 of 3: [◀, 2 / 3, ▶]
    row2 = build_pagination_row("stu", "hw", 2, 3)
    assert len(row2) == 3
    assert row2[0].callback_data == f"{CB_PREFIX}:stu:hw:1"
    assert row2[1].text == "2 / 3"
    assert row2[2].callback_data == f"{CB_PREFIX}:stu:hw:3"

    # Page 3 of 3 with extra parameter: [◀, 3 / 3, ·]
    row3 = build_pagination_row("adm", "u", 3, 3, extra="all")
    assert len(row3) == 3
    assert row3[0].callback_data == f"{CB_PREFIX}:adm:u:2:all"
    assert row3[1].text == "3 / 3"
    assert row3[2].text == "·"



def test_build_nav_row():
    row = build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_STUDENT}:home")
    assert len(row) == 2
    assert row[0].callback_data == f"{CB_PREFIX}:{DOMAIN_STUDENT}:home"
    assert row[1].callback_data == f"{CB_PREFIX}:{DOMAIN_NAV}:home"


def test_card_header():
    header = card_header("Заголовок", "Подзаголовок")
    assert "<b>Заголовок</b>" in header
    assert "<i>Подзаголовок</i>" in header


def test_context_resolution_student():
    student_user = MockUser(["student"])
    assert get_active_context(student_user) == "student"
    assert get_user_contexts(student_user) == ("student",)

    # Attempt unauthorized switch
    assert switch_context(student_user, "admin") == "student"
    assert switch_context(student_user, "creator") == "student"


def test_context_resolution_creator_and_toggle():
    creator_user = MockUser(["creator"], mode="ADMIN")
    assert get_active_context(creator_user) == "creator"
    assert get_user_contexts(creator_user) == ("teacher", "creator")

    # Toggle to teacher mode
    new_mode = toggle_creator_mode(creator_user)
    assert new_mode == "teacher"
    assert creator_user.creator_bot_mode == "TEACHER"

    # Toggle back to creator mode
    back_mode = toggle_creator_mode(creator_user)
    assert back_mode == "creator"
    assert creator_user.creator_bot_mode == "ADMIN"


def test_server_side_rbac_check_domain_access():
    student = MockUser(["student"])
    teacher = MockUser(["teacher"])
    parent = MockUser(["parent"])
    admin = MockUser(["admin"])
    creator = MockUser(["creator"])

    # Student checks
    assert check_domain_access(student, DOMAIN_STUDENT) is True
    assert check_domain_access(student, DOMAIN_TEACHER) is False
    assert check_domain_access(student, DOMAIN_ADMIN) is False
    assert check_domain_access(student, DOMAIN_CREATOR) is False

    # Teacher checks
    assert check_domain_access(teacher, DOMAIN_TEACHER) is True
    assert check_domain_access(teacher, DOMAIN_ADMIN) is False

    # Parent checks
    assert check_domain_access(parent, DOMAIN_PARENT) is True
    assert check_domain_access(parent, DOMAIN_STUDENT) is False

    # Admin checks
    assert check_domain_access(admin, DOMAIN_ADMIN) is True
    assert check_domain_access(admin, DOMAIN_CREATOR) is False

    # Creator has universal access
    assert check_domain_access(creator, DOMAIN_STUDENT) is True
    assert check_domain_access(creator, DOMAIN_TEACHER) is True
    assert check_domain_access(creator, DOMAIN_PARENT) is True
    assert check_domain_access(creator, DOMAIN_ADMIN) is True
    assert check_domain_access(creator, DOMAIN_CREATOR) is True
