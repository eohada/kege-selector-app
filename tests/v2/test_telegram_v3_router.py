"""Integration tests for BooStudy Bot V3 Router, command dispatching, and account linking."""
import asyncio
from datetime import datetime, timedelta, timezone
import pytest

from app.models import db, User, UserProfile
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
from app.telegram.v3.router import (
    attempt_link_by_code_or_token,
    handle_cancel_command,
    handle_help_command,
    handle_menu_command,
    handle_role_command,
    handle_settings_command,
    handle_start_command,
    handle_text_message,
    handle_unlink_command,
    handle_v3_callback,
)


def run(coro):
    return asyncio.run(coro)


class MockMessage:
    def __init__(self, text=""):
        self.text = text
        self.replies = []
        self.edits = []

    async def reply_text(self, text, reply_markup=None, parse_mode=None, **kwargs):
        self.replies.append({"text": text, "reply_markup": reply_markup, "parse_mode": parse_mode})

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None, **kwargs):
        self.edits.append({"text": text, "reply_markup": reply_markup, "parse_mode": parse_mode})


class MockCallbackQuery:
    def __init__(self, data=""):
        self.data = data
        self.message = MockMessage()
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append({"text": text, "show_alert": show_alert})

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None, **kwargs):
        self.message.edits.append({"text": text, "reply_markup": reply_markup, "parse_mode": parse_mode})


class MockUpdate:
    def __init__(self, chat_id=123, text="", callback_data=None):
        self.effective_chat = type("Chat", (), {"id": chat_id})()
        self.effective_user = type("User", (), {"id": chat_id, "username": f"user_{chat_id}", "first_name": "Test", "last_name": "User"})()
        if callback_data:
            self.callback_query = MockCallbackQuery(data=callback_data)
            self.message = None
        else:
            self.callback_query = None
            self.message = MockMessage(text=text)


class MockContext:
    def __init__(self, args=None):
        self.args = args or []
        self.user_data = {}


def _create_user_with_link_code(username: str, role: str, code: str, expired: bool = False) -> User:
    u = User(username=username, role=role, is_active=True)
    db.session.add(u)
    db.session.flush()

    exp = datetime.now(timezone.utc) + (timedelta(minutes=-10) if expired else timedelta(minutes=15))
    p = UserProfile(
        user_id=u.id,
        first_name=username.capitalize(),
        telegram_link_code=code,
        telegram_link_code_expires=exp,
    )
    db.session.add(p)
    db.session.commit()
    return u


def _create_user_with_token(username: str, role: str, token: str, expired: bool = False) -> User:
    u = User(username=username, role=role, is_active=True)
    db.session.add(u)
    db.session.flush()

    exp = datetime.now(timezone.utc) + (timedelta(minutes=-10) if expired else timedelta(minutes=15))
    p = UserProfile(
        user_id=u.id,
        first_name=username.capitalize(),
        telegram_link_token=token,
        telegram_link_token_expires=exp,
    )
    db.session.add(p)
    db.session.commit()
    return u


def test_link_by_code_success(app):
    with app.app_context():
        user = _create_user_with_link_code("student_code_test", "student", "BS-T3ST01")
        tg_user = type("TGUser", (), {"id": 777111, "username": "tg_alex"})()

        success, msg, linked_user = attempt_link_by_code_or_token(777111, tg_user, "BS-T3ST01")
        assert success is True
        assert linked_user.id == user.id

        # Check DB updated
        prof = UserProfile.query.filter_by(user_id=user.id).first()
        assert prof.telegram_chat_id == 777111
        assert prof.telegram_link_code is None  # Code consumed


def test_link_by_code_case_insensitive_and_without_prefix(app):
    with app.app_context():
        user = _create_user_with_link_code("student_case_test", "student", "BS-ABC123")
        tg_user = type("TGUser", (), {"id": 777222, "username": "tg_bob"})()

        # Input lowercase without BS- prefix: "abc123"
        success, msg, linked_user = attempt_link_by_code_or_token(777222, tg_user, "abc123")
        assert success is True
        assert linked_user.id == user.id


def test_link_by_code_expired_rejected(app):
    with app.app_context():
        _create_user_with_link_code("student_exp_test", "student", "BS-EXP001", expired=True)
        tg_user = type("TGUser", (), {"id": 777333, "username": "tg_exp"})()

        success, msg, linked_user = attempt_link_by_code_or_token(777333, tg_user, "BS-EXP001")
        assert success is False
        assert "истек" in msg
        assert linked_user is None


def test_link_by_deep_link_token_success(app):
    with app.app_context():
        token = "a" * 48
        user = _create_user_with_token("student_token_test", "student", token)
        tg_user = type("TGUser", (), {"id": 777444, "username": "tg_tok"})()

        success, msg, linked_user = attempt_link_by_code_or_token(777444, tg_user, token)
        assert success is True
        assert linked_user.id == user.id

        prof = UserProfile.query.filter_by(user_id=user.id).first()
        assert prof.telegram_chat_id == 777444
        assert prof.telegram_link_token is None  # Token consumed


def test_link_conflict_prevention(app):
    with app.app_context():
        # User 1 already linked to chat 888999
        u1 = _create_user_with_link_code("user_existing", "student", "BS-ONE001")
        prof1 = u1.profile
        prof1.telegram_chat_id = 888999
        db.session.commit()

        # User 2 generates code
        _create_user_with_link_code("user_second", "student", "BS-TWO002")
        tg_user = type("TGUser", (), {"id": 888999, "username": "tg_same"})()

        # Try to link chat 888999 to user 2: conflict!
        success, msg, _ = attempt_link_by_code_or_token(888999, tg_user, "BS-TWO002")
        assert success is False
        assert "уже привязан" in msg


def test_start_command_flow(app):
    with app.app_context():
        # Unlinked start
        update_unlinked = MockUpdate(chat_id=111001)
        context = MockContext()
        run(handle_start_command(update_unlinked, context))
        assert "Telegram не привязан к аккаунту" in update_unlinked.message.replies[-1]["text"]

        # Start with valid code parameter
        user = _create_user_with_link_code("student_start_test", "student", "BS-STR001")
        update_linking = MockUpdate(chat_id=111002)
        ctx_with_code = MockContext(args=["BS-STR001"])
        run(handle_start_command(update_linking, ctx_with_code))

        # Check welcome and dashboard
        assert len(update_linking.message.replies) >= 2
        assert "Аккаунт привязан" in update_linking.message.replies[0]["text"]
        assert "Личный кабинет" in update_linking.message.replies[1]["text"]


def test_plain_text_code_submission(app):
    with app.app_context():
        user = _create_user_with_link_code("student_text_test", "student", "BS-TXT001")
        update = MockUpdate(chat_id=111003, text="BS-TXT001")
        context = MockContext()

        run(handle_text_message(update, context))
        assert len(update.message.replies) >= 2
        assert "Аккаунт привязан" in update.message.replies[0]["text"]
        assert "Личный кабинет" in update.message.replies[1]["text"]


def test_menu_and_help_commands(app):
    with app.app_context():
        user = _create_user_with_link_code("user_menu_test", "student", "BS-MNU001")
        user.profile.telegram_chat_id = 111004
        db.session.commit()

        # /menu
        update_menu = MockUpdate(chat_id=111004)
        run(handle_menu_command(update_menu, MockContext()))
        assert "Личный кабинет" in update_menu.message.replies[-1]["text"]

        # /help
        update_help = MockUpdate(chat_id=111004)
        run(handle_help_command(update_help, MockContext()))
        assert "Справка и команды" in update_help.message.replies[-1]["text"]


def test_callback_dispatcher_rbac_rejection(app):
    with app.app_context():
        # Pure student user
        student = _create_user_with_link_code("student_rbac", "student", "BS-RBC001")
        student.profile.telegram_chat_id = 111005
        db.session.commit()

        # Student attempts to trigger admin dashboard via callback
        update_cb = MockUpdate(chat_id=111005, callback_data=f"{CB_PREFIX}:{DOMAIN_ADMIN}:home")
        run(handle_v3_callback(update_cb, MockContext()))

        # Query answered with alert
        assert len(update_cb.callback_query.answers) >= 1
        assert "Недостаточно прав" in update_cb.callback_query.answers[0]["text"]
        assert update_cb.callback_query.answers[0]["show_alert"] is True


def test_callback_dispatcher_role_switcher_and_unlink(app):
    with app.app_context():
        # Creator user with multi-role access
        creator = _create_user_with_link_code("chief_rbac", "creator", "BS-CRE001")
        creator.profile.telegram_chat_id = 111006
        db.session.commit()

        ctx = MockContext()

        # Switch to teacher mode
        update_switch = MockUpdate(chat_id=111006, callback_data=f"{CB_PREFIX}:{DOMAIN_CONTEXT}:set:teacher")
        run(handle_v3_callback(update_switch, ctx))
        assert "Преподавательская" in update_switch.callback_query.message.edits[-1]["text"]

        # Execute unlink via callback
        update_unlink = MockUpdate(chat_id=111006, callback_data=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:unlink:do")
        run(handle_v3_callback(update_unlink, ctx))
        assert "отвязан" in update_unlink.callback_query.answers[0]["text"]
        assert "Telegram не привязан к аккаунту" in update_unlink.callback_query.message.edits[-1]["text"]

        # Check DB reflects unlinking
        prof = UserProfile.query.filter_by(user_id=creator.id).first()
        assert prof.telegram_chat_id is None


def test_telegram_bot_version_production_guard(monkeypatch):
    from app.telegram.config import get_telegram_bot_version

    # In production without explicit TELEGRAM_BOT_VERSION -> must return 'v2'
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("TELEGRAM_BOT_VERSION", raising=False)
    assert get_telegram_bot_version() == "v2"

    # In staging without explicit -> must return 'v2'
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.delenv("TELEGRAM_BOT_VERSION", raising=False)
    assert get_telegram_bot_version() == "v2"

    # In production WITH explicit TELEGRAM_BOT_VERSION=v3 -> returns 'v3'
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("TELEGRAM_BOT_VERSION", "v3")
    assert get_telegram_bot_version() == "v3"

    # In local/dev -> returns 'v3'
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.delenv("TELEGRAM_BOT_VERSION", raising=False)
    assert get_telegram_bot_version() == "v3"


def test_idor_student_foreign_assignment(app):
    from app.models import Assignment
    with app.app_context():
        # Student A
        student_user = _create_user_with_link_code("student_a", "student", "BS-STUA01")
        student_user.profile.telegram_chat_id = 111007
        db.session.commit()

        now = datetime.now(timezone.utc)
        # Create Assignment belonging to no submission for Student A
        asg = Assignment(
            title="Secret Test HW",
            description="Secret description",
            assignment_type="homework",
            deadline=now + timedelta(days=2),
            created_by_id=student_user.id,
            is_active=True,
        )
        db.session.add(asg)
        db.session.commit()

        # Student A tries to view assignment via callback
        update_cb = MockUpdate(chat_id=111007, callback_data=f"{CB_PREFIX}:{DOMAIN_STUDENT}:hw_item:{asg.assignment_id}:1")
        run(handle_v3_callback(update_cb, MockContext()))

        # Must be rejected with "Доступ ограничен"
        assert len(update_cb.callback_query.message.edits) >= 1
        card_text = update_cb.callback_query.message.edits[-1]["text"]
        assert "Доступ ограничен" in card_text
        assert "Secret description" not in card_text


def test_idor_teacher_foreign_submission(app):
    from app.models import Assignment, Student, Submission
    with app.app_context():
        # Teacher A
        t1 = _create_user_with_link_code("teacher_1", "teacher", "BS-TCH001")
        t1.profile.telegram_chat_id = 111008
        db.session.commit()

        # Teacher B (owns Student B)
        t2 = _create_user_with_link_code("teacher_2", "teacher", "BS-TCH002")
        db.session.commit()

        st_b = Student(name="Student B", mentor_id=t2.id, is_active=True)
        db.session.add(st_b)
        db.session.flush()

        now = datetime.now(timezone.utc)
        asg = Assignment(
            title="HW for B",
            assignment_type="homework",
            deadline=now + timedelta(days=2),
            created_by_id=t2.id,
            is_active=True,
        )
        db.session.add(asg)
        db.session.flush()

        sub = Submission(assignment_id=asg.assignment_id, student_id=st_b.student_id, status="SUBMITTED")
        db.session.add(sub)
        db.session.commit()

        # Teacher A tries to view submission of Teacher B's student
        update_cb = MockUpdate(chat_id=111008, callback_data=f"{CB_PREFIX}:{DOMAIN_TEACHER}:q_item:{sub.submission_id}:1")
        run(handle_v3_callback(update_cb, MockContext()))

        assert len(update_cb.callback_query.message.edits) >= 1
        card_text = update_cb.callback_query.message.edits[-1]["text"]
        assert "Доступ ограничен" in card_text
        assert "Student B" not in card_text


def test_idor_parent_foreign_child(app):
    from app.models import Student
    with app.app_context():
        parent_user = _create_user_with_link_code("parent_a", "parent", "BS-PAR001")
        parent_user.profile.telegram_chat_id = 111009
        db.session.commit()

        # Foreign student not tied to parent
        foreign_student = Student(name="Foreign Student", is_active=True)
        db.session.add(foreign_student)
        db.session.commit()

        # Parent tries to access foreign child view, schedule, digest
        update_view = MockUpdate(chat_id=111009, callback_data=f"{CB_PREFIX}:{DOMAIN_PARENT}:ch:{foreign_student.student_id}")
        run(handle_v3_callback(update_view, MockContext()))
        assert "Доступ ограничен" in update_view.callback_query.message.edits[-1]["text"]

        update_sch = MockUpdate(chat_id=111009, callback_data=f"{CB_PREFIX}:{DOMAIN_PARENT}:sch:{foreign_student.student_id}")
        run(handle_v3_callback(update_sch, MockContext()))
        assert "Доступ ограничен" in update_sch.callback_query.message.edits[-1]["text"]

        update_dig = MockUpdate(chat_id=111009, callback_data=f"{CB_PREFIX}:{DOMAIN_PARENT}:dig:{foreign_student.student_id}")
        run(handle_v3_callback(update_dig, MockContext()))
        assert "Доступ ограничен" in update_dig.callback_query.message.edits[-1]["text"]
