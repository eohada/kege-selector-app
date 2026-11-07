"""
Comprehensive test suite for BooStudy Telegram Next safety, freshness, and RBAC overhaul:
1. Safe dev delivery mode (dry-run simulated by default, isolated live opt-in).
2. Freshness and pre-send object re-validation (cancelled lesson, past lesson, graded submission, revoked family tie, expired TTL).
3. Multi-teacher relationship scope and cross-teacher IDOR isolation.
4. Inline callback payload length (<= 64 bytes) and missing entity handling.
"""
from datetime import datetime, timedelta, timezone
import pytest

from app.models import (
    db, User, UserProfile, Student, Lesson,
    Assignment, Submission, FamilyTie, TeacherStudent
)
from core.db_models import TelegramDelivery, utc_now
from app.telegram.config import (
    is_live_delivery_active, set_live_delivery_active,
    is_delivery_permitted
)
from app.telegram.delivery import (
    claim_due_deliveries, deliver_one, enqueue_delivery,
    validate_delivery_freshness
)
from app.telegram.application import (
    _student_ids_for_context, _build_teacher_review_query,
    can_teacher_review_submission
)
from app.telegram.notification_templates import render_telegram_notification


def test_safe_delivery_mode_toggle(monkeypatch, tmp_path):
    # Ensure delivery mode file is isolated in tmp_path
    control_file = tmp_path / "telegram_delivery_mode.json"
    monkeypatch.setattr("app.telegram.config._CONTROL_FILE", str(control_file))

    monkeypatch.delenv("TELEGRAM_LIVE_TEST_MODE", raising=False)
    monkeypatch.delenv("TELEGRAM_DEV_SEND_LIVE_NOTIFICATIONS", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("TELEGRAM_DEV_ALLOWLIST_CHAT_IDS", "854161398")

    assert not is_live_delivery_active()

    # Enable live delivery
    set_live_delivery_active(True)
    assert is_live_delivery_active()
    assert is_delivery_permitted(854161398, user_id=4)

    # Disable live delivery
    set_live_delivery_active(False)
    assert not is_live_delivery_active()
    assert not is_delivery_permitted(854161398, user_id=4)


def test_delivery_simulated_in_dev_dry_run(app, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.delenv("TELEGRAM_LIVE_TEST_MODE", raising=False)
    monkeypatch.setattr("app.telegram.config.is_live_delivery_active", lambda: False)

    with app.app_context():
        user = User(username='dryrun-user', role='student')
        db.session.add(user)
        db.session.flush()
        db.session.add(UserProfile(user_id=user.id, telegram_chat_id=854161398, telegram_notifications_enabled=True))
        db.session.commit()

        row = enqueue_delivery(user.id, 'Test notification content', kind='news', dedupe_key='test:dryrun:1')
        claimed = claim_due_deliveries()
        assert row.delivery_id in claimed

        result = deliver_one(row.delivery_id)
        assert result['ok'] is True
        assert result['status'] == 'simulated'
        assert result.get('dry_run') is True

        updated_row = db.session.get(TelegramDelivery, row.delivery_id)
        assert updated_row.status == 'simulated'
        assert updated_row.sent_at is not None
        assert '[dev_dry_run]' in (updated_row.last_error or '')


def test_freshness_expired_ttl(app):
    with app.app_context():
        user = User(username='ttl-user', role='student')
        db.session.add(user)
        db.session.flush()
        db.session.add(UserProfile(user_id=user.id, telegram_chat_id=11111, telegram_notifications_enabled=True))

        past_time = (utc_now() - timedelta(minutes=10)).isoformat()
        row = TelegramDelivery(
            user_id=user.id,
            kind='lesson_reminder',
            dedupe_key='test:ttl:1',
            payload={'text': 'reminder', 'expires_at': past_time},
            status='processing'
        )
        db.session.add(row)
        db.session.commit()

        is_valid, reason = validate_delivery_freshness(row)
        assert not is_valid
        assert reason == 'expired_by_policy'

        res = deliver_one(row.delivery_id)
        assert res['status'] == 'cancelled'
        assert 'expired_by_policy' in res.get('reason', '')


def test_freshness_cancelled_lesson(app):
    with app.app_context():
        teacher = User(username='t-fresh', role='teacher')
        student = User(username='s-fresh', role='student')
        db.session.add_all([teacher, student])
        db.session.flush()
        db.session.add(UserProfile(user_id=student.id, telegram_chat_id=22222, telegram_notifications_enabled=True))

        st_rec = Student(user_id=student.id, name='S Fresh', is_active=True)
        db.session.add(st_rec)
        db.session.flush()

        lesson = Lesson(
            teacher_id=teacher.id,
            student_id=st_rec.student_id,
            topic='Algebra',
            lesson_date=utc_now() + timedelta(hours=3),
            status='cancelled'
        )
        db.session.add(lesson)
        db.session.flush()

        row = TelegramDelivery(
            user_id=student.id,
            kind='lesson_scheduled',
            dedupe_key='test:cancelled:1',
            payload={'text': 'Lesson planned', 'lesson_id': lesson.lesson_id},
            status='processing'
        )
        db.session.add(row)
        db.session.commit()

        is_valid, reason = validate_delivery_freshness(row)
        assert not is_valid
        assert reason == 'lesson_cancelled'

        res = deliver_one(row.delivery_id)
        assert res['status'] == 'cancelled'
        assert 'lesson_cancelled' in res.get('reason', '')


def test_freshness_already_started_lesson_reminder(app):
    with app.app_context():
        teacher = User(username='t-past', role='teacher')
        student = User(username='s-past', role='student')
        db.session.add_all([teacher, student])
        db.session.flush()
        db.session.add(UserProfile(user_id=student.id, telegram_chat_id=33333, telegram_notifications_enabled=True))

        st_rec = Student(user_id=student.id, name='S Past', is_active=True)
        db.session.add(st_rec)
        db.session.flush()

        lesson = Lesson(
            teacher_id=teacher.id,
            student_id=st_rec.student_id,
            topic='Geometry',
            lesson_date=utc_now() - timedelta(minutes=15),
            status='planned'
        )
        db.session.add(lesson)
        db.session.flush()

        row = TelegramDelivery(
            user_id=student.id,
            kind='lesson_reminder',
            dedupe_key='test:started:1',
            payload={'text': 'Lesson reminder', 'lesson_id': lesson.lesson_id},
            status='processing'
        )
        db.session.add(row)
        db.session.commit()

        is_valid, reason = validate_delivery_freshness(row)
        assert not is_valid
        assert reason == 'lesson_already_started'


def test_freshness_already_graded_submission(app):
    with app.app_context():
        teacher = User(username='t-sub', role='teacher')
        student = User(username='s-sub', role='student')
        db.session.add_all([teacher, student])
        db.session.flush()
        db.session.add(UserProfile(user_id=teacher.id, telegram_chat_id=44444, telegram_notifications_enabled=True))

        st_rec = Student(user_id=student.id, name='S Sub', is_active=True)
        db.session.add(st_rec)
        db.session.flush()

        assign = Assignment(
            created_by_id=teacher.id,
            title='HW 1',
            assignment_type='homework',
            deadline=utc_now() + timedelta(days=1)
        )
        db.session.add(assign)
        db.session.flush()

        sub = Submission(
            assignment_id=assign.assignment_id,
            student_id=st_rec.student_id,
            status='CHECKED',
            graded_at=utc_now()
        )
        db.session.add(sub)
        db.session.flush()

        row = TelegramDelivery(
            user_id=teacher.id,
            kind='review_queue',
            dedupe_key='test:graded:1',
            payload={'text': 'Check homework', 'submission_id': sub.submission_id},
            status='processing'
        )
        db.session.add(row)
        db.session.commit()

        is_valid, reason = validate_delivery_freshness(row)
        assert not is_valid
        assert reason == 'submission_already_graded'


def test_freshness_unconfirmed_family_tie(app):
    with app.app_context():
        parent = User(username='parent-fresh', role='parent')
        student = User(username='student-fresh', role='student')
        db.session.add_all([parent, student])
        db.session.flush()
        db.session.add(UserProfile(user_id=parent.id, telegram_chat_id=55555, telegram_notifications_enabled=True))

        # Tie is NOT confirmed
        tie = FamilyTie(parent_id=parent.id, student_id=student.id, is_confirmed=False)
        db.session.add(tie)
        db.session.commit()

        row = TelegramDelivery(
            user_id=parent.id,
            kind='news',
            dedupe_key='test:tie:1',
            payload={'text': 'Kid update', 'student_id': student.id},
            status='processing'
        )
        db.session.add(row)
        db.session.commit()

        is_valid, reason = validate_delivery_freshness(row)
        assert not is_valid
        assert reason == 'family tie unconfirmed or revoked'


def test_multi_teacher_relationship_scope(app):
    with app.app_context():
        t1 = User(username='teacher1', role='teacher')
        t2 = User(username='teacher2', role='teacher')
        u_stu_a = User(username='studentA', role='student')
        u_stu_b = User(username='studentB', role='student')
        db.session.add_all([t1, t2, u_stu_a, u_stu_b])
        db.session.flush()

        stu_a = Student(user_id=u_stu_a.id, name='Student A', is_active=True)
        stu_b = Student(user_id=u_stu_b.id, name='Student B', is_active=True, mentor_id=t1.id)
        db.session.add_all([stu_a, stu_b])
        db.session.flush()

        # Connect Student A to Teacher 1 via TeacherStudent
        db.session.add(TeacherStudent(teacher_id=t1.id, student_id=u_stu_a.id, status='active'))
        db.session.commit()

        t1_student_ids = _student_ids_for_context(t1, 'teacher')
        t2_student_ids = _student_ids_for_context(t2, 'teacher')

        assert stu_a.student_id in t1_student_ids
        assert stu_b.student_id in t1_student_ids
        assert stu_a.student_id not in t2_student_ids
        assert stu_b.student_id not in t2_student_ids


def test_teacher_review_cross_teacher_isolation(app):
    with app.app_context():
        t1 = User(username='teacher_math', role='tutor')
        t2 = User(username='teacher_cs', role='tutor')
        u_stu = User(username='shared_student', role='student')
        db.session.add_all([t1, t2, u_stu])
        db.session.flush()

        stu = Student(user_id=u_stu.id, name='Shared Student', is_active=True)
        db.session.add(stu)
        db.session.flush()

        # Both teachers teach this student
        db.session.add(TeacherStudent(teacher_id=t1.id, student_id=u_stu.id, status='active'))
        db.session.add(TeacherStudent(teacher_id=t2.id, student_id=u_stu.id, status='active'))
        db.session.flush()

        # Math assignment and CS assignment
        a_math = Assignment(created_by_id=t1.id, title='Math HW', assignment_type='homework', deadline=utc_now() + timedelta(days=1), is_active=True)
        a_cs = Assignment(created_by_id=t2.id, title='CS HW', assignment_type='homework', deadline=utc_now() + timedelta(days=1), is_active=True)
        db.session.add_all([a_math, a_cs])
        db.session.flush()

        sub_math = Submission(assignment_id=a_math.assignment_id, student_id=stu.student_id, status='SUBMITTED')
        sub_cs = Submission(assignment_id=a_cs.assignment_id, student_id=stu.student_id, status='SUBMITTED')
        db.session.add_all([sub_math, sub_cs])
        db.session.commit()

        # Math teacher can review math HW, but NOT CS HW
        assert can_teacher_review_submission(t1, sub_math.submission_id) is True
        assert can_teacher_review_submission(t1, sub_cs.submission_id) is False

        # CS teacher can review CS HW, but NOT Math HW
        assert can_teacher_review_submission(t2, sub_cs.submission_id) is True
        assert can_teacher_review_submission(t2, sub_math.submission_id) is False

        # Review queries are properly isolated
        t1_review_subs = [row[0].submission_id for row in _build_teacher_review_query(t1).all()]
        t2_review_subs = [row[0].submission_id for row in _build_teacher_review_query(t2).all()]

        assert sub_math.submission_id in t1_review_subs
        assert sub_cs.submission_id not in t1_review_subs

        assert sub_cs.submission_id in t2_review_subs
        assert sub_math.submission_id not in t2_review_subs


def test_in_bot_callbacks_length_and_structure(app):
    with app.app_context():
        # Test templates with in-bot actions
        kinds_to_test = [
            ("lesson_scheduled", {"lesson_id": 12345}),
            ("submission_submitted", {"submission_id": 67890}),
            ("submission_checked", {"submission_id": 67890}),
        ]

        for kind, meta in kinds_to_test:
            text, reply_markup = render_telegram_notification(
                user_id=1,
                kind=kind,
                title="Заголовок",
                body="Текст сообщения",
                link_url="http://127.0.0.1:5000/test",
                meta=meta
            )
            assert text
            assert reply_markup
            keyboard = reply_markup.get("inline_keyboard", [])
            for row in keyboard:
                for btn in row:
                    cb = btn.get("callback_data")
                    if cb:
                        # Telegram strict callback_data limit is 64 bytes
                        assert len(cb.encode("utf-8")) <= 64, f"Callback {cb} exceeds 64 bytes"


from app.telegram.v3.router import handle_v3_callback
import asyncio


class _MockMessage:
    def __init__(self):
        self.edits = []

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None, **kwargs):
        self.edits.append({"text": text, "reply_markup": reply_markup, "parse_mode": parse_mode})


class _MockCallbackQuery:
    def __init__(self, data=""):
        self.data = data
        self.message = _MockMessage()
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append({"text": text, "show_alert": show_alert})

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None, **kwargs):
        self.message.edits.append({"text": text, "reply_markup": reply_markup, "parse_mode": parse_mode})


class _MockUpdate:
    def __init__(self, chat_id=123, callback_data=""):
        self.effective_chat = type("Chat", (), {"id": chat_id})()
        self.effective_user = type("User", (), {"id": chat_id, "username": f"user_{chat_id}", "first_name": "Test", "last_name": "User"})()
        self.callback_query = _MockCallbackQuery(data=callback_data)
        self.message = None


def test_router_handles_missing_item_gracefully(app):
    with app.app_context():
        from app.models import UserRole
        user = User(username='router-test-user', role='teacher')
        db.session.add(user)
        db.session.flush()
        db.session.add(UserProfile(user_id=user.id, telegram_chat_id=987654))
        db.session.add(UserRole(user_id=user.id, role='teacher'))
        db.session.add(UserRole(user_id=user.id, role='student'))
        db.session.commit()

        mock_context = type("MockContext", (), {"user_data": {}})()

        # Non-existent queue item callback
        upd_tch = _MockUpdate(chat_id=987654, callback_data="v3:tch:q_item:999999")
        asyncio.run(handle_v3_callback(upd_tch, mock_context))
        assert len(upd_tch.callback_query.message.edits) > 0
        edit_text = upd_tch.callback_query.message.edits[-1]["text"].lower()
        assert "не найдена" in edit_text or "не найден" in edit_text

        # Non-existent student HW item callback
        upd_stu = _MockUpdate(chat_id=987654, callback_data="v3:stu:hw_item:999999")
        asyncio.run(handle_v3_callback(upd_stu, mock_context))
        assert len(upd_stu.callback_query.message.edits) > 0
        edit_text_stu = upd_stu.callback_query.message.edits[-1]["text"].lower()
        assert "не найден" in edit_text_stu or "не найдена" in edit_text_stu
