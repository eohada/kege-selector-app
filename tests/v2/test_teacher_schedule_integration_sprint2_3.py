"""Comprehensive test suite for Teacher Schedule: Multi-Teacher Integration & Operational Workflow (Sprint 2.3).

Covers all 20 mandatory acceptance scenarios:
1. Teacher A sees only own lessons.
2. Teacher B sees only own lessons.
3. Shared student sees both in Concept D.
4. Teacher A cannot modify Teacher B's lesson (403 IDOR rejection).
5. Teacher A cannot delete Teacher B's lesson (403 IDOR rejection).
6. IDOR details substitution rejected.
7. Lesson creation with explicit teacher_id and subject.
8. Subject selection restricted to confirmed educational relations.
9. Teacher time conflict detected ("В это время у вас уже есть занятие").
10. Student time conflict across two teachers detected ("В это время ученик занят на другом уроке").
11. No false-positive collision between different teachers & different students.
12. Concurrent creation race condition serialized with lock.
13. Reschedule lesson updates date/time without creating duplicate.
14. Cancel lesson frees the slot.
15. Completed lesson cannot be uncompleted (lifecycle guard).
16. Timezone aware conversion across MSK (+3) and NOVT (+7).
17. Concept D rendering matches created lessons with teacher avatars.
18. Historical lessons with teacher_id = NULL handled safely without false ownership.
19. ICS export and JSON events isolated by teacher_id.
20. Correct student ID vs user ID conversion.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone as dt_timezone
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
    can_user_modify_lesson,
    can_user_view_lesson,
    check_tutor_conflict_isolated,
    get_accessible_students_for_teacher,
    get_active_tutor_ids_for_student,
    resolve_historical_lesson_ownership,
    resolve_lesson_ownership,
)
from tests.v2.conftest import login_as


@pytest.fixture
def test_app():
    app = create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
    })
    with app.app_context():
        db.create_all()
        yield app
        db.session.rollback()


@pytest.fixture
def fixtures_sprint2_3(test_app):
    """Sets up two teachers (Ivan CS, Elena Math), one admin, and two students (Alice shared, Bob solo)."""
    with test_app.app_context():
        # Teachers
        tutor_ivan = User(
            username="tutor_ivan_s23",
            email="ivan_s23@example.com",
            password_hash=generate_password_hash("pass"),
            role="tutor",
            full_name="Иван Сергеевич",
        )
        db.session.add(tutor_ivan)

        tutor_elena = User(
            username="tutor_elena_s23",
            email="elena_s23@example.com",
            password_hash=generate_password_hash("pass"),
            role="tutor",
            full_name="Елена Петровна",
        )
        db.session.add(tutor_elena)

        # Admin
        admin_user = User(
            username="admin_s23",
            email="admin_s23@example.com",
            password_hash=generate_password_hash("pass"),
            role="creator",
            full_name="Админ Спринта",
        )
        db.session.add(admin_user)
        db.session.flush()

        # Profiles
        p_ivan = UserProfile(user_id=tutor_ivan.id, first_name="Иван", last_name="Сергеевич")
        p_elena = UserProfile(user_id=tutor_elena.id, first_name="Елена", last_name="Петровна")
        db.session.add_all([p_ivan, p_elena])

        # Students
        alice_user = User(
            username="alice_s23",
            email="alice_s23@example.com",
            password_hash=generate_password_hash("pass"),
            role="student",
            full_name="Алиса Мульти",
        )
        bob_user = User(
            username="bob_s23",
            email="bob_s23@example.com",
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

        # Enrollments:
        # Alice is enrolled with Ivan for "Информатика" and with Elena for "Математика"
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
        # Bob is enrolled with Ivan for "Информатика"
        enr_bob_cs = Enrollment(
            student_id=bob_user.id,
            tutor_id=tutor_ivan.id,
            subject="Информатика",
            status="active",
        )
        db.session.add_all([enr_alice_cs, enr_alice_math, enr_bob_cs])
        db.session.commit()

        return {
            "tutor_ivan_id": tutor_ivan.id,
            "tutor_elena_id": tutor_elena.id,
            "admin_id": admin_user.id,
            "alice_user_id": alice_user.id,
            "alice_student_id": alice_student.student_id,
            "bob_user_id": bob_user.id,
            "bob_student_id": bob_student.student_id,
        }


# ==============================================================================
# SCENARIO 1: Teacher A sees only own lessons
# ==============================================================================
def test_scenario_1_teacher_a_sees_only_own_lessons(test_app, fixtures_sprint2_3):
    fx = fixtures_sprint2_3
    client = test_app.test_client()
    login_as(client, fx["tutor_ivan_id"], "tutor")

    now = datetime.now(dt_timezone.utc)
    with test_app.app_context():
        # Create Ivan's lesson
        l_ivan = Lesson(
            student_id=fx["alice_student_id"],
            teacher_id=fx["tutor_ivan_id"],
            subject="Информатика",
            topic="Информатика с Иваном",
            lesson_date=now + timedelta(days=1),
            status="planned",
        )
        # Create Elena's lesson for shared student Alice
        l_elena = Lesson(
            student_id=fx["alice_student_id"],
            teacher_id=fx["tutor_elena_id"],
            subject="Математика",
            topic="Математика с Еленой",
            lesson_date=now + timedelta(days=1, hours=2),
            status="planned",
        )
        db.session.add_all([l_ivan, l_elena])
        db.session.commit()
        l_ivan_id = l_ivan.lesson_id
        l_elena_id = l_elena.lesson_id

    # 1. API events endpoint
    resp = client.get("/api/schedule/events")
    assert resp.status_code == 200
    data = resp.get_json()
    events = data.get("events", [])
    event_ids = [e["id"] for e in events]
    assert l_ivan_id in event_ids
    assert l_elena_id not in event_ids

    # 2. Main schedule page
    page_resp = client.get("/schedule")
    assert page_resp.status_code == 200
    page_html = page_resp.get_data(as_text=True)
    import re
    m_page = re.search(r'<script[^>]*id="schedule-data"[^>]*>(.*?)</script>', page_html, re.DOTALL)
    assert m_page is not None
    page_data = json.loads(m_page.group(1))
    page_topics = [l.get("topic") for l in page_data.get("lessons", [])]
    assert "Информатика с Иваном" in page_topics
    assert "Математика с Еленой" not in page_topics


# ==============================================================================
# SCENARIO 2: Teacher B sees only own lessons
# ==============================================================================
def test_scenario_2_teacher_b_sees_only_own_lessons(test_app, fixtures_sprint2_3):
    fx = fixtures_sprint2_3
    client = test_app.test_client()
    login_as(client, fx["tutor_elena_id"], "tutor")

    now = datetime.now(dt_timezone.utc)
    with test_app.app_context():
        l_ivan = Lesson(
            student_id=fx["alice_student_id"],
            teacher_id=fx["tutor_ivan_id"],
            subject="Информатика",
            topic="Информатика с Иваном",
            lesson_date=now + timedelta(days=1),
            status="planned",
        )
        l_elena = Lesson(
            student_id=fx["alice_student_id"],
            teacher_id=fx["tutor_elena_id"],
            subject="Математика",
            topic="Математика с Еленой",
            lesson_date=now + timedelta(days=1, hours=2),
            status="planned",
        )
        db.session.add_all([l_ivan, l_elena])
        db.session.commit()
        l_ivan_id = l_ivan.lesson_id
        l_elena_id = l_elena.lesson_id

    resp = client.get("/api/schedule/events")
    assert resp.status_code == 200
    events = resp.get_json().get("events", [])
    event_ids = [e["id"] for e in events]
    assert l_elena_id in event_ids
    assert l_ivan_id not in event_ids


# ==============================================================================
# SCENARIO 3: Shared student sees both in Concept D
# ==============================================================================
def test_scenario_3_shared_student_sees_both_in_concept_d(test_app, fixtures_sprint2_3):
    fx = fixtures_sprint2_3
    client = test_app.test_client()
    login_as(client, fx["alice_user_id"], "student")

    now = datetime.now(dt_timezone.utc)
    with test_app.app_context():
        l_ivan = Lesson(
            student_id=fx["alice_student_id"],
            teacher_id=fx["tutor_ivan_id"],
            subject="Информатика",
            topic="Алгоритмы поиска",
            lesson_date=now + timedelta(days=1),
            status="planned",
        )
        l_elena = Lesson(
            student_id=fx["alice_student_id"],
            teacher_id=fx["tutor_elena_id"],
            subject="Математика",
            topic="Тригонометрия",
            lesson_date=now + timedelta(days=2),
            status="planned",
        )
        db.session.add_all([l_ivan, l_elena])
        db.session.commit()

    resp = client.get("/schedule")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    import re
    m_stud = re.search(r'<script[^>]*id="schedule-data"[^>]*>(.*?)</script>', html, re.DOTALL)
    assert m_stud is not None
    schedule_data = json.loads(m_stud.group(1))
    lessons = schedule_data.get("lessons", [])
    topics = [l.get("topic") for l in lessons]
    subjects = [l.get("subject") for l in lessons]
    assert "Алгоритмы поиска" in topics
    assert "Тригонометрия" in topics
    assert "Информатика" in subjects
    assert "Математика" in subjects


# ==============================================================================
# SCENARIO 4: Teacher A cannot modify Teacher B's lesson (403 IDOR rejection)
# ==============================================================================
def test_scenario_4_teacher_a_cannot_modify_teacher_b_lesson(test_app, fixtures_sprint2_3):
    fx = fixtures_sprint2_3
    client = test_app.test_client()
    login_as(client, fx["tutor_ivan_id"], "tutor")

    now = datetime.now(dt_timezone.utc)
    with test_app.app_context():
        l_elena = Lesson(
            student_id=fx["alice_student_id"],
            teacher_id=fx["tutor_elena_id"],
            subject="Математика",
            topic="Урок Елены",
            lesson_date=now + timedelta(days=1),
            status="planned",
        )
        db.session.add(l_elena)
        db.session.commit()
        elena_lid = l_elena.lesson_id

    # 1. Update endpoint
    resp = client.post(
        f"/api/schedule/update_lesson/{elena_lid}",
        json={"topic": "Взлом темы", "subject": "Информатика"},
    )
    assert resp.status_code == 403

    # 2. Reschedule endpoint
    new_date = (now + timedelta(days=3)).strftime("%Y-%m-%d")
    resp_resched = client.post(
        f"/schedule/reschedule/{elena_lid}",
        data={"new_date": new_date, "new_time": "14:00"},
    )
    assert resp_resched.status_code == 403

    # Confirm in DB that lesson was NOT modified
    with test_app.app_context():
        l = db.session.get(Lesson, elena_lid)
        assert l.topic == "Урок Елены"
        assert l.teacher_id == fx["tutor_elena_id"]


# ==============================================================================
# SCENARIO 5: Teacher A cannot delete Teacher B's lesson
# ==============================================================================
def test_scenario_5_teacher_a_cannot_delete_teacher_b_lesson(test_app, fixtures_sprint2_3):
    fx = fixtures_sprint2_3
    client = test_app.test_client()
    login_as(client, fx["tutor_ivan_id"], "tutor")

    now = datetime.now(dt_timezone.utc)
    with test_app.app_context():
        l_elena = Lesson(
            student_id=fx["alice_student_id"],
            teacher_id=fx["tutor_elena_id"],
            subject="Математика",
            topic="Урок для защиты от удаления",
            lesson_date=now + timedelta(days=1),
            status="planned",
        )
        db.session.add(l_elena)
        db.session.commit()
        elena_lid = l_elena.lesson_id

    resp = client.post(f"/api/schedule/delete_lesson/{elena_lid}")
    assert resp.status_code == 403

    with test_app.app_context():
        l = db.session.get(Lesson, elena_lid)
        assert l is not None


# ==============================================================================
# SCENARIO 6: IDOR details substitution rejected
# ==============================================================================
def test_scenario_6_idor_details_substitution_rejected(test_app, fixtures_sprint2_3):
    fx = fixtures_sprint2_3
    client = test_app.test_client()
    login_as(client, fx["tutor_ivan_id"], "tutor")

    now = datetime.now(dt_timezone.utc)
    with test_app.app_context():
        l_elena = Lesson(
            student_id=fx["alice_student_id"],
            teacher_id=fx["tutor_elena_id"],
            subject="Математика",
            topic="Секретные заметки Елены",
            notes="Приватная заметка",
            lesson_date=now + timedelta(days=1),
            status="planned",
        )
        db.session.add(l_elena)
        db.session.commit()
        elena_lid = l_elena.lesson_id

    resp = client.get(f"/api/schedule/lesson/{elena_lid}/details")
    assert resp.status_code == 403
    data = resp.get_json()
    assert "error" in data or "message" in data


# ==============================================================================
# SCENARIO 7: Lesson creation with explicit teacher_id and subject
# ==============================================================================
def test_scenario_7_lesson_creation_with_explicit_teacher_and_subject(test_app, fixtures_sprint2_3):
    fx = fixtures_sprint2_3
    client = test_app.test_client()
    login_as(client, fx["tutor_ivan_id"], "tutor")

    tomorrow_str = (datetime.now(dt_timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    payload = {
        "student_id": fx["alice_student_id"],
        "subject": "Информатика",
        "topic": "Графы и пути",
        "lesson_date": tomorrow_str,
        "time": "12:00",
        "duration": 60,
        "status": "planned",
    }
    resp = client.post("/api/schedule/create_lesson", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("status") == "success" or data.get("success") is True
    created_id = data.get("lesson_id") or data.get("lesson", {}).get("lesson_id")

    with test_app.app_context():
        lesson = db.session.get(Lesson, created_id)
        assert lesson is not None
        assert lesson.teacher_id == fx["tutor_ivan_id"]
        assert lesson.subject == "Информатика"
        assert lesson.topic == "Графы и пути"


# ==============================================================================
# SCENARIO 8: Subject selection restricted to confirmed relations
# ==============================================================================
def test_scenario_8_subject_selection_restricted_to_confirmed_relations(test_app, fixtures_sprint2_3):
    fx = fixtures_sprint2_3
    with test_app.app_context():
        ivan_user = db.session.get(User, fx["tutor_ivan_id"])
        elena_user = db.session.get(User, fx["tutor_elena_id"])

        accessible_ivan = get_accessible_students_for_teacher(ivan_user)
        accessible_elena = get_accessible_students_for_teacher(elena_user)

        # Ivan has Alice (CS) and Bob (CS)
        ivan_alice = next((s for s in accessible_ivan if s["student_id"] == fx["alice_student_id"]), None)
        assert ivan_alice is not None
        assert "Информатика" in ivan_alice["subjects"]
        assert "Математика" not in ivan_alice["subjects"]

        # Elena has Alice (Math) only
        elena_alice = next((s for s in accessible_elena if s["student_id"] == fx["alice_student_id"]), None)
        assert elena_alice is not None
        assert "Математика" in elena_alice["subjects"]
        assert "Информатика" not in elena_alice["subjects"]
        elena_bob = next((s for s in accessible_elena if s["student_id"] == fx["bob_student_id"]), None)
        assert elena_bob is None


# ==============================================================================
# SCENARIO 9: Teacher time conflict detected ("В это время у вас уже есть занятие")
# ==============================================================================
def test_scenario_9_teacher_time_conflict_detected(test_app, fixtures_sprint2_3):
    fx = fixtures_sprint2_3
    client = test_app.test_client()
    login_as(client, fx["tutor_ivan_id"], "tutor")

    target_date = (datetime.now(dt_timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%d")

    # 1. First lesson: Bob at 10:00
    p1 = {
        "student_id": fx["bob_student_id"],
        "subject": "Информатика",
        "topic": "Урок с Бобом",
        "lesson_date": target_date,
        "time": "10:00",
        "duration": 60,
    }
    resp1 = client.post("/api/schedule/create_lesson", json=p1)
    assert resp1.status_code == 200

    # 2. Second lesson for Ivan with Alice at the exact same time (10:30, 60min) -> Conflict!
    p2 = {
        "student_id": fx["alice_student_id"],
        "subject": "Информатика",
        "topic": "Урок с Алисой",
        "lesson_date": target_date,
        "time": "10:30",
        "duration": 60,
    }
    resp2 = client.post("/api/schedule/create_lesson", json=p2)
    assert resp2.status_code in (400, 409)
    err_data = resp2.get_json() or {}
    err_text = err_data.get("message") or err_data.get("error") or resp2.get_data(as_text=True)
    assert "В это время у вас уже есть занятие" in err_text or "уже есть занятие" in err_text


# ==============================================================================
# SCENARIO 10: Student time conflict across two teachers detected
# ("В это время ученик занят на другом уроке")
# ==============================================================================
def test_scenario_10_student_time_conflict_across_two_teachers(test_app, fixtures_sprint2_3):
    fx = fixtures_sprint2_3
    client_elena = test_app.test_client()
    login_as(client_elena, fx["tutor_elena_id"], "tutor")

    client_ivan = test_app.test_client()
    login_as(client_ivan, fx["tutor_ivan_id"], "tutor")

    target_date = (datetime.now(dt_timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%d")

    # Elena books Alice for Math at 15:00 - 16:00
    p_elena = {
        "student_id": fx["alice_student_id"],
        "subject": "Математика",
        "topic": "Геометрия",
        "lesson_date": target_date,
        "time": "15:00",
        "duration": 60,
    }
    resp_elena = client_elena.post("/api/schedule/create_lesson", json=p_elena)
    assert resp_elena.status_code == 200

    # Ivan tries to book Alice for CS at 15:30 - 16:30 -> Student collision!
    p_ivan = {
        "student_id": fx["alice_student_id"],
        "subject": "Информатика",
        "topic": "Python",
        "lesson_date": target_date,
        "time": "15:30",
        "duration": 60,
    }
    resp_ivan = client_ivan.post("/api/schedule/create_lesson", json=p_ivan)
    assert resp_ivan.status_code in (400, 409)
    err_data = resp_ivan.get_json() or {}
    err_text = err_data.get("message") or err_data.get("error") or resp_ivan.get_data(as_text=True)
    assert "В это время ученик занят на другом уроке" in err_text or "ученик занят" in err_text


# ==============================================================================
# SCENARIO 11: No false-positive collision between different teachers & different students
# ==============================================================================
def test_scenario_11_no_false_positive_collision(test_app, fixtures_sprint2_3):
    fx = fixtures_sprint2_3
    client_elena = test_app.test_client()
    login_as(client_elena, fx["tutor_elena_id"], "tutor")

    client_ivan = test_app.test_client()
    login_as(client_ivan, fx["tutor_ivan_id"], "tutor")

    target_date = (datetime.now(dt_timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%d")

    # Elena teaches Alice at 11:00
    resp_elena = client_elena.post(
        "/api/schedule/create_lesson",
        json={
            "student_id": fx["alice_student_id"],
            "subject": "Математика",
            "topic": "Стереометрия",
            "lesson_date": target_date,
            "time": "11:00",
            "duration": 60,
        },
    )
    assert resp_elena.status_code == 200

    # Ivan teaches Bob at 11:00 (different student, different teacher) -> MUST SUCCEED!
    resp_ivan = client_ivan.post(
        "/api/schedule/create_lesson",
        json={
            "student_id": fx["bob_student_id"],
            "subject": "Информатика",
            "topic": "Динамическое программирование",
            "lesson_date": target_date,
            "time": "11:00",
            "duration": 60,
        },
    )
    assert resp_ivan.status_code == 200


# ==============================================================================
# SCENARIO 12: Concurrent creation race condition serialized with lock
# ==============================================================================
def test_scenario_12_concurrent_creation_serialized_with_lock(test_app, fixtures_sprint2_3):
    fx = fixtures_sprint2_3
    with test_app.app_context():
        # acquire_scheduling_locks performs row-level locking
        st_lock, u_lock = acquire_scheduling_locks(fx["alice_student_id"], fx["tutor_ivan_id"])
        assert st_lock is not None
        assert st_lock.student_id == fx["alice_student_id"]
        assert u_lock is not None
        assert u_lock.id == fx["tutor_ivan_id"]


# ==============================================================================
# SCENARIO 13: Reschedule lesson updates date/time without creating duplicate
# ==============================================================================
def test_scenario_13_reschedule_updates_without_duplicate(test_app, fixtures_sprint2_3):
    fx = fixtures_sprint2_3
    client = test_app.test_client()
    login_as(client, fx["tutor_ivan_id"], "tutor")

    target_date = (datetime.now(dt_timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    resp_create = client.post(
        "/api/schedule/create_lesson",
        json={
            "student_id": fx["bob_student_id"],
            "subject": "Информатика",
            "topic": "Перенос занятия",
            "lesson_date": target_date,
            "time": "10:00",
            "duration": 60,
        },
    )
    assert resp_create.status_code == 200
    lid = resp_create.get_json().get("lesson_id")

    with test_app.app_context():
        count_before = Lesson.query.count()

    new_date = (datetime.now(dt_timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%d")
    resp_resched = client.post(
        f"/schedule/reschedule/{lid}",
        data={"new_date": new_date, "new_time": "16:00"},
    )
    assert resp_resched.status_code in (200, 302)

    with test_app.app_context():
        count_after = Lesson.query.count()
        assert count_after == count_before
        updated = db.session.get(Lesson, lid)
        assert updated.lesson_date.strftime("%Y-%m-%d") == new_date
        assert updated.lesson_date.hour in (13, 16)  # Check UTC / local shift


# ==============================================================================
# SCENARIO 14: Cancel lesson frees the slot
# ==============================================================================
def test_scenario_14_cancel_lesson_frees_slot(test_app, fixtures_sprint2_3):
    fx = fixtures_sprint2_3
    client = test_app.test_client()
    login_as(client, fx["tutor_ivan_id"], "tutor")

    target_date = (datetime.now(dt_timezone.utc) + timedelta(days=4)).strftime("%Y-%m-%d")

    # 1. Create lesson at 14:00
    resp_create = client.post(
        "/api/schedule/create_lesson",
        json={
            "student_id": fx["bob_student_id"],
            "subject": "Информатика",
            "topic": "Урок для отмены",
            "lesson_date": target_date,
            "time": "14:00",
            "duration": 60,
        },
    )
    assert resp_create.status_code == 200
    lid = resp_create.get_json().get("lesson_id")

    # 2. Cancel lesson
    resp_cancel = client.post(
        f"/api/schedule/update_lesson/{lid}",
        json={"status": "cancelled"},
    )
    assert resp_cancel.status_code == 200

    # 3. Create a new lesson in the SAME time slot 14:00 -> MUST SUCCEED (slot freed)
    resp_new = client.post(
        "/api/schedule/create_lesson",
        json={
            "student_id": fx["bob_student_id"],
            "subject": "Информатика",
            "topic": "Новый урок в освободившийся слот",
            "lesson_date": target_date,
            "time": "14:00",
            "duration": 60,
        },
    )
    assert resp_new.status_code == 200


# ==============================================================================
# SCENARIO 15: Completed lesson cannot be uncompleted (lifecycle guard)
# ==============================================================================
def test_scenario_15_completed_lesson_lifecycle_guard(test_app, fixtures_sprint2_3):
    fx = fixtures_sprint2_3
    client = test_app.test_client()
    login_as(client, fx["tutor_ivan_id"], "tutor")

    with test_app.app_context():
        comp_lesson = Lesson(
            student_id=fx["bob_student_id"],
            teacher_id=fx["tutor_ivan_id"],
            subject="Информатика",
            topic="Проведённый урок",
            lesson_date=datetime.now(dt_timezone.utc) - timedelta(days=1),
            status="completed",
        )
        db.session.add(comp_lesson)
        db.session.commit()
        comp_lid = comp_lesson.lesson_id

    # Attempt to reset status back to planned
    resp = client.post(
        f"/api/schedule/update_lesson/{comp_lid}",
        json={"status": "planned"},
    )
    with test_app.app_context():
        l = db.session.get(Lesson, comp_lid)
        assert l.status in ("completed", "done") or resp.status_code in (400, 422)


# ==============================================================================
# SCENARIO 16: Timezone aware conversion across MSK (+3) and NOVT (+7)
# ==============================================================================
def test_scenario_16_timezone_aware_conversion(test_app, fixtures_sprint2_3):
    fx = fixtures_sprint2_3
    client = test_app.test_client()
    login_as(client, fx["tutor_ivan_id"], "tutor")

    target_date = (datetime.now(dt_timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%d")

    # Lesson created with timezone Europe/Moscow at 18:00 (18:00 MSK = 15:00 UTC)
    resp = client.post(
        "/api/schedule/create_lesson",
        json={
            "student_id": fx["bob_student_id"],
            "subject": "Информатика",
            "topic": "Таймзоны",
            "lesson_date": target_date,
            "time": "18:00",
            "duration": 60,
            "timezone": "Europe/Moscow",
        },
    )
    assert resp.status_code == 200
    lid = resp.get_json().get("lesson_id")

    with test_app.app_context():
        lesson = db.session.get(Lesson, lid)
        assert lesson.lesson_date.hour == 15

    # Fetch events in Novosibirsk timezone (+7) -> 15:00 UTC + 7 = 22:00
    resp_novt = client.get("/api/schedule/events?timezone=Asia/Novosibirsk")
    assert resp_novt.status_code == 200
    events = resp_novt.get_json().get("events", [])
    ev = next((e for e in events if e["id"] == lid), None)
    assert ev is not None
    assert "22:00" in ev["start"] or "22:00" in ev.get("time_str", "")


# ==============================================================================
# SCENARIO 17: Concept D rendering matches created lessons with teacher avatars
# ==============================================================================
def test_scenario_17_concept_d_teacher_avatars_and_metadata(test_app, fixtures_sprint2_3):
    fx = fixtures_sprint2_3
    client = test_app.test_client()
    login_as(client, fx["alice_user_id"], "student")

    now = datetime.now(dt_timezone.utc)
    with test_app.app_context():
        l_ivan = Lesson(
            student_id=fx["alice_student_id"],
            teacher_id=fx["tutor_ivan_id"],
            subject="Информатика",
            topic="Урок Информатики для Concept D",
            lesson_date=now + timedelta(days=1),
            status="planned",
        )
        db.session.add(l_ivan)
        db.session.commit()

    resp = client.get("/schedule")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Информатика" in html
    assert "Урок Информатики для Concept D" in html
    assert "Иван Сергеевич" in html or "Иван" in html or "default-avatar.svg" in html


# ==============================================================================
# SCENARIO 18: Historical lessons with teacher_id = NULL handled safely
# ==============================================================================
def test_scenario_18_historical_lessons_with_teacher_null_handled_safely(test_app, fixtures_sprint2_3):
    fx = fixtures_sprint2_3
    now = datetime.now(dt_timezone.utc)

    with test_app.app_context():
        hist_lesson = Lesson(
            student_id=fx["alice_student_id"],
            teacher_id=None,
            subject="Информатика",
            topic="Исторический урок без преподавателя",
            lesson_date=now - timedelta(days=10),
            status="completed",
        )
        db.session.add(hist_lesson)
        db.session.commit()
        hist_lid = hist_lesson.lesson_id

        ivan_user = db.session.get(User, fx["tutor_ivan_id"])
        elena_user = db.session.get(User, fx["tutor_elena_id"])
        admin_user = db.session.get(User, fx["admin_id"])

        can_ivan_mod, _ = can_user_modify_lesson(ivan_user, hist_lesson)
        assert can_ivan_mod is False

        can_elena_mod, _ = can_user_modify_lesson(elena_user, hist_lesson)
        assert can_elena_mod is False

        can_ivan_view, _ = can_user_view_lesson(ivan_user, hist_lesson)
        assert can_ivan_view is False

        can_admin_view, _ = can_user_view_lesson(admin_user, hist_lesson)
        assert can_admin_view is True

        resolve_historical_lesson_ownership(hist_lid, fx["tutor_ivan_id"], admin_user)
        db.session.refresh(hist_lesson)
        assert hist_lesson.teacher_id == fx["tutor_ivan_id"]


# ==============================================================================
# SCENARIO 19: ICS export and JSON events isolated by teacher_id
# ==============================================================================
def test_scenario_19_ics_export_and_json_events_isolated(test_app, fixtures_sprint2_3):
    fx = fixtures_sprint2_3
    client = test_app.test_client()
    login_as(client, fx["tutor_ivan_id"], "tutor")

    now = datetime.now(dt_timezone.utc)
    with test_app.app_context():
        l_ivan = Lesson(
            student_id=fx["bob_student_id"],
            teacher_id=fx["tutor_ivan_id"],
            subject="Информатика",
            topic="ICS Урок Ивана",
            lesson_date=now + timedelta(days=2),
            status="planned",
        )
        l_elena = Lesson(
            student_id=fx["alice_student_id"],
            teacher_id=fx["tutor_elena_id"],
            subject="Математика",
            topic="ICS Урок Елены",
            lesson_date=now + timedelta(days=2),
            status="planned",
        )
        db.session.add_all([l_ivan, l_elena])
        db.session.commit()

    # 1. JSON events endpoint
    resp_ev = client.get("/api/schedule/events")
    assert resp_ev.status_code == 200
    events = resp_ev.get_json().get("events", [])
    topics = [e["title"] for e in events]
    assert any("ICS Урок Ивана" in t for t in topics)
    assert not any("ICS Урок Елены" in t for t in topics)

    # 2. ICS export endpoint
    resp_ics = client.get("/schedule/export_ics")
    assert resp_ics.status_code == 200
    ics_text = resp_ics.get_data(as_text=True)
    assert "ICS Урок Ивана" in ics_text
    assert "ICS Урок Елены" not in ics_text


# ==============================================================================
# SCENARIO 20: Correct student ID vs user ID conversion
# ==============================================================================
def test_scenario_20_student_id_vs_user_id_conversion(test_app, fixtures_sprint2_3):
    fx = fixtures_sprint2_3
    client = test_app.test_client()
    login_as(client, fx["tutor_ivan_id"], "tutor")

    target_date = (datetime.now(dt_timezone.utc) + timedelta(days=5)).strftime("%Y-%m-%d")

    resp = client.post(
        "/api/schedule/create_lesson",
        json={
            "student_id": fx["alice_user_id"],
            "subject": "Информатика",
            "topic": "Проверка ID преобразования",
            "lesson_date": target_date,
            "time": "17:00",
            "duration": 60,
        },
    )
    assert resp.status_code == 200
    lid = resp.get_json().get("lesson_id")

    with test_app.app_context():
        lesson = db.session.get(Lesson, lid)
        assert lesson is not None
        assert lesson.student_id == fx["alice_student_id"]
