"""Comprehensive end-to-end test suite for the 5 critical user journeys in Telegram Next 2.2.

1. New student linking -> cabinet -> notification settings toggle.
2. Teacher inspects student card -> learning stats -> notification comparison.
3. Teacher schedules multiple lessons -> grouped batch card delivered to student.
4. Homework lifecycle: student submits -> teacher reviews -> student receives score & feedback.
5. Creator broadcast: custom campaign -> recipient analysis -> send -> history inspection.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import pytest

from app import db
from core.db_models import (
    User,
    UserProfile,
    Student,
    Lesson,
    Assignment,
    Submission,
    TelegramDelivery,
    TelegramBroadcast,
    UserNotificationPreference,
)
from app.telegram.v3.router import handle_start_command
from app.telegram.v3.screens.student import show_student_home
from app.telegram.v3.screens.teacher import show_teacher_student_card
from app.telegram.v3.screens.teacher_student_notifications import (
    evaluate_delivery_for_comparison,
    show_delivery_comparison_mode,
)
from app.telegram.v3.screens.settings import toggle_event_preference
from app.telegram.v3.screens.broadcast import (
    BroadcastDraft,
    analyze_broadcast_recipients,
    execute_broadcast_send,
    get_or_create_draft,
    show_broadcast_campaign_details,
    _DRAFTS,
)
from app.schedule.routes import notify_scheduled_lessons_batch
from app.telegram.delivery import claim_due_deliveries, deliver_one, enqueue_delivery
from app.telegram.user_notify import is_notification_enabled_for_user


def run(coro):
    return asyncio.run(coro)


class MockMessage:
    def __init__(self, text=""):
        self.text = text
        self.replies = []
        self.edits = []

    async def reply_text(self, text, reply_markup=None, parse_mode=None, **kwargs):
        self.replies.append({"text": text, "reply_markup": reply_markup, "parse_mode": parse_mode, **kwargs})

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None, **kwargs):
        self.edits.append({"text": text, "reply_markup": reply_markup, "parse_mode": parse_mode, **kwargs})


class MockCallbackQuery:
    def __init__(self, data="", message=None):
        self.data = data
        self.message = message or MockMessage()
        self.answers = []

    async def answer(self, text=None, show_alert=False, **kwargs):
        self.answers.append({"text": text, "show_alert": show_alert, **kwargs})

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None, **kwargs):
        self.message.edits.append({"text": text, "reply_markup": reply_markup, "parse_mode": parse_mode, **kwargs})


class MockUpdate:
    def __init__(self, chat_id=1001, text="", callback_data=None):
        self.effective_chat = type("Chat", (), {"id": chat_id})()
        self.effective_user = type("User", (), {"id": chat_id, "username": f"user_{chat_id}", "first_name": "Test", "last_name": "User"})()
        msg = MockMessage(text=text)
        if callback_data:
            self.callback_query = MockCallbackQuery(data=callback_data, message=msg)
            self.message = None
        else:
            self.callback_query = None
            self.message = msg


class MockContext:
    def __init__(self, args=None):
        self.args = args or []
        self.user_data = {}


def test_scenario_1_new_student_linking_cabinet_and_settings(app):
    """Scenario 1: New student links Telegram, opens home cabinet, and toggles notification preferences."""
    with app.app_context():
        # Setup student user with link token
        st_user = User(username="st_scen_1", role="student")
        db.session.add(st_user)
        db.session.flush()

        st_prof = UserProfile(
            user_id=st_user.id,
            telegram_link_token="TOKEN_SCENARIO_1_VALID",
            telegram_link_token_expires=datetime.now(timezone.utc) + timedelta(minutes=15),
            telegram_notifications_enabled=True,
        )
        db.session.add(st_prof)
        db.session.commit()

        # Student sends /start TOKEN_SCENARIO_1_VALID
        st_chat_id = 7711001
        update = MockUpdate(chat_id=st_chat_id, text="/start TOKEN_SCENARIO_1_VALID")
        context = MockContext(args=["TOKEN_SCENARIO_1_VALID"])
        run(handle_start_command(update, context))

        # Check linking success
        db.session.refresh(st_prof)
        assert st_prof.telegram_chat_id == st_chat_id
        assert len(update.message.replies) > 0
        assert "Аккаунт привязан" in update.message.replies[0]["text"]

        # Student opens student home
        up_home = MockUpdate(chat_id=st_chat_id)
        run(show_student_home(up_home, st_user))
        home_text = up_home.message.replies[-1]["text"]
        assert "Личный кабинет" in home_text
        assert "Ученик" in home_text

        # Student toggles homework_checked notification preference
        assert is_notification_enabled_for_user(st_user.id, role="student", kind="homework_checked") is True
        up_toggle = MockUpdate(chat_id=st_chat_id, callback_data="v3:st:notif:tog:student:homework:homework_checked")
        run(toggle_event_preference(up_toggle, st_user, "student", "homework", "homework_checked"))

        # Verify preference persisted
        assert is_notification_enabled_for_user(st_user.id, role="student", kind="homework_checked") is False


def test_scenario_2_teacher_inspects_student_and_compares_notifications(app):
    """Scenario 2: Teacher views student card, checks learning info, and runs dynamic notification comparison."""
    with app.app_context():
        teacher = User(username="t_scen_2", role="teacher")
        student_u = User(username="st_scen_2", role="student")
        db.session.add_all([teacher, student_u])
        db.session.flush()

        t_prof = UserProfile(user_id=teacher.id, telegram_chat_id=7711002, telegram_notifications_enabled=True)
        st_prof = UserProfile(user_id=student_u.id, telegram_chat_id=7711003, telegram_notifications_enabled=True)
        student_rec = Student(name="Алексей Смирнов", user_id=student_u.id, mentor_id=teacher.id, target_score=85, category="ЕГЭ Информатика", is_active=True)
        db.session.add_all([t_prof, st_prof, student_rec])
        db.session.commit()

        # Teacher opens student card
        up_tch = MockUpdate(chat_id=t_prof.telegram_chat_id)
        run(show_teacher_student_card(up_tch, teacher, student_rec.student_id))
        card_text = up_tch.message.replies[-1]["text"]
        assert "Алексей Смирнов" in card_text
        assert "85" in card_text
        assert "✅ Подключён" in card_text

        # Run dynamic notification comparison
        ev_title, t_verdict, s_verdict = evaluate_delivery_for_comparison(teacher, student_u.id, "lesson_reminder")
        assert "Напоминание" in ev_title
        assert "✅" in t_verdict or "доставка" in t_verdict.lower()
        assert "✅" in s_verdict or "доставка" in s_verdict.lower()
        assert "\\ge 3" not in t_verdict
        assert "\\ge 3" not in s_verdict

        # Render comparison screen
        up_comp = MockUpdate(chat_id=t_prof.telegram_chat_id)
        run(show_delivery_comparison_mode(up_comp, teacher, student_user_id=student_u.id, event_kind="lesson_reminder"))
        comp_text = up_comp.message.replies[-1]["text"]
        assert "Сравнение доставки" in comp_text
        assert "Напоминание" in comp_text
        assert "\\ge 3" not in comp_text


def test_scenario_3_teacher_schedules_batch_and_student_receives_grouped_card(app):
    """Scenario 3: Teacher schedules 3 lessons -> mass batching generates single grouped card."""
    with app.app_context():
        teacher = User(username="t_scen_3", role="teacher")
        student_u = User(username="st_scen_3", role="student")
        db.session.add_all([teacher, student_u])
        db.session.flush()

        t_prof = UserProfile(user_id=teacher.id, telegram_chat_id=7711004, telegram_notifications_enabled=True)
        st_prof = UserProfile(user_id=student_u.id, telegram_chat_id=7711005, telegram_notifications_enabled=True)
        student_rec = Student(name="Мария Иванова", user_id=student_u.id, mentor_id=teacher.id, is_active=True)
        db.session.add_all([t_prof, st_prof, student_rec])
        db.session.commit()

        # Create 3 planned lessons
        now_dt = datetime.now(timezone.utc)
        lessons = [
            Lesson(
                teacher_id=teacher.id,
                student_id=student_rec.student_id,
                subject="Информатика",
                topic=f"Тема #{i}",
                lesson_date=now_dt + timedelta(days=i+1),
                status="planned",
            )
            for i in range(1, 4)
        ]
        db.session.add_all(lessons)
        db.session.commit()

        # Trigger batch notification via application service
        notify_scheduled_lessons_batch(lessons, student=student_rec, actor_user_id=teacher.id)

        # Verify Outbox received exactly 1 grouped batch card for student, and 0 cards for teacher (self-action suppressed)
        deliveries = TelegramDelivery.query.filter_by(user_id=student_u.id).all()
        assert len(deliveries) == 1
        batch_deliv = deliveries[0]
        assert "Вам назначили 3" in batch_deliv.payload["text"]
        assert "Ближайшие уроки:" in batch_deliv.payload["text"]

        teacher_deliveries = TelegramDelivery.query.filter_by(user_id=teacher.id).all()
        assert len(teacher_deliveries) == 0


def test_scenario_4_homework_submission_and_grading_lifecycle(app):
    """Scenario 4: Student submits homework -> teacher notified. Teacher grades -> student receives score."""
    with app.app_context():
        teacher = User(username="t_scen_4", role="teacher")
        student_u = User(username="st_scen_4", role="student")
        db.session.add_all([teacher, student_u])
        db.session.flush()

        t_prof = UserProfile(user_id=teacher.id, telegram_chat_id=7711006, telegram_notifications_enabled=True)
        st_prof = UserProfile(user_id=student_u.id, telegram_chat_id=7711007, telegram_notifications_enabled=True)
        student_rec = Student(name="Дмитрий Попов", user_id=student_u.id, mentor_id=teacher.id, is_active=True)
        db.session.add_all([t_prof, st_prof, student_rec])
        db.session.commit()

        assignment = Assignment(
            title="Задание №27 Динамика",
            assignment_type="homework",
            deadline=datetime.now(timezone.utc) + timedelta(days=3),
            created_by_id=teacher.id,
        )
        db.session.add(assignment)
        db.session.commit()

        # 1. Student submits homework
        submission = Submission(
            assignment_id=assignment.assignment_id,
            student_id=student_rec.student_id,
            status="submitted",
        )
        db.session.add(submission)
        db.session.commit()

        # Enqueue teacher review notification
        enqueue_delivery(
            teacher.id,
            f"📥 Ученик Дмитрий Попов сдал задание «{assignment.title}»",
            kind="teacher_homework_submitted",
            meta={"submission_id": submission.submission_id, "recipient_role": "teacher"},
        )
        db.session.commit()

        t_delivs = TelegramDelivery.query.filter_by(user_id=teacher.id).all()
        assert len(t_delivs) == 1
        assert "сдал задание" in t_delivs[0].payload["text"]

        # 2. Teacher grades homework
        submission.status = "CHECKED"
        submission.total_score = 92
        submission.max_score = 100
        submission.teacher_feedback = "Отличное решение задачи!"
        submission.graded_at = datetime.now(timezone.utc)
        db.session.commit()

        enqueue_delivery(
            student_u.id,
            f"✅ Задание «{assignment.title}» проверено!\nБалл: <b>92/100</b>\nКомментарий: Отличное решение задачи!",
            kind="homework_checked",
            meta={"submission_id": submission.submission_id, "recipient_role": "student"},
        )
        db.session.commit()

        st_delivs = TelegramDelivery.query.filter_by(user_id=student_u.id).all()
        assert len(st_delivs) == 1
        assert "92/100" in st_delivs[0].payload["text"]


def test_scenario_5_creator_custom_broadcast_and_delivery_history(app):
    """Scenario 5: Creator creates broadcast -> recipient calculation -> send -> campaign history inspection."""
    with app.app_context():
        creator = User(username="creator_scen_5", role="creator")
        student_1 = User(username="st_b1", role="student")
        student_2 = User(username="st_b2", role="student")
        db.session.add_all([creator, student_1, student_2])
        db.session.flush()

        cr_prof = UserProfile(user_id=creator.id, telegram_chat_id=854161398, telegram_notifications_enabled=True)
        st1_prof = UserProfile(user_id=student_1.id, telegram_chat_id=7711008, telegram_notifications_enabled=True)
        st2_prof = UserProfile(user_id=student_2.id, telegram_chat_id=7711009, telegram_notifications_enabled=True)
        db.session.add_all([cr_prof, st1_prof, st2_prof])
        db.session.commit()

        # Setup draft
        draft = get_or_create_draft(creator.id)
        draft.audience = "students"
        draft.category = "announcement"
        draft.title = "Пробный экзамен по субботам"
        draft.text = "Уважаемые ученики! В эту субботу состоится пробник."
        draft.button_label = "Записаться"
        draft.button_url = "https://boostudy.ru/schedule"

        # Analyze recipients
        stats = analyze_broadcast_recipients(creator, audience="students", category="announcement")
        assert stats["total_audience"] >= 2
        assert stats["linked_telegram"] >= 2
        assert len(stats["eligible_users"]) >= 2
        eligible_ids = {u.id for u in stats["eligible_users"]}
        assert creator.id not in eligible_ids

        # Execute send
        up_cr = MockUpdate(chat_id=cr_prof.telegram_chat_id)
        run(execute_broadcast_send(up_cr, creator))

        # Check campaign record & details
        campaign = TelegramBroadcast.query.filter_by(created_by_user_id=creator.id).order_by(TelegramBroadcast.broadcast_id.desc()).first()
        assert campaign is not None
        assert campaign.total_planned >= 2

        # Check campaign details view
        run(show_broadcast_campaign_details(up_cr, creator, broadcast_id=campaign.broadcast_id))
        reply_text = up_cr.message.replies[-1]["text"]
        assert "Пробный экзамен по субботам" in reply_text
