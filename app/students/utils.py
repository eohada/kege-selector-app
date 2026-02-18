"""
Вспомогательные функции для работы со студентами
"""
from app.models import Lesson, LessonTask

def get_sorted_assignments(lesson, assignment_type):
    """Получает задания в порядке добавления в урок (lesson_task_id). Тройки 19–20–21 идут подряд."""
    if assignment_type == 'homework':
        assignments = lesson.homework_assignments
    elif assignment_type == 'classwork':
        assignments = lesson.classwork_assignments
    elif assignment_type == 'exam':
        assignments = lesson.exam_assignments
    else:
        assignments = lesson.homework_assignments
    return sorted(assignments, key=lambda ht: ht.lesson_task_id)

