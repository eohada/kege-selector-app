"""Integration tests for BooStudy Bot V3 Screen renderers."""
import asyncio
from datetime import datetime, timezone
import pytest

from app.models import db, User, UserProfile
from app.telegram.v3.constants import CB_PREFIX, DOMAIN_NAV
from app.telegram.v3.screens.admin import (
    show_admin_home,
    show_admin_metrics,
    show_admin_problems,
    show_admin_user_card,
    show_admin_users_list,
)
from app.telegram.v3.screens.creator import show_creator_home
from app.telegram.v3.screens.parent import (
    show_parent_child_digest,
    show_parent_child_schedule,
    show_parent_child_view,
    show_parent_home,
)
from app.telegram.v3.screens.settings import (
    show_help_screen,
    show_notifications_menu,
    show_role_switcher_menu,
    show_settings_home,
    show_unlink_confirmation,
)
from app.telegram.v3.screens.student import (
    show_student_home,
    show_student_hw_item,
    show_student_hw_list,
    show_student_progress,
    show_student_schedule,
)
from app.telegram.v3.screens.teacher import (
    show_teacher_home,
    show_teacher_review_queue,
    show_teacher_schedule,
    show_teacher_student_card,
    show_teacher_students_list,
    show_teacher_submission_item,
)
from app.telegram.v3.screens.unlinked import show_unlinked_screen


def run(coro):
    return asyncio.run(coro)


class MockMessage:
    def __init__(self):
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
        self.effective_user = type("User", (), {"id": chat_id, "username": "tg_user", "first_name": "First", "last_name": "Last"})()
        if callback_data:
            self.callback_query = MockCallbackQuery(data=callback_data)
            self.message = None
        else:
            self.callback_query = None
            self.message = MockMessage()
            self.message.text = text


def _make_user(username: str, role: str) -> User:
    u = User(username=username, role=role, is_active=True)
    db.session.add(u)
    db.session.flush()
    p = UserProfile(user_id=u.id, first_name=username.capitalize(), telegram_chat_id=1000 + u.id)
    db.session.add(p)
    db.session.commit()
    return u


def test_show_unlinked_screen():
    update = MockUpdate(chat_id=999)
    run(show_unlinked_screen(update))

    assert len(update.message.replies) == 1
    reply = update.message.replies[0]
    assert "Telegram не привязан к аккаунту" in reply["text"]
    assert "Открыть профиль BooStudy" in reply["reply_markup"].inline_keyboard[0][0].text


def test_student_screens(app):
    with app.app_context():
        student = _make_user("alex_student", "student")
        update = MockUpdate(chat_id=student.profile.telegram_chat_id)

        # 1. Student Home
        run(show_student_home(update, student))
        assert len(update.message.replies) >= 1
        assert "Личный кабинет" in update.message.replies[-1]["text"]

        # 2. Student Schedule
        run(show_student_schedule(update, student))
        assert "Расписание занятий" in update.message.replies[-1]["text"]

        # 3. Student Homework List
        run(show_student_hw_list(update, student, page=1))
        assert "Домашние задания" in update.message.replies[-1]["text"]

        # 4. Student Progress
        run(show_student_progress(update, student))
        assert "Прогресс обучения" in update.message.replies[-1]["text"]


def test_teacher_screens(app):
    with app.app_context():
        teacher = _make_user("maria_teacher", "teacher")
        update = MockUpdate(chat_id=teacher.profile.telegram_chat_id)

        # 1. Teacher Home
        run(show_teacher_home(update, teacher))
        assert "Преподавательская" in update.message.replies[-1]["text"]

        # 2. Teacher Schedule
        run(show_teacher_schedule(update, teacher))
        assert "Расписание уроков" in update.message.replies[-1]["text"]

        # 3. Teacher Review Queue
        run(show_teacher_review_queue(update, teacher, page=1))
        assert "Очередь проверки" in update.message.replies[-1]["text"]

        # 4. Teacher Students List
        run(show_teacher_students_list(update, teacher, page=1))
        assert "Мои ученики" in update.message.replies[-1]["text"]


def test_parent_screens(app):
    with app.app_context():
        parent = _make_user("olga_parent", "parent")
        update = MockUpdate(chat_id=parent.profile.telegram_chat_id)

        # Parent Home
        run(show_parent_home(update, parent))
        assert "Родительский кабинет" in update.message.replies[-1]["text"]


def test_admin_screens(app):
    with app.app_context():
        admin = _make_user("pavel_admin", "admin")
        update = MockUpdate(chat_id=admin.profile.telegram_chat_id)

        # 1. Admin Home
        run(show_admin_home(update, admin))
        assert "Панель администратора" in update.message.replies[-1]["text"]

        # 2. Admin Metrics
        run(show_admin_metrics(update, admin))
        assert "Сводные метрики" in update.message.replies[-1]["text"]

        # 3. Admin Problems
        run(show_admin_problems(update, admin))
        assert "Проблемы и обращения" in update.message.replies[-1]["text"]

        # 4. Admin Users List
        run(show_admin_users_list(update, admin, page=1, role_filter="all"))
        assert "Пользователи" in update.message.replies[-1]["text"]

        # 5. Admin Single User Card
        run(show_admin_user_card(update, admin, target_user_id=admin.id, return_page=1, return_role="all"))
        assert "Карточка пользователя" in update.message.replies[-1]["text"]
        assert f"ID: {admin.id}" in update.message.replies[-1]["text"]


def test_creator_screens(app):
    with app.app_context():
        creator = _make_user("chief_creator", "creator")
        update = MockUpdate(chat_id=creator.profile.telegram_chat_id)

        run(show_creator_home(update, creator))
        assert "Кабинет Создателя" in update.message.replies[-1]["text"]
        assert "Текущий рабочий режим" in update.message.replies[-1]["text"]


def test_settings_screens(app):
    with app.app_context():
        user = _make_user("ivan_student", "student")
        update = MockUpdate(chat_id=user.profile.telegram_chat_id)

        # 1. Settings Home
        run(show_settings_home(update, user, active_context="student"))
        assert "Настройки и профиль" in update.message.replies[-1]["text"]

        # 2. Notifications Menu
        run(show_notifications_menu(update, user))
        assert "Настройка уведомлений" in update.message.replies[-1]["text"]

        # 3. Role Switcher Menu
        run(show_role_switcher_menu(update, user, current_context="student"))
        assert "Выбор роли" in update.message.replies[-1]["text"]

        # 4. Help Screen
        run(show_help_screen(update, user))
        assert "Справка и команды" in update.message.replies[-1]["text"]

        # 5. Unlink Confirmation
        run(show_unlink_confirmation(update, user))
        assert "Отвязка Telegram" in update.message.replies[-1]["text"]
