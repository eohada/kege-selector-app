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
from app.models import Course, CourseTaskTemplate, Subject, User, UserRole, TheoryBlock
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
        for tn in range(1, 17):
            score = 2 if tn >= 13 else 1
            db.session.add(CourseTaskTemplate(
                course_id=oge.id, task_number=tn,
                max_primary_score=score, requires_manual_review=(tn >= 13),
            ))
        print("  Seeded 16 CourseTaskTemplates for OGE")
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


# Краткая теория для демо: задание 1 ОГЭ (объём информации, кодирование)
THEORY_OGE_TASK1 = """
## Задание 1 ОГЭ. Объём информации и кодирование

Задание 1 проверяет умение **оценивать объём памяти** для хранения текстовых данных при разных кодировках.

### Единицы измерения
- **1 бит** — минимальная единица информации (0 или 1).
- **1 байт = 8 бит** — один символ в кодировке с 256 символами.
- **1 Кбайт = 1024 байт**, 1 Мбайт = 1024 Кбайт.

### Кодировки (бит на символ)
- **КОИ-8, Windows-1251, ASCII**: 1 байт = 8 бит на символ.
- **Unicode (UTF-16)**: 2 байта = 16 бит на символ.
- **UTF-32**: 4 байта на символ.

### Типовые задачи
1. **Добавление текста**: посчитать количество добавленных символов (включая пробелы и знаки), умножить на размер символа в битах/байтах.
2. **Удаление текста**: заданное уменьшение размера (в байтах) разделить на размер одного символа — получится количество удалённых символов.

**Пример:** Текст в кодировке UTF-16 (2 байта на символ). Добавили слово из 6 букв и пробел — 7 символов. Объём увеличился на 7 × 2 = **14 байт**.
"""

# Краткая теория для демо: задание 1 ЕГЭ — графы (информационные модели)
THEORY_EGE_TASK1 = """
## Задание 1 ЕГЭ. Графы и информационные модели

Задание 1 проверяет **анализ информационных моделей**: схемы дорог (графы), таблицы, соответствия между обозначениями.

### Основные понятия
- **Граф** — вершины (узлы) и рёбра (связи между ними). Часто даётся схема дорог между пунктами с буквенными обозначениями.
- **Таблица** — сведения о протяжённостях или других величинах с числовыми номерами пунктов.
- Нужно **сопоставить буквы на схеме с номерами в таблице**, затем найти сумму или другую величину по условию.

### Как решать
1. Найти вершину с **уникальным числом связей** на схеме (например, только одна дорога входит/выходит) и такую же в таблице — по ним сопоставить букву и номер.
2. По цепочке сопоставить остальные пункты.
3. По таблице вычислить требуемую величину (сумма дорог между указанными пунктами и т.п.).
4. Записать ответ в указанном формате (целое число).
"""


def ensure_demo_theory(ege_course_id, oge_course_id, author_id):
    """
    Создаёт блоки теории для демо: ЕГЭ — 27 карточек (1 заполнена, остальные пустышки),
    ОГЭ — 16 карточек (1 заполнена, остальные пустышки).
    """
    # ЕГЭ: 1..27
    for tn in range(1, 28):
        existing = TheoryBlock.query.filter_by(course_id=ege_course_id, task_number=tn).first()
        if existing:
            if tn == 1 and not (existing.content and existing.content.strip()):
                existing.title = "Задание 1. Графы и информационные модели"
                existing.content = THEORY_EGE_TASK1.strip()
            continue
        title = "Задание 1. Графы и информационные модели" if tn == 1 else f"Задание {tn}"
        content = THEORY_EGE_TASK1.strip() if tn == 1 else None
        db.session.add(TheoryBlock(
            course_id=ege_course_id,
            task_number=tn,
            title=title,
            content=content,
            author_id=author_id,
        ))
    print("  Seeded 27 TheoryBlocks for EGE (task 1 filled, rest placeholders)")

    # ОГЭ: 1..16
    for tn in range(1, 17):
        existing = TheoryBlock.query.filter_by(course_id=oge_course_id, task_number=tn).first()
        if existing:
            if tn == 1 and not (existing.content and existing.content.strip()):
                existing.title = "Задание 1. Объём информации и кодирование"
                existing.content = THEORY_OGE_TASK1.strip()
            continue
        title = "Задание 1. Объём информации и кодирование" if tn == 1 else f"Задание {tn}"
        content = THEORY_OGE_TASK1.strip() if tn == 1 else None
        db.session.add(TheoryBlock(
            course_id=oge_course_id,
            task_number=tn,
            title=title,
            content=content,
            author_id=author_id,
        ))
    print("  Seeded 16 TheoryBlocks for OGE (task 1 filled, rest placeholders)")


def ensure_demo_scenario_tasks(ege_course_id, oge_course_id, data_dir):
    """
    Создаёт задачи демо из data/demo_scenario.json: жёстко заданные условия, ответы,
    подсказка и исправление для тренажёра. site_task_id: demo:assign:1, demo:assign:2, ..., demo:trainer.
    """
    path = os.path.join(data_dir, 'demo_scenario.json')
    if not os.path.isfile(path):
        print("  Skip demo scenario: demo_scenario.json not found")
        return
    with open(path, 'r', encoding='utf-8') as f:
        scenario = json.load(f)
    for exam_key, course_id in [('ege', ege_course_id), ('oge', oge_course_id)]:
        if exam_key not in scenario or not course_id:
            continue
        data = scenario[exam_key]
        tasks_data = data.get('assignment_tasks') or []
        trainer_data = data.get('trainer') or {}
        for i, item in enumerate(tasks_data):
            site_id = f"demo:assign:{i + 1}"
            existing = Tasks.query.filter_by(course_id=course_id, site_task_id=site_id).first()
            if existing:
                existing.content_html = item.get('condition_html') or existing.content_html
                existing.answer = item.get('answer') or existing.answer
                continue
            db.session.add(Tasks(
                course_id=course_id,
                task_number=i + 1,
                site_task_id=site_id,
                content_html=item.get('condition_html') or '',
                answer=item.get('answer') or '',
            ))
        # Одна задача для тренажёра
        if trainer_data:
            site_id = "demo:trainer"
            hint = trainer_data.get('assistant_reply') or trainer_data.get('hint') or ''
            correction = trainer_data.get('correction_text') or ''
            hints_json = [{"text": hint}, {"text": correction}] if (hint or correction) else None
            existing = Tasks.query.filter_by(course_id=course_id, site_task_id=site_id).first()
            if existing:
                existing.content_html = trainer_data.get('condition_html') or existing.content_html
                existing.answer = trainer_data.get('answer') or existing.answer
                existing.hints = hints_json
                continue
            db.session.add(Tasks(
                course_id=course_id,
                task_number=5,
                site_task_id=site_id,
                content_html=trainer_data.get('condition_html') or '',
                answer=trainer_data.get('answer') or '',
                hints=hints_json,
            ))
    print("  Seeded demo scenario tasks from demo_scenario.json")


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
            ege, oge = ensure_courses(app)
            db.session.flush()
            ensure_subjects()
            creator = ensure_demo_creator()
            ensure_demo_theory(ege.id, oge.id, creator.id)
            ensure_demo_scenario_tasks(ege.id, oge.id, data_dir)
            db.session.flush()
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
