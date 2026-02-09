"""
Скрипт для пересчета статистики выполнения заданий для всех учеников.

Проблема: статистика учитывает только задания с submission_correct is not None,
но некоторые задания могут иметь student_submission или student_answer без submission_correct.

Этот скрипт:
1. Находит все задания с ответами, но без submission_correct
2. Пересчитывает submission_correct для таких заданий
3. Выводит статистику до и после исправления
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from app.models import Student, Lesson, LessonTask, Tasks
from app.lessons.utils import normalize_answer_value

def recalculate_submission_correct(lesson_task):
    """
    Пересчитывает submission_correct для задания на основе student_submission/student_answer
    Использует ту же логику, что и perform_auto_check
    """
    student_value = lesson_task.student_submission or lesson_task.student_answer
    if not student_value:
        return None
    
    student_text = str(student_value).strip()
    
    is_skip = student_text == '' or student_text == '-1' or student_text.lower() == 'null'
    if is_skip:
        return False
    
    expected_text = (lesson_task.student_answer if lesson_task.student_answer else 
                     (lesson_task.task.answer if lesson_task.task and lesson_task.task.answer else '')) or ''
    
    if not expected_text:
        return False
    
    normalized_student = normalize_answer_value(student_text)
    normalized_expected = normalize_answer_value(expected_text)
    
    is_correct = normalized_student == normalized_expected and normalized_expected != ''
    return is_correct

def collect_statistics(student_id=None, fix_tasks=False):
    """
    Собирает статистику для ученика(ов) по всем типам заданий
    fix_tasks: если True, пересчитывает submission_correct для заданий без него
    Возвращает словарь с данными статистики
    """
    stats = {}
    
    if student_id:
        students = [Student.query.get(student_id)]
        if not students[0]:
            return None
    else:
        students = Student.query.filter_by(is_active=True).all()
    
    for student in students:
        student_stats = {
            'student_id': student.student_id,
            'student_name': student.name,
            'task_stats': {},
            'total_tasks': 0,
            'tasks_with_submission': 0,
            'tasks_with_correct': 0,
            'tasks_fixed': 0
        }
        
        lessons = Lesson.query.filter_by(student_id=student.student_id).options(
            db.joinedload(Lesson.homework_tasks).joinedload(LessonTask.task)
        ).all()
        
        for lesson in lessons:
            for assignment_type in ['homework', 'classwork', 'exam']:
                if assignment_type == 'homework':
                    assignments = lesson.homework_assignments
                elif assignment_type == 'classwork':
                    assignments = lesson.classwork_assignments
                elif assignment_type == 'exam':
                    assignments = lesson.exam_assignments
                else:
                    assignments = lesson.homework_assignments
                
                weight = 2 if assignment_type == 'exam' else 1
                
                for lt in assignments:
                    if not lt.task or not lt.task.task_number:
                        continue
                    
                    task_num = lt.task.task_number
                    student_stats['total_tasks'] += 1
                    
                    if task_num not in student_stats['task_stats']:
                        student_stats['task_stats'][task_num] = {
                            'correct': 0, 
                            'total': 0,
                            'before_correct': 0,
                            'before_total': 0
                        }
                    
                    has_submission = bool(lt.student_submission or lt.student_answer)
                    if has_submission:
                        student_stats['tasks_with_submission'] += 1
                    
                    if lt.submission_correct is not None:
                        student_stats['task_stats'][task_num]['before_total'] += weight
                        if lt.submission_correct:
                            student_stats['task_stats'][task_num]['before_correct'] += weight
                    
                    if fix_tasks and has_submission and lt.submission_correct is None:
                        new_correct = recalculate_submission_correct(lt)
                        if new_correct is not None:
                            lt.submission_correct = new_correct
                            student_stats['tasks_fixed'] += 1
                    
                    if lt.submission_correct is not None:
                        student_stats['task_stats'][task_num]['total'] += weight
                        if lt.submission_correct:
                            student_stats['task_stats'][task_num]['correct'] += weight
                            student_stats['tasks_with_correct'] += 1
        
        stats[student.student_id] = student_stats
    
    return stats

def print_statistics(stats, before_commit=True):
    """Выводит статистику в консоль"""
    prefix = "ДО" if before_commit else "ПОСЛЕ"
    
    for student_id, student_stats in stats.items():
        print(f"\n{'='*80}")
        print(f"Ученик: {student_stats['student_name']} (ID: {student_id})")
        print(f"{'='*80}")
        
        if before_commit:
            print(f"Всего заданий: {student_stats['total_tasks']}")
            print(f"Заданий с ответами: {student_stats['tasks_with_submission']}")
            print(f"Заданий с submission_correct (ДО): {sum(s['before_total'] for s in student_stats['task_stats'].values())}")
            print(f"Исправлено заданий: {student_stats['tasks_fixed']}")
        else:
            print(f"Заданий с submission_correct (ПОСЛЕ): {sum(s['total'] for s in student_stats['task_stats'].values())}")
        
        print(f"\nСтатистика по номерам заданий ({prefix}):")
        print(f"{'Номер':<8} {'Правильно':<12} {'Всего':<8} {'Процент':<10}")
        print("-" * 40)
        
        for task_num in sorted(student_stats['task_stats'].keys()):
            if before_commit:
                correct = student_stats['task_stats'][task_num]['before_correct']
                total = student_stats['task_stats'][task_num]['before_total']
            else:
                correct = student_stats['task_stats'][task_num]['correct']
                total = student_stats['task_stats'][task_num]['total']
            
            if total > 0:
                percent = round((correct / total) * 100, 1)
                print(f"{task_num:<8} {correct:<12} {total:<8} {percent}%")
        
        print()

def main():
    """Основная функция"""
    app = create_app()
    
    with app.app_context():
        print("="*80)
        print("ПЕРЕСЧЕТ СТАТИСТИКИ ВЫПОЛНЕНИЯ ЗАДАНИЙ")
        print("="*80)
        
        print("\n📊 Сбор статистики ДО исправления...")
        stats_before = collect_statistics(fix_tasks=False)
        
        if not stats_before:
            print("❌ Не найдено активных учеников")
            return
        
        print_statistics(stats_before, before_commit=True)
        
        print("\n🔧 Пересчет submission_correct для заданий с ответами...")
        stats_fixed = collect_statistics(fix_tasks=True)
        
        if not stats_fixed:
            print("❌ Ошибка при пересчете")
            return
        
        print("\n💾 Сохранение изменений в базу данных...")
        try:
            db.session.commit()
            print("✅ Изменения успешно сохранены")
        except Exception as e:
            db.session.rollback()
            print(f"❌ Ошибка при сохранении: {e}")
            return
        
        print("\n📊 Сбор статистики ПОСЛЕ исправления...")
        stats_after = collect_statistics(fix_tasks=False)
        
        print_statistics(stats_after, before_commit=False)
        
        print("\n" + "="*80)
        print("СВОДКА")
        print("="*80)
        total_fixed = sum(s['tasks_fixed'] for s in stats_fixed.values())
        total_students = len(stats_before)
        print(f"Всего учеников обработано: {total_students}")
        print(f"Всего заданий исправлено: {total_fixed}")
        
        if total_fixed > 0:
            print("\nТоп-10 учеников с наибольшим количеством исправлений:")
            sorted_students = sorted(
                stats_fixed.items(), 
                key=lambda x: x[1]['tasks_fixed'], 
                reverse=True
            )[:10]
            for student_id, student_stats in sorted_students:
                if student_stats['tasks_fixed'] > 0:
                    print(f"  {student_stats['student_name']}: {student_stats['tasks_fixed']} заданий")
        
        print("\n✅ Пересчет статистики завершен!")

if __name__ == '__main__':
    main()

