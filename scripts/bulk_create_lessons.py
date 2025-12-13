
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from core.db_models import Student, Lesson, MOSCOW_TZ

def create_lessons_from_data(lessons_data):

    created_count = 0
    skipped_count = 0
    errors = []

    with app.app_context():
        for lesson_data in lessons_data:
            try:

                platform_id = lesson_data.get('platform_id')
                if not platform_id:
                    errors.append(f"Пропущен урок: не указан platform_id")
                    skipped_count += 1
                    continue

                student = Student.query.filter_by(platform_id=platform_id.strip()).first()
                if not student:
                    errors.append(f"Ученик с ID '{platform_id}' не найден")
                    skipped_count += 1
                    continue

                date_str = lesson_data.get('date')
                time_str = lesson_data.get('time', '10:00')
                duration = lesson_data.get('duration', 60)
                status = lesson_data.get('status', 'completed')

                datetime_str = f"{date_str} {time_str}"
                lesson_datetime = datetime.strptime(datetime_str, '%Y-%m-%d %H:%M')
                lesson_datetime = lesson_datetime.replace(tzinfo=MOSCOW_TZ)

                existing = Lesson.query.filter_by(
                    student_id=student.student_id,
                    lesson_date=lesson_datetime
                ).first()

                if existing:
                    errors.append(f"Урок уже существует: {student.name} - {datetime_str}")
                    skipped_count += 1
                    continue

                lesson = Lesson(
                    student_id=student.student_id,
                    lesson_type='regular',
                    lesson_date=lesson_datetime,
                    duration=duration,
                    status=status,
                    topic=None,
                    notes=None,
                    homework=None,
                    homework_status='not_assigned'
                )

                db.session.add(lesson)
                created_count += 1

            except Exception as e:
                errors.append(f"Ошибка при создании урока: {lesson_data} - {str(e)}")
                skipped_count += 1
                continue

        try:
            db.session.commit()
            print(f"\n✅ Успешно создано уроков: {created_count}")
            print(f"⏭️  Пропущено: {skipped_count}")
            if errors:
                print(f"\n⚠️  Ошибки и предупреждения:")
                for error in errors:
                    print(f"   - {error}")
        except Exception as e:
            db.session.rollback()
            print(f"\n❌ Ошибка при сохранении: {e}")

if __name__ == '__main__':

    lessons_data = [

    ]

    if not lessons_data:
        print("⚠️  Данные уроков не указаны!")
        print("\nДобавьте данные в формате:")
        print()
        sys.exit(1)

    print(f"Создание {len(lessons_data)} уроков...")
    create_lessons_from_data(lessons_data)
