"""Sprint 2.4.1 Test Suite — Recurrence Integrity, Schedule Mutation Safety & Acceptance.

Invariant guarantees tested:
1. NO SILENT SKIPS. NO GHOST LESSONS. NO HISTORY MUTATION. NO DUPLICATE BOOKINGS.
2. Calendar exceptions management with existing lessons (reject, keep, cancel).
3. Explicit pause modes: Mode A (stop generation only) vs Mode B (pause & cancel future planned lessons).
4. Resume non-resurrection idempotency.
5. Safe series mutation preserving rescheduled instances and detecting collisions on new times.
6. Transparent reporting: expected_count, created_count, skipped_conflicts, skipped_availability, skipped_existing, skipped_exceptions, has_conflicts, is_partial.
7. IANA Timezones and DST wall-clock preservation.
8. PostgreSQL Concurrency Suite (8 realistic multi-worker scenarios).
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
)
from app.schedule.ownership_service import (
    acquire_scheduling_locks,
    check_tutor_conflict_isolated,
)
from app.schedule.recurrence_service import (
    add_teacher_schedule_exception,
    cancel_recurring_instance,
    check_student_conflict,
    check_teacher_availability,
    create_recurring_series,
    generate_lessons_for_slot,
    get_affected_lessons_for_exception,
    pause_recurring_series,
    preview_recurring_slot,
    reschedule_recurring_instance,
    resume_recurring_series,
    set_teacher_weekly_availability,
    update_series_from_date,
    update_whole_series,
    RecurrenceConflictError,
    TeacherAvailabilityError,
    TeacherExceptionConflictError,
)
from app.utils.timezone import parse_local_to_utc, to_viewer_tz, utc_now

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
def fixtures_sprint2_4_1(test_app):
    """Seed Ivan (tutor), Elena (tutor), Alice (student), Bob (student)."""
    with test_app.app_context():
        tutor_ivan = User(
            username="tutor_ivan_s241",
            email="ivan_s241@example.com",
            password_hash=generate_password_hash("pass"),
            role="tutor",
            full_name="Иван Сергеевич",
        )
        tutor_elena = User(
            username="tutor_elena_s241",
            email="elena_s241@example.com",
            password_hash=generate_password_hash("pass"),
            role="tutor",
            full_name="Елена Викторовна",
        )
        student_alice_user = User(
            username="student_alice_s241",
            email="alice_s241@example.com",
            password_hash=generate_password_hash("pass"),
            role="student",
            full_name="Алиса Смирнова",
        )
        student_bob_user = User(
            username="student_bob_s241",
            email="bob_s241@example.com",
            password_hash=generate_password_hash("pass"),
            role="student",
            full_name="Боб Васильев",
        )
        db.session.add_all([tutor_ivan, tutor_elena, student_alice_user, student_bob_user])
        db.session.flush()

        alice_st = Student(
            name="Алиса Смирнова",
            email="alice_s241@example.com",
            user_id=student_alice_user.id,
            mentor_id=tutor_ivan.id,
        )
        bob_st = Student(
            name="Боб Васильев",
            email="bob_s241@example.com",
            user_id=student_bob_user.id,
            mentor_id=tutor_ivan.id,
        )
        db.session.add_all([alice_st, bob_st])
        db.session.flush()

        enr_ivan_alice = Enrollment(tutor_id=tutor_ivan.id, student_id=student_alice_user.id, subject="Информатика", status="active")
        enr_elena_alice = Enrollment(tutor_id=tutor_elena.id, student_id=student_alice_user.id, subject="Математика", status="active")
        enr_ivan_bob = Enrollment(tutor_id=tutor_ivan.id, student_id=student_bob_user.id, subject="Информатика", status="active")
        db.session.add_all([enr_ivan_alice, enr_elena_alice, enr_ivan_bob])
        db.session.commit()

        return {
            "ivan_id": tutor_ivan.id,
            "elena_id": tutor_elena.id,
            "alice_student_id": alice_st.student_id,
            "bob_student_id": bob_st.student_id,
            "alice_user_id": student_alice_user.id,
            "bob_user_id": student_bob_user.id,
        }


# =========================================================================
# 1. Calendar Exception Resolution Policy (Reject, Keep, Cancel)
# =========================================================================

def test_calendar_exception_reject_when_lessons_exist(test_app, fixtures_sprint2_4_1):
    """Adding unavailable exception without resolution_action raises TeacherExceptionConflictError with affected lessons."""
    with test_app.app_context():
        fx = fixtures_sprint2_4_1
        today = date.today()
        # Find next Monday
        days = (0 - today.weekday()) % 7
        target_date = today + timedelta(days=days if days > 0 else 7)

        # Pre-create a planned lesson on target_date at 18:00
        lesson_dt_utc = parse_local_to_utc(target_date.isoformat(), "18:00", "Europe/Moscow")
        lesson = Lesson(
            student_id=fx["alice_student_id"],
            teacher_id=fx["ivan_id"],
            lesson_date=lesson_dt_utc,
            duration=60,
            status="planned",
            subject="Информатика",
        )
        db.session.add(lesson)
        db.session.commit()

        # Attempt to mark target_date as unavailable without resolution_action
        with pytest.raises(TeacherExceptionConflictError) as exc_info:
            add_teacher_schedule_exception(
                teacher_id=fx["ivan_id"],
                exception_date=target_date,
                exception_type="unavailable",
                reason="Семейные обстоятельства",
                resolution_action=None,
            )

        err = exc_info.value
        assert len(err.affected_lessons) == 1
        assert err.affected_lessons[0]["lesson_id"] == lesson.lesson_id
        assert err.affected_lessons[0]["time_local"] == "18:00"

        # Lesson remains planned
        db.session.refresh(lesson)
        assert lesson.status == "planned"


def test_calendar_exception_keep_policy(test_app, fixtures_sprint2_4_1):
    """With resolution_action='keep', exception is added and existing lesson is preserved."""
    with test_app.app_context():
        fx = fixtures_sprint2_4_1
        today = date.today()
        days = (1 - today.weekday()) % 7
        target_date = today + timedelta(days=days if days > 0 else 7)

        lesson_dt_utc = parse_local_to_utc(target_date.isoformat(), "16:00", "Europe/Moscow")
        lesson = Lesson(
            student_id=fx["alice_student_id"],
            teacher_id=fx["ivan_id"],
            lesson_date=lesson_dt_utc,
            duration=60,
            status="planned",
            subject="Информатика",
        )
        db.session.add(lesson)
        db.session.commit()

        exc = add_teacher_schedule_exception(
            teacher_id=fx["ivan_id"],
            exception_date=target_date,
            exception_type="unavailable",
            reason="День рождения",
            resolution_action="keep",
        )
        assert exc.id is not None
        db.session.refresh(lesson)
        assert lesson.status == "planned"


def test_calendar_exception_cancel_policy(test_app, fixtures_sprint2_4_1):
    """With resolution_action='cancel', affected lessons are cancelled and skip exception recorded."""
    with test_app.app_context():
        fx = fixtures_sprint2_4_1
        today = date.today()
        days = (2 - today.weekday()) % 7
        target_date = today + timedelta(days=days if days > 0 else 7)

        # Create recurring slot and generate lessons
        slot, gen_res = create_recurring_series(
            teacher_id=fx["ivan_id"],
            student_id=fx["alice_student_id"],
            weekday=2,
            time_hhmm="15:00",
            duration=60,
            start_date=target_date,
            horizon_days=14,
        )
        assert gen_res.get("created_count") >= 1
        lesson = Lesson.query.filter_by(recurring_slot_id=slot.slot_id, slot_origin_date=target_date).first()
        assert lesson is not None
        assert lesson.status == "planned"

        # Teacher adds exception with resolution_action='cancel'
        exc = add_teacher_schedule_exception(
            teacher_id=fx["ivan_id"],
            exception_date=target_date,
            exception_type="unavailable",
            reason="Больничный",
            resolution_action="cancel",
        )
        assert exc.id is not None
        db.session.refresh(lesson)
        assert lesson.status == "cancelled"

        # Subsequent generator run never resurrects the lesson
        gen2 = generate_lessons_for_slot(slot=slot, horizon_days=14)
        assert gen2.get("created_count") == 0
        db.session.refresh(lesson)
        assert lesson.status == "cancelled"


# =========================================================================
# 2. Pause Modes (A vs B) & Resume Semantics
# =========================================================================

def test_pause_mode_a_stops_generation_only(test_app, fixtures_sprint2_4_1):
    """Mode A: pauses series and stops future generation, existing planned lessons remain intact."""
    with test_app.app_context():
        fx = fixtures_sprint2_4_1
        slot, gen_res = create_recurring_series(
            teacher_id=fx["ivan_id"],
            student_id=fx["alice_student_id"],
            weekday=3,
            time_hhmm="17:00",
            duration=60,
            start_date=date.today(),
            horizon_days=21,
        )
        initial_created = gen_res.get("created_count")
        assert initial_created > 0

        # Pause Mode A
        slot = pause_recurring_series(slot.slot_id, mode="stop_generation_only")
        assert slot.is_active is False

        # Existing planned lessons remain planned
        planned_lessons = Lesson.query.filter_by(recurring_slot_id=slot.slot_id, status="planned").all()
        assert len(planned_lessons) == initial_created

        # Generator returns 0 while paused
        gen_after = generate_lessons_for_slot(slot, horizon_days=28)
        assert gen_after.get("created_count") == 0


def test_pause_mode_b_cancels_future_lessons(test_app, fixtures_sprint2_4_1):
    """Mode B: pauses series AND cancels future planned lessons with skip exceptions."""
    with test_app.app_context():
        fx = fixtures_sprint2_4_1
        slot, gen_res = create_recurring_series(
            teacher_id=fx["ivan_id"],
            student_id=fx["alice_student_id"],
            weekday=4,
            time_hhmm="14:00",
            duration=60,
            start_date=date.today(),
            horizon_days=21,
        )
        initial_created = gen_res.get("created_count")
        assert initial_created > 0

        # Pause Mode B
        slot = pause_recurring_series(slot.slot_id, mode="cancel_future_lessons", reason="Отпуск на месяц")
        assert slot.is_active is False

        # All future planned lessons are cancelled
        cancelled_lessons = Lesson.query.filter_by(recurring_slot_id=slot.slot_id, status="cancelled").all()
        assert len(cancelled_lessons) == initial_created

        # Resuming series does NOT resurrect cancelled lessons!
        slot = resume_recurring_series(slot.slot_id, generate_horizon_days=21)
        assert slot.is_active is True

        resurrected = Lesson.query.filter_by(recurring_slot_id=slot.slot_id, status="planned").all()
        assert len(resurrected) == 0


# =========================================================================
# 3. Safe Series Mutation & Rescheduled Instance Preservation
# =========================================================================

def test_safe_series_mutation_preserves_rescheduled_instances(test_app, fixtures_sprint2_4_1):
    """Series mutation updates standard future lessons but strictly preserves is_rescheduled=True lessons."""
    with test_app.app_context():
        fx = fixtures_sprint2_4_1
        slot, gen_res = create_recurring_series(
            teacher_id=fx["ivan_id"],
            student_id=fx["alice_student_id"],
            weekday=1,  # Tuesday
            time_hhmm="18:00",
            duration=60,
            start_date=date.today(),
            horizon_days=28,
        )
        lessons = Lesson.query.filter_by(recurring_slot_id=slot.slot_id, status="planned").order_by(Lesson.lesson_date.asc()).all()
        assert len(lessons) >= 2

        # Reschedule lesson #2 to Wednesday 20:00
        lesson2 = lessons[1]
        custom_date = lesson2.slot_origin_date + timedelta(days=1)
        rescheduled_lesson = reschedule_recurring_instance(
            lesson_id=lesson2.lesson_id,
            new_date=custom_date,
            new_time_hhmm="20:00",
            new_duration=90,
        )
        assert rescheduled_lesson.is_rescheduled is True
        resched_date_utc = rescheduled_lesson.lesson_date

        # Now update whole series from 18:00 to 12:00
        updated_slot = update_whole_series(
            slot_id=slot.slot_id,
            new_time_hhmm="12:00",
            new_duration=60,
        )
        assert updated_slot.time_hhmm == "12:00"

        # Check lesson #1 moved to 12:00
        db.session.refresh(lessons[0])
        local_l1 = to_viewer_tz(lessons[0].lesson_date, "Europe/Moscow")
        assert local_l1.strftime("%H:%M") == "12:00"

        # Rescheduled lesson #2 must remain at its custom 20:00 and 90 minutes!
        db.session.refresh(rescheduled_lesson)
        assert rescheduled_lesson.is_rescheduled is True
        assert rescheduled_lesson.lesson_date == resched_date_utc
        assert rescheduled_lesson.duration == 90


def test_safe_series_mutation_detects_collision_on_new_time(test_app, fixtures_sprint2_4_1):
    """If tutor is already busy at the new proposed time on any future occurrence, update_whole_series aborts with RecurrenceConflictError."""
    with test_app.app_context():
        fx = fixtures_sprint2_4_1
        slot, gen_res = create_recurring_series(
            teacher_id=fx["ivan_id"],
            student_id=fx["alice_student_id"],
            weekday=0,  # Monday
            time_hhmm="16:00",
            duration=60,
            start_date=date.today(),
            horizon_days=28,
        )
        lessons = Lesson.query.filter_by(recurring_slot_id=slot.slot_id).order_by(Lesson.lesson_date.asc()).all()
        assert len(lessons) >= 2

        # Create conflicting one-off lesson for Ivan on week 2 Monday at 19:00 with Bob
        week2_date = lessons[1].slot_origin_date
        conflict_dt = parse_local_to_utc(week2_date.isoformat(), "19:00", "Europe/Moscow")
        bob_lesson = Lesson(
            student_id=fx["bob_student_id"],
            teacher_id=fx["ivan_id"],
            lesson_date=conflict_dt,
            duration=60,
            status="planned",
            subject="Информатика",
        )
        db.session.add(bob_lesson)
        db.session.commit()

        # Attempt to move the series to 19:00 -> collision detected!
        with pytest.raises(RecurrenceConflictError) as exc_info:
            update_whole_series(
                slot_id=slot.slot_id,
                new_time_hhmm="19:00",
                new_duration=60,
            )

        err = exc_info.value
        assert len(err.conflict_details) >= 1
        assert any(c["date"] == week2_date.isoformat() for c in err.conflict_details)

        # Slot time remains unchanged (16:00)
        db.session.refresh(slot)
        assert slot.time_hhmm == "16:00"


# =========================================================================
# 4. Partial Creation & Transparent Reporting
# =========================================================================

def test_partial_creation_and_conflict_reporting(test_app, fixtures_sprint2_4_1):
    """Generator returns expected_count, created_count, skipped_conflicts, skipped_availability, is_partial, has_conflicts."""
    with test_app.app_context():
        fx = fixtures_sprint2_4_1
        today = date.today()
        days = (4 - today.weekday()) % 7
        start_d = today + timedelta(days=days if days > 0 else 7)

        # Teacher Ivan sets weekly working hours for Friday: 10:00-14:00
        set_teacher_weekly_availability(
            teacher_id=fx["ivan_id"],
            intervals=[{"weekday": 4, "start_time": "10:00", "end_time": "14:00"}],
        )

        # Create slot at 18:00 (outside working hours!)
        slot = RecurringLessonSlot(
            owner_user_id=fx["ivan_id"],
            student_id=fx["alice_student_id"],
            weekday=4,
            time_hhmm="18:00",
            duration=60,
            subject="Информатика",
            start_date=start_d,
            series_id="series_partial_test",
            timezone="Europe/Moscow",
            is_active=True,
        )
        db.session.add(slot)
        db.session.commit()

        gen_res = generate_lessons_for_slot(slot, horizon_days=21, skip_conflicts=True)
        assert gen_res.meta["expected_count"] == 3
        assert gen_res.meta["created_count"] == 0
        assert len(gen_res.meta["skipped_availability"]) == 3
        assert gen_res.meta["has_conflicts"] is True
        assert gen_res.meta["is_partial"] is True


# =========================================================================
# 5. IANA Timezones & DST Shift Wall-Clock Preservation
# =========================================================================

def test_iana_dst_transitions_wall_clock_preservation(test_app, fixtures_sprint2_4_1):
    """Berlin recurring slot preserves 10:00 wall-clock time across October DST transition."""
    with test_app.app_context():
        fx = fixtures_sprint2_4_1
        # In 2026, European DST transition occurs on Sunday October 25 (CEST UTC+2 -> CET UTC+1)
        # Recurring slot on Mondays at 10:00 Europe/Berlin
        # Before DST: Monday Oct 19, 2026 -> 10:00 CEST = 08:00 UTC
        # After DST: Monday Oct 26, 2026 -> 10:00 CET = 09:00 UTC
        oct_19 = date(2026, 10, 19)

        slot = RecurringLessonSlot(
            owner_user_id=fx["ivan_id"],
            student_id=fx["alice_student_id"],
            weekday=0,  # Monday
            time_hhmm="10:00",
            duration=60,
            subject="Информатика",
            start_date=oct_19,
            end_date=date(2026, 10, 26),
            series_id="series_dst_berlin",
            timezone="Europe/Berlin",
            is_active=True,
        )
        db.session.add(slot)
        db.session.commit()

        gen = generate_lessons_for_slot(slot, horizon_days=14, start_date=oct_19, ignore_availability=True)
        lessons = Lesson.query.filter_by(recurring_slot_id=slot.slot_id).order_by(Lesson.lesson_date.asc()).all()
        assert len(lessons) == 2

        # Lesson 1 (Oct 19, CEST = UTC+2)
        l1 = lessons[0]
        assert l1.slot_origin_date == date(2026, 10, 19)
        assert l1.lesson_date.hour == 8  # 08:00 UTC
        assert to_viewer_tz(l1.lesson_date, "Europe/Berlin").strftime("%H:%M") == "10:00"

        # Lesson 2 (Oct 26, CET = UTC+1)
        l2 = lessons[1]
        assert l2.slot_origin_date == date(2026, 10, 26)
        assert l2.lesson_date.hour == 9  # 09:00 UTC
        assert to_viewer_tz(l2.lesson_date, "Europe/Berlin").strftime("%H:%M") == "10:00"


# =========================================================================
# 6. PostgreSQL Concurrency Suite (8 Realistic Multi-Worker Scenarios)
# =========================================================================

def _get_pg_test_app():
    app = create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SQLALCHEMY_DATABASE_URI": PG_TEST_DB_URL,
    })
    return app


def _ensure_tutor_student(tutor_username: str, student_name: str, subject: str = "Информатика") -> tuple[int, int]:
    """Ensures tutor and student exist in PG test database with valid Enrollment and mentor relationship."""
    tutor = User.query.filter_by(username=tutor_username).first()
    if not tutor:
        tutor = User(username=tutor_username, email=f"{tutor_username}@example.com", password_hash="x", role="tutor")
        db.session.add(tutor)
        db.session.flush()

    stu_username = f"u_{tutor_username}_{abs(hash(student_name)) % 10000}"
    stu_user = User.query.filter_by(username=stu_username).first()
    if not stu_user:
        stu_user = User(username=stu_username, email=f"{stu_username}@example.com", password_hash="x", role="student")
        db.session.add(stu_user)
        db.session.flush()

    student = Student.query.filter_by(name=student_name).first()
    if not student:
        student = Student(name=student_name, email=f"{stu_username}@example.com", user_id=stu_user.id, mentor_id=tutor.id)
        db.session.add(student)
        db.session.flush()
    else:
        student.user_id = stu_user.id
        student.mentor_id = tutor.id

    enr = Enrollment.query.filter_by(tutor_id=tutor.id, student_id=stu_user.id).first()
    if not enr:
        enr = Enrollment(tutor_id=tutor.id, student_id=stu_user.id, subject=subject, status="active")
        db.session.add(enr)
    else:
        enr.status = "active"
        enr.subject = subject

    # Clear old test data for this tutor/student to avoid conflicts from previous test runs
    Lesson.query.filter((Lesson.teacher_id == tutor.id) | (Lesson.student_id == student.student_id)).delete()
    RecurringLessonSlot.query.filter((RecurringLessonSlot.owner_user_id == tutor.id) | (RecurringLessonSlot.student_id == student.student_id)).delete()
    TeacherScheduleException.query.filter_by(teacher_id=tutor.id).delete()
    db.session.commit()
    return tutor.id, student.student_id


def test_pg_scenario_1_concurrent_series_creation_overlap():
    """Scenario 1: 4 concurrent workers attempt to create overlapping series for same tutor/student."""
    app = _get_pg_test_app()
    with app.app_context():
        db.create_all()
        from app.utils.db_migrations import ensure_schema_columns
        ensure_schema_columns(app)

        tutor_id, student_id = _ensure_tutor_student("pg_sc1_tutor", "PG SC1 Student")

    def worker():
        w_app = _get_pg_test_app()
        with w_app.app_context():
            try:
                slot, gen = create_recurring_series(
                    teacher_id=tutor_id,
                    student_id=student_id,
                    weekday=1,
                    time_hhmm="17:00",
                    duration=60,
                    start_date=date.today(),
                    horizon_days=28,
                    skip_conflicts=False,
                )
                return gen.get("created_count", 0)
            except Exception:
                db.session.rollback()
                return 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: worker(), range(4)))

    with app.app_context():
        total_lessons = Lesson.query.filter_by(teacher_id=tutor_id).count()
        assert total_lessons == 4
        assert sum(r for r in results if r > 0) == 4


def test_pg_scenario_2_conflicting_series_race():
    """Scenario 2: 2 workers attempt to create series at the same time for same tutor with 2 different students."""
    app = _get_pg_test_app()
    with app.app_context():
        tutor_id, s1_id = _ensure_tutor_student("pg_sc2_tutor", "PG SC2 S1")
        _, s2_id = _ensure_tutor_student("pg_sc2_tutor", "PG SC2 S2")
        Lesson.query.filter_by(teacher_id=tutor_id).delete()
        RecurringLessonSlot.query.filter_by(owner_user_id=tutor_id).delete()
        db.session.commit()

    def worker(student_id):
        w_app = _get_pg_test_app()
        with w_app.app_context():
            try:
                slot, gen = create_recurring_series(
                    teacher_id=tutor_id,
                    student_id=student_id,
                    weekday=2,
                    time_hhmm="18:00",
                    duration=60,
                    start_date=date.today(),
                    horizon_days=28,
                    skip_conflicts=False,
                )
                return True
            except Exception:
                db.session.rollback()
                return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(worker, s1_id)
        f2 = executor.submit(worker, s2_id)
        r1, r2 = f1.result(), f2.result()

    with app.app_context():
        # Exactly one succeeded, one failed
        assert (r1 and not r2) or (r2 and not r1)
        total_lessons = Lesson.query.filter_by(teacher_id=tutor_id).count()
        assert total_lessons == 4


def test_pg_scenario_3_single_lesson_vs_series_generation_race():
    """Scenario 3: Single lesson booking races with series generation on the same occurrence."""
    app = _get_pg_test_app()
    with app.app_context():
        tutor_id, student_id = _ensure_tutor_student("pg_sc3_tutor", "PG SC3 Student")

        start_d = date.today()
        days = (3 - start_d.weekday()) % 7
        target_thu = start_d + timedelta(days=days if days > 0 else 7)

        slot = RecurringLessonSlot(
            owner_user_id=tutor_id,
            student_id=student_id,
            weekday=3,
            time_hhmm="16:00",
            duration=60,
            subject="Информатика",
            start_date=target_thu,
            series_id="series_sc3",
            timezone="Europe/Moscow",
            is_active=True,
        )
        db.session.add(slot)
        db.session.commit()
        slot_id = slot.slot_id

    def worker_single():
        w_app = _get_pg_test_app()
        with w_app.app_context():
            acquire_scheduling_locks(student_id, tutor_id)
            dt_utc = parse_local_to_utc(target_thu.isoformat(), "16:00", "Europe/Moscow")
            if not check_tutor_conflict_isolated(tutor_id, dt_utc, 60):
                l = Lesson(
                    student_id=student_id,
                    teacher_id=tutor_id,
                    lesson_date=dt_utc,
                    duration=60,
                    status="planned",
                    subject="Разовый урок",
                )
                db.session.add(l)
                db.session.commit()
                return "single"
            return "conflict"

    def worker_series():
        w_app = _get_pg_test_app()
        with w_app.app_context():
            s = db.session.get(RecurringLessonSlot, slot_id)
            gen = generate_lessons_for_slot(s, horizon_days=7, skip_conflicts=True)
            return gen.get("created_count", 0)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(worker_single)
        f2 = executor.submit(worker_series)
        r1, r2 = f1.result(), f2.result()

    with app.app_context():
        # Total lessons on that target_thu must be exactly 1!
        dt_utc = parse_local_to_utc(target_thu.isoformat(), "16:00", "Europe/Moscow")
        lessons_on_day = Lesson.query.filter_by(teacher_id=tutor_id, lesson_date=dt_utc).count()
        assert lessons_on_day == 1


def test_pg_scenario_4_availability_exception_vs_generation_race():
    """Scenario 4: Adding schedule exception while generator is running."""
    app = _get_pg_test_app()
    with app.app_context():
        tutor_id, student_id = _ensure_tutor_student("pg_sc4_tutor", "PG SC4 Student")

        start_d = date.today()
        days = (0 - start_d.weekday()) % 7
        target_mon = start_d + timedelta(days=days if days > 0 else 7)

        slot = RecurringLessonSlot(
            owner_user_id=tutor_id,
            student_id=student_id,
            weekday=0,
            time_hhmm="11:00",
            duration=60,
            subject="Информатика",
            start_date=target_mon,
            series_id="series_sc4",
            timezone="Europe/Moscow",
            is_active=True,
        )
        db.session.add(slot)
        db.session.commit()
        slot_id = slot.slot_id

    def worker_exc():
        w_app = _get_pg_test_app()
        with w_app.app_context():
            try:
                add_teacher_schedule_exception(
                    teacher_id=tutor_id,
                    exception_date=target_mon,
                    exception_type="unavailable",
                    reason="Отгул",
                    resolution_action="cancel",
                )
                return True
            except Exception:
                db.session.rollback()
                return False

    def worker_gen():
        w_app = _get_pg_test_app()
        with w_app.app_context():
            s = db.session.get(RecurringLessonSlot, slot_id)
            gen = generate_lessons_for_slot(s, horizon_days=7, skip_conflicts=True)
            return gen.get("created_count", 0)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(worker_exc)
        f2 = executor.submit(worker_gen)
        f1.result()
        f2.result()

    with app.app_context():
        # Either the lesson was not created or was cancelled; no active planned lesson on target_mon!
        dt_utc = parse_local_to_utc(target_mon.isoformat(), "11:00", "Europe/Moscow")
        active_lesson = Lesson.query.filter_by(
            teacher_id=tutor_id,
            lesson_date=dt_utc,
            status="planned",
        ).first()
        assert active_lesson is None


def test_pg_scenario_5_mass_reschedule_vs_single_edit_race():
    """Scenario 5: Update whole series while a worker reschedules a single lesson."""
    app = _get_pg_test_app()
    with app.app_context():
        tutor_id, student_id = _ensure_tutor_student("pg_sc5_tutor", "PG SC5 Student")

        slot, gen = create_recurring_series(
            teacher_id=tutor_id,
            student_id=student_id,
            weekday=2,
            time_hhmm="14:00",
            duration=60,
            start_date=date.today(),
            horizon_days=28,
        )
        lessons = Lesson.query.filter_by(recurring_slot_id=slot.slot_id).order_by(Lesson.lesson_date.asc()).all()
        target_lesson_id = lessons[1].lesson_id
        custom_target_date = lessons[1].slot_origin_date + timedelta(days=2)
        slot_id = slot.slot_id

    def worker_resched():
        w_app = _get_pg_test_app()
        with w_app.app_context():
            reschedule_recurring_instance(
                lesson_id=target_lesson_id,
                new_date=custom_target_date,
                new_time_hhmm="19:30",
            )

    def worker_update_whole():
        w_app = _get_pg_test_app()
        with w_app.app_context():
            update_whole_series(
                slot_id=slot_id,
                new_time_hhmm="10:00",
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(worker_resched)
        f2 = executor.submit(worker_update_whole)
        f1.result()
        f2.result()

    with app.app_context():
        # Rescheduled lesson must have is_rescheduled=True and custom date/time
        resched_l = db.session.get(Lesson, target_lesson_id)
        assert resched_l.is_rescheduled is True
        local_dt = to_viewer_tz(resched_l.lesson_date, "Europe/Moscow")
        assert local_dt.date() == custom_target_date
        assert local_dt.strftime("%H:%M") == "19:30"


def test_pg_scenario_6_cancel_series_vs_generation_race():
    """Scenario 6: Pause Mode B cancels future lessons while concurrent generator runs."""
    app = _get_pg_test_app()
    with app.app_context():
        tutor_id, student_id = _ensure_tutor_student("pg_sc6_tutor", "PG SC6 Student")

        slot, gen = create_recurring_series(
            teacher_id=tutor_id,
            student_id=student_id,
            weekday=3,
            time_hhmm="15:00",
            duration=60,
            start_date=date.today(),
            horizon_days=21,
        )
        slot_id = slot.slot_id

    def worker_pause():
        w_app = _get_pg_test_app()
        with w_app.app_context():
            pause_recurring_series(slot_id, mode="cancel_future_lessons")

    def worker_gen():
        w_app = _get_pg_test_app()
        with w_app.app_context():
            s = db.session.get(RecurringLessonSlot, slot_id)
            generate_lessons_for_slot(s, horizon_days=28)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(worker_pause)
        f2 = executor.submit(worker_gen)
        f1.result()
        f2.result()

    with app.app_context():
        # No planned lessons can remain after pause Mode B!
        planned = Lesson.query.filter_by(recurring_slot_id=slot_id, status="planned").count()
        assert planned == 0


def test_pg_scenario_7_retry_after_conflict():
    """Scenario 7: Worker encounters conflict, rolls back cleanly, and subsequent retry succeeds."""
    app = _get_pg_test_app()
    with app.app_context():
        tutor_id, student_id = _ensure_tutor_student("pg_sc7_tutor", "PG SC7 Student")

        # Pre-create lesson at 17:00
        l_date = date.today() + timedelta(days=2)
        dt_utc = parse_local_to_utc(l_date.isoformat(), "17:00", "Europe/Moscow")
        l = Lesson(student_id=student_id, teacher_id=tutor_id, lesson_date=dt_utc, duration=60, status="planned")
        db.session.add(l)
        db.session.commit()

        # Step 1: Attempt conflicting booking at 17:00 -> fails
        w_app = _get_pg_test_app()
        with w_app.app_context():
            conflicted = False
            try:
                acquire_scheduling_locks(student_id, tutor_id)
                if check_tutor_conflict_isolated(tutor_id, dt_utc, 60):
                    raise RecurrenceConflictError("Конфликт")
            except RecurrenceConflictError:
                conflicted = True
                db.session.rollback()
            assert conflicted is True

        # Step 2: Retry with non-conflicting time at 19:00 -> succeeds!
        with w_app.app_context():
            acquire_scheduling_locks(student_id, tutor_id)
            dt_retry = parse_local_to_utc(l_date.isoformat(), "19:00", "Europe/Moscow")
            assert not check_tutor_conflict_isolated(tutor_id, dt_retry, 60)
            l_retry = Lesson(student_id=student_id, teacher_id=tutor_id, lesson_date=dt_retry, duration=60, status="planned")
            db.session.add(l_retry)
            db.session.commit()
            assert l_retry.lesson_id is not None


def test_pg_scenario_8_concurrent_editing_two_teachers_shared_student():
    """Scenario 8: Two teachers attempt to book the same shared student concurrently at identical time."""
    app = _get_pg_test_app()
    with app.app_context():
        t1_id, student_id = _ensure_tutor_student("pg_sc8_t1", "PG SC8 Shared Student", subject="Информатика")
        t2 = User.query.filter_by(username="pg_sc8_t2").first()
        if not t2:
            t2 = User(username="pg_sc8_t2", email="sc8_2@example.com", password_hash="x", role="tutor")
            db.session.add(t2)
            db.session.flush()
        t2_id = t2.id
        student = db.session.get(Student, student_id)
        e2 = Enrollment.query.filter_by(tutor_id=t2_id, student_id=student.user_id).first()
        if not e2:
            e2 = Enrollment(tutor_id=t2_id, student_id=student.user_id, subject="Математика", status="active")
            db.session.add(e2)
        else:
            e2.status = "active"
        Lesson.query.filter_by(student_id=student_id).delete()
        RecurringLessonSlot.query.filter_by(student_id=student_id).delete()
        db.session.commit()

    def worker_teacher(teacher_id):
        w_app = _get_pg_test_app()
        with w_app.app_context():
            try:
                slot, gen = create_recurring_series(
                    teacher_id=teacher_id,
                    student_id=student_id,
                    weekday=4,
                    time_hhmm="16:00",
                    duration=60,
                    start_date=date.today(),
                    horizon_days=28,
                    skip_conflicts=False,
                )
                return True
            except Exception:
                db.session.rollback()
                return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(worker_teacher, t1_id)
        f2 = executor.submit(worker_teacher, t2_id)
        r1, r2 = f1.result(), f2.result()

    with app.app_context():
        # Exactly one teacher succeeds; zero double bookings for shared student!
        assert (r1 and not r2) or (r2 and not r1)
        student_lessons = Lesson.query.filter_by(student_id=student_id).count()
        assert student_lessons == 4

