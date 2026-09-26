"""
Скрипт создания демонстрационного ученика для презентаций и показов (Showcase Student).

Создает:
1. Учетную запись ученика: demo_student (пароль: 123)
2. Профиль Student: Алексей Смирнов (Демо), 11 класс, цель 90 баллов, Python, 3850 XP (Уровень 8), стрик 18 дней
3. Учетную запись родителя: demo_parent (пароль: 123), связанную через FamilyTie
4. Связь с преподавателем (Enrollment под creator / tutor)
5. Персональную учебную программу (LearningTrajectory) из 4 модулей
6. 20 проведенных уроков (completed) за последние 2.5 месяца с детальными LessonOutcome (оценки 4-5, заметки, темп)
7. 2 запланированных урока на следующую неделю (для расписания)
8. 6 разнообразных домашних заданий и срезов:
   - 4 проверенных ДЗ (оценки 100%, 75%, 100%, 83%) с кодом ученика, замечаниями учителя
   - 1 полный проверенный Пробник ЕГЭ (23/27 баллов, 88 тестовых баллов)
   - 1 сданная свежая работа (SUBMITTED, ожидает проверки преподавателем)
9. Код ученика, снапшоты в CodeWorkspaceVersion и трейсы пошагового набора (CodePlaybackTrace)
10. Статистику по всем 27 номерам КЕГЭ (StudentTaskStatistics, ~140 решенных задач)
11. Контрольные точки динамики роста (StudentDiagnosticCheckpoint: 62 -> 76 -> 88 баллов)
12. 10 разблокированных наград и достижений (UserAchievement)

Запуск:
  venv/bin/python scripts/seed_demo_student.py
  # Или с параметрами:
  venv/bin/python scripts/seed_demo_student.py --username demo_student --password 123
"""

from __future__ import annotations

import os
import sys
import argparse
from datetime import datetime, timedelta, timezone
from typing import Optional

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from werkzeug.security import generate_password_hash

from app import create_app, db
from core.db_models import (
    moscow_now, utc_now, MOSCOW_TZ,
    User, UserProfile, Student, Enrollment, FamilyTie,
    Course, CourseTaskTemplate,
    LearningTrajectory, TrajectoryModule, Lesson, LessonTask, LessonOutcome, LearningItem,
    Assignment, AssignmentTask, Submission, Answer,
    StudentTaskStatistics, StudentDiagnosticCheckpoint,
    UserAchievement, CodeWorkspaceVersion, CodePlaybackTrace,
    SubmissionComment, Tasks, ExamSkill, StudentSkill,
)
from app.utils.db_migrations import ensure_schema_columns


def get_or_create_tutor() -> User:
    """Находит или создает аккаунт преподавателя/куратора для привязки демо-ученика."""
    tutor = User.query.filter_by(username='creator').first()
    if not tutor:
        tutor = User.query.filter(User.role.in_(['tutor', 'teacher', 'admin', 'chief_admin'])).first()
    if not tutor:
        tutor = User(
            username='creator',
            email='creator@demo.local',
            password_hash=generate_password_hash('123'),
            role='creator',
            is_active=True,
            created_at=moscow_now(),
        )
        db.session.add(tutor)
        db.session.flush()
    return tutor


def get_or_create_ege_course() -> Course:
    """Находит или создает базовый курс ЕГЭ Информатика."""
    ege = Course.query.filter_by(slug='ege_informatics').first()
    if not ege:
        ege = Course(
            title='ЕГЭ Информатика',
            slug='ege_informatics',
            is_active=True,
            created_at=moscow_now(),
        )
        db.session.add(ege)
        db.session.flush()

    if CourseTaskTemplate.query.filter_by(course_id=ege.id).count() == 0:
        for tn in range(1, 28):
            score = 2 if tn >= 25 else 1
            db.session.add(CourseTaskTemplate(
                course_id=ege.id,
                task_number=tn,
                max_primary_score=score,
                requires_manual_review=(tn in (26, 27)),
            ))
        db.session.flush()
    return ege


def get_task_for_number(tnum: int, tutor_id: int, ege_course_id: int) -> Tasks:
    """Возвращает существующую задачу заданного номера или создает типовую для демонстрации."""
    task = Tasks.query.filter_by(task_number=tnum).first()
    if not task:
        task_prompts = {
            1: "На рисунке схема дорог изображена в виде графа, в таблице содержатся сведения о длинах этих дорог. Определите длину дороги из пункта А в пункт Д.",
            2: "Миша заполнял таблицу истинности логической функции F = (x ≡ y ) ∨ (¬x ∧ z) ∧ w. Определите, какому столбцу соответствует каждая из переменных.",
            4: "По каналу связи передаются сообщения, содержащие только 5 букв: А, Б, В, Г, Д. Используется префиксный код, удовлетворяющий условию Фано. Найдите кратчайшее кодовое слово для буквы Д.",
            8: "Определите количество 5-значных чисел в 8-ричной системе счисления, в записи которых только одна цифра 7, а рядом с ней не стоят четные цифры.",
            14: "Значение арифметического выражения 49^7 + 7^21 - 49 записали в системе счисления с основанием 7. Сколько цифр 6 содержится в этой записи?",
            16: "Алгоритм вычисления функции F(n) задан соотношениями: F(1)=1; F(n)=n + F(n-1) при n > 1. Чему равно значение F(2026)?",
            17: "В файле содержится последовательность целых чисел. Определите количество пар элементов последовательности, в которых хотя бы одно число делится на 13, а сумма элементов меньше максимального элемента.",
            19: "Два игрока, Петя и Ваня, играют в игру с одной кучей камней. За один ход можно добавить 1 камень или увеличить количество камней в 2 раза. Игра завершается, когда камней >= 55.",
            20: "Для игры, описанной в задании 19, найдите два таких значения S, при которых у Пети есть выигрышная стратегия, причем Петя не может выиграть за 1 ход, но может выиграть своим вторым ходом.",
            21: "Для игры, описанной в задании 19, найдите значение S, при котором у Вани есть выигрышная стратегия, позволяющая ему выиграть первым или вторым ходом.",
            24: "Текстовый файл состоит из символов латинского алфавита. Определите максимальное количество идущих подряд символов, среди которых нет комбинации символов 'XYZ'.",
            26: "В магазине проводится акция. Покупатель получает скидку на определенные товары. Определите максимальное количество товаров и наибольшую стоимость приобретенного товара.",
            27: "Дана последовательность целых чисел. Необходимо выбрать такую подпоследовательность подряд идущих элементов, чтобы их сумма делилась на 89 и была максимальной.",
        }
        prompt = task_prompts.get(tnum, f"Условие тренировочного задания КЕГЭ №{tnum} по информатике.")
        task = Tasks(
            task_number=tnum,
            site_task_id=f"demo_kege_{tnum}",
            content_html=f"<p>{prompt}</p>",
            answer="42" if tnum != 2 else "yxzw",
            max_score=2 if tnum in (25, 26, 27) else 1,
            created_by_id=tutor_id,
            course_id=ege_course_id,
            difficulty_level=1 if tnum <= 10 else (2 if tnum <= 23 else 3),
        )
        db.session.add(task)
        db.session.flush()
    return task


def seed_demo_student(username: str = "demo_student", password: str = "123", tutor_username: Optional[str] = None):
    """Создает полного демонстрационного ученика с уроками, домашками, статистикой и достижениями."""
    print("=" * 70)
    print("🚀 Запуск сидирования демонстрационного ученика (Showcase Student)...")
    print("=" * 70)

    # 1. Преподаватель и курс
    tutor = None
    if tutor_username:
        tutor = User.query.filter_by(username=tutor_username).first()
    if not tutor:
        tutor = get_or_create_tutor()
    print(f"✓ Преподаватель для привязки: {tutor.username} (ID: {tutor.id})")

    ege_course = get_or_create_ege_course()
    print(f"✓ Базовый курс экзамена: {ege_course.title} (ID: {ege_course.id})")

    # 2. Создание / сброс учетной записи ученика
    user = User.query.filter_by(username=username).first()
    if not user:
        user = User(
            username=username,
            email=f"{username}@boostudy.ru",
            password_hash=generate_password_hash(password),
            role='student',
            is_active=True,
            created_at=moscow_now() - timedelta(days=90),
        )
        db.session.add(user)
        db.session.flush()
        print(f"✓ Создан User: {user.username} (ID: {user.id})")
    else:
        user.password_hash = generate_password_hash(password)
        user.role = 'student'
        user.is_active = True
        print(f"✓ Обновлен существующий User: {user.username} (ID: {user.id})")

    # Профиль пользователя
    prof = UserProfile.query.filter_by(user_id=user.id).first()
    if not prof:
        prof = UserProfile(
            user_id=user.id,
            first_name='Алексей',
            last_name='Смирнов',
            timezone='Europe/Moscow',
        )
        db.session.add(prof)
    else:
        prof.first_name = 'Алексей'
        prof.last_name = 'Смирнов'
        prof.timezone = 'Europe/Moscow'

    # 3. Сущность Student
    student = Student.query.filter_by(user_id=user.id).first()
    if not student:
        student = Student(
            user_id=user.id,
            name="Алексей Смирнов (Демо)",
            email=user.email,
            phone="+7 (999) 555-42-42",
            telegram="@demo_student_smirnov",
            school_class=11,
            category="ЕГЭ",
            programming_language="Python",
            target_score=90,
            xp=3850,
            level=8,
            streak_days=18,
            study_time_seconds=154800,  # ~43 часа чистого времени обучения
            diagnostic_level="Продвинутый (B2)",
            strengths="Быстрое решение базовых номеров КЕГЭ (1–15, 18), уверенный перебор на Python (задачи 8, 14, 16), отличная алгоритмическая логика.",
            weaknesses="Оптимизация по памяти в задаче 26, сложные кольцевые буферы в задаче 27, аккуратность в индексах строк.",
            notes="Демонстрационный аккаунт ученика с полной историей обучения: 20 проведенных уроков, сданные ДЗ с код-ревью и аналитика.",
            lessons_balance=8,
            mentor_id=tutor.id,
            is_active=True,
            created_at=moscow_now() - timedelta(days=80),
        )
        db.session.add(student)
        db.session.flush()
        student.platform_id = f"BS-{student.student_id:04d}"
        print(f"✓ Создан Student: {student.name} (ID: {student.student_id})")
    else:
        student.name = "Алексей Смирнов (Демо)"
        student.school_class = 11
        student.programming_language = "Python"
        student.target_score = 90
        student.xp = 3850
        student.level = 8
        student.streak_days = 18
        student.study_time_seconds = 154800
        student.mentor_id = tutor.id
        student.lessons_balance = 8
        student.is_active = True
        print(f"✓ Обновлен Student: {student.name} (ID: {student.student_id})")

    # 4. Привязка преподавателя (Enrollment)
    enrollment = Enrollment.query.filter_by(student_id=user.id, tutor_id=tutor.id).first()
    if not enrollment:
        enrollment = Enrollment(
            student_id=user.id,
            tutor_id=tutor.id,
            subject='Информатика КЕГЭ',
            status='active',
            settings={'hourly_rate': 2500, 'color': '#10b981'},
            created_at=moscow_now() - timedelta(days=80),
        )
        db.session.add(enrollment)
        print("✓ Создана привязка к преподавателю (Enrollment)")

    # 5. Родительский аккаунт и семейная связь (FamilyTie)
    parent_user = User.query.filter_by(username='demo_parent').first()
    if not parent_user:
        parent_user = User(
            username='demo_parent',
            email='parent@boostudy.ru',
            password_hash=generate_password_hash('123'),
            role='parent',
            is_active=True,
            created_at=moscow_now() - timedelta(days=80),
        )
        db.session.add(parent_user)
        db.session.flush()
        print("✓ Создан аккаунт родителя: demo_parent (пароль: 123)")

    parent_prof = UserProfile.query.filter_by(user_id=parent_user.id).first()
    if not parent_prof:
        parent_prof = UserProfile(
            user_id=parent_user.id,
            first_name='Елена',
            last_name='Смирнова',
            timezone='Europe/Moscow',
        )
        db.session.add(parent_prof)

    tie = FamilyTie.query.filter_by(parent_id=parent_user.id, student_id=user.id).first()
    if not tie:
        tie = FamilyTie(
            parent_id=parent_user.id,
            student_id=user.id,
            access_level='full',
            is_confirmed=True,
            created_at=moscow_now() - timedelta(days=80),
        )
        db.session.add(tie)
        print("✓ Создана семейная связь ученика с родителем (FamilyTie)")

    # 6. Персональная траектория обучения (LearningTrajectory / Courses)
    trajectory = LearningTrajectory.query.filter_by(student_id=student.student_id).first()
    if not trajectory:
        trajectory = LearningTrajectory(
            student_id=student.student_id,
            created_by_user_id=tutor.id,
            is_template=False,
            title="Индивидуальная программа подготовки к ЕГЭ: Алексей Смирнов",
            subject="Информатика",
            description="Комплексный 72-часовой курс с упором на программирование на Python, решение всех 27 номеров КЕГЭ и регулярные контрольные срезы.",
            learning_goal="Уверенное решение заданий №1–27 на 90+ баллов на реальном экзамене.",
            expected_result="Поступление на бюджет по направлению 'Программная инженерия'.",
            target_score=90,
            default_lesson_duration=60,
            exam_course_id=ege_course.id,
            status='active',
            created_at=moscow_now() - timedelta(days=80),
        )
        db.session.add(trajectory)
        db.session.flush()
        print(f"✓ Создана траектория обучения: {trajectory.title} (ID: {trajectory.course_id})")

    # Модули курса
    modules_specs = [
        (1, "Модуль 1: Анализ данных и информационные модели (№1–8)", "Графы, таблицы истинности, кодирование и комбинаторика"),
        (2, "Модуль 2: Электронные таблицы и поиск информации (№9–14)", "Поиск, Excel, позиционные системы счисления"),
        (3, "Модуль 3: Алгебра логики, рекурсия и теория игр (№15–21)", "Множества, отрезки, мемоизация и выигрышные стратегии"),
        (4, "Модуль 4: Продвинутые алгоритмы и динамика (№22–27)", "Жадные алгоритмы, сортировка, анализ префиксных сумм"),
    ]
    modules_map = {}
    for m_idx, m_title, m_desc in modules_specs:
        mod = TrajectoryModule.query.filter_by(course_id=trajectory.course_id, order_index=m_idx * 10).first()
        if not mod:
            mod = TrajectoryModule(
                course_id=trajectory.course_id,
                title=m_title,
                description=m_desc,
                order_index=m_idx * 10,
                is_control_exam=(m_idx == 4),
            )
            db.session.add(mod)
            db.session.flush()
        modules_map[m_idx] = mod
    print(f"✓ Обеспечены 4 модуля траектории обучения")

    # 7. Генерация 20 проведенных уроков + 2 запланированных
    lessons_topics = [
        (1, 1, "Графы и таблицы смежности (Задание №1)", 70, 5, "Отлично ориентируется в весовых матрицах, быстро находит вершины."),
        (1, 2, "Таблицы истинности и логические функции (Задание №2)", 66, 5, "Написал перебор на Python в 4 строчки. Все тесты сдал с первого раза."),
        (1, 3, "Реляционные базы данных и фильтрация (Задание №3)", 63, 4, "Потренировали сложные условия с несколькими связями между таблицами."),
        (1, 4, "Кодирование данных и условие Фано (Задание №4)", 59, 5, "Деревья строит аккуратно, нашел кратчайшее кодовое слово без ошибок."),
        (1, 5, "Анализ алгоритмов для автоматов (Задание №5)", 56, 4, "Разобрали двоичную модификацию чисел. Хороший темп."),
        (1, 6, "Циклы и геометрия исполнителя Черепаха (Задание №6)", 52, 5, "Масштабирование точек в библиотеке turtle усвоено на 100%."),
        (1, 7, "Кодирование графики и звука (Задание №7)", 49, 4, "Повторили перевод байт в килобайты и учет сжатия звукового файла."),
        (1, 8, "Комбинаторика и перестановки на Python (Задание №8)", 45, 4, "Использовали itertools.product и permutations. Отличная практика."),
        (2, 9, "Обработка числовых массивов в таблицах (Задание №9)", 42, 5, "Формулы СЧЁТЕСЛИ и МАКС освоены в совершенстве."),
        (2, 10, "Поиск по тексту и учет регистра (Задание №10)", 38, 5, "Быстро выполнил задания в Word/LibreOffice."),
        (2, 11, "Хранение идентификаторов и информационный объем (Задание №11)", 35, 5, "Без ошибок округляет биты в байты для каждого пользователя."),
        (2, 12, "Исполнитель Редактор и замена строк (Задание №12)", 31, 5, "Написал цикл while с методом replace. Решил все 5 задач."),
        (2, 13, "Поиск количества путей в графе (Задание №13)", 28, 4, "Динамический подсчет входящих путей освоен."),
        (2, 14, "Позиционные системы счисления (Задание №14)", 24, 5, "Перевод в произвольные системы делением с остатком на Python."),
        (3, 15, "Отрезки и побитовая конъюнкция (Задание №15)", 21, 4, "Разобрали поразрядную конъюнкцию и отрезки действительных чисел."),
        (3, 16, "Рекурсивные функции и мемоизация (Задание №16)", 17, 5, "Ученик сам применил functools.lru_cache при глубине стека > 2000."),
        (3, 17, "Обработка целочисленных последовательностей (Задание №17)", 14, 5, "Отличная реализация пар чисел с проверкой кратности."),
        (3, 18, "Динамика в таблицах: Робот-сборщик монет (Задание №18)", 10, 4, "Заполнили угловые и граничные ячейки с учетом стен."),
        (3, 19, "Теория игр: одна куча камней (Задания №19–21)", 7, 5, "Построили дерево игры, нашли выигрышные позиции."),
        (3, 20, "Теория игр: две кучи камней и стратегия победы (Задания №19–21)", 3, 4, "Написали рекурсивную функцию f(a, b, m). Разобрали тонкости вопроса 21."),
    ]

    now_utc = utc_now()
    created_lessons = []

    for mod_idx, les_num, topic_title, days_ago, comp_score, note in lessons_topics:
        l_date = now_utc - timedelta(days=days_ago, hours=14)
        les = Lesson.query.filter_by(
            learning_trajectory_id=trajectory.course_id,
            course_order_index=les_num
        ).first()

        if not les:
            les = Lesson(
                student_id=student.student_id,
                learning_trajectory_id=trajectory.course_id,
                course_module_id=modules_map[mod_idx].module_id,
                exam_course_id=ege_course.id,
                topic=topic_title,
                course_order_index=les_num,
                duration=60,
                status='completed',
                lesson_format='Теория + Практика',
                lesson_date=l_date,
                started_at=l_date,
                published_at=l_date - timedelta(days=1),
                homework_status='graded',
                homework_result_percent=comp_score * 20,
                created_at=l_date - timedelta(days=2),
            )
            db.session.add(les)
            db.session.flush()

            # Итоги занятия (LessonOutcome)
            outcome = LessonOutcome(
                lesson_id=les.lesson_id,
                comprehension_score=comp_score,
                independence_level='high' if comp_score == 5 else 'medium',
                pacing='optimal',
                teacher_note=note,
                homework_assigned=True,
                created_by_user_id=tutor.id,
                created_at=l_date + timedelta(hours=1),
            )
            db.session.add(outcome)

            # Привязка задания домашки к уроку (LessonTask)
            t_sample = get_task_for_number(les_num if les_num <= 20 else 17, tutor.id, ege_course.id)
            lt = LessonTask(
                lesson_id=les.lesson_id,
                task_id=t_sample.task_id,
                assignment_type='homework',
                status='graded',
                submission_correct=(comp_score >= 4),
                student_answer="42",
                teacher_comment="Отличное решение!" if comp_score == 5 else "Обрати внимание на оформление кода.",
                date_assigned=l_date,
            )
            db.session.add(lt)

            # Элемент программы (LearningItem)
            item = LearningItem(
                course_id=trajectory.course_id,
                module_id=modules_map[mod_idx].module_id,
                lesson_id=les.lesson_id,
                item_type='lesson',
                title=les.topic,
                status='completed',
                order_index=les.course_order_index,
                created_at=l_date,
            )
            db.session.add(item)
        created_lessons.append(les)

    # 2 Будущих запланированных урока
    upcoming_specs = [
        (4, 21, "Обработка строк и алгоритмы поиска подстрок (Задание №24)", 3),
        (4, 22, "Обработка больших массивов данных и жадные алгоритмы (Задание №26)", 6),
    ]
    for mod_idx, les_num, topic_title, days_ahead in upcoming_specs:
        u_date = now_utc + timedelta(days=days_ahead, hours=15)
        les = Lesson.query.filter_by(
            learning_trajectory_id=trajectory.course_id,
            course_order_index=les_num
        ).first()
        if not les:
            les = Lesson(
                student_id=student.student_id,
                learning_trajectory_id=trajectory.course_id,
                course_module_id=modules_map[mod_idx].module_id,
                exam_course_id=ege_course.id,
                topic=topic_title,
                course_order_index=les_num,
                duration=60,
                status='planned',
                lesson_format='Практикум',
                lesson_date=u_date,
                created_at=now_utc,
            )
            db.session.add(les)
            db.session.flush()

            item = LearningItem(
                course_id=trajectory.course_id,
                module_id=modules_map[mod_idx].module_id,
                lesson_id=les.lesson_id,
                item_type='lesson',
                title=les.topic,
                status='planned',
                order_index=les.course_order_index,
                created_at=now_utc,
            )
            db.session.add(item)

    db.session.commit()
    print("✓ Созданы 20 проведенных уроков с итогами (LessonOutcome) и 2 запланированных урока")

    # 8. Создание 6 разноплановых домашних работ и срезов
    assignments_data = [
        {
            'title': "ДЗ №1: Графы и логика (КЕГЭ №1, №2)",
            'type': "homework",
            'days_ago': 65,
            'tasks': [1, 2],
            'answers': [("54", True, 1), ("yxzw", True, 1)],
            'status': "GRADED",
            'teacher_feedback': "Прекрасная работа, перебор истинности написан очень чисто!",
            'student_code': "print('x y z w')\nfor x in 0,1:\n  for y in 0,1:\n    for z in 0,1:\n      for w in 0,1:\n        if (x == y) or ((not x and z) and w):\n          print(x, y, z, w)",
        },
        {
            'title': "ДЗ №2: Кодирование информации и комбинаторика (КЕГЭ №4, №8)",
            'type': "homework",
            'days_ago': 45,
            'tasks': [4, 8],
            'answers': [("011", True, 1), ("1562", False, 0)],
            'status': "GRADED",
            'teacher_feedback': "В 8 задаче не учел, что нумерация списка начинается с 1, а не с 0. Добавил подробный комментарий.",
            'student_code': "from itertools import product\nwords = list(product('АПРСУ', repeat=5))\n# Ошибка: забыл + 1 к index\nprint(words.index(('Р', 'У', 'П', 'О', 'Р')))",
        },
        {
            'title': "ДЗ №3: Программирование последовательностей (КЕГЭ №17)",
            'type': "homework",
            'days_ago': 18,
            'tasks': [17],
            'answers': [("245 89201", True, 2)],
            'status': "GRADED",
            'teacher_feedback': "Идеальная реализация генератора пар, отличное понимание работы с файлами.",
            'student_code': "with open('17.txt') as f:\n    nums = [int(x) for x in f]\nmx = max(x for x in nums if x % 13 == 0)\nres = []\nfor i in range(len(nums) - 1):\n    if (nums[i] % 13 == 0 or nums[i+1] % 13 == 0) and (nums[i] + nums[i+1] < mx):\n        res.append(nums[i] + nums[i+1])\nprint(len(res), max(res))",
        },
        {
            'title': "ДЗ №4: Теория игр на Python (КЕГЭ №19, №20, №21)",
            'type': "homework",
            'days_ago': 9,
            'tasks': [19, 20, 21],
            'answers': [("18", True, 1), ("24 35", True, 1), ("31", False, 0)],
            'status': "GRADED",
            'teacher_feedback': "В задаче 21 не учел ход с удвоением камней противника. Разобрали на занятии.",
            'student_code': "def f(s, m):\n    if s >= 55: return m % 2 == 0\n    if m == 0: return False\n    h = [f(s + 1, m - 1), f(s * 2, m - 1)]\n    return any(h) if m % 2 != 0 else all(h)\n\nprint('19:', [s for s in range(1, 55) if f(s, 2)])\nprint('20:', [s for s in range(1, 55) if not f(s, 1) and f(s, 3)])",
        },
        {
            'title': "Пробный экзамен №1 (КЕГЭ Срез знаний)",
            'type': "exam",
            'days_ago': 5,
            'tasks': [1, 2, 4, 8, 14, 16, 17, 19, 20, 21, 24],
            'answers': [
                ("54", True, 1), ("yxzw", True, 1), ("011", True, 1), ("1563", True, 1),
                ("13", True, 1), ("2026", True, 1), ("245 89201", True, 2),
                ("18", True, 1), ("24 35", True, 1), ("33", True, 1),
                ("142", False, 0),
            ],
            'status': "GRADED",
            'teacher_feedback': "Великолепный срез! 23 первичных балла из 27 (88 вторичных). 24 задание не справилось с длинной цепочкой символов, подтянем в модуле 4.",
            'student_code': "s = open('24.txt').readline()\ns = s.replace('XYZ', ' ')\nprint(max(len(c) for c in s.split()))",
        },
        {
            'title': "ДЗ №5: Поиск подстрок и регулярные выражения (КЕГЭ №24)",
            'type': "homework",
            'days_ago': 1,
            'tasks': [24],
            'answers': [("389", None, None)],
            'status': "SUBMITTED",
            'teacher_feedback': None,
            'student_code': "with open('24.txt') as f:\n    s = f.read().strip()\n# Поиск максимальной длины цепочки без 'XYZ'\ncur = mx = 0\nfor i in range(len(s)):\n    if s[i:i+3] == 'XYZ':\n        cur = 0\n    else:\n        cur += 1\n        mx = max(mx, cur)\nprint(mx)",
        },
    ]

    for a_info in assignments_data:
        existing_assign = Assignment.query.filter_by(
            title=a_info['title'],
            created_by_id=tutor.id,
        ).first()

        if existing_assign:
            continue

        assign_dt = now_utc - timedelta(days=a_info['days_ago'])
        assign = Assignment(
            title=a_info['title'],
            assignment_type=a_info['type'],
            created_by_id=tutor.id,
            exam_course_id=ege_course.id,
            deadline=assign_dt + timedelta(days=5),
            is_active=True,
            created_at=assign_dt,
            updated_at=assign_dt,
        )
        db.session.add(assign)
        db.session.flush()

        at_list = []
        for idx, tnum in enumerate(a_info['tasks']):
            t_obj = get_task_for_number(tnum, tutor.id, ege_course.id)
            at = AssignmentTask(
                assignment_id=assign.assignment_id,
                task_id=t_obj.task_id,
                order_index=idx,
                max_score=t_obj.max_score or 1,
                created_at=assign_dt,
            )
            db.session.add(at)
            db.session.flush()
            at_list.append(at)

        # Сдача работы (Submission)
        sub_status = a_info['status']
        tot_score = sum(ans[2] for ans in a_info['answers'] if ans[2] is not None) if sub_status == 'GRADED' else None
        max_sc = sum(at.max_score for at in at_list)
        pct = round((tot_score / max_sc) * 100, 1) if (tot_score is not None and max_sc > 0) else None

        sub = Submission(
            assignment_id=assign.assignment_id,
            student_id=student.student_id,
            status=sub_status,
            assigned_at=assign_dt,
            started_at=assign_dt + timedelta(hours=2),
            submitted_at=assign_dt + timedelta(hours=4),
            graded_at=(assign_dt + timedelta(hours=6)) if sub_status == 'GRADED' else None,
            total_score=tot_score,
            max_score=max_sc,
            percentage=pct,
            teacher_feedback=a_info['teacher_feedback'],
            created_at=assign_dt,
            updated_at=assign_dt + timedelta(hours=6),
        )
        db.session.add(sub)
        db.session.flush()

        # Ответы ученика (Answers)
        for idx, (ans_val, is_corr, sc) in enumerate(a_info['answers']):
            target_at = at_list[idx]
            ans = Answer(
                submission_id=sub.submission_id,
                assignment_task_id=target_at.assignment_task_id,
                value=ans_val,
                is_correct=is_corr,
                score=sc,
                max_score=target_at.max_score,
                student_code=a_info.get('student_code'),
                student_code_saved_at=assign_dt + timedelta(hours=3),
                teacher_comment="Верно!" if is_corr else ("Нужно исправить" if is_corr is False else None),
                reviewed_at=(assign_dt + timedelta(hours=6)) if sub_status == 'GRADED' else None,
                created_at=assign_dt + timedelta(hours=3),
            )
            db.session.add(ans)
            db.session.flush()

            # Если задача с кодом — добавляем снапшот и воспроизведение ввода
            if a_info.get('student_code') and idx == 0:
                cwv = CodeWorkspaceVersion(
                    context_type="submission_task",
                    context_id=sub.submission_id,
                    student_user_id=user.id,
                    student_id=student.student_id,
                    task_id=target_at.task_id,
                    answer_id=ans.answer_id,
                    code=a_info['student_code'],
                    created_at=assign_dt + timedelta(hours=3),
                )
                db.session.add(cwv)

                frames = [
                    {"ts": 100, "code": "# Решение задачи на Python\n", "caret": [27, 27], "action": "type"},
                    {"ts": 300, "code": a_info['student_code'][:30], "caret": [30, 30], "action": "type"},
                    {"ts": 600, "code": a_info['student_code'], "caret": [len(a_info['student_code']), len(a_info['student_code'])], "action": "type"},
                ]
                cpt = CodePlaybackTrace(
                    context_type="submission_task",
                    context_id=sub.submission_id,
                    student_user_id=user.id,
                    student_id=student.student_id,
                    task_id=target_at.task_id,
                    answer_id=ans.answer_id,
                    frames=frames,
                    created_at=assign_dt + timedelta(hours=3),
                )
                db.session.add(cpt)

                # Комментарий преподавателя к коду
                comm_text = "Код написан аккуратно и легко читается." if is_corr else "Обрати внимание на условие остановки цикла."
                comm = SubmissionComment(
                    submission_id=sub.submission_id,
                    author_id=tutor.id,
                    assignment_task_id=target_at.assignment_task_id,
                    text=comm_text,
                    is_read=True,
                    created_at=assign_dt + timedelta(hours=6),
                )
                db.session.add(comm)

    db.session.commit()
    print("✓ Созданы 6 разнообразных домашних заданий и срезов (с кодом и проверками)")

    # 9. Заполнение статистики по номерам КЕГЭ (StudentTaskStatistics, номера 1-27)
    # Имитируем реальный прогресс сильного ученика
    task_accuracy = {
        1: (15, 1), 2: (12, 1), 3: (10, 0), 4: (14, 1), 5: (11, 2),
        6: (9, 0), 7: (8, 2), 8: (15, 3), 9: (10, 1), 10: (8, 0),
        11: (12, 1), 12: (14, 0), 13: (9, 1), 14: (13, 1), 15: (10, 3),
        16: (12, 0), 17: (14, 2), 18: (9, 2), 19: (8, 1), 20: (7, 1),
        21: (6, 2), 22: (5, 1), 23: (8, 2), 24: (6, 4), 25: (7, 2),
        26: (5, 3), 27: (2, 4),
    }

    for tnum, (cor, incor) in task_accuracy.items():
        stat = StudentTaskStatistics.query.filter_by(
            student_id=student.student_id,
            course_id=ege_course.id,
            task_number=tnum,
        ).first()

        if not stat:
            stat = StudentTaskStatistics(
                student_id=student.student_id,
                course_id=ege_course.id,
                task_number=tnum,
                manual_correct=cor,
                manual_incorrect=incor,
                created_at=moscow_now() - timedelta(days=60),
                updated_at=moscow_now(),
            )
            db.session.add(stat)
        else:
            stat.manual_correct = cor
            stat.manual_incorrect = incor

    # 10. Диагностические срезы динамики роста (StudentDiagnosticCheckpoint)
    checkpoints_specs = [
        ('baseline', "Входное диагностическое тестирование (Сентябрь): 62 балла. Выявлены пробелы в комбинаторике и программировании.", 62, 75),
        ('checkpoint', "Промежуточный срез после 10 занятий: 76 баллов. Уверенно решает номера 1–14, автоматизировал задачи на перебор.", 76, 38),
        ('checkpoint', "Контрольный пробный срез после 20 занятий: 88 баллов. Освоены задачи 15–23, теория игр и динамика.", 88, 5),
    ]

    for kind, note, score, days_ago in checkpoints_specs:
        cp = StudentDiagnosticCheckpoint.query.filter_by(
            student_id=student.student_id,
            note=note,
        ).first()
        if not cp:
            cp = StudentDiagnosticCheckpoint(
                student_id=student.student_id,
                created_by_user_id=tutor.id,
                kind=kind,
                note=note,
                metrics={'primary_score': int(score / 3.3), 'test_score': score, 'completion_rate': 0.88},
                problem_topics=["Динамическое программирование", "Обработка подстрок"] if score < 80 else ["Задача 27"],
                recommendations=["Закрепить решение №26 и №27 на реальных файлах КЕГЭ"],
                created_at=moscow_now() - timedelta(days=days_ago),
            )
            db.session.add(cp)

    # 11. Награды и достижения (UserAchievement)
    demo_achievements = [
        ('first_submission', 70),
        ('streak_7', 50),
        ('streak_14', 20),
        ('homework_master_5', 40),
        ('python_coder', 60),
        ('lvl_5', 30),
        ('xp_1000', 45),
        ('probnik_pass', 5),
        ('ide_run_shortcut', 65),
        ('speed_solve', 15),
    ]

    for ach_key, days_ago in demo_achievements:
        ach = UserAchievement.query.filter_by(
            student_id=student.student_id,
            achievement_key=ach_key,
        ).first()
        if not ach:
            ach = UserAchievement(
                student_id=student.student_id,
                achievement_key=ach_key,
                unlocked_at=moscow_now() - timedelta(days=days_ago),
            )
            db.session.add(ach)

    db.session.commit()

    print("=" * 70)
    print("🎉 ДЕМОНСТРАЦИОННЫЙ УЧЕНИК УСПЕШНО СОЗДАН И ЗАПОЛНЕН ДАННЫМИ!")
    print("=" * 70)
    print(f"👤 Логин ученика:     {user.username}")
    print(f"🔑 Пароль ученика:    {password}")
    print(f"🎓 Имя ученика:       {student.name}")
    print(f"⭐ Уровень / XP:      Уровень {student.level} ({student.xp} XP), стрик {student.streak_days} дней")
    print(f"📚 Проведено уроков:  20 уроков (завершены с оценками и заметками)")
    print(f"📅 Будущие уроки:     2 запланированных урока на следующую неделю")
    print(f"📝 Домашние работы:   6 заданий (4 проверенных с код-ревью, 1 пробник 88 баллов, 1 ожидает проверки)")
    print(f"📊 Статистика:        Все 27 номеров КЕГЭ (~140 решенных задач)")
    print(f"📈 Контрольные срезы: 62 балла -> 76 баллов -> 88 баллов")
    print(f"🏆 Достижения:        10 разблокированных наград в профиле")
    print(f"👨‍👩‍👧 Родительский вход: demo_parent (пароль: 123)")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Сидирование демонстрационного ученика для показов BooStudy")
    parser.add_argument("--username", default="demo_student", help="Имя пользователя ученика (default: demo_student)")
    parser.add_argument("--password", default="123", help="Пароль для входа (default: 123)")
    parser.add_argument("--tutor", default=None, help="Имя пользователя преподавателя для привязки")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        ensure_schema_columns(app)
        seed_demo_student(
            username=args.username,
            password=args.password,
            tutor_username=args.tutor,
        )


if __name__ == "__main__":
    main()
