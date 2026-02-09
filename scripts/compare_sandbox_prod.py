"""
Скрипт для сравнения данных между песочницей и продом
Помогает найти различия, которые могут вызывать проблемы с расписанием
"""
import sys
import os
from datetime import datetime, timedelta, time
from collections import defaultdict
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.db_models import Lesson, Student, MOSCOW_TZ

def get_db_session(database_url):
    """Создает сессию для подключения к БД"""
    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    return Session()

def compare_lessons(sandbox_url, prod_url):
    """Сравнивает уроки между песочницей и продом"""
    
    print("🔍 Сравнение данных между песочницей и продом\n")
    print("=" * 80)
    
    try:
        sandbox_session = get_db_session(sandbox_url)
        prod_session = get_db_session(prod_url)
        print("✅ Подключение к БД установлено\n")
    except Exception as e:
        print(f"❌ Ошибка подключения к БД: {e}")
        return
    
    today = datetime.now(MOSCOW_TZ).date()
    current_week_start = today - timedelta(days=today.weekday())
    
    week_start = current_week_start - timedelta(weeks=2)
    week_end = current_week_start + timedelta(days=6)  # До конца текущей недели
    
    week_start_datetime = datetime.combine(week_start, time.min)
    week_end_datetime = datetime.combine(week_end, time.max)
    
    print(f"📅 Проверяем период: {week_start} - {week_end} (3 недели)\n")
    
    sandbox_lessons = sandbox_session.query(Lesson).filter(
        Lesson.lesson_date >= week_start_datetime,
        Lesson.lesson_date < week_end_datetime + timedelta(days=1)
    ).all()
    
    prod_lessons = prod_session.query(Lesson).filter(
        Lesson.lesson_date >= week_start_datetime,
        Lesson.lesson_date < week_end_datetime + timedelta(days=1)
    ).all()
    
    print(f"📚 Песочница: {len(sandbox_lessons)} уроков")
    print(f"📚 Продакшн: {len(prod_lessons)} уроков")
    print(f"📊 Разница: {len(prod_lessons) - len(sandbox_lessons)} уроков\n")
    
    def group_lessons(lessons):
        grouped = defaultdict(list)
        for lesson in lessons:
            lesson_date = lesson.lesson_date
            if lesson_date.tzinfo is None:
                lesson_date = lesson_date.replace(tzinfo=MOSCOW_TZ)
            
            lesson_date_local = lesson_date.date()
            student_id = lesson.student_id if lesson.student_id else 0
            
            key = (student_id, lesson_date_local)
            grouped[key].append(lesson)
        return grouped
    
    sandbox_grouped = group_lessons(sandbox_lessons)
    prod_grouped = group_lessons(prod_lessons)
    
    print("🔍 Поиск различий:\n")
    
    print("1️⃣ Дубликаты в проде (один студент в один день):")
    prod_duplicates = []
    for key, lessons in prod_grouped.items():
        if len(lessons) > 1:
            student_id, lesson_date = key
            student = prod_session.query(Student).get(student_id)
            student_name = student.name if student else f"ID {student_id}"
            prod_duplicates.append((student_name, lesson_date, lessons))
    
    if prod_duplicates:
        print(f"   ⚠️  Найдено {len(prod_duplicates)} групп дубликатов в проде:")
        for student_name, lesson_date, lessons in prod_duplicates[:10]:
            print(f"      - {student_name} на {lesson_date}: {len(lessons)} уроков")
            for lesson in lessons:
                time_str = lesson.lesson_date.strftime('%H:%M')
                print(f"        ID: {lesson.lesson_id} | {time_str} | {lesson.status}")
        if len(prod_duplicates) > 10:
            print(f"      ... и еще {len(prod_duplicates) - 10} групп")
    else:
        print("   ✅ Дубликатов в проде не найдено")
    print()
    
    print("2️⃣ Дубликаты в песочнице (один студент в один день):")
    sandbox_duplicates = []
    for key, lessons in sandbox_grouped.items():
        if len(lessons) > 1:
            student_id, lesson_date = key
            student = sandbox_session.query(Student).get(student_id)
            student_name = student.name if student else f"ID {student_id}"
            sandbox_duplicates.append((student_name, lesson_date, lessons))
    
    if sandbox_duplicates:
        print(f"   ⚠️  Найдено {len(sandbox_duplicates)} групп дубликатов в песочнице")
    else:
        print("   ✅ Дубликатов в песочнице не найдено")
    print()
    
    print("3️⃣ Уроки, которые есть только в проде:")
    prod_only = []
    for key, prod_lesson_list in prod_grouped.items():
        if key not in sandbox_grouped:
            student_id, lesson_date = key
            student = prod_session.query(Student).get(student_id)
            student_name = student.name if student else f"ID {student_id}"
            prod_only.append((student_name, lesson_date, prod_lesson_list))
    
    if prod_only:
        print(f"   ⚠️  Найдено {len(prod_only)} групп уроков только в проде:")
        for student_name, lesson_date, lessons in prod_only[:10]:
            print(f"      - {student_name} на {lesson_date}: {len(lessons)} уроков")
            for lesson in lessons:
                time_str = lesson.lesson_date.strftime('%H:%M')
                print(f"        ID: {lesson.lesson_id} | {time_str} | {lesson.status}")
        if len(prod_only) > 10:
            print(f"      ... и еще {len(prod_only) - 10} групп")
    else:
        print("   ✅ Все уроки из прода есть в песочнице")
    print()
    
    print("4️⃣ Уроки с разным временем (возможные проблемы с часовыми поясами):")
    time_differences = []
    for key in set(list(sandbox_grouped.keys()) + list(prod_grouped.keys())):
        if key in sandbox_grouped and key in prod_grouped:
            sandbox_times = sorted([l.lesson_date.time() for l in sandbox_grouped[key]])
            prod_times = sorted([l.lesson_date.time() for l in prod_grouped[key]])
            
            if sandbox_times != prod_times:
                student_id, lesson_date = key
                student_sandbox = sandbox_session.query(Student).get(student_id)
                student_prod = prod_session.query(Student).get(student_id)
                student_name = student_sandbox.name if student_sandbox else (student_prod.name if student_prod else f"ID {student_id}")
                time_differences.append((student_name, lesson_date, sandbox_times, prod_times))
    
    if time_differences:
        print(f"   ⚠️  Найдено {len(time_differences)} различий во времени:")
        for student_name, lesson_date, sandbox_times, prod_times in time_differences[:10]:
            print(f"      - {student_name} на {lesson_date}:")
            print(f"        Песочница: {[t.strftime('%H:%M') for t in sandbox_times]}")
            print(f"        Продакшн: {[t.strftime('%H:%M') for t in prod_times]}")
        if len(time_differences) > 10:
            print(f"      ... и еще {len(time_differences) - 10} различий")
    else:
        print("   ✅ Время уроков совпадает")
    print()
    
    print("5️⃣ Статистика по дням недели:")
    def count_by_day(lessons):
        by_day = defaultdict(int)
        for lesson in lessons:
            lesson_date = lesson.lesson_date
            if lesson_date.tzinfo is None:
                lesson_date = lesson_date.replace(tzinfo=MOSCOW_TZ)
            day = lesson_date.date()
            by_day[day] += 1
        return by_day
    
    sandbox_by_day = count_by_day(sandbox_lessons)
    prod_by_day = count_by_day(prod_lessons)
    
    all_days = set(list(sandbox_by_day.keys()) + list(prod_by_day.keys()))
    for day in sorted(all_days):
        sandbox_count = sandbox_by_day.get(day, 0)
        prod_count = prod_by_day.get(day, 0)
        diff = prod_count - sandbox_count
        if diff != 0:
            print(f"   {day}: Песочница={sandbox_count}, Продакшн={prod_count}, Разница={diff:+d}")
    print()
    
    sandbox_session.close()
    prod_session.close()
    
    print("=" * 80)
    print("\n💡 Рекомендации:")
    if prod_duplicates:
        print("   1. Удалите дубликаты в проде: python scripts/find_duplicate_lessons.py --no-dry-run")
    if prod_only:
        print("   2. Проверьте, откуда взялись лишние уроки в проде")
    if time_differences:
        print("   3. Проверьте настройки часовых поясов и синхронизацию данных")
    if not prod_duplicates and not prod_only and not time_differences:
        print("   ✅ Значительных различий не найдено. Проблема может быть в коде или конфигурации.")

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Сравнение данных между песочницей и продом')
    parser.add_argument('--sandbox-url', required=True, help='URL БД песочницы (DATABASE_URL)')
    parser.add_argument('--prod-url', required=True, help='URL БД продакшна (DATABASE_URL)')
    
    args = parser.parse_args()
    
    compare_lessons(args.sandbox_url, args.prod_url)

