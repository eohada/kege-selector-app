"""Real PostgreSQL Concurrency and Transaction Isolation Test Suite (Sprint 2.3.1).

Validates scheduling row-level locks, race condition elimination, and deadlock safety
using an isolated real PostgreSQL database instance with concurrent connections.
"""
from __future__ import annotations

import concurrent.futures
from datetime import datetime, timedelta, timezone as dt_timezone
import time
import pytest
from werkzeug.security import generate_password_hash

from app import create_app, db
from app.models import (
    Enrollment,
    Lesson,
    Student,
    User,
    UserProfile,
)
from app.schedule.ownership_service import (
    acquire_scheduling_locks,
    check_tutor_conflict_isolated,
)
from tests.v2.conftest import login_as

PG_TEST_DB_URL = "postgresql://postgres@/boostudy_test?host=/tmp/pg_socket&port=54329"


@pytest.fixture(scope="module")
def pg_app():
    """Provides a Flask test app bound to the real isolated PostgreSQL instance."""
    app = create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SQLALCHEMY_DATABASE_URI": PG_TEST_DB_URL,
    })
    with app.app_context():
        db.create_all()
        from app.utils.db_migrations import ensure_schema_columns
        ensure_schema_columns(app)
        yield app


@pytest.fixture
def pg_fixtures(pg_app):
    """Seeds test teachers, students, and enrollments in clean PostgreSQL state."""
    with pg_app.app_context():
        db.session.rollback()
        db.session.remove()
        db.engine.dispose()
        from sqlalchemy import text
        db.session.execute(text('TRUNCATE TABLE "Lessons", "Enrollments", "Students", "UserProfiles", "Users" RESTART IDENTITY CASCADE'))
        db.session.commit()

        # Teachers
        tutor_ivan = User(
            username="tutor_ivan_pg_s231",
            email="ivan_pg_s231@example.com",
            password_hash=generate_password_hash("pass"),
            role="tutor",
            full_name="Иван Сергеевич",
        )
        tutor_elena = User(
            username="tutor_elena_pg_s231",
            email="elena_pg_s231@example.com",
            password_hash=generate_password_hash("pass"),
            role="tutor",
            full_name="Елена Петровна",
        )
        # Admin
        admin_user = User(
            username="admin_pg_s231",
            email="admin_pg_s231@example.com",
            password_hash=generate_password_hash("pass"),
            role="creator",
            full_name="Администратор",
        )
        db.session.add_all([tutor_ivan, tutor_elena, admin_user])
        db.session.flush()

        p_ivan = UserProfile(user_id=tutor_ivan.id, first_name="Иван", last_name="Сергеевич")
        p_elena = UserProfile(user_id=tutor_elena.id, first_name="Елена", last_name="Петровна")
        db.session.add_all([p_ivan, p_elena])

        # Students
        alice_user = User(
            username="alice_pg_s231",
            email="alice_pg_s231@example.com",
            password_hash=generate_password_hash("pass"),
            role="student",
            full_name="Алиса Мульти",
        )
        bob_user = User(
            username="bob_pg_s231",
            email="bob_pg_s231@example.com",
            password_hash=generate_password_hash("pass"),
            role="student",
            full_name="Боб Соло",
        )
        db.session.add_all([alice_user, bob_user])
        db.session.flush()

        alice_student = Student(
            user_id=alice_user.id,
            name="Алиса Мульти",
            lessons_balance=10,
            is_active=True,
        )
        bob_student = Student(
            user_id=bob_user.id,
            name="Боб Соло",
            mentor_id=tutor_ivan.id,
            lessons_balance=5,
            is_active=True,
        )
        db.session.add_all([alice_student, bob_student])
        db.session.flush()

        enr_alice_cs = Enrollment(
            student_id=alice_user.id,
            tutor_id=tutor_ivan.id,
            subject="Информатика",
            status="active",
        )
        enr_alice_math = Enrollment(
            student_id=alice_user.id,
            tutor_id=tutor_elena.id,
            subject="Математика",
            status="active",
        )
        enr_bob_cs = Enrollment(
            student_id=bob_user.id,
            tutor_id=tutor_ivan.id,
            subject="Информатика",
            status="active",
        )
        db.session.add_all([enr_alice_cs, enr_alice_math, enr_bob_cs])
        db.session.commit()

        fx_data = {
            "tutor_ivan_id": tutor_ivan.id,
            "tutor_elena_id": tutor_elena.id,
            "admin_id": admin_user.id,
            "alice_user_id": alice_user.id,
            "alice_student_id": alice_student.student_id,
            "bob_user_id": bob_user.id,
            "bob_student_id": bob_student.student_id,
        }
        yield fx_data
        db.session.rollback()
        db.session.remove()
        db.engine.dispose()


# ==============================================================================
# TEST 1: Real concurrent creation race on shared student (17:00-18:00 vs 17:30-18:30)
# ==============================================================================
def test_pg_concurrent_shared_student_booking_race(pg_app, pg_fixtures):
    """Two teachers attempt to concurrently book the same student in overlapping slots.
    PostgreSQL with_for_update() must serialize them: exactly one succeeds (200),
    the other receives 409 Conflict.
    """
    fx = pg_fixtures
    target_date = (datetime.now(dt_timezone.utc) + timedelta(days=10)).strftime("%Y-%m-%d")

    def run_teacher_a():
        client = pg_app.test_client()
        login_as(client, fx["tutor_ivan_id"], "tutor")
        payload = {
            "student_id": fx["alice_student_id"],
            "subject": "Информатика",
            "topic": "Параллельный урок Ивана",
            "lesson_date": target_date,
            "time": "17:00",
            "duration": 60,
        }
        return client.post("/api/schedule/create_lesson", json=payload)

    def run_teacher_b():
        client = pg_app.test_client()
        login_as(client, fx["tutor_elena_id"], "tutor")
        payload = {
            "student_id": fx["alice_student_id"],
            "subject": "Математика",
            "topic": "Параллельный урок Елены",
            "lesson_date": target_date,
            "time": "17:30",
            "duration": 60,
        }
        return client.post("/api/schedule/create_lesson", json=payload)

    # Launch concurrently in two threads
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f_a = executor.submit(run_teacher_a)
        f_b = executor.submit(run_teacher_b)
        resp_a = f_a.result()
        resp_b = f_b.result()

    statuses = [resp_a.status_code, resp_b.status_code]
    assert 200 in statuses, "At least one booking must succeed"
    assert 409 in statuses, "The conflicting booking must be rejected with 409 Conflict"

    # Verify that in PostgreSQL database exactly ONE lesson was committed
    with pg_app.app_context():
        lessons = Lesson.query.filter(
            Lesson.student_id == fx["alice_student_id"],
            Lesson.lesson_date >= datetime.strptime(target_date, "%Y-%m-%d"),
            Lesson.lesson_date < datetime.strptime(target_date, "%Y-%m-%d") + timedelta(days=1),
        ).all()
        assert len(lessons) == 1, f"Expected exactly 1 lesson in PostgreSQL, got {len(lessons)}"


# ==============================================================================
# TEST 2: Two teachers, two different students, same time -> both succeed
# ==============================================================================
def test_pg_concurrent_different_students_same_time_both_succeed(pg_app, pg_fixtures):
    fx = pg_fixtures
    target_date = (datetime.now(dt_timezone.utc) + timedelta(days=11)).strftime("%Y-%m-%d")

    def run_teacher_a():
        client = pg_app.test_client()
        login_as(client, fx["tutor_ivan_id"], "tutor")
        return client.post("/api/schedule/create_lesson", json={
            "student_id": fx["bob_student_id"],
            "subject": "Информатика",
            "topic": "Урок с Бобом",
            "lesson_date": target_date,
            "time": "14:00",
            "duration": 60,
        })

    def run_teacher_b():
        client = pg_app.test_client()
        login_as(client, fx["tutor_elena_id"], "tutor")
        return client.post("/api/schedule/create_lesson", json={
            "student_id": fx["alice_student_id"],
            "subject": "Математика",
            "topic": "Урок с Алисой",
            "lesson_date": target_date,
            "time": "14:00",
            "duration": 60,
        })

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f_a = executor.submit(run_teacher_a)
        f_b = executor.submit(run_teacher_b)
        resp_a = f_a.result()
        resp_b = f_b.result()

    assert resp_a.status_code == 200, f"Teacher A creation failed: {resp_a.get_json()}"
    assert resp_b.status_code == 200, f"Teacher B creation failed: {resp_b.get_json()}"

    with pg_app.app_context():
        count = Lesson.query.filter(
            Lesson.lesson_date >= datetime.strptime(target_date, "%Y-%m-%d"),
            Lesson.lesson_date < datetime.strptime(target_date, "%Y-%m-%d") + timedelta(days=1),
        ).count()
        assert count == 2


# ==============================================================================
# TEST 3: Two concurrent requests to same teacher for overlapping time
# ==============================================================================
def test_pg_concurrent_same_teacher_overlapping_slots(pg_app, pg_fixtures):
    """Ivan is booked concurrently for Bob (10:00-11:00) and Alice (10:30-11:30).
    Only one must succeed; the other must receive 409 with 'В это время у вас уже есть занятие'.
    """
    fx = pg_fixtures
    target_date = (datetime.now(dt_timezone.utc) + timedelta(days=12)).strftime("%Y-%m-%d")

    def book_bob():
        client = pg_app.test_client()
        login_as(client, fx["tutor_ivan_id"], "tutor")
        return client.post("/api/schedule/create_lesson", json={
            "student_id": fx["bob_student_id"],
            "subject": "Информатика",
            "topic": "Иван - Боб",
            "lesson_date": target_date,
            "time": "10:00",
            "duration": 60,
        })

    def book_alice():
        client = pg_app.test_client()
        login_as(client, fx["tutor_ivan_id"], "tutor")
        return client.post("/api/schedule/create_lesson", json={
            "student_id": fx["alice_student_id"],
            "subject": "Информатика",
            "topic": "Иван - Алиса",
            "lesson_date": target_date,
            "time": "10:30",
            "duration": 60,
        })

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(book_bob)
        f2 = executor.submit(book_alice)
        r1 = f1.result()
        r2 = f2.result()

    statuses = [r1.status_code, r2.status_code]
    assert 200 in statuses
    assert 409 in statuses


# ==============================================================================
# TEST 4: Concurrent creation and reschedule into the same slot
# ==============================================================================
def test_pg_concurrent_create_and_reschedule_collision(pg_app, pg_fixtures):
    """One transaction creates a new lesson at 16:00, while another concurrently
    reschedules an existing lesson to 16:00 for the same student.
    Only one must succeed; the other must receive 409.
    """
    fx = pg_fixtures
    base_date = datetime.now(dt_timezone.utc) + timedelta(days=13)
    target_date_str = base_date.strftime("%Y-%m-%d")

    # Pre-create an initial lesson for Ivan at 09:00
    with pg_app.app_context():
        init_lesson = Lesson(
            student_id=fx["alice_student_id"],
            teacher_id=fx["tutor_ivan_id"],
            subject="Информатика",
            topic="Урок для переноса",
            lesson_date=base_date.replace(hour=9, minute=0, second=0, microsecond=0),
            status="planned",
            duration=60,
        )
        db.session.add(init_lesson)
        db.session.commit()
        init_lid = init_lesson.lesson_id

    def do_create():
        client = pg_app.test_client()
        login_as(client, fx["tutor_elena_id"], "tutor")
        return client.post("/api/schedule/create_lesson", json={
            "student_id": fx["alice_student_id"],
            "subject": "Математика",
            "topic": "Новый урок в 16:00",
            "lesson_date": target_date_str,
            "time": "16:00",
            "duration": 60,
        })

    def do_reschedule():
        client = pg_app.test_client()
        login_as(client, fx["tutor_ivan_id"], "tutor")
        return client.post(
            f"/schedule/reschedule/{init_lid}",
            data={"new_date": target_date_str, "new_time": "16:00"},
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f_create = executor.submit(do_create)
        f_resched = executor.submit(do_reschedule)
        r_create = f_create.result()
        r_resched = f_resched.result()

    statuses = [r_create.status_code, r_resched.status_code]
    assert 200 in statuses
    assert 409 in statuses


# ==============================================================================
# TEST 4B: Two concurrent reschedules to the same slot
# ==============================================================================
def test_pg_concurrent_two_reschedules_to_same_slot(pg_app, pg_fixtures):
    """Two teachers attempt to concurrently reschedule two different existing lessons
    into the exact same target slot for shared student Alice.
    Row-level locking must serialize the rescheduling: exactly one succeeds (200),
    the other receives 409 Conflict ('В это время ученик занят на другом уроке').
    """
    fx = pg_fixtures
    base_date = datetime.now(dt_timezone.utc) + timedelta(days=16)
    target_date_str = base_date.strftime("%Y-%m-%d")

    with pg_app.app_context():
        l_ivan = Lesson(
            student_id=fx["alice_student_id"],
            teacher_id=fx["tutor_ivan_id"],
            subject="Информатика",
            topic="Урок Ивана для переноса",
            lesson_date=base_date.replace(hour=8, minute=0, second=0, microsecond=0),
            status="planned",
            duration=60,
        )
        l_elena = Lesson(
            student_id=fx["alice_student_id"],
            teacher_id=fx["tutor_elena_id"],
            subject="Математика",
            topic="Урок Елены для переноса",
            lesson_date=base_date.replace(hour=9, minute=0, second=0, microsecond=0),
            status="planned",
            duration=60,
        )
        db.session.add_all([l_ivan, l_elena])
        db.session.commit()
        ivan_lid = l_ivan.lesson_id
        elena_lid = l_elena.lesson_id

    def resched_ivan():
        client = pg_app.test_client()
        login_as(client, fx["tutor_ivan_id"], "tutor")
        return client.post(
            f"/schedule/reschedule/{ivan_lid}",
            data={"new_date": target_date_str, "new_time": "18:00"},
        )

    def resched_elena():
        client = pg_app.test_client()
        login_as(client, fx["tutor_elena_id"], "tutor")
        return client.post(
            f"/schedule/reschedule/{elena_lid}",
            data={"new_date": target_date_str, "new_time": "18:00"},
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(resched_ivan)
        f2 = executor.submit(resched_elena)
        r1 = f1.result()
        r2 = f2.result()

    statuses = [r1.status_code, r2.status_code]
    assert 200 in statuses
    assert 409 in statuses


# ==============================================================================
# TEST 5: Slot freed immediately after cancellation
# ==============================================================================
def test_pg_cancel_frees_slot_for_rebooking(pg_app, pg_fixtures):
    fx = pg_fixtures
    target_date_str = (datetime.now(dt_timezone.utc) + timedelta(days=14)).strftime("%Y-%m-%d")
    client = pg_app.test_client()
    login_as(client, fx["tutor_ivan_id"], "tutor")

    # 1. Create lesson at 15:00
    r_create = client.post("/api/schedule/create_lesson", json={
        "student_id": fx["bob_student_id"],
        "subject": "Информатика",
        "topic": "Первый урок",
        "lesson_date": target_date_str,
        "time": "15:00",
        "duration": 60,
    })
    assert r_create.status_code == 200
    lid = r_create.get_json()["lesson_id"]

    # 2. Cancel lesson
    r_cancel = client.post(f"/api/schedule/update_lesson/{lid}", json={"status": "cancelled"})
    assert r_cancel.status_code == 200

    # 3. New booking in the exact same slot must succeed
    r_rebook = client.post("/api/schedule/create_lesson", json={
        "student_id": fx["bob_student_id"],
        "subject": "Информатика",
        "topic": "Второй урок в освобожденный слот",
        "lesson_date": target_date_str,
        "time": "15:00",
        "duration": 60,
    })
    assert r_rebook.status_code == 200


# ==============================================================================
# TEST 6: Deadlock prevention with consistent lock ordering
# ==============================================================================
def test_pg_deadlock_safety_under_bidirectional_concurrency(pg_app, pg_fixtures):
    """Verifies that concurrent operations locking Student and Tutor rows
    never experience PostgreSQL deadlocks (SQLSTATE 40P01).
    """
    fx = pg_fixtures

    def op1():
        with pg_app.app_context():
            try:
                # Acquire locks for Alice & Ivan
                st_lock, u_lock = acquire_scheduling_locks(fx["alice_student_id"], fx["tutor_ivan_id"])
                time.sleep(0.05)
                db.session.commit()
                return True
            finally:
                db.session.remove()

    def op2():
        with pg_app.app_context():
            try:
                # Acquire locks for Alice & Elena
                st_lock, u_lock = acquire_scheduling_locks(fx["alice_student_id"], fx["tutor_elena_id"])
                time.sleep(0.05)
                db.session.commit()
                return True
            finally:
                db.session.remove()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(op1)
        f2 = executor.submit(op2)
        assert f1.result() is True
        assert f2.result() is True


# ==============================================================================
# TEST 7: Retry after conflict succeeds cleanly
# ==============================================================================
def test_pg_retry_after_conflict_succeeds(pg_app, pg_fixtures):
    fx = pg_fixtures
    client_ivan = pg_app.test_client()
    login_as(client_ivan, fx["tutor_ivan_id"], "tutor")

    client_elena = pg_app.test_client()
    login_as(client_elena, fx["tutor_elena_id"], "tutor")

    target_date_str = (datetime.now(dt_timezone.utc) + timedelta(days=15)).strftime("%Y-%m-%d")

    # Ivan books 12:00
    r1 = client_ivan.post("/api/schedule/create_lesson", json={
        "student_id": fx["alice_student_id"],
        "subject": "Информатика",
        "topic": "Урок 12:00",
        "lesson_date": target_date_str,
        "time": "12:00",
        "duration": 60,
    })
    assert r1.status_code == 200

    # Elena tries 12:30 -> gets 409 Conflict
    r2 = client_elena.post("/api/schedule/create_lesson", json={
        "student_id": fx["alice_student_id"],
        "subject": "Математика",
        "topic": "Конфликтный урок 12:30",
        "lesson_date": target_date_str,
        "time": "12:30",
        "duration": 60,
    })
    assert r2.status_code == 409

    # Elena retries with 14:00 (non-conflicting) -> MUST SUCCEED
    r3 = client_elena.post("/api/schedule/create_lesson", json={
        "student_id": fx["alice_student_id"],
        "subject": "Математика",
        "topic": "Успешный повтор 14:00",
        "lesson_date": target_date_str,
        "time": "14:00",
        "duration": 60,
    })
    assert r3.status_code == 200
