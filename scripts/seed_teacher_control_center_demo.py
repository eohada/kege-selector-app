import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from datetime import datetime, date, time as dt_time, timedelta
from app import create_app, db
from app.models import User, Student, Lesson
from core.db_models import (
    TeacherWeeklyAvailability,
    TeacherScheduleException,
    RecurringLessonSlot,
    Assignment,
    Submission,
    Tasks,
    AssignmentTask,
    Course,
    Enrollment,
)

def seed():
    app = create_app()
    with app.app_context():
        teacher = User.query.filter_by(username="qa_pool_teacher_1").first()
        if not teacher:
            print("qa_pool_teacher_1 not found!")
            return

        student1_user = User.query.filter_by(username="demo_student_1").first()
        student2_user = User.query.filter_by(username="demo_student_2").first()
        st1 = Student.query.filter_by(user_id=student1_user.id).first() if student1_user else None
        st2 = Student.query.filter_by(user_id=student2_user.id).first() if student2_user else None

        if not st1 or not st2:
            print("Students not found!")
            return

        print(f"Teacher id: {teacher.id}, Students: st1={st1.student_id}, st2={st2.student_id}")

        # 1. Weekly Availability (Mon-Fri 09:00-20:00)
        TeacherWeeklyAvailability.query.filter_by(teacher_id=teacher.id).delete()
        for wd in range(5): # Mon-Fri
            avail = TeacherWeeklyAvailability(
                teacher_id=teacher.id,
                weekday=wd,
                start_time="09:00",
                end_time="20:00",
                is_active=True
            )
            db.session.add(avail)

        # 2. Recurring Lesson Slots
        RecurringLessonSlot.query.filter_by(owner_user_id=teacher.id).delete()
        slot1 = RecurringLessonSlot(
            owner_user_id=teacher.id,
            student_id=st1.student_id,
            weekday=0, # Monday
            time_hhmm="12:00",
            duration=60,
            subject="Информатика",
            topic="ЕГЭ Информатика: рекурсия",
            start_date=date(2026, 9, 1),
            end_date=date(2027, 5, 30),
        )
        slot2 = RecurringLessonSlot(
            owner_user_id=teacher.id,
            student_id=st2.student_id,
            weekday=3, # Thursday
            time_hhmm="17:00",
            duration=90,
            subject="Математика",
            topic="Параметры в профильном ЕГЭ",
            start_date=date(2026, 9, 1),
            end_date=date(2027, 5, 30),
        )
        db.session.add_all([slot1, slot2])
        db.session.flush()

        # 3. Clean up existing lessons for teacher and add rich schedule for week 2026-11-02 to 2026-11-08
        Lesson.query.filter_by(teacher_id=teacher.id).delete()

        def msk(year, month, day, hour, minute):
            # Moscow is UTC+3; subtract 3 hours to store as UTC in database
            return datetime(year, month, day, hour, minute) - timedelta(hours=3)

        lessons_data = [
            # Monday 02 Nov
            {
                "student_id": st1.student_id,
                "subject": "Информатика",
                "topic": "Разбор графов и поиск путей · КЕГЭ №13",
                "start_time": msk(2026, 11, 2, 10, 30),
                "duration": 90,
                "status": "planned",
                "recurring_slot_id": None,
                "teacher_notes": "Повторить алгоритм Дейкстры и матрицы смежности."
            },
            {
                "student_id": st2.student_id,
                "subject": "Программирование",
                "topic": "Python для ЕГЭ №24 (обработка строк)",
                "start_time": msk(2026, 11, 2, 14, 0),
                "duration": 60,
                "status": "in_progress",
                "recurring_slot_id": None,
                "teacher_notes": "Разобрать регулярные выражения и срезы."
            },
            {
                "student_id": st1.student_id,
                "subject": "Информатика",
                "topic": "Экспресс-разбор домашнего задания",
                "start_time": msk(2026, 11, 2, 16, 30),
                "duration": 45,
                "status": "planned",
                "recurring_slot_id": None,
                "teacher_notes": "Проверка сложных тестов."
            },
            # Tuesday 03 Nov
            {
                "student_id": st1.student_id,
                "subject": "Информатика",
                "topic": "Утренний интенсив: Базовые алгоритмы",
                "start_time": msk(2026, 11, 3, 7, 0),
                "duration": 60,
                "status": "planned",
                "recurring_slot_id": None,
                "teacher_notes": "Утренний слот 07:00."
            },
            {
                "student_id": st2.student_id,
                "subject": "Математика",
                "topic": "Теория вероятностей: сложные события · ЕГЭ №10",
                "start_time": msk(2026, 11, 3, 14, 0),
                "duration": 60,
                "status": "planned",
                "recurring_slot_id": None,
                "teacher_notes": "Формула полной вероятности и Байеса."
            },
            {
                "student_id": st2.student_id,
                "subject": "Математика",
                "topic": "Параметры: аналитический метод",
                "start_time": msk(2026, 11, 3, 18, 0),
                "duration": 90,
                "status": "planned",
                "recurring_slot_id": None,
                "teacher_notes": "Разбор квадратных трехчленов с параметром."
            },
            # Wednesday 04 Nov
            {
                "student_id": st1.student_id,
                "subject": "Информатика",
                "topic": "Динамика в таблицах · КЕГЭ №9",
                "start_time": msk(2026, 11, 4, 11, 0),
                "duration": 60,
                "status": "planned",
                "recurring_slot_id": None,
                "teacher_notes": "Электронные таблицы и фильтры."
            },
            {
                "student_id": st1.student_id,
                "subject": "Программирование",
                "topic": "Динамическое программирование в Python · ЕГЭ №27",
                "start_time": msk(2026, 11, 4, 18, 0),
                "duration": 90,
                "status": "planned",
                "recurring_slot_id": None,
                "teacher_notes": "Кольцевой буфер и префиксные суммы."
            },
            {
                "student_id": st2.student_id,
                "subject": "Физика",
                "topic": "Поздний разбор олимпиадных задач: Механика",
                "start_time": msk(2026, 11, 4, 22, 0),
                "duration": 60,
                "status": "planned",
                "recurring_slot_id": None,
                "teacher_notes": "Поздний слот 22:00. Законы сохранения."
            },
            # Thursday 05 Nov
            {
                "student_id": st1.student_id,
                "subject": "Информатика",
                "topic": "Комбинаторика и логика · КЕГЭ №8",
                "start_time": msk(2026, 11, 5, 15, 0),
                "duration": 60,
                "status": "planned",
                "recurring_slot_id": None,
                "teacher_notes": "Формулы перестановок и размещений."
            },
            {
                "student_id": st2.student_id,
                "subject": "Математика",
                "topic": "Параметры в профильном ЕГЭ: мастеркласс",
                "start_time": msk(2026, 11, 5, 17, 0),
                "duration": 120,
                "status": "planned",
                "recurring_slot_id": slot2.slot_id,
                "teacher_notes": "Плоскость (x, a) и движение прямых. 2 часа интенсив."
            },
            # Friday 06 Nov
            {
                "student_id": st1.student_id,
                "subject": "Информатика",
                "topic": "Теория игр: две кучи · КЕГЭ №19-21",
                "start_time": msk(2026, 11, 6, 10, 0),
                "duration": 90,
                "status": "planned",
                "recurring_slot_id": None,
                "teacher_notes": "Табличный метод и рекурсивная функция."
            },
            {
                "student_id": st2.student_id,
                "subject": "Информатика",
                "topic": "Блиц-тестирование по пройденным темам",
                "start_time": msk(2026, 11, 6, 14, 0),
                "duration": 45,
                "status": "planned",
                "recurring_slot_id": None,
                "teacher_notes": "Быстрый опрос и проверка формул."
            },
            {
                "student_id": st1.student_id,
                "subject": "Информатика",
                "topic": "Рекурсивные алгоритмы и мемоизация · ЕГЭ №16",
                "start_time": msk(2026, 11, 6, 16, 0),
                "duration": 60,
                "status": "planned",
                "recurring_slot_id": None,
                "teacher_notes": "sys.setrecursionlimit и lru_cache."
            },
            {
                "student_id": st2.student_id,
                "subject": "Информатика",
                "topic": "Практикум: решение задач КЕГЭ №13",
                "start_time": msk(2026, 11, 6, 18, 0),
                "duration": 60,
                "status": "planned",
                "recurring_slot_id": None,
                "teacher_notes": "Проверка домашнего задания перед занятием."
            },
            # Saturday 07 Nov
            {
                "student_id": st1.student_id,
                "subject": "Информатика",
                "topic": "Субботний пробник: разбор первой части",
                "start_time": msk(2026, 11, 7, 12, 0),
                "duration": 90,
                "status": "planned",
                "recurring_slot_id": None,
                "teacher_notes": "Анализ типичных ошибок первой части."
            },
        ]

        for ld in lessons_data:
            l = Lesson(
                teacher_id=teacher.id,
                student_id=ld["student_id"],
                subject=ld["subject"],
                topic=ld["topic"],
                lesson_date=ld["start_time"],
                duration=ld["duration"],
                status=ld["status"],
                recurring_slot_id=ld["recurring_slot_id"],
                notes=ld.get("teacher_notes", ""),
            )
            db.session.add(l)

        # 4. Homework Assignment & Submission
        asg = Assignment.query.filter_by(created_by_id=teacher.id).first()
        if not asg:
            asg = Assignment(
                title="Домашнее задание: Рекурсивные алгоритмы №16",
                description="Решить 5 задач на рекурсию и прикрепить файлы решений.",
                assignment_type="homework",
                created_by_id=teacher.id,
                deadline=datetime(2026, 11, 6, 20, 0),
            )
            db.session.add(asg)
            db.session.flush()

        sub = Submission.query.filter_by(assignment_id=asg.assignment_id, student_id=st1.student_id).first()
        if not sub:
            sub = Submission(
                assignment_id=asg.assignment_id,
                student_id=st1.student_id,
                status="SUBMITTED",
                submitted_at=datetime(2026, 11, 2, 2, 0),
            )
            db.session.add(sub)
        else:
            sub.status = "SUBMITTED"

        db.session.commit()
        print("✓ Teacher Control Center seed data committed successfully!")

if __name__ == "__main__":
    seed()
