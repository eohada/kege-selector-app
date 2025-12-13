
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from core.db_models import Student, Lesson, MOSCOW_TZ, TOMSK_TZ

def create_lesson(platform_id_or_name, date_str, time_str, duration=60, status='completed'):

    with app.app_context():

        student = Student.query.filter_by(platform_id=platform_id_or_name.strip()).first()

        if not student:
            student = Student.query.filter_by(name=platform_id_or_name.strip()).first()

        if not student:
            print(f"[ERROR] Uchenik '{platform_id_or_name}' ne naiden")
            return False

        datetime_str = f"{date_str} {time_str}"
        lesson_datetime_tomsk = datetime.strptime(datetime_str, '%Y-%m-%d %H:%M')
        lesson_datetime_tomsk = lesson_datetime_tomsk.replace(tzinfo=TOMSK_TZ)

        lesson_datetime = lesson_datetime_tomsk.astimezone(MOSCOW_TZ)

        existing = Lesson.query.filter_by(
            student_id=student.student_id,
            lesson_date=lesson_datetime
        ).first()

        if existing:
            print(f"[SKIP] Urok uzhe sushestvuet: {student.name} - {datetime_str}")
            return False

        lesson = Lesson(
            student_id=student.student_id,
            lesson_type='regular',
            lesson_date=lesson_datetime,
            duration=duration,
            status=status,
            homework_status='not_assigned'
        )

        db.session.add(lesson)
        db.session.commit()
        print(f"[OK] Sozdan urok: {student.name} - {datetime_str} ({duration} min, {status})")
        return True

def delete_lesson(platform_id_or_name, date_str, time_str):

    with app.app_context():

        student = Student.query.filter_by(platform_id=platform_id_or_name.strip()).first()

        if not student:
            student = Student.query.filter_by(name=platform_id_or_name.strip()).first()

        if not student:
            print(f"[ERROR] Uchenik '{platform_id_or_name}' ne naiden")
            return False

        datetime_str = f"{date_str} {time_str}"
        lesson_datetime = datetime.strptime(datetime_str, '%Y-%m-%d %H:%M')
        lesson_datetime = lesson_datetime.replace(tzinfo=MOSCOW_TZ)

        lesson = Lesson.query.filter_by(
            student_id=student.student_id,
            lesson_date=lesson_datetime
        ).first()

        if not lesson:
            print(f"[SKIP] Urok ne naiden: {student.name} - {datetime_str}")
            return False

        db.session.delete(lesson)
        db.session.commit()
        print(f"[OK] Udalен urok: {student.name} - {datetime_str}")
        return True

def extract_lessons_from_page():

    pass

if __name__ == '__main__':

    lessons = [

        {'platform_id_or_name': 'Серая кукушка 53', 'date_str': '2025-09-23', 'time_str': '23:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Иван', 'date_str': '2025-09-27', 'time_str': '17:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Серая кукушка 53', 'date_str': '2025-09-27', 'time_str': '20:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Иван', 'date_str': '2025-09-28', 'time_str': '17:00', 'duration': 55, 'status': 'completed'},

        {'platform_id_or_name': 'Серая кукушка 53', 'date_str': '2025-09-30', 'time_str': '23:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Оливковая альпака 48', 'date_str': '2025-10-01', 'time_str': '22:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Даниил', 'date_str': '2025-10-03', 'time_str': '19:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Кремовая нутрия 20', 'date_str': '2025-10-04', 'time_str': '16:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Иван', 'date_str': '2025-10-04', 'time_str': '17:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Серая кукушка 53', 'date_str': '2025-10-04', 'time_str': '20:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Иван', 'date_str': '2025-10-05', 'time_str': '17:00', 'duration': 55, 'status': 'completed'},

        {'platform_id_or_name': 'Морковная чайка 64', 'date_str': '2025-10-06', 'time_str': '21:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Красный налим 4', 'date_str': '2025-10-07', 'time_str': '21:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Оливковая альпака 48', 'date_str': '2025-10-08', 'time_str': '22:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Даниил', 'date_str': '2025-10-10', 'time_str': '19:00', 'duration': 55, 'status': 'completed'},

        {'platform_id_or_name': 'Ксения', 'date_str': '2025-10-13', 'time_str': '21:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Глеб', 'date_str': '2025-10-14', 'time_str': '21:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Яромир', 'date_str': '2025-10-14', 'time_str': '23:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Ксения', 'date_str': '2025-10-15', 'time_str': '21:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Матвей', 'date_str': '2025-10-15', 'time_str': '22:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Егор', 'date_str': '2025-10-16', 'time_str': '20:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Виктория', 'date_str': '2025-10-16', 'time_str': '21:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Даниил', 'date_str': '2025-10-17', 'time_str': '19:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Кирилл', 'date_str': '2025-10-18', 'time_str': '16:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Иван', 'date_str': '2025-10-18', 'time_str': '17:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Яромир', 'date_str': '2025-10-18', 'time_str': '20:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Иван', 'date_str': '2025-10-19', 'time_str': '17:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Матвей', 'date_str': '2025-10-19', 'time_str': '22:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Ксения', 'date_str': '2025-10-19', 'time_str': '21:00', 'duration': 55, 'status': 'completed'},

        {'platform_id_or_name': 'Даниил', 'date_str': '2025-10-20', 'time_str': '19:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Ксения', 'date_str': '2025-10-20', 'time_str': '21:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Глеб', 'date_str': '2025-10-21', 'time_str': '21:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Яромир', 'date_str': '2025-10-21', 'time_str': '23:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Александр', 'date_str': '2025-10-22', 'time_str': '15:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Ксения', 'date_str': '2025-10-22', 'time_str': '21:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Матвей', 'date_str': '2025-10-22', 'time_str': '22:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Егор', 'date_str': '2025-10-23', 'time_str': '20:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Виктория', 'date_str': '2025-10-23', 'time_str': '21:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Всеволод', 'date_str': '2025-10-23', 'time_str': '23:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Матвей', 'date_str': '2025-10-24', 'time_str': '21:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Кирилл', 'date_str': '2025-10-25', 'time_str': '16:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Иван', 'date_str': '2025-10-25', 'time_str': '17:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Яромир', 'date_str': '2025-10-25', 'time_str': '20:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Иван', 'date_str': '2025-10-26', 'time_str': '17:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Матвей', 'date_str': '2025-10-26', 'time_str': '22:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Ксения', 'date_str': '2025-10-26', 'time_str': '21:00', 'duration': 55, 'status': 'completed'},

        {'platform_id_or_name': 'Ярослав', 'date_str': '2025-10-27', 'time_str': '14:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Ксения', 'date_str': '2025-10-27', 'time_str': '21:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Леонид', 'date_str': '2025-10-27', 'time_str': '15:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Яромир', 'date_str': '2025-10-28', 'time_str': '23:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Кирилл', 'date_str': '2025-10-30', 'time_str': '14:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Виктория', 'date_str': '2025-10-30', 'time_str': '21:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Ксения', 'date_str': '2025-10-30', 'time_str': '21:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Всеволод', 'date_str': '2025-10-30', 'time_str': '23:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Ярослав', 'date_str': '2025-10-31', 'time_str': '14:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Кирилл', 'date_str': '2025-11-01', 'time_str': '14:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Иван', 'date_str': '2025-11-01', 'time_str': '17:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Яромир', 'date_str': '2025-11-01', 'time_str': '18:00', 'duration': 55, 'status': 'completed'},

        {'platform_id_or_name': 'Ярослав', 'date_str': '2025-11-03', 'time_str': '14:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Александр', 'date_str': '2025-11-03', 'time_str': '15:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Иван', 'date_str': '2025-11-03', 'time_str': '17:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Ксения', 'date_str': '2025-11-03', 'time_str': '21:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Леонид', 'date_str': '2025-11-03', 'time_str': '15:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Глеб', 'date_str': '2025-11-04', 'time_str': '21:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Яромир', 'date_str': '2025-11-04', 'time_str': '23:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'У Иван', 'date_str': '2025-11-05', 'time_str': '15:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Ксения', 'date_str': '2025-11-05', 'time_str': '21:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Матвей', 'date_str': '2025-11-05', 'time_str': '22:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Валера', 'date_str': '2025-11-05', 'time_str': '19:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Егор', 'date_str': '2025-11-06', 'time_str': '20:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Виктория', 'date_str': '2025-11-06', 'time_str': '21:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Всеволод', 'date_str': '2025-11-06', 'time_str': '23:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Ярослав', 'date_str': '2025-11-07', 'time_str': '14:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Матвей', 'date_str': '2025-11-07', 'time_str': '21:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Кирилл', 'date_str': '2025-11-08', 'time_str': '14:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Александр', 'date_str': '2025-11-08', 'time_str': '15:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Валера', 'date_str': '2025-11-08', 'time_str': '16:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Иван', 'date_str': '2025-11-08', 'time_str': '17:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Яромир', 'date_str': '2025-11-08', 'time_str': '18:00', 'duration': 55, 'status': 'completed'},

        {'platform_id_or_name': 'Ярослав', 'date_str': '2025-11-10', 'time_str': '14:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Ксения', 'date_str': '2025-11-10', 'time_str': '21:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Леонид', 'date_str': '2025-11-10', 'time_str': '15:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Глеб', 'date_str': '2025-11-11', 'time_str': '21:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Яромир', 'date_str': '2025-11-11', 'time_str': '23:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'У Иван', 'date_str': '2025-11-12', 'time_str': '15:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Матвей', 'date_str': '2025-11-12', 'time_str': '22:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Валера', 'date_str': '2025-11-12', 'time_str': '19:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Егор', 'date_str': '2025-11-13', 'time_str': '20:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Виктория', 'date_str': '2025-11-13', 'time_str': '21:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Ксения', 'date_str': '2025-11-13', 'time_str': '21:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Всеволод', 'date_str': '2025-11-13', 'time_str': '23:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Ярослав', 'date_str': '2025-11-14', 'time_str': '14:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Александр', 'date_str': '2025-11-14', 'time_str': '15:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Валера', 'date_str': '2025-11-14', 'time_str': '16:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Кирилл', 'date_str': '2025-11-15', 'time_str': '14:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Александр', 'date_str': '2025-11-15', 'time_str': '15:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Матвей', 'date_str': '2025-11-15', 'time_str': '22:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Иван', 'date_str': '2025-11-15', 'time_str': '17:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Яромир', 'date_str': '2025-11-15', 'time_str': '18:00', 'duration': 55, 'status': 'completed'},

        {'platform_id_or_name': 'Гридеперлевая гимнура 18', 'date_str': '2025-11-17', 'time_str': '14:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Глеб', 'date_str': '2025-11-18', 'time_str': '21:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Яромир', 'date_str': '2025-11-18', 'time_str': '23:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'У Иван', 'date_str': '2025-11-19', 'time_str': '15:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Валера', 'date_str': '2025-11-19', 'time_str': '19:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Ксения', 'date_str': '2025-11-19', 'time_str': '21:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Матвей', 'date_str': '2025-11-19', 'time_str': '22:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Егор', 'date_str': '2025-11-20', 'time_str': '20:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Виктория', 'date_str': '2025-11-20', 'time_str': '21:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Всеволод', 'date_str': '2025-11-20', 'time_str': '23:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Ярослав', 'date_str': '2025-11-21', 'time_str': '14:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Матвей', 'date_str': '2025-11-21', 'time_str': '21:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Кирилл', 'date_str': '2025-11-22', 'time_str': '14:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Александр', 'date_str': '2025-11-22', 'time_str': '15:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Валера', 'date_str': '2025-11-22', 'time_str': '16:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Иван', 'date_str': '2025-11-22', 'time_str': '17:00', 'duration': 55, 'status': 'completed'},
        {'platform_id_or_name': 'Яромир', 'date_str': '2025-11-22', 'time_str': '18:00', 'duration': 55, 'status': 'completed'},
    ]

    if not lessons:
        print("Spisok urokov pust. Dobavte uroki v spisok 'lessons'")
        sys.exit(0)

    print(f"Sozdanie {len(lessons)} urokov...\n")

    created = 0
    for lesson_data in lessons:
        lesson_data_copy = lesson_data.copy()
        platform_id_or_name = lesson_data_copy.pop('platform_id_or_name')
        date_str = lesson_data_copy.pop('date_str')
        time_str = lesson_data_copy.pop('time_str')
        if create_lesson(platform_id_or_name, date_str, time_str, **lesson_data_copy):
            created += 1

    print(f"\n[OK] Vsego sozdano: {created} iz {len(lessons)}")
