"""
Сидирование демо-БД для изолированного демо-сайта.

Запуск после миграций на инстансе с DEMO_SITE=true (или с --demo):
  DEMO_SITE=true python scripts/seed_demo_db.py
  # или: python scripts/seed_demo_db.py --demo

Делает:
- Проверяет/создаёт курсы ЕГЭ и ОГЭ (ExamCourses), шаблоны заданий (миграции уже могли создать).
- Создаёт субъекты Subject (kege, oge) при отсутствии.
- Создаёт одного пользователя-создателя для created_by_id в демо-назначениях.
- Опционально импортирует задания ОГЭ из data/oge_inf_tasks.json, если заданий ОГЭ мало.
"""

import os
import sys
import json
import argparse

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from werkzeug.security import generate_password_hash

from sqlalchemy import text
from app import create_app, db
from app.models import Course, CourseTaskTemplate, Subject, User, UserRole
from core.db_models import Tasks, moscow_now
from app.utils.db_migrations import ensure_schema_columns


def ensure_courses(app):
    """Курсы ЕГЭ и ОГЭ + шаблоны заданий (если ещё нет)."""
    ege = Course.query.filter_by(slug='ege_informatics').first()
    if not ege:
        ege = Course(title='ЕГЭ Информатика', slug='ege_informatics', is_active=True)
        db.session.add(ege)
        db.session.flush()
        print("  Created Course: ege_informatics")
    if CourseTaskTemplate.query.filter_by(course_id=ege.id).count() == 0:
        for tn in range(1, 28):
            score = 2 if tn >= 25 else 1
            db.session.add(CourseTaskTemplate(
                course_id=ege.id, task_number=tn,
                max_primary_score=score, requires_manual_review=False,
            ))
        print("  Seeded 27 CourseTaskTemplates for EGE")

    oge = Course.query.filter_by(slug='oge_informatics').first()
    if not oge:
        oge = Course(title='ОГЭ Информатика', slug='oge_informatics', is_active=True)
        db.session.add(oge)
        db.session.flush()
        print("  Created Course: oge_informatics")
    if CourseTaskTemplate.query.filter_by(course_id=oge.id).count() == 0:
        for tn in range(1, 16):
            score = 2 if tn >= 13 else 1
            db.session.add(CourseTaskTemplate(
                course_id=oge.id, task_number=tn,
                max_primary_score=score, requires_manual_review=(tn >= 13),
            ))
        print("  Seeded 15 CourseTaskTemplates for OGE")
    return ege, oge


def ensure_subjects():
    """Субъекты kege и oge для аналитики."""
    for slug, name in [('kege', 'Информатика КЕГЭ'), ('oge', 'Информатика ОГЭ')]:
        if Subject.query.filter_by(slug=slug).first():
            continue
        db.session.add(Subject(slug=slug, name=name))
        print(f"  Created Subject: {slug}")


def ensure_demo_creator():
    """Один пользователь-создатель для демо-назначений."""
    u = User.query.filter_by(username='demo_creator').first()
    if u:
        return u
    u = User(
        username='demo_creator',
        email='demo_creator@demo.local',
        password_hash=generate_password_hash('demo'),
        role='creator',
        is_active=True,
        is_demo_user=False,
    )
    db.session.add(u)
    db.session.flush()
    db.session.add(UserRole(user_id=u.id, role='creator'))
    print("  Created User: demo_creator (password: demo)")
    return u


def import_oge_tasks_from_json(oge_course_id, data_dir, limit=500):
    """Импорт заданий ОГЭ из data/oge_inf_tasks.json."""
    path = os.path.join(data_dir, 'oge_inf_tasks.json')
    if not os.path.isfile(path):
        print("  Skip OGE import: oge_inf_tasks.json not found")
        return 0
    count = Tasks.query.filter_by(course_id=oge_course_id).count()
    if count >= 50:
        print(f"  OGE tasks already present: {count}, skip import")
        return 0
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    added = 0
    for item in data[:limit]:
        task_number = item.get('task_number') or 1
        if task_number < 1 or task_number > 15:
            continue
        content_html = item.get('content_html') or ''
        answer = item.get('answer')
        if isinstance(answer, list):
            answer = answer[0] if answer else None
        if not content_html:
            continue
        t = Tasks(
            course_id=oge_course_id,
            task_number=task_number,
            content_html=content_html,
            answer=str(answer).strip() if answer else None,
            site_task_id=str(item.get('site_id', '')),
            source_url=item.get('source_url'),
        )
        db.session.add(t)
        added += 1
    if added:
        print(f"  Imported {added} OGE tasks from oge_inf_tasks.json")
    return added


def main():
    parser = argparse.ArgumentParser(description="Seed demo DB for isolated demo site")
    parser.add_argument("--demo", action="store_true", help="Run as demo seed (even without DEMO_SITE)")
    parser.add_argument("--no-oge-import", action="store_true", help="Do not import OGE tasks from JSON")
    args = parser.parse_args()

    if not args.demo and os.environ.get('DEMO_SITE', 'false').lower() != 'true':
        print("Set DEMO_SITE=true or use --demo to run this script.")
        return 1

    app = create_app()
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    data_dir = os.path.join(base_dir, 'data')

    with app.app_context():
        try:
            db.session.execute(text("SELECT 1"))
            ensure_schema_columns(app)
            db.session.commit()
        except Exception as e:
            print("Warning: ensure_schema_columns failed:", e)
            db.session.rollback()

        try:
            ensure_courses(app)
            db.session.flush()
            ensure_subjects()
            ensure_demo_creator()
            oge = Course.query.filter_by(slug='oge_informatics').first()
            if oge and not args.no_oge_import:
                import_oge_tasks_from_json(oge.id, data_dir)
            db.session.commit()
            print("Demo DB seed completed.")
            return 0
        except Exception as e:
            db.session.rollback()
            print("Seed failed:", e)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
