"""
Пак профилей для визуального аудита (Applitools): ученик, преподаватель, родитель, администратор.
Создаёт пользователей, связи, уроки и задания, чтобы поочерёдно запускать visual_audit.py под каждой ролью.

Пароль для всех: VisualAudit123

Запуск:
  python scripts/seed_visual_audit_pack.py
  python scripts/seed_visual_audit_pack.py --sqlite   # локально SQLite (без удалённой БД)
  На хостинге: через команду запуска вашего сервиса (DATABASE_URL берётся из окружения).

Подключение к БД:
  - Локально без доступа к хостингу: используйте --sqlite (создаётся data/keg_tasks.db).
  - Подключение к БД хостинга: задайте в .env или в настройках хостинга актуальные
    DATABASE_URL (хост, пользователь, пароль) для вашего сервера БД, затем запустите без --sqlite.
"""

import os
import sys
import json
import argparse
from datetime import timedelta

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from werkzeug.security import generate_password_hash
from sqlalchemy import text

from app import create_app, db
from core.db_models import (
    moscow_now,
    User, UserProfile,
    Student, Lesson, LessonTask,
    Enrollment, FamilyTie,
    SchoolGroup, GroupStudent,
    Tasks,
    UserSubscription,
    Topic,
)
from app.utils.db_migrations import ensure_schema_columns
from app.utils.student_id_manager import assign_platform_id_if_needed

AUDIT_PASSWORD = "VisualAudit123"
IDS_FILE = "visual_audit_ids.json"


def _get_or_create_user(username: str, role: str, email: str | None = None) -> User:
    u = User.query.filter_by(username=username).first()
    if u:
        u.role = role
        u.is_active = True
        u.password_hash = generate_password_hash(AUDIT_PASSWORD)
        if email:
            u.email = email
    else:
        u = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(AUDIT_PASSWORD),
            role=role,
            is_active=True,
            created_at=moscow_now(),
        )
        db.session.add(u)
    db.session.flush()
    return u


def _get_or_create_student_entity(*, name: str, email: str, user_id: int) -> Student:
    s = Student.query.filter_by(user_id=user_id).first()
    if s:
        s.name = name
        s.email = email
        s.is_active = True
        return s
    s = Student(
        user_id=user_id,
        name=name,
        email=email,
        school_class=11,
        target_score=85,
        is_active=True,
        created_at=moscow_now(),
    )
    db.session.add(s)
    db.session.flush()
    assign_platform_id_if_needed(s)
    db.session.flush()
    return s


def _ensure_family_tie(parent: User, student_user: User):
    tie = FamilyTie.query.filter_by(parent_id=parent.id, student_id=student_user.id).first()
    if not tie:
        db.session.add(FamilyTie(
            parent_id=parent.id,
            student_id=student_user.id,
            access_level="full",
            is_confirmed=True,
            created_at=moscow_now(),
        ))


def _ensure_enrollment(tutor: User, student_user: User):
    enr = Enrollment.query.filter_by(student_id=student_user.id, tutor_id=tutor.id, subject="INFORMATICS_EGE_2026").first()
    if not enr:
        db.session.add(Enrollment(
            student_id=student_user.id,
            tutor_id=tutor.id,
            subject="INFORMATICS_EGE_2026",
            status="active",
            created_at=moscow_now(),
        ))


def _ensure_subscription(user_id: int):
    sub = UserSubscription.query.filter_by(user_id=user_id, status="active").first()
    if not sub:
        sub = UserSubscription(
            user_id=user_id,
            status="active",
            started_at=moscow_now(),
            ends_at=moscow_now() + timedelta(days=30),
            lessons_remaining=15,
            note="Подписка для визуального аудита",
            created_at=moscow_now(),
        )
        db.session.add(sub)
        db.session.flush()


def _seed_lessons(student_entity: Student, tutor_user_id: int, hours_offset: int = 0):
    # Clean up duplicate/old lessons for this student to prevent stacking
    old_lessons = Lesson.query.filter_by(student_id=student_entity.student_id).all()
    old_ids = [l.lesson_id for l in old_lessons]
    if old_ids:
        LessonTask.query.filter(LessonTask.lesson_id.in_(old_ids)).delete(synchronize_session=False)
        Lesson.query.filter(Lesson.student_id == student_entity.student_id).delete(synchronize_session=False)
    db.session.flush()

    # Base date: today at 14:00 (clean daytime hour) + hours_offset
    now_naive = moscow_now().replace(hour=14, minute=0, second=0, microsecond=0).replace(tzinfo=None)
    base_date = now_naive + timedelta(hours=hours_offset)

    lessons_data = [
        {
            "lesson_type": "regular",
            "lesson_date": base_date - timedelta(days=5),
            "duration": 60,
            "status": "completed",
            "topic": f"Визуальный аудит: Логика ({student_entity.name})",
            "notes": "Урок для проверки скриншотов.",
            "homework_status": "assigned_done",
            "homework_result_percent": 75,
        },
        {
            "lesson_type": "regular",
            "lesson_date": base_date - timedelta(days=1),
            "duration": 60,
            "status": "in_progress",
            "topic": f"Визуальный аудит: Алгоритмы ({student_entity.name})",
            "notes": "Текущий урок.",
            "homework_status": "assigned_not_done",
        },
        {
            "lesson_type": "exam",
            "lesson_date": base_date + timedelta(days=2),
            "duration": 90,
            "status": "planned",
            "topic": f"Визуальный аудит: Пробник ({student_entity.name})",
            "notes": "Запланированная проверочная.",
            "homework_status": "not_assigned",
        },
    ]
    created = []
    for data in lessons_data:
        lesson = Lesson(
            student_id=student_entity.student_id,
            lesson_type=data["lesson_type"],
            lesson_date=data["lesson_date"],
            duration=data.get("duration", 60),
            status=data.get("status", "planned"),
            topic=data["topic"],
            notes=data.get("notes"),
            homework_status=data.get("homework_status", "not_assigned"),
        )
        db.session.add(lesson)
        db.session.flush()
        created.append(lesson)
    return created



def _attach_tasks_to_lesson(lesson: Lesson, limit: int = 3):
    """Привязать несколько заданий из банка к уроку (если есть Tasks)."""
    tasks = Tasks.query.order_by(Tasks.task_id).limit(limit).all()
    if not tasks:
        return

    # Ensure a few topics exist and link them
    topic_names = ["Кодирование информации", "Базы данных", "Таблицы истинности", "Алгоритмы и циклы", "Адресация в сетях"]
    topics = []
    for name in topic_names:
        t = Topic.query.filter_by(name=name).first()
        if not t:
            t = Topic(name=name, created_at=moscow_now())
            db.session.add(t)
        topics.append(t)
    db.session.flush()

    for i, task in enumerate(tasks):
        topic = topics[i % len(topics)]
        if topic not in task.topics:
            task.topics.append(topic)

        # Determine status and correctness
        if lesson.homework_status == "assigned_done":
            submission_correct = (i % 2 == 0)  # 1st and 3rd correct, 2nd incorrect
            status = "graded"
        elif lesson.homework_status == "assigned_not_done":
            submission_correct = None
            status = "pending"
        else:
            submission_correct = None
            status = "pending"

        existing = LessonTask.query.filter_by(
            lesson_id=lesson.lesson_id,
            task_id=task.task_id,
        ).first()
        if existing:
            existing.submission_correct = submission_correct
            existing.status = status
            continue

        lt = LessonTask(
            lesson_id=lesson.lesson_id,
            task_id=task.task_id,
            assignment_type="homework",
            submission_correct=submission_correct,
            status=status,
            date_assigned=moscow_now(),
        )
        db.session.add(lt)


def run_seed(app, root_dir: str | None = None, write_ids_file: bool = True) -> int:
    """
    Создаёт таблицы и заполняет пак визуального аудита. Вызывать внутри app.app_context().
    root_dir — корень проекта (для пути к visual_audit_ids.json). По умолчанию — родитель scripts/.
    Возвращает 0 при успехе, 1 при ошибке.
    """
    if root_dir is None:
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    db.create_all()
    try:
        ensure_schema_columns(app)
    except Exception:
        pass

    try:
            admin = _get_or_create_user(
                username="visual_audit_admin",
                role="admin",
                email="visual_audit_admin@example.com",
            )
            tutor = _get_or_create_user(
                username="visual_audit_tutor",
                role="tutor",
                email="visual_audit_tutor@example.com",
            )
            student_user = _get_or_create_user(
                username="visual_audit_student",
                role="student",
                email="visual_audit_student@example.com",
            )
            student_user2 = _get_or_create_user(
                username="visual_audit_student2",
                role="student",
                email="visual_audit_student2@example.com",
            )
            parent = _get_or_create_user(
                username="visual_audit_parent",
                role="parent",
                email="visual_audit_parent@example.com",
            )

            student_entity = _get_or_create_student_entity(
                name="Визуальный Аудит Ученик 1",
                email="visual_audit_student@example.com",
                user_id=student_user.id,
            )
            student_entity2 = _get_or_create_student_entity(
                name="Визуальный Аудит Ученик 2",
                email="visual_audit_student2@example.com",
                user_id=student_user2.id,
            )

            _ensure_family_tie(parent, student_user)
            _ensure_family_tie(parent, student_user2)

            _ensure_enrollment(tutor, student_user)
            _ensure_enrollment(tutor, student_user2)

            _ensure_subscription(student_user.id)
            _ensure_subscription(student_user2.id)

            lessons = _seed_lessons(student_entity, tutor.id, hours_offset=0)
            for lesson in lessons:
                _attach_tasks_to_lesson(lesson)

            lessons2 = _seed_lessons(student_entity2, tutor.id, hours_offset=2)
            for lesson in lessons2:
                _attach_tasks_to_lesson(lesson)

            group = SchoolGroup.query.filter_by(
                title="Визуальный аудит · Группа",
                owner_user_id=tutor.id,
            ).first()
            if not group:
                group = SchoolGroup(
                    title="Визуальный аудит · Группа",
                    subject="Информатика (ЕГЭ)",
                    description="Для скриншотов по ролям",
                    status="active",
                    owner_user_id=tutor.id,
                    created_at=moscow_now(),
                )
                db.session.add(group)
                db.session.flush()

            link = GroupStudent.query.filter_by(
                group_id=group.group_id,
                student_id=student_entity.student_id,
            ).first()
            if not link:
                db.session.add(GroupStudent(
                    group_id=group.group_id,
                    student_id=student_entity.student_id,
                    added_by_user_id=tutor.id,
                ))

            link2 = GroupStudent.query.filter_by(
                group_id=group.group_id,
                student_id=student_entity2.student_id,
            ).first()
            if not link2:
                db.session.add(GroupStudent(
                    group_id=group.group_id,
                    student_id=student_entity2.student_id,
                    added_by_user_id=tutor.id,
                ))

            db.session.commit()

            lesson_id = lessons[0].lesson_id if lessons else 1
            ids_payload = {
                "student_id": student_entity.student_id,
                "lesson_id": lesson_id,
                "profiles": {
                    "student": {"username": "visual_audit_student", "password": AUDIT_PASSWORD},
                    "tutor": {"username": "visual_audit_tutor", "password": AUDIT_PASSWORD},
                    "parent": {"username": "visual_audit_parent", "password": AUDIT_PASSWORD},
                    "admin": {"username": "visual_audit_admin", "password": AUDIT_PASSWORD},
                },
            }

            if write_ids_file:
                ids_path = os.path.join(root_dir, IDS_FILE)
                with open(ids_path, "w", encoding="utf-8") as f:
                    json.dump(ids_payload, f, indent=2, ensure_ascii=False)
                try:
                    print(f"Записано: {ids_path}")
                except (ValueError, OSError):
                    sys.stdout = getattr(sys, "__stdout__", sys.stdout)
                    print(f"Записано: {ids_path}")

            print("=" * 60)
            print("ПАК ВИЗУАЛЬНОГО АУДИТА СОЗДАН")
            print("=" * 60)
            print(f"Пароль для всех: {AUDIT_PASSWORD}")
            print()
            print("Профили:")
            print("  admin:   visual_audit_admin")
            print("  tutor:   visual_audit_tutor")
            print("  student: visual_audit_student")
            print("  parent:  visual_audit_parent")
            print()
            print(f"student_id (для URL): {student_entity.student_id}")
            print(f"lesson_id (для URL):  {lesson_id}")
            print()
            print("Запуск аудита по ролям:")
            print("  python visual_audit.py --role student")
            print("  python visual_audit.py --role tutor")
            print("  python visual_audit.py --role parent")
            print("  python visual_audit.py --role admin")
            print("  python visual_audit.py --all-roles")
            print("=" * 60)
            return 0

    except Exception as e:
        db.session.rollback()
        print(f"Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return 1


def main():
    parser = argparse.ArgumentParser(description="Создать пак пользователей и данных для визуального аудита")
    parser.add_argument("--sqlite", action="store_true", help="Локально использовать SQLite")
    parser.add_argument("--no-ids-file", action="store_true", help="Не записывать visual_audit_ids.json")
    args = parser.parse_args()

    if args.sqlite:
        os.environ.pop("DATABASE_URL", None)
        os.environ.pop("DATABASE_EXTERNAL_URL", None)
        os.environ.pop("POSTGRES_URL", None)

    app = create_app()
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    with app.app_context():
        try:
            db.session.execute(text("SELECT 1"))
        except Exception as e:
            print("Ошибка: база недоступна.")
            print("  Причина:", str(e).split("\n")[0])
            print()
            print("Варианты:")
            print("  1) Локальный запуск:  python scripts/setup_local_test_db.py  — создать локальную тестовую БД")
            print("  2) Либо:  python scripts/seed_visual_audit_pack.py --sqlite")
            print("  3) Хостинг: задайте в .env актуальные DATABASE_URL и пароль, затем без --sqlite")
            print("     DATABASE_URL и пароль для нового сервера БД, затем запустите без --sqlite.")
            return 1

        return run_seed(app, root_dir, write_ids_file=not args.no_ids_file)


if __name__ == "__main__":
    raise SystemExit(main())
