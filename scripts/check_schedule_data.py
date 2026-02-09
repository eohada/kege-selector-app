"""
Скрипт для диагностики проблем с расписанием
Проверяет данные уроков и выявляет возможные проблемы
"""
import sys
import os
from datetime import datetime, timedelta, time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import Lesson, Student, MOSCOW_TZ, TOMSK_TZ

def check_schedule_data():
    """Проверяет данные уроков на проблемы"""
    app = create_app()
    
    with app.app_context():
        today = datetime.now(MOSCOW_TZ).date()
        current_week_start = today - timedelta(days=today.weekday())
        
        week_start = current_week_start - timedelta(weeks=2)
        week_end = current_week_start + timedelta(days=6)  # До конца текущей недели
        
        week_start_datetime = datetime.combine(week_start, time.min)
        week_end_datetime = datetime.combine(week_end, time.max)
        
        print(f"📅 Проверяем период: {week_start} - {week_end} (3 недели)\n")
        
        lessons = Lesson.query.filter(
            Lesson.lesson_date >= week_start_datetime,
            Lesson.lesson_date < week_end_datetime + timedelta(days=1)
        ).options(db.joinedload(Lesson.student)).order_by(Lesson.lesson_date).all()
        
        print(f"📚 Всего уроков за неделю: {len(lessons)}\n")
        
        lessons_by_day = defaultdict(list)
        lessons_by_student_day = defaultdict(list)
        
        for lesson in lessons:
            lesson_date = lesson.lesson_date
            if lesson_date.tzinfo is None:
                lesson_date = lesson_date.replace(tzinfo=MOSCOW_TZ)
            
            lesson_date_display = lesson_date.astimezone(MOSCOW_TZ)
            lesson_date_local = lesson_date_display.date()
            
            day_index = (lesson_date_local - week_start).days
            
            if 0 <= day_index < 7:
                day_name = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье'][day_index]
                lessons_by_day[day_name].append(lesson)
                
                student_name = lesson.student.name if lesson.student else "Без студента"
                key = (student_name, lesson_date_local)
                lessons_by_student_day[key].append(lesson)
        
        print("📊 Уроки по дням недели:")
        for day_name in ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']:
            day_lessons = lessons_by_day[day_name]
            print(f"   {day_name}: {len(day_lessons)} уроков")
            if day_lessons:
                for lesson in day_lessons[:5]:  # Показываем первые 5
                    student_name = lesson.student.name if lesson.student else "Без студента"
                    time_str = lesson.lesson_date.strftime('%H:%M')
                    print(f"      - {time_str} | {student_name} | {lesson.status} | ID: {lesson.lesson_id}")
                if len(day_lessons) > 5:
                    print(f"      ... и еще {len(day_lessons) - 5} уроков")
        print()
        
        print("🔍 Проверка дубликатов (один студент в один день):")
        duplicates_found = False
        for (student_name, lesson_date), lesson_list in lessons_by_student_day.items():
            if len(lesson_list) > 1:
                duplicates_found = True
                print(f"\n   ⚠️  Дубликаты для {student_name} на {lesson_date}:")
                for lesson in lesson_list:
                    time_str = lesson.lesson_date.strftime('%H:%M')
                    fill_score = calculate_fill_score(lesson)
                    print(f"      - ID: {lesson.lesson_id} | {time_str} | {lesson.status} | "
                          f"Заполненность: {fill_score} | "
                          f"Тема: {lesson.topic or 'нет'} | "
                          f"ДЗ: {lesson.homework or 'нет'}")
        
        if not duplicates_found:
            print("   ✅ Дубликатов не найдено")
        print()
        
        print("👤 Проверка уроков без студентов:")
        lessons_without_student = [l for l in lessons if not l.student]
        if lessons_without_student:
            print(f"   ⚠️  Найдено {len(lessons_without_student)} уроков без студентов:")
            for lesson in lessons_without_student[:10]:
                print(f"      - ID: {lesson.lesson_id} | {lesson.lesson_date} | {lesson.status}")
            if len(lessons_without_student) > 10:
                print(f"      ... и еще {len(lessons_without_student) - 10} уроков")
        else:
            print("   ✅ Все уроки имеют студентов")
        print()
        
        print("📅 Проверка уроков вне текущей недели:")
        lessons_outside_week = []
        for lesson in lessons:
            lesson_date = lesson.lesson_date
            if lesson_date.tzinfo is None:
                lesson_date = lesson_date.replace(tzinfo=MOSCOW_TZ)
            
            lesson_date_display = lesson_date.astimezone(MOSCOW_TZ)
            lesson_date_local = lesson_date_display.date()
            day_index = (lesson_date_local - week_start).days
            
            if day_index < 0 or day_index >= 7:
                lessons_outside_week.append(lesson)
        
        if lessons_outside_week:
            print(f"   ⚠️  Найдено {len(lessons_outside_week)} уроков вне недели:")
            for lesson in lessons_outside_week[:10]:
                student_name = lesson.student.name if lesson.student else "Без студента"
                print(f"      - ID: {lesson.lesson_id} | {student_name} | {lesson.lesson_date} | day_index: {(lesson_date_local - week_start).days}")
            if len(lessons_outside_week) > 10:
                print(f"      ... и еще {len(lessons_outside_week) - 10} уроков")
        else:
            print("   ✅ Все уроки попадают в текущую неделю")
        print()

def calculate_fill_score(lesson):
    """Вычисляет оценку заполненности урока"""
    score = 0
    
    if lesson.status == 'completed':
        score += 40
    elif lesson.status == 'in_progress':
        score += 20
    elif lesson.status == 'planned':
        score += 5
    
    if lesson.topic and lesson.topic.strip():
        score += 15
    
    if lesson.notes and lesson.notes.strip():
        score += 15
    
    if lesson.homework and lesson.homework.strip():
        score += 15
    
    if lesson.homework_status and lesson.homework_status != 'not_assigned':
        score += 10
    
    if lesson.homework_result_percent is not None:
        score += 5
    
    return score

if __name__ == '__main__':
    check_schedule_data()

