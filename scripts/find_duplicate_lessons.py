"""
Скрипт для поиска дубликатов уроков в базе данных
Находит уроки с одинаковым студентом и временем (с допуском 5 минут)
"""
import sys
import os
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import Lesson, Student

def find_duplicate_lessons(dry_run=True):
    """
    Находит дубликаты уроков
    
    Args:
        dry_run: Если True, только показывает дубликаты, не удаляет их
    """
    app = create_app()
    
    with app.app_context():
        # Получаем все уроки, отсортированные по студенту и дате
        lessons = Lesson.query.order_by(Lesson.student_id, Lesson.lesson_date).all()
        
        duplicates = []
        seen = {}  # {(student_id, lesson_date_normalized): [lesson_ids]}
        
        for lesson in lessons:
            # Нормализуем дату до 5-минутных интервалов для поиска дубликатов
            lesson_date_normalized = lesson.lesson_date.replace(
                minute=(lesson.lesson_date.minute // 5) * 5,
                second=0,
                microsecond=0
            )
            
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
                
                # Предлагаем оставить самый новый урок (с наибольшим lesson_id)
                if not dry_run:
                    # Сортируем по lesson_id (предполагаем, что больший ID = более новый)
                    sorted_lessons = sorted(dup['lessons'], key=lambda x: x.lesson_id, reverse=True)
                    keep_lesson = sorted_lessons[0]
                    to_delete = sorted_lessons[1:]
                    
                    print(f"   ✅ Оставляем урок ID: {keep_lesson.lesson_id}")
                    print(f"   ❌ Удаляем уроки: {[l.lesson_id for l in to_delete]}")
                    
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
    args = parser.parse_args()
    
    find_duplicate_lessons(dry_run=not args.no_dry_run)

