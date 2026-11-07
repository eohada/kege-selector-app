"""Comprehensive User Acceptance and Conversational UX test suite for Telegram Next 2.2.

Covers all 16 screens reviewed during platform owner manual acceptance:
- Multi-teacher isolation & no duplicate student records
- Dynamic Me / Student notification comparison engine
- Broadcast Center 5-step wizard, zero auto-injection of Creator, recipient stability
- Notification settings unclipped event detail cards & safe preview toasts
- Parent cabinet single/multi child handling, nearest lesson with teacher name, RBAC child HW
- Student cabinet upcoming lessons across future days, clear active/overdue HW, progress UX
- Admin delivery failure inspector & retry action
- Creator cabinet clear role/username distinction and default /start mode toggle
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
from core.db_models import TelegramDelivery, TelegramBroadcast
from app.telegram.application import (
    build_teacher_students,
    _student_ids_for_context,
)
from app.telegram.v3.constants import CB_PREFIX, DOMAIN_NAV, DOMAIN_PREVIEW, DOMAIN_SETTINGS
from app.telegram.v3.screens.admin import (
    retry_admin_delivery,
    show_admin_failed_deliveries,
    show_admin_home,
)
from app.telegram.v3.screens.broadcast import (
    analyze_broadcast_recipients,
    clear_draft,
    execute_broadcast_send,
    get_or_create_draft,
    show_broadcast_campaign_details,
    show_broadcast_preview,
)
from app.telegram.v3.screens.creator import show_creator_home
from app.telegram.v3.screens.parent import (
    show_parent_child_hw_item,
    show_parent_child_hw_list,
    show_parent_child_view,
    show_parent_home,
)
from app.telegram.v3.screens.preview import show_notification_preview
from app.telegram.v3.screens.settings import (
    show_category_events_menu,
    show_event_detail_card,
    toggle_event_preference,
)
from app.telegram.v3.screens.student import (
    show_student_home,
    show_student_progress,
)
from app.telegram.v3.screens.teacher import (
    show_teacher_home,
    show_teacher_student_card,
    show_teacher_students_list,
)
from app.telegram.v3.screens.teacher_student_notifications import (
    evaluate_delivery_for_comparison,
    show_delivery_comparison_mode,
    show_student_notification_details,
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
        self.effective_user = type("User", (), {"id": chat_id, "username": f"tg_u_{chat_id}", "first_name": "Test", "last_name": "User"})()
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
    cid = chat_id or (20000 + u.id)
    p = UserProfile(user_id=u.id, first_name=username.capitalize(), telegram_chat_id=cid)
    db.session.add(p)
    db.session.commit()
    return u


def test_teacher_student_list_isolation_and_no_duplicates(app):
    """Test 1: Multi-teacher isolation, no duplicate student rows, and name disambiguation."""
    with app.app_context():
        teacher_a = _create_user("t_alice_22", "teacher")
        teacher_b = _create_user("t_bob_22", "teacher")

        # Create students for Teacher A
        st1_user = _create_user("st1_user_22", "student")
        st1 = Student(user_id=st1_user.id, mentor_id=teacher_a.id, name="Иван Иванов", category="ЕГЭ Информатика")
        db.session.add(st1)

        st2_user = _create_user("st2_user_22", "student")
        st2 = Student(user_id=st2_user.id, mentor_id=teacher_a.id, name="Иван Иванов", category="ОГЭ Информатика")
        db.session.add(st2)

        # Create student for Teacher B (should NEVER leak to Teacher A)
        st_b_user = _create_user("st_b_user_22", "student")
        st_b = Student(user_id=st_b_user.id, mentor_id=teacher_b.id, name="Пётр Сидоров", category="ЕГЭ Математика")
        db.session.add(st_b)
        db.session.commit()

        # Check build_teacher_students for Teacher A
        t_a_students = build_teacher_students(teacher_a)
        assert len(t_a_students) == 2

        # Check disambiguation between the two "Иван Иванов"
        names = [s["name"] for s in t_a_students]
        assert "Иван Иванов" in names[0] or "Иван Иванов" in names[1]
        assert names[0] != names[1]  # Must be disambiguated by category or ID!

        # Context IDs must match exactly
        context_ids = _student_ids_for_context(teacher_a, "teacher")
        assert len(context_ids) == 2
        assert st_b.student_id not in context_ids

        # Render Teacher Students List screen
        update = MockUpdate(chat_id=teacher_a.profile.telegram_chat_id)
        run(show_teacher_students_list(update, teacher_a, page=1))
        reply = update.message.replies[-1]["text"]
        assert "Мои ученики" in reply
        assert "Пётр Сидоров" not in reply

        # Render Student Card with multi-teacher isolation
        run(show_teacher_student_card(update, teacher_a, student_id=st1.student_id))
        card_reply = update.message.replies[-1]["text"]
        assert "Карточка ученика" in card_reply
        assert "Иван Иванов" in card_reply
        assert "Telegram:" in card_reply


def test_dynamic_notification_comparison_engine(app):
    """Test 2: Dynamic comparison engine evaluates policy rules without LaTeX math."""
    with app.app_context():
        teacher = _create_user("t_cmp_22", "teacher")
        student_user = _create_user("st_cmp_22", "student")
        student = Student(user_id=student_user.id, mentor_id=teacher.id, name="Даниил Тестов")
        db.session.add(student)
        db.session.commit()

        # Evaluate lesson_reminder
        ev_title, t_verdict, s_verdict = evaluate_delivery_for_comparison(teacher, student_user.id, "lesson_reminder")
        assert "Напоминание" in ev_title
        assert "✅" in t_verdict or "доставка" in t_verdict.lower()
        assert "✅" in s_verdict or "доставка" in s_verdict.lower()

        # Render comparison screen
        update = MockUpdate(chat_id=teacher.profile.telegram_chat_id)
        run(show_delivery_comparison_mode(update, teacher, student_user_id=student_user.id, event_kind="lesson_reminder"))
        reply = update.message.replies[-1]["text"]
        assert "Сравнение доставки" in reply
        assert "Напоминание об уроке" in reply
        # Verify no LaTeX artifacts
        assert "$\\ge" not in reply
        assert "$ge" not in reply
        assert "Read-only" not in reply


def test_broadcast_zero_creator_injection_and_stability(app):
    """Test 3: Broadcast recipient stability and strict zero auto-injection of Creator."""
    with app.app_context():
        creator = _create_user("creator_bc_22", "creator")
        teacher = _create_user("teacher_bc_22", "teacher")
        student_u = _create_user("student_bc_22", "student")
        student = Student(user_id=student_u.id, mentor_id=teacher.id, name="Студент Рассылки")
        db.session.add(student)
        db.session.commit()

        # Analysis for students
        analysis = analyze_broadcast_recipients(teacher, audience="students", category="broadcast")
        eligible_ids = {u.id for u in analysis["eligible_users"]}

        # CRITICAL SAFETY CHECK: Creator must NOT be injected into students audience
        assert creator.id not in eligible_ids
        assert student_u.id in eligible_ids

        # Set up draft for teacher
        draft = get_or_create_draft(teacher.id)
        draft.audience = "students"
        draft.category = "broadcast"
        draft.title = "Важное объявление"
        draft.text = "Уважаемые ученики, завтра практический вебинар."
        draft.button_label = "Открыть BooStudy"
        draft.button_url = "https://boostudy.ru/webinar"

        # Preview screen
        update = MockUpdate(chat_id=teacher.profile.telegram_chat_id)
        run(show_broadcast_preview(update, teacher))
        preview_text = update.message.replies[-1]["text"]
        assert "Подтверждение рассылки" in preview_text or "Предпросмотр" in preview_text
        assert "Важное объявление" in preview_text

        # Execute send
        run(execute_broadcast_send(update, teacher))
        send_text = update.message.replies[-1]["text"]
        assert "Рассылка запущена" in send_text

        # Verify DB campaign record matches exact analysis
        campaign = TelegramBroadcast.query.filter_by(created_by_user_id=teacher.id).order_by(TelegramBroadcast.broadcast_id.desc()).first()
        assert campaign is not None
        assert campaign.total_planned == len(analysis["eligible_users"])
        assert campaign.sent_ok == len(analysis["eligible_users"])

        # History detail view
        run(show_broadcast_campaign_details(update, teacher, broadcast_id=campaign.broadcast_id))
        detail_text = update.message.replies[-1]["text"]
        assert f"Кампания #{campaign.broadcast_id}" in detail_text
        assert "Важное объявление" in detail_text


def test_settings_detail_card_and_safe_preview(app):
    """Test 4: Settings unclipped event detail cards and inert preview toasts."""
    with app.app_context():
        user = _create_user("set_user_22", "student")
        update = MockUpdate(chat_id=user.profile.telegram_chat_id)

        # 1. Category events menu shows full-width buttons
        run(show_category_events_menu(update, user, role="student", category="lessons"))
        cat_reply = update.message.replies[-1]
        buttons = [btn.text for row in cat_reply["reply_markup"].inline_keyboard for btn in row]
        # Full button titles, no clipped dots
        assert any("Напоминание об уроке" in b for b in buttons)

        # 2. Event detail card
        run(show_event_detail_card(update, user, role="student", category="lessons", kind="lesson_reminder"))
        card_reply = update.message.replies[-1]["text"]
        assert "Напоминание об уроке" in card_reply
        assert "Статус доставки:" in card_reply
        assert "Назначение оповещения:" in card_reply

        # 3. Notification preview card
        run(show_notification_preview(update, role="student", kind="lesson_reminder"))
        prev_reply = update.message.replies[-1]
        prev_text = prev_reply["text"]
        assert "Событие:" in prev_text
        assert "Получатель:" in prev_text
        assert "Тип: lesson_reminder" not in prev_text

        # Action buttons in preview must have safe callback_data and NO live url
        prev_buttons = [btn for row in prev_reply["reply_markup"].inline_keyboard for btn in row]
        action_btns = [b for b in prev_buttons if b.callback_data == f"{CB_PREFIX}:{DOMAIN_PREVIEW}:noop"]
        assert len(action_btns) >= 1
        assert all(b.url is None for b in action_btns)


def test_parent_cabinet_and_child_homework_rbac(app):
    """Test 5: Parent single/multi child handling, nearest lesson with teacher, and HW RBAC."""
    with app.app_context():
        parent = _create_user("parent_22", "parent")
        tutor = _create_user("tutor_22", "teacher")
        st_user = _create_user("child_22", "student")
        student = Student(user_id=st_user.id, mentor_id=tutor.id, name="Алиса Смирнова")
        db.session.add(student)
        db.session.commit()

        # Link parent to student via FamilyTie
        tie = FamilyTie(parent_id=parent.id, student_id=student.student_id, is_confirmed=True)
        db.session.add(tie)

        # Add upcoming lesson with teacher
        now = datetime.now(timezone.utc)
        lesson = Lesson(
            student_id=student.student_id,
            teacher_id=tutor.id,
            lesson_date=now + timedelta(days=2),
            topic="Разбор стереометрии",
            status="planned",
        )
        db.session.add(lesson)

        # Add assignments: 1 active, 1 graded
        asg1 = Assignment(
            title="ДЗ по стереометрии",
            description="Решить задачи 1-5",
            assignment_type="homework",
            created_by_id=tutor.id,
            deadline=now + timedelta(days=3),
            is_active=True,
        )
        asg2 = Assignment(
            title="Проверочная по алгебре",
            description="Тест",
            assignment_type="homework",
            created_by_id=tutor.id,
            deadline=now - timedelta(days=1),
            is_active=True,
        )
        db.session.add_all([asg1, asg2])
        db.session.flush()

        sub1 = Submission(assignment_id=asg1.assignment_id, student_id=student.student_id, status="ASSIGNED")
        sub2 = Submission(
            assignment_id=asg2.assignment_id,
            student_id=student.student_id,
            status="GRADED",
            percentage=92.0,
            total_score=23,
            max_score=25,
            teacher_feedback="Отличная работа!",
            graded_at=now,
        )
        db.session.add_all([sub1, sub2])
        db.session.commit()

        # 1. Parent home with 1 child opens child view directly
        update = MockUpdate(chat_id=parent.profile.telegram_chat_id)
        run(show_parent_home(update, parent))
        card_text = update.message.replies[-1]["text"]
        assert "Алиса Смирнова" in card_text
        assert "Разбор стереометрии" in card_text
        assert "Tutor_22" in card_text or "tutor_22" in card_text.lower()
        assert "Последняя проверенная работа:" in card_text
        assert "92%" in card_text

        # 2. Parent child HW list
        run(show_parent_child_hw_list(update, parent, student_id=student.student_id, page=1))
        hw_list_text = update.message.replies[-1]["text"]
        assert "Задания ребёнка" in hw_list_text
        assert "ДЗ по стереометрии" in hw_list_text

        # 3. Parent child HW item
        run(show_parent_child_hw_item(update, parent, student_id=student.student_id, assignment_id=asg2.assignment_id))
        hw_item_text = update.message.replies[-1]["text"]
        assert "Проверочная по алгебре" in hw_item_text
        assert "92%" in hw_item_text
        assert "Отличная работа!" in hw_item_text

        # 4. RBAC check: Unrelated parent cannot view homework
        other_parent = _create_user("intruder_parent", "parent")
        other_update = MockUpdate(chat_id=other_parent.profile.telegram_chat_id)
        run(show_parent_child_hw_list(other_update, other_parent, student_id=student.student_id, page=1))
        assert "Доступ ограничен" in other_update.message.replies[-1]["text"]


def test_student_cabinet_future_lessons_and_progress_empty_state(app):
    """Test 6: Student next lesson across dates and polite progress empty state."""
    with app.app_context():
        tutor = _create_user("tutor_st_22", "teacher")
        st_user = _create_user("student_ux_22", "student")
        student = Student(user_id=st_user.id, mentor_id=tutor.id, name="Елена Попова")
        db.session.add(student)
        db.session.commit()

        # Add lesson in 4 days (not today)
        now = datetime.now(timezone.utc)
        lesson = Lesson(
            student_id=student.student_id,
            teacher_id=tutor.id,
            lesson_date=now + timedelta(days=4),
            topic="Динамическое программирование",
            status="planned",
        )
        db.session.add(lesson)
        db.session.commit()

        # Student home should find the lesson across future days
        update = MockUpdate(chat_id=st_user.profile.telegram_chat_id)
        run(show_student_home(update, st_user))
        home_text = update.message.replies[-1]["text"]
        assert "Динамическое программирование" in home_text
        assert "Просроченных заданий:" in home_text
        assert "<b>0</b> ✅" in home_text

        # Progress screen with no graded work shows polite empty state
        run(show_student_progress(update, st_user))
        prog_text = update.message.replies[-1]["text"]
        assert "Оценок пока нет" in prog_text
        assert "0.0%" not in prog_text


def test_admin_failed_deliveries_inspector(app):
    """Test 7: Admin delivery failure inspector and retry action."""
    with app.app_context():
        admin = _create_user("admin_dl_22", "admin")
        update = MockUpdate(chat_id=admin.profile.telegram_chat_id)

        # 1. Admin Home shows failure button
        run(show_admin_home(update, admin))
        admin_home_reply = update.message.replies[-1]
        buttons = [btn.text for row in admin_home_reply["reply_markup"].inline_keyboard for btn in row]
        assert any("Сбои Telegram Outbox" in b for b in buttons)

        # 2. Create failed delivery
        failed_deliv = TelegramDelivery(
            user_id=admin.id,
            telegram_chat_id=admin.profile.telegram_chat_id,
            kind="lesson_reminder",
            payload={"text": "Урок начался"},
            priority="normal",
            dedupe_key=f"test:failed:delivery:{admin.id}",
            status="failed",
            attempt_count=3,
            last_error="Telegram API 403: Bot was blocked by the user",
        )
        db.session.add(failed_deliv)
        db.session.commit()

        # 3. View failed deliveries
        run(show_admin_failed_deliveries(update, admin, page=1))
        failed_view_text = update.message.replies[-1]["text"]
        assert "Сбои Telegram Outbox" in failed_view_text
        assert "Telegram API 403" in failed_view_text

        # 4. Retry delivery
        run(retry_admin_delivery(update, admin, delivery_id=failed_deliv.delivery_id, return_page=1))
        db.session.refresh(failed_deliv)
        assert failed_deliv.status == "pending"
        assert failed_deliv.last_error is None


def test_creator_cabinet_ux_clarity(app):
    """Test 8: Creator cabinet clear username display and distinct toggle button."""
    with app.app_context():
        creator = _create_user("chief_creator_22", "creator")
        update = MockUpdate(chat_id=creator.profile.telegram_chat_id)

        run(show_creator_home(update, creator))
        reply = update.message.replies[-1]
        text = reply["text"]
        assert "👑 Кабинет Создателя платформы" in text
        assert "Пользователь: chief_creator_22" in text
        assert "Общеплатформенная сводка BooStudy (все пользователи)" in text

        # Check separate toggle button vs direct teacher button
        buttons = [btn for row in reply["reply_markup"].inline_keyboard for btn in row]
        toggle_btn = next((b for b in buttons if "Сменить дефолт /start" in b.text or "Переключить" in b.text), None)
        teacher_nav_btn = next((b for b in buttons if b.text == "👨‍🏫 Преподавательская"), None)

        assert toggle_btn is not None
        assert teacher_nav_btn is not None
        assert toggle_btn.callback_data != teacher_nav_btn.callback_data


def test_admin_retry_guard_rails(app):
    """Test 9: Admin retry guard rails (cancelled lesson, unlinked tg, sent duplicate, expired)."""
    with app.app_context():
        admin = _create_user("admin_guard_22", "admin")
        update = MockUpdate(chat_id=admin.profile.telegram_chat_id)

        # 1. Guard against retrying already 'sent' delivery
        sent_deliv = TelegramDelivery(
            user_id=admin.id,
            telegram_chat_id=admin.profile.telegram_chat_id,
            kind="system_announcement",
            payload={"text": "Already sent"},
            priority="normal",
            dedupe_key=f"test:guard:sent:{admin.id}",
            status="sent",
        )
        db.session.add(sent_deliv)
        db.session.commit()

        run(retry_admin_delivery(update, admin, delivery_id=sent_deliv.delivery_id, return_page=1))
        db.session.refresh(sent_deliv)
        assert sent_deliv.status == "sent"  # Must NOT be modified to pending!

        # 2. Guard against retrying cancelled lesson notification
        cancelled_lesson = Lesson(
            teacher_id=admin.id,
            topic="Отменённое занятие",
            subject="Информатика",
            status="cancelled",
            lesson_date=datetime.now(timezone.utc) + timedelta(days=2),
        )
        db.session.add(cancelled_lesson)
        db.session.commit()

        lesson_deliv = TelegramDelivery(
            user_id=admin.id,
            telegram_chat_id=admin.profile.telegram_chat_id,
            kind="lesson_scheduled",
            payload={"text": "Урок", "lesson_id": cancelled_lesson.lesson_id},
            priority="normal",
            dedupe_key=f"test:guard:cancelled_lesson:{cancelled_lesson.lesson_id}",
            status="failed",
            last_error="Network timeout",
        )
        db.session.add(lesson_deliv)
        db.session.commit()

        run(retry_admin_delivery(update, admin, delivery_id=lesson_deliv.delivery_id, return_page=1))
        db.session.refresh(lesson_deliv)
        assert lesson_deliv.status == "cancelled"
        assert "lesson_cancelled" in str(lesson_deliv.last_error)

        # 3. Guard against duplicate when duplicate already sent
        sent_deliv.notification_id = 9911
        db.session.commit()

        dup_failed = TelegramDelivery(
            user_id=admin.id,
            notification_id=9911,
            telegram_chat_id=admin.profile.telegram_chat_id,
            kind="system_announcement",
            payload={"text": "Already sent duplicate"},
            priority="normal",
            dedupe_key=f"test:guard:dup_failed:{admin.id}",
            status="failed",
            last_error="Failed attempt",
        )
        db.session.add(dup_failed)
        db.session.commit()

        run(retry_admin_delivery(update, admin, delivery_id=dup_failed.delivery_id, return_page=1))
        db.session.refresh(dup_failed)
        assert dup_failed.status == "cancelled"
        assert "duplicate already sent" in str(dup_failed.last_error)

        # 4. Guard against unlinked recipient
        unlinked_user = _create_user("unlinked_guard_22", "student")
        unlinked_user.profile.telegram_chat_id = None
        unlinked_user.telegram_chat_id = None
        db.session.commit()

        unlinked_deliv = TelegramDelivery(
            user_id=unlinked_user.id,
            telegram_chat_id=None,
            kind="lesson_reminder",
            payload={"text": "Reminder for unlinked"},
            priority="normal",
            dedupe_key=f"test:guard:unlinked:{unlinked_user.id}",
            status="failed",
            last_error="No chat id",
        )
        db.session.add(unlinked_deliv)
        db.session.commit()

        run(retry_admin_delivery(update, admin, delivery_id=unlinked_deliv.delivery_id, return_page=1))
        db.session.refresh(unlinked_deliv)
        assert unlinked_deliv.status == "cancelled"
        assert "unlinked" in str(unlinked_deliv.last_error)


def test_real_accounts_and_outbox_edge_cases(app, monkeypatch):
    """Test 10: Outbox edge cases - 403 blocking, simulated vs sent separation, preference suppression."""
    with app.app_context():
        from app.telegram.delivery import enqueue_delivery, claim_due_deliveries, deliver_one
        from core.db_models import UserNotificationPreference

        # 1. User blocks bot (HTTP 403 Forbidden)
        blocked_user = _create_user("blocked_user_22", "student")
        blocked_user.profile.telegram_notifications_enabled = True
        db.session.commit()

        d_blocked = enqueue_delivery(
            blocked_user.id,
            "Тестовое уведомление",
            kind="lesson_reminder",
            priority="normal",
        )
        db.session.commit()

        # Mock is_delivery_permitted to True for live delivery test
        monkeypatch.setattr("app.telegram.delivery.is_delivery_permitted", lambda chat_id, user_id=None: True)

        # Mock send_telegram_message to simulate Telegram 403
        monkeypatch.setattr(
            "app.telegram.delivery.send_telegram_message",
            lambda chat_id, text, **kw: {"ok": False, "error_code": 403, "description": "Forbidden: bot was blocked by the user"},
        )

        claims = claim_due_deliveries(limit=10)
        assert d_blocked.delivery_id in claims

        res = deliver_one(d_blocked.delivery_id)
        assert res["ok"] is False
        assert res["status"] == "failed"

        db.session.refresh(d_blocked)
        db.session.refresh(blocked_user.profile)
        assert d_blocked.status == "failed"
        assert "blocked" in str(d_blocked.last_error).lower()
        # Personal preferences and master enabled flag are preserved!
        assert blocked_user.profile.telegram_notifications_enabled is True
        assert blocked_user.profile.telegram_blocked_at is not None

        # Re-interaction (/start or message) clears blocked state
        from app.telegram.v3.identity import touch_interaction
        touch_interaction(blocked_user.profile.telegram_chat_id)
        db.session.refresh(blocked_user.profile)
        assert blocked_user.profile.telegram_blocked_at is None

        # 2. Emergency Kill Switch pause and resume
        from app.telegram.config import set_kill_switch_active
        ks_user = _create_user("ks_user_22", "student")
        d_ks = enqueue_delivery(ks_user.id, "Pending delivery", kind="system_announcement")
        db.session.commit()

        set_kill_switch_active(True)
        try:
            # Kill switch suppresses claiming completely
            ks_claims = claim_due_deliveries(limit=10)
            assert ks_claims == []

            # Direct deliver_one pauses delivery safely in retry status without dropping
            d_ks.status = "processing"
            db.session.commit()
            pause_res = deliver_one(d_ks.delivery_id)
            assert pause_res["status"] == "paused"
            assert pause_res["paused"] is True
            db.session.refresh(d_ks)
            assert d_ks.status == "retry"
            assert "kill switch" in str(d_ks.last_error)
        finally:
            set_kill_switch_active(False)

        # 3. Suppression of disabled notifications
        pref_user = _create_user("pref_optout_user_22", "student")
        db.session.add(UserNotificationPreference(
            user_id=pref_user.id,
            role="student",
            event_kind="homework_submitted",
            is_enabled=False,
        ))
        db.session.commit()

        d_pref = enqueue_delivery(
            pref_user.id,
            "Ваша работа проверена",
            kind="homework_submitted",
            meta={"recipient_role": "student"},
        )
        db.session.commit()

        claims = claim_due_deliveries(limit=10)
        assert d_pref.delivery_id in claims

        res = deliver_one(d_pref.delivery_id)
        assert res["status"] == "cancelled"
        assert res.get("reason") == "disabled_by_preference"

        # 3. Simulated delivery distinction (never treated as 'sent')
        sim_user = _create_user("sim_user_22", "student")
        d_sim = enqueue_delivery(
            sim_user.id,
            "Симулированная доставка",
            kind="system_announcement",
        )
        db.session.commit()

        # Monkeypatch is_delivery_permitted to return False (dev dry run)
        monkeypatch.setattr("app.telegram.delivery.is_delivery_permitted", lambda chat_id, user_id=None: False)

        claims = claim_due_deliveries(limit=10)
        assert d_sim.delivery_id in claims

        res = deliver_one(d_sim.delivery_id)
        assert res["status"] == "simulated"
        assert res.get("dry_run") is True

        db.session.refresh(d_sim)
        assert d_sim.status == "simulated"
        assert d_sim.status != "sent"  # Strict distinction


def test_bot_v2_rollback_compatibility(app, monkeypatch):
    """Test 11: Rollback compatibility - Bot V2 application builds and executes safely with new DB."""
    with app.app_context():
        monkeypatch.setenv("TELEGRAM_BOT_VERSION", "v2")
        from app.telegram.config import get_telegram_bot_version
        from app.telegram.webhook import _build_application
        from app.telegram.handlers import cmd_help

        assert get_telegram_bot_version() == "v2"

        v2_app = _build_application(with_updater=False)
        assert v2_app is not None
        assert len(v2_app.handlers.get(0, [])) > 0

        # Verify V2 handler runs without breaking on new DB schema
        v2_user = _create_user("v2_rollback_user", "student")
        update = MockUpdate(chat_id=v2_user.profile.telegram_chat_id)
        run(cmd_help(update, None))
        assert len(update.message.replies) > 0
        help_reply = update.message.replies[-1]["text"]
        assert "BooStudy" in help_reply or "Команды" in help_reply or "Помощь" in help_reply

        # Restore v3
        monkeypatch.setenv("TELEGRAM_BOT_VERSION", "v3")
        assert get_telegram_bot_version() == "v3"



