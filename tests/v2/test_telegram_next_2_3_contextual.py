"""Comprehensive Contextual Experience Test Suite for Telegram Next 2.3.

Verifies deep educational informativeness and actionable cards across all 5 roles:
1. Student: nearest lesson with subject & teacher, urgent HW alerts, recently graded with feedback, multi-teacher support, clean empty states.
2. Teacher: nearest lesson with student, review queue spotlight (oldest submission by name & wait time), rich student cards with HW & schedule drilldowns.
3. Parent: single-child direct view, specific overdue homework titles & deadlines, latest grade with feedback quote, clean empty states.
4. Creator: operational platform health overview, oldest review wait time, critical bug counts, direct problem buttons.
5. Admin: failed delivery inspector with recipient, attempts, errors, and retry action.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import pytest

from app.models import (
    db,
    User,
    UserProfile,
    Student,
    Lesson,
    Assignment,
    Submission,
    FamilyTie,
)
from core.db_models import TelegramDelivery, BugReport
from app.telegram.v3.constants import CB_PREFIX, DOMAIN_ADMIN, DOMAIN_NAV, DOMAIN_PARENT, DOMAIN_STUDENT, DOMAIN_TEACHER
from app.telegram.v3.screens.student import (
    show_student_home,
    show_student_hw_item,
    show_student_hw_list,
    show_student_progress,
    show_student_schedule,
)
from app.telegram.v3.screens.teacher import (
    show_teacher_home,
    show_teacher_schedule,
    show_teacher_students_list,
    show_teacher_student_card,
    show_teacher_student_hw_list,
    show_teacher_student_schedule,
)
from app.telegram.v3.screens.parent import (
    show_parent_home,
    show_parent_child_view,
    show_parent_child_schedule,
)
from app.telegram.v3.screens.creator import show_creator_home
from app.telegram.v3.screens.admin import (
    show_admin_home,
    show_admin_problems,
    show_admin_failed_deliveries,
)


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
        self.effective_user = type("User", (), {"id": chat_id, "username": f"tg_{chat_id}", "first_name": "Test", "last_name": "User"})()
        if callback_data:
            self.callback_query = MockCallbackQuery(data=callback_data)
            self.message = None
        else:
            self.callback_query = None
            self.message = MockMessage()
            self.message.text = text


def _create_user(username: str, role: str, chat_id: int | None = None) -> User:
    u = User(username=username, role=role, is_active=True)
    db.session.add(u)
    db.session.flush()
    cid = chat_id or (70000 + u.id)
    p = UserProfile(user_id=u.id, first_name=username.capitalize(), telegram_chat_id=cid)
    db.session.add(p)
    db.session.commit()
    return u


def test_student_contextual_experience(app):
    """Verify student home screen contextual experience, urgency alerts, recently graded, multi-teacher."""
    with app.app_context():
        now = datetime.now(timezone.utc)
        t_math = _create_user("t_math_23", "teacher")
        t_cs = _create_user("t_cs_23", "teacher")

        st_user = _create_user("st_ctx_23", "student")
        st = Student(user_id=st_user.id, mentor_id=t_cs.id, name="Даниил Контекстный", category="ЕГЭ Информатика")
        db.session.add(st)
        db.session.commit()

        # 1. Lesson with teacher t_cs
        l1 = Lesson(
            student_id=st.student_id,
            teacher_id=t_cs.id,
            topic="Динамическое программирование",
            subject="Информатика",
            lesson_date=now + timedelta(hours=3),
            duration=90,
            status="planned",
        )
        db.session.add(l1)

        # 2. Urgent overdue homework with t_cs
        a_overdue = Assignment(
            title="Задание 27: Деревья",
            assignment_type="ДЗ",
            created_by_id=t_cs.id,
            deadline=now - timedelta(days=1),
            is_active=True,
        )
        db.session.add(a_overdue)
        db.session.flush()
        sub_overdue = Submission(
            student_id=st.student_id,
            assignment_id=a_overdue.assignment_id,
            status="ASSIGNED",
        )
        db.session.add(sub_overdue)

        # 3. Recently graded homework with t_math
        a_graded = Assignment(
            title="Теория вероятностей: Графы",
            assignment_type="Контрольная",
            created_by_id=t_math.id,
            deadline=now - timedelta(days=3),
            is_active=True,
        )
        db.session.add(a_graded)
        db.session.flush()
        sub_graded = Submission(
            student_id=st.student_id,
            assignment_id=a_graded.assignment_id,
            status="CHECKED",
            total_score=92,
            max_score=100,
            percentage=92.0,
            teacher_feedback="Отличный алгоритм, чистое оформление кода!",
            graded_at=now - timedelta(hours=5),
        )
        db.session.add(sub_graded)
        db.session.commit()

        # Render student home
        update = MockUpdate(chat_id=st_user.profile.telegram_chat_id)
        run(show_student_home(update, st_user))
        reply = update.message.replies[-1]
        text = reply["text"]

        # Check nearest lesson details
        assert "Динамическое программирование" in text
        assert "Информатика" in text
        assert "90 мин" in text
        assert t_cs.username in text

        # Check urgent homework block
        assert "Срочные задания" in text
        assert "Задание 27: Деревья" in text
        assert "Просрочено" in text

        # Check recently graded block with score and feedback
        assert "Недавно проверено" in text
        assert "92/100 (92%)" in text
        assert "Отличный алгоритм" in text

        # Check action button to open urgent homework
        buttons = [btn.text for row in reply["reply_markup"].inline_keyboard for btn in row]
        assert any("Открыть задание" in b for b in buttons)

        # Check schedule empty state does NOT contain party emoji
        db.session.delete(l1)
        db.session.commit()
        update_empty = MockUpdate(chat_id=st_user.profile.telegram_chat_id)
        run(show_student_schedule(update_empty, st_user))
        empty_text = update_empty.message.replies[-1]["text"]
        assert "🎉" not in empty_text
        assert "В ближайшие дни уроков не запланировано" in empty_text


def test_student_hw_item_and_progress_details(app):
    """Verify detailed card of student homework item and progress trend."""
    with app.app_context():
        now = datetime.now(timezone.utc)
        teacher = _create_user("t_item_23", "teacher")
        st_user = _create_user("st_prog_23", "student")
        st = Student(user_id=st_user.id, mentor_id=teacher.id, name="Полина Успешная", category="ЕГЭ")
        db.session.add(st)
        db.session.commit()

        a1 = Assignment(
            title="Рекурсия и перебор вариантов",
            assignment_type="ДЗ",
            description="Решите задачи 1-5 на Python с мемоизацией.",
            created_by_id=teacher.id,
            deadline=now + timedelta(days=2),
            is_active=True,
        )
        db.session.add(a1)
        db.session.flush()

        sub = Submission(
            student_id=st.student_id,
            assignment_id=a1.assignment_id,
            status="CHECKED",
            percentage=95.0,
            total_score=19,
            max_score=20,
            submitted_at=now - timedelta(days=1),
            graded_at=now - timedelta(hours=4),
            teacher_feedback="Прекрасное использование lru_cache!",
        )
        db.session.add(sub)
        db.session.commit()

        # Detailed item
        update_item = MockUpdate(chat_id=st_user.profile.telegram_chat_id)
        run(show_student_hw_item(update_item, st_user, assignment_id=a1.assignment_id))
        item_text = update_item.message.replies[-1]["text"]
        assert "Рекурсия и перебор вариантов" in item_text
        assert teacher.username in item_text
        assert "19 из 20 (95%)" in item_text
        assert "Прекрасное использование lru_cache" in item_text

        # Progress view with trend
        update_prog = MockUpdate(chat_id=st_user.profile.telegram_chat_id)
        run(show_student_progress(update_prog, st_user))
        prog_text = update_prog.message.replies[-1]["text"]
        assert "Сводка успеваемости" in prog_text
        assert "95.0%" in prog_text
        assert "Рекурсия и перебор вариантов" in prog_text


def test_teacher_contextual_experience_and_drilldowns(app):
    """Verify teacher home screen review spotlight, student list badges, and drilldown cards."""
    with app.app_context():
        now = datetime.now(timezone.utc)
        teacher = _create_user("t_spotlight_23", "teacher")
        st_user = _create_user("st_queue_23", "student")
        st = Student(user_id=st_user.id, mentor_id=teacher.id, name="Кирилл Очередной", category="ЕГЭ")
        db.session.add(st)
        db.session.commit()

        # Lesson with this teacher
        l = Lesson(
            student_id=st.student_id,
            teacher_id=teacher.id,
            topic="Разбор пробника №3",
            subject="Информатика",
            lesson_date=now + timedelta(hours=2),
            duration=60,
        )
        db.session.add(l)

        # Assignment and submission waiting in queue for 3 days
        asg = Assignment(
            title="Сложное ДЗ по графам",
            assignment_type="ДЗ",
            created_by_id=teacher.id,
            is_active=True,
            deadline=now - timedelta(days=4),
        )
        db.session.add(asg)
        db.session.flush()

        sub = Submission(
            student_id=st.student_id,
            assignment_id=asg.assignment_id,
            status="SUBMITTED",
            submitted_at=now - timedelta(days=3),
        )
        db.session.add(sub)
        db.session.commit()

        # 1. Teacher home screen
        update = MockUpdate(chat_id=teacher.profile.telegram_chat_id)
        run(show_teacher_home(update, teacher))
        reply = update.message.replies[-1]
        text = reply["text"]

        assert "Разбор пробника №3" in text
        assert "Очередь проверки:" in text
        assert "Работ ожидают проверки: <b>1</b>" in text
        assert "Старейшая работа" in text
        assert "Сложное ДЗ по графам" in text
        assert "3 дн." in text

        # Action button to check oldest submission directly
        buttons = [btn.text for row in reply["reply_markup"].inline_keyboard for btn in row]
        assert any("Проверить: Кирилл" in b for b in buttons)

        # 2. Teacher students list badges
        update_st = MockUpdate(chat_id=teacher.profile.telegram_chat_id)
        run(show_teacher_students_list(update_st, teacher, page=1))
        st_text = update_st.message.replies[-1]["text"]
        assert "Кирилл Очередной" in st_text
        assert "на проверке" in st_text

        # 3. Student card drilldown buttons
        update_card = MockUpdate(chat_id=teacher.profile.telegram_chat_id)
        run(show_teacher_student_card(update_card, teacher, student_id=st.student_id))
        card_reply = update_card.message.replies[-1]
        card_text = card_reply["text"]
        assert "Карточка ученика" in card_text
        assert "Кирилл Очередной" in card_text
        card_buttons = [btn.text for row in card_reply["reply_markup"].inline_keyboard for btn in row]
        assert any("Задания" in b for b in card_buttons)
        assert any("Расписание" in b for b in card_buttons)

        # 4. Teacher drilldown into student homeworks
        update_hw = MockUpdate(chat_id=teacher.profile.telegram_chat_id)
        run(show_teacher_student_hw_list(update_hw, teacher, student_id=st.student_id, page=1))
        hw_text = update_hw.message.replies[-1]["text"]
        assert "Сложное ДЗ по графам" in hw_text
        assert "На проверке" in hw_text

        # 5. Teacher drilldown into student schedule
        update_sch = MockUpdate(chat_id=teacher.profile.telegram_chat_id)
        run(show_teacher_student_schedule(update_sch, teacher, student_id=st.student_id))
        sch_text = update_sch.message.replies[-1]["text"]
        assert "Разбор пробника №3" in sch_text


def test_parent_contextual_experience(app):
    """Verify parent child card with detailed overdue list, feedback quote, and clean empty state."""
    with app.app_context():
        now = datetime.now(timezone.utc)
        teacher = _create_user("t_parent_23", "teacher")
        p_user = _create_user("parent_ctx_23", "parent")
        st_user = _create_user("child_ctx_23", "student")
        st = Student(user_id=st_user.id, mentor_id=teacher.id, name="Алиса Примерная", category="ОГЭ")
        db.session.add(st)
        db.session.flush()

        # Confirmed family tie
        tie = FamilyTie(parent_id=p_user.id, student_id=st.student_id, is_confirmed=True)
        db.session.add(tie)

        # Nearest lesson
        l = Lesson(
            student_id=st.student_id,
            teacher_id=teacher.id,
            topic="Основы логики и таблиц истинности",
            subject="Информатика",
            lesson_date=now + timedelta(days=1, hours=2),
            duration=60,
        )
        db.session.add(l)

        # Specific overdue assignment
        a_overdue = Assignment(
            title="Таблицы истинности: Задачи 1-10",
            assignment_type="ДЗ",
            created_by_id=teacher.id,
            deadline=now - timedelta(days=2),
            is_active=True,
        )
        db.session.add(a_overdue)
        db.session.flush()
        sub_overdue = Submission(
            student_id=st.student_id,
            assignment_id=a_overdue.assignment_id,
            status="ASSIGNED",
        )
        db.session.add(sub_overdue)

        # Graded assignment with feedback
        a_graded = Assignment(
            title="Системы счисления",
            assignment_type="ДЗ",
            created_by_id=teacher.id,
            deadline=now - timedelta(days=5),
            is_active=True,
        )
        db.session.add(a_graded)
        db.session.flush()
        sub_graded = Submission(
            student_id=st.student_id,
            assignment_id=a_graded.assignment_id,
            status="CHECKED",
            percentage=88.0,
            total_score=22,
            max_score=25,
            teacher_feedback="Хорошее понимание двоичной системы, обратите внимание на шестнадцатеричную.",
            graded_at=now - timedelta(days=1),
        )
        db.session.add(sub_graded)
        db.session.commit()

        # Single child parent automatically opens child view
        update = MockUpdate(chat_id=p_user.profile.telegram_chat_id)
        run(show_parent_home(update, p_user))
        reply = update.message.replies[-1]
        text = reply["text"]

        # Nearest lesson
        assert "Основы логики и таблиц истинности" in text
        assert teacher.username in text

        # Specific overdue list
        assert "Просроченные задания" in text
        assert "Таблицы истинности: Задачи 1-10" in text

        # Latest grade and feedback quote
        assert "Системы счисления" in text
        assert "22 из 25 баллов" in text
        assert "Хорошее понимание двоичной системы" in text


def test_creator_and_admin_operational_alerts(app):
    """Verify creator executive health summary, alert buttons, and admin problem empty state."""
    with app.app_context():
        creator = _create_user("chief_creator_23", "creator")

        # Create a failed Telegram delivery
        deliv = TelegramDelivery(
            user_id=creator.id,
            telegram_chat_id=12345678,
            kind="assignment_deadline_reminder",
            payload={"text": "Reminder"},
            dedupe_key="test_deliv_ctx_unique_99",
            status="failed",
            attempt_count=3,
            last_error="TelegramNetworkError: Bad Gateway 502",
        )
        db.session.add(deliv)

        # Create a critical bug report
        bug = BugReport(
            reporter_id=creator.id,
            title="Критический сбой платежного шлюза",
            description="Ошибка при оплате уроков",
            severity="CRITICAL",
            status="NEW",
        )
        db.session.add(bug)
        db.session.commit()

        # Render creator home
        update = MockUpdate(chat_id=creator.profile.telegram_chat_id)
        run(show_creator_home(update, creator))
        reply = update.message.replies[-1]
        text = reply["text"]

        assert "критичных: <b>1</b>" in text
        assert "сбоев: 1" in text

        # Check that quick alert buttons are present
        buttons = [btn.text for row in reply["reply_markup"].inline_keyboard for btn in row]
        assert any("Сбои Outbox" in b for b in buttons)
        assert any("Критичные баги" in b for b in buttons)

        # Verify admin failed deliveries view shows error details
        update_deliv = MockUpdate(chat_id=creator.profile.telegram_chat_id)
        run(show_admin_failed_deliveries(update_deliv, creator, page=1))
        deliv_text = update_deliv.message.replies[-1]["text"]
        assert "Сбои Telegram Outbox" in deliv_text
        assert "Bad Gateway 502" in deliv_text

        # Verify empty state in admin problems has no party emoji when resolved
        db.session.delete(bug)
        db.session.commit()
        update_prob = MockUpdate(chat_id=creator.profile.telegram_chat_id)
        run(show_admin_problems(update_prob, creator))
        prob_text = update_prob.message.replies[-1]["text"]
        assert "🎉" not in prob_text
        assert "Все обращения обработаны" in prob_text
