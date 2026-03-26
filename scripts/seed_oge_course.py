"""
Seed script: creates OGE Informatics course, task templates (1-15), and grading scale.
Usage: flask shell < scripts/seed_oge_course.py
   OR: python -c "from scripts.seed_oge_course import seed_oge; seed_oge()"
   OR: python scripts/seed_oge_course.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.models import db, Course, CourseTaskTemplate, GradingScale


OGE_COURSE_TITLE = 'ОГЭ Информатика'
OGE_COURSE_SLUG = 'oge-inf'

OGE_TASK_SPECS = [
    # (task_number, max_primary_score, requires_manual_review)
    (1,  1, False),
    (2,  1, False),
    (3,  1, False),
    (4,  1, False),
    (5,  1, False),
    (6,  1, False),
    (7,  1, False),
    (8,  1, False),
    (9,  1, False),
    (10, 1, False),
    (11, 1, False),
    (12, 1, False),
    (13, 2, True),   # файловое задание
    (14, 1, False),
    (15, 2, True),   # программирование
]

OGE_GRADING_SCALE = [
    # (min_primary, max_primary, final_grade, label)
    (0,  4,  2, 'Неудовлетворительно'),
    (5,  10, 3, 'Удовлетворительно'),
    (11, 15, 4, 'Хорошо'),
    (16, 19, 5, 'Отлично'),
]


def seed_oge():
    """Create OGE Informatics course with task templates and grading scale."""
    course = Course.query.filter_by(slug=OGE_COURSE_SLUG).first()
    if course:
        print(f'Курс "{OGE_COURSE_TITLE}" (slug={OGE_COURSE_SLUG}) уже существует (id={course.id}), пропуск.')
        return course

    try:
        course = Course(title=OGE_COURSE_TITLE, slug=OGE_COURSE_SLUG, is_active=True)
        db.session.add(course)
        db.session.flush()
        print(f'Создан курс: {course}')

        for task_number, max_score, manual in OGE_TASK_SPECS:
            tpl = CourseTaskTemplate(
                course_id=course.id,
                task_number=task_number,
                max_primary_score=max_score,
                requires_manual_review=manual,
            )
            db.session.add(tpl)
        print(f'Создано {len(OGE_TASK_SPECS)} шаблонов заданий (CourseTaskTemplate)')

        for min_p, max_p, grade, label in OGE_GRADING_SCALE:
            gs = GradingScale(
                course_id=course.id,
                min_primary=min_p,
                max_primary=max_p,
                final_grade=grade,
                label=label,
            )
            db.session.add(gs)
        print(f'Создано {len(OGE_GRADING_SCALE)} записей шкалы оценивания (GradingScale)')

        db.session.commit()
        print('seed_oge: OK')
        return course

    except Exception as exc:
        db.session.rollback()
        print(f'seed_oge: ОШИБКА — {exc}')
        raise


if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        seed_oge()
