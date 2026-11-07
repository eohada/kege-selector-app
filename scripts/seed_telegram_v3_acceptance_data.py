"""
Seed realistic and rich test data for BooStudy Telegram Bot V3 acceptance testing.
Targeted specifically for Creator account (User ID 4, Chat ID 854161398).
Idempotent and safe: does not alter real users or corrupt existing relations.
"""
import os
import sys

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root not in sys.path:
    sys.path.insert(0, root)

from datetime import datetime, timedelta, timezone
from wsgi import app
from app.models import (
    db, User, UserProfile, UserRole, Student, Lesson,
    Assignment, Submission, FamilyTie
)
from core.db_models import BugReport

def seed_acceptance_data():
    with app.app_context():
        print("[*] Starting Bot V3 acceptance test data seed...")
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        
        manifest = {
            "seeded_at": now_utc.isoformat(),
            "target_user_id": 4,
            "user_roles_added": [],
            "students_created": [],
            "lessons": [],
            "assignments": [],
            "submissions": [],
            "family_ties": [],
            "bug_reports": []
        }

        # 1. Ensure Creator (User 4) has full multi-role access
        creator = User.query.get(4)
        if not creator:
            print("[!] Creator User 4 not found!")
            return
        
        for role_name in ("teacher", "admin", "parent", "student"):
            existing_ur = UserRole.query.filter_by(user_id=4, role=role_name).first()
            if not existing_ur:
                db.session.add(UserRole(user_id=4, role=role_name))
                manifest["user_roles_added"].append({"user_id": 4, "role": role_name})
                print(f"[+] Added role '{role_name}' to Creator User 4")
        
        # Ensure profile exists with telegram_chat_id = 854161398
        prof = creator.profile or UserProfile.query.filter_by(user_id=4).first()
        if not prof:
            prof = UserProfile(user_id=4, telegram_chat_id=854161398, timezone='Europe/Moscow')
            db.session.add(prof)
        else:
            prof.telegram_chat_id = 854161398
            prof.timezone = 'Europe/Moscow'
        
        # 2. Ensure Student record for User 4 (Student 702)
        student_702 = Student.query.filter_by(user_id=4).first()
        if not student_702:
            student_702 = Student(
                user_id=4,
                name="Создатель платформы (Тестовый Ученик)",
                category="ЕГЭ",
                is_active=True,
                mentor_id=4
            )
            db.session.add(student_702)
            db.session.flush()
            manifest["students_created"].append(student_702.student_id)
            print(f"[+] Created student record for User 4: #{student_702.student_id}")
        else:
            student_702.is_active = True
            if not student_702.mentor_id:
                student_702.mentor_id = 4
        
        # 3. Lessons for Teacher (User 4) TODAY and upcoming
        # Today Lesson 1: in 2 hours
        l1_start = now_utc + timedelta(hours=2)
        l1 = Lesson.query.filter_by(teacher_id=4, topic="ЕГЭ Информатика: Графы и поиск в глубину (Задание 27)").first()
        if not l1:
            l1 = Lesson(
                teacher_id=4,
                student_id=student_702.student_id,
                topic="ЕГЭ Информатика: Графы и поиск в глубину (Задание 27)",
                lesson_date=l1_start,
                duration=90,
                status="planned"
            )
            db.session.add(l1)
            db.session.flush()
            print("[+] Added Teacher Lesson 1 today")
        else:
            l1.lesson_date = l1_start
            l1.status = "planned"
        manifest["lessons"].append(l1.lesson_id)

        # Today Lesson 2: in 5 hours
        l2_start = now_utc + timedelta(hours=5)
        l2 = Lesson.query.filter_by(teacher_id=4, topic="ОГЭ Информатика: Системы счисления и логика").first()
        if not l2:
            l2 = Lesson(
                teacher_id=4,
                student_id=29, # Алексей Смирнов
                topic="ОГЭ Информатика: Системы счисления и логика",
                lesson_date=l2_start,
                duration=60,
                status="planned"
            )
            db.session.add(l2)
            db.session.flush()
            print("[+] Added Teacher Lesson 2 today")
        else:
            l2.lesson_date = l2_start
            l2.status = "planned"
        manifest["lessons"].append(l2.lesson_id)

        # Cancelled Lesson
        l_canc = Lesson.query.filter_by(teacher_id=4, topic="Индивидуальная консультация (отменена)").first()
        if not l_canc:
            l_canc = Lesson(
                teacher_id=4,
                student_id=29,
                topic="Индивидуальная консультация (отменена)",
                lesson_date=now_utc - timedelta(days=1),
                duration=45,
                status="cancelled"
            )
            db.session.add(l_canc)
            db.session.flush()
            print("[+] Added Cancelled Lesson")
        manifest["lessons"].append(l_canc.lesson_id)

        # 4. Assignments & Submissions for Student 702
        # A) Active assignment with future deadline
        a_active = Assignment.query.filter_by(title="Лабораторная работа: Бинарные деревья поиска").first()
        if not a_active:
            a_active = Assignment(
                created_by_id=4,
                assignment_type='homework',
                title="Лабораторная работа: Бинарные деревья поиска",
                description="Реализовать балансировку АВЛ-дерева и поиск k-го минимума на Python.",
                deadline=now_utc + timedelta(days=3),
                is_active=True
            )
            db.session.add(a_active)
            db.session.flush()
        manifest["assignments"].append(a_active.assignment_id)
        
        sub_active = Submission.query.filter_by(assignment_id=a_active.assignment_id, student_id=student_702.student_id).first()
        if not sub_active:
            sub_active = Submission(
                assignment_id=a_active.assignment_id,
                student_id=student_702.student_id,
                status="ASSIGNED"
            )
            db.session.add(sub_active)
            db.session.flush()
            print("[+] Added active assignment for Student 702")
        manifest["submissions"].append(sub_active.submission_id)

        # B) Overdue assignment
        a_overdue = Assignment.query.filter_by(title="Практикум №14: Позиционные системы счисления").first()
        if not a_overdue:
            a_overdue = Assignment(
                created_by_id=4,
                assignment_type='homework',
                title="Практикум №14: Позиционные системы счисления",
                description="Решить 10 авторских задач на перевод чисел между основаниями 7, 12 и 16.",
                deadline=now_utc - timedelta(days=2),
                is_active=True
            )
            db.session.add(a_overdue)
            db.session.flush()
        manifest["assignments"].append(a_overdue.assignment_id)
        
        sub_overdue = Submission.query.filter_by(assignment_id=a_overdue.assignment_id, student_id=student_702.student_id).first()
        if not sub_overdue:
            sub_overdue = Submission(
                assignment_id=a_overdue.assignment_id,
                student_id=student_702.student_id,
                status="ASSIGNED"
            )
            db.session.add(sub_overdue)
            db.session.flush()
            print("[+] Added overdue assignment for Student 702")
        manifest["submissions"].append(sub_overdue.submission_id)

        # C) Submitted assignment (on review)
        a_submitted = Assignment.query.filter_by(title="Решение варианта №102 КЕГЭ 2026").first()
        if not a_submitted:
            a_submitted = Assignment(
                created_by_id=4,
                assignment_type='homework',
                title="Решение варианта №102 КЕГЭ 2026",
                description="Полный пробный экзамен КЕГЭ. Время выполнения: 3 часа 55 минут.",
                deadline=now_utc + timedelta(days=1),
                is_active=True
            )
            db.session.add(a_submitted)
            db.session.flush()
        manifest["assignments"].append(a_submitted.assignment_id)
        
        sub_submitted = Submission.query.filter_by(assignment_id=a_submitted.assignment_id, student_id=student_702.student_id).first()
        if not sub_submitted:
            sub_submitted = Submission(
                assignment_id=a_submitted.assignment_id,
                student_id=student_702.student_id,
                status="SUBMITTED",
                submitted_at=now_utc - timedelta(hours=4)
            )
            db.session.add(sub_submitted)
            db.session.flush()
            print("[+] Added submitted assignment for Student 702")
        manifest["submissions"].append(sub_submitted.submission_id)

        # D) Checked assignment with score and comment
        a_checked = Assignment.query.filter_by(title="Контрольная работа №2: Динамическое программирование").first()
        if not a_checked:
            a_checked = Assignment(
                created_by_id=4,
                assignment_type='homework',
                title="Контрольная работа №2: Динамическое программирование",
                description="Задачи на одномерную и двумерную динамику, рюкзак и НВП.",
                deadline=now_utc - timedelta(days=5),
                is_active=True
            )
            db.session.add(a_checked)
            db.session.flush()
        manifest["assignments"].append(a_checked.assignment_id)
        
        sub_checked = Submission.query.filter_by(assignment_id=a_checked.assignment_id, student_id=student_702.student_id).first()
        if not sub_checked:
            sub_checked = Submission(
                assignment_id=a_checked.assignment_id,
                student_id=student_702.student_id,
                status="CHECKED",
                submitted_at=now_utc - timedelta(days=4),
                graded_at=now_utc - timedelta(days=3),
                results_published_at=now_utc - timedelta(days=3),
                total_score=24,
                max_score=25,
                percentage=96,
                teacher_feedback="Отличная оптимизация памяти в задаче №3! В коде учтены все крайние случаи."
            )
            db.session.add(sub_checked)
            db.session.flush()
            print("[+] Added checked assignment for Student 702")
        manifest["submissions"].append(sub_checked.submission_id)

        # 5. Confirmed FamilyTie for Creator as Parent (with student 29 "Алексей Смирнов (Демо)")
        tie = FamilyTie.query.filter_by(parent_id=4, student_id=29).first()
        if not tie:
            tie = FamilyTie(parent_id=4, student_id=29, is_confirmed=True)
            db.session.add(tie)
            print("[+] Added confirmed FamilyTie: Parent 4 -> Student 29 (Алексей Смирнов)")
        else:
            tie.is_confirmed = True
        manifest["family_ties"].append({"parent_id": 4, "student_id": 29})

        # Also add a second confirmed tie to test multi-child parent
        tie2 = FamilyTie.query.filter_by(parent_id=4, student_id=1).first()
        if not tie2:
            tie2 = FamilyTie(parent_id=4, student_id=1, is_confirmed=True)
            db.session.add(tie2)
            print("[+] Added second confirmed FamilyTie: Parent 4 -> Student 1 (Ученик Room QA)")
        else:
            tie2.is_confirmed = True
        manifest["family_ties"].append({"parent_id": 4, "student_id": 1})

        # 6. Operational Bug Report for Admin testing
        bug = BugReport.query.filter_by(title="Тестовый инцидент: Оптимизация рендеринга формул").first()
        if not bug:
            bug = BugReport(
                reporter_id=4,
                title="Тестовый инцидент: Оптимизация рендеринга формул",
                description="Проверить отображение KaTeX в заданиях №19-21.",
                severity="low",
                status="IN_PROGRESS"
            )
            db.session.add(bug)
            db.session.flush()
            print("[+] Added operational bug report for Admin panel")
        manifest["bug_reports"].append(bug.id)

        db.session.commit()

        # Save manifest
        manifest_path = os.path.join(root, 'instance', 'telegram_acceptance_seed_manifest.json')
        os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
        import json
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        print(f"[✓] Manifest saved to {manifest_path}")
        print("[✓] All Bot V3 acceptance test data successfully seeded!")

if __name__ == '__main__':
    seed_acceptance_data()
