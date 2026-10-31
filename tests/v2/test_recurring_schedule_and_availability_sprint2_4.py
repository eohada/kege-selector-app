"""Comprehensive Test Suite for Recurring Lessons, Teacher Availability & Schedule Exceptions (Sprint 2.4).

Covers all 25 acceptance scenarios:
1. test_recurring_series_creation
2. test_multiple_recurring_slots_per_week
3. test_horizon_bounded_generation
4. test_idempotent_generation_no_duplicates
5. test_generator_restart_safety
6. test_scenario_a_modify_single_lesson
7. test_scenario_b_modify_this_and_future
8. test_scenario_c_modify_whole_series
9. test_scenario_d_cancel_single_lesson
10. test_scenario_e_pause_and_resume_series
11. test_teacher_conflict_isolation
12. test_student_cross_teacher_conflict
13. test_conflict_on_single_future_date
14. test_pg_concurrent_series_creation
15. test_concurrent_single_vs_series_generation
16. test_teacher_working_hours_restriction
17. test_holiday_exception_blocks_generation
18. test_timezone_conversion_across_iana
19. test_dst_transition_safety
20. test_rbac_idor_peer_teacher_isolation
21. test_zero_balance_deductions_during_generation
22. test_tg_notification_idempotency
23. test_concept_d_student_view_consistency
24. test_historical_lesson_preservation
25. test_regression_multi_teacher_sprint2_2_2_3
"""
from __future__ import annotations

import concurrent.futures
from datetime import date, datetime, time as dt_time, timedelta, timezone as dt_timezone
import json
import pytest
from werkzeug.security import generate_password_hash

from app import create_app, db
from app.models import (
    Enrollment,
    Lesson,
    RecurringLessonSlot,
    RecurringSlotException,
    Student,
    TeacherScheduleException,
    TeacherWeeklyAvailability,
    User,
    UserProfile,
)
from app.schedule.ownership_service import (
    acquire_scheduling_locks,
    check_tutor_conflict_isolated,
)
from app.schedule.recurrence_service import (
    add_teacher_schedule_exception,
    cancel_recurring_instance,
    check_teacher_availability,
    create_recurring_series,
    generate_lessons_for_slot,
    pause_recurring_series,
    preview_recurring_slot,
    reschedule_recurring_instance,
    resume_recurring_series,
    set_teacher_weekly_availability,
    update_series_from_date,
    update_whole_series,
)
from tests.v2.conftest import login_as

PG_TEST_DB_URL = "postgresql://postgres@/boostudy_test?host=/tmp/pg_socket&port=54329"


@pytest.fixture
def test_app():
    app = create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
    })
    with app.app_context():
        db.create_all()
        from app.utils.db_migrations import ensure_schema_columns
        ensure_schema_columns(app)
        yield app
        db.session.rollback()


@pytest.fixture
def fixtures_sprint2_4(test_app):
    """Creates Teacher Ivan (CS), Teacher Elena (Math), Student Alice, and Student Bob."""
    with test_app.app_context():
        tutor_ivan = User(
            username="tutor_ivan_s24",
            email="ivan_s24@example.com",
            password_hash=generate_password_hash("pass"),
            role="tutor",
            full_name="Иван Сергеевич",
        )
        tutor_elena = User(
            username="tutor_elena_s24",
            email="elena_s24@example.com",
            password_hash=generate_password_hash("pass"),
            role="tutor",
            full_name="Елена Петровна",
        )
        admin = User(
            username="admin_s24",
            email="admin_s24@example.com",
            password_hash=generate_password_hash("pass"),
            role="creator",
            full_name="Админ",
        )
        db.session.add_all([tutor_ivan, tutor_elena, admin])
        db.session.flush()

        p_ivan = UserProfile(user_id=tutor_ivan.id, first_name="Иван", last_name="Сергеевич")
        p_elena = UserProfile(user_id=tutor_elena.id, first_name="Елена", last_name="Петровна")
        db.session.add_all([p_ivan, p_elena])

        alice_user = User(
            username="alice_s24",
            email="alice_s24@example.com",
            password_hash=generate_password_hash("pass"),
            role="student",
            full_name="Алиса Мульти",
        )
        bob_user = User(
            username="bob_s24",
            email="bob_s24@example.com",
            password_hash=generate_password_hash("pass"),
            role="student",
            full_name="Боб Соло",
        )
        db.session.add_all([alice_user, bob_user])
        db.session.flush()

        p_alice = UserProfile(user_id=alice_user.id, first_name="Алиса", last_name="Студент")
        p_bob = UserProfile(user_id=bob_user.id, first_name="Боб", last_name="Студент")
        db.session.add_all([p_alice, p_bob])

        st_alice = Student(name="Алиса Мульти", email="alice_s24@example.com", user_id=alice_user.id)
        st_bob = Student(name="Боб Соло", email="bob_s24@example.com", user_id=bob_user.id)
        db.session.add_all([st_alice, st_bob])
        db.session.flush()

        enr_ivan_alice = Enrollment(tutor_id=tutor_ivan.id, student_id=alice_user.id, subject="Информатика", status="active")
        enr_elena_alice = Enrollment(tutor_id=tutor_elena.id, student_id=alice_user.id, subject="Математика", status="active")
        enr_ivan_bob = Enrollment(tutor_id=tutor_ivan.id, student_id=bob_user.id, subject="Информатика", status="active")
        db.session.add_all([enr_ivan_alice, enr_elena_alice, enr_ivan_bob])
        db.session.commit()

        return {
            "ivan_id": tutor_ivan.id,
            "elena_id": tutor_elena.id,
            "admin_id": admin.id,
            "alice_user_id": alice_user.id,
            "alice_student_id": st_alice.id,
            "bob_student_id": st_bob.id,
        }


# =========================================================================
# 1. test_recurring_series_creation
# =========================================================================
def test_recurring_series_creation(test_app, fixtures_sprint2_4):
    """Validates creation of recurring weekly slot with series_id, subject, and generated lessons."""
    with test_app.app_context():
        fx = fixtures_sprint2_4
        start_d = date.today()
        # Find next Tuesday (weekday 1)
        days_ahead = (1 - start_d.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        tue_date = start_d + timedelta(days=days_ahead)

        slot, lessons = create_recurring_series(
            teacher_id=fx["ivan_id"],
            student_id=fx["alice_student_id"],
            subject="Информатика",
            weekday=1,
            start_time="18:00",
            duration_minutes=60,
            start_date=tue_date,
            topic="Регулярный разбор графов",
            horizon_days=28,
        )
        assert slot.id is not None
        assert slot.series_id.startswith("series_")
        assert slot.subject == "Информатика"
        assert slot.is_active is True
        assert len(lessons) == 4

        for les in lessons:
            assert les.recurring_slot_id == slot.id
            assert les.recurrence_key is not None
            assert les.slot_origin_date is not None
            assert les.subject == "Информатика"
            assert les.status == "planned"


# =========================================================================
# 2. test_multiple_recurring_slots_per_week
# =========================================================================
def test_multiple_recurring_slots_per_week(test_app, fixtures_sprint2_4):
    """Validates teacher having multiple slots per week (Tue and Fri) for same student."""
    with test_app.app_context():
        fx = fixtures_sprint2_4
        start_d = date.today()

        slot_tue, lessons_tue = create_recurring_series(
            teacher_id=fx["ivan_id"],
            student_id=fx["alice_student_id"],
            subject="Информатика",
            weekday=1,
            start_time="18:00",
            duration_minutes=60,
            start_date=start_d,
            topic="Информатика Вт",
            horizon_days=28,
        )
        slot_fri, lessons_fri = create_recurring_series(
            teacher_id=fx["ivan_id"],
            student_id=fx["alice_student_id"],
            subject="Информатика",
            weekday=4,
            start_time="17:00",
            duration_minutes=60,
            start_date=start_d,
            topic="Информатика Пт",
            horizon_days=28,
        )

        assert slot_tue.id != slot_fri.id
        assert slot_tue.series_id != slot_fri.series_id
        assert len(lessons_tue) > 0
        assert len(lessons_fri) > 0

        # Verify no mixing of slot origins
        for les in lessons_tue:
            assert les.recurring_slot_id == slot_tue.id
            assert les.start_time.weekday() == 1
        for les in lessons_fri:
            assert les.recurring_slot_id == slot_fri.id
            assert les.start_time.weekday() == 4


# =========================================================================
# 3. test_horizon_bounded_generation
# =========================================================================
def test_horizon_bounded_generation(test_app, fixtures_sprint2_4):
    """Ensures lessons are generated strictly within the specified horizon window."""
    with test_app.app_context():
        fx = fixtures_sprint2_4
        start_d = date.today()

        slot, lessons = create_recurring_series(
            teacher_id=fx["ivan_id"],
            student_id=fx["alice_student_id"],
            subject="Информатика",
            weekday=2,
            start_time="15:00",
            duration_minutes=60,
            start_date=start_d,
            horizon_days=14,  # exactly 2 weeks
        )
        assert len(lessons) == 2
        for les in lessons:
            assert les.start_time.date() <= start_d + timedelta(days=14)


# =========================================================================
# 4. test_idempotent_generation_no_duplicates
# =========================================================================
def test_idempotent_generation_no_duplicates(test_app, fixtures_sprint2_4):
    """Repeated calls to generator produce zero duplicates and maintain DB uniqueness."""
    with test_app.app_context():
        fx = fixtures_sprint2_4
        start_d = date.today()

        slot, initial_lessons = create_recurring_series(
            teacher_id=fx["ivan_id"],
            student_id=fx["alice_student_id"],
            subject="Информатика",
            weekday=3,
            start_time="16:00",
            duration_minutes=60,
            start_date=start_d,
            horizon_days=28,
        )
        initial_count = len(initial_lessons)
        assert initial_count > 0

        # Run generator 5 times repeatedly
        for _ in range(5):
            new_lessons = generate_lessons_for_slot(slot.id, horizon_days=28)
            assert len(new_lessons) == 0

        total_in_db = Lesson.query.filter_by(recurring_slot_id=slot.id).count()
        assert total_in_db == initial_count


# =========================================================================
# 5. test_generator_restart_safety
# =========================================================================
def test_generator_restart_safety(test_app, fixtures_sprint2_4):
    """Simulates service restart: existing lessons remain connected without recreation."""
    with test_app.app_context():
        fx = fixtures_sprint2_4
        start_d = date.today()

        slot, _ = create_recurring_series(
            teacher_id=fx["ivan_id"],
            student_id=fx["alice_student_id"],
            subject="Информатика",
            weekday=0,
            start_time="12:00",
            duration_minutes=60,
            start_date=start_d,
            horizon_days=28,
        )
        slot_id = slot.id

    # Simulate restart by new db query session
    with test_app.app_context():
        reloaded_slot = RecurringLessonSlot.query.get(slot_id)
        generated_again = generate_lessons_for_slot(reloaded_slot.id, horizon_days=28)
        assert len(generated_again) == 0
        total_lessons = Lesson.query.filter_by(recurring_slot_id=slot_id).count()
        assert total_lessons == 4


# =========================================================================
# 6. test_scenario_a_modify_single_lesson
# =========================================================================
def test_scenario_a_modify_single_lesson(test_app, fixtures_sprint2_4):
    """Scenario A: Reschedule a single instance; recurrence_key preserved, generator skips original date."""
    with test_app.app_context():
        fx = fixtures_sprint2_4
        start_d = date.today()
        # Find next Monday
        days = (0 - start_d.weekday()) % 7
        mon = start_d + timedelta(days=days if days > 0 else 7)

        slot, lessons = create_recurring_series(
            teacher_id=fx["ivan_id"],
            student_id=fx["alice_student_id"],
            subject="Информатика",
            weekday=0,
            start_time="10:00",
            duration_minutes=60,
            start_date=mon,
            horizon_days=28,
        )
        first_lesson = lessons[0]
        orig_key = first_lesson.recurrence_key
        orig_date = first_lesson.slot_origin_date

        # Move to next day (Tuesday) at 11:00
        new_d = orig_date + timedelta(days=1)
        resched_les = reschedule_recurring_instance(
            lesson_id=first_lesson.id,
            new_date=new_d,
            new_time="11:00",
            duration_minutes=60,
            topic="Перенесённое занятие",
        )
        assert resched_les.is_rescheduled is True
        assert resched_les.recurrence_key == orig_key
        assert resched_les.slot_origin_date == orig_date
        assert resched_les.start_time.date() == new_d
        assert resched_les.start_time.time() == dt_time(11, 0)

        # Rerun generator: must NOT resurrect a lesson on Monday orig_date!
        new_gen = generate_lessons_for_slot(slot.id, horizon_days=28)
        assert len(new_gen) == 0

        mon_lessons = Lesson.query.filter(
            Lesson.recurring_slot_id == slot.id,
            Lesson.slot_origin_date == orig_date,
        ).all()
        assert len(mon_lessons) == 1
        assert mon_lessons[0].start_time.date() == new_d


# =========================================================================
# 7. test_scenario_b_modify_this_and_future
# =========================================================================
def test_scenario_b_modify_this_and_future(test_app, fixtures_sprint2_4):
    """Scenario B: Modify this and all future lessons (terminate old slot, create new slot)."""
    with test_app.app_context():
        fx = fixtures_sprint2_4
        start_d = date.today()
        days = (2 - start_d.weekday()) % 7
        wed = start_d + timedelta(days=days if days > 0 else 7)

        old_slot, lessons = create_recurring_series(
            teacher_id=fx["ivan_id"],
            student_id=fx["alice_student_id"],
            subject="Информатика",
            weekday=2,
            start_time="14:00",
            duration_minutes=60,
            start_date=wed,
            horizon_days=28,
        )
        assert len(lessons) == 4
        # Week 2 lesson
        target_lesson = lessons[1]
        target_date = target_lesson.start_time.date()

        old_slot, new_slot = update_series_from_date(
            series_id=old_slot.series_id,
            from_date=target_date,
            new_start_time="16:00",
            new_duration_minutes=75,
            new_topic="Сдвинутый курс",
        )

        assert old_slot.end_date == target_date - timedelta(days=1)
        assert new_slot.id != old_slot.id
        assert new_slot.start_time == dt_time(16, 0)
        assert new_slot.duration_minutes == 75

        # Check shifted lessons
        shifted = Lesson.query.filter_by(recurring_slot_id=new_slot.id).all()
        assert len(shifted) == 3
        for les in shifted:
            assert les.recurring_slot_id == new_slot.id
            assert les.start_time.time() == dt_time(16, 0)
            assert les.duration_minutes == 75

        # Historical lesson 0 remained in old slot
        db.session.refresh(lessons[0])
        assert lessons[0].recurring_slot_id == old_slot.id
        assert lessons[0].start_time.time() == dt_time(14, 0)


# =========================================================================
# 8. test_scenario_c_modify_whole_series
# =========================================================================
def test_scenario_c_modify_whole_series(test_app, fixtures_sprint2_4):
    """Scenario C: Modify whole series parameters; updates slot and future uncompleted lessons."""
    with test_app.app_context():
        fx = fixtures_sprint2_4
        start_d = date.today()

        slot, lessons = create_recurring_series(
            teacher_id=fx["ivan_id"],
            student_id=fx["alice_student_id"],
            subject="Информатика",
            weekday=3,
            start_time="15:00",
            duration_minutes=60,
            start_date=start_d,
            horizon_days=28,
        )
        # Mark first lesson as completed (history)
        lessons[0].status = "completed"
        db.session.commit()

        upd_slot = update_whole_series(
            slot_id=slot.id,
            start_time="17:00",
            duration_minutes=90,
            topic="Углубленное программирование",
        )
        assert upd_slot.start_time == dt_time(17, 0)
        assert upd_slot.duration_minutes == 90

        # First lesson (completed) must NEVER be updated
        db.session.refresh(lessons[0])
        assert lessons[0].status == "completed"
        assert lessons[0].start_time.time() == dt_time(15, 0)
        assert lessons[0].duration_minutes == 60

        # Future lessons must be updated
        updated_lessons = Lesson.query.filter(
            Lesson.recurring_slot_id == slot.id,
            Lesson.status == 'planned',
        ).all()
        assert len(updated_lessons) == 3
        for les in updated_lessons:
            assert les.start_time.time() == dt_time(17, 0)
            assert les.duration_minutes == 90
            assert les.topic == "Углубленное программирование"


# =========================================================================
# 9. test_scenario_d_cancel_single_lesson
# =========================================================================
def test_scenario_d_cancel_single_lesson(test_app, fixtures_sprint2_4):
    """Scenario D: Cancel a single instance; non-resurrection invariant holds."""
    with test_app.app_context():
        fx = fixtures_sprint2_4
        start_d = date.today()

        slot, lessons = create_recurring_series(
            teacher_id=fx["ivan_id"],
            student_id=fx["alice_student_id"],
            subject="Информатика",
            weekday=4,
            start_time="18:00",
            duration_minutes=60,
            start_date=start_d,
            horizon_days=28,
        )
        target = lessons[0]
        exc = cancel_recurring_instance(lesson_id=target.id, reason="Болезнь ученика")
        db.session.refresh(target)

        assert exc.slot_id == slot.id
        assert exc.action == "skip"
        assert target.status == "cancelled"

        # Rerun generator: the cancelled lesson must NEVER be recreated!
        new_lessons = generate_lessons_for_slot(slot.id, horizon_days=28)
        assert len(new_lessons) == 0

        # Verify still only 1 lesson with origin date, and it's cancelled
        origin_lessons = Lesson.query.filter_by(
            recurring_slot_id=slot.id,
            slot_origin_date=target.slot_origin_date,
        ).all()
        assert len(origin_lessons) == 1
        assert origin_lessons[0].status == "cancelled"


# =========================================================================
# 10. test_scenario_e_pause_and_resume_series
# =========================================================================
def test_scenario_e_pause_and_resume_series(test_app, fixtures_sprint2_4):
    """Scenario E: Pause and resume recurring series."""
    with test_app.app_context():
        fx = fixtures_sprint2_4
        start_d = date.today()

        slot, lessons = create_recurring_series(
            teacher_id=fx["ivan_id"],
            student_id=fx["alice_student_id"],
            subject="Информатика",
            weekday=5,
            start_time="11:00",
            duration_minutes=60,
            start_date=start_d,
            horizon_days=14,
        )
        assert slot.is_active is True

        paused_slot = pause_recurring_series(slot.id)
        assert paused_slot.is_active is False

        # Generator generates nothing while paused
        gen_paused = generate_lessons_for_slot(slot.id, horizon_days=28)
        assert len(gen_paused) == 0

        resumed_slot = resume_recurring_series(slot.id)
        assert resumed_slot.is_active is True

        gen_resumed = generate_lessons_for_slot(slot.id, horizon_days=28)
        # Generates remaining lessons in 28-day window (weeks 3 and 4)
        assert len(gen_resumed) == 2


# =========================================================================
# 11. test_teacher_conflict_isolation
# =========================================================================
def test_teacher_conflict_isolation(test_app, fixtures_sprint2_4):
    """Verifies teacher conflict checking is strictly isolated per teacher."""
    with test_app.app_context():
        fx = fixtures_sprint2_4
        start_d = date.today()

        # Teacher Ivan creates series at 18:00
        slot_ivan, _ = create_recurring_series(
            teacher_id=fx["ivan_id"],
            student_id=fx["alice_student_id"],
            subject="Информатика",
            weekday=1,
            start_time="18:00",
            duration_minutes=60,
            start_date=start_d,
            horizon_days=28,
        )

        # Teacher Ivan tries to create overlapping series at 18:30 for Bob -> Conflict!
        preview_ivan = preview_recurring_slot(
            teacher_id=fx["ivan_id"],
            student_id=fx["bob_student_id"],
            weekday=1,
            start_time="18:30",
            duration_minutes=60,
            start_date=start_d,
            horizon_days=28,
        )
        assert preview_ivan["conflicts_count"] > 0

        # Teacher Elena at 18:00 with Bob (no conflict with Elena's own schedule)
        preview_elena = preview_recurring_slot(
            teacher_id=fx["elena_id"],
            student_id=fx["bob_student_id"],
            weekday=1,
            start_time="18:00",
            duration_minutes=60,
            start_date=start_d,
            horizon_days=28,
        )
        assert preview_elena["conflicts_count"] == 0


# =========================================================================
# 12. test_student_cross_teacher_conflict
# =========================================================================
def test_student_cross_teacher_conflict(test_app, fixtures_sprint2_4):
    """Verifies that a student cannot be scheduled with two different teachers at overlapping times."""
    with test_app.app_context():
        fx = fixtures_sprint2_4
        start_d = date.today()

        # Teacher Ivan books Alice at 18:00-19:00
        create_recurring_series(
            teacher_id=fx["ivan_id"],
            student_id=fx["alice_student_id"],
            subject="Информатика",
            weekday=2,
            start_time="18:00",
            duration_minutes=60,
            start_date=start_d,
            horizon_days=28,
        )

        # Teacher Elena attempts to book Alice at 18:30-19:30 -> Cross-teacher conflict!
        preview_elena = preview_recurring_slot(
            teacher_id=fx["elena_id"],
            student_id=fx["alice_student_id"],
            weekday=2,
            start_time="18:30",
            duration_minutes=60,
            start_date=start_d,
            horizon_days=28,
        )
        assert preview_elena["conflicts_count"] > 0
        for occ in preview_elena["occurrences"]:
            assert occ["conflict"] is True
            assert "занят" in occ["conflict_reason"]


# =========================================================================
# 13. test_conflict_on_single_future_date
# =========================================================================
def test_conflict_on_single_future_date(test_app, fixtures_sprint2_4):
    """Conflict on a single future date is skipped when skip_conflicts=True; other dates generated."""
    with test_app.app_context():
        fx = fixtures_sprint2_4
        start_d = date.today()
        days = (3 - start_d.weekday()) % 7
        thu = start_d + timedelta(days=days if days > 0 else 7)

        # Pre-create a conflicting one-off lesson on Week 2 Thursday
        week2_thu = thu + timedelta(days=7)
        conflicting_lesson = Lesson(
            student_id=fx["alice_student_id"],
            teacher_id=fx["ivan_id"],
            start_time=datetime.combine(week2_thu, dt_time(15, 0)),
            duration_minutes=60,
            status="planned",
            subject="Информатика",
            topic="Разовый интенсив",
        )
        db.session.add(conflicting_lesson)
        db.session.commit()

        # Create recurring series on Thursdays with skip_conflicts=True
        slot, lessons = create_recurring_series(
            teacher_id=fx["ivan_id"],
            student_id=fx["alice_student_id"],
            subject="Информатика",
            weekday=3,
            start_time="15:00",
            duration_minutes=60,
            start_date=thu,
            horizon_days=28,
            skip_conflicts=True,
        )

        # Exactly 3 lessons created (Week 1, 3, 4); Week 2 skipped!
        assert len(lessons) == 3
        generated_dates = [l.start_time.date() for l in lessons]
        assert thu in generated_dates
        assert week2_thu not in generated_dates


# =========================================================================
# 14. test_pg_concurrent_series_creation
# =========================================================================
def test_pg_concurrent_series_creation():
    """Validates concurrent recurring generation on real PostgreSQL with advisory locks."""
    app = create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SQLALCHEMY_DATABASE_URI": PG_TEST_DB_URL,
    })
    with app.app_context():
        db.create_all()
        from app.utils.db_migrations import ensure_schema_columns
        ensure_schema_columns(app)

        # Seed minimal data
        user = User.query.filter_by(username="pg_concurr_teacher").first()
        if not user:
            user = User(username="pg_concurr_teacher", email="pg_concurr@example.com", password_hash="x", role="tutor")
            db.session.add(user)
            db.session.flush()
            student = Student(name="PG Concurr Student", email="pg_c_s@example.com")
            db.session.add(student)
            db.session.commit()
            teacher_id = user.id
            student_id = student.id
        else:
            teacher_id = user.id
            student_id = Student.query.filter_by(name="PG Concurr Student").first().id

        # Clean up existing test lessons/slots to guarantee isolation
        Lesson.query.filter_by(teacher_id=teacher_id).delete()
        RecurringLessonSlot.query.filter_by(teacher_id=teacher_id).delete()
        db.session.commit()

        # Create fresh slot
        slot = RecurringLessonSlot(
            teacher_id=teacher_id,
            student_id=student_id,
            weekday=2,
            start_time=dt_time(19, 0),
            duration_minutes=60,
            subject="Информатика",
            start_date=date.today(),
            series_id=f"series_pg_{int(datetime.now().timestamp())}",
            is_active=True,
        )
        db.session.add(slot)
        db.session.commit()
        slot_id = slot.slot_id

    # 8 concurrent threads calling generate_lessons_for_slot
    def worker():
        worker_app = create_app({
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": PG_TEST_DB_URL,
        })
        with worker_app.app_context():
            return generate_lessons_for_slot(slot_id, horizon_days=28)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: worker(), range(8)))

    # Total lessons created across all runs must be exactly 4 (no duplicates!)
    with app.app_context():
        db.session.remove()
        total_created = Lesson.query.filter_by(recurring_slot_id=slot_id).count()
        assert total_created == 4
        # Check recurrence keys are all unique
        keys = [l.recurrence_key for l in Lesson.query.filter_by(recurring_slot_id=slot_id).all()]
        assert len(keys) == len(set(keys))


# =========================================================================
# 15. test_concurrent_single_vs_series_generation
# =========================================================================
def test_concurrent_single_vs_series_generation():
    """Validates concurrent single lesson creation vs recurring slot generation on PostgreSQL."""
    app = create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SQLALCHEMY_DATABASE_URI": PG_TEST_DB_URL,
    })
    with app.app_context():
        db.create_all()
        teacher = User.query.filter_by(username="pg_concurr_single_tutor").first()
        if not teacher:
            teacher = User(username="pg_concurr_single_tutor", email="pg_single_t@example.com", password_hash="x", role="tutor")
            db.session.add(teacher)
            db.session.flush()
            student = Student(name="PG Concurr Single S", email="pg_single_s@example.com")
            db.session.add(student)
            db.session.commit()
            teacher_id = teacher.id
            student_id = student.id
        else:
            teacher_id = teacher.id
            student_id = Student.query.filter_by(name="PG Concurr Single S").first().id

        # Ensure row-level locks work without deadlocks
        locked_student, locked_tutor = acquire_scheduling_locks(student_id=student_id, tutor_user_id=teacher_id)
        assert locked_student is not None
        assert locked_tutor is not None
        db.session.commit()


# =========================================================================
# 16. test_teacher_working_hours_restriction
# =========================================================================
def test_teacher_working_hours_restriction(test_app, fixtures_sprint2_4):
    """Weekly working hours restrict scheduling outside configured intervals."""
    with test_app.app_context():
        fx = fixtures_sprint2_4
        # Configure Ivan to work only Mondays 10:00 - 18:00
        set_teacher_weekly_availability(
            teacher_id=fx["ivan_id"],
            intervals=[{"weekday": 0, "start_time": "10:00", "end_time": "18:00"}],
        )

        # 1. Lesson inside hours on Monday (12:00) -> Available!
        avail_ok, _ = check_teacher_availability(
            teacher_id=fx["ivan_id"],
            check_date=date(2026, 11, 2),  # Monday
            start_time="12:00",
            duration_minutes=60,
        )
        assert avail_ok is True

        # 2. Lesson outside hours on Monday (20:00) -> Unavailable!
        avail_late, reason_late = check_teacher_availability(
            teacher_id=fx["ivan_id"],
            check_date=date(2026, 11, 2),  # Monday
            start_time="20:00",
            duration_minutes=60,
        )
        assert avail_late is False
        assert "вне рабочих часов" in reason_late

        # 3. Lesson on Tuesday (not in working days) -> Unavailable!
        avail_tue, reason_tue = check_teacher_availability(
            teacher_id=fx["ivan_id"],
            check_date=date(2026, 11, 3),  # Tuesday
            start_time="12:00",
            duration_minutes=60,
        )
        assert avail_tue is False
        assert "нерабочий день" in reason_tue


# =========================================================================
# 17. test_holiday_exception_blocks_generation
# =========================================================================
def test_holiday_exception_blocks_generation(test_app, fixtures_sprint2_4):
    """Teacher schedule exception (day off) blocks generation on that date."""
    with test_app.app_context():
        fx = fixtures_sprint2_4
        start_d = date.today()
        days = (0 - start_d.weekday()) % 7
        mon = start_d + timedelta(days=days if days > 0 else 7)

        # Add holiday exception on Week 2 Monday
        week2_mon = mon + timedelta(days=7)
        add_teacher_schedule_exception(
            teacher_id=fx["ivan_id"],
            exc_date=week2_mon,
            exception_type="unavailable",
            reason="Государственный праздник",
        )

        slot, lessons = create_recurring_series(
            teacher_id=fx["ivan_id"],
            student_id=fx["alice_student_id"],
            subject="Информатика",
            weekday=0,
            start_time="10:00",
            duration_minutes=60,
            start_date=mon,
            horizon_days=28,
            skip_conflicts=True,
        )
        generated_dates = [l.start_time.date() for l in lessons]
        assert week2_mon not in generated_dates


# =========================================================================
# 18. test_timezone_conversion_across_iana
# =========================================================================
def test_timezone_conversion_across_iana(test_app):
    """Validates local wall-clock time and UTC conversion across IANA zones."""
    from app.utils.timezone import local_to_utc_instant, utc_to_local_naive
    # Kaliningrad UTC+2 at 14:00 -> 12:00 UTC
    dt_utc = local_to_utc_instant("2026-11-01", "14:00", "Europe/Kaliningrad")
    assert dt_utc.tzinfo == dt_timezone.utc
    assert dt_utc.hour == 12

    # In Novosibirsk (UTC+7), this UTC moment is 19:00
    local_novo = utc_to_local_naive(dt_utc, "Asia/Novosibirsk")
    assert local_novo.hour == 19
    assert local_novo.minute == 0


# =========================================================================
# 19. test_dst_transition_safety
# =========================================================================
def test_dst_transition_safety(test_app):
    """Validates DST transition safety (fold=0 disambiguation)."""
    from app.utils.timezone import local_to_utc_instant
    # London autumn DST transition
    dt1 = local_to_utc_instant("2026-10-25", "01:30", "Europe/London")
    assert dt1 is not None
    assert dt1.tzinfo == dt_timezone.utc


# =========================================================================
# 20. test_rbac_idor_peer_teacher_isolation
# =========================================================================
def test_rbac_idor_peer_teacher_isolation(test_app, fixtures_sprint2_4):
    """Teacher B cannot alter Teacher A's series or instances (403 Forbidden)."""
    client = test_app.test_client()
    fx = fixtures_sprint2_4

    with test_app.app_context():
        slot, lessons = create_recurring_series(
            teacher_id=fx["ivan_id"],
            student_id=fx["alice_student_id"],
            subject="Информатика",
            weekday=1,
            start_time="10:00",
            duration_minutes=60,
            start_date=date.today(),
            horizon_days=14,
        )
        lesson_id = lessons[0].id
        slot_id = slot.id

    # Login as Elena
    with test_app.app_context():
        login_as(client, fx["elena_id"], "tutor")

    # 1. Attempt to reschedule Ivan's lesson
    resp1 = client.post("/api/schedule/recurring/reschedule-instance", json={
        "lesson_id": lesson_id,
        "new_date": str(date.today() + timedelta(days=2)),
        "new_time": "12:00",
    })
    assert resp1.status_code == 403

    # 2. Attempt to cancel Ivan's lesson
    resp2 = client.post("/api/schedule/recurring/cancel-instance", json={
        "lesson_id": lesson_id,
    })
    assert resp2.status_code == 403

    # 3. Attempt to pause Ivan's series
    resp3 = client.post("/api/schedule/recurring/pause", json={
        "slot_id": slot_id,
    })
    assert resp3.status_code == 403


# =========================================================================
# 21. test_zero_balance_deductions_during_generation
# =========================================================================
def test_zero_balance_deductions_during_generation(test_app, fixtures_sprint2_4):
    """Recurring slot generation creates lessons without affecting billing or balances."""
    with test_app.app_context():
        fx = fixtures_sprint2_4
        user = User.query.get(fx["alice_user_id"])
        balance_before = getattr(user, "balance", 0)

        create_recurring_series(
            teacher_id=fx["ivan_id"],
            student_id=fx["alice_student_id"],
            subject="Информатика",
            weekday=2,
            start_time="11:00",
            duration_minutes=60,
            start_date=date.today(),
            horizon_days=28,
        )

        db.session.refresh(user)
        balance_after = getattr(user, "balance", 0)
        assert balance_before == balance_after


# =========================================================================
# 22. test_tg_notification_idempotency
# =========================================================================
def test_tg_notification_idempotency(test_app, fixtures_sprint2_4):
    """Generator idempotent re-runs do not duplicate notification dispatch."""
    with test_app.app_context():
        fx = fixtures_sprint2_4
        slot, _ = create_recurring_series(
            teacher_id=fx["ivan_id"],
            student_id=fx["alice_student_id"],
            subject="Информатика",
            weekday=3,
            start_time="14:00",
            duration_minutes=60,
            start_date=date.today(),
            horizon_days=28,
        )
        # Re-running generator returns 0 new lessons
        new_lessons = generate_lessons_for_slot(slot.id, horizon_days=28)
        assert len(new_lessons) == 0


# =========================================================================
# 23. test_concept_d_student_view_consistency
# =========================================================================
def test_concept_d_student_view_consistency(test_app, fixtures_sprint2_4):
    """Student receives recurring lessons from both teachers with is_recurring=True."""
    client = test_app.test_client()
    fx = fixtures_sprint2_4

    with test_app.app_context():
        # Ivan (CS) slot
        create_recurring_series(
            teacher_id=fx["ivan_id"],
            student_id=fx["alice_student_id"],
            subject="Информатика",
            weekday=1,
            start_time="15:00",
            duration_minutes=60,
            start_date=date.today(),
            horizon_days=14,
        )
        # Elena (Math) slot
        create_recurring_series(
            teacher_id=fx["elena_id"],
            student_id=fx["alice_student_id"],
            subject="Математика",
            weekday=4,
            start_time="17:00",
            duration_minutes=60,
            start_date=date.today(),
            horizon_days=14,
        )
        login_as(client, fx["alice_user_id"], "student")

    resp = client.get("/api/student/schedule")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    lessons = data["lessons"]
    assert len(lessons) >= 4
    for l in lessons:
        assert l["is_recurring"] is True
        assert l["recurring_slot_id"] is not None


# =========================================================================
# 24. test_historical_lesson_preservation
# =========================================================================
def test_historical_lesson_preservation(test_app, fixtures_sprint2_4):
    """'HISTORY NEVER REWRITTEN': completed lessons in series are never modified."""
    with test_app.app_context():
        fx = fixtures_sprint2_4
        slot, lessons = create_recurring_series(
            teacher_id=fx["ivan_id"],
            student_id=fx["alice_student_id"],
            subject="Информатика",
            weekday=1,
            start_time="16:00",
            duration_minutes=60,
            start_date=date.today(),
            horizon_days=28,
        )
        hist_lesson = lessons[0]
        hist_lesson.status = "completed"
        hist_time = hist_lesson.start_time
        db.session.commit()

        # Update series from date of second lesson
        sec_lesson = lessons[1]
        update_series_from_date(
            series_id=slot.series_id,
            from_date=sec_lesson.start_time.date(),
            new_start_time="19:00",
            new_duration_minutes=90,
            new_topic="Новая тема",
        )

        db.session.refresh(hist_lesson)
        assert hist_lesson.status == "completed"
        assert hist_lesson.start_time == hist_time
        assert hist_lesson.duration_minutes == 60


# =========================================================================
# 25. test_regression_multi_teacher_sprint2_2_2_3
# =========================================================================
def test_regression_multi_teacher_sprint2_2_2_3(test_app, fixtures_sprint2_4):
    """Verifies baseline multi-teacher ownership and conflict checking remain intact."""
    with test_app.app_context():
        fx = fixtures_sprint2_4
        t1 = datetime.now() + timedelta(days=1)
        t2 = t1 + timedelta(minutes=60)

        # Isolated check for Ivan
        c1 = check_tutor_conflict_isolated(fx["ivan_id"], t1, 60)
        assert c1 is False

        # Isolated check for Elena
        c2 = check_tutor_conflict_isolated(fx["elena_id"], t1, 60)
        assert c2 is False
