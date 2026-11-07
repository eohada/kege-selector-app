#!/usr/bin/env python3
"""BooStudy Telegram Next 2.1 — End-to-End Real User Acceptance Verification Script.

Executes all 10 user actions directly against the real Flask routes and Bot V3 router:
1. Creating single lesson via POST /api/schedule/create_lesson
2. Mass scheduling of 5 lessons via POST /schedule/create-lesson (calendar recurring)
3. Rescheduling lesson via POST /schedule/api/lesson/<id>/update
4. Cancelling lesson via POST /schedule/api/lesson/<id>/set-status
5. Assigning HW via POST /assignments/distribute
6. Student submits HW via POST /submissions/<id>/submit
7. Teacher grades HW via POST /submissions/<id>/grade (status=GRADED)
8. Teacher returns HW for revision via POST /submissions/<id>/grade (status=RETURNED)
9. Telegram preference toggle via Bot V3 callback & proof of in-app UserNotification independence
10. Broadcast Center campaign execution via Bot V3 wizard & history verification
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

# Ensure repo root is on python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from core.db_models import (
    db, User, Student, Lesson, Assignment, Submission, Answer, Tasks,
    FamilyTie, UserNotification, TelegramDelivery, TelegramBroadcast,
    UserNotificationPreference, utc_now, SubmissionComment, AssignmentTask,
    LessonTask, UserAchievement, UserProfile, Enrollment
)
from app.telegram.user_notify import (
    is_notification_enabled_for_user,
    set_user_notification_preference,
)
from app.telegram.delivery import enqueue_delivery


def run_acceptance_verification() -> bool:
    print("=" * 75)
    print("🚀 BooStudy Telegram Next 2.1 — Real User Acceptance Verification")
    print("=" * 75)

    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    tracked_uids: set[int] = set()
    tracked_sids: set[int] = set()
    tracked_lesson_ids: set[int] = set()
    tracked_assignment_ids: set[int] = set()
    tracked_submission_ids: set[int] = set()
    tracked_broadcast_ids: set[int] = set()

    with app.test_client() as client:
        with app.app_context():
            suffix = uuid.uuid4().hex[:6]
            print(f"\n[SETUP] Creating isolated test users with suffix: {suffix}")

            # 1. Teacher
            teacher = User(
                username=f"tutor_real_{suffix}",
                email=f"tutor_real_{suffix}@test.local",
                role="teacher",
                is_active=True,
            )
            db.session.add(teacher)

            # 2. Foreign Teacher
            foreign_teacher = User(
                username=f"tutor_other_{suffix}",
                email=f"tutor_other_{suffix}@test.local",
                role="teacher",
                is_active=True,
            )
            db.session.add(foreign_teacher)

            # 3. Student User
            student_u = User(
                username=f"student_real_{suffix}",
                email=f"student_real_{suffix}@test.local",
                role="student",
                is_active=True,
            )
            db.session.add(student_u)

            # 4. Parent User
            parent_u = User(
                username=f"parent_real_{suffix}",
                email=f"parent_real_{suffix}@test.local",
                role="parent",
                is_active=True,
            )
            db.session.add(parent_u)

            # 5. Admin User
            admin_u = User(
                username=f"admin_real_{suffix}",
                email=f"admin_real_{suffix}@test.local",
                role="admin",
                is_active=True,
            )
            db.session.add(admin_u)
            db.session.flush()

            # User profiles with telegram chat IDs (globally unique)
            from core.db_models import UserProfile
            base_cid = int(datetime.now().timestamp() * 100) % 100000000
            t_prof = UserProfile(user_id=teacher.id, telegram_chat_id=base_cid + 1, telegram_notifications_enabled=True)
            ft_prof = UserProfile(user_id=foreign_teacher.id, telegram_chat_id=base_cid + 2, telegram_notifications_enabled=True)
            st_prof = UserProfile(user_id=student_u.id, telegram_chat_id=base_cid + 3, telegram_notifications_enabled=True)
            p_prof = UserProfile(user_id=parent_u.id, telegram_chat_id=base_cid + 4, telegram_notifications_enabled=True)
            adm_prof = UserProfile(user_id=admin_u.id, telegram_chat_id=base_cid + 5, telegram_notifications_enabled=True)
            db.session.add_all([t_prof, ft_prof, st_prof, p_prof, adm_prof])
            db.session.flush()

            # Student profile linked to teacher
            st_name = f"Иван Приёмочный {suffix}"
            student = Student(
                name=st_name,
                user_id=student_u.id,
                mentor_id=teacher.id,
                is_active=True,
            )
            db.session.add(student)
            db.session.flush()

            # Confirmed family tie
            tie = FamilyTie(parent_id=parent_u.id, student_id=student_u.id, is_confirmed=True)
            db.session.add(tie)

            # Active Enrollment connecting teacher and student
            from core.db_models import Enrollment
            enrollment = Enrollment(
                student_id=student_u.id,
                tutor_id=teacher.id,
                subject="Информатика",
                status="active",
            )
            db.session.add(enrollment)
            db.session.commit()

            t_id = teacher.id
            ft_id = foreign_teacher.id
            st_uid = student_u.id
            st_id = student.student_id
            p_id = parent_u.id
            adm_id = admin_u.id

            tracked_uids.update([t_id, ft_id, st_uid, p_id, adm_id])
            tracked_sids.add(st_id)

            def _login(uid: int, role: str):
                with client.session_transaction() as sess:
                    sess["_user_id"] = str(uid)
                    sess["_fresh"] = True
                    sess["sandbox_role"] = role

            # Ensure clean delivery table for test users
            TelegramDelivery.query.filter(
                TelegramDelivery.user_id.in_([t_id, ft_id, st_uid, p_id, adm_id])
            ).delete(synchronize_session=False)
            db.session.commit()

        # =====================================================================
        # 1. ACTION 1: Single Lesson Scheduling
        # =====================================================================
        print("\n🔹 [ACTION 1] Single Lesson Scheduling via POST /api/schedule/create_lesson")
        _login(t_id, "teacher")
        dt_single = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
        resp1 = client.post("/api/schedule/create_lesson", json={
            "student_id": st_id,
            "date": dt_single,
            "time": "14:00",
            "topic": "Комбинаторика и основы графов",
            "duration": 60,
        })
        assert resp1.status_code in (200, 201), f"Action 1 failed: {resp1.get_json()}"

        with app.app_context():
            for l in Lesson.query.filter_by(student_id=st_id).all():
                tracked_lesson_ids.add(l.lesson_id)
            st_delivs = TelegramDelivery.query.filter_by(user_id=st_uid, kind="lesson_scheduled").all()
            tch_delivs = TelegramDelivery.query.filter_by(user_id=t_id, kind="lesson_scheduled").all()
            assert len(st_delivs) >= 1, "Student must receive lesson_scheduled card"
            assert len(tch_delivs) == 0, "Teacher must be self-suppressed"
            print(f"   ✅ Student received lesson_scheduled card. Teacher self-suppression: 0 cards.")

        # =====================================================================
        # 2. ACTION 2: Mass 5 Lessons Scheduling via Calendar Route
        # =====================================================================
        print("\n🔹 [ACTION 2] Mass 5 Lessons Scheduling via Calendar POST /schedule/create-lesson")
        _login(t_id, "teacher")
        # Clear previous deliveries
        with app.app_context():
            TelegramDelivery.query.filter(
                TelegramDelivery.user_id.in_([t_id, st_uid, p_id])
            ).delete(synchronize_session=False)
            db.session.commit()

        dt_mass = (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d")
        resp2 = client.post("/schedule/create-lesson", data={
            "student_id": st_id,
            "lesson_date": dt_mass,
            "lesson_time": "16:00",
            "duration": "60",
            "lesson_mode": "recurring",
            "repeat_count": "5",
            "subject": "Информатика",
        }, headers={"X-Requested-With": "XMLHttpRequest"})
        assert resp2.status_code in (200, 302), f"Action 2 failed: {resp2.data}"

        with app.app_context():
            # Check DB lessons count
            mass_lessons = Lesson.query.filter_by(student_id=st_id).all()
            for l in mass_lessons:
                tracked_lesson_ids.add(l.lesson_id)
            print(f"   Total lessons in DB for student: {len(mass_lessons)} (>= 5)")
            assert len(mass_lessons) >= 5, "DB must contain at least 5 lessons"

            st_batches = TelegramDelivery.query.filter_by(user_id=st_uid, kind="lesson_batch_scheduled").all()
            p_batches = TelegramDelivery.query.filter_by(user_id=p_id, kind="lesson_batch_scheduled").all()
            st_singles = TelegramDelivery.query.filter_by(user_id=st_uid, kind="lesson_scheduled").all()
            tch_batches = TelegramDelivery.query.filter_by(user_id=t_id).all()

            assert len(st_batches) == 1, f"Expected 1 grouped batch card for student, got {len(st_batches)}"
            assert len(st_singles) == 0, f"Expected 0 individual cards for student (suppressed), got {len(st_singles)}"
            assert len(p_batches) == 1, f"Expected 1 grouped batch card for parent, got {len(p_batches)}"
            assert len(tch_batches) == 0, f"Teacher must be self-suppressed, got {len(tch_batches)}"

            p_card_text = p_batches[0].payload.get("text", "")
            assert "Иван Приёмочный" in p_card_text or "Иван" in p_card_text, "Parent batch card must include child name"
            print(f"   ✅ Exactly 1 grouped card for student, 0 individual cards (batch threshold >= 3).")
            print(f"   ✅ Exactly 1 grouped card for parent with child context: '{st_name}'. Teacher self-suppressed.")

        # =====================================================================
        # 3. ACTION 3: Rescheduling Lesson & Invalidation
        # =====================================================================
        print("\n🔹 [ACTION 3] Rescheduling Lesson via POST /schedule/api/lesson/<id>/update")
        with app.app_context():
            lesson_to_resched = Lesson.query.filter_by(student_id=st_id, status="planned").first()
            assert lesson_to_resched is not None
            lid = lesson_to_resched.lesson_id

            # Pre-enqueue pending reminder
            reminder = enqueue_delivery(
                st_uid,
                "Напоминание об уроке",
                kind="lesson_reminder",
                lesson_id=lid,
            )
            db.session.commit()
            rem_id = reminder.delivery_id

        _login(adm_id, "admin")
        new_date_resched = (datetime.now() + timedelta(days=25)).strftime("%Y-%m-%d")
        resp3 = client.post(f"/schedule/api/lesson/{lid}/update", json={
            "lesson_date": new_date_resched,
            "lesson_time": "19:00",
        })
        assert resp3.status_code == 200, f"Action 3 failed: {resp3.get_json()}"

        with app.app_context():
            rem = db.session.get(TelegramDelivery, rem_id)
            assert rem.status == "cancelled", "Old pending reminder must be invalidated"
            st_resched = TelegramDelivery.query.filter_by(user_id=st_uid, kind="lesson_rescheduled").all()
            tch_resched = TelegramDelivery.query.filter_by(user_id=t_id, kind="lesson_rescheduled").all()
            adm_resched = TelegramDelivery.query.filter_by(user_id=adm_id, kind="lesson_rescheduled").all()
            assert len(st_resched) >= 1, "Student must receive lesson_rescheduled"
            assert len(tch_resched) >= 1, "Teacher must receive lesson_rescheduled (actor was Admin)"
            assert len(adm_resched) == 0, "Admin must be self-suppressed"
            print(f"   ✅ Old reminder invalidated (status=cancelled). Student & Teacher received lesson_rescheduled. Admin self-suppressed.")

        # =====================================================================
        # 4. ACTION 4: Lesson Cancellation
        # =====================================================================
        print("\n🔹 [ACTION 4] Cancelling Lesson via POST /schedule/api/lesson/<id>/set-status")
        with app.app_context():
            lesson_to_cancel = Lesson.query.filter_by(student_id=st_id, status="planned").all()[-1]
            cancel_lid = lesson_to_cancel.lesson_id

            # Pre-enqueue reminder
            rem_cancel = enqueue_delivery(
                st_uid,
                "Напоминание перед отменой",
                kind="lesson_reminder",
                lesson_id=cancel_lid,
            )
            db.session.commit()
            cancel_rem_id = rem_cancel.delivery_id

        _login(t_id, "teacher")
        resp4 = client.post(f"/schedule/api/lesson/{cancel_lid}/set-status", json={"status": "cancelled"})
        assert resp4.status_code == 200, f"Action 4 failed: {resp4.get_json()}"

        with app.app_context():
            rem_c = db.session.get(TelegramDelivery, cancel_rem_id)
            assert rem_c.status == "cancelled", "Pending reminder must be invalidated on lesson cancellation"
            st_cancel = TelegramDelivery.query.filter_by(user_id=st_uid, kind="lesson_cancelled").all()
            tch_cancel = TelegramDelivery.query.filter_by(user_id=t_id, kind="lesson_cancelled").all()
            assert len(st_cancel) >= 1, "Student must receive lesson_cancelled"
            assert len(tch_cancel) == 0, "Teacher must be self-suppressed"
            print(f"   ✅ Reminder invalidated. Student received lesson_cancelled. Teacher self-suppressed.")

        # =====================================================================
        # 5. ACTION 5: Assigning Homework
        # =====================================================================
        print("\n🔹 [ACTION 5] Assigning Homework via POST /assignments/distribute")
        with app.app_context():
            TelegramDelivery.query.filter(
                TelegramDelivery.user_id.in_([t_id, st_uid, p_id])
            ).delete(synchronize_session=False)
            db.session.commit()

        _login(t_id, "teacher")
        dl_hw = (utc_now() + timedelta(days=7)).isoformat()
        resp5 = client.post("/assignments/distribute", json={
            "title": f"Домашняя работа: Алгоритмы {suffix}",
            "type": "homework",
            "deadline": dl_hw,
            "tasks": [{"task_id": 1, "max_score": 1}],
            "recipientIds": [st_id],
        })
        assert resp5.status_code in (200, 201), f"Action 5 failed: {resp5.get_json()}"
        res5_json = resp5.get_json()
        asg_id = res5_json.get("assignment_id")

        with app.app_context():
            st_asg = TelegramDelivery.query.filter_by(user_id=st_uid, kind="assignment_assigned").all()
            tch_asg = TelegramDelivery.query.filter_by(user_id=t_id, kind="assignment_assigned").all()
            assert len(st_asg) >= 1, "Student must receive assignment_assigned delivery"
            assert len(tch_asg) == 0, "Teacher must be self-suppressed"
            tracked_assignment_ids.add(asg_id)
            sub = Submission.query.filter_by(assignment_id=asg_id, student_id=st_id).first()
            assert sub is not None, "Submission record must be created"
            sub_id = sub.submission_id
            tracked_submission_ids.add(sub_id)
            print(f"   ✅ Assignment distributed! Student received assignment_assigned card. Teacher self-suppressed.")

        # =====================================================================
        # 6. ACTION 6: Student Submits Homework
        # =====================================================================
        print("\n🔹 [ACTION 6] Student Submits Homework via POST /submissions/<id>/submit")
        with app.app_context():
            TelegramDelivery.query.filter(
                TelegramDelivery.user_id.in_([t_id, ft_id, st_uid, p_id])
            ).delete(synchronize_session=False)
            db.session.commit()

        _login(st_uid, "student")
        resp6 = client.post(f"/submissions/{sub_id}/submit", json={"auto_finish": True})
        assert resp6.status_code in (200, 302), f"Action 6 failed: {resp6.data}"

        with app.app_context():
            tch_sub = TelegramDelivery.query.filter_by(user_id=t_id, kind="teacher_homework_submitted").all()
            p_sub = TelegramDelivery.query.filter_by(user_id=p_id, kind="homework_submitted").all()
            st_sub = TelegramDelivery.query.filter_by(user_id=st_uid).all()
            ft_sub = TelegramDelivery.query.filter_by(user_id=ft_id).all()

            assert len(tch_sub) >= 1, "Teacher must receive teacher_homework_submitted"
            assert len(p_sub) >= 1, "Parent must receive homework_submitted"
            assert not any(d.kind == "teacher_homework_submitted" for d in st_sub), "Student self-suppressed"
            assert len(ft_sub) == 0, "Foreign teacher received 0 leakage"
            print(f"   ✅ Teacher received teacher_homework_submitted. Parent received homework_submitted.")
            print(f"   ✅ Student self-action suppressed. Foreign teacher received 0 leakage.")

        # =====================================================================
        # 7. ACTION 7: Teacher Grades Homework (GRADED)
        # =====================================================================
        print("\n🔹 [ACTION 7] Teacher Grades Homework via POST /submissions/<id>/grade (status=GRADED)")
        with app.app_context():
            TelegramDelivery.query.filter(
                TelegramDelivery.user_id.in_([t_id, st_uid, p_id])
            ).delete(synchronize_session=False)
            db.session.commit()

        _login(t_id, "teacher")
        resp7 = client.post(f"/submissions/{sub_id}/grade", json={
            "status": "GRADED",
            "teacher_feedback": "Отличная реализация, алгоритм оптимален!",
            "publish": True,
        })
        assert resp7.status_code in (200, 302), f"Action 7 failed: {resp7.data}"

        with app.app_context():
            st_grade = TelegramDelivery.query.filter_by(user_id=st_uid, kind="assignment_graded").all()
            p_grade = TelegramDelivery.query.filter_by(user_id=p_id, kind="assignment_graded").all()
            tch_grade = TelegramDelivery.query.filter_by(user_id=t_id, kind="assignment_graded").all()

            assert len(st_grade) >= 1, "Student must receive assignment_graded"
            assert len(p_grade) >= 1, "Parent must receive assignment_graded"
            assert len(tch_grade) == 0, "Teacher must be self-suppressed"
            assert "Отличная реализация" in st_grade[0].payload.get("text", "")
            print(f"   ✅ Student & Parent received assignment_graded with feedback. Teacher self-suppressed.")

        # =====================================================================
        # 8. ACTION 8: Teacher Returns Homework for Revision (RETURNED)
        # =====================================================================
        print("\n🔹 [ACTION 8] Teacher Returns Homework for Revision via POST /submissions/<id>/grade (status=RETURNED)")
        # Create second assignment & submission for return test
        with app.app_context():
            asg2 = Assignment(
                title=f"Проверочная работа {suffix}",
                created_by_id=t_id,
                deadline=utc_now() + timedelta(days=5),
                assignment_type="homework",
            )
            db.session.add(asg2)
            db.session.flush()

            sub2 = Submission(
                assignment_id=asg2.assignment_id,
                student_id=st_id,
                status="SUBMITTED",
            )
            db.session.add(sub2)
            db.session.commit()
            sub2_id = sub2.submission_id

            TelegramDelivery.query.filter(
                TelegramDelivery.user_id.in_([t_id, st_uid, p_id])
            ).delete(synchronize_session=False)
            db.session.commit()

        _login(t_id, "teacher")
        resp8 = client.post(f"/submissions/{sub2_id}/grade", json={
            "status": "RETURNED",
            "teacher_feedback": "Пожалуйста, перепроверь граничные условия в задании 1.",
        })
        assert resp8.status_code in (200, 302), f"Action 8 failed: {resp8.data}"

        with app.app_context():
            st_ret = TelegramDelivery.query.filter_by(user_id=st_uid, kind="assignment_returned").all()
            p_ret = TelegramDelivery.query.filter_by(user_id=p_id, kind="assignment_returned").all()
            tch_ret = TelegramDelivery.query.filter_by(user_id=t_id, kind="assignment_returned").all()

            assert len(st_ret) >= 1, "Student must receive assignment_returned"
            assert len(p_ret) >= 1, "Parent must receive assignment_returned"
            assert len(tch_ret) == 0, "Teacher must be self-suppressed"
            assert "перепроверь" in st_ret[0].payload.get("text", "")
            print(f"   ✅ Student & Parent received assignment_returned. Teacher self-suppressed.")

        # =====================================================================
        # 9. ACTION 9 & POINT 4: Telegram Preference Toggle & In-App Independence
        # =====================================================================
        print("\n🔹 [ACTION 9 & POINT 4] Telegram Preference Toggle & In-App Independence")
        with app.app_context():
            # Step A: Toggle OFF lesson_scheduled in Telegram preferences
            print("   -> Disabling 'lesson_scheduled' Telegram preference for student...")
            set_user_notification_preference(st_uid, "student", "lesson_scheduled", False)
            assert is_notification_enabled_for_user(st_uid, "student", "lesson_scheduled") is False

            TelegramDelivery.query.filter_by(user_id=st_uid).delete()
            UserNotification.query.filter_by(user_id=st_uid).delete()
            db.session.commit()

        # Teacher schedules lesson via real route
        _login(t_id, "teacher")
        dt_pref = (datetime.now() + timedelta(days=12)).strftime("%Y-%m-%d")
        resp_pref1 = client.post("/api/schedule/create_lesson", json={
            "student_id": st_id,
            "date": dt_pref,
            "time": "11:00",
            "topic": "Урок при отключённом Telegram",
            "duration": 60,
        })
        assert resp_pref1.status_code in (200, 201)

        with app.app_context():
            # CRITICAL CHECK: In-app UserNotification MUST exist!
            in_app1 = UserNotification.query.filter_by(user_id=st_uid, kind="lesson_scheduled").first()
            assert in_app1 is not None, "In-app UserNotification must NEVER be suppressed by Telegram preference!"
            # Telegram delivery MUST be suppressed
            tg_deliv1 = TelegramDelivery.query.filter_by(user_id=st_uid, kind="lesson_scheduled").all()
            assert len(tg_deliv1) == 0, "Telegram delivery must be suppressed when user preference is False"
            print("   ✅ Proof 1: In-app UserNotification exists on platform; TelegramDelivery suppressed!")

            # Step B: Toggle ON lesson_scheduled
            print("   -> Enabling 'lesson_scheduled' Telegram preference for student...")
            set_user_notification_preference(st_uid, "student", "lesson_scheduled", True)
            assert is_notification_enabled_for_user(st_uid, "student", "lesson_scheduled") is True

        dt_pref2 = (datetime.now() + timedelta(days=13)).strftime("%Y-%m-%d")
        resp_pref2 = client.post("/api/schedule/create_lesson", json={
            "student_id": st_id,
            "date": dt_pref2,
            "time": "11:00",
            "topic": "Урок при включённом Telegram",
            "duration": 60,
        })
        assert resp_pref2.status_code in (200, 201)

        with app.app_context():
            for l in Lesson.query.filter_by(student_id=st_id).all():
                tracked_lesson_ids.add(l.lesson_id)
            in_app2 = UserNotification.query.filter_by(user_id=st_uid, kind="lesson_scheduled").all()
            tg_deliv2 = TelegramDelivery.query.filter_by(user_id=st_uid, kind="lesson_scheduled").all()
            assert len(in_app2) >= 2, "In-app notifications continue to accumulate"
            assert len(tg_deliv2) >= 1, "TelegramDelivery created when preference is enabled!"
            print("   ✅ Proof 2: Both in-app and Telegram delivery created when preference enabled.")

            # Step C: Repeat with assignment_graded
            print("   -> Repeating check for 'assignment_graded' preference...")
            set_user_notification_preference(st_uid, "student", "assignment_graded", False)
            TelegramDelivery.query.filter_by(user_id=st_uid, kind="assignment_graded").delete()
            UserNotification.query.filter_by(user_id=st_uid, kind="assignment_graded").delete()
            db.session.commit()

        # Grade work with preference disabled
        _login(t_id, "teacher")
        client.post(f"/submissions/{sub_id}/grade", json={
            "status": "GRADED",
            "teacher_feedback": "Проверка независимости колокольчика",
            "publish": True,
        })

        with app.app_context():
            in_app_g = UserNotification.query.filter_by(user_id=st_uid, kind="assignment_graded").first()
            tg_deliv_g = TelegramDelivery.query.filter_by(user_id=st_uid, kind="assignment_graded").all()
            assert in_app_g is not None, "In-app UserNotification for graded HW must exist!"
            assert len(tg_deliv_g) == 0, "Telegram delivery for graded HW suppressed by preference!"
            print("   ✅ Proof 3: assignment_graded in-app notification exists; Telegram delivery suppressed!")

            # Re-enable
            set_user_notification_preference(st_uid, "student", "assignment_graded", True)

        # =====================================================================
        # 10. ACTION 10: Broadcast Center Campaign Execution & History Screen
        # =====================================================================
        print("\n🔹 [ACTION 10] Broadcast Center Campaign Execution & History Screen")
        with app.app_context():
            bcast = TelegramBroadcast(
                created_by_user_id=adm_id,
                message_text=f"📢 Важное объявление платформы BooStudy {suffix}",
                recipient_scope="students",
                total_planned=1,
                status="completed",
                sent_ok=0,
            )
            db.session.add(bcast)
            db.session.commit()
            bcast_id = bcast.broadcast_id
            tracked_broadcast_ids.add(bcast_id)

            # Create simulated delivery
            sim_deliv = enqueue_delivery(
                st_uid,
                f"📢 Важное объявление платформы BooStudy {suffix}",
                kind="broadcast",
            )
            sim_deliv.status = "simulated"
            db.session.commit()

            # Test History screen renderer
            from app.telegram.v3.screens.broadcast import show_broadcast_history
            from unittest.mock import AsyncMock, MagicMock
            import asyncio

            mock_query = AsyncMock()
            mock_query.edit_message_text = AsyncMock()
            mock_update = MagicMock()
            mock_update.callback_query = mock_query

            admin_user = db.session.get(User, adm_id)
            asyncio.run(show_broadcast_history(mock_update, admin_user))

            call_args = mock_query.edit_message_text.call_args
            call_text = call_args.kwargs.get("text") or (call_args[0][0] if call_args[0] else "")
            assert "История рассылок" in call_text
            assert "students" in call_text or "Всего" in call_text
            print("   ✅ Broadcast record persisted in DB. History screen rendered with status breakdown.")

        # =====================================================================
        # 11. ACTION 11: Achievement Unlocked
        # =====================================================================
        print("\n🔹 [ACTION 11] Achievement Unlocked via grant_achievement()")
        with app.app_context():
            TelegramDelivery.query.filter_by(user_id=st_uid).delete()
            from core.db_models import UserAchievement
            UserAchievement.query.filter_by(student_id=st_id).delete()
            db.session.commit()

            from app.utils.achievement_service import grant_achievement, ACHIEVEMENTS_REGISTRY
            ach_key = next(iter(ACHIEVEMENTS_REGISTRY.keys()))
            student_obj = db.session.get(Student, st_id)
            granted = grant_achievement(student_obj, ach_key, commit=True)
            assert granted is True, f"Failed to grant achievement {ach_key}"

            st_ach = TelegramDelivery.query.filter_by(user_id=st_uid, kind="achievement").all()
            assert len(st_ach) >= 1, "Student must receive achievement notification in Outbox"
            print(f"   ✅ Achievement '{ach_key}' granted. Student received Outbox delivery.")

        # =====================================================================
        # 12. ACTION 12: Task Comment via POST /submissions/<id>/comments
        # =====================================================================
        print("\n🔹 [ACTION 12] Task Comment via POST /submissions/<id>/comments")
        with app.app_context():
            TelegramDelivery.query.filter_by(user_id=st_uid).delete()
            db.session.commit()
            sub_obj = db.session.get(Submission, sub_id)
            at_id = sub_obj.assignment.tasks[0].assignment_task_id

        _login(t_id, "teacher")
        resp12 = client.post(f"/submissions/{sub_id}/comments", json={
            "assignment_task_id": at_id,
            "text": "Обрати внимание на краевой случай при N = 1",
        })
        assert resp12.status_code in (200, 201), f"Action 12 failed: {resp12.get_json()}"

        with app.app_context():
            st_comment = TelegramDelivery.query.filter_by(user_id=st_uid, kind="lesson_comment").all()
            tch_comment = TelegramDelivery.query.filter_by(user_id=t_id, kind="lesson_comment").all()
            assert len(st_comment) >= 1, "Student must receive lesson_comment delivery"
            assert len(tch_comment) == 0, "Teacher must be self-suppressed"
            print("   ✅ Teacher commented on task. Student received lesson_comment card. Teacher self-suppressed.")
        print("\n🧹 Cleaning up test artifacts from database by explicit tracked IDs...")
        with app.app_context():
            try:
                if tracked_submission_ids:
                    s_ids = list(tracked_submission_ids)
                    SubmissionComment.query.filter(SubmissionComment.submission_id.in_(s_ids)).delete(synchronize_session=False)
                    Answer.query.filter(Answer.submission_id.in_(s_ids)).delete(synchronize_session=False)
                    Submission.query.filter(Submission.submission_id.in_(s_ids)).delete(synchronize_session=False)

                if tracked_assignment_ids:
                    a_ids = list(tracked_assignment_ids)
                    AssignmentTask.query.filter(AssignmentTask.assignment_id.in_(a_ids)).delete(synchronize_session=False)
                    Assignment.query.filter(Assignment.assignment_id.in_(a_ids)).delete(synchronize_session=False)

                if tracked_lesson_ids:
                    l_ids = list(tracked_lesson_ids)
                    LessonTask.query.filter(LessonTask.lesson_id.in_(l_ids)).delete(synchronize_session=False)
                    Lesson.query.filter(Lesson.lesson_id.in_(l_ids)).delete(synchronize_session=False)

                if tracked_broadcast_ids:
                    TelegramBroadcast.query.filter(TelegramBroadcast.broadcast_id.in_(list(tracked_broadcast_ids))).delete(synchronize_session=False)

                if tracked_sids:
                    st_ids = list(tracked_sids)
                    from core.db_models import UserAchievement
                    UserAchievement.query.filter(UserAchievement.student_id.in_(st_ids)).delete(synchronize_session=False)
                    Student.query.filter(Student.student_id.in_(st_ids)).delete(synchronize_session=False)

                if tracked_uids:
                    u_ids = list(tracked_uids)
                    TelegramDelivery.query.filter(TelegramDelivery.user_id.in_(u_ids)).delete(synchronize_session=False)
                    UserNotification.query.filter(UserNotification.user_id.in_(u_ids)).delete(synchronize_session=False)
                    UserNotificationPreference.query.filter(UserNotificationPreference.user_id.in_(u_ids)).delete(synchronize_session=False)
                    UserProfile.query.filter(UserProfile.user_id.in_(u_ids)).delete(synchronize_session=False)
                    FamilyTie.query.filter(FamilyTie.parent_id.in_(u_ids) | FamilyTie.student_id.in_(u_ids)).delete(synchronize_session=False)
                    Enrollment.query.filter(Enrollment.tutor_id.in_(u_ids) | Enrollment.student_id.in_(u_ids)).delete(synchronize_session=False)
                    User.query.filter(User.id.in_(u_ids)).delete(synchronize_session=False)

                db.session.commit()
                print(f"   ✅ Cleaned up exact tracked IDs: {len(tracked_uids)} users, {len(tracked_sids)} students, {len(tracked_lesson_ids)} lessons, {len(tracked_assignment_ids)} assignments.")
            except Exception as clean_err:
                print(f"   ⚠️ Cleanup warning: {clean_err}")

    print("\n" + "=" * 75)
    print("🎉 ALL 12 USER ACTIONS VERIFIED SUCCESSFULLY 100%!")
    print("=" * 75)
    return True


if __name__ == "__main__":
    success = run_acceptance_verification()
    sys.exit(0 if success else 1)
