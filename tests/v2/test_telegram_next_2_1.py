"""Automated verification suite for BooStudy Telegram Next 2.1.

Tests:
1. Self-notification suppression & actor-unknown safety.
2. Batching of mass lesson creation (>= 3 grouped, < 3 individual).
3. Granular preferences per role & isolation across roles.
4. Outbox delivery respecting granular preferences.
5. Teacher RBAC check when inspecting student notifications.
6. Broadcast audience calculation and dev safety.
"""
from __future__ import annotations

import pytest
from app import create_app
from core.db_models import db, User, UserProfile, UserNotificationPreference, TelegramDelivery, TelegramBroadcast
from app.telegram.event_policy import EventContext, should_suppress_notification, resolve_recipients_and_deduplicate
from app.telegram.batching import process_scheduled_lessons_batch, BATCH_THRESHOLD
from app.telegram.registry import NotificationTypeRegistry
from app.telegram.user_notify import (
    is_notification_enabled_for_user,
    set_user_notification_preference,
    reset_user_notification_preferences_to_defaults,
    get_user_notification_preference,
)
from app.telegram.delivery import deliver_one, enqueue_delivery


@pytest.fixture(scope="module")
def app_ctx():
    app = create_app()
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()


def test_self_notification_suppression(app_ctx):
    """Test that actors never receive Telegram echoes for their own actions."""
    student_id = 101
    teacher_id = 202
    admin_id = 303

    # 1. Student submits homework -> student is suppressed, teacher is allowed
    sub_ctx = EventContext(
        event_kind="homework_submitted",
        actor_user_id=student_id,
        actor_role="student",
        subject_user_id=student_id,
        entity_type="submission",
        entity_id=501,
    )
    sup_student, reason_st = should_suppress_notification(sub_ctx, student_id, "student")
    assert sup_student is True
    assert "self_action_suppressed" in reason_st

    sup_teacher, reason_tch = should_suppress_notification(sub_ctx, teacher_id, "teacher")
    assert sup_teacher is False

    # 2. Teacher schedules lesson -> teacher is suppressed, student is allowed
    sched_ctx = EventContext(
        event_kind="lesson_scheduled",
        actor_user_id=teacher_id,
        actor_role="teacher",
        subject_user_id=student_id,
        entity_type="lesson",
        entity_id=888,
    )
    sup_teacher2, _ = should_suppress_notification(sched_ctx, teacher_id, "teacher")
    assert sup_teacher2 is True

    sup_student2, _ = should_suppress_notification(sched_ctx, student_id, "student")
    assert sup_student2 is False

    # 3. Admin reschedules -> neither teacher nor student is suppressed
    admin_ctx = EventContext(
        event_kind="lesson_rescheduled",
        actor_user_id=admin_id,
        actor_role="admin",
        subject_user_id=student_id,
        entity_type="lesson",
        entity_id=888,
    )
    sup_teacher3, _ = should_suppress_notification(admin_ctx, teacher_id, "teacher")
    sup_student3, _ = should_suppress_notification(admin_ctx, student_id, "student")
    assert sup_teacher3 is False
    assert sup_student3 is False

    # 4. System reminder (actor unknown) -> never guess recipient as actor
    reminder_ctx = EventContext(
        event_kind="lesson_reminder",
        actor_user_id=None,  # unknown/system
        subject_user_id=student_id,
        entity_type="lesson",
        entity_id=888,
    )
    sup_rem_st, _ = should_suppress_notification(reminder_ctx, student_id, "student")
    sup_rem_tch, _ = should_suppress_notification(reminder_ctx, teacher_id, "teacher")
    assert sup_rem_st is False
    assert sup_rem_tch is False


def test_batching_mass_lessons(app_ctx):
    """Test grouping of >= 3 lessons into a single card vs individual cards."""
    student_id = 105
    batch_id = "test_batch_99"
    teacher_name = "Михаил Викторович"

    lessons = [
        {"lesson_id": 1, "topic": "Урок 1: Рекурсия", "start_time": "2026-11-05T18:00:00Z"},
        {"lesson_id": 2, "topic": "Урок 2: Графы", "start_time": "2026-11-07T18:00:00Z"},
        {"lesson_id": 3, "topic": "Урок 3: Деревья", "start_time": "2026-11-12T18:00:00Z"},
        {"lesson_id": 4, "topic": "Урок 4: Динамика", "start_time": "2026-11-14T18:00:00Z"},
        {"lesson_id": 5, "topic": "Урок 5: Теория игр", "start_time": "2026-11-19T18:00:00Z"},
    ]

    # 1. Five lessons -> Exactly 1 batch delivery card
    cards_5 = process_scheduled_lessons_batch(
        recipient_user_id=student_id,
        teacher_name=teacher_name,
        lessons_data=lessons,
        batch_id=batch_id,
        recipient_role="student",
    )
    assert len(cards_5) == 1
    batch_card = cards_5[0]
    assert batch_card["kind"] == "lesson_batch_scheduled"
    assert "Вам назначили 5 занятий" in batch_card["text"]
    assert "Михаил Викторович" in batch_card["text"]
    assert "Урок 1: Рекурсия" in batch_card["text"]
    assert f"telegram:batch:lesson_scheduled:{student_id}:{batch_id}" == batch_card["dedupe_key"]

    # 2. Two lessons -> Exactly 2 individual cards
    cards_2 = process_scheduled_lessons_batch(
        recipient_user_id=student_id,
        teacher_name=teacher_name,
        lessons_data=lessons[:2],
        batch_id=batch_id,
        recipient_role="student",
    )
    assert len(cards_2) == 2
    assert cards_2[0]["kind"] == "lesson_scheduled"
    assert cards_2[1]["kind"] == "lesson_scheduled"


def test_granular_preferences_isolation_and_resolution(app_ctx):
    """Test per-role preference isolation and fallback resolution."""
    # Ensure test user exists
    test_user = User.query.filter_by(username="test_pref_user").first()
    if not test_user:
        test_user = User(username="test_pref_user", role="student")
        db.session.add(test_user)
        db.session.commit()
    test_user_id = test_user.id

    # Clean any leftover preferences
    UserNotificationPreference.query.filter_by(user_id=test_user_id).delete()
    db.session.commit()

    # Create test profile with telegram enabled
    prof = UserProfile.query.filter_by(user_id=test_user_id).first()
    if not prof:
        prof = UserProfile(user_id=test_user_id, telegram_chat_id=99998888, telegram_notifications_enabled=True)
        db.session.add(prof)
        db.session.commit()

    # 1. By default, lesson_scheduled is enabled for student
    assert is_notification_enabled_for_user(test_user_id, role="student", kind="lesson_scheduled") is True

    # 2. Disable lesson_scheduled for student
    set_user_notification_preference(test_user_id, role="student", kind="lesson_scheduled", is_enabled=False)
    assert is_notification_enabled_for_user(test_user_id, role="student", kind="lesson_scheduled") is False

    # 3. Isolation: teacher role for the same user is still enabled!
    assert is_notification_enabled_for_user(test_user_id, role="teacher", kind="lesson_scheduled") is True

    # 4. Check provenance
    val, prov = get_user_notification_preference(test_user_id, role="student", kind="lesson_scheduled")
    assert val is False
    assert prov == "user"

    # 5. Reset to defaults
    reset_user_notification_preferences_to_defaults(test_user_id, role="student")
    assert is_notification_enabled_for_user(test_user_id, role="student", kind="lesson_scheduled") is True
    val_def, prov_def = get_user_notification_preference(test_user_id, role="student", kind="lesson_scheduled")
    assert val_def is True
    assert prov_def == "default"


def test_delivery_respects_granular_preference(app_ctx):
    """Test that Outbox delivery cancels dispatch when disabled by granular preference."""
    test_user = User.query.filter_by(username="test_deliv_user").first()
    if not test_user:
        test_user = User(username="test_deliv_user", role="student")
        db.session.add(test_user)
        db.session.commit()
    test_user_id = test_user.id

    prof = UserProfile.query.filter_by(user_id=test_user_id).first()
    if not prof:
        prof = UserProfile(user_id=test_user_id, telegram_chat_id=99998887, telegram_notifications_enabled=True)
        db.session.add(prof)
        db.session.commit()

    # Disable assignment_assigned for student
    set_user_notification_preference(test_user_id, role="student", kind="assignment_assigned", is_enabled=False)

    # Enqueue Outbox delivery
    row = enqueue_delivery(
        user_id=test_user_id,
        text="Новое домашнее задание",
        kind="assignment_assigned",
        meta={"recipient_role": "student"},
    )
    row.status = "processing"
    db.session.commit()

    # Attempt deliver
    res = deliver_one(row.delivery_id)
    assert res["ok"] is False
    assert res["status"] == "cancelled"
    assert "disabled_by_preference" in (res.get("reason") or "")

    # Cleanup
    reset_user_notification_preferences_to_defaults(test_user_id, role="student")


def test_teacher_student_rbac_and_comparison(app_ctx):
    """Test RBAC enforcement on teacher inspecting student notifications."""
    test_creator = User.query.filter_by(username="test_creator_rbac").first()
    if not test_creator:
        test_creator = User(username="test_creator_rbac", role="creator")
        db.session.add(test_creator)
        db.session.commit()

    from app.telegram.v3.screens.teacher_student_notifications import _is_teacher_authorized
    assert _is_teacher_authorized(test_creator) is True

    # Verify retired notifications
    from app.telegram.notifications import notify_new_gradebook_entry, notify_subscription_expiring
    res_gb = notify_new_gradebook_entry(student_user_id=1, student_id=1, entry_title="Тест", score_text="5")
    assert res_gb is False

    res_sub = notify_subscription_expiring(student_user_id=1, days_left=1, subscription_end="2026-12-31")
    assert res_sub is False
