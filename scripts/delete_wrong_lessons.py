
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from core.db_models import Lesson

def delete_wrong_lessons():

    with app.app_context():

        lessons_2024 = Lesson.query.filter(
            Lesson.lesson_date >= datetime(2024, 1, 1).replace(tzinfo=None),
            Lesson.lesson_date < datetime(2025, 1, 1).replace(tzinfo=None)
        ).all()

        deleted_2024 = 0
        for lesson in lessons_2024:
            db.session.delete(lesson)
            deleted_2024 += 1

        lessons_wrong_time = Lesson.query.filter(
            Lesson.lesson_date >= datetime(2025, 9, 23).replace(tzinfo=None),
            Lesson.lesson_date <= datetime(2025, 10, 5, 23, 59, 59).replace(tzinfo=None)
        ).all()

        deleted_wrong_time = 0
        for lesson in lessons_wrong_time:
            db.session.delete(lesson)
            deleted_wrong_time += 1

        db.session.commit()

        print(f"[OK] Udaleno urokov za 2024 god: {deleted_2024}")
        print(f"[OK] Udaleno urokov s nepravilnym vremenem (2025): {deleted_wrong_time}")
        print(f"[OK] Vsego udaleno: {deleted_2024 + deleted_wrong_time}")

if __name__ == '__main__':
    delete_wrong_lessons()
