"""Comprehensive end-to-end acceptance test suite for BooStudy Telegram Next 2.1.

Verifies:
1. Scenario A: Student submits homework via real submission route -> teacher notified, student self-suppressed, parent notified, other teachers isolated.
2. Scenario B: Teacher grades submission via real grade save route -> student notified, teacher self-suppressed, parent notified (tie/pref enforced).
3. Scenario C: Teacher schedules single lesson via real schedule route -> student notified, teacher self-suppressed.
4. Scenario D: Admin reschedules lesson -> old reminders invalidated, student & teacher notified, admin self-suppressed.
5. Scenario Cancellation: Teacher cancels lesson -> old reminders invalidated, student notified, teacher self-suppressed.
6. Mass Lesson Batching Threshold: 1 lesson (1 card), 2 lessons (2 cards), 5 lessons (1 grouped card, parent gets child context).
7. In-App Notification vs Telegram Independence: Disabling Telegram preferences NEVER breaks in-platform UserNotification.
8. Broadcast Center: Wizard execution, DB campaign persistence, Outbox enqueuing, and history screen auditing.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import pytest
from flask import g

from app import db
from core.db_models import (
    User,
    UserProfile,
    Student,
    FamilyTie,
    Lesson,
    Assignment,
    Submission,
    TelegramDelivery,
    UserNotification,
    TelegramBroadcast,
    UserNotificationPreference,
    utc_now,
)
from app.telegram.delivery import enqueue_delivery
from app.schedule.routes import notify_scheduled_lessons_batch, _notify_lesson_scheduled
from app.telegram.user_notify import is_notification_enabled_for_user, set_user_notification_preference
from app.telegram.v3.screens.broadcast import (
    execute_broadcast_send,
    show_broadcast_history,
    _DRAFTS,
)


def _login(client, user_id: int, role: str) -> None:
    try:
        g.pop('_login_user', None)
    except Exception:
        pass
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True
        sess['sandbox_role'] = role


@pytest.fixture
def e2e_users(app):
    """Seed clean set of users: teacher, student, parent, admin, and a foreign teacher."""
    with app.app_context():
        # Clean previous test records
        TelegramDelivery.query.delete()
        UserNotification.query.delete()
        TelegramBroadcast.query.delete()
        UserNotificationPreference.query.delete()
        db.session.commit()

        suffix = f"_{int(datetime.now().timestamp() * 1000) % 100000}"

        teacher = User(username=f"t_e2e{suffix}", role="teacher")
        foreign_teacher = User(username=f"t_other{suffix}", role="teacher")
        student_u = User(username=f"st_e2e{suffix}", role="student")
        parent_u = User(username=f"p_e2e{suffix}", role="parent")
        admin_u = User(username=f"adm_e2e{suffix}", role="admin")

        db.session.add_all([teacher, foreign_teacher, student_u, parent_u, admin_u])
        db.session.flush()

        t_id = teacher.id
        ft_id = foreign_teacher.id
        st_uid = student_u.id
        p_id = parent_u.id
        adm_id = admin_u.id

        # Profiles with telegram chat IDs
        t_prof = UserProfile(user_id=t_id, telegram_chat_id=1110001, telegram_notifications_enabled=True)
        ft_prof = UserProfile(user_id=ft_id, telegram_chat_id=1110002, telegram_notifications_enabled=True)
        st_prof = UserProfile(user_id=st_uid, telegram_chat_id=1110003, telegram_notifications_enabled=True)
        p_prof = UserProfile(user_id=p_id, telegram_chat_id=1110004, telegram_notifications_enabled=True)
        adm_prof = UserProfile(user_id=adm_id, telegram_chat_id=1110005, telegram_notifications_enabled=True)

        db.session.add_all([t_prof, ft_prof, st_prof, p_prof, adm_prof])
        db.session.flush()

        # Student entity with mentor_id=t_id for RBAC scheduling ownership
        st_name = f"Иван Тестов{suffix}"
        student = Student(name=st_name, user_id=st_uid, mentor_id=t_id)
        db.session.add(student)
        db.session.flush()
        st_id = student.student_id

        # Confirmed FamilyTie
        tie = FamilyTie(parent_id=p_id, student_id=st_uid, is_confirmed=True)
        db.session.add(tie)
        db.session.commit()

        return {
            "teacher_id": t_id,
            "foreign_teacher_id": ft_id,
            "student_user_id": st_uid,
            "student_id": st_id,
            "student_name": st_name,
            "parent_id": p_id,
            "admin_id": adm_id,
        }


# =========================================================================
# 1. SCENARIO A: Student submits HW via real route
# =========================================================================
def test_scenario_a_student_submits_homework_real_route(app, client, e2e_users):
    """Scenario A:
    Student submits work -> Teacher gets Outbox notification,
    Student self-suppressed, Parent gets child notification, foreign teacher gets nothing.
    """
    teacher_id = e2e_users["teacher_id"]
    student_id = e2e_users["student_id"]
    student_uid = e2e_users["student_user_id"]
    parent_id = e2e_users["parent_id"]
    foreign_teacher_id = e2e_users["foreign_teacher_id"]

    with app.app_context():
        assignment = Assignment(
            title="Домашнее задание №1 (ЕГЭ)",
            created_by_id=teacher_id,
            deadline=utc_now() + timedelta(days=7),
            assignment_type="homework",
        )
        db.session.add(assignment)
        db.session.flush()

        submission = Submission(
            assignment_id=assignment.assignment_id,
            student_id=student_id,
            status="IN_PROGRESS",
        )
        db.session.add(submission)
        db.session.commit()
        sub_id = submission.submission_id

    # Student submits via real endpoint
    _login(client, student_uid, "student")
    resp = client.post(f"/submissions/{sub_id}/submit", json={"auto_finish": True})
    assert resp.status_code in (200, 302)

    with app.app_context():
        deliveries = TelegramDelivery.query.all()
        teacher_delivs = [d for d in deliveries if d.user_id == teacher_id]
        student_delivs = [d for d in deliveries if d.user_id == student_uid]
        parent_delivs = [d for d in deliveries if d.user_id == parent_id]
        foreign_delivs = [d for d in deliveries if d.user_id == foreign_teacher_id]

        # 1. Teacher received homework submission notification
        assert len(teacher_delivs) >= 1
        assert any(d.kind == "teacher_homework_submitted" for d in teacher_delivs)
        t_card = next(d for d in teacher_delivs if d.kind == "teacher_homework_submitted")
        t_text = t_card.payload.get("text", "")
        assert "сдал" in t_text or "Домашнее задание" in t_text

        # 2. Student self-action suppressed: student does NOT receive teacher_homework_submitted
        assert not any(d.kind == "teacher_homework_submitted" for d in student_delivs)

        # 3. Parent received homework_submitted
        assert len(parent_delivs) >= 1
        assert any(d.kind == "homework_submitted" for d in parent_delivs)

        # 4. Foreign teacher received 0 leakage
        assert len(foreign_delivs) == 0


# =========================================================================
# 2. SCENARIO B: Teacher grades submission via real route
# =========================================================================
def test_scenario_b_teacher_grades_submission_real_route(app, client, e2e_users):
    """Scenario B:
    Teacher grades work -> Student gets Outbox score notification,
    Teacher self-suppressed, Parent gets notification.
    """
    teacher_id = e2e_users["teacher_id"]
    student_id = e2e_users["student_id"]
    student_uid = e2e_users["student_user_id"]
    parent_id = e2e_users["parent_id"]

    with app.app_context():
        assignment = Assignment(
            title="Контрольная работа №2",
            created_by_id=teacher_id,
            deadline=utc_now() + timedelta(days=7),
            assignment_type="homework",
        )
        db.session.add(assignment)
        db.session.flush()

        submission = Submission(
            assignment_id=assignment.assignment_id,
            student_id=student_id,
            status="SUBMITTED",
        )
        db.session.add(submission)
        db.session.commit()
        sub_id = submission.submission_id

    # Teacher grades via real endpoint
    _login(client, teacher_id, "teacher")
    resp = client.post(f"/submissions/{sub_id}/grade", json={
        "status": "GRADED",
        "teacher_feedback": "Отличная работа, все прототипы решены верно!",
        "publish": True,
    })
    assert resp.status_code in (200, 302)

    with app.app_context():
        deliveries = TelegramDelivery.query.all()
        student_delivs = [d for d in deliveries if d.user_id == student_uid and d.kind == "assignment_graded"]
        teacher_delivs = [d for d in deliveries if d.user_id == teacher_id and d.kind == "assignment_graded"]
        parent_delivs = [d for d in deliveries if d.user_id == parent_id and d.kind == "assignment_graded"]

        # 1. Student received assignment_graded Outbox card
        assert len(student_delivs) >= 1
        st_text = student_delivs[0].payload.get("text", "")
        assert "Отличная работа" in st_text or "Работа проверена" in st_text

        # 2. Teacher self-action suppressed
        assert len(teacher_delivs) == 0

        # 3. Parent received assignment_graded Outbox card
        assert len(parent_delivs) >= 1


# =========================================================================
# 3. SCENARIO C: Teacher schedules single lesson via real route
# =========================================================================
def test_scenario_c_teacher_schedules_single_lesson_real_route(app, client, e2e_users):
    """Scenario C:
    Teacher schedules 1 lesson -> Student receives lesson_scheduled Outbox card,
    Teacher self-suppressed.
    """
    teacher_id = e2e_users["teacher_id"]
    student_id = e2e_users["student_id"]
    student_uid = e2e_users["student_user_id"]

    _login(client, teacher_id, "teacher")
    lesson_dt = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d 16:00")
    resp = client.post("/api/schedule/create_lesson", json={
        "student_id": student_id,
        "date": lesson_dt.split()[0],
        "time": "16:00",
        "topic": "Теория графов и поиск путей",
        "duration": 60,
    })
    assert resp.status_code in (200, 201)

    with app.app_context():
        student_delivs = TelegramDelivery.query.filter_by(user_id=student_uid, kind="lesson_scheduled").all()
        teacher_delivs = TelegramDelivery.query.filter_by(user_id=teacher_id, kind="lesson_scheduled").all()

        # 1. Student gets lesson card
        assert len(student_delivs) >= 1
        st_text = student_delivs[0].payload.get("text", "")
        assert "Теория графов" in st_text or "Новый урок" in st_text

        # 2. Teacher self-suppressed: 0 cards
        assert len(teacher_delivs) == 0


# =========================================================================
# 4. SCENARIO D: Admin reschedules lesson -> Invalidation & delivery
# =========================================================================
def test_scenario_d_admin_reschedules_lesson_real_route(app, client, e2e_users):
    """Scenario D:
    Admin reschedules lesson -> Old pending reminders invalidated,
    Both Student and Teacher receive notification (Admin is actor, so Teacher not suppressed).
    """
    teacher_id = e2e_users["teacher_id"]
    student_id = e2e_users["student_id"]
    student_uid = e2e_users["student_user_id"]
    admin_id = e2e_users["admin_id"]

    with app.app_context():
        lesson = Lesson(
            student_id=student_id,
            teacher_id=teacher_id,
            lesson_date=utc_now() + timedelta(days=3),
            status="planned",
            topic="Динамическое программирование",
            duration=60,
        )
        db.session.add(lesson)
        db.session.flush()

        # Pending reminder before reschedule
        reminder = enqueue_delivery(
            student_uid,
            "Напоминание об уроке через 30 минут",
            kind="lesson_reminder",
            lesson_id=lesson.lesson_id,
        )
        db.session.commit()
        lesson_id = lesson.lesson_id
        reminder_id = reminder.delivery_id

    # Admin reschedules lesson via inline update
    _login(client, admin_id, "admin")
    new_day = (datetime.now() + timedelta(days=4)).strftime("%Y-%m-%d")
    resp = client.post(f"/schedule/api/lesson/{lesson_id}/update", json={
        "lesson_date": new_day,
        "lesson_time": "18:00",
    })
    assert resp.status_code == 200

    with app.app_context():
        # 1. Old reminder invalidated
        rem = db.session.get(TelegramDelivery, reminder_id)
        assert rem.status == "cancelled"
        assert "invalidated" in rem.last_error

        # 2. Student received rescheduled notification
        st_delivs = TelegramDelivery.query.filter_by(user_id=student_uid, kind="lesson_rescheduled").all()
        assert len(st_delivs) >= 1
        assert any("перенесён" in d.payload.get("text", "").lower() for d in st_delivs)

        # 3. Teacher received rescheduled notification (actor was Admin!)
        tch_delivs = TelegramDelivery.query.filter_by(user_id=teacher_id, kind="lesson_rescheduled").all()
        assert len(tch_delivs) >= 1
        assert any("перенесён" in d.payload.get("text", "").lower() for d in tch_delivs)

        # 4. Admin self-suppressed
        adm_delivs = TelegramDelivery.query.filter_by(user_id=admin_id, kind="lesson_rescheduled").all()
        assert len(adm_delivs) == 0


# =========================================================================
# 5. SCENARIO CANCELLATION: Teacher cancels lesson
# =========================================================================
def test_scenario_cancellation_teacher_cancels_lesson_real_route(app, client, e2e_users):
    """Cancellation:
    Teacher sets lesson status to cancelled -> pending reminders invalidated,
    Student receives cancellation card, Teacher self-suppressed.
    """
    teacher_id = e2e_users["teacher_id"]
    student_id = e2e_users["student_id"]
    student_uid = e2e_users["student_user_id"]

    with app.app_context():
        lesson = Lesson(
            student_id=student_id,
            teacher_id=teacher_id,
            lesson_date=utc_now() + timedelta(days=2),
            status="planned",
            topic="Рекурсивные алгоритмы",
            duration=60,
        )
        db.session.add(lesson)
        db.session.flush()

        reminder = enqueue_delivery(
            student_uid,
            "Напоминание об уроке",
            kind="lesson_reminder",
            lesson_id=lesson.lesson_id,
        )
        db.session.commit()
        lesson_id = lesson.lesson_id
        reminder_id = reminder.delivery_id

    # Teacher cancels lesson via set-status API
    _login(client, teacher_id, "teacher")
    resp = client.post(f"/schedule/api/lesson/{lesson_id}/set-status", json={"status": "cancelled"})
    assert resp.status_code == 200

    with app.app_context():
        # 1. Reminder invalidated
        rem = db.session.get(TelegramDelivery, reminder_id)
        assert rem.status == "cancelled"

        # 2. Student received lesson_cancelled
        st_delivs = TelegramDelivery.query.filter_by(user_id=student_uid, kind="lesson_cancelled").all()
        assert len(st_delivs) >= 1
        st_text = st_delivs[0].payload.get("text", "")
        assert "отменён" in st_text.lower()

        # 3. Teacher self-suppressed
        tch_delivs = TelegramDelivery.query.filter_by(user_id=teacher_id, kind="lesson_cancelled").all()
        assert len(tch_delivs) == 0


# =========================================================================
# 6. BATCHING THRESHOLD: 1, 2, 5 Lessons
# =========================================================================
def test_batching_threshold_mass_lesson_scheduling(app, e2e_users):
    """Batching threshold:
    1 lesson -> 1 individual card.
    2 lessons -> 2 individual cards.
    5 lessons -> exactly 1 grouped batch card (lesson_batch_scheduled), 5 individual cards suppressed.
    Parent grouped card contains child context.
    """
    teacher_id = e2e_users["teacher_id"]
    student_id = e2e_users["student_id"]
    student_uid = e2e_users["student_user_id"]
    parent_id = e2e_users["parent_id"]

    with app.app_context():
        student = db.session.get(Student, student_id)

        # A) Test 1 lesson
        TelegramDelivery.query.delete()
        db.session.commit()
        l1 = [Lesson(student_id=student_id, teacher_id=teacher_id, lesson_date=utc_now() + timedelta(days=1), status="planned", topic="L1")]
        db.session.add_all(l1)
        db.session.flush()

        notify_scheduled_lessons_batch(l1, student, actor_user_id=teacher_id)
        delivs_1 = TelegramDelivery.query.filter_by(user_id=student_uid).all()
        assert len(delivs_1) == 1
        assert delivs_1[0].kind == "lesson_scheduled"

        # B) Test 2 lessons
        TelegramDelivery.query.delete()
        db.session.commit()
        l2 = [
            Lesson(student_id=student_id, teacher_id=teacher_id, lesson_date=utc_now() + timedelta(days=1), status="planned", topic="L1"),
            Lesson(student_id=student_id, teacher_id=teacher_id, lesson_date=utc_now() + timedelta(days=2), status="planned", topic="L2"),
        ]
        db.session.add_all(l2)
        db.session.flush()

        notify_scheduled_lessons_batch(l2, student, actor_user_id=teacher_id)
        delivs_2 = TelegramDelivery.query.filter_by(user_id=student_uid).all()
        assert len(delivs_2) == 2
        assert all(d.kind == "lesson_scheduled" for d in delivs_2)

        # C) Test 5 lessons (>= BATCH_THRESHOLD = 3)
        TelegramDelivery.query.delete()
        db.session.commit()
        l5 = [
            Lesson(student_id=student_id, teacher_id=teacher_id, lesson_date=utc_now() + timedelta(days=i), status="planned", topic=f"Урок {i}")
            for i in range(1, 6)
        ]
        db.session.add_all(l5)
        db.session.flush()

        notify_scheduled_lessons_batch(l5, student, actor_user_id=teacher_id)
        delivs_st_5 = TelegramDelivery.query.filter_by(user_id=student_uid).all()
        delivs_p_5 = TelegramDelivery.query.filter_by(user_id=parent_id).all()
        delivs_tch_5 = TelegramDelivery.query.filter_by(user_id=teacher_id).all()

        # Student gets exactly 1 grouped card! Individual 5 cards suppressed!
        assert len(delivs_st_5) == 1
        assert delivs_st_5[0].kind == "lesson_batch_scheduled"
        st_card_text = delivs_st_5[0].payload.get("text", "")
        assert "5" in st_card_text

        # Teacher self-suppressed: 0 cards
        assert len(delivs_tch_5) == 0

        # Parent gets exactly 1 grouped card with child context!
        assert len(delivs_p_5) == 1
        assert delivs_p_5[0].kind == "lesson_batch_scheduled"
        p_card_text = delivs_p_5[0].payload.get("text", "")
        assert student.name in p_card_text or "Иван" in p_card_text


# =========================================================================
# 7. IN-APP NOTIFICATION INDEPENDENT OF TELEGRAM PREFERENCES
# =========================================================================
def test_in_app_notification_independent_of_telegram_preferences(app, e2e_users):
    """CRITICAL ACCEPTANCE REQUIREMENT:
    Disabling Telegram notification preferences must NEVER break or suppress
    the in-platform UserNotification record.
    """
    student_uid = e2e_users["student_user_id"]
    student_id = e2e_users["student_id"]
    teacher_id = e2e_users["teacher_id"]

    with app.app_context():
        student = db.session.get(Student, student_id)

        # Step 1: Disable Telegram preference for lesson_scheduled
        set_user_notification_preference(student_uid, "student", "lesson_scheduled", False)
        assert is_notification_enabled_for_user(student_uid, "student", "lesson_scheduled") is False

        # Schedule lesson
        l = Lesson(student_id=student_id, teacher_id=teacher_id, lesson_date=utc_now() + timedelta(days=2), status="planned", topic="Независимые уведомления")
        db.session.add(l)
        db.session.commit()

        _notify_lesson_scheduled(l, student, "Новый урок запланирован", actor_user_id=teacher_id)
        db.session.commit()

        # In-App UserNotification MUST EXIST!
        in_app = UserNotification.query.filter_by(user_id=student_uid, kind="lesson_scheduled").first()
        assert in_app is not None
        assert "Новый урок" in in_app.title

        # TelegramDelivery Outbox row MUST BE SUPPRESSED by user preference!
        tg_outbox = TelegramDelivery.query.filter_by(user_id=student_uid, kind="lesson_scheduled").all()
        assert len(tg_outbox) == 0

        # Step 2: Re-enable Telegram preference
        set_user_notification_preference(student_uid, "student", "lesson_scheduled", True)
        assert is_notification_enabled_for_user(student_uid, "student", "lesson_scheduled") is True

        _notify_lesson_scheduled(l, student, "Новый урок запланирован (дубль)", actor_user_id=teacher_id)
        db.session.commit()

        # Now BOTH in-app and Telegram delivery are generated!
        tg_outbox_enabled = TelegramDelivery.query.filter_by(user_id=student_uid, kind="lesson_scheduled").all()
        assert len(tg_outbox_enabled) >= 1


# =========================================================================
# 8. BROADCAST CENTER: Wizard Execution, DB persistence, and History Screen
# =========================================================================
def test_broadcast_center_wizard_and_history_screen(app, e2e_users, monkeypatch):
    """Broadcast Center:
    1. Execute broadcast send -> TelegramBroadcast record created with status completed and sent_ok.
    2. Outbox deliveries enqueued with broadcast_id in dedupe_key and meta.
    3. History screen displays past campaigns and delivery status metrics.
    """
    captured_messages = []

    async def fake_render(update, text, markup=None):
        captured_messages.append({"text": text, "markup": markup})

    monkeypatch.setattr("app.telegram.v3.screens.broadcast.render_screen", fake_render)

    teacher_id = e2e_users["teacher_id"]

    with app.app_context():
        teacher = db.session.get(User, teacher_id)

        # Setup draft for teacher
        _DRAFTS[teacher_id] = {
            "audience": "students",
            "category": "broadcast",
            "title": "Срочный вебинар по КЕГЭ",
            "text": "Сегодня в 19:00 разбираем прототипы 27 задания.",
        }

        class FakeUpdate:
            pass

        # 1. Execute broadcast
        asyncio.run(execute_broadcast_send(FakeUpdate(), teacher))

        # 2. Verify TelegramBroadcast DB record
        b_record = TelegramBroadcast.query.filter_by(created_by_user_id=teacher_id).first()
        assert b_record is not None
        assert b_record.title == "Срочный вебинар по КЕГЭ"
        assert b_record.status == "completed"
        assert b_record.sent_ok > 0
        assert b_record.recipient_scope == "students"

        # 3. Check Outbox deliveries
        broadcast_delivs = TelegramDelivery.query.filter(
            TelegramDelivery.dedupe_key.like(f"telegram:broadcast:{b_record.broadcast_id}:%")
        ).all()
        assert len(broadcast_delivs) > 0

        # Simulate dispatcher delivery for history metrics
        for d in broadcast_delivs:
            d.status = "sent"
        db.session.commit()

        # 4. View history screen
        captured_messages.clear()
        asyncio.run(show_broadcast_history(FakeUpdate(), teacher))

        assert len(captured_messages) == 1
        hist_text = captured_messages[0]["text"]
        assert "История рассылок" in hist_text
        assert "Срочный вебинар по КЕГЭ" in hist_text
        assert "отпр." in hist_text
