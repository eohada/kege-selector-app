"""Regression and closure verification suite for BooStudy Telegram Next 2.1.

Verifies:
1. Achievement kind alignment ('achievement' <-> 'achievement_unlocked'),
   in-app notification delivery, and granular preference toggling.
2. Lesson balance threshold crossings (low_lessons <= 2, package_exhausted == 0),
   preventing duplicate spam on re-saving, and independent in-app bell preservation.
3. Celery Beat background periodic tasks:
   - 30-min lesson reminders (telegram_lesson_reminders_task)
   - 24h deadline reminders (telegram_deadline_reminders_task)
   - Invalidation of outdated reminders on reschedule/cancel
   - Antispam and suppression when personal Telegram settings are disabled.
"""
from __future__ import annotations

import uuid
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
    UserNotification,
    UserNotificationPreference,
    SubmissionTelegramDeadlineSent,
    utc_now,
    MOSCOW_TZ,
)
from app.telegram.registry import NotificationTypeRegistry
from app.telegram.user_notify import (
    is_notification_enabled_for_user,
    set_user_notification_preference,
    normalize_notification_kind,
    _KIND_TO_ATTR,
)
from app.telegram.delivery import enqueue_delivery, invalidate_pending_lesson_deliveries
from app.telegram.notifications import notify_lesson_balance_changed
from app.utils.achievement_service import grant_achievement, ACHIEVEMENTS_REGISTRY
from app.tasks.telegram_lesson_reminders import telegram_lesson_reminders_task
from app.tasks.telegram_deadlines import telegram_deadline_reminders_task


def _create_unique_student_user(role="student"):
    db.create_all()
    suffix = uuid.uuid4().hex[:6]
    user = User(
        username=f"student_reg_{suffix}",
        email=f"student_reg_{suffix}@test.local",
        role=role,
        is_active=True,
    )
    db.session.add(user)
    db.session.flush()

    prof = UserProfile(
        user_id=user.id,
        telegram_chat_id=int(datetime.now().timestamp() * 100) % 100000000 + 10,
        telegram_notifications_enabled=True,
    )
    db.session.add(prof)

    student = Student(
        name=f"Ученик Регрессионный {suffix}",
        user_id=user.id,
        is_active=True,
    )
    db.session.add(student)
    db.session.commit()
    return user, student, prof


def test_achievement_event_kind_and_preference_alignment(app):
    """Test alignment between 'achievement' and 'achievement_unlocked' in registry, preferences, and delivery."""
    with app.app_context():
        # 1. Registry & Aliases check
        ach_def = NotificationTypeRegistry.get("achievement")
        ach_unlocked_def = NotificationTypeRegistry.get("achievement_unlocked")
        assert ach_def is not None, "NotificationTypeDefinition for 'achievement' must exist"
        assert ach_unlocked_def is not None, "NotificationTypeDefinition for 'achievement_unlocked' must resolve via alias"
        assert ach_def.kind == ach_unlocked_def.kind == "achievement"
        assert NotificationTypeRegistry.is_default_enabled("achievement_unlocked", "student") is True
        assert normalize_notification_kind("achievement_unlocked") == "achievement"
        assert _KIND_TO_ATTR.get("achievement_unlocked") == "tg_notify_news"

        # 2. Real achievement granting creates Outbox delivery and in-app UserNotification
        user, student, prof = _create_unique_student_user()
        ach_key = "ide_run_shortcut"

        granted = grant_achievement(student, ach_key, commit=True)
        assert granted is True

        in_app_notif = UserNotification.query.filter_by(user_id=user.id, kind="achievement").all()
        assert len(in_app_notif) >= 1, "In-app UserNotification must be created for achievement"

        tg_deliv = TelegramDelivery.query.filter_by(user_id=user.id, kind="achievement").all()
        assert len(tg_deliv) >= 1, "TelegramDelivery in Outbox must be created for achievement"

        # 3. Suppress Telegram preference -> in-app remains, TelegramDelivery suppressed
        set_user_notification_preference(user.id, "student", "achievement", False)
        assert is_notification_enabled_for_user(user.id, "student", "achievement") is False
        assert is_notification_enabled_for_user(user.id, "student", "achievement_unlocked") is False

        TelegramDelivery.query.filter_by(user_id=user.id).delete()
        UserNotification.query.filter_by(user_id=user.id).delete()
        db.session.commit()

        ach_key2 = "ide_copy_code"
        granted2 = grant_achievement(student, ach_key2, commit=True)
        assert granted2 is True

        in_app2 = UserNotification.query.filter_by(user_id=user.id, kind="achievement").all()
        tg_deliv2 = TelegramDelivery.query.filter_by(user_id=user.id, kind="achievement").all()
        assert len(in_app2) >= 1, "In-app bell notification MUST still be created when Telegram is disabled!"
        assert len(tg_deliv2) == 0, "Telegram delivery MUST be suppressed by personal preference!"

        # 4. Enabling via alias works seamlessly
        set_user_notification_preference(user.id, "student", "achievement_unlocked", True)
        assert is_notification_enabled_for_user(user.id, "student", "achievement") is True


def test_lesson_balance_threshold_crossings_and_dedup(app):
    """Test that low_lessons and package_exhausted are triggered strictly on threshold crossing, without duplicate spam."""
    with app.app_context():
        user, student, prof = _create_unique_student_user()
        uid = user.id

        # Clear initial deliveries
        TelegramDelivery.query.filter_by(user_id=uid).delete()
        UserNotification.query.filter_by(user_id=uid).delete()
        db.session.commit()

        # Step 1: Normal deduction above threshold (10 -> 9). Neither low_lessons nor package_exhausted.
        ok = notify_lesson_balance_changed(student_user_id=uid, before=10, after=9, reason="Списание за урок")
        assert ok is True
        delivs = TelegramDelivery.query.filter_by(user_id=uid).all()
        assert len(delivs) == 1
        assert delivs[0].kind == "lesson_balance_changed"

        # Step 2: Deduction crossing low_lessons threshold (3 -> 2).
        # Must create lesson_balance_changed AND low_lessons warning.
        TelegramDelivery.query.filter_by(user_id=uid).delete()
        db.session.commit()
        ok = notify_lesson_balance_changed(student_user_id=uid, before=3, after=2, reason="Списание за урок")
        assert ok is True
        kinds = [d.kind for d in TelegramDelivery.query.filter_by(user_id=uid).all()]
        assert "lesson_balance_changed" in kinds
        assert "low_lessons" in kinds
        assert "package_exhausted" not in kinds

        # Step 3: Re-saving state with unchanged balance (2 -> 2).
        # Must return False immediately without generating any notifications or Outbox entries.
        TelegramDelivery.query.filter_by(user_id=uid).delete()
        db.session.commit()
        ok_resave = notify_lesson_balance_changed(student_user_id=uid, before=2, after=2, reason="Повторное сохранение")
        assert ok_resave is False
        assert len(TelegramDelivery.query.filter_by(user_id=uid).all()) == 0

        # Step 4: Deduction while already in low state (2 -> 1).
        # Must notify balance change, but must NOT duplicate low_lessons alert!
        ok = notify_lesson_balance_changed(student_user_id=uid, before=2, after=1, reason="Списание за урок")
        assert ok is True
        kinds = [d.kind for d in TelegramDelivery.query.filter_by(user_id=uid).all()]
        assert kinds == ["lesson_balance_changed"]

        # Step 5: Deduction crossing to zero (1 -> 0).
        # Must create lesson_balance_changed AND package_exhausted warning.
        TelegramDelivery.query.filter_by(user_id=uid).delete()
        db.session.commit()
        ok = notify_lesson_balance_changed(student_user_id=uid, before=1, after=0, reason="Списание за урок")
        assert ok is True
        kinds = [d.kind for d in TelegramDelivery.query.filter_by(user_id=uid).all()]
        assert "lesson_balance_changed" in kinds
        assert "package_exhausted" in kinds
        assert "low_lessons" not in kinds

        # Step 6: Re-saving state at zero (0 -> 0).
        # Must return False immediately without duplicate alerts.
        TelegramDelivery.query.filter_by(user_id=uid).delete()
        db.session.commit()
        assert notify_lesson_balance_changed(student_user_id=uid, before=0, after=0) is False
        assert len(TelegramDelivery.query.filter_by(user_id=uid).all()) == 0

        # Step 7: Top-up from 0 to 5 (diff > 0).
        # Must notify balance change, but diff > 0 must never trigger package_exhausted or low_lessons.
        ok = notify_lesson_balance_changed(student_user_id=uid, before=0, after=5, reason="Пополнение баланса")
        assert ok is True
        kinds = [d.kind for d in TelegramDelivery.query.filter_by(user_id=uid).all()]
        assert kinds == ["lesson_balance_changed"]

        # Step 8: Disabling Telegram preference suppresses Outbox but preserves in-app UserNotification bell
        set_user_notification_preference(uid, "student", "lesson_balance_changed", False)
        TelegramDelivery.query.filter_by(user_id=uid).delete()
        UserNotification.query.filter_by(user_id=uid).delete()
        db.session.commit()

        ok = notify_lesson_balance_changed(student_user_id=uid, before=5, after=4, reason="Списание при отключенном TG")
        assert ok is True

        in_app = UserNotification.query.filter_by(user_id=uid, kind="lesson_balance_changed").all()
        tg_delivs = TelegramDelivery.query.filter_by(user_id=uid, kind="lesson_balance_changed").all()
        assert len(in_app) >= 1, "In-app bell notification must NEVER be suppressed by Telegram preferences!"
        assert len(tg_delivs) == 0, "TelegramDelivery must be suppressed by user's personal preference!"


def test_celery_beat_reminders_and_deadlines_execution(app):
    """Test that background Celery Beat tasks execute, respect settings, record dedup, and invalidate outdated items."""
    with app.app_context():
        user, student, prof = _create_unique_student_user()
        uid = user.id
        sid = student.student_id

        # ---------------------------------------------------------------------
        # 1. Lesson 30-min Reminder Periodic Task
        # ---------------------------------------------------------------------
        # Create a planned lesson starting exactly in 30 minutes (falls within [29m20s, 30m40s] window)
        now_utc = datetime.now(timezone.utc).replace(microsecond=0)
        lesson_time_utc = now_utc + timedelta(minutes=30)

        lesson = Lesson(
            student_id=sid,
            teacher_id=uid,
            lesson_date=lesson_time_utc,
            status="planned",
            topic="Информатика КЕГЭ: Рекурсия",
            tg_reminder_30min_sent=False,
        )
        db.session.add(lesson)
        db.session.commit()

        TelegramDelivery.query.filter_by(user_id=uid).delete()
        db.session.commit()

        # Run periodic task
        result = telegram_lesson_reminders_task.run()
        assert result.get("ok") is True
        assert result.get("sent", 0) >= 1

        db.session.refresh(lesson)
        assert lesson.tg_reminder_30min_sent is True, "Lesson reminder flag must be marked True"

        # Check Outbox delivery
        rem_deliv = TelegramDelivery.query.filter_by(user_id=uid, kind="lesson_reminder").all()
        assert len(rem_deliv) >= 1, "Telegram delivery for lesson_reminder must be enqueued"

        # Antispam verification: running task again should not re-send
        result_repeat = telegram_lesson_reminders_task.run()
        assert result_repeat.get("ok") is True
        assert result_repeat.get("sent") == 0, "Re-running reminder task must send 0 due to dedup flag"

        # ---------------------------------------------------------------------
        # 2. Reschedule & Cancellation Invalidation
        # ---------------------------------------------------------------------
        # Enqueue a pending reminder for this lesson
        pending_rem = enqueue_delivery(
            uid,
            "Напоминание о предстоящем занятии",
            kind="lesson_reminder",
            lesson_id=lesson.lesson_id,
        )
        db.session.commit()
        assert pending_rem.status == "pending"

        # Simulate lesson reschedule/cancellation invalidation
        inv_count = invalidate_pending_lesson_deliveries(lesson.lesson_id, reason="lesson_rescheduled")
        assert inv_count >= 1

        db.session.refresh(pending_rem)
        assert pending_rem.status == "cancelled"
        assert "invalidated: lesson_rescheduled" in (pending_rem.last_error or "")

        # ---------------------------------------------------------------------
        # 3. Deadline 24h Reminder Periodic Task
        # ---------------------------------------------------------------------
        now_msk = utc_now().astimezone(MOSCOW_TZ)
        deadline = now_msk + timedelta(hours=24)
        assignment = Assignment(
            title="Домашнее задание: Теория графов",
            assignment_type="homework",
            created_by_id=uid,
            deadline=deadline,
            is_active=True,
        )
        db.session.add(assignment)
        db.session.flush()

        submission = Submission(
            assignment_id=assignment.assignment_id,
            student_id=sid,
            status="IN_PROGRESS",
        )
        db.session.add(submission)
        db.session.commit()

        TelegramDelivery.query.filter_by(user_id=uid).delete()
        db.session.commit()

        # Run deadline reminders task
        dl_res = telegram_deadline_reminders_task.run()
        assert dl_res.get("ok") is True
        assert dl_res.get("sent", 0) >= 1

        # Check SubmissionTelegramDeadlineSent antispam marker
        sent_record = SubmissionTelegramDeadlineSent.query.filter_by(
            submission_id=submission.submission_id,
            window_key="24h",
        ).first()
        assert sent_record is not None, "SubmissionTelegramDeadlineSent record must be persisted"

        # Check Outbox delivery
        dl_deliv = TelegramDelivery.query.filter_by(user_id=uid, kind="assignment_deadline").all()
        assert len(dl_deliv) >= 1, "Telegram delivery for assignment_deadline must be enqueued"

        # Repeat run must not send duplicate
        dl_repeat = telegram_deadline_reminders_task.run()
        assert dl_repeat.get("ok") is True
        assert dl_repeat.get("sent") == 0, "Repeated deadline scan must send 0 due to antispam table"

        # ---------------------------------------------------------------------
        # 4. Suppression when user opts out in Telegram preferences
        # ---------------------------------------------------------------------
        set_user_notification_preference(uid, "student", "lesson_reminder", False)
        TelegramDelivery.query.filter_by(user_id=uid).delete()
        db.session.commit()

        lesson2 = Lesson(
            student_id=sid,
            teacher_id=uid,
            lesson_date=now_utc + timedelta(minutes=30),
            status="planned",
            topic="Урок при отключенных напоминаниях",
            tg_reminder_30min_sent=False,
        )
        db.session.add(lesson2)
        db.session.commit()

        res2 = telegram_lesson_reminders_task.run()
        assert res2.get("ok") is True
        # Delivery must be suppressed
        tg_rem2 = TelegramDelivery.query.filter_by(user_id=uid, kind="lesson_reminder").all()
        assert len(tg_rem2) == 0, "Lesson reminder delivery must be suppressed when user preference is disabled"
