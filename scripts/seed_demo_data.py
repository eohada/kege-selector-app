#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Seed demo dataset for manual QA.

Creates:
- 1 tutor
- 2 students (+ linked Student rows)
- 2 parents
- Family ties (parent -> student)
- Enrollments (student -> tutor)
- Several lessons per student (different lesson_type + status)
- (Optional) one group with both students

Passwords for all created users are set to: 123

Run:
  # Local (SQLite):
  python scripts/seed_demo_data.py --sqlite

  # Railway (seeds remote Postgres):
  railway run python scripts/seed_demo_data.py
"""

import os
import sys
from datetime import timedelta
import argparse
from sqlalchemy import text

# Fix Windows encoding
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Add repo root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from werkzeug.security import generate_password_hash

from app import create_app, db
from core.db_models import (
    moscow_now,
    User, UserProfile,
    Student, Lesson,
    Enrollment, FamilyTie,
    SchoolGroup, GroupStudent,
)
from app.utils.db_migrations import ensure_schema_columns


DEMO_PASSWORD = "123"


def _get_or_create_user(*, username: str, role: str, email: str | None = None, timezone: str | None = None) -> User:
    u = User.query.filter_by(username=username).first()
    if u:
        # ensure role/email/password for demo consistency
        u.role = role
        u.is_active = True
        if email:
            u.email = email
        u.password_hash = generate_password_hash(DEMO_PASSWORD)
    else:
        u = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(DEMO_PASSWORD),
            role=role,
            is_active=True,
            created_at=moscow_now(),
        )
        db.session.add(u)
        db.session.flush()

    if timezone:
        prof = UserProfile.query.filter_by(user_id=u.id).first()
        if not prof:
            prof = UserProfile(user_id=u.id, timezone=timezone)
            db.session.add(prof)
        else:
            prof.timezone = timezone
    return u


def _get_or_create_student_entity(*, name: str, email: str) -> Student:
    s = Student.query.filter_by(email=email).first()
    if s:
        s.name = name
        s.is_active = True
        return s
    s = Student(
        name=name,
        email=email,
        category="ЕГЭ",
        programming_language="Python",
        school_class=11,
        target_score=90,
        is_active=True,
        created_at=moscow_now(),
    )
    db.session.add(s)
    db.session.flush()
    # platform_id for convenience in UI
    if not s.platform_id:
        s.platform_id = f"DEMO-{s.student_id}"
    return s


def _ensure_family_tie(*, parent: User, student_user: User):
    tie = FamilyTie.query.filter_by(parent_id=parent.id, student_id=student_user.id).first()
    if not tie:
        tie = FamilyTie(
            parent_id=parent.id,
            student_id=student_user.id,
            access_level="full",
            is_confirmed=True,
            created_at=moscow_now(),
        )
        db.session.add(tie)
    else:
        tie.access_level = "full"
        tie.is_confirmed = True


def _ensure_enrollment(*, tutor: User, student_user: User, subject: str = "INFORMATICS_EGE_2026"):
    enr = Enrollment.query.filter_by(student_id=student_user.id, tutor_id=tutor.id, subject=subject).first()
    if not enr:
        enr = Enrollment(
            student_id=student_user.id,
            tutor_id=tutor.id,
            subject=subject,
            status="active",
            created_at=moscow_now(),
        )
        db.session.add(enr)
    else:
        enr.status = "active"


def _ensure_group(*, tutor: User, title: str, student_entities: list[Student]) -> SchoolGroup:
    g = SchoolGroup.query.filter_by(title=title, owner_user_id=tutor.id).first()
    if not g:
        g = SchoolGroup(
            title=title,
            subject="Информатика (ЕГЭ)",
            description="Демо-группа для QA",
            status="active",
            owner_user_id=tutor.id,
            created_at=moscow_now(),
        )
        db.session.add(g)
        db.session.flush()
    # members
    for s in student_entities:
        link = GroupStudent.query.filter_by(group_id=g.group_id, student_id=s.student_id).first()
        if not link:
            db.session.add(GroupStudent(group_id=g.group_id, student_id=s.student_id, added_by_user_id=tutor.id))
    return g


def _seed_lessons(*, student_entity: Student):
    now_naive = moscow_now().replace(tzinfo=None)

    def upsert_lesson(key: str, **kwargs):
        # Use topic+lesson_date uniqueness heuristic to avoid duplicates
        topic = kwargs.get("topic")
        dt = kwargs.get("lesson_date")
        existing = Lesson.query.filter_by(student_id=student_entity.student_id, topic=topic, lesson_date=dt).first()
        if existing:
            for k, v in kwargs.items():
                setattr(existing, k, v)
            return existing
        l = Lesson(student_id=student_entity.student_id, **kwargs)
        db.session.add(l)
        return l

    # Completed regular lesson
    upsert_lesson(
        "completed_regular",
        lesson_type="regular",
        lesson_date=now_naive - timedelta(days=7),
        duration=60,
        status="completed",
        topic="Демо: Логика (таблицы истинности)",
        notes="Разобрали базовые операции, примеры из КЕГЭ.",
        content="### Теория\n- И/ИЛИ/НЕ\n- Импликация\n",
        homework="Решить 5 задач по теме.",
        homework_status="assigned_done",
        homework_result_percent=80,
        homework_result_notes="Хорошо, но внимательнее с приоритетами операций.",
    )

    # In progress lesson
    upsert_lesson(
        "in_progress",
        lesson_type="regular",
        lesson_date=now_naive - timedelta(minutes=30),
        duration=60,
        status="in_progress",
        topic="Демо: Таблицы и сортировка",
        notes="Урок идет сейчас.",
        homework_status="assigned_not_done",
    )

    # Planned exam/checkpoint lesson
    upsert_lesson(
        "planned_exam",
        lesson_type="exam",
        lesson_date=now_naive + timedelta(days=3),
        duration=90,
        status="planned",
        topic="Демо: Пробник (мини)",
        notes="Проверочная работа.",
        homework_status="not_assigned",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", action="store_true", help="Force local SQLite (ignore DATABASE_URL)")
    args = parser.parse_args()

    # In Windows/local, DATABASE_URL may point to Railway internal host and be unreachable.
    # Allow forcing sqlite for quick local QA.
    if args.sqlite:
        os.environ.pop("DATABASE_URL", None)
        os.environ.pop("DATABASE_EXTERNAL_URL", None)
        os.environ.pop("POSTGRES_URL", None)

    app = create_app()

    with app.app_context():
        try:
            # quick connectivity check (gives a better hint than a giant stacktrace)
            try:
                db.session.execute(text("SELECT 1"))
            except Exception:
                raise RuntimeError(
                    "Database is not reachable. "
                    "If you are on Windows/local and DATABASE_URL points to Railway internal host, run with --sqlite "
                    "or seed via Railway: `railway run python scripts/seed_demo_data.py`."
                )

            # Ensure schema exists (especially for local SQLite)
            db.create_all()
            try:
                ensure_schema_columns(app)
            except Exception:
                # non-fatal for seeding; create_all may already cover most tables
                pass

            # Tutor
            tutor = _get_or_create_user(
                username="demo_tutor",
                role="tutor",
                email="demo_tutor@example.com",
                timezone="Europe/Moscow",
            )

            # Students (users) + Student entities
            stu1_user = _get_or_create_user(
                username="demo_student_1",
                role="student",
                email="demo_student_1@example.com",
                timezone="Europe/Moscow",
            )
            stu2_user = _get_or_create_user(
                username="demo_student_2",
                role="student",
                email="demo_student_2@example.com",
                timezone="Asia/Tomsk",
            )

            stu1 = _get_or_create_student_entity(name="Демо Ученик 1", email="demo_student_1@example.com")
            stu2 = _get_or_create_student_entity(name="Демо Ученик 2", email="demo_student_2@example.com")

            # Parents
            parent1 = _get_or_create_user(
                username="demo_parent_1",
                role="parent",
                email="demo_parent_1@example.com",
                timezone="Europe/Moscow",
            )
            parent2 = _get_or_create_user(
                username="demo_parent_2",
                role="parent",
                email="demo_parent_2@example.com",
                timezone="Europe/Moscow",
            )

            # Links
            _ensure_family_tie(parent=parent1, student_user=stu1_user)
            _ensure_family_tie(parent=parent2, student_user=stu2_user)
            _ensure_enrollment(tutor=tutor, student_user=stu1_user)
            _ensure_enrollment(tutor=tutor, student_user=stu2_user)

            # Lessons
            _seed_lessons(student_entity=stu1)
            _seed_lessons(student_entity=stu2)

            # Group
            _ensure_group(tutor=tutor, title="DEMO · Информатика ЕГЭ", student_entities=[stu1, stu2])

            db.session.commit()

            print("=" * 72)
            print("✅ DEMO DATA SEEDED")
            print("=" * 72)
            print("Пароль для всех: 123")
            print()
            print("Пользователи:")
            print(" - tutor:   demo_tutor")
            print(" - student: demo_student_1")
            print(" - student: demo_student_2")
            print(" - parent:  demo_parent_1")
            print(" - parent:  demo_parent_2")
            print()
            print("Связи:")
            print(" - demo_parent_1 -> demo_student_1 (FamilyTie)")
            print(" - demo_parent_2 -> demo_student_2 (FamilyTie)")
            print(" - demo_tutor teaches both students (Enrollment)")
            print()
            print("Уроки созданы для обоих учеников (completed / in_progress / planned).")
            print("Группа: DEMO · Информатика ЕГЭ")
            print("=" * 72)
            return 0
        except Exception as e:
            db.session.rollback()
            print("❌ Failed to seed demo data:", e)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())

