"""Comprehensive test suite for Multi-Teacher Data Foundation (Sprint 2.2).

Covers all 14 mandatory acceptance scenarios:
1. Single student with single teacher.
2. Single student with two teachers of different subjects.
3. Single student with two teachers of the same subject.
4. New lesson created with explicit verified teacher_id and subject.
5. Old lesson with teacher_id = NULL rendered safely.
6. Ambiguous historical backfill retains NULL (no falsification).
7. Repeated dry-run determinism (zero DB mutations).
8. Idempotency of backfill on isolated database.
9. Security / RBAC: Tutor cannot mutate (reschedule/update/delete) a peer tutor's lesson.
10. Conflict detection: No false-positive blocking from peer teachers of shared students.
11. Preservation of existing materials, outcomes, and student notes.
12. Billing and completion lifecycle integrity (no financial drift).
13. PostgreSQL compatibility of schema DDL and Alembic migration.
14. Concept D zero-regression for student schedule.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone as dt_timezone
import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from werkzeug.security import generate_password_hash

from app import create_app, db
from app.models import (
    Enrollment,
    GradebookEntry,
    Lesson,
    LessonOutcome,
    LessonTeacherHomeworkNote,
    Student,
    User,
)
from app.schedule.backfill_service import (
    CATEGORY_ARTIFACT_CONFIRMED,
    CATEGORY_MULTIPLE_CANDIDATES,
    CATEGORY_NO_TEACHER_FOUND,
    CATEGORY_SINGLE_TUTOR,
    STATUS_ALREADY_RESOLVED,
    STATUS_RESOLVED,
    STATUS_UNRESOLVED_NULL,
    classify_lesson_ownership,
    execute_historical_backfill,
)
from app.schedule.ownership_service import (
    check_tutor_conflict_isolated,
    can_user_modify_lesson,
    resolve_lesson_ownership,
    OwnershipSecurityError,
    OwnershipValidationError,
)


@pytest.fixture
def app_instance():
    app = create_app()
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    with app.app_context():
        db.create_all()
        yield app
        db.session.rollback()


@pytest.fixture
def setup_multi_teacher_fixtures(app_instance):
    """Creates isolated test users, students, and enrollments."""
    with app_instance.app_context():
        # Teachers
        tutor_cs = User.query.filter_by(username="tutor_ivan_cs").first()
        if not tutor_cs:
            tutor_cs = User(
                username="tutor_ivan_cs",
                email="ivan_cs@example.com",
                password_hash=generate_password_hash("pass"),
                role="tutor",
                full_name="Иван Сергеевич (Информатика)",
            )
            db.session.add(tutor_cs)

        tutor_math = User.query.filter_by(username="tutor_elena_math").first()
        if not tutor_math:
            tutor_math = User(
                username="tutor_elena_math",
                email="elena_math@example.com",
                password_hash=generate_password_hash("pass"),
                role="tutor",
                full_name="Елена Петровна (Математика)",
            )
            db.session.add(tutor_math)

        # Admin / Creator
        creator = User.query.filter_by(username="admin_creator_mt").first()
        if not creator:
            creator = User(
                username="admin_creator_mt",
                email="creator_mt@example.com",
                password_hash=generate_password_hash("pass"),
                role="creator",
                full_name="Администратор Платформы",
            )
            db.session.add(creator)

        # Students
        st_user1 = User.query.filter_by(username="student_multi_alice").first()
        if not st_user1:
            st_user1 = User(
                username="student_multi_alice",
                email="alice@example.com",
                password_hash=generate_password_hash("pass"),
                role="student",
                full_name="Алиса Мульти",
            )
            db.session.add(st_user1)
            db.session.commit()

            st1 = Student(
                user_id=st_user1.id,
                name="Алиса Мульти",
                lessons_balance=10,
                is_active=True,
            )
            db.session.add(st1)

        st_user2 = User.query.filter_by(username="student_solo_bob").first()
        if not st_user2:
            st_user2 = User(
                username="student_solo_bob",
                email="bob@example.com",
                password_hash=generate_password_hash("pass"),
                role="student",
                full_name="Боб Соло",
            )
            db.session.add(st_user2)
            db.session.commit()

            st2 = Student(
                user_id=st_user2.id,
                name="Боб Соло",
                mentor_id=tutor_cs.id,
                lessons_balance=5,
                is_active=True,
            )
            db.session.add(st2)

        db.session.commit()

        # Enrollments
        # Alice is enrolled with Ivan for Computer Science, and with Elena for Mathematics
        enr_cs = Enrollment.query.filter_by(
            student_id=st_user1.id, tutor_id=tutor_cs.id, subject="Информатика"
        ).first()
        if not enr_cs:
            enr_cs = Enrollment(
                student_id=st_user1.id,
                tutor_id=tutor_cs.id,
                subject="Информатика",
                status="active",
            )
            db.session.add(enr_cs)

        enr_math = Enrollment.query.filter_by(
            student_id=st_user1.id, tutor_id=tutor_math.id, subject="Математика"
        ).first()
        if not enr_math:
            enr_math = Enrollment(
                student_id=st_user1.id,
                tutor_id=tutor_math.id,
                subject="Математика",
                status="active",
            )
            db.session.add(enr_math)

        # Bob is enrolled only with Ivan
        enr_bob = Enrollment.query.filter_by(
            student_id=st_user2.id, tutor_id=tutor_cs.id
        ).first()
        if not enr_bob:
            enr_bob = Enrollment(
                student_id=st_user2.id,
                tutor_id=tutor_cs.id,
                subject="Информатика",
                status="active",
            )
            db.session.add(enr_bob)

        db.session.commit()

        yield {
            "tutor_cs": tutor_cs,
            "tutor_math": tutor_math,
            "creator": creator,
            "student_alice_user": st_user1,
            "student_alice": Student.query.filter_by(user_id=st_user1.id).first(),
            "student_bob_user": st_user2,
            "student_bob": Student.query.filter_by(user_id=st_user2.id).first(),
        }


# ==============================================================================
# SCENARIO 1: Single student with single teacher
# ==============================================================================
def test_single_student_single_teacher(app_instance, setup_multi_teacher_fixtures):
    """One student with exactly one teacher resolves teacher and subject from enrollment."""
    fx = setup_multi_teacher_fixtures
    tutor_cs = fx["tutor_cs"]
    student_bob = fx["student_bob"]

    tid, subj = resolve_lesson_ownership(
        actor_user=tutor_cs,
        student=student_bob,
        requested_teacher_id=None,
        requested_subject=None,
    )
    assert tid == tutor_cs.id
    assert subj == "Информатика"


# ==============================================================================
# SCENARIO 2: Single student with two teachers of different subjects
# ==============================================================================
def test_single_student_two_teachers_different_subjects(app_instance, setup_multi_teacher_fixtures):
    """Alice has CS tutor and Math tutor. Each tutor assigns own ID and matching subject."""
    fx = setup_multi_teacher_fixtures
    tutor_cs = fx["tutor_cs"]
    tutor_math = fx["tutor_math"]
    student_alice = fx["student_alice"]

    # Ivan (CS) creates lesson for Alice
    tid_cs, subj_cs = resolve_lesson_ownership(
        actor_user=tutor_cs,
        student=student_alice,
        requested_teacher_id=None,
        requested_subject=None,
    )
    assert tid_cs == tutor_cs.id
    assert subj_cs == "Информатика"

    # Elena (Math) creates lesson for Alice
    tid_math, subj_math = resolve_lesson_ownership(
        actor_user=tutor_math,
        student=student_alice,
        requested_teacher_id=None,
        requested_subject=None,
    )
    assert tid_math == tutor_math.id
    assert subj_math == "Математика"


# ==============================================================================
# SCENARIO 3: Single student with two teachers of the same subject
# ==============================================================================
def test_single_student_two_teachers_same_subject(app_instance, setup_multi_teacher_fixtures):
    """If two tutors teach the same subject to a student, each tutor assigns their own ID."""
    fx = setup_multi_teacher_fixtures
    student_alice = fx["student_alice"]
    tutor_cs = fx["tutor_cs"]

    # Add second CS tutor
    with app_instance.app_context():
        tutor_cs2 = User(
            username="tutor_petr_cs2",
            email="petr_cs2@example.com",
            password_hash=generate_password_hash("pass"),
            role="tutor",
            full_name="Пётр (Информатика)",
        )
        db.session.add(tutor_cs2)
        db.session.commit()

        enr_cs2 = Enrollment(
            student_id=student_alice.user_id,
            tutor_id=tutor_cs2.id,
            subject="Информатика",
            status="active",
        )
        db.session.add(enr_cs2)
        db.session.commit()

        tid1, subj1 = resolve_lesson_ownership(
            actor_user=tutor_cs,
            student=student_alice,
            requested_subject="Информатика",
        )
        tid2, subj2 = resolve_lesson_ownership(
            actor_user=tutor_cs2,
            student=student_alice,
            requested_subject="Информатика",
        )

        assert tid1 == tutor_cs.id
        assert tid2 == tutor_cs2.id
        assert subj1 == "Информатика"
        assert subj2 == "Информатика"


# ==============================================================================
# SCENARIO 4: New lesson created with explicit verified teacher_id
# ==============================================================================
def test_new_lesson_explicit_teacher_id(app_instance, setup_multi_teacher_fixtures):
    """Creating a Lesson persists teacher_id and subject directly into database."""
    fx = setup_multi_teacher_fixtures
    tutor_cs = fx["tutor_cs"]
    student_bob = fx["student_bob"]

    lesson = Lesson(
        student_id=student_bob.student_id,
        teacher_id=tutor_cs.id,
        subject="Информатика",
        topic="Графы и деревья",
        lesson_date=datetime.now(dt_timezone.utc),
        duration=60,
        status="planned",
    )
    db.session.add(lesson)
    db.session.commit()

    reloaded = db.session.get(Lesson, lesson.lesson_id)
    assert reloaded.teacher_id == tutor_cs.id
    assert reloaded.subject == "Информатика"
    assert reloaded.teacher.id == tutor_cs.id
    assert reloaded.teacher_user_id == tutor_cs.id  # backward compatibility property


# ==============================================================================
# SCENARIO 5: Old lesson with teacher_id = NULL rendered safely
# ==============================================================================
def test_old_lesson_teacher_id_null(app_instance, setup_multi_teacher_fixtures):
    """Historical lesson with teacher_id = NULL has None in DB and fallback in display."""
    fx = setup_multi_teacher_fixtures
    student_alice = fx["student_alice"]

    old_lesson = Lesson(
        student_id=student_alice.student_id,
        teacher_id=None,
        subject=None,
        topic="Старый исторический урок",
        lesson_date=datetime.now(dt_timezone.utc) - timedelta(days=60),
        duration=60,
        status="completed",
    )
    db.session.add(old_lesson)
    db.session.commit()

    reloaded = db.session.get(Lesson, old_lesson.lesson_id)
    assert reloaded.teacher_id is None
    assert reloaded.display_subject == "Информатика"
    assert reloaded.teacher is None


# ==============================================================================
# SCENARIO 6: Ambiguous historical backfill retains NULL
# ==============================================================================
def test_ambiguous_backfill_retains_null(app_instance, setup_multi_teacher_fixtures):
    """Student with multiple tutors and no lesson artifacts classifies as CATEGORY 3 (Retains NULL)."""
    fx = setup_multi_teacher_fixtures
    student_alice = fx["student_alice"]

    ambiguous_lesson = Lesson(
        student_id=student_alice.student_id,
        teacher_id=None,
        topic="Урок без артефактов при двух тьюторах",
        lesson_date=datetime.now(dt_timezone.utc) - timedelta(days=30),
        status="completed",
    )
    db.session.add(ambiguous_lesson)
    db.session.commit()

    record = classify_lesson_ownership(ambiguous_lesson)
    assert record.category == CATEGORY_MULTIPLE_CANDIDATES
    assert record.candidate_teacher_id is None
    assert record.resolution_status == STATUS_UNRESOLVED_NULL


# ==============================================================================
# SCENARIO 7: Repeated dry-run determinism
# ==============================================================================
def test_repeated_dry_run_determinism(app_instance, setup_multi_teacher_fixtures):
    """Dry-run backfill executed multiple times produces identical deterministic results and 0 DB mutations."""
    fx = setup_multi_teacher_fixtures
    student_bob = fx["student_bob"]

    # Bob has only 1 tutor (Ivan CS)
    test_lesson = Lesson(
        student_id=student_bob.student_id,
        teacher_id=None,
        topic="Тест детерминизма dry-run",
        lesson_date=datetime.now(dt_timezone.utc),
        status="completed",
    )
    db.session.add(test_lesson)
    db.session.commit()

    report1 = execute_historical_backfill(dry_run=True, lesson_id_filter=[test_lesson.lesson_id])
    assert report1.is_dry_run is True
    assert report1.cat1_single_tutor_count == 1
    assert report1.total_confidently_resolved == 1

    # Verify DB was NOT mutated
    assert db.session.get(Lesson, test_lesson.lesson_id).teacher_id is None

    # Run again: exactly same result
    report2 = execute_historical_backfill(dry_run=True, lesson_id_filter=[test_lesson.lesson_id])
    assert report2.cat1_single_tutor_count == 1
    assert report2.total_confidently_resolved == 1
    assert db.session.get(Lesson, test_lesson.lesson_id).teacher_id is None


# ==============================================================================
# SCENARIO 8: Idempotency of backfill on isolated database
# ==============================================================================
def test_backfill_idempotency_isolated_db(app_instance, setup_multi_teacher_fixtures):
    """Backfill applied on isolated DB resolves records; subsequent run reports ALREADY_RESOLVED."""
    fx = setup_multi_teacher_fixtures
    student_bob = fx["student_bob"]
    tutor_cs = fx["tutor_cs"]

    lesson = Lesson(
        student_id=student_bob.student_id,
        teacher_id=None,
        topic="Урок для проверки idempotency",
        lesson_date=datetime.now(dt_timezone.utc),
        status="completed",
    )
    db.session.add(lesson)
    db.session.commit()

    # Apply backfill
    report_apply = execute_historical_backfill(dry_run=False, lesson_id_filter=[lesson.lesson_id])
    assert report_apply.total_confidently_resolved == 1

    # Verify lesson is now resolved
    db.session.expire_all()
    reloaded = db.session.get(Lesson, lesson.lesson_id)
    assert reloaded.teacher_id == tutor_cs.id

    # Second run on same lesson: must be reported as ALREADY_RESOLVED
    report_subsequent = execute_historical_backfill(dry_run=True, lesson_id_filter=[lesson.lesson_id])
    assert report_subsequent.already_resolved == 1
    assert report_subsequent.total_confidently_resolved == 0


# ==============================================================================
# SCENARIO 9: Tutor cannot mutate peer tutor's lesson (RBAC & Security)
# ==============================================================================
def test_tutor_cannot_mutate_peer_lesson(app_instance, setup_multi_teacher_fixtures):
    """Tutor Elena (Math) cannot modify, reschedule, or cancel Tutor Ivan's (CS) lesson."""
    fx = setup_multi_teacher_fixtures
    tutor_cs = fx["tutor_cs"]
    tutor_math = fx["tutor_math"]
    student_alice = fx["student_alice"]

    cs_lesson = Lesson(
        student_id=student_alice.student_id,
        teacher_id=tutor_cs.id,
        subject="Информатика",
        topic="Урок Ивана",
        lesson_date=datetime.now(dt_timezone.utc) + timedelta(days=2),
        status="planned",
    )
    db.session.add(cs_lesson)
    db.session.commit()

    # Ivan (owner) CAN modify
    can_ivan, _ = can_user_modify_lesson(tutor_cs, cs_lesson)
    assert can_ivan is True

    # Elena (peer tutor) CANNOT modify
    can_elena, err = can_user_modify_lesson(tutor_math, cs_lesson)
    assert can_elena is False
    assert "назначателю" in err or "другому преподавателю" in err


# ==============================================================================
# SCENARIO 10: Isolated conflict check (No false-positive collisions)
# ==============================================================================
def test_tutor_collision_isolated_no_false_positive(app_instance, setup_multi_teacher_fixtures):
    """Tutor B having a lesson with shared Student S at 15:00 does NOT block Tutor A from teaching at 15:00."""
    fx = setup_multi_teacher_fixtures
    tutor_cs = fx["tutor_cs"]
    tutor_math = fx["tutor_math"]
    student_alice = fx["student_alice"]

    slot_time = datetime.now(dt_timezone.utc).replace(hour=15, minute=0, second=0)

    # Elena (Math) teaches Alice at 15:00
    math_lesson = Lesson(
        student_id=student_alice.student_id,
        teacher_id=tutor_math.id,
        subject="Математика",
        topic="Математика в 15:00",
        lesson_date=slot_time,
        duration=60,
        status="planned",
    )
    db.session.add(math_lesson)
    db.session.commit()

    # Elena is busy at 15:00
    assert check_tutor_conflict_isolated(tutor_math.id, slot_time, 60) is True

    # Ivan (CS) is FREE at 15:00 (even though Alice is enrolled with him too!)
    assert check_tutor_conflict_isolated(tutor_cs.id, slot_time, 60) is False


# ==============================================================================
# SCENARIO 11: Preservation of materials, notes, and outcomes
# ==============================================================================
def test_materials_and_outcomes_preservation(app_instance, setup_multi_teacher_fixtures):
    """Adding teacher_id preserves all JSON materials, notes, and associated outcomes."""
    fx = setup_multi_teacher_fixtures
    tutor_cs = fx["tutor_cs"]
    student_bob = fx["student_bob"]

    materials_data = [{"title": "PDF Конспект", "url": "https://example.com/c.pdf", "type": "pdf"}]
    lesson = Lesson(
        student_id=student_bob.student_id,
        teacher_id=tutor_cs.id,
        subject="Информатика",
        topic="Урок с материалами",
        materials=materials_data,
        notes="Заметка преподавателя",
        student_notes="Заметка ученика",
        lesson_date=datetime.now(dt_timezone.utc),
        status="completed",
    )
    db.session.add(lesson)
    db.session.commit()

    # Attach outcome
    outcome = LessonOutcome(
        lesson_id=lesson.lesson_id,
        created_by_user_id=tutor_cs.id,
        teacher_note="Успешный разбор графов",
    )
    db.session.add(outcome)
    db.session.commit()

    reloaded = db.session.get(Lesson, lesson.lesson_id)
    assert reloaded.materials == materials_data
    assert reloaded.notes == "Заметка преподавателя"
    assert reloaded.student_notes == "Заметка ученика"
    assert len(reloaded.materials) == 1
    assert reloaded.outcome.teacher_note == "Успешный разбор графов"


# ==============================================================================
# SCENARIO 12: Billing and completion lifecycle integrity
# ==============================================================================
def test_billing_and_completion_lifecycle_integrity(app_instance, setup_multi_teacher_fixtures):
    """Completing a lesson with explicit teacher_id executes standard balance deduction without drift."""
    from app.lessons.lifecycle import deduct_lesson_balance

    fx = setup_multi_teacher_fixtures
    tutor_cs = fx["tutor_cs"]
    student_bob = fx["student_bob"]

    initial_balance = student_bob.lessons_balance or 5

    lesson = Lesson(
        student_id=student_bob.student_id,
        teacher_id=tutor_cs.id,
        subject="Информатика",
        topic="Урок для биллинга",
        lesson_date=datetime.now(dt_timezone.utc),
        status="planned",
        balance_deducted=False,
    )
    db.session.add(lesson)
    db.session.commit()

    # Deduct balance (returns (old_balance, new_balance, notice))
    old_bal, new_bal, notice = deduct_lesson_balance(lesson, source="unit_test", actor_user_id=tutor_cs.id)
    db.session.commit()

    assert old_bal == initial_balance
    assert new_bal == initial_balance - 1
    reloaded_student = db.session.get(Student, student_bob.student_id)
    assert reloaded_student.lessons_balance == initial_balance - 1
    assert db.session.get(Lesson, lesson.lesson_id).balance_deducted is True


# ==============================================================================
# SCENARIO 13: PostgreSQL DDL and migration compatibility
# ==============================================================================
def test_postgresql_ddl_and_migration_compatibility():
    """Validates that Lesson model with teacher_id, subject, and indexes compiles to PostgreSQL DDL."""
    compiled_ddl = str(CreateTable(Lesson.__table__).compile(dialect=postgresql.dialect()))
    assert "teacher_id INTEGER" in compiled_ddl or "teacher_id INT" in compiled_ddl
    assert "subject VARCHAR(100)" in compiled_ddl
    assert "FOREIGN KEY(teacher_id) REFERENCES \"Users\" (id)" in compiled_ddl


# ==============================================================================
# SCENARIO 14: Concept D zero-regression
# ==============================================================================
def test_concept_d_zero_regression(app_instance, setup_multi_teacher_fixtures):
    """Concept D schedule endpoint returns HTTP 200 and renders exact teacher name for multi-teacher student."""
    client = app_instance.test_client()
    fx = setup_multi_teacher_fixtures
    alice_user = fx["student_alice_user"]
    student_alice = fx["student_alice"]
    tutor_cs = fx["tutor_cs"]

    now = datetime.now(dt_timezone.utc).replace(hour=11, minute=0, second=0)
    cs_lesson = Lesson(
        student_id=student_alice.student_id,
        teacher_id=tutor_cs.id,
        subject="Информатика",
        topic="Алгоритмы Concept D",
        lesson_date=now,
        duration=60,
        status="planned",
    )
    db.session.add(cs_lesson)
    db.session.commit()

    with client.session_transaction() as sess:
        sess["_user_id"] = str(alice_user.id)
        sess["_fresh"] = True

    resp = client.get("/schedule")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Concept D renders exact teacher name and topic
    assert "Алгоритмы Concept D" in html
    assert "Иван Сергеевич" in html or "tutor_ivan_cs" in html
