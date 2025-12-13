"""
Скрипт для поиска дубликатов уроков в базе данных
Находит уроки с одинаковым студентом и датой (день), независимо от времени
"""
import sys
import os
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import Lesson, Student

def get_lesson_fill_score(lesson):
    """
    Вычисляет "оценку заполненности" урока
    Чем больше заполнено полей, тем выше оценка
    
    Returns:
        int: Оценка заполненности (0-100)
    """
    score = 0
    
    # Статус урока (важнее всего)
    if lesson.status == 'completed':
        score += 40
    elif lesson.status == 'in_progress':
        score += 20
    elif lesson.status == 'planned':
        score += 5
    
    # Тема урока
    if lesson.topic and lesson.topic.strip():
        score += 15
    
    # Заметки
    if lesson.notes and lesson.notes.strip():
        score += 15
    
    # Домашнее задание
    if lesson.homework and lesson.homework.strip():
        score += 15
    
    # Статус ДЗ
    if lesson.homework_status and lesson.homework_status != 'not_assigned':
        score += 10
    
    # Результаты автопроверки
    if lesson.homework_result_percent is not None:
        score += 5
    
    return score

def find_duplicate_lessons(dry_run=True, same_day_only=True):
    """
    Находит дубликаты уроков
    
    Args:
        dry_run: Если True, только показывает дубликаты, не удаляет их
        same_day_only: Если True, ищет дубликаты только в один день, иначе в пределах ±3 часов
    """
    app = create_app()
    
    with app.app_context():
        # Получаем все уроки, отсортированные по студенту и дате
        lessons = Lesson.query.order_by(Lesson.student_id, Lesson.lesson_date).all()
        
        duplicates = []
        seen = {}  # {(student_id, lesson_date_normalized): [lesson_ids]}
        
        for lesson in lessons:
            # Нормализуем дату до дня для поиска дубликатов
            # Считаем дубликатами уроки одного студента в один день
            lesson_date_normalized = lesson.lesson_date.date()
            
            key = (lesson.student_id, lesson_date_normalized)
            
            if key not in seen:
                seen[key] = []
            seen[key].append(lesson)
        
        # Находим дубликаты (больше одного урока на ключ)
        for key, lesson_list in seen.items():
            if len(lesson_list) > 1:
                student_id, lesson_date = key
                student = Student.query.get(student_id)
                student_name = student.name if student else f"ID {student_id}"
                
                # Если same_day_only=False, дополнительно фильтруем по времени (в пределах ±3 часов)
                if not same_day_only:
                    filtered_lessons = []
                    for lesson in lesson_list:
                        # Проверяем, есть ли другие уроки в пределах ±3 часов
                        has_nearby = False
                        for other_lesson in lesson_list:
                            if other_lesson.lesson_id != lesson.lesson_id:
                                time_diff = abs((lesson.lesson_date - other_lesson.lesson_date).total_seconds() / 3600)
                                if time_diff <= 3:
                                    has_nearby = True
                                    break
                        if has_nearby:
                            filtered_lessons.append(lesson)
                    
                    if len(filtered_lessons) > 1:
                        lesson_list = filtered_lessons
                    else:
                        continue
                
                duplicates.append({
                    'student_id': student_id,
                    'student_name': student_name,
                    'lesson_date': lesson_date,
                    'lessons': lesson_list,
                    'count': len(lesson_list)
                })
        
        # Выводим результаты
        if duplicates:
            print(f"\n🔍 Найдено {len(duplicates)} групп дубликатов:\n")
            
            total_duplicates = 0
            for dup in duplicates:
                print(f"👤 Студент: {dup['student_name']} (ID: {dup['student_id']})")
                print(f"   📅 Дата: {dup['lesson_date']}")
                print(f"   📚 Количество дубликатов: {dup['count']}")
                print(f"   🆔 ID уроков: {[l.lesson_id for l in dup['lessons']]}")
                print(f"   ⏰ Время уроков: {[l.lesson_date.strftime('%Y-%m-%d %H:%M') for l in dup['lessons']]}")
                print(f"   📊 Статусы: {[l.status for l in dup['lessons']]}")
                print()
                
                # Определяем, какой урок оставить
                # Приоритет: более заполненный урок (с большим fill_score)
                if not dry_run:
                    # Вычисляем оценку заполненности для каждого урока
                    lessons_with_scores = []
                    for lesson in dup['lessons']:
                        fill_score = get_lesson_fill_score(lesson)
                        lessons_with_scores.append((lesson, fill_score))
                    
                    # Сортируем по fill_score (убывание), затем по lesson_id (убывание) как запасной вариант
                    lessons_with_scores.sort(key=lambda x: (x[1], x[0].lesson_id), reverse=True)
                    
                    keep_lesson, keep_score = lessons_with_scores[0]
                    to_delete = [l for l, _ in lessons_with_scores[1:]]
                    
                    print(f"   ✅ Оставляем урок ID: {keep_lesson.lesson_id} (оценка заполненности: {keep_score})")
                    print(f"      Время: {keep_lesson.lesson_date.strftime('%Y-%m-%d %H:%M')}")
                    print(f"      Статус: {keep_lesson.status}")
                    print(f"      Тема: {keep_lesson.topic or 'нет'}")
                    print(f"   ❌ Удаляем уроки:")
                    for lesson, score in lessons_with_scores[1:]:
                        print(f"      ID: {lesson.lesson_id} (оценка: {score}, время: {lesson.lesson_date.strftime('%Y-%m-%d %H:%M')}, статус: {lesson.status})")
                    
                    for lesson in to_delete:
                        db.session.delete(lesson)
                        total_duplicates += 1
                
                print("-" * 60)
            
            if not dry_run:
                try:
                    db.session.commit()
                    print(f"\n✅ Успешно удалено {total_duplicates} дубликатов уроков")
                except Exception as e:
                    db.session.rollback()
                    print(f"\n❌ Ошибка при удалении дубликатов: {e}")
            else:
                print(f"\n⚠️  Режим dry-run: дубликаты не удалены")
                print(f"   Для удаления запустите скрипт с параметром --no-dry-run")
        else:
            print("\n✅ Дубликатов не найдено")

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Поиск и удаление дубликатов уроков')
    parser.add_argument('--no-dry-run', action='store_true', help='Реально удалить дубликаты (по умолчанию только показывать)')
    parser.add_argument('--time-window', action='store_true', help='Искать дубликаты в пределах ±3 часов, а не только в один день')
    args = parser.parse_args()
    
    find_duplicate_lessons(dry_run=not args.no_dry_run, same_day_only=not args.time_window)

